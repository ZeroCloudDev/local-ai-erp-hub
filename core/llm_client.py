"""
Local Ollama client wrapper with honest hardware telemetry.
Separates C++ GBNF Structured Output extraction from naive regex/prompting for live Episode 1 benchmarks.
"""

import os
from pathlib import Path
import socket
import subprocess
import time
from typing import Any, Dict, Tuple
import ollama
from core.schemas import PurchaseOrderExtraction

DEFAULT_MODEL = "qwen2.5:3b"


def _ensure_ollama_running() -> None:
    """Automatically starts local `ollama serve` if port 11434 is not listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", 11434)) == 0:
            return

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    ollama_exe = next((str(p) for p in candidates if p.exists()), "ollama")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    subprocess.Popen(
        [ollama_exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    for _ in range(20):
        time.sleep(0.3)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            if sock.connect_ex(("127.0.0.1", 11434)) == 0:
                return

SYSTEM_PROMPT = """You are a strict data extraction engine for an ERP procurement database.
Extract purchase order details from the user input into the exact JSON schema provided.
CRITICAL RULES:
1. Extract vendor_name (store/supplier), job_or_po_number, every line item, and stated_total (overall receipt total if stated).
2. Convert explicit quantities into numbers (e.g. 'Qty: 4' -> 4, '12x' -> 12, '3 spools' -> 3, 'two' -> 2, '3 gallons' -> 3).
3. Only set quantity to null if no quantity number is written for that item at all (e.g. bare plural 'Ordered microcontrollers' or 'a bunch of' / 'forgot how many'). Never confuse electrical specs ('10k Ohm', '20A', '24V') with quantity.
4. NEVER invent or divide numbers to guess a missing unit_price. If unit_price is not explicitly stated, set unit_price to null.
5. If a table or text includes a Part No or SKU column/code (e.g. STM32F407VGT6, ESP32-S3-WROOM-1, BR120), map it into sku_or_part_no.
6. Only set stated_total if an overall receipt/invoice total is explicitly written in the text. Never calculate stated_total yourself.
"""


def extract_naive_unstructured(raw_text: str, model: str = DEFAULT_MODEL) -> Tuple[str, Dict[str, Any]]:
    """
    Demonstrates the classic 'before' failure mode for Episode 1:
    Asking a small 3B model for JSON via prompt alone without grammar locking.
    """
    _ensure_ollama_running()
    t0 = time.perf_counter()
    response = ollama.chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Extract items, quantities, and prices into JSON format.",
            },
            {"role": "user", "content": raw_text},
        ],
        options={"temperature": 0.2},
        keep_alive="30m",
    )
    wall_ms = round((time.perf_counter() - t0) * 1000, 1)
    metrics = _parse_ollama_metrics(response, wall_ms)
    return response["message"]["content"], metrics


def extract_structured_erp(
    raw_text: str, model: str = DEFAULT_MODEL
) -> Tuple[PurchaseOrderExtraction, Dict[str, Any]]:
    """
    Production Two-Layer Defense pipeline used across Episodes 1, 2, 3, and 4:
    1. Enforces JSON schema at token-generation level via Ollama `format`.
    2. Validates and enriches via Pydantic `PurchaseOrderExtraction` model_validator.
    """
    _ensure_ollama_running()
    t0 = time.perf_counter()
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
        format=PurchaseOrderExtraction.model_json_schema(),
        options={"temperature": 0.0},
        keep_alive="30m",
    )
    wall_ms = round((time.perf_counter() - t0) * 1000, 1)
    metrics = _parse_ollama_metrics(response, wall_ms)

    raw_json = response["message"]["content"]
    validated_po = PurchaseOrderExtraction.model_validate_json(raw_json)
    return validated_po, metrics


def _parse_ollama_metrics(response: Any, wall_ms: float) -> Dict[str, Any]:
    """Extracts real Ollama engine timing (converting nanoseconds to milliseconds)."""
    ns_to_ms = 1_000_000.0
    load_ms = round(response.get("load_duration", 0) / ns_to_ms, 1)
    prompt_ms = round(response.get("prompt_eval_duration", 0) / ns_to_ms, 1)
    eval_ms = round(response.get("eval_duration", 0) / ns_to_ms, 1)
    eval_count = response.get("eval_count", 0)
    tokens_per_sec = round(eval_count / (eval_ms / 1000.0), 1) if eval_ms > 0 else 0.0

    return {
        "wall_time_ms": wall_ms,
        "load_duration_ms": load_ms,
        "prompt_eval_ms": prompt_ms,
        "eval_duration_ms": eval_ms,
        "output_tokens": eval_count,
        "tokens_per_sec": tokens_per_sec,
    }
