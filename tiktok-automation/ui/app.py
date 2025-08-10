from __future__ import annotations
import os, sys, json, requests, pathlib, time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QPushButton, QLabel, QComboBox, QTextEdit, QFileDialog, QCheckBox, QGroupBox,
    QFormLayout, QSpinBox, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QInputDialog
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QIcon, QAction, QShortcut, QKeySequence

try:
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAVE_MEDIA=True
except Exception:
    HAVE_MEDIA=False

from ui.scrcpy import SCRCPY

API = os.environ.get("API_URL","http://127.0.0.1:8000")

def toast(parent: QWidget, text: str):
    QMessageBox.information(parent, "Info", text)

def load_qss():
    dark = pathlib.Path("assets/theme_dark.qss")
    light = pathlib.Path("assets/theme_light.qss")
    if dark.exists():
        with open(dark,"r",encoding="utf-8") as f: return f.read()
    return ""

class OverviewPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v=QVBoxLayout(self)
        top=QHBoxLayout()
        self.device=QComboBox(); self.refresh=QPushButton("Refresh"); self.refresh.setToolTip("Refresh connected devices")
        self.open_scrcpy=QPushButton("Open scrcpy"); self.open_scrcpy.setToolTip("Mirror the device")
        self.close_scrcpy=QPushButton("Close")
        for w in (QLabel("Device:"), self.device, self.refresh, self.open_scrcpy, self.close_scrcpy): top.addWidget(w)
        v.addLayout(top)

        quick=QGroupBox("Quick actions")
        fl=QFormLayout(quick)
        self.warm_secs=QSpinBox(); self.warm_secs.setRange(30, 7200); self.warm_secs.setValue(120)
        btn_warm=QPushButton("Start Warmup"); btn_warm.setShortcut("Ctrl+R")
        fl.addRow("Warmup seconds", self.warm_secs); fl.addRow(btn_warm)
        v.addWidget(quick)

        self.logs=QTextEdit(); self.logs.setReadOnly(True); self.logs.setMinimumHeight(240); v.addWidget(self.logs,1)

        self.refresh.clicked.connect(self.load_devices)
        self.open_scrcpy.clicked.connect(self.open_scrcpy_clicked)
        self.close_scrcpy.clicked.connect(lambda: SCRCPY.stop())
        btn_warm.clicked.connect(self.toggle_warmup)

        # Track last warmup job id and progress
        self._warmup_job_id = None
        self._warmup_start_ms = None
        self._warmup_target_s = None

        self.load_devices()
        self.t=QTimer(self); self.t.timeout.connect(self._tick); self.t.start(1000); self.pull_logs()

    def curdev(self):
        t=self.device.currentText().strip(); return t or None

    def load_devices(self):
        try:
            r=requests.get(f"{API}/devices",timeout=5); r.raise_for_status(); devs=r.json()
        except Exception as e:
            QMessageBox.warning(self,"API",f"Could not fetch devices: {e}"); devs=[]
        self.device.clear()
        for d in devs: self.device.addItem(d["serial"])

    def pull_logs(self):
        try:
            r=requests.get(f"{API}/logs",params={"source":"all","lines":400},timeout=5)
            if r.status_code==200: self.logs.setPlainText(r.text)
        except Exception: pass

    def _tick(self):
        # logs refresh (less often)
        self.pull_logs()
        # warmup progress indicator
        if self._warmup_job_id and self._warmup_target_s and self._warmup_start_ms:
            elapsed = int(time.time()*1000) - self._warmup_start_ms
            pct = max(0, min(100, int((elapsed/1000) / self._warmup_target_s * 100)))
            self.open_scrcpy.setText(f"Open scrcpy ({pct}%)")
            # check if job finished
            try:
                rr = requests.get(f"{API}/jobs/{self._warmup_job_id}", timeout=5)
                if rr.status_code==200:
                    st = rr.json().get("status")
                    if st in ("done","failed","cancelled"):
                        self._warmup_job_id=None; self._warmup_start_ms=None; self._warmup_target_s=None
                        self.open_scrcpy.setText("Open scrcpy")
            except Exception:
                pass

    def open_scrcpy_clicked(self):
        d=self.curdev()
        if not d: QMessageBox.warning(self,"scrcpy","Select device"); return
        try: SCRCPY.start(serial=d, control=False, turn_screen_off=False, max_fps=30, bit_rate="8M",
                          window_title=f"scrcpy - {d}", always_on_top=True)
        except Exception as e: QMessageBox.warning(self,"scrcpy",str(e))

    def toggle_warmup(self):
        d=self.curdev()
        if not d:
            toast(self,"Select a device first"); return
        # If a warmup is running, request cancel
        if self._warmup_job_id:
            try:
                requests.post(f"{API}/jobs/{self._warmup_job_id}/cancel", timeout=5)
                self._warmup_job_id=None; self._warmup_start_ms=None; self._warmup_target_s=None
                toast(self, "Warmup cancel requested")
            except Exception as e:
                QMessageBox.warning(self,"Cancel",str(e))
            return
        secs=int(self.warm_secs.value())
        try:
            r=requests.post(f"{API}/enqueue/warmup",json={"device_serial":d,"seconds":secs}, timeout=10)
            if r.status_code==200:
                jid = r.json().get("job_id")
                self._warmup_job_id = jid
                self._warmup_start_ms = int(time.time()*1000)
                self._warmup_target_s = secs
                toast(self, f"Warmup enqueued: #{jid}")
            else:
                QMessageBox.warning(self,"Error",f"{r.status_code}: {r.text}")
        except Exception as e:
            QMessageBox.warning(self,"Error",str(e))

class QuickRunPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v=QVBoxLayout(self)
        row=QHBoxLayout()
        self.goal=QComboBox(); self.goal.addItems(["Warmup","Post","Full Pipeline"])
        self.device=QComboBox()
        self.btn_dev=QPushButton("Refresh")
        for w in (QLabel("Goal:"), self.goal, QLabel("Device:"), self.device, self.btn_dev): row.addWidget(w)
        v.addLayout(row)

        content=QGroupBox("Content")
        cf=QHBoxLayout(content)
        self.video_path=QLineEdit(); self.video_path.setPlaceholderText("Select video for Post…")
        self.pick_video=QPushButton("Browse…"); self.pick_video.setToolTip("Pick a video file to post")
        self.repurpose=QCheckBox("Repurpose to 9:16 before post")
        self.preview_btn=QPushButton("Preview")
        cf.addWidget(self.video_path,1); cf.addWidget(self.pick_video); cf.addWidget(self.repurpose); cf.addWidget(self.preview_btn)
        v.addWidget(content)

        safety=QGroupBox("Safety preset")
        sf=QHBoxLayout(safety)
        self.preset=QComboBox(); self.preset.addItems(["Safe","Balanced","Pushy"])
        self.like_prob=QSpinBox(); self.like_prob.setRange(0,100); self.like_prob.setValue(7)
        self.watch_lo=QSpinBox(); self.watch_lo.setRange(1,60); self.watch_lo.setValue(6)
        self.watch_hi=QSpinBox(); self.watch_hi.setRange(2,120); self.watch_hi.setValue(13)
        for w in (QLabel("Preset"), self.preset, QLabel("Like %"), self.like_prob, QLabel("Watch s"), self.watch_lo, QLabel("–"), self.watch_hi): sf.addWidget(w)
        v.addWidget(safety)

        act=QHBoxLayout()
        self.launch=QPushButton("Run now")
        self.auto_scrcpy=QCheckBox("Auto-open scrcpy when running"); self.auto_scrcpy.setChecked(False)
        act.addWidget(self.launch); act.addWidget(self.auto_scrcpy); act.addStretch(1)
        v.addLayout(act)

        # Non-modal embedded preview (does not overlay UI)
        self.preview_box=QGroupBox("Video Preview")
        pv=QVBoxLayout(self.preview_box)
        if HAVE_MEDIA:
            self.video_widget=QVideoWidget()
            self.media=QMediaPlayer()
            self.audio=QAudioOutput()
            self.media.setAudioOutput(self.audio)
            self.media.setVideoOutput(self.video_widget)
            pv.addWidget(self.video_widget,1)
        else:
            pv.addWidget(QLabel("QtMultimedia not available; preview disabled."))
        v.addWidget(self.preview_box,2)

        self.btn_dev.clicked.connect(self.load_devices)
        self.pick_video.clicked.connect(self.pick_video_dialog)
        self.preview_btn.clicked.connect(self.preview_video)
        self.launch.clicked.connect(self.run_now)
        self.load_devices()

    def load_devices(self):
        try:
            r=requests.get(f"{API}/devices",timeout=5); r.raise_for_status(); devs=r.json()
        except Exception as e:
            QMessageBox.warning(self,"API",f"Could not fetch devices: {e}"); devs=[]
        self.device.clear()
        for d in devs: self.device.addItem(d["serial"])

    def pick_video_dialog(self):
        fn,_=QFileDialog.getOpenFileName(self,"Pick video","","Video files (*.mp4 *.mov *.mkv)")
        if fn: self.video_path.setText(fn)

    def preview_video(self):
        if not HAVE_MEDIA:
            QMessageBox.information(self,"Preview","QtMultimedia not available"); return
        p=self.video_path.text().strip()
        if not p: QMessageBox.information(self,"Preview","Pick a video first"); return
        self.media.setSource(QUrl.fromLocalFile(p)); self.media.play()

    def run_now(self):
        d=self.device.currentText().strip()
        if not d: QMessageBox.warning(self,"Missing","Select a device"); return
        if self.auto_scrcpy.isChecked() and not SCRCPY.running():
            try: SCRCPY.start(serial=d, control=False, always_on_top=True, max_fps=30, bit_rate="6M", window_title=f"scrcpy - {d}")
            except Exception as e: QMessageBox.warning(self,"scrcpy",f"Could not open scrcpy: {e}")
        goal=self.goal.currentText()
        if goal=="Warmup":
            secs = max(int(self.watch_lo.value()*10), 60)
            r=requests.post(f"{API}/enqueue/warmup",json={"device_serial":d,"seconds":secs})
        elif goal=="Post":
            steps=[{"type":"post_video","video":self.video_path.text().strip(),"caption":""}]
            r=requests.post(f"{API}/enqueue/pipeline",json={"device_serial":d,"steps":steps,"repeat":1,"sleep_between":[2,5]})
        else:
            steps=[{"type":"rotate_identity","soft":True},{"type":"warmup","duration":max(60,int(self.watch_lo.value()*10))},{"type":"post_video","video":self.video_path.text().strip()}]
            r=requests.post(f"{API}/enqueue/pipeline",json={"device_serial":d,"steps":steps,"repeat":1,"sleep_between":[2,5]})
        if r.status_code==200: toast(self,f"Enqueued: {r.json()}")
        else: QMessageBox.warning(self,"Error",f"{r.status_code}: {r.text}")

class PipelinesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v=QVBoxLayout(self)
        row=QHBoxLayout()
        self.device=QComboBox(); self.refresh=QPushButton("Refresh devices")
        row.addWidget(QLabel("Device:")); row.addWidget(self.device); row.addWidget(self.refresh); row.addStretch(1)
        v.addLayout(row)

        self.steps_edit=QTextEdit()
        self.steps_edit.setPlaceholderText('''Example steps JSON:
[{"type":"warmup","duration":120},
 {"type":"post_video","video":"C:/video.mp4","caption":"Hello"},
 {"type":"break","duration":60}]''')
        v.addWidget(self.steps_edit,2)

        controls=QHBoxLayout()
        self.repeat=QSpinBox(); self.repeat.setRange(1,50); self.repeat.setValue(1)
        self.run_btn=QPushButton("Run pipeline")
        controls.addWidget(QLabel("Repeat")); controls.addWidget(self.repeat); controls.addStretch(1); controls.addWidget(self.run_btn)
        v.addLayout(controls)

        self.refresh.clicked.connect(self.load_devices)
        self.run_btn.clicked.connect(self.run_pipeline)
        self.load_devices()

    def load_devices(self):
        try:
            r=requests.get(f"{API}/devices",timeout=5); r.raise_for_status(); devs=r.json()
        except Exception as e:
            QMessageBox.warning(self,"API",f"Could not fetch devices: {e}"); devs=[]
        self.device.clear()
        for d in devs: self.device.addItem(d["serial"])

    def run_pipeline(self):
        d=self.device.currentText().strip()
        if not d: QMessageBox.warning(self,"Missing","Select device"); return
        try:
            steps=json.loads(self.steps_edit.toPlainText().strip() or "[]")
        except Exception as e:
            QMessageBox.warning(self,"JSON","Invalid steps JSON"); return
        r=requests.post(f"{API}/enqueue/pipeline",json={"device_serial":d,"steps":steps,"repeat":int(self.repeat.value()),"sleep_between":[2,5]})
        if r.status_code==200: toast(self, f"Enqueued: {r.json()}")
        else: QMessageBox.warning(self,"Error",f"{r.status_code}: {r.text}")

class SchedulesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v=QVBoxLayout(self)
        # Top controls: device + run now
        top=QHBoxLayout()
        self.device=QComboBox(); self.btn_refresh_dev=QPushButton("Refresh devices")
        self.btn_run_now=QPushButton("Run Now (Flatten & Enqueue)")
        top.addWidget(QLabel("Device:")); top.addWidget(self.device); top.addWidget(self.btn_refresh_dev); top.addStretch(1); top.addWidget(self.btn_run_now)
        v.addLayout(top)

        self.text=QTextEdit(); self.text.setPlaceholderText("Schedules (read-only view). 'Run Now' flattens selected schedule from config into a pipeline for the chosen device.")
        v.addWidget(self.text,1)
        # Simple selector for schedule name
        selrow=QHBoxLayout(); self.sel_sched=QComboBox(); selrow.addWidget(QLabel("Schedule:")); selrow.addWidget(self.sel_sched); v.addLayout(selrow)

        self.t=QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(3000); self.refresh()
        self.btn_refresh_dev.clicked.connect(self.load_devices)
        self.btn_run_now.clicked.connect(self.run_now)
        self.load_devices()

    def refresh(self):
        try:
            r=requests.get(f"{API}/config/schedules",timeout=5)
            data = r.json()
            self.text.setPlainText(json.dumps(data, indent=2))
            # populate selector
            cur=self.sel_sched.currentText()
            self.sel_sched.blockSignals(True)
            self.sel_sched.clear()
            for name in data.keys(): self.sel_sched.addItem(name)
            if cur:
                idx = self.sel_sched.findText(cur)
                if idx>=0: self.sel_sched.setCurrentIndex(idx)
            self.sel_sched.blockSignals(False)
        except Exception as e:
            self.text.setPlainText(str(e))

    def load_devices(self):
        try:
            r=requests.get(f"{API}/devices",timeout=5); r.raise_for_status(); devs=r.json()
        except Exception:
            devs=[]
        self.device.clear()
        for d in devs:
            label = d.get("serial","?")
            if d.get("state") and d["state"]!="device": label += f" ({d['state']})"
            self.device.addItem(label, d.get("serial",""))

    def _flatten_schedule(self, cfg_schedules: dict, cfg_cycles: dict, name: str):
        s = cfg_schedules.get(name) or {}
        items = s.get("items", [])
        steps=[]
        for it in items:
            if it.get("type")=="cycle":
                cyc = cfg_cycles.get(it.get("name","")) or {}
                steps.extend(cyc.get("steps", []))
            elif it.get("type")=="break":
                mins = int(it.get("minutes",10))
                steps.append({"type":"break","duration":mins*60})
        return steps

    def run_now(self):
        serial = self.device.currentData() or self.device.currentText().split(" ")[0]
        if not serial:
            QMessageBox.warning(self,"Run Now","Select a device first"); return
        sched_name = self.sel_sched.currentText().strip()
        if not sched_name:
            QMessageBox.warning(self,"Run Now","No schedule selected"); return
        try:
            s = requests.get(f"{API}/config/schedules", timeout=5).json()
            c = requests.get(f"{API}/config/cycles", timeout=5).json()
            steps = self._flatten_schedule(s, c, sched_name)
            if not steps:
                QMessageBox.information(self,"Run Now","No steps for this schedule"); return
            r = requests.post(f"{API}/enqueue/pipeline", json={"device_serial":serial, "steps":steps, "repeat":1, "sleep_between":[2,5]}, timeout=10)
            if r.status_code==200:
                toast(self, f"Enqueued: {r.json()}")
            else:
                QMessageBox.warning(self,"Run Now", f"{r.status_code}: {r.text}")
        except Exception as e:
            QMessageBox.warning(self,"Run Now", str(e))

class DevicesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v=QVBoxLayout(self)
        self.text=QTextEdit(); self.text.setReadOnly(True)
        v.addWidget(self.text,1)
        self.t=QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(2000); self.refresh()

    def refresh(self):
        try:
            r=requests.get(f"{API}/devices",timeout=5); r.raise_for_status()
            self.text.setPlainText(json.dumps(r.json(), indent=2))
        except Exception as e:
            self.text.setPlainText(str(e))

class JobsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        h=QHBoxLayout(self)
        left=QVBoxLayout(); right=QVBoxLayout()
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(["ID","Device","Type","Status","Created"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        left.addWidget(self.table,1)
        act=QHBoxLayout()
        self.btn_cancel=QPushButton("Cancel"); self.btn_retry=QPushButton("Retry")
        act.addWidget(self.btn_cancel); act.addWidget(self.btn_retry); left.addLayout(act)
        self.details=QTextEdit(); self.details.setReadOnly(True)
        right.addWidget(QLabel("Run details / Logs (tail)")); right.addWidget(self.details,1)
        spl=QSplitter(); lw=QWidget(); rw=QWidget(); lw.setLayout(left); rw.setLayout(right); spl.addWidget(lw); spl.addWidget(rw)
        h.addWidget(spl)

        self.table.itemSelectionChanged.connect(self.refresh_details)
        self.btn_cancel.clicked.connect(self.cancel_selected)
        self.btn_retry.clicked.connect(self.retry_selected)

        self.t=QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(1500); self.refresh()

    def refresh(self):
        try:
            r=requests.get(f"{API}/jobs",timeout=5); r.raise_for_status(); rows=r.json()
            self.table.setRowCount(len(rows))
            for i,row in enumerate(rows):
                for j,k in enumerate(["id","device","type","status","created_at"]):
                    self.table.setItem(i,j,QTableWidgetItem(str(row.get(k,""))))
        except Exception: pass

    def _sel_job_id(self):
        it = self.table.currentItem()
        if not it: return None
        row = it.row()
        jid_item = self.table.item(row, 0)
        return int(jid_item.text()) if jid_item else None

    def refresh_details(self):
        jid = self._sel_job_id()
        if not jid: return
        try:
            rr = requests.get(f"{API}/runs", params={"job_id": jid}, timeout=5).json()
            logs = requests.get(f"{API}/logs", params={"source":"all","lines":200}, timeout=5).text
            self.details.setPlainText(json.dumps(rr, indent=2) + "\n\n" + logs)
        except Exception as e:
            self.details.setPlainText(str(e))

    def cancel_selected(self):
        jid = self._sel_job_id()
        if not jid:
            return
        r = requests.post(f"{API}/jobs/{jid}/cancel")
        if r.status_code!=200: QMessageBox.warning(self,"Cancel",f"{r.status_code}: {r.text}")

    def retry_selected(self):
        jid = self._sel_job_id()
        if not jid:
            return
        r = requests.post(f"{API}/jobs/{jid}/retry")
        if r.status_code!=200: QMessageBox.warning(self,"Retry",f"{r.status_code}: {r.text}")

class CycleBuilderPage(QWidget):
    """Minimal, functional Cycle Builder with Palette · Canvas · Inspector.
    Saves/loads under artifacts/cycles; Run Now enqueues current canvas.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_step = None
        self.steps = []  # list[dict]
        root = QVBoxLayout(self)

        # Header actions
        hdr = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_load = QPushButton("Load…")
        self.btn_save = QPushButton("Save…")
        self.btn_est = QPushButton("Estimate")
        self.btn_run = QPushButton("Run Now")
        self.auto_scrcpy = QCheckBox("Auto-open scrcpy")
        for w in (self.btn_new, self.btn_load, self.btn_save, self.btn_est, self.btn_run, self.auto_scrcpy): hdr.addWidget(w)
        hdr.addStretch(1)
        root.addLayout(hdr)

        # Three panes: Palette | Canvas | Inspector
        panes = QHBoxLayout()
        # Palette
        self.palette = QListWidget(); self.palette.setFixedWidth(220)
        palette_items = [
            ("warmup", "Warmup {seconds, like_prob}"),
            ("post_video", "Post video {video, caption}"),
            ("break", "Break {duration}"),
            ("rotate_identity", "Rotate identity (soft)"),
        ]
        for key, desc in palette_items:
            it = QListWidgetItem(f"{key} — {desc}")
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.palette.addItem(it)
        # Canvas
        self.canvas = QListWidget(); self.canvas.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.canvas.setDragEnabled(True); self.canvas.setAcceptDrops(True); self.canvas.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        # Inspector
        self.inspect_box = QGroupBox("Properties")
        self.inspect_form = QFormLayout(self.inspect_box)

        panes.addWidget(self.palette)
        panes.addWidget(self.canvas, 1)
        panes.addWidget(self.inspect_box)
        root.addLayout(panes, 1)

        # Footer: live preview
        self.preview = QTextEdit(); self.preview.setReadOnly(True); self.preview.setMinimumHeight(110)
        root.addWidget(self.preview)

        # Signals
        self.palette.itemDoubleClicked.connect(self.add_from_palette)
        self.canvas.currentItemChanged.connect(self.on_canvas_selection)
        self.btn_new.clicked.connect(self.new_cycle)
        self.btn_load.clicked.connect(self.load_cycle_dialog)
        self.btn_save.clicked.connect(self.save_cycle_dialog)
        self.btn_est.clicked.connect(self.estimate)
        self.btn_run.clicked.connect(self.run_now)

        self.new_cycle()

    # --------- model helpers ---------
    def _default_for(self, t: str) -> dict:
        if t == "warmup": return {"type":"warmup","duration":120,"like_prob":0.07}
        if t == "post_video": return {"type":"post_video","video":"","caption":""}
        if t == "break": return {"type":"break","duration":60}
        if t == "rotate_identity": return {"type":"rotate_identity","soft":True}
        return {"type":t}

    def _refresh_preview(self):
        lines=[]
        for i, st in enumerate(self.steps):
            t = st.get("type")
            if t=="warmup": lines.append(f"{i+1}. warmup {st.get('duration',0)}s like={st.get('like_prob',0)}")
            elif t=="break": lines.append(f"{i+1}. break {st.get('duration',0)}s")
            elif t=="post_video": lines.append(f"{i+1}. post_video {os.path.basename(st.get('video',''))}")
            else: lines.append(f"{i+1}. {t}")
        self.preview.setPlainText("\n".join(lines))

    def _sync_canvas(self):
        self.canvas.blockSignals(True)
        self.canvas.clear()
        for st in self.steps:
            t=st.get("type","?")
            text = t
            if t=="warmup": text = f"warmup · {st.get('duration',0)}s"
            if t=="break": text = f"break · {st.get('duration',0)}s"
            if t=="post_video": text = f"post_video · {os.path.basename(st.get('video',''))}"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, st)
            self.canvas.addItem(it)
        self.canvas.blockSignals(False)
        self._refresh_preview()

    def _rebind_inspector(self, st: dict | None):
        # Clear form
        while self.inspect_form.rowCount():
            self.inspect_form.removeRow(0)
        if not st:
            return
        t = st.get("type")
        # Common: type label
        self.inspect_form.addRow(QLabel(f"Type: {t}"))
        # Build fields by type
        if t == "warmup":
            s = QSpinBox(); s.setRange(10, 7200); s.setValue(int(st.get("duration",120)))
            p = QLineEdit(str(st.get("like_prob",0.07)))
            self.inspect_form.addRow("Seconds", s); self.inspect_form.addRow("Like prob (0-1)", p)
            def on_change():
                try: st["duration"] = int(s.value())
                except Exception: pass
                try: st["like_prob"] = float(p.text() or 0)
                except Exception: st["like_prob"]=0.07
                self._sync_canvas()
            s.valueChanged.connect(lambda _: on_change()); p.textChanged.connect(lambda _: on_change())
        elif t == "post_video":
            path = QLineEdit(st.get("video","")); cap = QLineEdit(st.get("caption",""))
            btn = QPushButton("Browse…")
            def pick():
                fn,_=QFileDialog.getOpenFileName(self,"Pick video","","Video files (*.mp4 *.mov *.mkv)")
                if fn: path.setText(fn)
            btn.clicked.connect(pick)
            def on_change():
                st["video"]=path.text().strip(); st["caption"]=cap.text()
                self._sync_canvas()
            path.textChanged.connect(lambda _: on_change()); cap.textChanged.connect(lambda _: on_change())
            row=QHBoxLayout(); row.addWidget(path); row.addWidget(btn); wrap=QWidget(); wrap.setLayout(row)
            self.inspect_form.addRow("Video", wrap); self.inspect_form.addRow("Caption", cap)
        elif t == "break":
            s = QSpinBox(); s.setRange(5, 24*3600); s.setValue(int(st.get("duration",60)))
            self.inspect_form.addRow("Duration (s)", s)
            def on_change():
                st["duration"] = int(s.value()); self._sync_canvas()
            s.valueChanged.connect(lambda _: on_change())
        elif t == "rotate_identity":
            soft = QCheckBox("Soft (no reboot)"); soft.setChecked(bool(st.get("soft",True)))
            def on_change():
                st["soft"]=soft.isChecked(); self._sync_canvas()
            soft.toggled.connect(lambda _: on_change())
            self.inspect_form.addRow("Mode", soft)

    # --------- actions ---------
    def add_from_palette(self, item: QListWidgetItem):
        t = item.data(Qt.ItemDataRole.UserRole)
        self.steps.append(self._default_for(t))
        self._sync_canvas()

    def on_canvas_selection(self, cur: QListWidgetItem, _prev: QListWidgetItem):
        st = cur.data(Qt.ItemDataRole.UserRole) if cur else None
        self.current_step = st
        self._rebind_inspector(st)

    def new_cycle(self):
        self.steps = []
        self._sync_canvas(); self._rebind_inspector(None)

    def save_cycle_dialog(self):
        pathlib.Path("artifacts/cycles").mkdir(parents=True, exist_ok=True)
        fn,_=QFileDialog.getSaveFileName(self, "Save cycle as", "artifacts/cycles/cycle.json", "JSON (*.json)")
        if not fn: return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"schema":"ta.cycle.v1","name":pathlib.Path(fn).stem,"steps":self.steps}, f, indent=2)
            toast(self, f"Saved {fn}")
        except Exception as e:
            QMessageBox.warning(self, "Save", str(e))

    def load_cycle_dialog(self):
        fn,_=QFileDialog.getOpenFileName(self, "Load cycle", "artifacts/cycles", "JSON (*.json)")
        if not fn: return
        try:
            with open(fn, "r", encoding="utf-8") as f:
                data=json.load(f)
            self.steps = list(data.get("steps", []))
            self._sync_canvas(); self._rebind_inspector(None)
            toast(self, f"Loaded {fn}")
        except Exception as e:
            QMessageBox.warning(self, "Load", str(e))

    def estimate(self):
        # naive estimate
        total = 0; swipes=0; likes=0
        for st in self.steps:
            if st.get("type")=="warmup":
                dur=int(st.get("duration",120)); total+=dur
                swipes += max(1, int(dur/6))
                likes += int(swipes * float(st.get("like_prob",0.07)))
            elif st.get("type")=="break": total+=int(st.get("duration",60))
            elif st.get("type")=="post_video": total+=180
        QMessageBox.information(self, "Estimate", f"~{int(total/60)} min • ~{swipes} swipes • ~{likes} likes")

    def run_now(self):
        # Ask device
        serial, ok = QInputDialog.getText(self, "Run Now", "Device serial (empty = default):")
        if not ok: return
        serial = serial.strip()
        try:
            payload={"device_serial":serial, "steps":self.steps, "repeat":1, "sleep_between":[2,5]}
            r=requests.post(f"{API}/enqueue/pipeline", json=payload, timeout=10)
            if r.status_code==200: toast(self, f"Enqueued: {r.json()}")
            else: QMessageBox.warning(self, "Run Now", f"{r.status_code}: {r.text}")
        except Exception as e:
            QMessageBox.warning(self, "Run Now", str(e))

class LogsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v=QVBoxLayout(self)
        self.text=QTextEdit(); self.text.setReadOnly(True); v.addWidget(self.text,1)
        self.t=QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(1500); self.refresh()

    def refresh(self):
        try:
            r=requests.get(f"{API}/logs",params={"source":"all","lines":800},timeout=5)
            self.text.setPlainText(r.text if r.status_code==200 else r.text)
        except Exception as e:
            self.text.setPlainText(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TikTok Automation — Max Client")
        self.resize(1280,800)
        central=QWidget(); self.setCentralWidget(central)
        h=QHBoxLayout(central)
        self.sidebar=QListWidget(); self.sidebar.setFixedWidth(210)
        for name in ["Overview","Quick Run","Cycle Builder","Pipelines","Schedules","Devices","Jobs/Runs","Logs","Settings"]:
            QListWidgetItem(name, self.sidebar)
        self.stack=QStackedWidget()
        h.addWidget(self.sidebar); h.addWidget(self.stack,1)
        self.page_over=OverviewPage(); self.page_quick=QuickRunPage(); self.page_cycles=CycleBuilderPage(); self.page_pipes=PipelinesPage(); self.page_sched=SchedulesPage(); self.page_dev=DevicesPage(); self.page_jobs=JobsPage(); self.page_logs=LogsPage()
        self.page_settings=QTextEdit(); self.page_settings.setPlainText("Edit config in config/config.yaml")
        for w in [self.page_over,self.page_quick,self.page_cycles,self.page_pipes,self.page_sched,self.page_dev,self.page_jobs,self.page_logs,self.page_settings]:
            self.stack.addWidget(w)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        # menu / shortcuts
        self._setup_menu()
        # theme
        qss = load_qss()
        if qss: self.setStyleSheet(qss)

    def _setup_menu(self):
        bar = self.menuBar()
        filem = bar.addMenu("&File")
        act_quit = QAction("Quit", self); act_quit.triggered.connect(self.close); filem.addAction(act_quit)
        viewm = bar.addMenu("&View")
        act_scrcpy = QAction("Open scrcpy", self); act_scrcpy.triggered.connect(self.page_over.open_scrcpy_clicked); viewm.addAction(act_scrcpy)
        # shortcuts
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.page_over.enqueue_warm)

def run_gui():
    app=QApplication(sys.argv); win=MainWindow(); win.show(); app.exec()

if __name__=="__main__": run_gui()
