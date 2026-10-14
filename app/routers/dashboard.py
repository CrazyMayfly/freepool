"""看板数据接口。"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from .. import quota, tier_router
from ..db import get_db
from ..models import UsageRecord

router = APIRouter()


@router.get("/api/overview")
def api_overview(db=Depends(get_db)):
    return quota.overview(db)


@router.get("/api/tiers")
def api_tiers(db=Depends(get_db)):
    offline = quota.offline_models(db)
    tiers = tier_router.load_tiers()
    result = []
    for tier in tiers.values():
        entries = []
        for m in tier.models:
            st = quota.compute_status(db, m, offline=m in offline)
            if st is not None:
                entries.append(st.to_dict())
            else:
                entries.append({"model": m, "status": "unknown", "total_tokens": 0})
        usable = [e for e in entries if e.get("status") in quota.USABLE_OR_UNKNOWN]
        result.append(
            {
                "name": tier.name,
                "display_name": tier.display_name,
                "active_model": usable[0]["model"] if usable else None,
                "healthy": bool(usable),
                "models": entries,
            }
        )
    return {"tiers": result}


@router.get("/api/usage/series")
def api_usage_series(days: int = 30, model: str | None = None, db=Depends(get_db)):
    days = max(1, min(days, 365))
    start_date = date.today() - timedelta(days=days - 1)
    start_dt = datetime.combine(start_date, datetime.min.time())

    q = select(
        func.date(UsageRecord.ts).label("d"),
        func.coalesce(func.sum(UsageRecord.input_tokens), 0),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        func.count(UsageRecord.id),
    ).where(UsageRecord.ts >= start_dt)
    if model:
        q = q.where(UsageRecord.actual_model == model)
    q = q.group_by("d")

    by_date = {str(row[0]): (int(row[1]), int(row[2]), int(row[3])) for row in db.execute(q).all()}

    series = []
    for i in range(days):
        d = (start_date + timedelta(days=i)).isoformat()
        inp, outp, cnt = by_date.get(d, (0, 0, 0))
        series.append({"date": d, "input_tokens": inp, "output_tokens": outp, "requests": cnt})
    return {"days": days, "model": model, "series": series}


@router.get("/api/requests")
def api_requests(limit: int = 50, db=Depends(get_db)):
    limit = max(1, min(limit, 500))
    rows = db.execute(select(UsageRecord).order_by(UsageRecord.id.desc()).limit(limit)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "ts": r.ts.isoformat(timespec="seconds"),
                "requested_model": r.requested_model,
                "actual_model": r.actual_model,
                "tier": r.tier,
                "switched": r.switched,
                "switch_reason": r.switch_reason,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "cached_tokens": r.cached_tokens,
                "reasoning_tokens": r.reasoning_tokens,
                "duration_ms": r.duration_ms,
                "status_code": r.status_code,
                "error_code": r.error_code,
                "stream": r.stream,
            }
            for r in rows
        ]
    }
