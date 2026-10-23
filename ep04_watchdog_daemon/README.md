# Episode 4 Implementation Plan: Zero-UI Watch-Folder Daemon (`watchdog` + SQLite)

## 1. Engineering Objective
Unify Episodes 1, 2, and 3 into a hands-free background service (`watcher_service.py`) for small business office automation. Whenever an employee drops a `.txt` note, `.pdf` invoice, or `.jpg` receipt into `data/incoming_watch/`, the daemon:
1. Auto-detects the file format and routes it to the matching Episode 1–3 pipeline.
2. Runs the Two-Layer Defense and upserts into `erp_procurement.db` using SHA-256 content hashing.
3. Automatically routes clean files into `data/processed_watch/approved/` and flagged files (missing prices or math mismatches) into `data/processed_watch/quarantine_review/`.

## 2. Verification Command
```powershell
python ep04_watchdog_daemon/watcher_service.py
```
