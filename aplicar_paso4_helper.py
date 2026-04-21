# aplicar_paso4_helper.py
# Script Python que aplica los 6 cambios del PASO 4.
# Lo invoca aplicar_paso4.ps1 automaticamente.

import sys
import os
import py_compile

def reemplazar(path, viejo, nuevo, nombre):
    with open(path, 'r', encoding='utf-8-sig') as f:
        contenido = f.read()
    if viejo in contenido:
        contenido = contenido.replace(viejo, nuevo, 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(contenido)
        print(f"  [OK] {nombre}")
        return True
    else:
        print(f"  [WARN] {nombre} - bloque no encontrado exactamente, revisar manualmente")
        return False

# ============================================================
print("\n--- Modificando language_engine.py ---")
# ============================================================

# LE-1: import DecisionGate
reemplazar(
    'language_engine.py',
    (
        'try:\n'
        '    from cognia.symbolic_responder import SymbolicResponder, UMBRAL_CONFIANZA, UMBRAL_FALLBACK, UMBRAL_MINIMO\n'
        'except ImportError:\n'
        '    from symbolic_responder import SymbolicResponder, UMBRAL_CONFIANZA, UMBRAL_FALLBACK, UMBRAL_MINIMO'
    ),
    (
        'try:\n'
        '    from cognia.symbolic_responder import SymbolicResponder, UMBRAL_CONFIANZA, UMBRAL_FALLBACK, UMBRAL_MINIMO\n'
        'except ImportError:\n'
        '    from symbolic_responder import SymbolicResponder, UMBRAL_CONFIANZA, UMBRAL_FALLBACK, UMBRAL_MINIMO\n'
        '\n'
        '# PASO 4: Decision Gate de tres zonas\n'
        'try:\n'
        '    from cognia.decision_gate import DecisionGate, GateAction, get_decision_gate\n'
        'except ImportError:\n'
        '    from decision_gate import DecisionGate, GateAction, get_decision_gate\n'
        '\n'
        'from logger_config import get_logger as _get_le_logger\n'
        '_le_logger = _get_le_logger(__name__)'
    ),
    'LE-1: import DecisionGate'
)

# LE-2: self.gate en __init__
reemplazar(
    'language_engine.py',
    '        print("[LanguageEngine] Motor h\u00edbrido inicializado.")',
    (
        '        # PASO 4: gate de decision de tres zonas\n'
        '        self.gate = get_decision_gate()\n'
        '        print("[LanguageEngine] Motor h\u00edbrido inicializado.")'
    ),
    'LE-2: self.gate en __init__'
)

# LE-3: Stage 2 completo
LE3_VIEJO = (
    '        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
    '        # STAGE 2: SYMBOLIC RESPONSE\n'
    '        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
    '        sym_response = self.symbolic.respond(ai, question)\n'
    '        throttle_level = self._get_throttle_level(ai)\n'
    '\n'
    '        if sym_response.confidence >= UMBRAL_CONFIANZA:\n'
    '            self._stats["symbolic_only"] += 1\n'
    '            latency = (time.perf_counter() - t0) * 1000\n'
    '            # Guardar en cach\u00e9 para pr\u00f3ximas veces\n'
    '            if vec:\n'
    '                self.cache.store(\n'
    '                    question   = question,\n'
    '                    response   = sym_response.text,\n'
    '                    vector     = vec,\n'
    '                    concept    = self._get_top_concept(ai, question),\n'
    '                    confidence = sym_response.confidence,\n'
    '                    used_llm   = False,\n'
    '                )\n'
    '            self._record_metrics("symbolic", question, sym_response.question_type,\n'
    '                                 0, latency, False)\n'
    '            return EngineResult(\n'
    '                response         = sym_response.text,\n'
    '                stage_used       = "symbolic",\n'
    '                latency_ms       = latency,\n'
    '                tokens_sent      = 0,\n'
    '                confidence       = sym_response.confidence,\n'
    '                cache_hit        = False,\n'
    '                used_llm         = False,\n'
    '                symbolic_sources = sym_response.sources,\n'
    '                question_type    = sym_response.question_type,\n'
    '                tipo_pregunta    = sym_response.question_type,\n'
    '                tiene_contexto   = True,\n'
    '                info_suficiente  = True,\n'
    '            )\n'
    '\n'
    '        # Si el nivel de carga es cr\u00edtico \u2192 forzar respuesta simb\u00f3lica\n'
    '        if throttle_level == "critical":\n'
    '            self._stats["symbolic_only"] += 1\n'
    '            latency = (time.perf_counter() - t0) * 1000\n'
    '            text = sym_response.text\n'
    '            if sym_response.confidence < UMBRAL_MINIMO:\n'
    '                text = (sym_response.text + "\\n\\n(Nota: el sistema est\u00e1 bajo alta "\n'
    '                        "carga; esta respuesta viene de mi conocimiento estructurado.)")\n'
    '            return EngineResult(\n'
    '                response       = text,\n'
    '                stage_used     = "symbolic_forced",\n'
    '                latency_ms     = latency,\n'
    '                tokens_sent    = 0,\n'
    '                confidence     = sym_response.confidence,\n'
    '                cache_hit      = False,\n'
    '                used_llm       = False,\n'
    '                question_type  = sym_response.question_type,\n'
    '                tipo_pregunta  = sym_response.question_type,\n'
    '                tiene_contexto = sym_response.confidence > 0.1,\n'
    '            )\n'
    '\n'
    '        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
    '        # STAGES 3 & 4: LLM (H\u00cdBRIDO O COMPLETO)\n'
    '        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
    '\n'
    '        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM\n'
    '        # va a ser necesario. Si pre_built_context ya existe y es suficiente,\n'
    '        # se reutiliza. Si no, se intenta investigaci\u00f3n aut\u00f3noma primero.\n'
    '        # PASO 3: construir_contexto() ya incluye el bloque conversacional.\n'
    '        context = pre_built_context or self._build_context(ai, question)\n'
    '        context, investigated = self._maybe_investigate(ai, question, context)\n'
    '\n'
    '        # \u2500\u2500 PASO 3: detectar cambio de tema para ajustar system prompt \u2500\n'
    '        try:\n'
    '            from conversation_memory import get_conversation_context\n'
    '            _conv_ctx = get_conversation_context(ai)\n'
    '            self._topic_changed_hint = _conv_ctx.topic_changed_last()\n'
    '        except Exception:\n'
    '            self._topic_changed_hint = False\n'
    '\n'
    '        # Decidir entre h\u00edbrido y LLM completo\n'
    '        is_hybrid = (UMBRAL_FALLBACK <= sym_response.confidence < UMBRAL_CONFIANZA)'
)

LE3_NUEVO = (
    '        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
    '        # STAGE 2: SYMBOLIC RESPONSE + DECISION GATE (PASO 4)\n'
    '        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
    '        sym_response   = self.symbolic.respond(ai, question)\n'
    '        throttle_level = self._get_throttle_level(ai)\n'
    '\n'
    '        # Forzar simb\u00f3lico si el sistema est\u00e1 bajo carga cr\u00edtica\n'
    '        if throttle_level == "critical":\n'
    '            self._stats["symbolic_only"] += 1\n'
    '            latency = (time.perf_counter() - t0) * 1000\n'
    '            text = sym_response.text\n'
    '            if sym_response.confidence < 0.30:\n'
    '                text = (sym_response.text + "\\n\\n(Nota: el sistema est\u00e1 bajo alta "\n'
    '                        "carga; esta respuesta viene de mi conocimiento estructurado.)")\n'
    '            _le_logger.info(\n'
    '                "stage=decision confidence={:.3f} decision=symbolic_forced "\n'
    '                "reason=critical_throttle".format(sym_response.confidence),\n'
    '                extra={"op": "language_engine.stage2", "context": "throttle=critical"},\n'
    '            )\n'
    '            return EngineResult(\n'
    '                response       = text,\n'
    '                stage_used     = "symbolic_forced",\n'
    '                latency_ms     = latency,\n'
    '                tokens_sent    = 0,\n'
    '                confidence     = sym_response.confidence,\n'
    '                cache_hit      = False,\n'
    '                used_llm       = False,\n'
    '                question_type  = sym_response.question_type,\n'
    '                tipo_pregunta  = sym_response.question_type,\n'
    '                tiene_contexto = sym_response.confidence > 0.10,\n'
    '            )\n'
    '\n'
    '        # PASO 4: Decision Gate de tres zonas\n'
    '        # vec ya fue calculado en Stage 1 (cache check) - reutilizar\n'
    '        gate_decision = self.gate.evaluate(\n'
    '            sym_response    = sym_response,\n'
    '            question        = question,\n'
    '            question_vec    = vec,\n'
    '            cognia_instance = ai,\n'
    '        )\n'
    '\n'
    '        if gate_decision.action == GateAction.SYMBOLIC:\n'
    '            # Zona alta + relevancia OK - simb\u00f3lico directo\n'
    '            self._stats["symbolic_only"] += 1\n'
    '            latency = (time.perf_counter() - t0) * 1000\n'
    '            if vec:\n'
    '                self.cache.store(\n'
    '                    question   = question,\n'
    '                    response   = sym_response.text,\n'
    '                    vector     = vec,\n'
    '                    concept    = self._get_top_concept(ai, question),\n'
    '                    confidence = sym_response.confidence,\n'
    '                    used_llm   = False,\n'
    '                )\n'
    '            self._record_metrics("symbolic", question, sym_response.question_type,\n'
    '                                 0, latency, False)\n'
    '            return EngineResult(\n'
    '                response         = sym_response.text,\n'
    '                stage_used       = "symbolic",\n'
    '                latency_ms       = latency,\n'
    '                tokens_sent      = 0,\n'
    '                confidence       = sym_response.confidence,\n'
    '                cache_hit        = False,\n'
    '                used_llm         = False,\n'
    '                symbolic_sources = sym_response.sources,\n'
    '                question_type    = sym_response.question_type,\n'
    '                tipo_pregunta    = sym_response.question_type,\n'
    '                tiene_contexto   = True,\n'
    '                info_suficiente  = True,\n'
    '            )\n'
    '\n'
    '        # Zona media o baja - LLM necesario\n'
    '        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
    '        # STAGES 3 & 4: LLM (H\u00cdBRIDO O COMPLETO)\n'
    '        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n'
    '\n'
    '        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM\n'
    '        # va a ser necesario. Si pre_built_context ya existe y es suficiente,\n'
    '        # se reutiliza. Si no, se intenta investigaci\u00f3n aut\u00f3noma primero.\n'
    '        # PASO 3: construir_contexto() ya incluye el bloque conversacional.\n'
    '        context = pre_built_context or self._build_context(ai, question)\n'
    '        context, investigated = self._maybe_investigate(ai, question, context)\n'
    '\n'
    '        # PASO 3: detectar cambio de tema para ajustar system prompt\n'
    '        try:\n'
    '            from conversation_memory import get_conversation_context\n'
    '            _conv_ctx = get_conversation_context(ai)\n'
    '            self._topic_changed_hint = _conv_ctx.topic_changed_last()\n'
    '        except Exception:\n'
    '            self._topic_changed_hint = False\n'
    '\n'
    '        # Usar gate para determinar h\u00edbrido vs LLM completo\n'
    '        is_hybrid = (gate_decision.action == GateAction.HYBRID)'
)

reemplazar('language_engine.py', LE3_VIEJO, LE3_NUEVO, 'LE-3: Stage 2 con Decision Gate')

# ============================================================
print("\n--- Modificando symbolic_responder.py ---")
# ============================================================

# SR-1: import logger
reemplazar(
    'symbolic_responder.py',
    'from typing import Optional, List, Dict, Any',
    (
        'from typing import Optional, List, Dict, Any\n'
        '\n'
        'from logger_config import get_logger as _get_sr_logger\n'
        '_sr_logger = _get_sr_logger(__name__)'
    ),
    'SR-1: import logger'
)

# SR-2: _estimate_confidence nueva
SR2_VIEJO = (
    '    def _estimate_confidence(self, ai, concepto: str, descripcion: str,\n'
    '                              hechos: List, inferencias: List,\n'
    '                              episodios: List) -> float:\n'
    '        """\n'
    '        Calcula la confianza de la respuesta simb\u00f3lica.\n'
    '        Pondera: confianza sem\u00e1ntica + hechos KG + episodios + inferencias.\n'
    '        """\n'
    '        try:\n'
    '            import sqlite3\n'
    '            conn = sqlite3.connect(ai.db)\n'
    '            conn.text_factory = str\n'
    '            row = conn.execute(\n'
    '                "SELECT confidence, support FROM semantic_memory WHERE concept=?",\n'
    '                (concepto,)\n'
    '            ).fetchone()\n'
    '            conn.close()\n'
    '            sem_conf    = row[0] if row else 0.0\n'
    '            sem_support = row[1] if row else 0\n'
    '        except Exception:\n'
    '            sem_conf, sem_support = 0.0, 0\n'
    '\n'
    '        score_sem  = sem_conf * 0.40\n'
    '        score_kg   = min(1.0, len(hechos) / 5.0) * 0.25\n'
    '        score_ep   = min(1.0, len(episodios) / 4.0) * 0.20\n'
    '        score_inf  = min(1.0, len(inferencias) / 3.0) * 0.10\n'
    '        score_desc = (0.05 if descripcion else 0.0)\n'
    '\n'
    '        total = score_sem + score_kg + score_ep + score_inf + score_desc\n'
    '        return round(min(1.0, total), 3)'
)

SR2_NUEVO = (
    '    def _estimate_confidence(self, ai, concepto: str, descripcion: str,\n'
    '                              hechos: List, inferencias: List,\n'
    '                              episodios: List,\n'
    '                              question: str = "") -> float:\n'
    '        """\n'
    '        Calcula la confianza de la respuesta simb\u00f3lica.\n'
    '        PASO 4: penalizaci\u00f3n por baja similitud sem\u00e1ntica pregunta-episodios.\n'
    '        Corrige el fallo donde el simb\u00f3lico obten\u00eda confianza alta con datos\n'
    '        gen\u00e9ricos no relacionados con la pregunta espec\u00edfica del usuario.\n'
    '        Pesos: sem 0.35 / kg 0.22 / ep 0.18 / inf 0.10 / desc 0.05 / rel 0.10\n'
    '        """\n'
    '        try:\n'
    '            import sqlite3\n'
    '            conn = sqlite3.connect(ai.db)\n'
    '            conn.text_factory = str\n'
    '            row = conn.execute(\n'
    '                "SELECT confidence, support FROM semantic_memory WHERE concept=?",\n'
    '                (concepto,)\n'
    '            ).fetchone()\n'
    '            conn.close()\n'
    '            sem_conf    = float(row[0]) if row else 0.0\n'
    '            sem_support = int(row[1])   if row else 0\n'
    '        except Exception:\n'
    '            sem_conf, sem_support = 0.0, 0\n'
    '\n'
    '        score_sem   = sem_conf * 0.35\n'
    '        score_kg    = min(1.0, len(hechos)      / 5.0) * 0.22\n'
    '        score_ep    = min(1.0, len(episodios)   / 4.0) * 0.18\n'
    '        score_inf   = min(1.0, len(inferencias) / 3.0) * 0.10\n'
    '        score_desc  = 0.05 if descripcion else 0.0\n'
    '\n'
    '        # PASO 4: penalizaci\u00f3n por relevancia sem\u00e1ntica\n'
    '        # sim < 0.20 -> score_relevance = 0.0  (penalizacion maxima)\n'
    '        # sim = 0.40 -> score_relevance = 0.10 (neutro)\n'
    '        # sim > 0.60 -> score_relevance = 0.20 (bonificacion)\n'
    '        score_relevance = 0.10\n'
    '        if question and episodios:\n'
    '            try:\n'
    '                sims = [ep.get("similarity", 0.0) for ep in episodios[:4]\n'
    '                        if ep.get("similarity", 0.0) > 0.0]\n'
    '                if sims:\n'
    '                    avg_sim = sum(sims) / len(sims)\n'
    '                    if avg_sim < 0.20:\n'
    '                        score_relevance = 0.0\n'
    '                    elif avg_sim < 0.40:\n'
    '                        score_relevance = 0.10 * ((avg_sim - 0.20) / 0.20)\n'
    '                    elif avg_sim < 0.60:\n'
    '                        score_relevance = 0.10 + 0.10 * ((avg_sim - 0.40) / 0.20)\n'
    '                    else:\n'
    '                        score_relevance = 0.20\n'
    '            except Exception:\n'
    '                pass\n'
    '\n'
    '        total = score_sem + score_kg + score_ep + score_inf + score_desc + score_relevance\n'
    '        result = round(min(1.0, total), 3)\n'
    '\n'
    '        _sr_logger.debug(\n'
    '            f"confidence_calc concept={concepto} "\n'
    '            f"sem={score_sem:.3f} kg={score_kg:.3f} ep={score_ep:.3f} "\n'
    '            f"inf={score_inf:.3f} desc={score_desc:.2f} rel={score_relevance:.3f} "\n'
    '            f"total={result:.3f}",\n'
    '            extra={\n'
    '                "op":      "symbolic_responder._estimate_confidence",\n'
    '                "context": (\n'
    '                    f"concept={concepto} sem_conf={sem_conf:.2f} "\n'
    '                    f"support={sem_support} n_hechos={len(hechos)} "\n'
    '                    f"n_episodios={len(episodios)}"\n'
    '                ),\n'
    '            },\n'
    '        )\n'
    '        return result'
)

reemplazar('symbolic_responder.py', SR2_VIEJO, SR2_NUEVO, 'SR-2: _estimate_confidence con relevancia')

# SR-3: llamada con question=
reemplazar(
    'symbolic_responder.py',
    (
        '        conf = self._estimate_confidence(ai, concepto, descripcion,\n'
        '                                         hechos_kg, inferencias, episodios)'
    ),
    (
        '        # PASO 4: pasar question para calculo de penalizacion de relevancia\n'
        '        conf = self._estimate_confidence(ai, concepto, descripcion,\n'
        '                                         hechos_kg, inferencias, episodios,\n'
        '                                         question=question)'
    ),
    'SR-3: llamada _estimate_confidence con question='
)

# ============================================================
print("\n--- Verificando sintaxis Python ---")
# ============================================================
for f in ["decision_gate.py", "language_engine.py", "symbolic_responder.py"]:
    try:
        py_compile.compile(f, doraise=True)
        print(f"  [OK] {f} - sintaxis correcta")
    except py_compile.PyCompileError as e:
        print(f"  [ERROR] {f} - {e}")

print("\nPASO 4 completado.")
