# Cognia installer — Windows (PowerShell)
# Usage: irm https://raw.githubusercontent.com/tomascomenta-blip/cognia_v2/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$PYPI_PKG = "cognia-ai"
$REPO     = "git+https://github.com/tomascomenta-blip/cognia_v2.git"

function Write-Ok($msg)   { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }
function Write-Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }

Write-Host ""
Write-Host "  Cognia installer" -ForegroundColor White
Write-Host "  ----------------"

# ── Python 3.11+ ──────────────────────────────────────────────────────────────
Write-Step "Python"

function Refresh-EnvPath {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")
    # Agregar rutas de instalacion comunes que winget puede no haber propagado aun
    foreach ($ver in @("313", "312", "311")) {
        $base = "$env:LOCALAPPDATA\Programs\Python\Python$ver"
        if (Test-Path $base) {
            if ($env:PATH -notlike "*$base\Scripts*") { $env:PATH = "$base\Scripts;$env:PATH" }
            if ($env:PATH -notlike "*$base;*")        { $env:PATH = "$base;$env:PATH" }
        }
    }
}

function Find-Python {
    # Probar comandos especificos primero para evitar falsos positivos
    foreach ($cmd in @("python3.13", "python3.12", "python3.11", "python", "python3", "py")) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { continue }
        & $cmd -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $cmd }
    }
    return $null
}

$PY = Find-Python

if (-not $PY) {
    Write-Warn "Python 3.11+ no encontrado. Intentando instalar con winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        $installed = $false
        foreach ($pyId in @("Python.Python.3.12", "Python.Python.3.11")) {
            winget install --id $pyId --source winget --accept-package-agreements --accept-source-agreements --silent 2>$null
            if ($LASTEXITCODE -eq 0) { $installed = $true; break }
        }
        if ($installed) {
            Refresh-EnvPath
            $PY = Find-Python
        }
    }

    if (-not $PY) {
        Write-Fail @"
Python 3.11+ no encontrado y no se pudo instalar automaticamente.

  1. Ve a https://python.org/downloads
  2. Descarga Python 3.12 o superior
  3. Durante la instalacion marca: [x] Add Python to PATH
  4. Vuelve a ejecutar este script
"@
    }
}

$pyVer = & $PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $pyVer"

# Asegurar que el directorio Scripts este en PATH para esta sesion
$scriptsDir = & $PY -c "import sysconfig; print(sysconfig.get_path('scripts'))"
if ($env:PATH -notlike "*$scriptsDir*") {
    $env:PATH = "$scriptsDir;$env:PATH"
}

# ── Instalar cognia-ai ────────────────────────────────────────────────────────
Write-Step "Instalando cognia-ai"

& $PY -m pip install --quiet --upgrade $PYPI_PKG
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Fallo pip install desde PyPI."
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        Write-Warn "Intentando desde GitHub..."
        & $PY -m pip install --quiet --upgrade $REPO
        if ($LASTEXITCODE -ne 0) { Write-Fail "No se pudo instalar cognia-ai." }
    } else {
        Write-Fail "No se pudo instalar cognia-ai desde PyPI. Verifica tu conexion a internet."
    }
}

$cognia = Get-Command cognia -ErrorAction SilentlyContinue
if ($cognia) {
    Write-Ok "cognia instalado en $($cognia.Source)"
} else {
    Write-Ok "cognia-ai instalado (el comando cognia estara disponible en una nueva sesion de PowerShell)"
    Write-Warn "Reinicia PowerShell y ejecuta: cognia"
    exit 0
}

# ── Ollama (opcional) ─────────────────────────────────────────────────────────
Write-Step "Ollama (opcional)"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Ok "Ollama disponible"
} else {
    Write-Warn "Ollama no encontrado (necesario para modo standalone)"
    Write-Host "         Descarga: https://ollama.ai"
}

# ── Listo ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  -----------------------------------------------" -ForegroundColor Cyan
Write-Host "  Instalacion completa." -ForegroundColor Green
Write-Host ""
Write-Host "  Uso standalone (sin swarm):"
Write-Host ""
Write-Host "    cognia" -ForegroundColor White
Write-Host ""
Write-Host "  Configurar como nodo del swarm:"
Write-Host ""
Write-Host "    cognia install-weights --coordinator http://IP:8001" -ForegroundColor White
Write-Host "    cognia node" -ForegroundColor White
Write-Host ""
