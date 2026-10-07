param(
    [int]$UiPort = 5173,
    [int]$BackendPort = 8787
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root "tia-lib\Scripts\python.exe"
$logDir = Join-Path $root "logs"
$outLog = Join-Path $logDir "tia-backend.out.log"
$errLog = Join-Path $logDir "tia-backend.err.log"

if (-not (Test-Path $python)) {
    Write-Host "[TIA] ERROR: TIA virtual environment was not found at $python" -ForegroundColor Red
    exit 1
}

# =============================================================
# Pause helper.
#
# Read-Host throws when stdin is redirected (non-interactive
# launch), and with $ErrorActionPreference = "Stop" that aborts
# the failure block before it can reach exit 1 -- the script
# would then keep going and start the UI after reporting an
# error. Pause only when a prompt is actually possible.
# =============================================================

function Read-TiaPause {
    try { Read-Host | Out-Null } catch { }
}

# =============================================================
# 1. Free the backend port from a stale TIA backend process.
# =============================================================

$listener = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1

if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and $owner.ProcessName -like "*python*") {
        Write-Host "[TIA] Stopping stale backend (PID $($owner.Id)) holding port $BackendPort..." -ForegroundColor Yellow
        Stop-Process -Id $owner.Id -Force
        Start-Sleep -Milliseconds 800
    }
    else {
        Write-Host "[TIA] ERROR: port $BackendPort is held by '$($owner.ProcessName)' (PID $($owner.Id)). Free the port first." -ForegroundColor Red
        exit 1
    }
}

# =============================================================
# 2. Start the backend hidden with output captured to logs/.
# =============================================================

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$env:TIA_PORT = $BackendPort
$env:PYTHONIOENCODING = 'utf-8'

$backend = Start-Process `
    -FilePath $python `
    -ArgumentList "backend_service.py" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru

# =============================================================
# 3. Wait for /health before starting the UI.
# =============================================================

$ready = $false

for ($i = 0; $i -lt 40; $i++) {
    if ($backend.HasExited) {
        Write-Host "[TIA] ERROR: backend exited early (code $($backend.ExitCode))." -ForegroundColor Red
        break
    }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSec 2
        if ($health.status -eq "ok") { $ready = $true; break }
    }
    catch {
        Start-Sleep -Milliseconds 750
    }
}

if (-not $ready) {
    Write-Host "[TIA] ERROR: backend failed to become healthy on port $BackendPort." -ForegroundColor Red
    if ($backend.HasExited -and (Test-Path $errLog)) {
        Write-Host "[TIA] Recent error output:" -ForegroundColor Red
        Get-Content $errLog -Tail 40 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    }
    Write-Host "[TIA] Run aborted. Press Enter to close..." -ForegroundColor Yellow
    Read-TiaPause
    exit 1
}

Write-Host "[TIA] Backend online at http://127.0.0.1:$BackendPort (PID $($backend.Id))" -ForegroundColor Green

# =============================================================
# 3a. Report the shell used by the run_terminal capability.
#
# Agent-generated commands use POSIX syntax. On Windows that
# requires bash, which a Git installation provides without
# necessarily exposing it on PATH.
# =============================================================

$bashCommand = Get-Command "bash" -ErrorAction SilentlyContinue
if ($bashCommand) {
    Write-Host "[TIA] Terminal shell: bash ($($bashCommand.Source))" -ForegroundColor Green
}
else {
    $gitCommand = Get-Command "git" -ErrorAction SilentlyContinue
    $gitBash = $null
    if ($gitCommand) {
        $gitRoot = Split-Path -Parent (Split-Path -Parent $gitCommand.Source)
        foreach ($candidate in @("$gitRoot\bin\bash.exe", "$gitRoot\usr\bin\bash.exe")) {
            if (Test-Path $candidate) { $gitBash = $candidate; break }
        }
    }
    if (-not $gitBash) {
        foreach ($candidate in @("C:\Program Files\Git\bin\bash.exe", "C:\Program Files (x86)\Git\bin\bash.exe")) {
            if (Test-Path $candidate) { $gitBash = $candidate; break }
        }
    }
    if ($gitBash) {
        Write-Host "[TIA] Terminal shell: bash ($gitBash)" -ForegroundColor Green
    }
    else {
        Write-Host "[TIA] WARNING: bash was not found. run_terminal will fall back to PowerShell." -ForegroundColor Yellow
        Write-Host "[TIA] WARNING: POSIX-only commands such as printf will fail without bash." -ForegroundColor Yellow
    }
}

# =============================================================
# 3b. Make sure a local Ollama server is reachable.
# =============================================================

function Test-Ollama {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -eq 200)
    }
    catch {
        return $false
    }
}

