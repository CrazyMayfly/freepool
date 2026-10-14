from datetime import datetime

from app.db import SessionLocal
from app.models import UsageRecord


def _add(model: str, total: int):
    with SessionLocal() as db:
        db.add(
            UsageRecord(
                ts=datetime.now(),
                requested_model=model,
                actual_model=model,
                input_tokens=total,
                output_tokens=0,
                total_tokens=total,
            )
        )
        db.commit()


def test_put_quota_creates_rule(client):
    resp = client.put(
        "/api/quota/test-model-x", json={"total_tokens": 5000, "valid_days": 30}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_tokens"] == 5000
    assert body["valid_days"] == 30
    assert body["effective_from"]  # 自动起算日


def test_put_quota_rejects_empty(client):
    resp = client.put("/api/quota/test-model-x", json={})
    assert resp.status_code == 200
    assert "error" in resp.json()


def test_overview_and_series(client):
    client.put("/api/quota/qwen3.8-flash", json={"total_tokens": 1000})
    _add("qwen3.8-flash", 300)
    ov = client.get("/api/overview").json()
    flash = next(m for m in ov["models"] if m["model"] == "qwen3.8-flash")
    assert flash["used_tokens"] == 300
    assert flash["remaining_tokens"] == 700
    assert ov["totals"]["today_tokens"] >= 300

    series = client.get("/api/usage/series?days=7").json()
    assert len(series["series"]) == 7
    assert series["series"][-1]["input_tokens"] >= 300


def test_tiers_endpoint(client):
    from app.tier_router import load_tiers

    data = client.get("/api/tiers").json()
    names = [t["name"] for t in data["tiers"]]
    assert "fast" in names and "max" in names
    fast = next(t for t in data["tiers"] if t["name"] == "fast")
    assert fast["active_model"] == load_tiers()["fast"].models[0]  # 全部可用时取链首
    assert fast["healthy"] is True


def test_requests_endpoint(client):
    _add("m-req", 42)
    data = client.get("/api/requests?limit=10").json()
    assert any(r["actual_model"] == "m-req" and r["total_tokens"] == 42 for r in data["items"])
