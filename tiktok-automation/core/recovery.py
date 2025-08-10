from __future__ import annotations
from loguru import logger
import time

class Recovery:
    def __init__(self, serial: str, d):
        self.serial=serial; self.d=d

    def escalate(self, level:int):
        if level==1:
            logger.warning("Recovery L1: restart app")
        elif level==2:
            logger.warning("Recovery L2: wait+restart"); time.sleep(5)
        elif level>=3:
            logger.error("Recovery L3: reboot device (stub)")
