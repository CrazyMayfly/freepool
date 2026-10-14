"""官方 ListModels / models-limits 同步（Bearer sk- key 可用）。"""

from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from .config import get_settings
from .models import CatalogLimit, CatalogModel

PAGE_SIZE = 50
MAX_PAGES = 60


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def _first_offline_time(info) -> datetime | None:
    """inference_offline_info 形如 {"$": {"offline_time": ...}} 或 {model: {...}}。"""
    if isinstance(info, dict):
        for v in info.values():
            if isinstance(v, dict) and v.get("offline_time"):
                return _parse_dt(v["offline_time"])
    elif isinstance(info, str):
        return _parse_dt(info)
    return None


async def _paginate(client: httpx.AsyncClient, url: str, items_key: str):
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.bailian_api_key}"}
    page_no = 1
    while page_no <= MAX_PAGES:
        resp = await client.get(
            url,
            params={"page_no": page_no, "page_size": PAGE_SIZE, "language": "zh-CN"},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output") or {}
        items = output.get(items_key) or []
        total = int(output.get("total") or 0)
        if items:
            yield items
        if page_no * PAGE_SIZE >= total or not items:
            return
        page_no += 1


async def sync_catalog(client: httpx.AsyncClient, db: Session) -> dict:
    settings = get_settings()
    now = datetime.now()
    models_count = 0
    async for items in _paginate(client, settings.list_models_url, "models"):
        for m in items:
            mid = m.get("model")
            if not mid:
                continue
            info = m.get("model_info") or {}
            row = db.get(CatalogModel, mid)
            if row is None:
                row = CatalogModel(model=mid)
                db.add(row)
            row.name = m.get("name")
            row.description = (m.get("description") or None) and str(m.get("description"))[:1024]
            row.provider = m.get("provider")
            row.inference_provider = m.get("inference_provider")
            row.capabilities = m.get("capabilities") or []
            row.features = m.get("features") or []
            row.context_window = info.get("context_window")
            row.max_input_tokens = info.get("max_input_tokens")
            row.max_output_tokens = info.get("max_output_tokens")
            row.published_time = _parse_dt(m.get("published_time"))
            row.offline_time = _first_offline_time(m.get("inference_offline_info"))
            row.equivalent_snapshot = m.get("equivalent_snapshot")
            row.prices = m.get("prices") or []
            row.synced_at = now
        db.commit()
        models_count += len(items)

    limits_count = 0
    async for items in _paginate(client, settings.list_limits_url, "quotas"):
        for q in items:
            mid = q.get("model")
            if not mid:
                continue
            for scope, key in (("account", "model_limit"), ("workspace", "workspace_limit")):
                lim = q.get(key)
                if not isinstance(lim, dict):
                    continue
                row = (
                    db.query(CatalogLimit)
                    .filter(CatalogLimit.model == mid, CatalogLimit.scope == scope)
                    .one_or_none()
                )
                if row is None:
                    row = CatalogLimit(model=mid, scope=scope)
                    db.add(row)
                row.workspace_id = q.get("workspace_id")
                row.request_limit = lim.get("request_limit")
                row.request_limit_period = lim.get("request_limit_period")
                row.usage_limit = lim.get("usage_limit")
                row.usage_limit_field = lim.get("usage_limit_field")
                row.usage_limit_period = lim.get("usage_limit_period")
                row.synced_at = now
        db.commit()
        limits_count += len(items)

    return {"models": models_count, "limits": limits_count}
