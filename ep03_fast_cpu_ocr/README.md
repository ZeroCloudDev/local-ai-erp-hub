# Episode 3 Implementation Plan: Fast CPU OCR + LLM Pipeline (Why Vision LLMs Crawl on CPU)

## 1. Engineering Objective
Prove with a real stopwatch benchmark why running an 11B Vision Language Model (`llama3.2-vision:11b`) on a laptop CPU takes 80+ seconds due to image patch tokenization and memory bandwidth limits — and replace it with a **3.5-second Two-Stage CPU Pipeline**:
1. **Stage 1 (`RapidOCR` ONNX + 12-line Y-Coordinate Sorter)**: Extracts text bounding boxes in ~0.6s on CPU and horizontally aligns item names with right-hand prices even on tilted photos.
2. **Stage 2 (`core/llm_client.py`)**: Sends the aligned text into `qwen2.5:3b` with our Episode 1 Two-Layer Defense.

## 2. Files Included
- [`ocr_pipeline.py`](ocr_pipeline.py): OpenCV pre-processing, RapidOCR ONNX execution, `sort_ocr_boxes_into_rows()`, and end-to-end timing metrics.
