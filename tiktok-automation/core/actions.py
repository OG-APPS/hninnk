from __future__ import annotations
import time, random
from loguru import logger

class Actions:
    def __init__(self, d):
        self.d=d

    def swipe_up(self):
        try: self.d.swipe(0.5,0.80,0.5,0.20,0.2)
        except Exception as e: logger.warning(f"Swipe up failed: {e}")

    def like(self, prob=0.05):
        if random.random()<prob:
            try: self.d.click(0.90,0.55); time.sleep(0.2)
            except Exception: pass
