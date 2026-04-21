# =============================================================================
# apply_goal_pattern_engine.ps1
# Aplica los cambios de GoalAndPatternEngine - PASO 7 + PASO 8 - a Cognia
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "C:\Users\Tomanquito\Downloads\cognia\cognia_v2\cognia"
$CogniaFile  = Join-Path $ProjectRoot "cognia.py"
$LangFile    = Join-Path $ProjectRoot "language_engine.py"

foreach ($f in @($CogniaFile, $LangFile)) {
    if (-not (Test-Path $f)) {
        Write-Error "No se encontro el archivo: $f"
        exit 1
    }
}

function Backup-File {
    param([string]$path)
    $ts     = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backup = "$path.bak_$ts"
    Copy-Item -Path $path -Destination $backup
    Write-Host "   Backup creado: $backup"
}

function Apply-Patch {
    param(
        [string]$FilePath,
        [string]$OldText,
        [string]$NewText,
        [string]$Desc
    )

    $content = [System.IO.File]::ReadAllText($FilePath, [System.Text.Encoding]::UTF8)

    if (-not $content.Contains($OldText)) {
        Write-Warning "   OMITIDO - ya aplicado o no encontrado: $Desc"
        return
    }

    $newContent = $content.Replace($OldText, $NewText)
    [System.IO.File]::WriteAllText($FilePath, $newContent, [System.Text.Encoding]::UTF8)
    Write-Host "   OK: $Desc"
}

# =============================================================================
# PARCHE 1 - cognia.py - __init__ - importar GoalAndPatternEngine
# =============================================================================
$p1_old = @'
        # ── PASO 6: ConsolidationEngine (consolidación y limpieza) ─────
        try:
            from consolidation_engine import get_consolidation_engine
            self._consolidation_engine = get_consolidation_engine(
                db_path,
                consolidation_interval=self.consolidation_interval,
            )
            print("✅ ConsolidationEngine PASO 6 activo")
        except ImportError:
            self._consolidation_engine = None
'@

$p1_new = @'
        # ── PASO 6: ConsolidationEngine (consolidación y limpieza) ─────
        try:
            from consolidation_engine import get_consolidation_engine
            self._consolidation_engine = get_consolidation_engine(
                db_path,
                consolidation_interval=self.consolidation_interval,
            )
            print("✅ ConsolidationEngine PASO 6 activo")
        except ImportError:
            self._consolidation_engine = None

        # ── PASO 7+8: GoalAndPatternEngine (objetivos + patrones) ──────
        try:
            from goal_and_pattern_engine import GoalAndPatternEngine
            self._goal_engine = GoalAndPatternEngine(db_path)
            print("✅ GoalAndPatternEngine PASOS 7+8 activo")
        except ImportError:
            self._goal_engine = None
'@

# =============================================================================
# PARCHE 2 - cognia.py - observe - pre_observe al inicio
# =============================================================================
$p2_old = @'
        features = self.perception.extract_features(observation)
        vec = features["vector"]
        emotion = features["emotion"]

        working_hits = self.working_mem.find_similar_in_buffer(vec, threshold=0.7)
'@

$p2_new = @'
        features = self.perception.extract_features(observation)
        vec = features["vector"]
        emotion = features["emotion"]

        # ── PASO 7: detectar/actualizar objetivo activo ────────────────
        if self._goal_engine:
            self._goal_engine.pre_observe(observation, vec)

        working_hits = self.working_mem.find_similar_in_buffer(vec, threshold=0.7)
'@

# =============================================================================
# PARCHE 3 - cognia.py - observe - post_observe y tick antes del return
# =============================================================================
$p3_old = @'
        if self._maintenance:
            self._maintenance.tick(self.interaction_count)

        # PASO 6: ciclo ligero de consolidación (decay + weaken suave)
        if self._consolidation_engine is not None:
            try:
                self._consolidation_engine.tick(self.interaction_count)
            except Exception:
                pass

        return result
'@

$p3_new = @'
        if self._maintenance:
            self._maintenance.tick(self.interaction_count)

        # PASO 6: ciclo ligero de consolidación (decay + weaken suave)
        if self._consolidation_engine is not None:
            try:
                self._consolidation_engine.tick(self.interaction_count)
            except Exception:
                pass

        # ── PASO 7+8: post_observe y tick ─────────────────────────────
        if self._goal_engine:
            self._goal_engine.post_observe(observation, result)
            self._goal_engine.tick(self.interaction_count)

        return result
