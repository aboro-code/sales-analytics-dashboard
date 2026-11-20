"""
Filter parsing, validation and SQL generation.

Every data endpoint accepts the same filter set. Values are validated against
the real dimension values (from /api/meta), so unknown values are rejected with
a clear 422 instead of silently returning empty charts. SQL is always built
with ``?`` placeholders - user input never reaches the SQL string.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import HTTPException, Query

# filter name -> column in both line_items and orders (where applicable)
ORDER_LEVEL = {"outlets": "outlet", "order_types": "order_type", "settlements": "settlement"}
LINE_LEVEL = {"groups": "item_group", "items": "item"}


@dataclass(frozen=True)
class Filters:
    start: str | None = None  # inclusive 'YYYY-MM-DD'
    end: str | None = None    # inclusive 'YYYY-MM-DD'
    outlets: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    items: tuple[str, ...] = ()
    order_types: tuple[str, ...] = ()
    settlements: tuple[str, ...] = ()

    @property
    def has_line_filters(self) -> bool:
        """Group/item filters act on line items, so orders must be re-derived."""
        return bool(self.groups or self.items)

    def key(self) -> tuple[Any, ...]:
        """Normalised, hashable cache key (order of multi-select values is irrelevant)."""
        return (self.start, self.end, self.outlets, self.groups, self.items, self.order_types, self.settlements)

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start, "end": self.end,
            "outlets": list(self.outlets), "groups": list(self.groups), "items": list(self.items),
            "order_types": list(self.order_types), "settlements": list(self.settlements),
        }


def _norm(values: list[str] | None) -> tuple[str, ...]:
    """Accept both repeated params (?outlets=A&outlets=B) and comma lists (?outlets=A,B)."""
    out: set[str] = set()
    for v in values or []:
        for part in v.split(","):
            part = part.strip()
            if part:
                out.add(part)
    return tuple(sorted(out))


def _date(v: str | None, name: str) -> str | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise HTTPException(422, f"'{name}' must be an ISO date (YYYY-MM-DD), got {v!r}")


class FilterParser:
    """FastAPI dependency. Holds the allowed values so it can validate input."""

    def __init__(self, allowed: dict[str, set[str]]) -> None:
        self.allowed = allowed

    def __call__(
        self,
        start: Annotated[str | None, Query(description="Inclusive start date, YYYY-MM-DD")] = None,
        end: Annotated[str | None, Query(description="Inclusive end date, YYYY-MM-DD")] = None,
        outlets: Annotated[list[str] | None, Query()] = None,
        groups: Annotated[list[str] | None, Query()] = None,
        items: Annotated[list[str] | None, Query()] = None,
        order_types: Annotated[list[str] | None, Query()] = None,
        settlements: Annotated[list[str] | None, Query()] = None,
    ) -> Filters:
        f = Filters(
            start=_date(start, "start"),
            end=_date(end, "end"),
            outlets=_norm(outlets),
            groups=_norm(groups),
            items=_norm(items),
            order_types=_norm(order_types),
            settlements=_norm(settlements),
        )
        if f.start and f.end and f.start > f.end:
            raise HTTPException(422, "'start' must be on or before 'end'")
        for name in (*ORDER_LEVEL, *LINE_LEVEL):
            unknown = set(getattr(f, name)) - self.allowed.get(name, set())
            if unknown:
                raise HTTPException(422, f"Unknown {name}: {sorted(unknown)}")
        return f


# --------------------------------------------------------------------------- #
# SQL builders
# --------------------------------------------------------------------------- #
def _in(col: str, values: tuple[str, ...], params: list[Any]) -> str:
    params.extend(values)
    return f"{col} IN ({','.join('?' * len(values))})"


def where(f: Filters, *, include_line_level: bool = True, alias: str = "") -> tuple[str, list[Any]]:
    """WHERE clause for line_items (or orders when include_line_level=False)."""
    p = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    if f.start:
        clauses.append(f"{p}order_date >= CAST(? AS DATE)")
        params.append(f.start)
    if f.end:
        clauses.append(f"{p}order_date <= CAST(? AS DATE)")
        params.append(f.end)
    for name, col in ORDER_LEVEL.items():
        vals = getattr(f, name)
        if vals:
            clauses.append(_in(p + col, vals, params))
    if include_line_level:
        for name, col in LINE_LEVEL.items():
            vals = getattr(f, name)
            if vals:
                clauses.append(_in(p + col, vals, params))
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def orders_cte(f: Filters) -> tuple[str, list[Any]]:
    """
    ``WITH o AS (...)`` - one row per order, matching the filters.

    * No group/item filter: read the pre-aggregated ``orders`` table (fast path).
    * With a group/item filter: derive orders from the matching line items, so
      ``order_value`` is the revenue of the *matching lines* in each bill and an
      order counts if it contains at least one matching line.

    Downstream queries are identical either way - they just read ``o``.
    """
    bill_cols = ["outlet", "order_type", "settlement", "order_date", "week", "month", "hour", "weekday"]
    if not f.has_line_filters:
        w, params = where(f, include_line_level=False)
        cols = ", ".join(["bill_no", *bill_cols, "item_count", "order_value"])
        return f"WITH o AS (SELECT {cols} FROM orders {w})", params
    w, params = where(f)
    # Bill-level columns are constant within a bill (validated in the ETL), so
    # any_value() is exact here, not an approximation.
    picked = ", ".join(f"any_value({c}) AS {c}" for c in bill_cols)
    return (
        f"WITH o AS (SELECT bill_no, {picked}, SUM(quantity) AS item_count, SUM(revenue) AS order_value "
        f"FROM line_items {w} GROUP BY bill_no)",
        params,
    )
