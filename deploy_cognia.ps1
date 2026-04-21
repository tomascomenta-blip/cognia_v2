# =============================================================================
# deploy_cognia.ps1 — Despliega los archivos del plan de migracion (Pasos 1-4)
# =============================================================================
# USO:
#   PowerShell -ExecutionPolicy Bypass -File .\deploy_cognia.ps1
#   PowerShell -ExecutionPolicy Bypass -File .\deploy_cognia.ps1 -DryRun
#   PowerShell -ExecutionPolicy Bypass -File .\deploy_cognia.ps1 -NoBackup

param(
    [string]$UpdateDir   = "cognia_update",
    [string]$ProjectRoot = $PSScriptRoot,
    [switch]$DryRun      = $false,
    [switch]$NoBackup    = $false
)

function Write-OK   { param($m) Write-Host "  [OK] $m" -ForegroundColor Green  }
function Write-SKIP { param($m) Write-Host "  [--] $m" -ForegroundColor Yellow }
function Write-FAIL { param($m) Write-Host "  [!!] $m" -ForegroundColor Red    }
function Write-HEAD { param($m) Write-Host "`n=== $m ===" -ForegroundColor Cyan }

$UpdatePath    = Join-Path $ProjectRoot $UpdateDir
$CogniaPackage = Join-Path $ProjectRoot "cognia"
$BackupDir     = Join-Path $ProjectRoot ("backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

$FileMap = [ordered]@{
    "web_app.py"                = "web_app.py"
    "language_engine.py"        = "language_engine.py"
    "respuestas_articuladas.py" = "respuestas_articuladas.py"
    "self_architect.py"         = "self_architect.py"
    "teacher_interface.py"      = "teacher_interface.py"
    "model_collapse_guard.py"   = "model_collapse_guard.py"
    "language_corrector.py"     = "language_corrector.py"
    "cognia.py"                 = "cognia\cognia.py"
}

# -- VALIDACIONES -------------------------------------------------------------
Write-HEAD "Validando entorno"

if (-not (Test-Path $UpdatePath)) {
    Write-FAIL "No se encontro la carpeta '$UpdateDir' en '$ProjectRoot'"
    Write-FAIL "Crea la carpeta y pon dentro los 8 archivos descargados."
    exit 1
}

if (-not (Test-Path $CogniaPackage -PathType Container)) {
    Write-FAIL "No se encontro el paquete 'cognia\' en '$ProjectRoot'"
    Write-FAIL "Asegurate de correr este script desde la raiz del proyecto."
    exit 1
}

$missing = @()
foreach ($src in $FileMap.Keys) {
    if (-not (Test-Path (Join-Path $UpdatePath $src))) { $missing += $src }
}
if ($missing.Count -gt 0) {
    Write-FAIL "Faltan archivos en '$UpdateDir':"
    foreach ($m in $missing) { Write-FAIL "  - $m" }
    exit 1
}

Write-OK "Todos los archivos encontrados"
Write-OK "Paquete cognia\ encontrado"

# -- BACKUP -------------------------------------------------------------------
if (-not $NoBackup) {
    Write-HEAD "Creando backup en $BackupDir"
    if (-not $DryRun) {
        New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $BackupDir "cognia") -Force | Out-Null
    }
    foreach ($dst in $FileMap.Values) {
        $dstPath = Join-Path $ProjectRoot $dst
        if (Test-Path $dstPath) {
            $backupPath   = Join-Path $BackupDir $dst
            $backupParent = Split-Path $backupPath -Parent
            if (-not $DryRun) {
                if (-not (Test-Path $backupParent)) {
                    New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
                }
                Copy-Item $dstPath $backupPath -Force
            }
            Write-OK "Backup: $dst"
        } else {
            Write-SKIP "Archivo nuevo (sin backup): $dst"
        }
    }
} else {
    Write-SKIP "Backup omitido (-NoBackup)"
}

