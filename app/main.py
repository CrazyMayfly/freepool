from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import quota
from .config import BASE_DIR, get_settings
from .db import SessionLocal, init_db
from .routers import catalog, dashboard, gateway, settings
from .scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        quota.seed_rules(db)
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)
    )
    app.state.scheduler = start_scheduler()
    yield
    app.state.scheduler.shutdown(wait=False)
    await app.state.http.aclose()


app = FastAPI(title="freepool", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(gateway.router)
app.include_router(dashboard.router)
app.include_router(catalog.router)
app.include_router(settings.router)

_dist = BASE_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
