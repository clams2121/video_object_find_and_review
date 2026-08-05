from __future__ import annotations

import logging
import os
import signal

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _shutdown() -> None:
    logger.info("Shutdown requested from the UI")
    # SIGTERM (not SIGKILL) so uvicorn's normal shutdown path runs - the
    # lifespan context manager stops the worker thread cleanly.
    os.kill(os.getpid(), signal.SIGTERM)


@router.post("/admin/shutdown")
def shutdown(background_tasks: BackgroundTasks):
    # Deferred via BackgroundTasks so this response is sent before the
    # process starts tearing down.
    background_tasks.add_task(_shutdown)
    return JSONResponse({"ok": True})
