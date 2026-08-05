from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_config
from app.db import init_db
from app.web.routes_clips import router as clips_router
from app.web.routes_config import router as config_router
from app.worker.pipeline import run_scan_cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_stop_event = threading.Event()


def _worker_loop() -> None:
    while not _stop_event.is_set():
        try:
            run_scan_cycle()
        except Exception:
            logger.exception("Scan cycle failed")
        interval = get_config().scan_interval_seconds
        _stop_event.wait(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    thread = threading.Thread(target=_worker_loop, daemon=True)
    thread.start()
    yield
    _stop_event.set()


app = FastAPI(title="Camera Clip Review", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(clips_router)
app.include_router(config_router)


def main() -> None:
    import uvicorn

    cfg = get_config()
    uvicorn.run("app.main:app", host=cfg.server.host, port=cfg.server.port)


if __name__ == "__main__":
    main()
