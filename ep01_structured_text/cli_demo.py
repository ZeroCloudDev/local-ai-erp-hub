"""
Episode 1 CLI Benchmark:
Compares Naive Prompting vs. Two-Layer Defense (Ollama C++ GBNF Schema Lock + Pydantic Math Validator)
across 5 chaotic field messages.
"""

import json
from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm_client import extract_structured_erp, DEFAULT_MODEL
from core.database import save_extraction

SAMPLES_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "samples_ep1_text"
    / "chaotic_messages.json"
)


def run_benchmark(model: str = DEFAULT_MODEL) -> None:
    samples = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
    print(f"=== EPISODE 1 BENCHMARK: {model} (Two-Layer Defense) ===\n")

    for sample in samples:
        print(f"--- {sample['title']} ---")
        print(f"Input: {sample['text']}\n")

        po, metrics = extract_structured_erp(sample["text"], model=model)
        po_id = save_extraction(
            po=po,
            source_type="ep01_text",
            source_name=sample["source_name"],
            raw_content=sample["text"],
            wall_time_ms=metrics["wall_time_ms"],
        )

        status_str = "⚠️ NEEDS HUMAN REVIEW" if po.needs_human_review else "✅ AUTO-APPROVED"
        print(f"DB Record #{po_id} | Status: {status_str}")
        print(
            f"Timing: wall={metrics['wall_time_ms']} ms | "
            f"eval={metrics['eval_duration_ms']} ms | "
            f"speed={metrics['tokens_per_sec']} tok/s"
        )
        print(po.model_dump_json(indent=2))
        print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    run_benchmark()
