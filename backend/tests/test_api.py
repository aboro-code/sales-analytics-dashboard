import csv
import io

import pytest

from conftest import TOTAL_LINES, TOTAL_ORDERS, TOTAL_QTY, TOTAL_REVENUE


def get(client, url, **params):
    r = client.get(url, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- meta / health
def test_health(client):
    body = get(client, "/health")
    assert body["status"] == "ok" and body["rows"] == TOTAL_LINES


def test_meta(client):
    m = get(client, "/api/meta")
    assert m["outlets"] == ["Koramangala", "MG Road"]
    assert m["min_date"] == "2026-02-01" and m["max_date"] == "2026-03-20"
    assert m["brands"] == ["Burger Town"]
    assert {i["item"] for i in m["items"]} == {"Burger A", "Burger B", "Coke", "Fries", "Dip - Mayo"}


# ---------------------------------------------------------------- summary
def test_summary_unfiltered(client):
    s = get(client, "/api/summary")
    assert s["total_records"] == TOTAL_LINES
    assert s["orders"] == TOTAL_ORDERS
    assert s["revenue"] == TOTAL_REVENUE
    assert s["aov"] == TOTAL_REVENUE / TOTAL_ORDERS
    assert s["items_sold"] == TOTAL_QTY
    assert s["free_items"] == 1
    assert s["top_outlet"]["name"] == "MG Road"  # 460 vs 350


def test_order_level_filter(client):
    s = get(client, "/api/summary", outlets="Koramangala")
    assert (s["orders"], s["revenue"], s["total_records"]) == (2, 350, 4)


def test_line_level_filter_semantics(client):
    # Orders = bills containing a drink; revenue = drink lines only.
    s = get(client, "/api/summary", groups="Drinks")
    assert s["orders"] == 3
    assert s["revenue"] == 200
    assert s["aov"] == round(200 / 3, 2)


def test_combined_filters_and_multi_values(client):
    s = get(client, "/api/summary", groups=["Drinks", "Sides"], order_types="Delivery")
    # bill 2 fries 160 + bill 4 coke 50
    assert (s["orders"], s["revenue"]) == (2, 210)
    # comma-separated form is equivalent
    assert get(client, "/api/summary", groups="Sides,Drinks", order_types="Delivery") == s


def test_date_range_is_inclusive(client):
    s = get(client, "/api/summary", start="2026-02-03", end="2026-03-15")
    assert (s["orders"], s["revenue"]) == (2, 360)  # bills 2 and 3


def test_empty_result(client):
    s = get(client, "/api/summary", start="2030-01-01")
    assert s["orders"] == 0 and s["revenue"] == 0 and s["aov"] == 0


@pytest.mark.parametrize("params,needle", [
    ({"outlets": "Atlantis"}, "Unknown outlets"),
    ({"groups": "Pizza"}, "Unknown groups"),
    ({"start": "2026-13-01"}, "ISO date"),
    ({"start": "2026-03-01", "end": "2026-02-01"}, "on or before"),
])
def test_validation(client, params, needle):
    r = client.get("/api/summary", params=params)
    assert r.status_code == 422 and needle in r.text


def test_sql_injection_is_rejected_not_executed(client):
    r = client.get("/api/summary", params={"outlets": "x') OR 1=1 --"})
    assert r.status_code == 422


# ---------------------------------------------------------------- charts
@pytest.mark.parametrize("granularity,periods", [
    ("day", ["2026-02-01", "2026-02-03", "2026-03-15", "2026-03-20"]),
    ("week", ["2026-01-26", "2026-02-02", "2026-03-09", "2026-03-16"]),
    ("month", ["2026-02", "2026-03"]),
])
def test_timeseries(client, granularity, periods):
    pts = get(client, "/api/timeseries", granularity=granularity)["points"]
    assert [p["period"] for p in pts] == periods
    assert sum(p["revenue"] for p in pts) == TOTAL_REVENUE
    assert sum(p["orders"] for p in pts) == TOTAL_ORDERS


def test_timeseries_bad_granularity(client):
    assert client.get("/api/timeseries", params={"granularity": "hour"}).status_code == 422


@pytest.mark.parametrize("dim", ["outlet", "group", "item", "order_type", "settlement"])
def test_breakdown_reconciles(client, dim):
    rows = get(client, "/api/breakdown", dim=dim)["rows"]
    assert sum(r["revenue"] for r in rows) == TOTAL_REVENUE
    assert abs(sum(r["share"] for r in rows) - 1) < 1e-3
    assert [r["revenue"] for r in rows] == sorted((r["revenue"] for r in rows), reverse=True)


def test_breakdown_group_orders_are_distinct_bills(client):
    rows = {r["name"]: r for r in get(client, "/api/breakdown", dim="group")["rows"]}
    assert rows["Drinks"]["orders"] == 3 and rows["Drinks"]["quantity"] == 4
    assert rows["Extras"]["revenue"] == 0 and rows["Extras"]["quantity"] == 1


def test_breakdown_limit_keeps_global_share(client):
    rows = get(client, "/api/breakdown", dim="item", limit=1)["rows"]
    assert len(rows) == 1 and rows[0]["name"] == "Burger A"  # 300
    assert rows[0]["share"] == round(300 / TOTAL_REVENUE, 4)


def test_heatmap(client):
    cells = get(client, "/api/heatmap")["cells"]
    assert sum(c["orders"] for c in cells) == TOTAL_ORDERS
    assert any(c["weekday"] == 6 and c["hour"] == 12 for c in cells)  # Sunday lunch, bill 1


def test_insights(client):
    ins = get(client, "/api/insights")["insights"]
    ids = {i["id"] for i in ins}
    assert {"top_outlet", "peak_hour", "delivery_share", "aggregator_share", "free_dips"} <= ids
    agg = next(i for i in ins if i["id"] == "aggregator_share")
    assert agg["value"] == 1.0  # both delivery bills via aggregators


def test_insights_empty(client):
    assert get(client, "/api/insights", start="2030-01-01")["insights"] == []


# ---------------------------------------------------------------- records / export
def test_records_pagination_and_sort(client):
    p1 = get(client, "/api/records", page=1, page_size=3, sort="revenue", order="desc")
    p3 = get(client, "/api/records", page=3, page_size=3, sort="revenue", order="desc")
    assert p1["total"] == TOTAL_LINES and p1["pages"] == 3
    assert [r["revenue"] for r in p1["rows"]] == [200, 160, 150]
    assert len(p3["rows"]) == 2
    assert get(client, "/api/records", sort="order_ts", order="desc")["rows"][0]["bill_no"] == 4


def test_records_rejects_unknown_sort(client):
    assert client.get("/api/records", params={"sort": "price; DROP TABLE x"}).status_code == 422
    assert client.get("/api/records", params={"page_size": 1000}).status_code == 422


def test_export_csv(client):
    r = client.get("/api/export.csv", params={"outlets": "MG Road"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 4 and {row["outlet"] for row in rows} == {"MG Road"}
    assert sum(float(row["revenue"]) for row in rows) == 460


def test_export_csv_empty_has_header(client):
    r = client.get("/api/export.csv", params={"start": "2030-01-01"})
    assert r.text.strip() == "bill_no,order_ts,outlet,item_group,item,price,quantity,revenue,order_type,settlement,brand"


# ---------------------------------------------------------------- caching / headers
def test_cache_and_timing_headers(client):
    first = client.get("/api/breakdown", params={"outlets": "MG Road", "groups": "Burgers", "dim": "item"})
    # same filters, different parameter order -> same normalised cache key
    second = client.get("/api/breakdown", params={"dim": "item", "groups": "Burgers", "outlets": "MG Road"})
    assert first.headers["X-Cache"] == "MISS" and second.headers["X-Cache"] == "HIT"
    assert float(second.headers["X-Query-Time-ms"]) >= 0
    assert first.json() == second.json()


def test_gzip(client):
    r = client.get("/api/records", params={"page_size": 200}, headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_cors(client):
    r = client.get("/api/meta", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "X-Query-Time-ms" in r.headers["access-control-expose-headers"]
