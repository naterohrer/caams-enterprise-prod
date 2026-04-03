"""CAAMS Enterprise — Unified Audit Platform. FastAPI application entry point."""

import os
import pathlib
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from sqlalchemy import text as _sa_text

from app.database import DATABASE_URL, engine
from app import models
from app.limiter import limiter
from app.logging_config import get_logger, setup_logging

# Routers
from app.routers import (
    auth as auth_router,
    frameworks as frameworks_router,
    tools as tools_router,
    assessments as assessments_router,
    evidence as evidence_router,
    findings as findings_router,
    audit_log as audit_log_router,
    export as export_router,
    pdf_export as pdf_export_router,
    dashboard as dashboard_router,
    rfi as rfi_router,
    api_tokens as api_tokens_router,
    crosswalk as crosswalk_router,
    auditor_shares as auditor_shares_router,
    importers_router,
    mfa as mfa_router,
    oidc as oidc_router,
    admin as admin_router,
)

setup_logging()
log = get_logger("caams.app")

VERSION = "1.1.0"
SECRET_KEY = os.environ.get("CAAMS_SECRET_KEY", "")
ENABLE_DOCS = os.environ.get("CAAMS_ENABLE_DOCS", "").lower() in ("1", "true", "yes")

# Maximum upload size in bytes.  Controls both the per-file evidence limit and
# the global Content-Length guard applied to every request.
# Set CAAMS_MAX_UPLOAD_MB to override (default: 50 MB).
try:
    MAX_UPLOAD_BYTES = int(os.environ.get("CAAMS_MAX_UPLOAD_MB", "50")) * 1024 * 1024
except ValueError:
    raise RuntimeError("CAAMS_MAX_UPLOAD_MB must be an integer (e.g. 50)")

if not SECRET_KEY:
    raise RuntimeError(
        "CAAMS_SECRET_KEY environment variable is not set. "
        "Generate one with: python3 -c 'import secrets; print(secrets.token_hex(32))'"
    )
if len(SECRET_KEY) < 32:
    raise RuntimeError(
        "CAAMS_SECRET_KEY is too short (minimum 32 characters). "
        "Generate a secure key with: python3 -c 'import secrets; print(secrets.token_hex(32))'"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if DATABASE_URL.startswith("sqlite"):
        # SQLite (dev/test only): auto-create schema for convenience.
        # Production PostgreSQL schema is managed by Alembic — run:
        #   alembic upgrade head
        models.Base.metadata.create_all(bind=engine)
    log.info("STARTUP | CAAMS Enterprise v%s | database ready", VERSION)
    yield
    log.info("SHUTDOWN | CAAMS Enterprise v%s", VERSION)


app = FastAPI(
    title="CAAMS Enterprise — Unified Audit Platform",
    description=(
        "Compliance and Auditing Made Simple — assessment lifecycle, evidence management, "
        "findings tracker, audit log, SOA export, and scoped external auditor access."
    ),
    version=VERSION,
    lifespan=lifespan,
    # Disable interactive API docs in production; set CAAMS_ENABLE_DOCS=true to re-enable
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
cors_origin = os.environ.get("CAAMS_CORS_ORIGIN", "")
if cors_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cors_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    log.warning(
        "CAAMS_CORS_ORIGIN is not set — CORS is disabled. "
        "Set CAAMS_CORS_ORIGIN to your frontend domain in production."
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],  # No origins allowed unless explicitly configured
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── Security headers middleware ───────────────────────────────────────────────
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}
# HSTS must only be sent when the app is behind a TLS terminator.
# Set CAAMS_USE_HSTS=true in production to enable it.
if os.environ.get("CAAMS_USE_HSTS", "").lower() in ("1", "true", "yes"):
    _SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


# ── Global request-size guard ────────────────────────────────────────────────
# Rejects any request whose Content-Length header exceeds MAX_UPLOAD_BYTES
# before the body is read.  Clients that omit Content-Length still get checked
# by the per-endpoint body read (evidence upload, importer).
@app.middleware("http")
async def reject_oversized_requests(request: Request, call_next):
    cl_header = request.headers.get("content-length")
    if cl_header:
        try:
            if int(cl_header) > MAX_UPLOAD_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)"},
                )
        except ValueError:
            pass  # malformed header — let the endpoint handle it
    return await call_next(request)


# ── Access log middleware ─────────────────────────────────────────────────────
access_log = get_logger("caams.access")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    ms = round((time.time() - start) * 1000)
    ip = request.client.host if request.client else "-"
    access_log.info("%s | %s | %s %s | %d | %dms",
                    ip, request.headers.get("x-forwarded-for", ""),
                    request.method, request.url.path, response.status_code, ms)
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(frameworks_router.router)
app.include_router(tools_router.router)
app.include_router(assessments_router.router)
app.include_router(evidence_router.router)
app.include_router(findings_router.router)
app.include_router(audit_log_router.router)
app.include_router(export_router.router)
app.include_router(pdf_export_router.router)
app.include_router(dashboard_router.router)
app.include_router(rfi_router.router)
app.include_router(api_tokens_router.router)
app.include_router(crosswalk_router.router)
app.include_router(auditor_shares_router.router)
app.include_router(importers_router.router)
app.include_router(mfa_router.router)
app.include_router(oidc_router.router)
app.include_router(admin_router.router)


# ── Health checks ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["misc"])
def health():
    """Liveness probe — confirms process is running."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["misc"])
def health_ready():
    """Readiness probe — confirms DB is reachable before accepting traffic."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        db.execute(_sa_text("SELECT 1"))
        return {"status": "ok", "version": VERSION}
    except Exception as exc:
        log.error("HEALTH_READY failed: %s", exc)
        return JSONResponse(status_code=503, content={"status": "error", "detail": "Database unavailable"})
    finally:
        db.close()


# ── Static files / SPA ───────────────────────────────────────────────────────
STATIC_DIR = pathlib.Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/privacy", include_in_schema=False)
    def privacy():
        return FileResponse(str(STATIC_DIR / "privacy.html"))

    @app.get("/terms", include_in_schema=False)
    def terms():
        return FileResponse(str(STATIC_DIR / "terms.html"))
