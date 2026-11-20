"""Sanity checks against the full 300K-row build (skipped if it hasn't been built)."""


def test_known_totals(real_client):
    s = real_client.get("/api/summary").json()
    assert s["total_records"] == 300_000
    assert s["orders"] == 110_478
    assert s["revenue"] == 69_480_952
    assert round(s["aov"]) == 629


def test_aggregators_only_on_delivery(real_client):
    params = {"dim": "settlement", "order_types": ["Dine-In", "Takeaway"]}
    rows = real_client.get("/api/breakdown", params=params).json()["rows"]
    assert {r["name"] for r in rows} == {"Cash/Card/Coupon", "Dineout"}


def test_free_items_are_dips(real_client):
    params = {"sort": "price", "order": "asc", "page_size": 200}
    rows = real_client.get("/api/records", params=params).json()["rows"]
    zero = [r for r in rows if r["price"] == 0]
    assert zero and all(r["item"].startswith("Dip - ") for r in zero)
    s = real_client.get("/api/summary").json()
    # 8,611 ₹0 rows carrying 12,543 units: rows and quantities must not be mixed up.
    assert (s["free_lines"], s["free_items"]) == (8_611, 12_543)


def test_group_filter_partitions_revenue(real_client):
    total = real_client.get("/api/summary").json()["revenue"]
    groups = real_client.get("/api/meta").json()["groups"]
    parts = sum(real_client.get("/api/summary", params={"groups": g}).json()["revenue"] for g in groups)
    assert parts == total
