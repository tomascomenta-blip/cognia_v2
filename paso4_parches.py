"""
paso4_parches.py — Cognia PASO 4: Síntesis Simbólica
=====================================================
Aplica estos dos parches sobre los archivos existentes.
Cada sección muestra EXACTAMENTE qué buscar y qué reemplazar.

NO toques nada más. El resto del pipeline queda intacto.

ARCHIVOS A MODIFICAR:
  1. symbolic_responder.py  — integrar SymbolicSynthesizer en respond()
  2. language_engine.py     — usar síntesis en Stage 2 antes del gate

ARCHIVO NUEVO A AGREGAR:
  • symbolic_synthesizer.py (ya generado) → copiarlo junto a los demás .py
"""

# ══════════════════════════════════════════════════════════════════════
# ARCHIVO 1: symbolic_responder.py
# ══════════════════════════════════════════════════════════════════════

# ── PARCHE SR-1 ───────────────────────────────────────────────────────
# Ubicación: bloque de imports al inicio del archivo,
#            justo después de:  from logger_config import get_logger as _get_sr_logger
# Añadir estas líneas:

PATCH_SR1_DESCRIPCION = "Añadir import de SymbolicSynthesizer al inicio del archivo"

PATCH_SR1_DESPUES_DE = "from logger_config import get_logger as _get_sr_logger"

PATCH_SR1_AGREGAR = """
# ── PASO 4: Sintetizador multi-fuente ────────────────────────────────
try:
    from cognia.symbolic_synthesizer import get_synthesizer
    HAS_SYNTHESIZER = True
except ImportError:
    try:
        from symbolic_synthesizer import get_synthesizer
        HAS_SYNTHESIZER = True
    except ImportError:
        HAS_SYNTHESIZER = False
"""


# ── PARCHE SR-2 ───────────────────────────────────────────────────────
# Ubicación: método respond() de SymbolicResponder,
#            REEMPLAZAR desde el comentario "── 1. Identificar concepto"
#            hasta el return SymbolicResponse al final del método.
#
# ANTES (líneas ~263-325):

PATCH_SR2_ANTES = '''
        # ── 1. Identificar concepto principal ────────────────────────
        concepto = self._extract_main_concept(ai, question)
        if not concepto:
            return SymbolicResponse(
                text=self.templates.render_ignorante("este tema"),
                confidence=0.10,
                question_type=q_type,
            )

        # ── 2. Recopilar conocimiento ─────────────────────────────────
        descripcion  = self._get_description(ai, concepto)
        hechos_kg    = self._get_kg_facts(ai, concepto)
        inferencias  = self._get_inferences(ai, concepto)
        episodios    = self._get_similar_episodes(ai, question)
        activaciones = self._get_activations(ai, concepto)

        if hechos_kg:    sources.append("knowledge_graph")
        if inferencias:  sources.append("inference_engine")
        if episodios:    sources.append("episodic_memory")
        if activaciones: sources.append("semantic_memory")

        # ── 3. Calcular confianza de respuesta ────────────────────────
        # PASO 4: pasar question para calculo de penalizacion de relevancia
        conf = self._estimate_confidence(ai, concepto, descripcion,
                                         hechos_kg, inferencias, episodios,
                                         question=question)

        # ── 4. Renderizar según tipo de pregunta ──────────────────────
        if conf < 0.15 or (not descripcion and not hechos_kg and not episodios):
            text = self.templates.render_ignorante(concepto)
            conf = 0.12
        elif q_type == "lista":
            items = self._collect_list_items(hechos_kg, activaciones, inferencias)
            text = self.templates.render_lista(concepto, items)
        elif q_type == "comparacion":
            concepto_b = self._extract_second_concept(question, concepto)
            hechos_b   = self._get_kg_facts(ai, concepto_b) if concepto_b else []
            text = self.templates.render_comparacion(
                concepto, concepto_b or "el otro concepto", hechos_kg, hechos_b
            )
        else:
            # Definición, como_funciona, general, corta, estado...
            # Añadir episodios como contexto narrativo
            ep_text = self.templates.render_episodios(episodios)
            hechos_combinados = hechos_kg.copy()
            if ep_text:
                hechos_combinados.insert(0, ep_text)

            text = self.templates.render_definicion(
                concepto=concepto,
                descripcion=descripcion or f"un concepto en mi memoria con confianza {conf:.0%}",
                hechos=hechos_combinados,
                inferencias=inferencias,
                confianza=conf,
            )

        return SymbolicResponse(
            text=text,
            confidence=conf,
            used_llm=False,
            sources=sources,
            question_type=q_type,
        )
'''

