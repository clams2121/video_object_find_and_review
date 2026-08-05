from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import (
    AppConfig,
    DetectionConfig,
    EventGroupingConfig,
    OutputConfig,
    YoloConfig,
    get_config,
    save_config,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/config")
def config_page(request: Request):
    cfg = get_config()
    return templates.TemplateResponse(request, "config.html", {"cfg": cfg})


@router.post("/config")
def update_config(
    watch_directories: str = Form(""),
    scan_interval_seconds: int = Form(60),
    min_file_age_seconds: int = Form(30),
    good_dir: str = Form(...),
    maybe_dir: str = Form(...),
    no_detect_dir: str = Form(...),
    trash_dir: str = Form(...),
    overlap_tolerance_seconds: float = Form(5),
    min_frames: int = Form(5),
    min_size_ratio: float = Form(0.01),
    max_size_ratio: float = Form(0.9),
    min_duration_seconds: float = Form(0.5),
    ambiguous_band_low: float = Form(0.35),
    ambiguous_band_high: float = Form(0.65),
    yolo_enabled: bool = Form(False),
    yolo_model: str = Form("yolov8n.pt"),
    yolo_device: str = Form("auto"),
    yolo_confidence_threshold: float = Form(0.4),
    yolo_classes: str = Form(""),
):
    cfg = get_config()

    new_cfg = AppConfig(
        server=cfg.server,
        watch_directories=[line.strip() for line in watch_directories.splitlines() if line.strip()],
        scan_interval_seconds=scan_interval_seconds,
        min_file_age_seconds=min_file_age_seconds,
        output=OutputConfig(
            good_dir=good_dir,
            maybe_dir=maybe_dir,
            no_detect_dir=no_detect_dir,
            trash_dir=trash_dir,
        ),
        database_path=cfg.database_path,
        event_grouping=EventGroupingConfig(overlap_tolerance_seconds=overlap_tolerance_seconds),
        detection=DetectionConfig(
            min_frames=min_frames,
            min_size_ratio=min_size_ratio,
            max_size_ratio=max_size_ratio,
            min_duration_seconds=min_duration_seconds,
            ambiguous_band=[ambiguous_band_low, ambiguous_band_high],
        ),
        yolo=YoloConfig(
            enabled=yolo_enabled,
            model=yolo_model,
            device=yolo_device,
            confidence_threshold=yolo_confidence_threshold,
            classes=[c.strip() for c in yolo_classes.split(",") if c.strip()],
        ),
        json_field_map=cfg.json_field_map,
    )
    save_config(new_cfg)
    return RedirectResponse("/config", status_code=303)
