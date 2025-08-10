from __future__ import annotations
import time, random, subprocess, os
from typing import Dict, Any, List, Optional, Callable
from loguru import logger
from interfaces.ui2 import connect
from core.state_machine import StateMachine
from core.blockers import BlockerResolver
from core.permissions import Permissions

TIKTOK_PACKAGES = [
    "com.zhiliaoapp.musically",
    "com.ss.android.ugc.trill",
    "com.ss.android.ugc.aweme",
]

def _adb(*args: str) -> int:
    return subprocess.call(list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class DeviceRunner:
    def __init__(self, serial: str):
        self.serial = serial
        logger.info(f"Connecting to {serial}")
        self.d = connect(serial)
        self.sm = StateMachine(serial, self.d)
        self.pkg: Optional[str] = None
        self.blockers = BlockerResolver(serial, self.d)
        self.perm = Permissions(self.d)

    def wake_and_unlock(self):
        try:
            if not self.d.screen_on():
                self.d.screen_on(); time.sleep(0.8)
            self.d.unlock()
        except Exception:
            try:
                subprocess.run(["adb","-s",self.serial,"shell","input","keyevent","224"])  # wake
                time.sleep(0.4)
                subprocess.run(["adb","-s",self.serial,"shell","swipe","400","1200","400","300","200"])  # swipe up
            except Exception as e:
                logger.warning(f"Unlock fallback failed: {e}")

    def _resolve_pkg(self) -> str:
        for p in TIKTOK_PACKAGES:
            try:
                if self.d.app_info(p):
                    return p
            except Exception:
                pass
        return TIKTOK_PACKAGES[0]

    def start_tiktok(self):
        if not self.pkg:
            self.pkg = self._resolve_pkg()
        logger.info(f"Starting TikTok package {self.pkg}")
        try:
            self.d.app_start(self.pkg, use_monkey=True)
        except Exception:
            _adb("adb","-s",self.serial,"shell","monkey","-p", self.pkg or TIKTOK_PACKAGES[0], "1")
        time.sleep(2.0)
        # resolve blockers after launch
        try: self.blockers.resolve(1.0)
        except Exception: pass
        try: self.perm.dismiss_popups(1.0)
        except Exception: pass

    def warmup(self, seconds: int = 60, like_prob: float = 0.07, should_continue: Optional[Callable[[], bool]] = None) -> bool:
        self.wake_and_unlock(); self.start_tiktok()
        t0=time.time()
        # periodic blocker resolve
        def _hook():
            try: self.blockers.resolve(0.5)
            except Exception: pass
        ok = self.sm.warmup(seconds=seconds, like_prob=like_prob, should_continue=should_continue)
        _hook()
        return ok

    def post_video(self, video_path: str, caption: str = "", should_continue: Optional[Callable[[], bool]] = None) -> bool:
        logger.info(f"Posting video: {video_path} (caption len={len(caption)})")
        if not os.path.exists(video_path):
            logger.error(f"Video not found: {video_path}")
            return False
        # Best-effort flow: push, open upload, pick, caption, post
        dst = "/sdcard/Movies/ta_upload.mp4"
        try:
            subprocess.run(["adb","-s",self.serial,"push", video_path, dst], check=False)
        except Exception as e:
            logger.error(f"adb push failed: {e}")
            return False

        self.wake_and_unlock(); self.start_tiktok()
        try: self.blockers.resolve(1.0)
        except Exception: pass
        if should_continue and not should_continue():
            logger.info("Cancelled before upload flow")
            return False

        # Tap '+' area
        try:
            self.d.click(0.50, 0.92); time.sleep(1.6)
        except Exception: pass
        try: self.blockers.resolve(0.8)
        except Exception: pass

        # Try 'Upload' or similar
        for txt in ("Upload","Post","Upload video","Next"):
            try:
                if self.d(text=txt).exists:
                    self.d(text=txt).click(); time.sleep(1.2); break
            except Exception: pass

        if should_continue and not should_continue(): return False

        # Pick first grid item
        try: self.d.click(0.15, 0.25); time.sleep(0.8)
        except Exception: pass

        for txt in ("Next","Done","Confirm"):
            try:
                if self.d(text=txt).exists:
                    self.d(text=txt).click(); time.sleep(1.0); break
            except Exception: pass
        try: self.blockers.resolve(0.8)
        except Exception: pass

        if should_continue and not should_continue(): return False

        # Caption field attempts
        try:
            el = None
            if self.d(descriptionContains="Add caption").exists:
                el = self.d(descriptionContains="Add caption")
            elif self.d(textContains="Add caption").exists:
                el = self.d(textContains="Add caption")
            if el:
                el.click(); time.sleep(0.6)
                try:
                    self.d.set_fastinput_ime(True)
                except Exception:
                    pass
                try:
                    self.d.send_keys(caption)
                except Exception:
                    pass
        except Exception:
            try:
                self.d.click(0.5, 0.3); time.sleep(0.4)
                self.d.send_keys(caption)
            except Exception: pass

        # Post / Publish
        for txt in ("Post","Publish","Share"):
            try:
                if self.d(text=txt).exists:
                    self.d(text=txt).click(); time.sleep(2.0); break
            except Exception: pass
        try:
            self.d.click(0.90, 0.93)
        except Exception: pass
        time.sleep(2.0)
        return True

    def run_pipeline(self, payload: Dict[str, Any], should_continue: Optional[Callable[[], bool]] = None) -> bool:
        steps: List[Dict[str, Any]] = payload.get("steps", [])
        repeat = int(payload.get("repeat", 1))
        lo, hi = payload.get("sleep_between", [2,5])
        ok=True
        for _ in range(repeat):
            for st in steps:
                if should_continue and not should_continue():
                    logger.info("Pipeline interrupted")
                    return False
                t = st.get("type")
                if t=="warmup":
                    dur = int(st.get("duration",60))
                    likep = float(st.get("like_prob", 0.07))
                    ok = self.warmup(dur, likep, should_continue) and ok
                elif t=="break":
                    dur = int(st.get("duration",60))
                    for _i in range(dur):
                        if should_continue and not should_continue():
                            return False
                        time.sleep(1)
                elif t=="post_video":
                    vp = st.get("video",""); cap = st.get("caption","")
                    ok = self.post_video(vp, cap, should_continue) and ok
                elif t=="rotate_identity":
                    logger.info("Rotate identity (soft): clear + restart app"); time.sleep(2.0)
                else:
                    logger.warning(f"Unknown step: {t}")
                time.sleep(random.uniform(lo,hi))
        return ok
