from __future__ import annotations
from loguru import logger
import time
from typing import Callable, Optional
from core.actions import Actions
from core.recovery import Recovery
from core.permissions import Permissions

class StateMachine:
    def __init__(self, serial: str, d):
        self.serial=serial; self.d=d
        self.act=Actions(d); self.rec=Recovery(serial,d); self.perm=Permissions(d)

    def warmup(self, seconds:int=60, like_prob:float=0.05, should_continue: Optional[Callable[[], bool]] = None):
        logger.info(f"Warmup start {seconds}s, like_prob={like_prob}")
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