# DESPUÉS (reemplazar todo lo anterior con esto):

PATCH_SR2_DESPUES = '''
        # ── PASO 4: Intentar síntesis multi-fuente primero ───────────
        # La síntesis ancla la respuesta al vector de la pregunta,
        # produciendo mayor relevancia semántica que el lookup por concepto.
        # Si produce texto suficiente, se usa directamente.
        # Si no, se cae al pipeline de lookup original (compatibilidad).
        if HAS_SYNTHESIZER:
            try:
                _synth = get_synthesizer()
                _vec_q = None
                try:
                    from cognia.vectors import text_to_vector as _ttv
                    _vec_q = _ttv(question)
                except ImportError:
                    try:
                        from vectors import text_to_vector as _ttv
                        _vec_q = _ttv(question)
                    except Exception:
                        pass

                _sr   = _synth.synthesize(ai, question, _vec_q)

                _sr_logger.info(
                    f"synthesis used={not _sr.fallback} "
                    f"episodes={_sr.episodes_used} facts={_sr.facts_used} "
                    f"inferences={_sr.inferences_used} "
                    f"confidence={_sr.confidence:.3f} "
                    f"concepts={_sr.concepts_used[:3]} "
                    f"synthesis_ms={_sr.synthesis_ms:.1f}",
                    extra={
                        "op":      "symbolic_responder.respond",
                        "context": f"q_type={q_type} synthesizer=paso4",
                    },
                )

                # Usar síntesis si tiene texto suficiente y confianza mínima
                if not _sr.fallback and _sr.confidence >= 0.12:
                    return SymbolicResponse(
                        text          = _sr.text,
                        confidence    = _sr.confidence,
                        used_llm      = False,
                        sources       = _sr.sources_used,
                        question_type = q_type,
                    )
            except Exception as _synth_exc:
                _sr_logger.warning(
                    "Síntesis multi-fuente falló, usando lookup original",
                    extra={
                        "op":      "symbolic_responder.respond",
                        "context": str(_synth_exc),
                    },
                )

        # ── Fallback: pipeline de lookup original ─────────────────────
        # Se ejecuta si HAS_SYNTHESIZER=False o si la síntesis no produjo
        # resultado suficiente. Compatibilidad total con pasos anteriores.

        # ── 1. Identificar concepto principal ────────────────────────
        concepto = self._extract_main_concept(ai, question)
        if not concepto:
            return SymbolicResponse(
                text=self.templates.render_ignorante("este tema"),
                confidence=0.10,
                question_type=q_type,
            )

        # ── 2. Recopilar conocimiento ─────────────────────────────────
        descripcion  = self._get_description(ai, concepto)
        hechos_kg    = self._get_kg_facts(ai, concepto)
        inferencias  = self._get_inferences(ai, concepto)
        episodios    = self._get_similar_episodes(ai, question)
        activaciones = self._get_activations(ai, concepto)

        if hechos_kg:    sources.append("knowledge_graph")
        if inferencias:  sources.append("inference_engine")
        if episodios:    sources.append("episodic_memory")
        if activaciones: sources.append("semantic_memory")

        # ── 3. Calcular confianza de respuesta ────────────────────────
        conf = self._estimate_confidence(ai, concepto, descripcion,
                                         hechos_kg, inferencias, episodios,
                                         question=question)

        # ── 4. Renderizar según tipo de pregunta ──────────────────────
        if conf < 0.15 or (not descripcion and not hechos_kg and not episodios):
            text = self.templates.render_ignorante(concepto)
            conf = 0.12
        elif q_type == "lista":
            items = self._collect_list_items(hechos_kg, activaciones, inferencias)
            text = self.templates.render_lista(concepto, items)
        elif q_type == "comparacion":
            concepto_b = self._extract_second_concept(question, concepto)
            hechos_b   = self._get_kg_facts(ai, concepto_b) if concepto_b else []
            text = self.templates.render_comparacion(
                concepto, concepto_b or "el otro concepto", hechos_kg, hechos_b
            )
        else:
            ep_text = self.templates.render_episodios(episodios)
            hechos_combinados = hechos_kg.copy()
            if ep_text:
                hechos_combinados.insert(0, ep_text)
            text = self.templates.render_definicion(
                concepto=concepto,
                descripcion=descripcion or f"un concepto en mi memoria con confianza {conf:.0%}",
                hechos=hechos_combinados,
                inferencias=inferencias,
                confianza=conf,
            )

        return SymbolicResponse(
            text=text,
            confidence=conf,
            used_llm=False,
            sources=sources,
            question_type=q_type,
        )
'''


