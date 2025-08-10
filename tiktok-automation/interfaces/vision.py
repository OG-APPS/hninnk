from __future__ import annotations
import time
from typing import Optional

def is_on_feed_ui(d) -> bool:
    """Fast UI-based check for being on the main feed/home.

    Looks for common elements; adjust as needed per locale.
    """
    try:
        if d(descriptionContains="Home").exists: return True
        if d(textMatches=r"(?i)home").exists: return True
    except Exception:
        pass
    return False

def wait_on_feed(d, timeout_s: float = 8.0) -> bool:
    end = time.time() + max(0.5, timeout_s)
    while time.time() < end:
        if is_on_feed_ui(d):
            return True
        time.sleep(0.3)
    return False
