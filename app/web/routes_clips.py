from __future__ import annotations

import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_config
from app.db import session_scope
from app.models import Clip
from app.worker.pipeline import move_clip_to_trash, record_feedback, reprocess_clip

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

# "bad" in the UI means no_detect specifically - not maybe/error, since those
# still need a human look and bulk-hiding/deleting them could lose something
# unreviewed or mask a real processing bug.
_FILTER_TO_STATUS = {"good": "good", "bad": "no_detect"}


def _status_filter_from_param(filter_param: str) -> str | None:
    """Maps ?filter= to the Clip.status to restrict to, or None for 'all'
    (and for any unrecognized value, so a bad query param degrades to
    showing everything rather than an empty page)."""
    return _FILTER_TO_STATUS.get(filter_param)


@router.get("/")
def tile_view(request: Request, filter: str = "good"):
    status_filter = _status_filter_from_param(filter)

    with session_scope() as session:
        stmt = select(Clip).where(Clip.status != "trashed")
        if status_filter is not None:
            stmt = stmt.where(Clip.status == status_filter)
        clips = list(session.execute(stmt.order_by(Clip.start_time.desc())).scalars())

        groups_by_day: dict[str, dict[str, list[Clip]]] = defaultdict(lambda: defaultdict(list))
        for clip in clips:
            day_key = clip.start_time.strftime("%Y-%m-%d")
            hour_key = clip.start_time.strftime("%H")
            groups_by_day[day_key][hour_key].append(clip)

        days = []
        for day_key in sorted(groups_by_day.keys(), reverse=True):
            hours = []
            for hour_key in sorted(groups_by_day[day_key].keys(), reverse=True):
                hour_clips = groups_by_day[day_key][hour_key]
                hours.append({"hour": hour_key, "clips": hour_clips, "count": len(hour_clips)})
            days.append({"day": day_key, "hours": hours})

    return templates.TemplateResponse(request, "clips.html", {"days": days, "current_filter": filter})


@router.get("/video/{clip_id}")
def get_video(clip_id: int):
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(404)
        # Clips that errored out before the move step still have their
        # video at source_video_path rather than output_video_path.
        path = clip.output_video_path or clip.source_video_path
        if not path:
            raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


@router.get("/thumb/{clip_id}")
def get_thumb(clip_id: int):
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None or not clip.thumbnail_path:
            raise HTTPException(404)
        path = clip.thumbnail_path
    return FileResponse(path, media_type="image/jpeg")


@router.post("/clips/{clip_id}/feedback")
def post_feedback(clip_id: int, label: str = Form(...)):
    if label not in ("good", "bad"):
        raise HTTPException(400, "label must be 'good' or 'bad'")
    cfg = get_config()
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(404)
        record_feedback(session, clip, label, cfg)
    return JSONResponse({"ok": True})


@router.post("/clips/{clip_id}/reprocess")
def reprocess(clip_id: int):
    cfg = get_config()
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(404)
        reprocess_clip(session, clip, cfg)
        result_status = clip.status
    return JSONResponse({"ok": True, "status": result_status})


class ClipIdsRequest(BaseModel):
    clip_ids: list[int]


@router.post("/clips/reprocess")
def reprocess_selected(body: ClipIdsRequest):
    # reprocess_clip() itself no-ops on trashed clips, so nothing extra
    # needed here to keep them untouched.
    cfg = get_config()
    with session_scope() as session:
        for clip_id in body.clip_ids:
            clip = session.get(Clip, clip_id)
            if clip is not None:
                reprocess_clip(session, clip, cfg)
    return JSONResponse({"ok": True})


@router.post("/clips/delete")
def delete_clips(body: ClipIdsRequest):
    cfg = get_config()
    with session_scope() as session:
        for clip_id in body.clip_ids:
            clip = session.get(Clip, clip_id)
            if clip is not None and clip.status != "trashed":
                move_clip_to_trash(clip, cfg)
    return JSONResponse({"ok": True})


@router.post("/clips/delete_all_bad")
def delete_all_bad():
    cfg = get_config()
    with session_scope() as session:
        clips = session.execute(select(Clip).where(Clip.status == "no_detect")).scalars()
        count = 0
        for clip in clips:
            move_clip_to_trash(clip, cfg)
            count += 1
    return JSONResponse({"ok": True, "count": count})


@router.post("/clips/delete_hour")
def delete_hour(day: str = Form(...), hour: str = Form(...), filter: str = Form("all")):
    try:
        day_start = dt.datetime.strptime(f"{day} {hour}", "%Y-%m-%d %H")
    except ValueError:
        raise HTTPException(400, "invalid day/hour")
    day_end = day_start + dt.timedelta(hours=1)

    # Scope to whatever status the page had filtered to, so this only
    # deletes what was actually visible on screen.
    status_filter = _status_filter_from_param(filter)

    cfg = get_config()
    with session_scope() as session:
        stmt = select(Clip).where(
            Clip.start_time >= day_start,
            Clip.start_time < day_end,
            Clip.status != "trashed",
        )
        if status_filter is not None:
            stmt = stmt.where(Clip.status == status_filter)
        clips = session.execute(stmt).scalars()
        for clip in clips:
            move_clip_to_trash(clip, cfg)
    return JSONResponse({"ok": True})
