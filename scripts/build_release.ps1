<#
.SYNOPSIS
    Build a signed Cognia Desktop installer for Windows.

.DESCRIPTION
    1. Installs Node dependencies in cognia_desktop/
    2. Runs electron-builder with the extended config
    3. Outputs the NSIS installer to cognia_desktop/dist/

.PARAMETER Version
    Override the version tag (e.g. "0.8.1"). Defaults to value in package.json.

.PARAMETER SkipSign
    Skip code signing even if CSC_LINK is set.

.EXAMPLE
    .\scripts\build_release.ps1
    .\scripts\build_release.ps1 -Version "0.8.1" -SkipSign
#>

param(
    [string]$Version  = "",
    [switch]$SkipSign = $false
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT   = Split-Path $PSScriptRoot -Parent
$DESK   = Join-Path $ROOT "cognia_desktop"

function Write-Step([string]$msg) { Write-Host "[BUILD] $msg" }
function Write-OK([string]$msg)   { Write-Host "[OK] $msg" }
function Write-Fail([string]$msg) { Write-Host "[FAIL] $msg"; exit 1 }

# ── Validate prerequisites ─────────────────────────────────────────────

Write-Step "Checking Node.js..."
try { node --version | Out-Null }
catch { Write-Fail "Node.js not found. Install from https://nodejs.org" }
Write-OK "Node.js"

Write-Step "Checking Python..."
try { python --version | Out-Null }
catch { Write-Fail "Python not found." }
Write-OK "Python"

# ── Install Node dependencies ──────────────────────────────────────────

Write-Step "Installing Node dependencies..."
Push-Location $DESK
try {
    npm install --no-audit --no-fund --prefer-offline
    if ($LASTEXITCODE -ne 0) { Write-Fail "npm install failed." }
    Write-OK "npm install"
} finally {
    Pop-Location
}

# ── Set version if provided ────────────────────────────────────────────

if ($Version -ne "") {
    Write-Step "Setting version to $Version..."
    Push-Location $DESK
    try {
        npm version $Version --no-git-tag-version | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Fail "npm version failed." }
        Write-OK "Version set to $Version"
    } finally {
        Pop-Location
    }
}

# ── Configure signing ──────────────────────────────────────────────────

if ($SkipSign) {
    $env:CSC_LINK = ""
    $env:CSC_KEY_PASSWORD = ""
    Write-Step "Code signing skipped (--SkipSign)."
} elseif ($env:CSC_LINK) {
    Write-OK "Code signing enabled via CSC_LINK."
} else {
    Write-Step "CSC_LINK not set. Building unsigned installer."
}

# ── Run electron-builder ───────────────────────────────────────────────

Write-Step "Running electron-builder..."
Push-Location $DESK
try {
    npx electron-builder --win `
        --config electron-builder.config.js `
        --publish never
    if ($LASTEXITCODE -ne 0) { Write-Fail "electron-builder failed." }
    Write-OK "Build complete."
} finally {
    Pop-Location
}

# ── Report output ──────────────────────────────────────────────────────

$DIST = Join-Path $DESK "dist"
Write-Host ""
Write-Host "[DONE] Installer written to: $DIST"
Get-ChildItem $DIST -Filter "*.exe" | ForEach-Object { Write-Host "       $_" }
