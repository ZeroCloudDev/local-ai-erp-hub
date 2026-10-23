<#
EP05 - full local rehearsal on the presenter's laptop (real MariaDB, real Ollama model, real photo).

Run from the repository root:
    powershell -ExecutionPolicy Bypass -File ep05_fiscal_ingest_robot\run_ep05_rehearsal.ps1
    powershell -ExecutionPolicy Bypass -File ep05_fiscal_ingest_robot\run_ep05_rehearsal.ps1 -Order Reverse

What it does (each step prints PASS/FAIL; it stops at the first failure):
  0. records machine, versions, model, input hashes into a transcript log
  1. starts XAMPP MariaDB if port 3306 is closed
  2. checks Ollama and the model, unloads it so the first load is measured separately
  3. resets kasa_ep05 and verifies the seed (5 / 0)
  4. processes the three documents with the REAL model (order: Normal or Reverse)  -> 27 / 3
  5. resolves 95012 = 3.49 as operator, then submits it again (must have no effect) -> 28 / 2
  6. drops the message again (replay)                                                -> 28 / 2
  7. snapshot, fail probe with injected failure, identical snapshot                  -> 28 / 2
  8. exports the CSV and prints the same SELECT as HeidiSQL
  9. runs EP05 unittest suites, including saved real-model answers (DB tests opt-in)

It never pushes to GitHub and never touches the original POS dump.
Inputs are synthetic fixtures with frozen expectations; measured outcomes are produced by this run.
#>
param(
    [ValidateSet("Normal", "Reverse")] [string]$Order = "Normal",
    [switch]$UseSimulatedPhoto,   # dry run only; the log then says SIMULATED PHOTO
    [switch]$DbTests,
    [string]$XamppDir = "C:\xampp"
)
# PowerShell operations fail immediately. Native stderr handling is localized in Run().
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$Ep = Join-Path $Root "ep05_fiscal_ingest_robot"
$Inputs = Join-Path $Ep "demo_inputs"
$Stamp = (Get-Date -Format "yyyyMMdd_HHmmss_fff") + "_" + $Order
$LogDir = Join-Path $Root "data\ep05_archive\rehearsal"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "rehearsal_${Stamp}_$Order.log"
Start-Transcript -Path $Log | Out-Null
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"

# Use .NET directly: Get-FileHash is not exposed in every Windows PowerShell host.
# Compute the actual bytes; failure to open/read propagates and stops rehearsal.
function Get-Ep05Sha256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return [System.BitConverter]::ToString($sha.ComputeHash($stream)).Replace("-", "") }
    finally { $sha.Dispose(); $stream.Dispose() }
}

function Step($t) { Write-Host ""; Write-Host "==== $t ====" -ForegroundColor Cyan }
function Run($label, [scriptblock]$cmd) {
    # Windows PowerShell 5.1 wraps native stderr as NativeCommandError.
    # Genuine PowerShell errors still fail; every native exit code is checked.
    $ErrorActionPreference = "Continue"
    $global:LASTEXITCODE = 0
    $runState = @{ Failed = $false }
    try {
        & $cmd 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord] -and
                $_.FullyQualifiedErrorId -notlike 'NativeCommandError*') { $runState.Failed = $true }
            "$_"
        } | Out-Host
        if ($runState.Failed -or $LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE; PowerShell error=$($runState.Failed)" }
    } catch { throw "FAIL: $label : $_" }
}
function Py {
    # Preserve both direct arguments and legacy inline arrays in PowerShell 5.1.
    # A typed remaining-arguments parameter can stringify an array as one path.
    $PythonArgs = @()
    foreach ($argument in $args) {
        if ($argument -is [Array]) { $PythonArgs += @($argument) }
        else { $PythonArgs += [string]$argument }
    }
    if ($PythonArgs[0] -like '*verify_demo.py') {
        if ((Get-Ep05Sha256 $Config) -ne $ConfigHash) { throw "Configuration changed during rehearsal" }
        $PythonArgs += @("--expected-sha256", $ExpectedHash)
    }
    & $Py -B @PythonArgs
}

