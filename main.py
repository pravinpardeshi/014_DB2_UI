from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path so sibling modules can be imported
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import load_settings
from database import init_database
from routers.jobs import router as jobs_router

logger = logging.getLogger(__name__)

settings = load_settings()
app = FastAPI(
    title="Mainframe Job Monitor",
    description="Monitor Mainframe job statuses via ODBC",
    version="1.0.0",
)

app.include_router(jobs_router)

# --- Application mode state lives in services.py to avoid circular imports ---
from services import get_app_mode, set_app_mode  # noqa: E402

set_app_mode(settings.app_mode if settings.app_mode in ("demo", "production") else "demo")


class ModeResponse(BaseModel):
    mode: str


class ModeRequest(BaseModel):
    mode: str


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.on_event("startup")
def startup():
    try:
        init_database(settings)
        logger.info("Database connection initialized")
    except Exception as e:
        logger.warning("Could not connect to Mainframe ODBC: %s. Running in demo mode.", e)


@app.on_event("shutdown")
def shutdown():
    from database import db

    if db:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "mode": get_app_mode()}


@app.get("/api/mode", response_model=ModeResponse)
def get_mode():
    return ModeResponse(mode=get_app_mode())


@app.post("/api/mode", response_model=ModeResponse)
def set_mode(req: ModeRequest):
    if req.mode not in ("demo", "production"):
        raise HTTPException(status_code=400, detail="Mode must be 'demo' or 'production'")
    set_app_mode(req.mode)
    logger.info("Application mode switched to: %s", req.mode)
    return ModeResponse(mode=req.mode)


def run():
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )
