"""AI summary endpoint. The Claude client is faked: no network, no API key needed."""
import json
from types import SimpleNamespace

import pytest

from app import ai


class FakeMessages:
    def __init__(self, payload: dict, stop_reason: str = "end_turn") -> None:
        self.payload, self.stop_reason, self.calls = payload, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
            stop_reason=self.stop_reason,
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=150),
        )


BRIEF = {"headline": "Koramangala leads.", "points": ["a", "b", "c"], "actions": ["x", "y"]}


@pytest.fixture
def fake(monkeypatch):
    msgs = FakeMessages(BRIEF)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai, "_get_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=msgs)))
    monkeypatch.setattr(ai, "_limiter", ai._RateLimiter(100))
    return msgs


def test_disabled_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/meta").json()["ai_summary"] is False
    r = client.get("/api/ai-summary", params={"outlets": "MG Road"})
    assert r.status_code == 503


def test_summary_is_cached_per_filter(client, fake):
    assert client.get("/api/meta").json()["ai_summary"] is True
    params = {"order_types": "Delivery"}
    r1 = client.get("/api/ai-summary", params=params)
    r2 = client.get("/api/ai-summary", params=params)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["headline"] == BRIEF["headline"]
    assert r1.headers["X-Cache"] == "MISS" and r2.headers["X-Cache"] == "HIT"
    assert len(fake.calls) == 1  # second request never reached the model


def test_model_only_sees_formatted_facts_for_the_filters(client, fake):
    client.get("/api/ai-summary", params={"outlets": "Koramangala"})
    call = fake.calls[-1]
    facts = json.loads(call["messages"][0]["content"].split("\n", 1)[1])
    assert facts["filters"] == {"outlets": ["Koramangala"]}
    # Koramangala bills: 250 + 100 = ₹350 over 2 orders
    assert facts["kpis"]["revenue"] == "₹350" and facts["kpis"]["orders"] == "2"
    assert [o["name"] for o in facts["by_outlet"]] == ["Koramangala"]
    assert facts["computed_insights"], "rule-based insights are passed through"
    assert call["output_config"]["format"]["type"] == "json_schema"


def test_rate_limit(client, fake, monkeypatch):
    monkeypatch.setattr(ai, "_limiter", ai._RateLimiter(0))
    r = client.get("/api/ai-summary", params={"settlements": "Dineout"})
    assert r.status_code == 429
    assert fake.calls == []


def test_refusal_is_an_error_not_a_summary(client, fake):
    fake.stop_reason = "refusal"
    r = client.get("/api/ai-summary", params={"settlements": "SwiggyPay"})
    assert r.status_code == 502


def test_empty_selection(client, fake):
    r = client.get("/api/ai-summary", params={"start": "2030-01-01", "end": "2030-01-31"})
    assert r.status_code == 422
    assert fake.calls == []
