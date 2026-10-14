from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    if url == "sqlite://":  # 测试用内存库：单连接共享
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})


settings = get_settings()
engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401 确保表定义已加载

    if settings.database_url.startswith("sqlite:///") and settings.database_url != "sqlite://":
        from pathlib import Path

        db_file = settings.database_url.removeprefix("sqlite:///")
        if db_file:
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
