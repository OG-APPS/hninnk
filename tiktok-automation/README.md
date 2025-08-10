# TikTok Automation — Max Client Edition

**Production-focused**: API + Worker + Scheduler + Polished GUI, scrcpy integration, pipelines/schedules, logs, video preview, and templates.

## Quick start
```powershell
.\install.ps1
.\.venv\Scriptsctivate
python main.py
```

## Highlights
- One-click **launcher** (auto port + device)
- **FastAPI** with jobs/runs/cancel/retry + logs
- **Scheduler** (APScheduler) reads `config.yaml` schedules and enqueues jobs
- **Worker** executes warmup/pipeline with recovery hooks
- **GUI**: Overview · Quick Run · Pipelines · Schedules · Devices · Jobs/Runs · Logs · Settings
- **scrcpy**: open/close, auto-open on runs, version-aware flags
- **Video**: 9:16 repurpose helper (ffmpeg)
- **Theming**: dark/light QSS, icons, tooltips, shortcuts

See `docs/UX_NOTES.md` for UX decisions.
