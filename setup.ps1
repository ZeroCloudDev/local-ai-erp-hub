<#
.SYNOPSIS
    One-Click Automated Setup Script for "Zero-Cloud ERP Engine on a Laptop"
.DESCRIPTION
    Automates Python venv creation, Ollama validation & model download, dependency installation,
    synthetic test data generation, and SQLite database initialization.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup.ps1
#>

param(
    [switch]$SkipModelPull = $false
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "`n========================================================" -ForegroundColor Cyan
    Write-Host " [STEP] $Message" -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

Clear-Host
Write-Host @"
================================================================================
   ZERO-CLOUD ERP ENGINE ON A LAPTOP (Local AI + Python)
   Automated One-Click Environment Setup Pipeline
   100% Offline | Zero Cloud Fees | Standard Laptop CPU Friendly
================================================================================
"@ -ForegroundColor DarkCyan

# -------------------------------------------------------------
# 1. VERIFY PYTHON
# -------------------------------------------------------------
Write-Step "1/6: Verifying Python Installation (Requires 3.10+)"

$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
}

if (-not $pythonCmd) {
    Write-Err "Python was not found in your system PATH!"
    Write-Info "Please download and install Python 3.10+ from: https://www.python.org/downloads/"
    Write-Info "IMPORTANT: Make sure to check the box 'Add python.exe to PATH' during installation."
    Exit 1
}

$rawPyVersion = (& $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
$pyMajor = [int]($rawPyVersion.Split('.')[0])
$pyMinor = [int]($rawPyVersion.Split('.')[1])

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Write-Err "Detected Python $rawPyVersion, but Python 3.10 or higher is required."
    Write-Info "Please install a modern Python version from https://www.python.org/downloads/"
    Exit 1
}
Write-Success "Found Python $rawPyVersion at $(Get-Command $pythonCmd | Select-Object -ExpandProperty Source)"

# -------------------------------------------------------------
# 2. VERIFY & INITIALIZE OLLAMA
# -------------------------------------------------------------
Write-Step "2/6: Verifying Ollama & Local AI Model (qwen2.5:3b)"

$ollamaExe = $null
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $ollamaExe = (Get-Command ollama).Source
} else {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) {
            $ollamaExe = $cand
            break
        }
    }
}

if (-not $ollamaExe) {
    Write-Err "Ollama executable not found in PATH or standard installation directories."
    Write-Info "Please install Ollama from: https://ollama.com/download"
    Write-Info "After installation, re-run this setup script."
    Exit 1
}
Write-Success "Found Ollama at: $ollamaExe"

# Ensure Ollama server is running on port 11434
$isListening = $false
try {
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 -ErrorAction Stop
    $isListening = $true
} catch {
    $isListening = $false
}

if (-not $isListening) {
    Write-Info "Ollama background service is not running. Starting local daemon ('$ollamaExe serve')..."
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    
    # Wait for daemon up to 10 seconds
    $retries = 20
    while ($retries -gt 0 -and -not $isListening) {
        Start-Sleep -Milliseconds 500
        try {
            $res = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 1 -ErrorAction Stop
            $isListening = $true
            break
        } catch {
            $retries--
        }
    }
}

if ($isListening) {
    Write-Success "Ollama server is active and listening on http://127.0.0.1:11434"
} else {
    Write-Err "Could not establish connection to Ollama server at http://127.0.0.1:11434"
    Write-Info "Please start Ollama manually from your Start Menu and try again."
    Exit 1
}

# Check if model qwen2.5:3b exists
$modelFound = $false
try {
    $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
    if ($tags.models) {
        foreach ($m in $tags.models) {
            if ($m.name -ceq "qwen2.5:3b" -or $m.model -ceq "qwen2.5:3b") {
                $modelFound = $true
                break
            }
        }
    }
} catch {
    # Fallback to CLI
}

if ($modelFound) {
    Write-Success "Model 'qwen2.5:3b' is already available locally in Ollama cache."
} elseif ($SkipModelPull) {
    Write-Info "Skipping model pull (-SkipModelPull switch specified)."
} else {
    Write-Info "Model 'qwen2.5:3b' not found locally (~1.9 GB). Downloading now via Ollama..."
    & $ollamaExe pull qwen2.5:3b
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to pull 'qwen2.5:3b'. Please run 'ollama pull qwen2.5:3b' manually."
        Exit 1
    }
    Write-Success "Model 'qwen2.5:3b' downloaded successfully."
}

# -------------------------------------------------------------
# 3. VIRTUAL ENVIRONMENT CREATION
# -------------------------------------------------------------
Write-Step "3/6: Creating Python Virtual Environment (.venv)"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$venvDir = Join-Path $scriptDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Info "Creating virtual environment at $venvDir..."
    & $pythonCmd -m venv ".venv"
    if (-not (Test-Path $venvPython)) {
        Write-Err "Failed to create virtual environment."
        Exit 1
    }
    Write-Success "Virtual environment created."
} else {
    Write-Success "Existing virtual environment detected at $venvDir."
}

# -------------------------------------------------------------
# 4. INSTALL DEPENDENCIES
# -------------------------------------------------------------
Write-Step "4/6: Installing Python Dependencies from requirements.txt"

