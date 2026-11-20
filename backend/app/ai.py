"""
Optional AI summary: Claude rewrites facts we already computed into a short
manager-style brief.

Design rules (see DECISIONS.md, D11):
* The model never computes anything. It gets the SQL-derived KPIs, breakdowns
  and rule-based insights as JSON and is told to use only numbers that appear
  there, already formatted.
* It is off unless ANTHROPIC_API_KEY is set. The frontend hides the button when
  /api/meta reports `ai_summary: false`, so the dashboard never depends on it.
* Responses are cached per filter combination (the data is immutable), and
  uncached calls are rate-limited, so a public demo can't run up a bill.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from typing import Any

from . import insights as insights_mod
from . import queries
from .db import Database
from .filters import Filters

log = logging.getLogger("api.ai")

MODEL = os.environ.get("AI_MODEL", "claude-opus-5-5")
MAX_CALLS_PER_HOUR = int(os.environ.get("AI_MAX_CALLS_PER_HOUR", 30))

SYSTEM = """You are a business analyst writing a brief for the owner of a restaurant brand \
with several outlets in Bengaluru. You receive JSON facts computed from their sales data \
for the filters they selected.

Rules:
- Use ONLY numbers that appear in the facts, copied exactly as formatted (₹ amounts with L/Cr, \
percentages). Never calculate, round, estimate or invent a number.
- If the facts don't support a claim, leave it out.
- Plain, direct business English. No hype, no emojis, no markdown.
- headline: one sentence, the single most important takeaway.
- points: 3 or 4 short observations (max ~30 words each), most important first.
- actions: 2 concrete, practical suggestions that follow from the observations."""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "points": {"type": "array", "items": {"type": "string"}},
        "actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "points", "actions"],
    "additionalProperties": False,
}


class AIUnavailable(Exception):
    """Raised when the summary can't be produced (disabled, rate-limited, API error)."""

    def __init__(self, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


class _RateLimiter:
    """Sliding one-hour window over *uncached* model calls."""

    def __init__(self, per_hour: int) -> None:
        self.per_hour = per_hour
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._calls and now - self._calls[0] > 3600:
                self._calls.popleft()
            if len(self._calls) >= self.per_hour:
                return False
            self._calls.append(now)
            return True


_limiter = _RateLimiter(MAX_CALLS_PER_HOUR)
_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so the API runs without the package/key

        _client = anthropic.Anthropic(timeout=60.0, max_retries=2)
    return _client


def facts(db: Database, f: Filters) -> dict[str, Any]:
    """The only data the model sees: pre-formatted, filter-aware facts."""
    fmt = insights_mod._inr
    s = queries.summary(db, f)
    if not s["orders"]:
        raise AIUnavailable("No orders match these filters.", status=422)

    def mix(dim: str) -> list[dict[str, str]]:
        return [
            {"name": r["name"], "revenue": fmt(r["revenue"]), "share_of_revenue": f"{r['share'] * 100:.1f}%",
             "orders": f"{r['orders']:,}"}
            for r in queries.breakdown(db, f, dim, 6)
        ]

    months = queries.timeseries(db, f, "month")
    return {
        "filters": {k: v for k, v in f.__dict__.items() if v},
        "period": {"from": f.start or months[0]["period"], "to": f.end or months[-1]["period"],
                   "trading_days": s["active_days"]},
        "kpis": {
            "revenue": fmt(s["revenue"]),
            "orders": f"{s['orders']:,}",
            "average_order_value": f"₹{s['aov']:.2f}",
            "items_per_order": f"{s['avg_items_per_order']:.2f}",
            "average_daily_revenue": fmt(s["avg_daily_revenue"]),
        },
        "monthly_revenue": [
            {"month": p["period"][:7], "revenue": fmt(p["revenue"]),
             **({"note": f"partial month ({p['days']} of {p['period_days']} days)"} if p.get("partial") else {})}
            for p in months
        ],
        "by_outlet": mix("outlet"),
        "by_order_type": mix("order_type"),
        "by_channel": mix("settlement"),
        "by_category": mix("group"),
        "computed_insights": [{"title": i["title"], "text": i["text"]} for i in insights_mod.generate(db, f)],
    }


def summarize(db: Database, f: Filters) -> dict[str, Any]:
    if not enabled():
        raise AIUnavailable("AI summary is not configured on this server.")
    data = facts(db, f)
    if not _limiter.acquire():
        raise AIUnavailable("AI summary rate limit reached; try again later.", status=429)

    import anthropic

    t0 = time.perf_counter()
    try:
        response = _get_client().beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": "Facts (JSON):\n" + json.dumps(data, ensure_ascii=False)}],
        )
    except anthropic.AuthenticationError:
        log.error("AI summary: invalid ANTHROPIC_API_KEY")
        raise AIUnavailable("AI summary is misconfigured on this server.")
    except anthropic.RateLimitError:
        raise AIUnavailable("The AI provider is busy; try again in a minute.", status=429)
    except anthropic.APIStatusError as e:
        log.error("AI summary: API error %s %s", e.status_code, e.message)
        raise AIUnavailable("The AI provider returned an error.", status=502)
    except anthropic.APIConnectionError:
        raise AIUnavailable("Could not reach the AI provider.", status=502)

    if response.stop_reason == "refusal":
        raise AIUnavailable("The model declined to summarise this selection.", status=502)
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        brief = json.loads(text)
    except json.JSONDecodeError:
        log.error("AI summary: unparseable output (stop_reason=%s)", response.stop_reason)
        raise AIUnavailable("The AI summary came back malformed; try again.", status=502)

    return {
        **brief,
        "model": response.model,
        "generated_ms": round((time.perf_counter() - t0) * 1000),
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
    }
