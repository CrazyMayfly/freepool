from datetime import date, datetime, timedelta

from app import quota
from app.db import SessionLocal, init_db
from app.models import UsageRecord


def _db():
    init_db()
    return SessionLocal()


def _add_usage(db, model, total, ts=None, inp=None, out=None):
    db.add(
        UsageRecord(
            ts=ts or datetime.now(),
            requested_model=model,
            actual_model=model,
            input_tokens=inp if inp is not None else total,
            output_tokens=out if out is not None else 0,
            total_tokens=total,
        )
    )
    db.commit()


def test_status_normal_and_low():
    with _db() as db:
        quota.upsert_rule(db, "m1", total_tokens=1_000_000, effective_from=date.today())
        _add_usage(db, "m1", 100_000)
        st = quota.compute_status(db, "m1")
        assert st.status == quota.STATUS_NORMAL
        assert st.remaining_tokens == 900_000
        assert st.used_tokens == 100_000

        _add_usage(db, "m1", 850_000)
        st = quota.compute_status(db, "m1")
        assert st.status == quota.STATUS_LOW  # 剩余 5% < 20%


def test_status_exhausted_via_usage_and_flag():
    with _db() as db:
        quota.upsert_rule(db, "m2", total_tokens=1000, effective_from=date.today())
        _add_usage(db, "m2", 1000)
        assert quota.compute_status(db, "m2").status == quota.STATUS_EXHAUSTED

        # used_offset 也计入
        quota.upsert_rule(db, "m3", total_tokens=1000, effective_from=date.today())
        _add_usage(db, "m3", 600)
        quota.upsert_rule(db, "m3", used_offset=400)
        assert quota.compute_status(db, "m3").status == quota.STATUS_EXHAUSTED

        # 403 标记（账本余量未到 0 也算）
        quota.upsert_rule(db, "m4", total_tokens=10_000, effective_from=date.today())
        quota.mark_exhausted(db, "m4")
        assert quota.compute_status(db, "m4").status == quota.STATUS_EXHAUSTED
        assert quota.compute_status(db, "m4").remaining_tokens == 10_000


def test_status_expired_and_window():
    with _db() as db:
        old = date.today() - timedelta(days=100)
        quota.upsert_rule(db, "m5", total_tokens=1000, effective_from=old, valid_days=90)
        _add_usage(db, "m5", 100, ts=datetime.now() - timedelta(days=95))  # 窗口内
        _add_usage(db, "m5", 500, ts=datetime.now() - timedelta(days=5))  # 过期后
        st = quota.compute_status(db, "m5")
        assert st.status == quota.STATUS_EXPIRED
        # 过期后的用量不计入该窗口
        assert st.metered_tokens == 100
        assert st.used_tokens == 100


def test_overview_totals_and_today():
    with _db() as db:
        quota.upsert_rule(db, "m6", total_tokens=1000, effective_from=date.today())
        _add_usage(db, "m6", 300)
        ov = quota.overview(db)
        assert ov["totals"]["total_free"] >= 1000
        assert ov["totals"]["today_tokens"] >= 300
        assert any(m["model"] == "m6" for m in ov["models"])