# Ensure pip is present in virtual environment (handles environments created with uv or without pip)
$hasPip = $false
try {
    & $venvPython -m pip --version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $hasPip = $true }
} catch {
    $hasPip = $false
}

if (-not $hasPip) {
    Write-Info "pip not found in virtual environment. Bootstrapping via ensurepip..."
    & $venvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to bootstrap pip inside virtual environment."
        Exit 1
    }
}

Write-Info "Upgrading pip..."
& $venvPython -m pip install --upgrade pip --quiet

Write-Info "Installing core and episode packages..."
& $venvPython -m pip install -r (Join-Path $scriptDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Err "Failed to install dependencies from requirements.txt"
    Exit 1
}
Write-Success "All Python packages installed successfully."

# -------------------------------------------------------------
# 5. GENERATE TEST DATA & INITIALIZE DATABASE
# -------------------------------------------------------------
Write-Step "5/6: Generating Synthetic Test Data & Initializing SQLite DB"

$genScript = Join-Path $scriptDir "data\generate_test_assets.py"
if (Test-Path $genScript) {
    Write-Info "Generating PDF invoices, OCR receipt images, and field test assets..."
    & $venvPython $genScript
    if ($LASTEXITCODE -ne 0) { throw "Test asset generation failed." }
    Write-Success "Test assets generated in data/ directory."
}

Write-Info "Initializing idempotent SQLite database (data/erp_procurement.db)..."
& $venvPython -c "from core.database import init_db; init_db(); print('SQLite schema verified.')"
if ($LASTEXITCODE -ne 0) { throw "SQLite initialization failed." }
Write-Success "Database initialized successfully."

# -------------------------------------------------------------
# 6. SMOKE TEST & VERIFICATION
# -------------------------------------------------------------
Write-Step "6/6: Running Core Engine Smoke Test"

$smokeCode = @"
from core.schemas import PurchaseOrderExtraction, LineItem
from core.database import get_connection
conn = get_connection()
conn.execute('SELECT count(*) FROM purchase_orders')
conn.close()
print('[PASS] Pydantic models & SQLite connection verified.')
"@

& $venvPython -c $smokeCode
if ($LASTEXITCODE -ne 0) {
    Write-Err "Smoke test failed! Please check logs above."
    Exit 1
}
Write-Success "Smoke test passed with zero errors!"

# -------------------------------------------------------------
# COMPLETION BANNER
# -------------------------------------------------------------
Write-Host @"

================================================================================
   SETUP COMPLETE! ALL 4 EPISODES ARE READY TO RUN
================================================================================

How to launch each episode (Windows PowerShell):

  * Ep 01 CLI Demo (5 Field Messages -> SQLite):
      .\.venv\Scripts\python.exe ep01_structured_text\cli_demo.py

  * Ep 01 Streamlit Dashboard (Live Accounting UI):
      .\.venv\Scripts\streamlit.exe run ep01_structured_text\app_streamlit.py

  * Ep 02 B2B PDF Table X-Ray CLI Demo:
      .\.venv\Scripts\python.exe ep02_pdf_tables\cli_demo.py

  * Ep 02 Streamlit Dashboard (PDF X-Ray Web UI):
      .\.venv\Scripts\streamlit.exe run ep02_pdf_tables\app_streamlit.py

  * Ep 03 CPU OCR Receipt Parser:
      .\.venv\Scripts\python.exe ep03_fast_cpu_ocr\cli_demo.py

  * Ep 04 Autonomous Watch-Folder Daemon:
      .\.venv\Scripts\python.exe ep04_watchdog_daemon\watcher_service.py

================================================================================
"@ -ForegroundColor Green

# -----------------------------------------------------------------
# INTERACTIVE EXPERIMENT LAUNCHER
# -----------------------------------------------------------------
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " SELECT AN EXPERIMENT TO RUN NOW (or press Enter to exit):" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " [1] Episode 1: CLI Benchmark (5 Field Messages -> SQLite)"
Write-Host " [2] Episode 1: Launch Streamlit Accounting Dashboard (Web UI)"
Write-Host " [3] Episode 2: Multi-Column B2B PDF Table X-Ray CLI Demo"
Write-Host " [4] Episode 2: Launch PDF Table X-Ray Dashboard (Web UI)"
Write-Host " [5] Episode 3: Fast CPU Receipt OCR + Y-Coordinate Sorter Demo"
Write-Host " [6] Episode 4: Start Autonomous Watch-Folder Daemon"
Write-Host " [Q] Quit to prompt"
Write-Host "-----------------------------------------------------------------"
$Choice = Read-Host "Enter choice (1-6 or Q)"
switch ($Choice) {
    "1" { & $venvPython ep01_structured_text\cli_demo.py }
    "2" { & ".\.venv\Scripts\streamlit.exe" run ep01_structured_text\app_streamlit.py }
    "3" { & $venvPython ep02_pdf_tables\cli_demo.py }
    "4" { & ".\.venv\Scripts\streamlit.exe" run ep02_pdf_tables\app_streamlit.py }
    "5" { & $venvPython ep03_fast_cpu_ocr\cli_demo.py }
    "6" { & $venvPython ep04_watchdog_daemon\watcher_service.py }
    Default { Write-Host "`nSetup finished. You can run any demo manually using .\.venv\Scripts\python.exe" -ForegroundColor Green }
}
