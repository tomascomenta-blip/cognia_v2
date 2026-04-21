# aplicar_paso4.ps1
# Delega toda la logica en Python para evitar conflictos de sintaxis con PowerShell

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  COGNIA PASO 4 - Aplicando Decision Gate tres zonas  " -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

foreach ($f in @("language_engine.py", "symbolic_responder.py", "decision_gate.py")) {
    if (-not (Test-Path $f)) {
        Write-Host "ERROR: No se encontro '$f' en la carpeta actual." -ForegroundColor Red
        exit 1
    }
}
Write-Host "OK - Archivos encontrados." -ForegroundColor Green

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "language_engine.py"    "language_engine.py.bak_$ts"
Copy-Item "symbolic_responder.py" "symbolic_responder.py.bak_$ts"
Write-Host "OK - Backups creados (.bak_$ts)" -ForegroundColor Green

$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $pyCmd) {
    Write-Host "ERROR: Python no encontrado en PATH." -ForegroundColor Red
    exit 1
}

$pyFile = [System.IO.Path]::Combine($PSScriptRoot, "aplicar_paso4_helper.py")
if (-not (Test-Path $pyFile)) {
    Write-Host "ERROR: No se encontro 'aplicar_paso4_helper.py' en la carpeta actual." -ForegroundColor Red
    Write-Host "Asegurate de que aplicar_paso4_helper.py este junto a este script." -ForegroundColor Red
    exit 1
}

& $pyCmd.Source $pyFile

Write-Host ""
Write-Host "Backups: language_engine.py.bak_$ts / symbolic_responder.py.bak_$ts" -ForegroundColor Gray
Write-Host "Para verificar: busca 'stage=decision' en tus logs." -ForegroundColor Gray
