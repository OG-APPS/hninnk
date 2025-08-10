"""Worker loop for executing jobs on a single connected device.

The module polls the orchestrator API for the next job assigned to the
current device, runs the job via :class:`~core.device_runner.DeviceRunner`,
and posts completion status back to the server.  It expects two environment
variables at startup:

``API_URL``
    Base URL of the orchestrator service (default ``http://127.0.0.1:8000``).
``DEVICE_SERIAL``
    Android device serial to target.

Running the module directly will start the worker loop and block forever.
"""

from __future__ import annotations
import time, requests, os, json
from typing import Callable
from loguru import logger
from utils.logger_setup import setup_logger
from core.device_runner import DeviceRunner

API = os.environ.get("API_URL", "http://127.0.0.1:8000")
DEVICE = os.environ.get("DEVICE_SERIAL", "")

def _make_should_continue(jid: int) -> Callable[[], bool]:
    """Returns a function that checks if the job is still allowed to run.
    Treats statuses other than running/queued as stop signals (cancelled/paused/failed/done)."""
    def _inner() -> bool:
        try:
            rr = requests.get(f"{API}/jobs/{jid}", timeout=5)
            if rr.status_code != 200:
                return True
            row = rr.json()
            return row.get("status") in ("running", "queued")
        except Exception:
            return True
    return _inner

def run() -> None:
    """Entry point for the worker loop.

    The loop continuously polls ``/jobs/next`` for work, executes the returned
    job, and reports completion.  It blocks forever until an unhandled
    exception or process termination.  Logging is configured via
    :func:`utils.logger_setup.setup_logger`.
    """

    setup_logger("worker")
    if not DEVICE:
        logger.error("DEVICE_SERIAL not set")
        return
    dr = DeviceRunner(DEVICE)
    logger.info(f"Worker starting for device {DEVICE}")
    while True:
        try:
            r = requests.get(f"{API}/jobs/next", params={"device": DEVICE}, timeout=10)
            if r.status_code != 200:
                time.sleep(1.0); continue
            j = r.json() or {}
            if not j:
                time.sleep(1.0); continue
            jid = j.get("id"); jtype = j.get("type"); payload = json.loads(j.get("payload") or "{}")
            ok = True
            logger.info(f"Running job {jid} type={jtype}")

            should_continue = _make_should_continue(jid)

            if jtype == "warmup":
                secs = int(payload.get("seconds", 60))
                likep = float(payload.get("like_prob", 0.07))
                ok = dr.warmup(seconds=secs, like_prob=likep, should_continue=should_continue)
            elif jtype == "pipeline":
                ok = dr.run_pipeline(payload, should_continue=should_continue)
            else:
                logger.warning(f"Unknown job type: {jtype}"); ok = False
            try:
                requests.post(f"{API}/jobs/{jid}/complete", params={"ok": ok}, timeout=10)
            except Exception as e:
                logger.warning(f"Could not notify completion: {e}")
        except Exception as e:
            logger.error(f"Loop error: {e}"); time.sleep(2.0)

if __name__ == "__main__": run()
