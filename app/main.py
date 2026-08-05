from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_config
from app.db import init_db
from app.logging_utils import attach_db_log_handler, setup_console_and_file_logging
from app.web.routes_admin import router as admin_router
from app.web.routes_clips import router as clips_router
from app.web.routes_config import router as config_router
from app.web.routes_status import router as status_router
from app.worker.pipeline import run_scan_cycle
from app.worker.status import status as worker_status

setup_console_and_file_logging()
logger = logging.getLogger(__name__)

_stop_event = threading.Event()


def _worker_loop() -> None:
    while not _stop_event.is_set():
        try:
            run_scan_cycle()
        except Exception:
            # run_scan_cycle already handles scan/per-clip failures internally;
            # this is a last-resort net so a truly unexpected bug can't leave
            # the status bar stuck showing "processing" forever.
            logger.exception("Scan cycle failed unexpectedly")
            worker_status.record_error("Scan cycle failed unexpectedly - see log for details")
            worker_status.finish_cycle()
        interval = get_config().scan_interval_seconds
        _stop_event.wait(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    attach_db_log_handler()
    thread = threading.Thread(target=_worker_loop, daemon=True)
    thread.start()
    yield
    _stop_event.set()


app = FastAPI(title="Camera Clip Review", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(clips_router)
app.include_router(config_router)
app.include_router(status_router)
app.include_router(admin_router)


def main() -> None:
    import uvicorn

    cfg = get_config()
    # Pass the app object directly (not the "app.main:app" import string) so
    # `python -m app.main` doesn't cause this module to be imported twice
    # under two different names (__main__ and app.main), which would
    # double-attach logging handlers and duplicate every log line.
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port)


if __name__ == "__main__":
    main()
