# Cognia installer — Windows (PowerShell)
# Usage: irm https://raw.githubusercontent.com/tomascomenta-blip/cognia_v2/main/install.ps1 | iex
#
# Si la politica de ejecucion bloquea el script:
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser

$ErrorActionPreference = "Stop"
$REPO = "git+https://github.com/tomascomenta-blip/cognia_v2.git"

function Write-Ok($msg)   { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }
function Write-Step($msg) { Write-Host "`n$msg" -ForegroundColor Cyan }

Write-Step "Cognia installer"
Write-Host "Instalando desde GitHub..."
Write-Host "---------------------------------------------------"

# ── Python 3.11+ ──────────────────────────────────────
Write-Step "Verificando Python..."

$PY = $null
foreach ($cmd in @("python", "python3", "py")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $ok = & $cmd -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $PY = $cmd; break }
    }
}

if (-not $PY) {
    Write-Fail @"
Python 3.11+ no encontrado.

Opciones de instalacion:
  winget install Python.Python.3.11
  scoop install python
  Descarga: https://python.org/downloads  (marcar "Add to PATH")
"@
}

$pyVer = & $PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $pyVer"

# ── Instalar cognia ───────────────────────────────────
Write-Step "Instalando cognia..."
& $PY -m pip install --quiet --upgrade $REPO
if ($LASTEXITCODE -ne 0) { Write-Fail "pip install fallo." }

$cognia = Get-Command cognia -ErrorAction SilentlyContinue
if (-not $cognia) {
    # pip instalo en Scripts\ fuera del PATH de la sesion actual
    $scriptsDir = & $PY -c "import sysconfig; print(sysconfig.get_path('scripts'))"
    $env:PATH = "$scriptsDir;$env:PATH"
    $cognia = Get-Command cognia -ErrorAction SilentlyContinue
}

if ($cognia) {
    Write-Ok "cognia instalado en $($cognia.Source)"
} else {
    Write-Warn "cognia no esta en PATH."
    Write-Warn "Agrega la carpeta Scripts de Python a tu PATH y reinicia la terminal."
    Write-Warn "Luego ejecuta: cognia"
    exit 0
}

# ── Ollama (opcional) ─────────────────────────────────
Write-Step "Verificando Ollama..."
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Ok "Ollama disponible"
} else {
    Write-Warn "Ollama no encontrado."
    Write-Host "  Para usar inferencia local: https://ollama.ai"
    Write-Host "  Para unirte al swarm distribuido no es necesario."
}

# ── Listo ─────────────────────────────────────────────
Write-Host ""
Write-Host "---------------------------------------------------"
Write-Host "Instalacion completa." -ForegroundColor Green
Write-Host ""
Write-Host "  Ejecuta el siguiente comando para configurar Cognia:"
Write-Host ""
Write-Host "    cognia" -ForegroundColor White
Write-Host ""
Write-Host "  (el wizard se ejecuta automaticamente la primera vez)"
Write-Host ""
Write-Host "  Otros comandos:"
Write-Host "    cognia server       -- servidor web"
Write-Host "    cognia node         -- nodo del swarm distribuido"
Write-Host "    cognia coordinator  -- coordinador del swarm"
Write-Host "    cognia status       -- estado del sistema"
