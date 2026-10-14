import httpx
import respx

from app.db import SessionLocal
from app.models import CatalogModel


def _models_page():
    return {
        "success": True,
        "output": {
            "total": 2,
            "page_no": 1,
            "page_size": 50,
            "models": [
                {
                    "model": "qwen3.8-flash",
                    "name": "Qwen3.8 Flash",
                    "provider": "qwen",
                    "inference_provider": "aliyun-bailian",
                    "capabilities": ["Text"],
                    "features": ["cache"],
                    "published_time": "2026-09-01 10:00:00",
                    "model_info": {
                        "context_window": 131072,
                        "max_input_tokens": 130000,
                        "max_output_tokens": 8192,
                    },
                    "prices": [{"range_name": "Default", "prices": []}],
                    "inference_offline_info": None,
                },
                {
                    "model": "deepseek-v4-pro",
                    "name": "DeepSeek V4 Pro",
                    "provider": "deepseek",
                    "published_time": None,
                },
            ],
        },
    }


def _limits_page():
    return {
        "success": True,
        "output": {
            "total": 1,
            "quotas": [
                {
                    "model": "qwen3.8-flash",
                    "workspace_id": "ws-test",
                    "model_limit": {
                        "request_limit": 60,
                        "request_limit_period": 60,
                        "usage_limit": 1000000,
                        "usage_limit_field": "total_tokens",
                        "usage_limit_period": 60,
                    },
                    "workspace_limit": None,
                }
            ],
        },
    }


@respx.mock
def test_catalog_sync(client):
    respx.get("http://upstream.test/api/v1/models").mock(
        return_value=httpx.Response(200, json=_models_page())
    )
    respx.get("http://upstream.test/api/v1/models/limits").mock(
        return_value=httpx.Response(200, json=_limits_page())
    )
    resp = client.post("/api/catalog/sync")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "models": 2, "limits": 1}

    with SessionLocal() as db:
        flash = db.get(CatalogModel, "qwen3.8-flash")
        assert flash is not None
        assert flash.provider == "qwen"
        assert flash.context_window == 131072
        assert flash.published_time is not None
        assert flash.published_time.year == 2026

    items = client.get("/api/catalog").json()["items"]
    assert len(items) == 2
    flash = next(i for i in items if i["model"] == "qwen3.8-flash")
    assert flash["rate_limit"]["request_limit"] == 60
    assert flash["published_time"] == "2026-09-01T10:00:00"
