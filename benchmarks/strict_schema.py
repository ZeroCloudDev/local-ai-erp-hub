"""
Strict variant of the EP01 schema, used only by the benchmark (`--schema strict`).

Experiment 2026-10-26 (benchmarks/README.md): in core/schemas.py `items` has
`default_factory=list`, so the JSON schema sent to Ollama does not list it as
required and a model may leave it out. Here `items` is required and must hold
at least one line. Everything else is inherited unchanged: the same fields and
descriptions, and the same Layer 2 validator (math, missing fields, totals).

The episode code is not edited. The runner swaps the class that
core.llm_client uses, so the strict schema is both the `format` sent to Ollama
and the model that parses the answer, for EP01, EP02, EP03 and the synthetic
messages. EP05 has its own per-line schema and is not affected.
"""

from typing import List

from pydantic import ConfigDict, Field

from core.schemas import LineItem, PurchaseOrderExtraction


class StrictPurchaseOrderExtraction(PurchaseOrderExtraction):
    # Same title as the original, so the only difference in the JSON schema is
    # `items` in `required` plus `minItems: 1`.
    model_config = ConfigDict(title="PurchaseOrderExtraction")

    items: List[LineItem] = Field(
        ...,
        min_length=1,
        description="All purchased items mentioned in the message.",
    )
