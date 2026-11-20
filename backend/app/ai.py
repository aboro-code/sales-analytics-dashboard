"""
Optional AI summary: an LLM rewrites facts we already computed into a short
manager-style brief. Two interchangeable providers:

* ``groq``      - free tier, open-weights model (default: openai/gpt-oss-120b).
                  This is what the live demo uses.
* ``anthropic`` - Claude (default: claude-opus-5-5).

Design rules (see DECISIONS.md, D11):
* The model never computes anything. It gets the SQL-derived KPIs, breakdowns
  and rule-based insights as JSON and is told to use only numbers that appear
  there, already formatted.
* It is off unless a provider key is set. The frontend hides the button when
  /api/meta reports `ai_summary: false`, so the dashboard never depends on it.
* Responses are cached per filter combination (the data is immutable), and
  uncached calls are rate-limited, so a public demo can't run up a bill.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any

from . import insights as insights_mod
from . import queries
from .db import Database
from .filters import Filters

log = logging.getLogger("api.ai")

DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "groq": "openai/gpt-oss-120b"}
KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY"}
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_CALLS_PER_HOUR = int(os.environ.get("AI_MAX_CALLS_PER_HOUR", 30))

SYSTEM = """You are a business analyst writing a brief for the owner of a restaurant brand \
with several outlets in Bengaluru. You receive JSON facts computed from their sales data \
for the filters they selected.

Rules:
- Use ONLY numbers that appear in the facts, copied exactly as formatted (₹ amounts with L/Cr, \
percentages). Never calculate, add up, round, estimate or invent a number; describe combined \
or relative sizes in words instead (e.g. "the top three outlets bring most of the revenue").
- Keep each fact's meaning exactly as the facts state it; don't reinterpret what a percentage \
refers to.
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


def provider() -> str | None:
    """AI_PROVIDER if set, else whichever key is present (Groq first: it's free)."""
    chosen = os.environ.get("AI_PROVIDER", "").strip().lower()
    if chosen:
        return chosen if chosen in KEY_VARS and os.environ.get(KEY_VARS[chosen]) else None
    for name in ("groq", "anthropic"):
        if os.environ.get(KEY_VARS[name]):
            return name
    return None


def model_for(name: str) -> str:
    return os.environ.get("AI_MODEL") or DEFAULT_MODELS[name]


def enabled() -> bool:
    return provider() is not None


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


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    return {float(m.replace(",", "")) for m in _NUM.findall(text)}


def unverified_numbers(brief: dict[str, Any], facts_text: str) -> list[str]:
    """Numbers in the brief that don't appear anywhere in the facts.

    Compared as values (so "1,10,478" == "110,478" and "1.9" == "1.90"). Years and
    small integers (hours, day counts, "top 3") are skipped: they're words, not data.
    """
    known = _numbers(facts_text)
    out = []
    for sentence in [brief["headline"], *brief["points"], *brief["actions"]]:
        for m in _NUM.findall(sentence):
            v = float(m.replace(",", ""))
            if v in known or (v.is_integer() and (v <= 31 or 2000 <= v <= 2100)):
                continue
            out.append(m)
    return out


def _parse(text: str, model: str) -> dict[str, Any]:
    try:
        brief = json.loads(text)
        assert isinstance(brief.get("headline"), str) and brief["headline"].strip()
        assert all(isinstance(brief.get(k), list) for k in ("points", "actions"))
    except (json.JSONDecodeError, AssertionError, AttributeError):
        log.error("AI summary: malformed output from %s", model)
        raise AIUnavailable("The AI summary came back malformed; try again.", status=502)
    return {"headline": brief["headline"], "points": [str(p) for p in brief["points"]],
            "actions": [str(a) for a in brief["actions"]]}


def summarize(db: Database, f: Filters) -> dict[str, Any]:
    name = provider()
    if name is None:
        raise AIUnavailable("AI summary is not configured on this server.")
    data = facts(db, f)
    if not _limiter.acquire():
        raise AIUnavailable("AI summary rate limit reached; try again later.", status=429)

    facts_text = json.dumps(data, ensure_ascii=False)
    messages = [{"role": "user", "content": "Facts (JSON):\n" + facts_text}]
    call = _call_groq if name == "groq" else _call_anthropic
    t0 = time.perf_counter()
    text, model, usage = call(messages)
    brief = _parse(text, model)

    # Guardrail: every number must exist in the facts. One corrective retry, then flag.
    bad = unverified_numbers(brief, facts_text)
    attempts = 1
    if bad:
        log.warning("AI summary: unverified numbers %s; retrying once", bad)
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"These numbers do not appear in the facts: {', '.join(bad)}. "
                                        "Rewrite the brief using only numbers copied from the facts; "
                                        "describe anything else in words."},
        ]
        text, model, usage2 = call(messages)
        brief = _parse(text, model)
        usage = {k: usage[k] + usage2[k] for k in usage}
        bad = unverified_numbers(brief, facts_text)
        attempts = 2

    return {
        **brief,
        "verified": not bad,
        "unverified_numbers": bad,
        "attempts": attempts,
        "model": model,
        "provider": name,
        "generated_ms": round((time.perf_counter() - t0) * 1000),
        "usage": usage,
    }


def _call_anthropic(messages: list[dict[str, str]]) -> tuple[str, str, dict[str, int]]:
    import anthropic

    try:
        response = _get_client().beta.messages.create(
            model=model_for("anthropic"),
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=messages,
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
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return text, response.model, usage


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float = 60) -> dict[str, Any]:
    """Tiny stdlib HTTP client: one POST per summary doesn't justify another dependency."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "sales-analytics-dashboard/1.0", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _call_groq(messages: list[dict[str, str]]) -> tuple[str, str, dict[str, int]]:
    body = {
        "model": model_for("groq"),
        "messages": [{"role": "system", "content": SYSTEM}, *messages],
        # Strict mode = constrained decoding, so the reply always matches SCHEMA.
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "brief", "strict": True, "schema": SCHEMA}},
        "reasoning_effort": "low",
        "include_reasoning": False,
        "temperature": 0.3,
        "max_completion_tokens": 2000,
    }
    try:
        res = _post_json(GROQ_URL, body, {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"})
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        log.error("AI summary: Groq HTTP %s %s", e.code, detail)
        if e.code in (401, 403):
            raise AIUnavailable("AI summary is misconfigured on this server.")
        if e.code == 429:
            raise AIUnavailable("The free AI quota is busy; try again in a minute.", status=429)
        raise AIUnavailable("The AI provider returned an error.", status=502)
    except (urllib.error.URLError, TimeoutError):
        raise AIUnavailable("Could not reach the AI provider.", status=502)

    choice = res["choices"][0]
    if choice.get("finish_reason") == "length":
        raise AIUnavailable("The AI summary was cut off; try again.", status=502)
    u = res.get("usage") or {}
    usage = {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}
    return choice["message"].get("content") or "", res.get("model", body["model"]), usage
