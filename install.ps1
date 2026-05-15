# Cognia installer — Windows (PowerShell)
# Usage: irm https://raw.githubusercontent.com/tomascomenta-blip/cognia_v2/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$REPO = "git+https://github.com/tomascomenta-blip/cognia_v2.git"

function Write-Ok($msg)   { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }
function Write-Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }

Write-Host ""
Write-Host "  Cognia installer" -ForegroundColor White
Write-Host "  ----------------"

# ── Python 3.11+ ──────────────────────────────────────────────────────────────
Write-Step "Python"

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            $ok = & $cmd -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $cmd }
        }
    }
    return $null
}

$PY = Find-Python

if (-not $PY) {
    Write-Warn "Python 3.11+ no encontrado. Intentando instalar con winget..."

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
        # Recargar PATH de la sesion actual
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH", "User")
        $PY = Find-Python
    }

    if (-not $PY) {
        Write-Host ""
        Write-Fail @"
Python 3.11+ no encontrado y no se pudo instalar automaticamente.

Instalalo manualmente:
  1. Ve a https://python.org/downloads
  2. Descarga Python 3.11 o superior
  3. Durante la instalacion marca: [x] Add Python to PATH
  4. Vuelve a ejecutar este script
"@
    }
}

$pyVer = & $PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $pyVer"

# ── pip en PATH ───────────────────────────────────────────────────────────────
$scriptsDir = & $PY -c "import sysconfig; print(sysconfig.get_path('scripts'))"
if ($env:PATH -notlike "*$scriptsDir*") {
    $env:PATH = "$scriptsDir;$env:PATH"
}

# ── git (necesario para pip install git+https) ────────────────────────────────
Write-Step "Git"

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Warn "Git no encontrado. Intentando instalar con winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id Git.Git --source winget --accept-package-agreements --accept-source-agreements
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH", "User")
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Fail "Git no encontrado. Instalalo desde https://git-scm.com y vuelve a ejecutar este script."
    }
}
Write-Ok "Git $(git --version)"

# ── Instalar cognia-ai ────────────────────────────────────────────────────────
Write-Step "Instalando cognia-ai"

& $PY -m pip install --quiet --upgrade cognia-ai
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Fallo pip install cognia-ai. Intentando desde GitHub..."
    & $PY -m pip install --quiet --upgrade $REPO
    if ($LASTEXITCODE -ne 0) { Write-Fail "No se pudo instalar cognia-ai." }
}

# Recargar PATH por si pip instalo cognia en Scripts\
$scriptsDir = & $PY -c "import sysconfig; print(sysconfig.get_path('scripts'))"
$env:PATH = "$scriptsDir;$env:PATH"

$cognia = Get-Command cognia -ErrorAction SilentlyContinue
if ($cognia) {
    Write-Ok "cognia instalado en $($cognia.Source)"
} else {
    Write-Ok "cognia-ai instalado"
    Write-Warn "Reinicia PowerShell y ejecuta: cognia"
    exit 0
}

# ── Ollama (opcional) ─────────────────────────────────────────────────────────
Write-Step "Ollama (opcional)"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Ok "Ollama disponible"
} else {
    Write-Warn "Ollama no encontrado (solo necesario para modo standalone)"
    Write-Host "         Descarga: https://ollama.ai"
}

# ── Listo ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  -----------------------------------------------" -ForegroundColor Cyan
Write-Host "  Instalacion completa." -ForegroundColor Green
Write-Host ""
Write-Host "  Para configurar este dispositivo como nodo:"
Write-Host ""
Write-Host "    cognia install-weights --coordinator http://IP:8001" -ForegroundColor White
Write-Host "    cognia node" -ForegroundColor White
Write-Host ""
Write-Host "  Para usar de forma independiente (sin swarm):"
Write-Host ""
Write-Host "    cognia" -ForegroundColor White
Write-Host ""
