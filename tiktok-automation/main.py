from __future__ import annotations
import os, sys, time, requests, subprocess, contextlib, socket

def find_free_port(preferred=8000):
    import socket, contextlib
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        if s.connect_ex(("127.0.0.1", preferred)) != 0: return preferred
    for p in range(preferred+1, preferred+50):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s2:
            if s2.connect_ex(("127.0.0.1", p)) != 0: return p
    return preferred + 60

def main():
    host="127.0.0.1"; py=sys.executable
    api_port=find_free_port(8000)
    env=os.environ.copy(); env["API_URL"]=f"http://{host}:{api_port}"
    api_cmd=[py,"-m","uvicorn","orchestrator.api:app","--host",host,"--port",str(api_port),"--log-level","info"]
    api = subprocess.Popen(api_cmd, env=env)
    # Wait for API up
    for _ in range(120):
        try:
            r=requests.get(f"http://{host}:{api_port}/health",timeout=1.0)
            if r.status_code==200: break
        except Exception: time.sleep(0.25)
    # auto-detect device
    dev=env.get("DEVICE_SERIAL","")
    if not dev:
        try:
            out=subprocess.check_output(["adb","devices"],text=True)
            for line in out.splitlines():
                if line.strip().endswith("device") and not line.startswith("List of devices"):
                    dev=line.split("\t")[0].strip(); break
        except Exception: pass
    env["DEVICE_SERIAL"]=dev or ""
    # start scheduler + worker + GUI
    scheduler=subprocess.Popen([py,"-m","orchestrator.scheduler"], env=env)
    worker=subprocess.Popen([py,"-m","worker.device_worker"], env=env)
    gui=subprocess.Popen([py,"-m","ui.app"], env=env)
    print(f"[up] running on API http://{host}:{api_port}. Press Ctrl+C to stop.")
    try: gui.wait()
    finally:
        for p in (worker, scheduler, api):
            try: p.terminate()
            except Exception: pass

if __name__=="__main__": main()
