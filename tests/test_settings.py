import httpx
import respx


def test_settings_overview_masked(client):
    data = client.get("/api/settings").json()
    assert "..." in data["gateway"]["api_key_masked"]
    assert "sk-test-key" not in data["gateway"]["api_key_masked"]
    assert data["gateway"]["base_url"] == "http://upstream.test/compatible-mode/v1"
    assert any(t["name"] == "fast" for t in data["tiers"])
    assert data["defaults"]["default_total_tokens"] > 0


def test_put_tiers_roundtrip_and_hot_effect(client):
    new = [
        {"name": "fast", "display_name": "F档", "models": ["m-a", "m-b"]},
        {"name": "max", "display_name": "M档", "models": ["m-x"]},
    ]
    resp = client.put("/api/settings/tiers", json={"tiers": new})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 立即反映到档位健康度接口（热生效，无需重启）
    tiers = client.get("/api/tiers").json()["tiers"]
    fast = next(t for t in tiers if t["name"] == "fast")
    assert fast["active_model"] == "m-a"
    assert [m["model"] for m in fast["models"]] == ["m-a", "m-b"]

    # 空模型链被拒绝
    bad = client.put("/api/settings/tiers", json={"tiers": [{"name": "x", "models": []}]})
    assert bad.json().get("error", {}).get("code") == "TT.BadRequest"


def test_put_defaults_roundtrip(client):
    resp = client.put(
        "/api/settings/defaults",
        json={"default_valid_days": 60, "default_effective_from": "2026-10-01"},
    )
    assert resp.json()["ok"] is True
    data = client.get("/api/settings").json()["defaults"]
    assert data["default_valid_days"] == 60
    assert data["default_effective_from"] == "2026-10-01"

    # 清空起算日 → null
    resp = client.put("/api/settings/defaults", json={"default_effective_from": ""})
    assert resp.json()["defaults"]["default_effective_from"] is None

    # 非法日期被拒绝
    bad = client.put("/api/settings/defaults", json={"default_effective_from": "10/01"})
    assert bad.json().get("error", {}).get("code") == "TT.BadRequest"


@respx.mock
def test_upstream_check_ok(client):
    respx.get("http://upstream.test/compatible-mode/v1/models").mock(
        return_value=httpx.Response(200, json={"object": "list", "data": [{"id": "a"}, {"id": "b"}]})
    )
    r = client.get("/api/settings/upstream-check").json()
    assert r["ok"] is True
    assert r["model_count"] == 2
    assert r["latency_ms"] >= 0


@respx.mock
def test_upstream_check_failure(client):
    respx.get("http://upstream.test/compatible-mode/v1/models").mock(
        return_value=httpx.Response(401, json={"error": {"code": "InvalidApiKey"}})
    )
    r = client.get("/api/settings/upstream-check").json()
    assert r["ok"] is False
    assert r["status_code"] == 401


def test_put_service_roundtrip(client, monkeypatch):
    # 环境变量优先级高于 .env 文件，删掉才能看到文件值（monkeypatch 测试后自动还原）
    monkeypatch.delenv("BAILIAN_BASE_URL", raising=False)
    monkeypatch.delenv("BAILIAN_API_KEY", raising=False)

    resp = client.put(
        "/api/settings/service",
        json={
            "base_url": "http://upstream2.test/compatible-mode/v1",
            "api_key": "sk-newkey-12345678",
            "app_port": 8100,
            "low_percent": 0.3,
            "sync_hour": 4,
        },
    )
    body = resp.json()
    assert body["ok"] is True
    assert "监听端口" in body["restart_required"]  # 端口改动需重启

    # 热生效：GET 立即反映新端点/Key/阈值
    data = client.get("/api/settings").json()
    assert data["gateway"]["base_url"] == "http://upstream2.test/compatible-mode/v1"
    assert data["gateway"]["api_key_masked"] == "sk-new...5678"
    assert data["gateway"]["port"] == 8100
    assert data["low_percent"] == 0.3
    assert data["sync_hour"] == 4

    # .env 文件确实写入且保留其他行
    from pathlib import Path

    from app.config import get_settings

    env_text = Path(get_settings().env_path).read_text(encoding="utf-8")
    assert "BAILIAN_BASE_URL=http://upstream2.test/compatible-mode/v1" in env_text
    assert "BAILIAN_API_KEY=sk-newkey-12345678" in env_text
    assert "APP_PORT=8100" in env_text
    assert "FREE_QUOTA_LOW_PERCENT=0.3" in env_text

    # api_key 留空 = 保持不变
    r2 = client.put("/api/settings/service", json={"api_key": ""}).json()
    assert r2["ok"] is True
    env_text2 = Path(get_settings().env_path).read_text(encoding="utf-8")
    assert "sk-newkey-12345678" in env_text2

    # 非法端点被拒绝
    bad = client.put("/api/settings/service", json={"base_url": "ftp://x"})
    assert bad.json().get("error", {}).get("code") == "TT.BadRequest"
    bad2 = client.put("/api/settings/service", json={"app_port": 70000})
    assert bad2.json().get("error", {}).get("code") == "TT.BadRequest"
