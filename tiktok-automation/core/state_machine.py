from __future__ import annotations
from loguru import logger
import time
from typing import Callable, Optional
from enum import Enum, auto
from interfaces.vision import is_on_feed_ui, wait_on_feed
from core.actions import Actions
from core.recovery import Recovery
from core.permissions import Permissions

class StateMachine:
    def __init__(self, serial: str, d):
        self.serial=serial; self.d=d
        self.act=Actions(d); self.rec=Recovery(serial,d); self.perm=Permissions(d)

    class Page(Enum):
        UNKNOWN = auto()
        FEED = auto()
        LOGIN = auto()
        DIALOG = auto()

    def detect_page(self) -> "StateMachine.Page":
        try:
            if is_on_feed_ui(self.d):
                return self.Page.FEED
            # Heuristics for login and dialogs
            if self.d(textMatches=r"(?i)log in|sign in").exists:
                return self.Page.LOGIN
            if self.d(textMatches=r"(?i)when.?s your birthday|terms of service|got it|ok|continue").exists:
                return self.Page.DIALOG
        except Exception:
            pass
        return self.Page.UNKNOWN

    def ensure_ready_for_warmup(self, settle_s: float = 1.0) -> bool:
        """Bring the app to a state suitable for warmup (on feed)."""
        p = self.detect_page()
        if p == self.Page.FEED:
            return True
        # Try easy fixes
        try:
            self.perm.dismiss_popups(1.0)
        except Exception:
            pass
        try:
            # In case a dialog blocks, a back press may help
            self.d.press("back")
        except Exception:
            pass
        ok = wait_on_feed(self.d, timeout_s=3.0)
        if ok:
            time.sleep(max(0.0, settle_s))
        else:
            logger.info("Not on feed after attempts; proceed cautiously")
        return ok

    def warmup(self, seconds:int=60, like_prob:float=0.05, should_continue: Optional[Callable[[], bool]] = None):
        logger.info(f"Warmup start {seconds}s, like_prob={like_prob}")
        # Try to ensure feed context
        try:
            self.ensure_ready_for_warmup(0.5)
        except Exception:
            pass
        t0=time.time()
        while time.time()-t0 < seconds:
            if should_continue and not should_continue():
                logger.info("Warmup interrupted by cancel/pause")
                return False
            time.sleep(0.8)
            self.act.like(like_prob)
            self.act.swipe_up()
        logger.info("Warmup done")
        return True