if (Test-Ollama) {
    Write-Host "[TIA] Ollama is online at http://127.0.0.1:11434" -ForegroundColor Green
}
else {
    $ollama = Get-Command "ollama" -ErrorAction SilentlyContinue

    if (-not $ollama) {
        Write-Host "[TIA] WARNING: Ollama is not running and was not found on PATH." -ForegroundColor Yellow
        Write-Host "[TIA] WARNING: LLM nodes (evaluator/compressor) require a local Ollama server." -ForegroundColor Yellow
    }
    else {
        Write-Host "[TIA] Ollama is not running. Starting it now..." -ForegroundColor Yellow
        $ollamaOutLog = Join-Path $logDir "tia-ollama.out.log"
        $ollamaErrLog = Join-Path $logDir "tia-ollama.err.log"

        $ollamaReady = $false
        $ollamaProc = $null
        $maxStartAttempts = 3

        for ($attempt = 1; $attempt -le $maxStartAttempts; $attempt++) {
            if ($attempt -gt 1) {
                Write-Host "[TIA] Ollama start retry $attempt of $maxStartAttempts..." -ForegroundColor Yellow
                Start-Sleep -Seconds 2
            }

            $ollamaProc = Start-Process `
                -FilePath $ollama.Source `
                -ArgumentList "serve" `
                -WindowStyle Hidden `
                -RedirectStandardOutput $ollamaOutLog `
                -RedirectStandardError $ollamaErrLog `
                -PassThru

            for ($i = 0; $i -lt 40; $i++) {
                if ($ollamaProc.HasExited) { break }
                if (Test-Ollama) { $ollamaReady = $true; break }
                Start-Sleep -Milliseconds 750
            }

            if ($ollamaReady) { break }

            if (-not $ollamaProc.HasExited) {
                Stop-Process -Id $ollamaProc.Id -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 800
            }
        }

        if ($ollamaReady) {
            Write-Host "[TIA] Ollama online at http://127.0.0.1:11434 (PID $($ollamaProc.Id))" -ForegroundColor Green
        }
        else {
            Write-Host "[TIA] ERROR: Ollama failed to start on port 11434 after $maxStartAttempts attempts." -ForegroundColor Red
            if (Test-Path $ollamaErrLog) {
                Get-Content $ollamaErrLog -Tail 20 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
            }
            Write-Host "[TIA] Continuing without Ollama: LLM nodes (evaluator/compressor) will fail if they run." -ForegroundColor Yellow
        }
    }
}

# =============================================================
# 3c. Make sure an OmniRoute gateway is reachable.
# =============================================================

# OmniRoute is started outside this script, so it can only be probed. Every
# LLM node in TIA routes through it, so an unreachable gateway means the
# workflow cannot produce any model output.

function Read-TiaEnvValue {
    param([string]$Name)

    $envFile = Join-Path $root ".env"
    if (-not (Test-Path $envFile)) { return $null }

    foreach ($line in (Get-Content $envFile)) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }

    return $null
}

$omniBase = $env:OMNIROUTE_BASE_URL
if (-not $omniBase) { $omniBase = Read-TiaEnvValue "OMNIROUTE_BASE_URL" }
if (-not $omniBase) { $omniBase = "http://127.0.0.1:20128" }
$omniBase = $omniBase.TrimEnd("/")
if (-not $omniBase.EndsWith("/v1")) { $omniBase = "$omniBase/v1" }

$omniKey = $env:OMNIROUTE_API_KEY
if (-not $omniKey) { $omniKey = Read-TiaEnvValue "OMNIROUTE_API_KEY" }
if (-not $omniKey) { $omniKey = $env:OPENAI_API_KEY }
if (-not $omniKey) { $omniKey = Read-TiaEnvValue "OPENAI_API_KEY" }

$omniHeaders = @{ "Content-Type" = "application/json" }
if ($omniKey) {
    $omniHeaders["Authorization"] = "Bearer $omniKey"
}

$omniModelsRaw = $null

try {
    $omniModelsRaw = (Invoke-WebRequest -Uri "$omniBase/models" -Headers $omniHeaders -UseBasicParsing -TimeoutSec 5).Content
    Write-Host "[TIA] OmniRoute is online at $omniBase" -ForegroundColor Green
}
catch {
    $status = $null
    if ($_.Exception.Response) {
        $status = [int]$_.Exception.Response.StatusCode
    }

    if ($status -eq 401 -or $status -eq 403) {
        Write-Host "[TIA] ERROR: OmniRoute at $omniBase rejected the API key (HTTP $status)." -ForegroundColor Red
        Write-Host "[TIA] ERROR: Check OMNIROUTE_API_KEY in .env against the gateway's configured key." -ForegroundColor Red
    }
    elseif ($status) {
        Write-Host "[TIA] ERROR: OmniRoute at $omniBase returned HTTP $status." -ForegroundColor Red
    }
    else {
        Write-Host "[TIA] ERROR: OmniRoute is not reachable at $omniBase." -ForegroundColor Red
    }

    Write-Host "[TIA] ERROR: TIA routes every LLM node through OmniRoute, so no node will produce output." -ForegroundColor Red
    Write-Host "[TIA] Start OmniRoute, then re-run this script. Press Enter to close..." -ForegroundColor Yellow
    Read-TiaPause
    exit 1
}