# ══════════════════════════════════════════════════════════════════════
# ARCHIVO 2: language_engine.py
# ══════════════════════════════════════════════════════════════════════

# ── PARCHE LE-1 ───────────────────────────────────────────────────────
# Ubicación: Stage 2, después de que el gate decide LLM por low_relevance,
#            intentar la síntesis como segunda oportunidad antes de llamar
#            al LLM.
#
# ANTES (líneas ~293-294):

PATCH_LE1_ANTES = '''        # Zona media o baja - LLM necesario
        # ══════════════════════════════════════════════════════════════
        # STAGES 3 & 4: LLM (HÍBRIDO O COMPLETO)
        # ══════════════════════════════════════════════════════════════

        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM'''

# DESPUÉS: añadir bloque de segunda oportunidad simbólica entre esas dos secciones

PATCH_LE1_DESPUES = '''        # Zona media o baja - LLM necesario
        # ══════════════════════════════════════════════════════════════
        # STAGE 2B: SEGUNDA OPORTUNIDAD SIMBÓLICA (PASO 4)
        # ══════════════════════════════════════════════════════════════
        # Si el gate rechazó por low_relevance (no por low_confidence),
        # intentar la síntesis multi-fuente que ancla al vector de la pregunta.
        # La síntesis tiene mayor probabilidad de pasar el umbral de relevancia.
        if gate_decision.reason in ("low_relevance", "medium_confidence_low_relevance"):
            try:
                from cognia.symbolic_synthesizer import get_synthesizer as _get_synth
            except ImportError:
                try:
                    from symbolic_synthesizer import get_synthesizer as _get_synth
                except ImportError:
                    _get_synth = None

            if _get_synth is not None:
                try:
                    _synth2  = _get_synth()
                    _sr2     = _synth2.synthesize(ai, question, vec)

                    if not _sr2.fallback and _sr2.confidence >= 0.12:
                        # Re-evaluar con el gate usando la respuesta sintetizada
                        from symbolic_responder import SymbolicResponse as _SR
                        _sym2 = _SR(
                            text          = _sr2.text,
                            confidence    = _sr2.confidence,
                            used_llm      = False,
                            sources       = _sr2.sources_used,
                            question_type = sym_response.question_type,
                        )
                        _gate2 = self.gate.evaluate(
                            sym_response    = _sym2,
                            question        = question,
                            question_vec    = vec,
                            cognia_instance = ai,
                        )
                        _le_logger.info(
                            f"stage=synthesis_retry "
                            f"confidence={_sr2.confidence:.3f} "
                            f"decision={_gate2.action.value} "
                            f"reason={_gate2.reason} "
                            f"relevance={_gate2.relevance_score:.3f} "
                            f"episodes={_sr2.episodes_used} facts={_sr2.facts_used}",
                            extra={
                                "op":      "language_engine.stage2b",
                                "context": f"original_reason={gate_decision.reason}",
                            },
                        )

                        if _gate2.action == GateAction.SYMBOLIC:
                            self._stats["symbolic_only"] += 1
                            latency = (time.perf_counter() - t0) * 1000
                            if vec:
                                self.cache.store(
                                    question   = question,
                                    response   = _sr2.text,
                                    vector     = vec,
                                    concept    = self._get_top_concept(ai, question),
                                    confidence = _sr2.confidence,
                                    used_llm   = False,
                                )
                            self._record_metrics("symbolic", question,
                                                 sym_response.question_type,
                                                 0, latency, False)
                            return EngineResult(
                                response         = _sr2.text,
                                stage_used       = "symbolic_synthesized",
                                latency_ms       = latency,
                                tokens_sent      = 0,
                                confidence       = _sr2.confidence,
                                cache_hit        = False,
                                used_llm         = False,
                                symbolic_sources = _sr2.sources_used,
                                question_type    = sym_response.question_type,
                                tipo_pregunta    = sym_response.question_type,
                                tiene_contexto   = True,
                                info_suficiente  = True,
                            )

                        # Si el gate decide HYBRID con la síntesis,
                        # usar el texto sintetizado como base híbrida
                        if _gate2.action == GateAction.HYBRID:
                            sym_response = _sym2   # sustituir base para stage 3
                            gate_decision = _gate2  # actualizar decisión
                except Exception as _se:
                    _le_logger.warning(
                        "Stage 2B synthesis_retry falló",
                        extra={"op": "language_engine.stage2b", "context": str(_se)},
                    )

        # ══════════════════════════════════════════════════════════════
        # STAGES 3 & 4: LLM (HÍBRIDO O COMPLETO)
        # ══════════════════════════════════════════════════════════════

        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM'''