try {
    if (-not $env:EP05_DB_PASSWORD) {
        $sec = Read-Host "Password for the local ep05_demo MySQL user (any local value)" -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        try { $env:EP05_DB_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }
    if ($null -eq $env:EP05_ADMIN_PASSWORD) { $env:EP05_ADMIN_PASSWORD = "" }   # XAMPP root default

    Step "0. Machine, versions, inputs"
    $cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
    $ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
    $gpu = (Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }) -join "; "
    Write-Host "CPU: $cpu | RAM: $ram GB | GPU(s): $gpu"
    Run "Python version" { & $Py -B --version }
    Run "already installed dependencies" { Py -c "import pymysql, ollama, pdfplumber, rapidocr_onnxruntime, watchdog, reportlab; print('Dependencies installed; no download/install step')" }
    Run "git HEAD" { git -C $Root rev-parse HEAD }
    Run "git status" { git -C $Root status --short }
    $ExpectedPath = Join-Path $Inputs "expected_results.json"
    $ExpectedHash = (Get-Ep05Sha256 $ExpectedPath)
    $Config = Join-Path $Ep "pos_adapter_config.toml"
    if (-not (Test-Path -LiteralPath $Config)) { $Config = Join-Path $Ep "pos_adapter_config.example.toml" }
    $ConfigHash = (Get-Ep05Sha256 $Config)
    Write-Host "expected_results sha256=$ExpectedHash"
    Write-Host "config sha256=$ConfigHash"
    Get-Content (Join-Path $Ep "pos_adapter_config.example.toml") | Select-String "profile_version|^name ="
    $photo = Join-Path $Inputs "shelf_tags_photo.jpg"
    if ($UseSimulatedPhoto) {
        $photo = Join-Path $Root "tests\fixtures\ep05_simulated_shelf_photo.jpg"
        Write-Host "!!! SIMULATED PHOTO - this run is NOT valid for recording !!!" -ForegroundColor Yellow
    } elseif (-not (Test-Path $photo)) {
        Write-Host "Missing demo_inputs\shelf_tags_photo.jpg. Print demo_inputs\shelf_tags_to_print.pdf," -ForegroundColor Red
        Write-Host "photograph it with a phone and save it under that name. (Or use -UseSimulatedPhoto for a dry run.)" -ForegroundColor Red
        exit 1
    }
    $docs = @(
        @{ Name = "register_update_message.txt"; Src = (Join-Path $Inputs "register_update_message.txt") },
        @{ Name = "approved_retail_price_update.pdf"; Src = (Join-Path $Inputs "approved_retail_price_update.pdf") },
        @{ Name = "shelf_tags_photo.jpg"; Src = $photo }
    )
    if ($Order -eq "Reverse") { [array]::Reverse($docs) }
    foreach ($d in $docs + @(@{ Name = "fail_probe.txt"; Src = (Join-Path $Inputs "fail_probe.txt") })) {
        $h = (Get-Ep05Sha256 $d.Src)
        Write-Host ("input {0,-34} sha256={1}" -f $d.Name, $h)
    }

    Step "1. MariaDB"
    function PortOpen { try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", 3306); $c.Close(); return $true } catch { return $false } }
    $open = PortOpen
    if (-not $open) {
        Write-Host "starting XAMPP MariaDB ..."
        Start-Process -FilePath (Join-Path $XamppDir "mysql\bin\mysqld.exe") `
            -ArgumentList "--defaults-file=$(Join-Path $XamppDir 'mysql\bin\my.ini')", "--standalone" -WindowStyle Hidden
        for ($i = 0; $i -lt 30 -and -not $open; $i++) {
            Start-Sleep -Seconds 1
            $open = PortOpen
        }
    }
    if (-not $open) { throw "MariaDB is not listening on 3306" }
    Run "MariaDB version" { & (Join-Path $XamppDir "mysql\bin\mysql.exe") --version }

    Step "2. Ollama + model"
    Run "ollama" { ollama --version }
    $model = "qwen2.5:3b"
    Run "model present" { ollama show $model }
    Run "model unload" { ollama stop $model }
    Write-Host "model unloaded; the first model call below includes the model load time"
    Write-Host "-- quick model probe on the demo lines (no database) --"
    $ProbePassed = $true
    try {
        if ($UseSimulatedPhoto) { Run "model diagnostic" { Py "$Ep\probe_model_lines.py" } }
        else { Run "model diagnostic" { Py "$Ep\probe_model_lines.py" --photo $photo } }
    } catch { $ProbePassed = $false; Write-Host "MODEL DIAGNOSTIC FAILED: $_" -ForegroundColor Yellow }
    Run "unload before timed processing" { ollama stop $model }

    Step "3. Database reset + seed"
    Run "setup" { Py @("$Ep\setup_demo_db.py", "--reset") }
    Run "verify seed" { Py @("$Ep\verify_demo.py", "--phase", "seed") }

    Step "4. Three documents, real model, order $Order"
    $WatcherResult = Join-Path $LogDir "watcher_$Stamp.json"
    $WatcherArgs = @("$Ep\pos_watch_service.py", "--watch-smoke") + @($docs | ForEach-Object { $_.Src }) + @("--result-json", $WatcherResult)
    Run "real startup/rename/created watcher" { Py @WatcherArgs }
    $watchProof = Get-Content -LiteralPath $WatcherResult -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    if ($watchProof.status -ne "watcher_smoke_pass" -or $watchProof.documents_processed -ne 3) { throw "Incomplete watcher evidence" }
    Run "processor allocation" { ollama ps }
    Run "verify after three" { Py @("$Ep\verify_demo.py", "--phase", "after_three_documents") }
    Py @("$Ep\quarantine_cli.py", "list")

    Step "5. Operator resolves 95012 = 3.49 (twice)"
    Run "resolve" { Py @("$Ep\quarantine_cli.py", "resolve", "sku:95012", "--price", "3.49", "--operator", "Eldar", "--confirm", "price confirmed by Mike") }
    Run "resolve again" { Py @("$Ep\quarantine_cli.py", "resolve", "sku:95012", "--price", "3.49", "--operator", "Eldar", "--confirm", "double submit test") }
    Run "verify after resolution" { Py @("$Ep\verify_demo.py", "--phase", "after_resolution") }

    Step "6. Replay"
    Run "replay" { Py @("$Ep\pos_watch_service.py", "--once", (Join-Path $Inputs "register_update_message.txt")) }
    Run "verify after replay" { Py @("$Ep\verify_demo.py", "--phase", "after_replay") }

    Step "7. Rollback proof"
    Run "snapshot" { Py @("$Ep\snapshot_demo_state.py", "--label", "before_fail_$Stamp") }
    $FailureResult = Join-Path $LogDir "failure_$Stamp.json"
    $OldFailureSetting = $env:EP05_FAIL_AFTER_OPS
    try {
        $env:EP05_FAIL_AFTER_OPS = "3"
        Run "fail probe" { Py @("$Ep\pos_watch_service.py", "--once", (Join-Path $Inputs "fail_probe.txt"), "--demo-failure-injection", "--result-json", $FailureResult) }
    } finally {
        if ($null -eq $OldFailureSetting) { Remove-Item Env:\EP05_FAIL_AFTER_OPS -ErrorAction SilentlyContinue }
        else { $env:EP05_FAIL_AFTER_OPS = $OldFailureSetting }
    }
    Run "verify after fail probe" { Py @("$Ep\verify_demo.py", "--phase", "after_fail_probe", "--snapshot-before", "before_fail_$Stamp", "--failure-result", $FailureResult) }

    Step "8. Export + final view"
    Run "export" { Py @("$Ep\export_pos_csv.py", "--show") }

    Step "9. Tests"
    $OldDbTests = $env:EP05_DB_TESTS
    try {
        $env:EP05_DB_TESTS = "0"
        Run "EP05 unit and saved-answer regression tests" { Py -m unittest discover -s tests -p "test_ep05*.py" -v }
        Run "recorded video line checks" { Py -m unittest discover -s tests -p "test_video_lines.py" -v }
        if ($DbTests) {
            $env:EP05_DB_TESTS = "1"
            Run "opt-in DB tests" { Py -m unittest discover -s tests -p "test_ep05_db.py" -v }
            Write-Host "DB tests reset kasa_ep05; rerun without -DbTests before recording." -ForegroundColor Yellow
        }
    } finally {
        if ($null -eq $OldDbTests) { Remove-Item Env:\EP05_DB_TESTS -ErrorAction SilentlyContinue }
        else { $env:EP05_DB_TESTS = $OldDbTests }
    }
    if ((Get-Ep05Sha256 $ExpectedPath) -ne $ExpectedHash) { throw "Expected results changed during rehearsal" }
    if ((Get-Ep05Sha256 $Config) -ne $ConfigHash) { throw "Configuration changed during rehearsal" }
    if (-not $ProbePassed) { throw "Model diagnostic failed; this rehearsal cannot be ALL PASS" }

    Write-Host ""
    if ($UseSimulatedPhoto -or $DbTests) { Write-Host "DRY RUN CHECKS PASS - NOT RECORDING EVIDENCE" -ForegroundColor Yellow }
    else { Write-Host "REHEARSAL $Order : ALL PASS (real watcher and three-mutation rollback)" -ForegroundColor Green }
    Write-Host "Reports: data\ep05_archive\reports\   Log: $Log"
} catch {
    Write-Host "REHEARSAL FAILED: $_" -ForegroundColor Red
    exit 1
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}
