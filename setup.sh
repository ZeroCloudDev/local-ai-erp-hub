#!/usr/bin/env bash
# ==============================================================================
# ZERO-CLOUD ERP ENGINE ON A LAPTOP (Local AI + Python)
# Automated One-Click Setup Script for Linux & macOS
# ==============================================================================

set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}================================================================================${NC}"
echo -e "${CYAN}   ZERO-CLOUD ERP ENGINE ON A LAPTOP (Local AI + Python)                        ${NC}"
echo -e "${CYAN}   Automated Setup Pipeline (POSIX / Linux / macOS)                             ${NC}"
echo -e "${CYAN}================================================================================${NC}"

# 1. VERIFY PYTHON
echo -e "\n${CYAN}--- [1/6] Verifying Python 3.10+ ---${NC}"
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo -e "${RED}[ERROR] Python was not found in PATH!${NC}"
    echo -e "${YELLOW}Please install Python 3.10+ from https://www.python.org/downloads/${NC}"
    exit 1
fi

PY_VER=$($PYTHON_BIN -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON_BIN -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON_BIN -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo -e "${RED}[ERROR] Python $PY_VER is installed, but Python 3.10+ is required.${NC}"
    exit 1
fi
echo -e "${GREEN}[SUCCESS] Found Python $PY_VER ($($PYTHON_BIN -c 'import sys; print(sys.executable)'))${NC}"

# 2. VERIFY OLLAMA
echo -e "\n${CYAN}--- [2/6] Verifying Ollama & Local Model ---${NC}"
if ! command -v ollama >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Ollama command not found!${NC}"
    echo -e "${YELLOW}Please install Ollama from: https://ollama.com/download${NC}"
    exit 1
fi
echo -e "${GREEN}[SUCCESS] Found Ollama binary in PATH.${NC}"

# Check if Ollama daemon is running
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo -e "${YELLOW}[INFO] Ollama service not running. Starting 'ollama serve' in background...${NC}"
    ollama serve >/dev/null 2>&1 &
    sleep 3
fi

# Check for qwen2.5:3b
if curl -fsS http://127.0.0.1:11434/api/tags | "$PYTHON_BIN" -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(m.get("name")=="qwen2.5:3b" or m.get("model")=="qwen2.5:3b" for m in d.get("models", [])) else 1)' ; then
    echo -e "${GREEN}[SUCCESS] Model 'qwen2.5:3b' is already cached locally.${NC}"
else
    echo -e "${YELLOW}[INFO] Downloading model 'qwen2.5:3b' (~1.9 GB)...${NC}"
    ollama pull qwen2.5:3b
    echo -e "${GREEN}[SUCCESS] Model 'qwen2.5:3b' ready.${NC}"
fi

# 3. VIRTUAL ENVIRONMENT
echo -e "\n${CYAN}--- [3/6] Setting Up Virtual Environment (.venv) ---${NC}"
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}[INFO] Creating .venv...${NC}"
    $PYTHON_BIN -m venv .venv
    echo -e "${GREEN}[SUCCESS] Virtual environment created.${NC}"
else
    echo -e "${GREEN}[SUCCESS] Existing .venv directory found.${NC}"
fi

VENV_PY=".venv/bin/python"

# 4. INSTALL DEPENDENCIES
echo -e "\n${CYAN}--- [4/6] Installing Dependencies from requirements.txt ---${NC}"
if ! $VENV_PY -m pip --version >/dev/null 2>&1; then
    echo -e "${YELLOW}[INFO] Bootstrapping pip in virtual environment...${NC}"
    $VENV_PY -m ensurepip --upgrade
fi
$VENV_PY -m pip install --upgrade pip --quiet
$VENV_PY -m pip install -r requirements.txt --quiet
echo -e "${GREEN}[SUCCESS] Dependencies installed successfully.${NC}"

# 5. GENERATE TEST ASSETS & INIT DB
echo -e "\n${CYAN}--- [5/6] Generating Test Assets & Initializing SQLite DB ---${NC}"
$VENV_PY data/generate_test_assets.py
$VENV_PY -c "from core.database import init_db; init_db(); print('SQLite schema verified.')"
echo -e "${GREEN}[SUCCESS] Database and test files ready.${NC}"

# 6. SMOKE TEST
echo -e "\n${CYAN}--- [6/6] Running Smoke Test ---${NC}"
$VENV_PY -c "from core.schemas import PurchaseOrderExtraction; from core.llm_client import extract_structured_erp; print('[PASS] Core modules verified.')"
echo -e "${GREEN}[SUCCESS] Smoke test passed!${NC}"

echo -e "\n${GREEN}================================================================================${NC}"
echo -e "${GREEN}   SETUP COMPLETE! ALL 4 EPISODES ARE READY TO RUN                              ${NC}"
echo -e "${GREEN}================================================================================${NC}"
echo -e "Run Part 1 CLI:          ./.venv/bin/python ep01_structured_text/cli_demo.py"
echo -e "Run Part 1 Dashboard:    ./.venv/bin/streamlit run ep01_structured_text/app_streamlit.py"
echo -e "Run Part 2 PDF CLI:      ./.venv/bin/python ep02_pdf_tables/cli_demo.py"
echo -e "Run Part 2 Dashboard:    ./.venv/bin/streamlit run ep02_pdf_tables/app_streamlit.py"
echo -e "Run Part 3 CPU OCR:      ./.venv/bin/python ep03_fast_cpu_ocr/cli_demo.py"
echo -e "Run Part 4 Watch Daemon: ./.venv/bin/python ep04_watchdog_daemon/watcher_service.py"
echo -e "${GREEN}================================================================================${NC}"
