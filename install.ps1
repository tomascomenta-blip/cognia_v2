# install.ps1 -- Cognia one-command installer for Windows
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

function Has-Command($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

Write-Host "Cognia -- Windows installer"
Write-Host "---------------------------"

# Python 3.11+
if (-not (Has-Command "python")) {
    Write-Host "[FAIL] Python not found. Install Python 3.11+ from https://python.org" -ForegroundColor Red
    exit 1
}
$pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
$pyOk  = & python -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" 2>&1; $pyOk = ($LASTEXITCODE -eq 0)
if (-not $pyOk) {
    Write-Host "[FAIL] Python $pyVer found — 3.11+ required." -ForegroundColor Red
    exit 1
}
Write-Host "[OK]   Python $pyVer" -ForegroundColor Green

# Python dependencies
Write-Host "       Installing Python dependencies..."
& python -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] pip install failed." -ForegroundColor Red
    exit 1
}
Write-Host "[OK]   Python dependencies" -ForegroundColor Green

# Ollama (optional but required for inference)
if (Has-Command "ollama") {
    Write-Host "[OK]   Ollama" -ForegroundColor Green
} else {
    Write-Host "[WARN] Ollama not found. Download from https://ollama.ai" -ForegroundColor Yellow
    Write-Host "       Cognia requires Ollama to generate responses."
}

# Node.js + Electron (optional -- only for Desktop app)
if (Has-Command "node") {
    $nodeVer = & node --version 2>&1
    Write-Host "[OK]   Node.js $nodeVer" -ForegroundColor Green
    if (Test-Path "cognia_desktop\package.json") {
        Write-Host "       Installing Electron dependencies..."
        Push-Location cognia_desktop
        & npm install --quiet
        Pop-Location
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK]   Electron dependencies" -ForegroundColor Green
        } else {
            Write-Host "[WARN] npm install failed. Desktop app may not work." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "[WARN] Node.js not found. Desktop app will not be available." -ForegroundColor Yellow
    Write-Host "       Download from https://nodejs.org"
}

# .env from .env.example
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[OK]   .env created from .env.example" -ForegroundColor Green
    Write-Host "[WARN] Review .env and set COORDINATOR_KEY before production use." -ForegroundColor Yellow
} else {
    Write-Host "[SKIP] .env already exists" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host "  Start CLI:     python -m cognia.cli"
Write-Host "  Run checks:    python scripts/cognia_doctor.py"
Write-Host "  Start desktop: cd cognia_desktop && npm start"
