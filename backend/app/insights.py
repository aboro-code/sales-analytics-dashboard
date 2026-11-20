"""
Rule-based, plain-English insights computed from the same filter-aware queries
the charts use. Deterministic, free and instant, so there are no API keys and
no hallucinated numbers. An LLM could later rephrase or prioritise these facts,
but the facts themselves should keep coming from SQL.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from typing import Any

from . import queries
from .db import Database
from .filters import Filters, where

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
AGGREGATORS = {"ZomatoPay", "SwiggyPay"}
MIN_GROUP_SHARE = 0.05  # categories below 5% of monthly revenue are too small to headline


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _inr(x: float) -> str:
    """Indian short form: ₹1.2 Cr, ₹4.5 L, ₹12,340."""
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:.2f} Cr"
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:.2f} L"
    return f"₹{x:,.0f}"


def _hour(h: int) -> str:
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def _insight(id_: str, title: str, text: str, tone: str = "neutral", **extra: Any) -> dict[str, Any]:
    return {"id": id_, "title": title, "text": text, "tone": tone, **extra}


def _complete_months(days: list[str], f: Filters) -> list[str]:
    """Months fully covered by both the data and the selected date range."""
    present: dict[str, int] = defaultdict(int)
    for d in days:
        present[d[:7]] += 1
    out = []
    for m, n in sorted(present.items()):
        y, mo = int(m[:4]), int(m[5:])
        first, last = date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])
        if f.start and first.isoformat() < f.start:
            continue
        if f.end and last.isoformat() > f.end:
            continue
        if n == calendar.monthrange(y, mo)[1]:
            out.append(m)
    return out


def generate(db: Database, f: Filters) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    s = queries.summary(db, f)
    if not s["orders"]:
        return out

    # 1. Best outlet, and how far ahead of the weakest it is.
    outlets = queries.breakdown(db, f, "outlet")
    if len(outlets) > 1:
        best, worst = outlets[0], outlets[-1]
        out.append(_insight(
            "top_outlet", "Top outlet",
            f"{best['name']} leads with {_inr(best['revenue'])} ({_pct(best['share'])} of revenue), "
            f"{best['revenue'] / worst['revenue']:.1f}× the smallest outlet, {worst['name']}.",
            "positive", value=best["name"],
        ))

    # 2. Peak hour plus the lunch and dinner windows.
    cells = queries.heatmap(db, f)
    by_hour: dict[int, int] = defaultdict(int)
    by_wd: dict[int, int] = defaultdict(int)
    for c in cells:
        by_hour[c["hour"]] += c["orders"]
        by_wd[c["weekday"]] += c["orders"]
    total_orders = sum(by_hour.values())
    if total_orders:
        peak_h = max(by_hour, key=by_hour.get)
        lunch = sum(v for h, v in by_hour.items() if 12 <= h <= 14) / total_orders
        dinner = sum(v for h, v in by_hour.items() if 19 <= h <= 21) / total_orders
        out.append(_insight(
            "peak_hour", "Peak hour",
            f"The busiest hour is {_hour(peak_h)}–{_hour(peak_h + 1)} ({_pct(by_hour[peak_h] / total_orders)} of orders). "
            f"Lunch (12–3 PM) brings {_pct(lunch)} and dinner (7–10 PM) {_pct(dinner)}. Staff for those two windows.",
            value=peak_h,
        ))

    # 3. Weekend vs weekday, as average revenue per trading day.
    days = queries.timeseries(db, f, "day")
    wk = [d["revenue"] for d in days if date.fromisoformat(d["period"]).weekday() >= 5]
    wd = [d["revenue"] for d in days if date.fromisoformat(d["period"]).weekday() < 5]
    if wk and wd:
        we_avg, wd_avg = sum(wk) / len(wk), sum(wd) / len(wd)
        diff = we_avg / wd_avg - 1
        busiest = WEEKDAYS[max(by_wd, key=by_wd.get)] if by_wd else None
        out.append(_insight(
            "weekend", "Weekend vs weekday",
            f"An average weekend day brings {_inr(we_avg)} vs {_inr(wd_avg)} on weekdays "
            f"({'+' if diff >= 0 else ''}{_pct(diff)}). The busiest day of the week is {busiest}.",
            "positive" if diff > 0 else "neutral", value=round(diff, 4),
        ))

    # 4. Order type mix and delivery share.
    types = {r["name"]: r for r in queries.breakdown(db, f, "order_type")}
    if "Delivery" in types and len(types) > 1:
        d = types["Delivery"]
        out.append(_insight(
            "delivery_share", "Delivery share",
            f"Delivery is {_pct(d['orders'] / s['orders'])} of orders and {_pct(d['share'])} of revenue "
            f"(AOV {_inr(d['aov'])} vs {_inr(s['aov'])} overall).",
            value=round(d["orders"] / s["orders"], 4),
        ))

    # 5. Aggregator dependence within delivery.
    if "Delivery" in types and (not f.order_types or "Delivery" in f.order_types):
        df = Filters(**{**f.__dict__, "order_types": ("Delivery",)})
        sett = {r["name"]: r for r in queries.breakdown(db, df, "settlement")}
        agg_orders = sum(r["orders"] for n, r in sett.items() if n in AGGREGATORS)
        deliv_orders = sum(r["orders"] for r in sett.values())
        if deliv_orders and agg_orders:
            z, sw = sett.get("ZomatoPay", {}).get("orders", 0), sett.get("SwiggyPay", {}).get("orders", 0)
            share = agg_orders / deliv_orders
            out.append(_insight(
                "aggregator_share", "Aggregator dependence",
                f"{_pct(share)} of delivery orders come through Zomato or Swiggy "
                f"(Zomato {z:,} vs Swiggy {sw:,}); only {_pct(1 - share)} are direct. "
                f"Growing direct delivery would save aggregator commission.",
                "warning" if share > 0.75 else "neutral", value=round(share, 4),
            ))

    # 6. Fastest-growing group, last complete month vs the one before.
    months = _complete_months([d["period"] for d in days], f)
    if len(months) >= 2:
        prev_m, last_m = months[-2], months[-1]
        w, p = where(f)
        cond = f"{w} AND" if w else "WHERE"
        rows = db.all(
            f"SELECT item_group, month, SUM(revenue) AS revenue FROM line_items {cond} month IN (?, ?) "
            f"GROUP BY item_group, month",
            [*p, prev_m, last_m],
        )
        rev: dict[str, dict[str, float]] = defaultdict(dict)
        for r in rows:
            rev[r["item_group"]][r["month"]] = r["revenue"]
        # Ignore immaterial categories (< MIN_GROUP_SHARE of the month's revenue):
        # a +30% swing on a ₹50K category is noise, not a headline.
        prev_total = sum(v.get(prev_m, 0) for v in rev.values())
        growth = {
            g: v[last_m] / v[prev_m] - 1
            for g, v in rev.items()
            if v.get(prev_m) and v.get(last_m) is not None and v[prev_m] >= MIN_GROUP_SHARE * prev_total
        }
        if growth:
            g = max(growth, key=growth.get)
            label = calendar.month_name[int(last_m[5:])] + " " + last_m[:4]
            prev_label = calendar.month_name[int(prev_m[5:])]
            out.append(_insight(
                "fastest_group", "Fastest-growing category",
                f"{g} grew the most in {label}: {'+' if growth[g] >= 0 else ''}{_pct(growth[g])} revenue vs {prev_label} "
                f"({_inr(rev[g][prev_m])} → {_inr(rev[g][last_m])}).",
                "positive" if growth[g] > 0 else "warning", value=round(growth[g], 4),
            ))

    # 7. Hero item.
    if s["top_item"] and s["revenue"]:
        ti = s["top_item"]
        out.append(_insight(
            "top_item", "Hero item",
            f"{ti['name']} is the top earner: {_inr(ti['revenue'])} from {ti['quantity']:,} units "
            f"({_pct(ti['revenue'] / s['revenue'])} of revenue).",
            "positive", value=ti["name"],
        ))

    # 8. Complimentary dips (price = 0).
    if s["free_items"]:
        w, p = where(f)
        cond = f"{w} AND" if w else "WHERE"
        with_dip = db.scalar(f"SELECT COUNT(DISTINCT bill_no) FROM line_items {cond} price = 0", p) or 0
        out.append(_insight(
            "free_dips", "Free add-ons",
            f"{s['free_items']:,} complimentary dips were handed out (on {s['free_lines']:,} ₹0 lines) across {_pct(with_dip / s['orders'])} of orders. "
            f"Even a ₹10 charge would have added {_inr(s['free_items'] * 10)}.",
            value=s["free_items"],
        ))
    return out
