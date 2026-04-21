"""
apply_paso4_patches.py — Aplicador automático de parches del PASO 4
====================================================================
Ejecutar desde el directorio de Cognia:
    python apply_paso4_patches.py

Aplica los 3 parches necesarios:
  SR-1: import SymbolicSynthesizer en symbolic_responder.py
  SR-2: método respond() con síntesis multi-fuente
  LE-1: Stage 2B en language_engine.py (segunda oportunidad simbólica)

Hace backup automático antes de cada modificación.
"""

import os
import sys
import re
import shutil
from datetime import datetime

# ── Configuración ─────────────────────────────────────────────────────
SR_FILE = "symbolic_responder.py"
LE_FILE = "language_engine.py"

TS = datetime.now().strftime("%Y%m%d_%H%M%S")


def backup(filepath):
    bak = f"{filepath}.bak_{TS}"
    shutil.copy2(filepath, bak)
    return bak


def read(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def write(filepath, content):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def apply_patch(content, old, new, label):
    if old in content:
        result = content.replace(old, new, 1)
        print(f"  [OK] {label}")
        return result, True
    else:
        print(f"  [WARN] {label}: fragmento no encontrado (¿ya aplicado?)")
        return content, False


# ══════════════════════════════════════════════════════════════════════
# PARCHE SR-1: import del sintetizador
# ══════════════════════════════════════════════════════════════════════

SR1_OLD = "from logger_config import get_logger as _get_sr_logger"

SR1_NEW = """\
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
        HAS_SYNTHESIZER = False"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE SR-2: cuerpo del método respond()
# ══════════════════════════════════════════════════════════════════════

SR2_OLD = """\
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
        )"""

SR2_NEW = """\
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
        )"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE LE-1: Stage 2B en language_engine.py
# ══════════════════════════════════════════════════════════════════════

LE1_OLD = """\
        # Zona media o baja - LLM necesario
        # ══════════════════════════════════════════════════════════════
        # STAGES 3 & 4: LLM (HÍBRIDO O COMPLETO)
        # ══════════════════════════════════════════════════════════════

        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM"""

LE1_NEW = """\
        # Zona media o baja - LLM necesario
        # ══════════════════════════════════════════════════════════════
        # STAGE 2B: SEGUNDA OPORTUNIDAD SIMBÓLICA (PASO 4)
        # ══════════════════════════════════════════════════════════════
        # Si el gate rechazó por low_relevance (no por low_confidence),
        # intentar la síntesis multi-fuente que ancla al vector de la pregunta.
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
                        try:
                            from cognia.symbolic_responder import SymbolicResponse as _SR
                        except ImportError:
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

                        if _gate2.action == GateAction.HYBRID:
                            sym_response  = _sym2
                            gate_decision = _gate2
                except Exception as _se:
                    _le_logger.warning(
                        "Stage 2B synthesis_retry falló",
                        extra={"op": "language_engine.stage2b", "context": str(_se)},
                    )

        # ══════════════════════════════════════════════════════════════
        # STAGES 3 & 4: LLM (HÍBRIDO O COMPLETO)
        # ══════════════════════════════════════════════════════════════

        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM"""


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  COGNIA PASO 4 — Aplicando Síntesis Simbólica")
    print("=" * 60)

    # Verificar archivos
    for f in [SR_FILE, LE_FILE]:
        if not os.path.exists(f):
            print(f"\n[ERROR] No se encuentra: {f}")
            print("Ejecutar desde el directorio de Cognia.")
            sys.exit(1)
    print("OK - Archivos encontrados.\n")

    # Verificar que symbolic_synthesizer.py está presente
    if not os.path.exists("symbolic_synthesizer.py"):
        print("[WARN] symbolic_synthesizer.py no encontrado en este directorio.")
        print("       Cópialo antes de ejecutar este script.")
        print()

    # Backups
    bak_sr = backup(SR_FILE)
    bak_le = backup(LE_FILE)
    print(f"OK - Backups: {bak_sr} / {bak_le}\n")

    # ── symbolic_responder.py ──────────────────────────────────────
    print(f"--- Modificando {SR_FILE} ---")
    sr = read(SR_FILE)
    sr, ok1 = apply_patch(sr, SR1_OLD, SR1_NEW, "SR-1: import synthesizer")
    sr, ok2 = apply_patch(sr, SR2_OLD, SR2_NEW, "SR-2: respond() con síntesis")
    write(SR_FILE, sr)

    # ── language_engine.py ─────────────────────────────────────────
    print(f"\n--- Modificando {LE_FILE} ---")
    le = read(LE_FILE)
    le, ok3 = apply_patch(le, LE1_OLD, LE1_NEW, "LE-1: Stage 2B síntesis retry")
    write(LE_FILE, le)

    # ── Verificar sintaxis ─────────────────────────────────────────
    print("\n--- Verificando sintaxis Python ---")
    import subprocess
    for pyfile in ["symbolic_synthesizer.py", SR_FILE, LE_FILE]:
        if not os.path.exists(pyfile):
            print(f"  [SKIP] {pyfile} no encontrado")
            continue
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", pyfile],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            print(f"  [OK] {pyfile} — sintaxis correcta")
        else:
            print(f"  [ERROR] {pyfile} — error de sintaxis:")
            print(f"    {r.stderr.strip()}")

    applied = sum([ok1, ok2, ok3])
    print(f"\nPASO 4 completado. Parches aplicados: {applied}/3")
    print("\nLogs esperados después de reiniciar:")
    print("  stage=synthesis_retry decision=symbolic → síntesis rescató la respuesta")
    print("  synthesis used=True episodes=N          → síntesis tuvo datos")
    print("  stage=symbolic_synthesized              → EngineResult sin LLM")
    if applied < 3:
        print(f"\n[WARN] Solo {applied}/3 parches aplicados.")
        print("Revisa si alguno ya estaba aplicado o si el código cambió.")


if __name__ == "__main__":
    main()
