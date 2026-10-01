"""FastAPI entry point. Run with: uvicorn app.main:app --reload"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import settings
from .db import engine
from .routers import auth as auth_router
from .routers import debts as debts_router
from .routers import friends as friends_router
from .routers import history as history_router
from .routers import local_auth as local_auth_router
from .routers import mahjong as mahjong_router
from .routers import notifications as notifications_router
from .routers import rooms as rooms_router
from .routers import stats as stats_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Every request body here is a handful of fields; anything bigger is a
# mistake or an attack, and rejecting it before parsing keeps a single
# worker from spending its time validating it.
MAX_BODY_BYTES = 64 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Fail closed: see Settings.auth_mode for why there's no default.
    if settings.auth_mode is None:
        raise RuntimeError("TAIDI_AUTH_MODE must be set to 'dev', 'supabase' or 'local'.")
    if settings.auth_mode == "local" and len(settings.local_jwt_secret or "") < 32:
        raise RuntimeError("TAIDI_AUTH_MODE=local needs TAIDI_LOCAL_JWT_SECRET (32+ characters).")
    yield


app = FastAPI(title="GamBROle API", version="0.7.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Auth is a bearer header, never a cookie, so browsers needn't send
    # credentials cross-origin.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def limit_body_size(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request body too large."}, status_code=413)
    return await call_next(request)


app.include_router(auth_router.router)
app.include_router(local_auth_router.router)
app.include_router(rooms_router.router)
app.include_router(mahjong_router.router)
app.include_router(stats_router.router)
app.include_router(debts_router.router)
app.include_router(friends_router.router)
app.include_router(notifications_router.router)
app.include_router(history_router.router)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Shallow on purpose: Render restarts the service when this fails, and a
    database blip isn't something a restart fixes."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Can this instance actually serve requests? Touches the database, so
    pinging it also keeps a free-tier Supabase project from pausing."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logging.getLogger(__name__).exception("Readiness check failed")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