# ------------------------------------------------------------
# 3d. Every model TIA can request must resolve to a catalog
#     entry, including the fallback used when a call fails.
#     TIA's model IDs are only usable through OMNIROUTE_MODEL_MAP:
#     the raw IDs are absent from the catalog by design, so a
#     missing mapping or a bad gateway catalog means every node
#     fails with no working fallback.
# ------------------------------------------------------------

$omniCatalog = $null

try {
    $omniCatalog = @(($omniModelsRaw | ConvertFrom-Json).data | ForEach-Object { [string]$_.id })
}
catch {
    Write-Host "[TIA] WARNING: Could not parse the OmniRoute model catalog; skipping model-target validation." -ForegroundColor Yellow
}

if ($omniCatalog) {
    $omniMapRaw = $env:OMNIROUTE_MODEL_MAP
    if (-not $omniMapRaw) { $omniMapRaw = Read-TiaEnvValue "OMNIROUTE_MODEL_MAP" }

    $omniMap = @{}
    if ($omniMapRaw) {
        try {
            $parsedMap = $omniMapRaw | ConvertFrom-Json
            foreach ($entry in $parsedMap.PSObject.Properties) {
                $omniMap[$entry.Name] = [string]$entry.Value
            }
        }
        catch {
            Write-Host "[TIA] ERROR: OMNIROUTE_MODEL_MAP in .env is not a valid JSON object." -ForegroundColor Red
            Write-Host '[TIA] ERROR: Expected {"tia/model": "provider/tia/model"} entries.' -ForegroundColor Red
            Read-TiaPause
            exit 1
        }
    }

    # Mirrors the model IDs in nodes/planner.py, nodes/critics.py,
    # nodes/task_executor.py, task_executor/task_worker.py,
    # output/generator.py and result_processing/memory_condenser.py.
    $tiaModels = @(
        "nvidia/nemotron-3.5-lightning-30b-a3b",
        "nvidia/nemotron-3-super-120b-a12b",
        "meta/muse-glimmer-30b",
        "openai/gpt-oss-20b"
    )

    $missing = @()
    foreach ($model in $tiaModels) {
        $target = $omniMap[$model]
        if (-not $target) { $target = $model }

        if ($omniCatalog -notcontains $target) {
            $missing += [pscustomobject]@{ Model = $model; Target = $target }
        }
    }

    if ($missing.Count -gt 0) {
        Write-Host "[TIA] ERROR: OmniRoute has no catalog entry for these models TIA will request:" -ForegroundColor Red
        foreach ($entry in $missing) {
            if ($entry.Model -eq $entry.Target) {
                Write-Host "[TIA] ERROR:   $($entry.Model) -- add an OMNIROUTE_MODEL_MAP entry in .env." -ForegroundColor Red
            }
            else {
                Write-Host "[TIA] ERROR:   $($entry.Model) -> $($entry.Target) -- OMNIROUTE_MODEL_MAP target is not in the catalog." -ForegroundColor Red
            }
        }

        Write-Host "[TIA] ERROR: TIA routes every LLM node through OmniRoute, so no node will produce output." -ForegroundColor Red
        Write-Host "[TIA] ERROR: Fix OMNIROUTE_MODEL_MAP in .env, then re-run this script. Press Enter to close..." -ForegroundColor Yellow
        Read-TiaPause
        exit 1
    }

    $fallbackTarget = $omniMap["openai/gpt-oss-20b"]
    if (-not $fallbackTarget) { $fallbackTarget = "openai/gpt-oss-20b" }
    Write-Host "[TIA] OmniRoute catalog OK: $($tiaModels.Count) TIA models resolve; fallback -> $fallbackTarget" -ForegroundColor Green
}

# =============================================================
# 4. Start the UI in the foreground.
# =============================================================

$ui = Join-Path $root "ui"
if (-not (Test-Path (Join-Path $ui "package.json"))) {
    Write-Host "[TIA] ERROR: UI package.json not found at $ui" -ForegroundColor Red
    exit 1
}

$env:VITE_TIA_API_URL = "http://127.0.0.1:$BackendPort"

Push-Location $ui
try {
    & npm run dev -- --host 127.0.0.1 --port $UiPort
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[TIA] Vite dev server exited with code $LASTEXITCODE. Press Enter to close..." -ForegroundColor Yellow
        Read-TiaPause
    }
}
finally {
    Pop-Location
}