# ══════════════════════════════════════════════════════════════════════
# INSTRUCCIONES DE APLICACIÓN
# ══════════════════════════════════════════════════════════════════════

INSTRUCCIONES = """
PASO 4 — GUÍA DE APLICACIÓN MANUAL
====================================

PASO 0: Copiar symbolic_synthesizer.py
  → Colocar junto a symbolic_responder.py y language_engine.py

PASO 1: symbolic_responder.py — PARCHE SR-1 (import)
  Buscar la línea:
    from logger_config import get_logger as _get_sr_logger
  Añadir DESPUÉS:
    (ver PATCH_SR1_AGREGAR arriba)

PASO 2: symbolic_responder.py — PARCHE SR-2 (método respond)
  Buscar el bloque que empieza con:
    # ── 1. Identificar concepto principal
  y termina con el último:
    return SymbolicResponse(...)
  del método respond().
  Reemplazarlo con PATCH_SR2_DESPUES.

PASO 3: language_engine.py — PARCHE LE-1 (Stage 2B)
  Buscar el comentario:
    # Zona media o baja - LLM necesario
  Reemplazar el bloque completo (hasta "Stage 0 (lazy)") con PATCH_LE1_DESPUES.

VERIFICACIÓN esperada en logs:
  • stage=synthesis_retry decision=symbolic → síntesis rescató la respuesta
  • stage=symbolic_synthesized             → etapa usada en EngineResult
  • synthesis used=True episodes=N facts=N → la síntesis tuvo datos

DIAGNÓSTICO si sigue yendo al LLM:
  • episodes=0 → la memoria episódica está vacía para ese tema → normal
  • fallback=True → la síntesis no tuvo suficientes datos → correcto
  • decision=llm reason=low_confidence → confianza base baja, síntesis no ayuda → correcto
"""

if __name__ == "__main__":
    print(INSTRUCCIONES)
"""

# ══════════════════════════════════════════════════════════════════════
# AUTOMATIZADOR PowerShell
# ══════════════════════════════════════════════════════════════════════
# Si prefieres script automático, usa aplicar_paso4.ps1 (abajo).
# Requiere que los .py estén en el mismo directorio.

POWERSHELL_SCRIPT = r"""
# aplicar_paso4.ps1
# ==================
# Aplica PASO 4 automáticamente sobre symbolic_responder.py y language_engine.py

$ErrorActionPreference = "Stop"
Write-Host "======================================================"
Write-Host "  COGNIA PASO 4 - Síntesis Simbólica Multi-Fuente"
Write-Host "======================================================"

$srFile = "symbolic_responder.py"
$leFile = "language_engine.py"

if (-not (Test-Path $srFile)) { Write-Error "No encuentro $srFile"; exit 1 }
if (-not (Test-Path $leFile)) { Write-Error "No encuentro $leFile"; exit 1 }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item $srFile "$srFile.bak_$ts"
Copy-Item $leFile "$leFile.bak_$ts"
Write-Host "OK - Backups creados (.$ts)"

# ── PARCHE SR-1: import synthesizer ────────────────────────────────
$srContent = Get-Content $srFile -Raw -Encoding UTF8

$srImportOld = "from logger_config import get_logger as _get_sr_logger"
$srImportNew = @"
from logger_config import get_logger as _get_sr_logger