'@

# =============================================================================
# PARCHE 4 - cognia.py - sleep - run_pattern_batch
# =============================================================================
$p4_old = @'
        # Language Engine — evolución de prompts + reporte al architect
        engine_info = ""
        if HAS_LANGUAGE_ENGINE:
'@

$p4_new = @'
        # ── PASO 7+8: aprendizaje por patrones ────────────────────────
        pattern_info = ""
        if self._goal_engine:
            try:
                pattern_info = self._goal_engine.run_pattern_batch(
                    semantic_memory=self.semantic,
                    interaction_count=self.interaction_count,
                )
            except Exception:
                pass

        # Language Engine — evolución de prompts + reporte al architect
        engine_info = ""
        if HAS_LANGUAGE_ENGINE:
'@

# =============================================================================
# PARCHE 5 - cognia.py - sleep - añadir pattern_info al return
# =============================================================================
$p5_old = '                + consolidation6_info + architect_info)'
$p5_new = '                + consolidation6_info + architect_info + pattern_info)'

# =============================================================================
# PARCHE 6 - language_engine.py - _build_context - inyectar goal_hint
# =============================================================================
$p6_old = @'
    def _build_context(self, ai, question: str) -> str:
        """
        Construye contexto cognitivo completo.
        Intenta importar construir_contexto desde respuestas_articuladas
        con paths absoluto y relativo para robustez.
        """
        try:
            try:
                from respuestas_articuladas import construir_contexto
            except ImportError:
                from cognia.respuestas_articuladas import construir_contexto
            return construir_contexto(ai, question)
        except Exception:
            return ""
'@

$p6_new = @'
    def _build_context(self, ai, question: str) -> str:
        """
        Construye contexto cognitivo completo.
        Intenta importar construir_contexto desde respuestas_articuladas
        con paths absoluto y relativo para robustez.
        Incluye goal_hint de PASO 7 si hay objetivo activo.
        """
        try:
            try:
                from respuestas_articuladas import construir_contexto
            except ImportError:
                from cognia.respuestas_articuladas import construir_contexto
            context = construir_contexto(ai, question)
        except Exception:
            context = ""

        # ── PASO 7: anteponer objetivo activo al contexto ──────────────
        if hasattr(ai, '_goal_engine') and ai._goal_engine:
            try:
                goal_hint = ai._goal_engine.active_goal_hint()
                if goal_hint:
                    context = goal_hint + "\n\n" + context
            except Exception:
                pass

        return context
'@

# =============================================================================
# EJECUTAR
# =============================================================================

Write-Host ""
Write-Host "============================================================"
Write-Host "  GoalAndPatternEngine - Aplicando PASO 7 + PASO 8"
Write-Host "============================================================"
Write-Host ""

Write-Host "Creando backups..."
Backup-File $CogniaFile
Backup-File $LangFile
Write-Host ""

Write-Host "Modificando cognia.py..."
Apply-Patch -FilePath $CogniaFile -OldText $p1_old -NewText $p1_new -Desc "init - importar GoalAndPatternEngine"
Apply-Patch -FilePath $CogniaFile -OldText $p2_old -NewText $p2_new -Desc "observe - pre_observe al inicio"
Apply-Patch -FilePath $CogniaFile -OldText $p3_old -NewText $p3_new -Desc "observe - post_observe y tick al final"
Apply-Patch -FilePath $CogniaFile -OldText $p4_old -NewText $p4_new -Desc "sleep - run_pattern_batch"
Apply-Patch -FilePath $CogniaFile -OldText $p5_old -NewText $p5_new -Desc "sleep - pattern_info en el return"
Write-Host ""

Write-Host "Modificando language_engine.py..."
Apply-Patch -FilePath $LangFile -OldText $p6_old -NewText $p6_new -Desc "build_context - inyectar goal_hint"
Write-Host ""

Write-Host "============================================================"
Write-Host "  Proceso completado."
Write-Host ""
Write-Host "  Recuerda copiar goal_and_pattern_engine.py a:"
Write-Host "  $ProjectRoot"
Write-Host "============================================================"
Write-Host ""
