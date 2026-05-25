# Cognia installer — Windows (PowerShell)
# Usage (from web, no repo needed):
#   irm https://raw.githubusercontent.com/tomascomenta-blip/cognia_v2/main/install.ps1 | iex
#
# Usage (from inside the cloned repo):
#   .\install.ps1
#   .\install.ps1 --local        # standalone mode, no network required after setup
#   .\install.ps1 --coordinator https://my-coordinator.example.com

param(
    [switch]$Local,
    [string]$Coordinator = "https://cognia-coordinator-production.up.railway.app"
)

$ErrorActionPreference = "Stop"

function ok($msg)   { Write-Host "  [ok]  $msg" -ForegroundColor Green }
function warn($msg) { Write-Host "  [--]  $msg" -ForegroundColor Yellow }
function fail($msg) { Write-Host "  [!!]  $msg" -ForegroundColor Red; exit 1 }
function step($msg) { Write-Host "`n  $msg" -ForegroundColor White }

Write-Host ""
Write-Host "  Cognia" -ForegroundColor White
Write-Host "  ------"
Write-Host ""
Write-Host "  Cognia is a P2P AI network. You contribute one model fragment"
Write-Host "  (~300 MB of storage) and get access to the full AI model in return."
Write-Host ""

# ── Detect if running from repo or as standalone script ──────────────────────

$SCRIPT_DIR = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
$IN_REPO    = Test-Path (Join-Path $SCRIPT_DIR "scripts\cognia_setup.py")
$DATA_DIR   = Join-Path $env:USERPROFILE ".cognia"
$REPO_DIR   = if ($IN_REPO) { $SCRIPT_DIR } else { Join-Path $DATA_DIR "repo" }
$VENV_DIR   = Join-Path $DATA_DIR "env"
$ENV_FILE   = Join-Path $DATA_DIR ".env"
$SHARDS_DIR = Join-Path $DATA_DIR "shards\qwen-coder-3b-q4"

# ── Python 3.11+ ──────────────────────────────────────────────────────────────
step "Checking Python..."

function Refresh-EnvPath {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
    foreach ($ver in @("313","312","311")) {
        $base = "$env:LOCALAPPDATA\Programs\Python\Python$ver"
        if (Test-Path $base) {
            if ($env:PATH -notlike "*$base\Scripts*") { $env:PATH = "$base\Scripts;$env:PATH" }
            if ($env:PATH -notlike "*$base;*")        { $env:PATH = "$base;$env:PATH" }
        }
    }
}

function Find-Python {
    foreach ($cmd in @("python3.13","python3.12","python3.11","python","python3","py")) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { continue }
        & $cmd -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $cmd }
    }
    return $null
}

$PY = Find-Python

if (-not $PY) {
    warn "Python 3.11+ not found. Trying to install via winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        foreach ($pyId in @("Python.Python.3.12","Python.Python.3.11")) {
            winget install --id $pyId --source winget `
                --accept-package-agreements --accept-source-agreements --silent 2>$null
            if ($LASTEXITCODE -eq 0) { Refresh-EnvPath; $PY = Find-Python; break }
        }
    }
    if (-not $PY) {
        fail @"
Python 3.11+ not found and could not be installed automatically.

  1. Go to https://python.org/downloads
  2. Download Python 3.12 or newer
  3. During installation, check: [x] Add Python to PATH
  4. Re-run this script
"@
    }
}

$pyVer = & $PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
ok "Python $pyVer"

# Add Scripts to PATH for this session
$scriptsDir = & $PY -c "import sysconfig; print(sysconfig.get_path('scripts'))"
if ($env:PATH -notlike "*$scriptsDir*") { $env:PATH = "$scriptsDir;$env:PATH" }

# ── Clone repo if not already local ──────────────────────────────────────────

if (-not $IN_REPO) {
    step "Downloading Cognia..."

    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        fail @"
git is required to download Cognia.

  Option A: Install Git from https://git-scm.com/download/win
  Option B: Download the repo as a ZIP from GitHub and run install.ps1 from inside it.
"@
    }

    if (-not (Test-Path $REPO_DIR)) {
        New-Item -ItemType Directory -Path $REPO_DIR -Force | Out-Null
        git clone --depth 1 https://github.com/tomascomenta-blip/cognia_v2.git "$REPO_DIR"
        if ($LASTEXITCODE -ne 0) { fail "Could not clone Cognia repository." }
    } else {
        ok "Repository already present at $REPO_DIR"
    }
}

ok "Cognia source: $REPO_DIR"

# ── Virtual environment ───────────────────────────────────────────────────────
step "Setting up Python environment..."

if (-not (Test-Path (Join-Path $VENV_DIR "Scripts\python.exe"))) {
    & $PY -m venv "$VENV_DIR" --prompt cognia
    if ($LASTEXITCODE -ne 0) { fail "Could not create virtual environment." }
    ok "Virtual environment created"
} else {
    ok "Virtual environment already exists"
}

$VPYTHON = Join-Path $VENV_DIR "Scripts\python.exe"

# ── Install dependencies ──────────────────────────────────────────────────────
step "Installing dependencies..."

$reqFile = Join-Path $REPO_DIR "requirements.txt"
if (-not (Test-Path $reqFile)) { fail "requirements.txt not found in $REPO_DIR" }

& $VPYTHON -m pip install -r "$reqFile" -q --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { fail "Failed to install dependencies. Check your internet connection." }
ok "Dependencies installed"

# ── Run Cognia setup ──────────────────────────────────────────────────────────
step "Setting up Cognia..."

$setupScript = Join-Path $REPO_DIR "scripts\cognia_setup.py"
if (-not (Test-Path $setupScript)) { fail "Setup script not found: $setupScript" }

if ($Local) {
    Write-Host ""
    Write-Host "  Running in standalone mode." -ForegroundColor White
    Write-Host "  Downloading all 4 model fragments (~1.1 GB)."
    Write-Host ""
    & $VPYTHON "$setupScript" --mode cli --coordinator local `
        --shards-dir "$SHARDS_DIR" --env-path "$ENV_FILE"
} else {
    Write-Host ""
    Write-Host "  Connecting to the Cognia network at:" -ForegroundColor White
    Write-Host "  $Coordinator"
    Write-Host ""
    Write-Host "  The coordinator will assign you one model fragment (~300 MB)."
    Write-Host "  You'll host it in exchange for full AI access."
    Write-Host ""
    & $VPYTHON "$setupScript" --mode cli --coordinator "$Coordinator" `
        --shards-dir "$SHARDS_DIR" --env-path "$ENV_FILE"
}

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    warn "Setup encountered an issue."
    Write-Host ""
    Write-Host "  If the network is unavailable, try standalone mode:"
    Write-Host "  .\install.ps1 --local" -ForegroundColor White
    exit 1
}

# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ----------------------------------------" -ForegroundColor Green
Write-Host "  Cognia is ready." -ForegroundColor Green
Write-Host ""
Write-Host "  Start the desktop app:"
Write-Host "    cd $REPO_DIR\cognia_desktop && npm start" -ForegroundColor White
Write-Host ""
Write-Host "  Or use the command line:"
Write-Host "    $VPYTHON -m cognia" -ForegroundColor White
Write-Host ""