# ── PASO 4: Sintetizador multi-fuente ────────────────────────────────
try:
    from cognia.symbolic_synthesizer import get_synthesizer
    HAS_SYNTHESIZER = True
except ImportError:
    try:
        from symbolic_synthesizer import get_synthesizer
        HAS_SYNTHESIZER = True
    except ImportError:
        HAS_SYNTHESIZER = False
"@

if ($srContent.Contains($srImportOld)) {
    $srContent = $srContent.Replace($srImportOld, $srImportNew)
    Write-Host "  [OK] SR-1: import synthesizer"
} else {
    Write-Host "  [WARN] SR-1: línea de import no encontrada (¿ya aplicado?)"
}

# ── PARCHE SR-2: respond() con síntesis ────────────────────────────
# Detectar el bloque que empieza en "# ── 1. Identificar concepto"
# y termina en el último return SymbolicResponse del método respond()

$sr2Old = @"
        # ── 1. Identificar concepto principal ────────────────────────
        concepto = self._extract_main_concept(ai, question)
        if not concepto:
            return SymbolicResponse(
                text=self.templates.render_ignorante("este tema"),
                confidence=0.10,
                question_type=q_type,
            )

        # ── 2. Recopilar conocimiento ─────────────────────────────────
        descripcion  = self._get_description(ai, concepto)
        hechos_kg    = self._get_kg_facts(ai, concepto)
        inferencias  = self._get_inferences(ai, concepto)
        episodios    = self._get_similar_episodes(ai, question)
        activaciones = self._get_activations(ai, concepto)

        if hechos_kg:    sources.append("knowledge_graph")
        if inferencias:  sources.append("inference_engine")
        if episodios:    sources.append("episodic_memory")
        if activaciones: sources.append("semantic_memory")

        # ── 3. Calcular confianza de respuesta ────────────────────────
        # PASO 4: pasar question para calculo de penalizacion de relevancia
        conf = self._estimate_confidence(ai, concepto, descripcion,
                                         hechos_kg, inferencias, episodios,
                                         question=question)

        # ── 4. Renderizar según tipo de pregunta ──────────────────────
        if conf < 0.15 or (not descripcion and not hechos_kg and not episodios):
            text = self.templates.render_ignorante(concepto)
            conf = 0.12
        elif q_type == "lista":
            items = self._collect_list_items(hechos_kg, activaciones, inferencias)
            text = self.templates.render_lista(concepto, items)
        elif q_type == "comparacion":
            concepto_b = self._extract_second_concept(question, concepto)
            hechos_b   = self._get_kg_facts(ai, concepto_b) if concepto_b else []
            text = self.templates.render_comparacion(
                concepto, concepto_b or "el otro concepto", hechos_kg, hechos_b
            )
        else:
            # Definición, como_funciona, general, corta, estado...
            # Añadir episodios como contexto narrativo
            ep_text = self.templates.render_episodios(episodios)
            hechos_combinados = hechos_kg.copy()
            if ep_text:
                hechos_combinados.insert(0, ep_text)

            text = self.templates.render_definicion(
                concepto=concepto,
                descripcion=descripcion or f"un concepto en mi memoria con confianza {conf:.0%}",
                hechos=hechos_combinados,
                inferencias=inferencias,
                confianza=conf,
            )

        return SymbolicResponse(
            text=text,
            confidence=conf,
            used_llm=False,
            sources=sources,
            question_type=q_type,
        )
"@

Write-Host "  Verificando SR-2 ..."
if ($srContent.Contains("# ── 1. Identificar concepto principal")) {
    Write-Host "  [OK] SR-2: bloque encontrado, aplicando parche"
    # El reemplazo completo se hace via el script Python helper
    Write-Host "  [INFO] SR-2: ejecuta apply_patches.py para este parche"
} else {
    Write-Host "  [WARN] SR-2: bloque no encontrado (¿ya aplicado?)"
}

Set-Content $srFile $srContent -Encoding UTF8
Write-Host "OK - $srFile guardado"

Write-Host ""
Write-Host "PASO 4 completado parcialmente."
Write-Host "Para SR-2 y LE-1 ejecuta: python apply_paso4_patches.py"
Write-Host "Verifica en logs: stage=synthesis_retry o stage=symbolic_synthesized"
"""
