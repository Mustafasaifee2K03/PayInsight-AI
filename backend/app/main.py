"""FastAPI application entry point."""
from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.auth_routes import router as auth_router
from .api.routes import router
from .config import get_settings
from .core.errors import register_exception_handlers
from .core.logging import configure_logging, request_id_var
from .core.security import jwt_secret
from .database.app_store import init_app_store
from .services.auth import seed_demo_users, startup_housekeeping
from .services.scenarios import restore_active

log = logging.getLogger("payinsight.http")
_RID_RE = re.compile(r"[A-Za-z0-9._-]{8,64}")


def startup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_app_store()
    jwt_secret()  # fail fast on a weak configured secret; create the persisted one on first run
    seed_demo_users()
    startup_housekeeping()  # purge expired sessions / audit rows past retention
    restore_active()  # generates the active profile's database on first run


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PayInsight AI", version="1.0.0", lifespan=lifespan,
                  description="Enterprise AI-powered payments business analyst — local deterministic analysis engine, no external AI API.")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                       allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Requested-With"])
    register_exception_handlers(app)

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        # Accept a well-formed upstream id (load balancer / gateway) so one id follows the request across tiers.
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _RID_RE.fullmatch(incoming) else uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        log.info("request", extra={"request_id": rid, "method": request.method, "path": request.url.path,
                                   "status": response.status_code, "ms": round((time.perf_counter() - t0) * 1000, 1)})
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    app.include_router(auth_router)
    app.include_router(router)
    return app


app = create_app()
