# cognia_launcher.ps1
# Lanzador para el acceso directo del escritorio.
# Configura el entorno y arranca cognia con una ventana presentable.

$Host.UI.RawUI.WindowTitle = "Cognia"

# Asegurar que pip Scripts este en PATH
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python311\Scripts",
    "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts",
    "$env:APPDATA\Python\Python311\Scripts",
    "$env:APPDATA\Python\Python312\Scripts"
)
foreach ($dir in $candidates) {
    if ((Test-Path $dir) -and ($env:PATH -notlike "*$dir*")) {
        $env:PATH = "$dir;$env:PATH"
    }
}

# Verificar que cognia esta instalado
$cognia = Get-Command cognia -ErrorAction SilentlyContinue
if (-not $cognia) {
    Write-Host "Cognia no encontrado. Instalando..." -ForegroundColor Yellow
    pip install cognia-ai --quiet
    $env:PATH = "$env:LOCALAPPDATA\Programs\Python\Python311\Scripts;$env:PATH"
}

Write-Host ""
Write-Host "  Cognia v3.2" -ForegroundColor Cyan
Write-Host "  -----------"
Write-Host ""

cognia
