"""模型目录、同步触发与额度规则编辑。"""

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from .. import quota
from ..db import SessionLocal, get_db
from ..models import CatalogLimit, CatalogModel, QuotaRule
from ..sync import sync_catalog

router = APIRouter()


@router.get("/api/health")
def health():
    return {"ok": True}


@router.get("/api/catalog")
def api_catalog(db=Depends(get_db)):
    """目录列表。只返回看板表格用到的字段（prices/description 等大字段不下发，
    354 个模型的完整目录从 ~360KB 减到 ~100KB）。"""
    limits = {
        row.model: row
        for row in db.execute(select(CatalogLimit).where(CatalogLimit.scope == "account")).scalars()
    }
    items = []
    for cat in db.execute(select(CatalogModel).order_by(CatalogModel.provider, CatalogModel.model)).scalars():
        rule = quota.get_rule(db, cat.model)
        lim = limits.get(cat.model)
        items.append(
            {
                "model": cat.model,
                "name": cat.name,
                "provider": cat.provider,
                "capabilities": cat.capabilities or [],
                "context_window": cat.context_window,
                "published_time": cat.published_time.isoformat() if cat.published_time else None,
                "offline_time": cat.offline_time.isoformat() if cat.offline_time else None,
                "synced_at": cat.synced_at.isoformat(timespec="seconds") if cat.synced_at else None,
                "rate_limit": {
                    "request_limit": lim.request_limit if lim else None,
                    "request_limit_period": lim.request_limit_period if lim else None,
                    "usage_limit": lim.usage_limit if lim else None,
                    "usage_limit_field": lim.usage_limit_field if lim else None,
                },
                "has_quota_rule": rule is not None,
            }
        )
    return {"items": items, "count": len(items)}


@router.post("/api/catalog/sync")
async def api_sync(request: Request):
    client = request.app.state.http
    with SessionLocal() as db:
        result = await sync_catalog(client, db)
    return {"ok": True, **result}


@router.put("/api/quota/{model}")
def api_put_quota(model: str, body: dict, db=Depends(get_db)):
    fields: dict = {}
    if "total_tokens" in body:
        fields["total_tokens"] = max(0, int(body["total_tokens"]))
    if "effective_from" in body and body["effective_from"]:
        fields["effective_from"] = date.fromisoformat(str(body["effective_from"]))
    if "valid_days" in body:
        fields["valid_days"] = max(1, int(body["valid_days"]))
    if "used_offset" in body:
        fields["used_offset"] = max(0, int(body["used_offset"]))
    if "note" in body:
        fields["note"] = str(body["note"])[:255]
    if "exhausted" in body:
        fields["exhausted"] = bool(body["exhausted"])
    if not fields:
        return {"error": {"message": "没有可更新字段", "code": "TT.NoFields"}}
    quota.upsert_rule(db, model, **fields)
    st = quota.compute_status(db, model)
    return st.to_dict() if st else {"ok": True}
