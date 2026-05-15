# cognia_launcher.ps1
# Lanzador para el acceso directo del escritorio.
# Configura el entorno y arranca cognia con una ventana presentable.

$Host.UI.RawUI.WindowTitle = "Cognia"

# Agregar directorios Scripts de instalaciones Python conocidas
$scriptsDirs = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\Scripts",
    "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts",
    "$env:LOCALAPPDATA\Programs\Python\Python311\Scripts",
    "$env:APPDATA\Python\Python313\Scripts",
    "$env:APPDATA\Python\Python312\Scripts",
    "$env:APPDATA\Python\Python311\Scripts"
)
foreach ($dir in $scriptsDirs) {
    if ((Test-Path $dir) -and ($env:PATH -notlike "*$dir*")) {
        $env:PATH = "$dir;$env:PATH"
    }
}

# Encontrar Python (necesario para el fallback de instalacion)
function Find-AnyPython {
    foreach ($cmd in @("python3.13", "python3.12", "python3.11", "python", "python3", "py")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) { return $cmd }
    }
    return $null
}

# Si cognia no esta instalado, instalarlo
$cognia = Get-Command cognia -ErrorAction SilentlyContinue
if (-not $cognia) {
    Write-Host "[WARN] cognia no encontrado en PATH. Instalando..." -ForegroundColor Yellow
    $py = Find-AnyPython
    if ($py) {
        & $py -m pip install cognia-ai --upgrade --quiet
        # Refrescar Scripts dirs por si el ejecutable acaba de aparecer
        foreach ($dir in $scriptsDirs) {
            if ((Test-Path $dir) -and ($env:PATH -notlike "*$dir*")) {
                $env:PATH = "$dir;$env:PATH"
            }
        }
    } else {
        Write-Host "[ERROR] Python no encontrado." -ForegroundColor Red
        Write-Host "Instala Python 3.12+ desde https://python.org y vuelve a abrir esta ventana." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""
Write-Host "  Cognia v3.2" -ForegroundColor Cyan
Write-Host "  -----------"
Write-Host ""

# Intentar el ejecutable cognia; si falla, usar python -m cognia
$cognia = Get-Command cognia -ErrorAction SilentlyContinue
if ($cognia) {
    cognia
} else {
    $py = Find-AnyPython
    if ($py) {
        & $py -m cognia
    } else {
        Write-Host "[ERROR] No se encontro cognia ni Python." -ForegroundColor Red
        Write-Host "Ejecuta el instalador de nuevo o instala Python 3.12+ desde https://python.org" -ForegroundColor Yellow
        exit 1
    }
}
