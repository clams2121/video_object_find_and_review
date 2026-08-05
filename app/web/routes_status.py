from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.db import session_scope
from app.logging_utils import log_file_path
from app.models import Clip, WorkerEvent
from app.worker.status import status as worker_status

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/api/status")
def api_status():
    snapshot = worker_status.snapshot()
    with session_scope() as session:
        error_clip_ids = session.execute(select(Clip.id).where(Clip.status == "error")).scalars().all()
    snapshot["error_clip_count"] = len(error_clip_ids)
    return JSONResponse(snapshot)


@router.get("/errors")
def errors_page(request: Request):
    with session_scope() as session:
        events = list(
            session.execute(
                select(WorkerEvent).order_by(WorkerEvent.created_at.desc()).limit(200)
            ).scalars()
        )
        error_clips = list(
            session.execute(
                select(Clip).where(Clip.status == "error").order_by(Clip.start_time.desc())
            ).scalars()
        )
    return templates.TemplateResponse(
        request,
        "errors.html",
        {"events": events, "error_clips": error_clips, "log_path": str(log_file_path())},
    )
