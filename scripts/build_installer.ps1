<#
.SYNOPSIS
    Compila cognia-setup.exe usando Inno Setup.

.DESCRIPTION
    Genera un instalador grafico de Windows que:
      - Instala Python 3.11 si no esta presente
      - Ejecuta pip install cognia-ai
      - Crea accesos directos en el escritorio y menu inicio

.EXAMPLE
    .\scripts\build_installer.ps1
#>

$ErrorActionPreference = "Stop"
$ROOT      = Split-Path $PSScriptRoot -Parent
$INSTALLER = Join-Path $ROOT "installer"
$ISS_FILE  = Join-Path $INSTALLER "cognia_setup.iss"

function Write-Step($msg) { Write-Host "[BUILD] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "[FAIL]  $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  Cognia -- Build Installer" -ForegroundColor White
Write-Host "  -------------------------"
Write-Host ""

# ── Buscar Inno Setup ─────────────────────────────────────────────────────────
Write-Step "Buscando Inno Setup..."

$iscc = $null
$candidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Get-Command ISCC -ErrorAction SilentlyContinue)?.Source
)
foreach ($c in $candidates) {
    if ($c -and (Test-Path $c)) { $iscc = $c; break }
}

if (-not $iscc) {
    Write-Host ""
    Write-Host "  Inno Setup no encontrado." -ForegroundColor Yellow
    Write-Host "  Descargandolo automaticamente..."

    $installerExe = "$env:TEMP\innosetup-installer.exe"
    $innoURL = "https://files.jrsoftware.org/is/6/innosetup-6.3.3.exe"

    Write-Step "Descargando Inno Setup (~5MB)..."
    Invoke-WebRequest -Uri $innoURL -OutFile $installerExe -UseBasicParsing

    Write-Step "Instalando Inno Setup (silencioso)..."
    Start-Process -FilePath $installerExe -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait
    Remove-Item $installerExe -Force

    $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) {
        Write-Fail "No se pudo instalar Inno Setup. Descargalo manualmente: https://jrsoftware.org/isinfo.php"
    }
}

Write-Ok "Inno Setup: $iscc"

# ── Crear directorio dist en installer/ ───────────────────────────────────────
$distDir = Join-Path $INSTALLER "dist"
if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Path $distDir | Out-Null }

# ── Compilar el installer ─────────────────────────────────────────────────────
Write-Step "Compilando cognia-setup.exe..."

Push-Location $INSTALLER
try {
    & $iscc $ISS_FILE
    if ($LASTEXITCODE -ne 0) { Write-Fail "ISCC fallo con codigo $LASTEXITCODE" }
} finally {
    Pop-Location
}

# ── Resultado ─────────────────────────────────────────────────────────────────
$output = Join-Path $INSTALLER "dist\cognia-setup.exe"
if (Test-Path $output) {
    $sizeMB = [math]::Round((Get-Item $output).Length / 1MB, 1)
    Write-Host ""
    Write-Ok "Installer creado: $output ($sizeMB MB)"
    Write-Host ""
    Write-Host "  Sube este archivo a GitHub Releases para que los usuarios lo descarguen." -ForegroundColor White
    Write-Host "  gh release create v3.2.0 '$output' --title 'Cognia v3.2.0' --notes 'Instalador Windows'"
    Write-Host ""
} else {
    Write-Fail "No se genero el archivo de salida."
}
