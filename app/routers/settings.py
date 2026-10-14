"""配置页接口：档位链与全局默认的查看/修改（写 yaml，热生效）+ 上游连通性检查。

.env 里的网关地址/Key 只读展示（改 .env 需重启）；yaml 配置每请求实时加载，保存即生效。
"""

import time
from datetime import date
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter

from .. import tier_router
from ..config import get_settings

router = APIRouter()


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "****"
    return f"{key[:6]}...{key[-4:]}"


def _dump_yaml(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _read_free_models() -> dict:
    path = get_settings().config_dir / "free_models.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _tiers_view() -> list[dict]:
    return [
        {"name": t.name, "display_name": t.display_name, "models": t.models}
        for t in tier_router.load_tiers().values()
    ]


@router.get("/api/settings")
def api_settings():
    s = get_settings()
    conf = _read_free_models()
    return {
        "gateway": {
            "base_url": s.bailian_base_url,
            "chat_url": s.chat_url,
            "api_key_masked": _mask(s.bailian_api_key),
            "host": s.app_host,
            "port": s.app_port,
            "database_url": s.database_url,
            "config_dir": str(s.config_dir),
        },
        "defaults": {
            "default_total_tokens": conf.get("default_total_tokens", s.default_total_tokens),
            "default_valid_days": conf.get("default_valid_days", s.default_valid_days),
            "default_effective_from": conf.get("default_effective_from"),
        },
        "low_percent": s.free_quota_low_percent,
        "sync_hour": s.sync_hour,
        "tiers": _tiers_view(),
    }


@router.put("/api/settings/service")
def api_put_service(body: dict):
    """编辑服务信息：写回 .env（保留其他行），端点/Key/阈值/同步小时即时生效，
    监听地址/端口需重启。api_key 留空 = 保持不变。"""
    s = get_settings()
    updates: dict[str, str] = {}
    restart: list[str] = []

    if "base_url" in body:
        v = str(body["base_url"]).strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            return {"error": {"message": "端点必须以 http:// 或 https:// 开头", "code": "TT.BadRequest"}}
        if v != s.bailian_base_url:
            updates["BAILIAN_BASE_URL"] = v
    if "api_key" in body:
        v = str(body["api_key"]).strip()
        if v and (len(v) < 8 or any(c.isspace() for c in v)):
            return {"error": {"message": "API Key 格式不正确", "code": "TT.BadRequest"}}
        if v and v != s.bailian_api_key:
            updates["BAILIAN_API_KEY"] = v
    if "app_host" in body:
        v = str(body["app_host"]).strip()
        if not v:
            return {"error": {"message": "监听地址不能为空", "code": "TT.BadRequest"}}
        if v != s.app_host:
            updates["APP_HOST"] = v
            restart.append("监听地址")
    if "app_port" in body:
        v = int(body["app_port"])
        if not 1 <= v <= 65535:
            return {"error": {"message": "端口范围 1-65535", "code": "TT.BadRequest"}}
        if v != s.app_port:
            updates["APP_PORT"] = str(v)
            restart.append("监听端口")
    if "low_percent" in body:
        v = float(body["low_percent"])
        if not 0 < v < 1:
            return {"error": {"message": "偏低阈值应为 0-1 之间的小数", "code": "TT.BadRequest"}}
        if abs(v - s.free_quota_low_percent) > 1e-9:
            updates["FREE_QUOTA_LOW_PERCENT"] = str(v)
    if "sync_hour" in body:
        v = int(body["sync_hour"])
        if not 0 <= v <= 23:
            return {"error": {"message": "同步小时范围 0-23", "code": "TT.BadRequest"}}
        if v != s.sync_hour:
            updates["SYNC_HOUR"] = str(v)
            restart.append("每日同步时间（下次调度起生效）")

    if updates:
        _write_env(s.env_path, updates)
        get_settings.cache_clear()  # 端点/Key/阈值热生效

    s2 = get_settings()
    return {
        "ok": True,
        "restart_required": restart,
        "gateway": {
            "base_url": s2.bailian_base_url,
            "chat_url": s2.chat_url,
            "api_key_masked": _mask(s2.bailian_api_key),
            "host": s2.app_host,
            "port": s2.app_port,
        },
    }


def _write_env(path: Path, updates: dict[str, str]) -> None:
    """就地更新 .env 中的键，其余行（含注释）原样保留；键不存在则追加到末尾。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if key and key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(path)


@router.put("/api/settings/tiers")
def api_put_tiers(body: dict):
    items = body.get("tiers")
    if not isinstance(items, list) or not items:
        return {"error": {"message": "tiers 必须是非空数组", "code": "TT.BadRequest"}}
    cleaned: dict[str, dict] = {}
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            return {"error": {"message": "档位名不能为空", "code": "TT.BadRequest"}}
        models = [str(m).strip() for m in (item.get("models") or []) if str(m).strip()]
        if not models:
            return {"error": {"message": f"档位 {name} 的模型链不能为空", "code": "TT.BadRequest"}}
        cleaned[name] = {
            "display_name": str(item.get("display_name") or "").strip() or name,
            "models": models,
        }
    _dump_yaml(get_settings().config_dir / "tiers.yaml", {"tiers": cleaned})
    return {"ok": True, "tiers": _tiers_view()}


@router.put("/api/settings/defaults")
def api_put_defaults(body: dict):
    s = get_settings()
    path = s.config_dir / "free_models.yaml"
    conf = _read_free_models()
    if "default_total_tokens" in body:
        v = int(body["default_total_tokens"])
        if v <= 0:
            return {"error": {"message": "默认总量必须为正整数", "code": "TT.BadRequest"}}
        conf["default_total_tokens"] = v
    if "default_valid_days" in body:
        v = int(body["default_valid_days"])
        if v <= 0:
            return {"error": {"message": "默认有效天数必须为正整数", "code": "TT.BadRequest"}}
        conf["default_valid_days"] = v
    if "default_effective_from" in body:
        v = body["default_effective_from"]
        if v in (None, ""):
            conf["default_effective_from"] = None
        else:
            try:
                conf["default_effective_from"] = date.fromisoformat(str(v)).isoformat()
            except ValueError:
                return {"error": {"message": "起算日格式应为 YYYY-MM-DD", "code": "TT.BadRequest"}}
    _dump_yaml(path, conf)
    return {
        "ok": True,
        "defaults": {
            "default_total_tokens": conf.get("default_total_tokens"),
            "default_valid_days": conf.get("default_valid_days"),
            "default_effective_from": conf.get("default_effective_from"),
        },
    }


@router.get("/api/settings/upstream-check")
async def api_upstream_check():
    s = get_settings()
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(
                s.models_url, headers={"Authorization": f"Bearer {s.bailian_api_key}"}
            )
        latency = int((time.monotonic() - started) * 1000)
        model_count = None
        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data")
            model_count = len(data) if isinstance(data, list) else None
        return {
            "ok": resp.status_code == 200,
            "status_code": resp.status_code,
            "latency_ms": latency,
            "model_count": model_count,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