# -- DESPLIEGUE ---------------------------------------------------------------
Write-HEAD "Desplegando archivos"

$deployed = 0
$errors   = 0

foreach ($entry in $FileMap.GetEnumerator()) {
    $src       = $entry.Key
    $dst       = $entry.Value
    $srcPath   = Join-Path $UpdatePath $src
    $dstPath   = Join-Path $ProjectRoot $dst
    $dstParent = Split-Path $dstPath -Parent

    try {
        if (-not $DryRun) {
            if (-not (Test-Path $dstParent)) {
                New-Item -ItemType Directory -Path $dstParent -Force | Out-Null
            }
            Copy-Item -Path $srcPath -Destination $dstPath -Force
        }
        $tag = if ($DryRun) { "[DRY] " } else { "" }
        Write-OK ($tag + $src + "  ->  " + $dst)
        $deployed++
    } catch {
        Write-FAIL ("Error copiando " + $src + " -> " + $dst + " : " + $_.Exception.Message)
        $errors++
    }
}

# -- VERIFICACION SINTAXIS PYTHON ---------------------------------------------
Write-HEAD "Verificando sintaxis Python"

$pyFiles = @(
    "web_app.py",
    "language_engine.py",
    "respuestas_articuladas.py",
    "self_architect.py",
    "teacher_interface.py",
    "model_collapse_guard.py",
    "language_corrector.py",
    "cognia\cognia.py"
)

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $v = & $cmd --version 2>&1
        if ($v -match "Python") { $pythonCmd = $cmd; break }
    } catch { }
}

if ($null -ne $pythonCmd) {
    $checkScript = "import ast, sys; ast.parse(open(sys.argv[1]).read()); print('OK')"
    foreach ($f in $pyFiles) {
        $fPath = Join-Path $ProjectRoot $f
        if (Test-Path $fPath) {
            $result = & $pythonCmd -c $checkScript $fPath 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-OK ("Sintaxis OK: " + $f)
            } else {
                Write-FAIL ("Error de sintaxis en " + $f + ": " + $result)
                $errors++
            }
        }
    }
} else {
    Write-SKIP "Python no encontrado en PATH - omitiendo verificacion de sintaxis"
}

# -- RESUMEN ------------------------------------------------------------------
Write-HEAD "Resumen"

Write-Host ("  Archivos desplegados : " + $deployed) -ForegroundColor White

if ($errors -gt 0) {
    Write-Host ("  Errores              : " + $errors) -ForegroundColor Red
} else {
    Write-Host "  Errores              : 0" -ForegroundColor Green
}

if ((-not $NoBackup) -and (-not $DryRun)) {
    Write-Host ("  Backup guardado en   : " + $BackupDir) -ForegroundColor White
}

Write-Host ""

if ($errors -eq 0) {
    Write-Host "Despliegue completado. Arranca el servidor con:" -ForegroundColor Green
    Write-Host "  python web_app.py" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Endpoints nuevos:" -ForegroundColor White
    Write-Host "  GET  /api/learning_health        estado del sistema de aprendizaje" -ForegroundColor Gray
    Write-Host "  POST /api/learn/batch            ensenanza en lote" -ForegroundColor Gray
    Write-Host "  GET  /api/architect/collapse     reporte CollapseGuard" -ForegroundColor Gray
    Write-Host "  GET  /api/architect/engine_zones zonas debiles del LanguageEngine" -ForegroundColor Gray
    Write-Host "  GET  /api/architect/estado       estado SelfArchitect" -ForegroundColor Gray
    Write-Host "  POST /api/energy/loop            ciclo de optimizacion energetica" -ForegroundColor Gray
} else {
    Write-FAIL ("Hubo " + $errors + " error(es). Revisa los mensajes anteriores.")
    if ((-not $NoBackup) -and (-not $DryRun)) {
        Write-FAIL ("Restaura desde: " + $BackupDir)
    }
    exit 1
}
