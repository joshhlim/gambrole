"""FastAPI entry point. Run with: uvicorn app.main:app --reload"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import auth as auth_router
from .routers import debts as debts_router
from .routers import history as history_router
from .routers import mahjong as mahjong_router
from .routers import rooms as rooms_router
from .routers import stats as stats_router

app = FastAPI(title="Taidi API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(rooms_router.router)
app.include_router(mahjong_router.router)
app.include_router(stats_router.router)
app.include_router(debts_router.router)
app.include_router(history_router.router)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok"}
