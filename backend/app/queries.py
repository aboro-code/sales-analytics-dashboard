"""
All analytical SQL lives here. Each function takes a Database and Filters and
returns plain JSON-serialisable data.

Metric definitions (used consistently everywhere):
  revenue      = Σ price × quantity of matching line items
  orders       = distinct BillNo with at least one matching line item
  AOV          = revenue / orders
  items sold   = Σ quantity of matching line items
  records      = number of matching line items (rows)
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Iterator

from .db import Database
from .filters import Filters, orders_cte, where

GRANULARITY = {"day": "order_date", "week": "week", "month": "month"}

# dimension -> (column, level). Order-level dims are answered from the orders CTE;
# line-level dims (group, item) need line_items because one order spans many groups.
DIMENSIONS = {
    "outlet": ("outlet", "order"),
    "order_type": ("order_type", "order"),
    "settlement": ("settlement", "order"),
    "group": ("item_group", "line"),
    "item": ("item", "line"),
}

RECORD_COLUMNS = [
    "bill_no", "order_ts", "outlet", "item_group", "item", "price", "quantity",
    "revenue", "order_type", "settlement", "brand",
]
SORTABLE = {
    "order_ts": "order_ts", "bill_no": "bill_no", "outlet": "outlet", "item_group": "item_group",
    "item": "item", "price": "price", "quantity": "quantity", "revenue": "revenue",
    "order_type": "order_type", "settlement": "settlement",
}


def _r(x: float | None, nd: int = 2) -> float:
    return round(float(x or 0), nd)


# --------------------------------------------------------------------------- #
def meta(db: Database) -> dict[str, Any]:
    def distinct(col: str, table: str = "line_items") -> list[str]:
        return [r[col] for r in db.all(f"SELECT DISTINCT {col} FROM {table} ORDER BY {col}")]

    rng = db.one("SELECT MIN(order_date) AS min_date, MAX(order_date) AS max_date FROM orders")
    items = db.all(
        "SELECT item, item_group, MAX(price) AS price FROM line_items GROUP BY item, item_group ORDER BY item_group, item"
    )
    info = {r["key"]: r["value"] for r in db.all("SELECT key, value FROM build_info")}
    return {
        "outlets": distinct("outlet", "orders"),
        "groups": distinct("item_group"),
        "items": items,
        "order_types": distinct("order_type", "orders"),
        "settlements": distinct("settlement", "orders"),
        "brands": distinct("brand"),
        "min_date": rng["min_date"],
        "max_date": rng["max_date"],
        "build": info,
    }


# --------------------------------------------------------------------------- #
def summary(db: Database, f: Filters) -> dict[str, Any]:
    lw, lp = where(f)
    lines = db.one(
        f"""SELECT COUNT(*) AS records, COALESCE(SUM(quantity),0) AS items_sold,
                   COALESCE(SUM(revenue),0) AS revenue,
                   SUM(CASE WHEN price = 0 THEN quantity ELSE 0 END) AS free_items,
                   COUNT(*) FILTER (WHERE price = 0) AS free_lines
            FROM line_items {lw}""",
        lp,
    )
    cte, cp = orders_cte(f)
    orders = db.one(
        f"{cte} SELECT COUNT(*) AS orders, COALESCE(SUM(order_value),0) AS revenue, "
        f"COALESCE(SUM(item_count),0) AS items, COUNT(DISTINCT order_date) AS days FROM o",
        cp,
    )
    top_outlet = db.one(
        f"{cte} SELECT outlet AS name, SUM(order_value) AS revenue FROM o GROUP BY outlet ORDER BY revenue DESC LIMIT 1",
        cp,
    )
    top_item = db.one(
        f"SELECT item AS name, SUM(revenue) AS revenue, SUM(quantity) AS quantity FROM line_items {lw} "
        f"GROUP BY item ORDER BY revenue DESC LIMIT 1",
        lp,
    )
    n = orders["orders"] or 0
    rev = lines["revenue"] or 0
    return {
        "total_records": lines["records"],
        "orders": n,
        "revenue": _r(rev),
        "aov": _r(rev / n) if n else 0,
        "items_sold": lines["items_sold"],
        "avg_items_per_order": _r(orders["items"] / n) if n else 0,
        "free_items": lines["free_items"] or 0,  # units handed out at ₹0 (quantity)
        "free_lines": lines["free_lines"] or 0,  # ₹0 rows
        "active_days": orders["days"],
        "avg_daily_revenue": _r(rev / orders["days"]) if orders["days"] else 0,
        "top_outlet": {"name": top_outlet.get("name"), "revenue": _r(top_outlet.get("revenue"))} if top_outlet else None,
        "top_item": {"name": top_item.get("name"), "revenue": _r(top_item.get("revenue")), "quantity": top_item.get("quantity")} if top_item else None,
    }


# --------------------------------------------------------------------------- #
def _period_bounds(period: str, granularity: str) -> tuple[date, date]:
    if granularity == "day":
        d = date.fromisoformat(period)
        return d, d
    if granularity == "week":
        d = date.fromisoformat(period)
        return d, d + timedelta(days=6)
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def timeseries(db: Database, f: Filters, granularity: str) -> list[dict[str, Any]]:
    """
    Points per period. ``partial`` marks a week/month that is cut off by the
    data's or the filter's date range (e.g. the dataset ends on a Tuesday), so
    the UI can show it differently instead of implying a collapse in sales.
    """
    col = GRANULARITY[granularity]
    cte, p = orders_cte(f)
    rows = db.all(
        f"""{cte}
            SELECT {col} AS period, COUNT(*) AS orders, SUM(order_value) AS revenue, SUM(item_count) AS items
            FROM o GROUP BY {col} ORDER BY {col}""",
        p,
    )
    lo, hi = db.one("SELECT MIN(order_date) AS lo, MAX(order_date) AS hi FROM orders").values()
    lo = max(date.fromisoformat(lo), date.fromisoformat(f.start)) if f.start else date.fromisoformat(lo)
    hi = min(date.fromisoformat(hi), date.fromisoformat(f.end)) if f.end else date.fromisoformat(hi)
    for r in rows:
        r["revenue"] = _r(r["revenue"])
        r["aov"] = _r(r["revenue"] / r["orders"]) if r["orders"] else 0
        start, end = _period_bounds(str(r["period"]), granularity)
        r["days"] = (min(end, hi) - max(start, lo)).days + 1
        r["period_days"] = (end - start).days + 1
        r["partial"] = r["days"] < r["period_days"]
    return rows


# --------------------------------------------------------------------------- #
def breakdown(db: Database, f: Filters, dim: str, limit: int | None = None) -> list[dict[str, Any]]:
    col, level = DIMENSIONS[dim]
    lim = f" LIMIT {int(limit)}" if limit else ""
    if level == "order":
        cte, p = orders_cte(f)
        sql = (
            f"{cte} SELECT {col} AS name, SUM(order_value) AS revenue, COUNT(*) AS orders, "
            f"SUM(item_count) AS quantity FROM o GROUP BY {col} ORDER BY revenue DESC{lim}"
        )
    else:
        w, p = where(f)
        sql = (
            f"SELECT {col} AS name, SUM(revenue) AS revenue, COUNT(DISTINCT bill_no) AS orders, "
            f"SUM(quantity) AS quantity FROM line_items {w} GROUP BY {col} "
            f"ORDER BY revenue DESC, quantity DESC{lim}"
        )
    rows = db.all(sql, p)
    if limit:  # share must be relative to *all* categories, not just the top N
        lw, lp = where(f)
        total = db.scalar(f"SELECT COALESCE(SUM(revenue),0) FROM line_items {lw}", lp)
    else:
        total = sum(r["revenue"] or 0 for r in rows)
    for r in rows:
        r["revenue"] = _r(r["revenue"])
        r["share"] = _r(r["revenue"] / total, 4) if total else 0
        r["aov"] = _r(r["revenue"] / r["orders"]) if r["orders"] else 0
    return rows


# --------------------------------------------------------------------------- #
def heatmap(db: Database, f: Filters) -> list[dict[str, Any]]:
    cte, p = orders_cte(f)
    rows = db.all(
        f"""{cte} SELECT weekday, hour, COUNT(*) AS orders, SUM(order_value) AS revenue
            FROM o GROUP BY weekday, hour ORDER BY weekday, hour""",
        p,
    )
    for r in rows:
        r["revenue"] = _r(r["revenue"])
    return rows


# --------------------------------------------------------------------------- #
def records(db: Database, f: Filters, page: int, page_size: int, sort: str, order: str) -> dict[str, Any]:
    w, p = where(f)
    col = SORTABLE[sort]
    direction = "DESC" if order == "desc" else "ASC"
    total = db.scalar(f"SELECT COUNT(*) FROM line_items {w}", p)
    rows = db.all(
        f"SELECT {', '.join(RECORD_COLUMNS)} FROM line_items {w} "
        f"ORDER BY {col} {direction}, id {direction} LIMIT ? OFFSET ?",
        [*p, page_size, (page - 1) * page_size],
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
        "sort": sort,
        "order": order,
        "rows": rows,
    }


def export_rows(db: Database, f: Filters) -> Iterator[tuple[list[str], list[tuple[Any, ...]]]]:
    """Filtered line items in chronological order, in batches, for CSV streaming."""
    w, p = where(f)
    return db.stream(f"SELECT {', '.join(RECORD_COLUMNS)} FROM line_items {w} ORDER BY order_ts, id", p)
