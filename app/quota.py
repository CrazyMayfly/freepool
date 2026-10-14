"""额度账本：规则加载、用量聚合、剩余/到期/状态计算。"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings, load_yaml
from .models import CatalogModel, QuotaRule, UsageRecord

STATUS_NORMAL = "normal"
STATUS_LOW = "low"
STATUS_EXHAUSTED = "exhausted"
STATUS_EXPIRED = "expired"
STATUS_OFFLINE = "offline"

# 可承接请求的状态（档位健康度判断用）；unknown = 尚未建规则，首次调用会自动建，视为可用
USABLE_OK = {STATUS_NORMAL, STATUS_LOW}
USABLE_OR_UNKNOWN = USABLE_OK | {"unknown"}


@dataclass
class ModelQuota:
    model: str
    total_tokens: int
    used_tokens: int
    metered_tokens: int
    used_offset: int
    remaining_tokens: int
    percent: float
    effective_from: date
    valid_days: int
    expires_at: date
    days_left: int
    status: str
    exhausted_flag: bool = field(default=False)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "total_tokens": self.total_tokens,
            "used_tokens": self.used_tokens,
            "metered_tokens": self.metered_tokens,
            "used_offset": self.used_offset,
            "remaining_tokens": self.remaining_tokens,
            "percent": round(self.percent, 4),
            "effective_from": self.effective_from.isoformat(),
            "valid_days": self.valid_days,
            "expires_at": self.expires_at.isoformat(),
            "days_left": self.days_left,
            "status": self.status,
        }


def get_rule(db: Session, model: str) -> QuotaRule | None:
    return db.execute(
        select(QuotaRule).where(QuotaRule.model == model)
    ).scalar_one_or_none()


def upsert_rule(db: Session, model: str, **fields) -> QuotaRule:
    rule = get_rule(db, model)
    if rule is None:
        seed = (_seed_conf().get("models") or {}).get(model) or {}
        rule = QuotaRule(
            model=model,
            total_tokens=seed.get("total_tokens", _defaults()["total"]),
            effective_from=_resolve_effective_from(model, seed),
            valid_days=seed.get("valid_days", _defaults()["days"]),
        )
        db.add(rule)
    for key, value in fields.items():
        if value is None:
            continue
        setattr(rule, key, value)
    db.commit()
    return rule


def ensure_rule(db: Session, model: str) -> QuotaRule:
    rule = get_rule(db, model)
    if rule is None:
        return upsert_rule(db, model)
    return rule


def seed_rules(db: Session) -> int:
    """启动时按 free_models.yaml 补齐规则（不覆盖已存在行）。"""
    conf = _seed_conf()
    created = 0
    for model in conf.get("models") or {}:
        if get_rule(db, model) is None:
            upsert_rule(db, model)
            created += 1
    return created


def mark_exhausted(db: Session, model: str, exhausted: bool = True) -> None:
    rule = ensure_rule(db, model)
    if rule.exhausted != exhausted:
        rule.exhausted = exhausted
        db.commit()


def metered_usage(
    db: Session, model: str, since: datetime, until: datetime | None = None
) -> tuple[int, int, int, int]:
    """窗口期内的 (input, output, total, requests)。"""
    q = select(
        func.coalesce(func.sum(UsageRecord.input_tokens), 0),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0),
        func.count(UsageRecord.id),
    ).where(
        UsageRecord.actual_model == model,
        UsageRecord.ts >= since,
    )
    if until is not None:
        q = q.where(UsageRecord.ts < until)
    row = db.execute(q).one()
    return int(row[0]), int(row[1]), int(row[2]), int(row[3])


def compute_status(
    db: Session,
    model: str,
    *,
    now: datetime | None = None,
    rule: QuotaRule | None = None,
    offline: bool = False,
) -> ModelQuota | None:
    now = now or datetime.now()
    rule = rule or get_rule(db, model)
    if rule is None:
        return None
    window_start = datetime.combine(rule.effective_from, datetime.min.time())
    expires_at = rule.effective_from + timedelta(days=rule.valid_days)
    # 过期后产生的用量不属于这个免费窗口
    window_end = datetime.combine(expires_at + timedelta(days=1), datetime.min.time())
    inp, outp, total, _reqs = metered_usage(db, model, window_start, until=window_end)
    used = total + rule.used_offset
    remaining = max(rule.total_tokens - used, 0)
    percent = (used / rule.total_tokens) if rule.total_tokens else 0.0
    days_left = (expires_at - now.date()).days

    if offline:
        status = STATUS_OFFLINE
    elif days_left < 0:
        status = STATUS_EXPIRED
    elif rule.exhausted or remaining <= 0:
        status = STATUS_EXHAUSTED
    elif rule.total_tokens and remaining / rule.total_tokens < get_settings().free_quota_low_percent:
        status = STATUS_LOW
    else:
        status = STATUS_NORMAL

    return ModelQuota(
        model=model,
        total_tokens=rule.total_tokens,
        used_tokens=used,
        metered_tokens=total,
        used_offset=rule.used_offset,
        remaining_tokens=remaining,
        percent=percent,
        effective_from=rule.effective_from,
        valid_days=rule.valid_days,
        expires_at=expires_at,
        days_left=days_left,
        status=status,
        exhausted_flag=rule.exhausted,
    )


def all_models(db: Session) -> list[str]:
    """规则表 ∪ 已有计量的模型。"""
    in_rules = set(db.execute(select(QuotaRule.model)).scalars())
    in_usage = set(db.execute(select(UsageRecord.actual_model).distinct()).scalars())
    return sorted(in_rules | in_usage)


def offline_models(db: Session) -> set[str]:
    now = datetime.now()
    rows = db.execute(select(CatalogModel.model, CatalogModel.offline_time)).all()
    return {m for m, off in rows if off is not None and off <= now}


def overview(db: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    offline = offline_models(db)
    models_view = []
    for model in all_models(db):
        st = compute_status(db, model, now=now, offline=model in offline)
        if st is None:
            continue
        entry = st.to_dict()
        cat = db.get(CatalogModel, model)
        if cat:
            entry.update(
                {
                    "provider": cat.provider,
                    "context_window": cat.context_window,
                    "published_time": cat.published_time.isoformat() if cat.published_time else None,
                    "offline_time": cat.offline_time.isoformat() if cat.offline_time else None,
                }
            )
        models_view.append(entry)

    with_quota = [m for m in models_view if m["total_tokens"] > 0]
    today_start = datetime.combine(now.date(), datetime.min.time())
    today_row = db.execute(
        select(
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
            func.count(UsageRecord.id),
        ).where(UsageRecord.ts >= today_start)
    ).one()

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "totals": {
            "total_free": sum(m["total_tokens"] for m in with_quota),
            "total_used": sum(m["used_tokens"] for m in with_quota),
            "total_remaining": sum(m["remaining_tokens"] for m in with_quota),
            "today_tokens": int(today_row[0]),
            "today_requests": int(today_row[1]),
            "expiring_soon": sum(
                1
                for m in with_quota
                if 0 <= m["days_left"] <= 7 and m["remaining_tokens"] > 0
            ),
        },
        "models": sorted(models_view, key=lambda m: m["remaining_tokens"], reverse=True),
    }


# ---- 种子/默认值解析 -----------------------------------------------------------


def _seed_conf() -> dict:
    return load_yaml("free_models.yaml")


def _defaults() -> dict:
    s = get_settings()
    conf = _seed_conf()
    return {
        "total": conf.get("default_total_tokens", s.default_total_tokens),
        "days": conf.get("default_valid_days", s.default_valid_days),
    }


def _resolve_effective_from(model: str, seed: dict) -> date:
    if seed.get("effective_from"):
        return date.fromisoformat(str(seed["effective_from"]))
    conf_default = _seed_conf().get("default_effective_from")
    if conf_default:
        return date.fromisoformat(str(conf_default))
    # 优先用目录里的 published_time（90 天窗口自模型发布起算的口径）
    try:
        from .db import SessionLocal

        with SessionLocal() as db:
            cat = db.get(CatalogModel, model)
            if cat and cat.published_time:
                return cat.published_time.date()
    except Exception:
        pass
    return date.today()
