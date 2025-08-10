from __future__ import annotations
import os, sqlite3, json, pathlib, time, subprocess
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from loguru import logger
from utils.logger_setup import setup_logger
from utils.config import load_config, save_config

DB_PATH = "artifacts/orchestrator.db"
LOG_DIR = "artifacts/logs"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      device TEXT, type TEXT, payload TEXT,
      status TEXT DEFAULT 'queued', created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS runs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER, device TEXT, status TEXT,
      started_at DATETIME DEFAULT CURRENT_TIMESTAMP, ended_at DATETIME);
    """)
    conn.commit(); conn.close()

app = FastAPI(title="Automation API", version="1.2")

@app.on_event("startup")
def startup_event():
    pathlib.Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    setup_logger("api", LOG_DIR); init_db()
    logger.info("API starting…"); logger.info(f"Database ready at {DB_PATH}")

@app.on_event("shutdown")
def shutdown_event(): logger.info("API stopping…")

class EnqueueWarmup(BaseModel):
    device_serial: str; seconds: int = 60; like_prob: float = 0.07
class EnqueuePipeline(BaseModel):
    device_serial: str; steps: List[Dict[str, Any]] = []; repeat: int = 1; sleep_between: List[int] = [2,5]

def row_to_dict(r: sqlite3.Row) -> Dict[str, Any]: return {k:r[k] for k in r.keys()}
def enqueue_job(device: str, jtype: str, payload: Dict[str, Any]) -> int:
    conn=get_db(); cur=conn.execute("INSERT INTO jobs(device,type,payload,status) VALUES(?,?,?,?)",(device,jtype,json.dumps(payload),"queued"))
    jid=cur.lastrowid; conn.commit(); conn.close(); logger.info(f"Enqueued job {jid} type={jtype} device={device}"); return jid

@app.get("/health")
def health(): return {"ok": True, "ts": time.time()}

def _adb_model(serial: str) -> str:
    try:
        out = subprocess.check_output(["adb","-s",serial,"shell","getprop","ro.product.model"], text=True)
        return out.strip()
    except Exception:
        return ""

@app.get("/devices")
def devices():
    try:
        out = subprocess.check_output(["adb","devices","-l"], text=True, stderr=subprocess.STDOUT)
    except Exception:
        return []
    devs=[]
    for line in out.splitlines():
        line=line.strip()
        if not line or line.startswith("List of devices"): continue
        parts=line.split()
        serial=parts[0]
        state="unknown"
        for p in parts[1:]:
            if p in ("device","offline","unauthorized"): state=p
        devs.append({"serial":serial,"state":state,"model":_adb_model(serial)})
    return devs

@app.get("/jobs")
def get_jobs(device: Optional[str] = None, status: Optional[str] = None):
    conn=get_db(); q="SELECT * FROM jobs WHERE 1=1"; params=[]
    if device: q+=" AND device=?"; params.append(device)
    if status and status!="next": q+=" AND status=?"; params.append(status)
    q+=" ORDER BY id DESC LIMIT 500"
    rows=[row_to_dict(r) for r in conn.execute(q,params).fetchall()]; conn.close()
    if device and status=="next":
        conn=get_db()
        r=conn.execute("SELECT * FROM jobs WHERE device=? AND status='queued' ORDER BY id ASC LIMIT 1",(device,)).fetchone()
        if not r: conn.close(); return []
        jid=r["id"]
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
        conn.execute("INSERT INTO runs(job_id,device,status) VALUES(?,?,?)", (jid, device, "running"))
        conn.commit(); rr=row_to_dict(r); conn.close(); return [rr]
    return rows

@app.get("/jobs/next")
def get_next_job(device: str):
    """Atomically claim the next queued job for a device and mark it running."""
    conn=get_db()
    r=conn.execute("SELECT * FROM jobs WHERE device=? AND status='queued' ORDER BY id ASC LIMIT 1",(device,)).fetchone()
    if not r:
        conn.close(); return {}
    jid=r["id"]
    conn.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    conn.execute("INSERT INTO runs(job_id,device,status) VALUES(?,?,?)", (jid, device, "running"))
    conn.commit(); rr=row_to_dict(r); conn.close(); return rr

@app.get("/runs")
def get_runs(device: Optional[str] = None, job_id: Optional[int] = None):
    conn=get_db(); q="SELECT * FROM runs WHERE 1=1"; params=[]
    if device: q+=" AND device=?"; params.append(device)
    if job_id: q+=" AND job_id=?"; params.append(job_id)
    q+=" ORDER BY id DESC LIMIT 500"
    rows=[row_to_dict(r) for r in conn.execute(q,params).fetchall()]; conn.close(); return rows

@app.post("/enqueue/warmup")
def post_enqueue_warmup(req: EnqueueWarmup):
    payload = {"seconds": req.seconds, "like_prob": req.like_prob}
    return {"job_id": enqueue_job(req.device_serial, "warmup", payload)}

@app.post("/enqueue/pipeline")
def post_enqueue_pipeline(req: EnqueuePipeline):
    return {"job_id": enqueue_job(req.device_serial, "pipeline", {"steps": req.steps, "repeat": req.repeat, "sleep_between": req.sleep_between})}

@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    conn=get_db(); r=conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r: conn.close(); raise HTTPException(404, "Job not found")
    if r["status"] in ("done","failed","cancelled"): conn.close(); return {"ok": True}
    conn.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,))
    conn.execute("UPDATE runs SET status='cancelled', ended_at=CURRENT_TIMESTAMP WHERE job_id=? AND ended_at IS NULL", (job_id,))
    conn.commit(); conn.close(); logger.info(f"Job {job_id} cancelled"); return {"ok": True}

@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: int):
    conn=get_db(); r=conn.execute("SELECT device,type,payload FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r: conn.close(); raise HTTPException(404, "Job not found")
    new_id = enqueue_job(r["device"], r["type"], json.loads(r["payload"] or "{}"))
    return {"job_id": new_id}

@app.post("/jobs/{job_id}/complete")
def complete_job(job_id: int, ok: bool = True):
    conn=get_db()
    conn.execute("UPDATE jobs SET status=? WHERE id=?", ("done" if ok else "failed", job_id))
    conn.execute("UPDATE runs SET status=?, ended_at=CURRENT_TIMESTAMP WHERE job_id=? AND ended_at IS NULL", ("done" if ok else "failed", job_id))
    conn.commit(); conn.close(); return {"ok": True}

@app.get("/jobs/{job_id}")
def get_job(job_id: int):
    conn=get_db(); r=conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone(); conn.close()
    if not r: raise HTTPException(404, "Job not found")
    return row_to_dict(r)

@app.get("/logs")
def get_logs(source: str = Query("all"), lines: int = Query(1000)):
    files=[]
    if source in ("all","api"): files.append(pathlib.Path(LOG_DIR)/"api.log")
    if source in ("all","worker"): files.append(pathlib.Path(LOG_DIR)/"worker.log")
    if source in ("all","scheduler"): files.append(pathlib.Path(LOG_DIR)/"scheduler.log")
    chunks=[]
    for f in files:
        if f.exists():
            text=f.read_text(encoding="utf-8", errors="ignore").splitlines()[-lines:]
            chunks.append(f"===== {f.name} =====\n" + "\n".join(text))
    return PlainTextResponse("\n\n".join(chunks) if chunks else "(no logs)")

@app.get("/config/cycles")
def config_cycles():
    return load_config().get("cycles", {})

@app.get("/config/schedules")
def config_schedules():
    return load_config().get("schedules", {})

@app.get("/config")
def get_config():
    return load_config()

@app.post("/config")
def set_config(data: Dict[str, Any] = Body(...)):
    save_config(data); return {"ok": True}
