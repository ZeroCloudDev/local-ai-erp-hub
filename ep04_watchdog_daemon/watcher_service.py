"""
Episode 4: Zero-UI Watch-Folder Automation Daemon
Monitors `data/incoming_watch/`, detects file type (.txt, .pdf, .jpg/.png),
routes through Episode 1, 2, or 3 adapters, saves to SQLite with SHA-256 deduplication,
and moves the file to `data/processed_watch/` (either `approved/` or `quarantine_review/`).
"""

from pathlib import Path
import shutil
import sys
import time
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm_client import extract_structured_erp
from core.database import save_extraction
from ep02_pdf_tables.pdf_parser import process_pdf_to_erp
from ep03_fast_cpu_ocr.ocr_pipeline import process_receipt_image_to_erp

ROOT_DIR = Path(__file__).resolve().parent.parent
INCOMING_DIR = ROOT_DIR / "data" / "incoming_watch"
PROCESSED_DIR = ROOT_DIR / "data" / "processed_watch"


class ProcurementDropHandler(FileSystemEventHandler):
    def on_created(self, event) -> None:
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        # Brief pause to ensure Windows finished writing the file stream
        time.sleep(0.5)
        self.process_file(file_path)

    def process_file(self, file_path: Path) -> None:
        if not file_path.exists():
            return
        ext = file_path.suffix.lower()
        print(f"\n[WATCHDOG] Detected new file: {file_path.name}")

        try:
            raw_bytes = file_path.read_bytes()
            if ext in {".txt", ".md"}:
                text = raw_bytes.decode("utf-8", errors="replace")
                po, metrics = extract_structured_erp(text)
                source_type = "ep04_watch_text"
            elif ext == ".pdf":
                _md, po, metrics = process_pdf_to_erp(file_path)
                source_type = "ep04_watch_pdf"
            elif ext in {".jpg", ".jpeg", ".png"}:
                _txt, po, metrics = process_receipt_image_to_erp(file_path)
                source_type = "ep04_watch_image"
            else:
                print(f"[WATCHDOG] Skipping unsupported extension: {ext}")
                return

            po_id = save_extraction(
                po=po,
                source_type=source_type,
                source_name=file_path.name,
                raw_content=raw_bytes,
                wall_time_ms=metrics.get("total_pipeline_ms", metrics["wall_time_ms"]),
            )

            subfolder = "quarantine_review" if po.needs_human_review else "approved"
            dest_dir = PROCESSED_DIR / subfolder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / file_path.name
            shutil.move(str(file_path), str(dest_path))

            print(
                f"[WATCHDOG] Saved DB Record #{po_id} -> Moved to {subfolder}/{file_path.name} "
                f"({metrics['wall_time_ms']} ms)"
            )
        except Exception as exc:
            err_dir = PROCESSED_DIR / "error_failed"
            err_dir.mkdir(parents=True, exist_ok=True)
            if file_path.exists():
                shutil.move(str(file_path), str(err_dir / file_path.name))
            print(f"[WATCHDOG ERROR] Failed on {file_path.name}: {exc}")


def run_daemon() -> None:
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(ProcurementDropHandler(), str(INCOMING_DIR), recursive=False)
    observer.start()
    print(f"👀 Zero-UI ERP Watchdog active on: {INCOMING_DIR}")
    print("Drop any .txt, .pdf, or .jpg/.png invoice into the folder. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    run_daemon()
