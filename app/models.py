from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class UsageRecord(Base):
    """每次上游调用一行（自动切换会为每个尝试的模型各记一行）。"""

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    requested_model: Mapped[str] = mapped_column(String(128), index=True)
    actual_model: Mapped[str] = mapped_column(String(128), index=True)
    tier: Mapped[str | None] = mapped_column(String(64))
    switched: Mapped[bool] = mapped_column(Boolean, default=False)
    switch_reason: Mapped[str | None] = mapped_column(String(128))

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)

    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    stream: Mapped[bool] = mapped_column(Boolean, default=False)


class QuotaRule(Base):
    """每个模型的免费额度规则（账本）。"""

    __tablename__ = "quota_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=1_000_000)
    effective_from: Mapped[date] = mapped_column(Date)
    valid_days: Mapped[int] = mapped_column(Integer, default=90)
    used_offset: Mapped[int] = mapped_column(Integer, default=0)
    exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class CatalogModel(Base):
    """ListModels 同步来的模型目录。"""

    __tablename__ = "catalog_models"

    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1024))
    provider: Mapped[str | None] = mapped_column(String(64))
    inference_provider: Mapped[str | None] = mapped_column(String(64))
    capabilities: Mapped[list | None] = mapped_column(JSON)
    features: Mapped[list | None] = mapped_column(JSON)
    context_window: Mapped[int | None] = mapped_column(Integer)
    max_input_tokens: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    published_time: Mapped[datetime | None] = mapped_column(DateTime)
    offline_time: Mapped[datetime | None] = mapped_column(DateTime)
    equivalent_snapshot: Mapped[str | None] = mapped_column(String(128))
    prices: Mapped[dict | list | None] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class CatalogLimit(Base):
    """models/limits 同步来的限流配置（账号级/空间级）。"""

    __tablename__ = "catalog_limits"
    __table_args__ = (UniqueConstraint("model", "scope", name="uq_limit_model_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    scope: Mapped[str] = mapped_column(String(32))  # account | workspace
    workspace_id: Mapped[str | None] = mapped_column(String(64))
    request_limit: Mapped[int | None] = mapped_column(Integer)
    request_limit_period: Mapped[int | None] = mapped_column(Integer)
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    usage_limit_field: Mapped[str | None] = mapped_column(String(64))
    usage_limit_period: Mapped[int | None] = mapped_column(Integer)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
