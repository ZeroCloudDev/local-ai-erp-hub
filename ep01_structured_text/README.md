# Episode 1 Implementation Plan: Guaranteed JSON Schema & Two-Layer Defense

## 1. Engineering Objective
Prove why regex post-processing and "Please respond in JSON" prompts fail on 3B local models, and implement a **Two-Layer Defense**:
1. **Layer 1 (Syntax Lock)**: Ollama `format=PurchaseOrderExtraction.model_json_schema()` (GBNF C++ grammar enforcement).
2. **Layer 2 (Semantic & Arithmetic Lock)**: Pydantic `@model_validator` in [`core/schemas.py`](../core/schemas.py) that preserves `null` (`None`) for missing data and flags arithmetic discrepancies (`needs_human_review = True`).

## 2. Files Included
- [`cli_demo.py`](cli_demo.py): Terminal benchmark across all 5 test messages in [`chaotic_messages.json`](../data/samples_ep1_text/chaotic_messages.json).
- [`app_streamlit.py`](app_streamlit.py): Side-by-side comparison UI + live SQLite ERP viewer.

## 3. Verification Commands
```powershell
python ep01_structured_text/cli_demo.py
python -m streamlit run ep01_structured_text/app_streamlit.py
```
