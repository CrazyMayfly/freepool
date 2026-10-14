from apscheduler.schedulers.asyncio import AsyncIOScheduler
import httpx

from .config import get_settings
from .db import SessionLocal
from .sync import sync_catalog


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(_daily_sync, "cron", hour=get_settings().sync_hour, minute=0)
    scheduler.start()
    return scheduler


async def _daily_sync() -> None:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            with SessionLocal() as db:
                await sync_catalog(client, db)
    except Exception as exc:  # 调度任务异常只记日志，不打挂服务
        print(f"[scheduler] catalog sync failed: {exc}")
