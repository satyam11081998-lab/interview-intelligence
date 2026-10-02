"""MECE Interview Intelligence — FastAPI application (independent service).

    uvicorn interview_intelligence.main:app --host 0.0.0.0 --port $PORT --workers 1
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .errors import IIError
from .versions import versions


def _register_job_handlers() -> None:
    # Importing registers @register(...) handlers with the queue.
    from .documents import analysis  # noqa: F401
    from .drive_integration import sync  # noqa: F401
    from .evidence_engine import extractor  # noqa: F401
    from .interview_engine import blueprint  # noqa: F401
    from .report_engine import assessment  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logging.basicConfig(level=s.log_level)
    _register_job_handlers()
    from .access.policy import bootstrap_test_grants
    from .db.session import db_session
    from .security.crypto import _get as _crypto_ready
    if s.is_production and s.is_sqlite:
        # Fail fast: a forgotten II_DATABASE_URL would otherwise run on an in-memory database.
        raise RuntimeError("II_DATABASE_URL must point to Postgres in production (II_ENV is not dev/test/qa).")
    if s.is_production and s.drive_configured and not s.drive_folder_salt:
        logging.getLogger("ii").error("II_DRIVE_FOLDER_SALT is not set: Drive folder names use the public default salt.")
    _crypto_ready()  # fail fast in prod without an encryption key
    try:
        with db_session() as db:
            bootstrap_test_grants(db)
    except Exception:  # noqa: BLE001 - the service must still boot to report health
        logging.getLogger("ii").exception("bootstrap failed (database reachable? migration run?)")
    worker = sweeper = None
    if s.worker_threads > 0:
        from .jobs.maintenance import Sweeper
        from .jobs.queue import Worker
        worker = Worker(threads=s.worker_threads)
        worker.start()
        sweeper = Sweeper()
        sweeper.start()
    yield
    if worker:
        worker.stop()
    if sweeper:
        sweeper.stop()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="MECE Interview Intelligence", version=versions()["service"], lifespan=lifespan,
                  docs_url=None if s.is_production else "/docs", redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_origin_regex=s.cors_origin_regex,
                       allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type"], max_age=600)

    @app.exception_handler(IIError)
    async def _ii(_: Request, exc: IIError):
        return JSONResponse(status_code=exc.status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", [])[1:])
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request",
                                                                "message": f"Invalid request: {loc} {first.get('msg', '')}".strip()}})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logging.getLogger("ii").exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": {"code": "internal",
                                                                "message": "Something went wrong. Please try again."}})

    @app.get("/healthz")
    def healthz():
        ok = True
        try:
            from .db.session import get_engine
            with get_engine().connect() as c:
                c.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            ok = False
        return {"ok": ok, "service": "interview-intelligence", "version": versions()["service"],
                "assertion_keys": len(get_settings().assertion_public_keys),
                "drive_configured": get_settings().drive_configured}

    from .api.admin_routes import router as admin_router
    from .api.routes import router as api_router
    from .voice.routes import router as voice_router
    app.include_router(api_router)
    app.include_router(admin_router)
    app.include_router(voice_router)
    return app


app = create_app()
