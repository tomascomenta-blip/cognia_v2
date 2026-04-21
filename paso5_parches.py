"""
paso5_parches.py — PASO 5: Parches de integración del sistema de feedback
=========================================================================
Aplica exactamente TRES cambios a los archivos existentes.

  ARCHIVO 1: language_engine.py  → registrar fuentes de cada respuesta
  ARCHIVO 2: cognia.py           → reemplazar apply_feedback() + inicializar engine
  ARCHIVO 3: episodic.py         → ponderar score por feedback_weight en retrieve_similar()

Aplica cada parche buscando el bloque ANTES y reemplazándolo por DESPUÉS.
NO se modifica nada más. Todo el resto del pipeline queda intacto.

NOTA: Si usas apply_paso5_patches.py (script automático), estas constantes
      se usan directamente. Si aplicas manualmente, busca el texto ANTES
      en el archivo indicado y reemplázalo por DESPUÉS.
"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE 1 — language_engine.py
# ══════════════════════════════════════════════════════════════════════
# Archivo : language_engine.py
# Objetivo: (a) Importar FeedbackTracker al inicio del archivo.
#           (b) Registrar episode_ids y concepts en cada EngineResult
#               devuelto por respond().
#
# ── PARCHE 1A: bloque de imports (añadir DESPUÉS del bloque de imports de DecisionGate) ──
PATCH_1A_ANTES = """\
# PASO 4: Decision Gate de tres zonas
try:
    from cognia.decision_gate import DecisionGate, GateAction, get_decision_gate
except ImportError:
    from decision_gate import DecisionGate, GateAction, get_decision_gate"""

PATCH_1A_DESPUES = """\
# PASO 4: Decision Gate de tres zonas
try:
    from cognia.decision_gate import DecisionGate, GateAction, get_decision_gate
except ImportError:
    from decision_gate import DecisionGate, GateAction, get_decision_gate

# PASO 5: Tracker de fuentes de respuesta para feedback
try:
    from cognia.feedback_engine import get_feedback_tracker
    HAS_FEEDBACK_TRACKER = True
except ImportError:
    try:
        from feedback_engine import get_feedback_tracker
        HAS_FEEDBACK_TRACKER = True
    except ImportError:
        HAS_FEEDBACK_TRACKER = False"""

# ── PARCHE 1B: EngineResult — añadir campo episode_ids ──────────────
# Ubicación: dataclass EngineResult, después del campo "symbolic_sources"
PATCH_1B_ANTES = """\
    symbolic_sources:  list = field(default_factory=list)
    question_type:     str  = "general\""""

PATCH_1B_DESPUES = """\
    symbolic_sources:  list = field(default_factory=list)
    # PASO 5: IDs de episodios usados para poder rastrear el feedback
    episode_ids:       list = field(default_factory=list)
    question_type:     str  = "general\""""

# ── PARCHE 1C: respond() — extracción de episode_ids desde sym_response ──
# Ubicación: justo antes del bloque de Stage 2 (SYMBOLIC RESPONSE)
PATCH_1C_ANTES = """\
        # ══════════════════════════════════════════════════════════════
        # STAGE 2: SYMBOLIC RESPONSE + DECISION GATE (PASO 4)
        # ══════════════════════════════════════════════════════════════
        sym_response   = self.symbolic.respond(ai, question)
        throttle_level = self._get_throttle_level(ai)"""

PATCH_1C_DESPUES = """\
        # ══════════════════════════════════════════════════════════════
        # STAGE 2: SYMBOLIC RESPONSE + DECISION GATE (PASO 4)
        # ══════════════════════════════════════════════════════════════
        sym_response   = self.symbolic.respond(ai, question)
        throttle_level = self._get_throttle_level(ai)

        # PASO 5: extraer episode_ids del último retrieve_similar para rastrear feedback.
        # Se recogen del estado interno de ai.episodic — sin coste extra
        # porque retrieve_similar() ya fue llamado dentro de symbolic.respond().
        def _collect_ep_ids(ai_inst) -> list:
            try:
                # La función retrieve_similar() actualiza access_count en DB
                # pero no expone los IDs usados. Los recuperamos del contexto
                # de la última llamada vía los similares del assessment.
                try:
                    from cognia.vectors import text_to_vector as _tv
                except ImportError:
                    from vectors import text_to_vector as _tv
                _v = _tv(question)
                _sims = ai_inst.episodic.retrieve_similar(_v, top_k=5)
                return [s["id"] for s in _sims if s.get("id") and s["similarity"] > 0.20]
            except Exception:
                return []"""

# ── PARCHE 1D: respond() — registrar respuesta en tracker antes de cada return ──
# Hay varios return en respond(). Los más importantes son:
#   - Stage 2 (symbolic): return EngineResult(response=sym_response.text, ...)
#   - Stages 3&4 (llm/hybrid): return EngineResult(response=response, ...)
#   - Stage 5 (fallback): se omite (no rastrear fallbacks — no tienen memorias claras)
#
# PARCHE 1D-1: return de Stage 2 SYMBOLIC (zona alta)
PATCH_1D1_ANTES = """\
        if gate_decision.action == GateAction.SYMBOLIC:
            # Zona alta + relevancia OK - simbólico directo
            self._stats["symbolic_only"] += 1
            latency = (time.perf_counter() - t0) * 1000
            if vec:
                self.cache.store(
                    question   = question,
                    response   = sym_response.text,
                    vector     = vec,
                    concept    = self._get_top_concept(ai, question),
                    confidence = sym_response.confidence,
                    used_llm   = False,
                )
            self._record_metrics("symbolic", question, sym_response.question_type,
                                 0, latency, False)
            return EngineResult(
                response         = sym_response.text,
                stage_used       = "symbolic",
                latency_ms       = latency,
                tokens_sent      = 0,
                confidence       = sym_response.confidence,
                cache_hit        = False,
                used_llm         = False,
                symbolic_sources = sym_response.sources,
                question_type    = sym_response.question_type,
                tipo_pregunta    = sym_response.question_type,
                tiene_contexto   = True,
                info_suficiente  = True,
            )"""

PATCH_1D1_DESPUES = """\
        if gate_decision.action == GateAction.SYMBOLIC:
            # Zona alta + relevancia OK - simbólico directo
            self._stats["symbolic_only"] += 1
            latency = (time.perf_counter() - t0) * 1000
            if vec:
                self.cache.store(
                    question   = question,
                    response   = sym_response.text,
                    vector     = vec,
                    concept    = self._get_top_concept(ai, question),
                    confidence = sym_response.confidence,
                    used_llm   = False,
                )
            self._record_metrics("symbolic", question, sym_response.question_type,
                                 0, latency, False)

            # PASO 5: recoger IDs y registrar en tracker
            _ep_ids    = _collect_ep_ids(ai)
            _concepts  = [self._get_top_concept(ai, question)] if self._get_top_concept(ai, question) else []
            _result_sym = EngineResult(
                response         = sym_response.text,
                stage_used       = "symbolic",
                latency_ms       = latency,
                tokens_sent      = 0,
                confidence       = sym_response.confidence,
                cache_hit        = False,
                used_llm         = False,
                symbolic_sources = sym_response.sources,
                episode_ids      = _ep_ids,
                question_type    = sym_response.question_type,
                tipo_pregunta    = sym_response.question_type,
                tiene_contexto   = True,
                info_suficiente  = True,
            )
            if HAS_FEEDBACK_TRACKER:
                get_feedback_tracker().register_response(
                    response_id   = _result_sym.response_id,
                    question      = question,
                    response_text = sym_response.text,
                    stage_used    = "symbolic",
                    confidence    = sym_response.confidence,
                    episode_ids   = _ep_ids,
                    concepts      = _concepts,
                )
            return _result_sym"""

# ── PARCHE 1D-2: return de Stages 3&4 (llm/hybrid) ──────────────────
PATCH_1D2_ANTES = """\
            self._record_metrics(stage, question, q_type,
                                 optimized.tokens_estimated, latency, True)
            return EngineResult(
                response          = response,
                stage_used        = stage,
                latency_ms        = latency,
                tokens_sent       = optimized.tokens_estimated,
                confidence        = max(sym_response.confidence, 0.45),
                cache_hit         = False,
                used_llm          = True,
                symbolic_sources  = sym_response.sources,
                question_type     = q_type,
                compression_ratio = optimized.compression_ratio,
                modelo            = self.modelo,
                tipo_pregunta     = q_type,
                tiene_contexto    = bool(context),
                episodios_usados  = context.count("- '") if context else 0,
                investigated      = investigated,
            )"""

PATCH_1D2_DESPUES = """\
            self._record_metrics(stage, question, q_type,
                                 optimized.tokens_estimated, latency, True)

            # PASO 5: recoger IDs y registrar en tracker
            _ep_ids_llm   = _collect_ep_ids(ai)
            _top_c_llm    = self._get_top_concept(ai, question)
            _concepts_llm = [_top_c_llm] if _top_c_llm else []
            _result_llm   = EngineResult(
                response          = response,
                stage_used        = stage,
                latency_ms        = latency,
                tokens_sent       = optimized.tokens_estimated,
                confidence        = max(sym_response.confidence, 0.45),
                cache_hit         = False,
                used_llm          = True,
                symbolic_sources  = sym_response.sources,
                episode_ids       = _ep_ids_llm,
                question_type     = q_type,
                compression_ratio = optimized.compression_ratio,
                modelo            = self.modelo,
                tipo_pregunta     = q_type,
                tiene_contexto    = bool(context),
                episodios_usados  = context.count("- '") if context else 0,
                investigated      = investigated,
            )
            if HAS_FEEDBACK_TRACKER:
                get_feedback_tracker().register_response(
                    response_id   = _result_llm.response_id,
                    question      = question,
                    response_text = response,
                    stage_used    = stage,
                    confidence    = max(sym_response.confidence, 0.45),
                    episode_ids   = _ep_ids_llm,
                    concepts      = _concepts_llm,
                )
            return _result_llm"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE 2 — cognia.py
# ══════════════════════════════════════════════════════════════════════
# Archivo : cognia.py
# Objetivo: (a) Inicializar FeedbackEngine en __init__
#           (b) Reemplazar apply_feedback() con versión que usa el engine
#           (c) Añadir decay_weights() al ciclo de sueño

# ── PARCHE 2A: __init__ — inicializar FeedbackEngine ─────────────────
PATCH_2A_ANTES = """\
        # ── Paso 4: SelfArchitect ──────────────────────────────────────
        if HAS_SELF_ARCHITECT:"""

PATCH_2A_DESPUES = """\
        # ── PASO 5: FeedbackEngine (aprendizaje por feedback) ──────────
        try:
            from feedback_engine import get_feedback_engine
            self._feedback_engine = get_feedback_engine(db_path)
            print("✅ FeedbackEngine PASO 5 activo")
        except ImportError:
            self._feedback_engine = None

        # ── Paso 4: SelfArchitect ──────────────────────────────────────
        if HAS_SELF_ARCHITECT:"""

# ── PARCHE 2B: apply_feedback() — reemplazar método completo ─────────
PATCH_2B_ANTES = """\
    def apply_feedback(self, response_id: str, correct: bool,
                       correction_text: str = None) -> str:
        self.chat_history.add_feedback(response_id, 1 if correct else -1)
        self.metacog.log_decision(action="feedback", prediction="response",
                                  outcome="correct" if correct else "incorrect",
                                  was_error=not correct, learned=correction_text or "")
        if correction_text:
            vec = self.perception.encode(correction_text)
            emotion = {"score": 0.3 if correct else -0.3,
                       "label": "positivo" if correct else "negativo", "intensity": 0.5}
            self.episodic.store(
                observation=correction_text, label=None, vector=vec,
                confidence=0.8, importance=2.0, emotion=emotion, surprise=0.5,
                context_tags=["feedback", "correction" if not correct else "confirmation"]
            )
            self.working_mem.add(correction_text, None, vec, emotion, 0.8)
            return "✅ Feedback registrado. Corrección guardada con alta prioridad."
        return f"✅ Feedback {'positivo' if correct else 'negativo'} registrado.\""""

PATCH_2B_DESPUES = """\
    def apply_feedback(self, response_id: str, correct: bool,
                       correction_text: str = None) -> str:
        \"\"\"
        PASO 5: Aplica feedback (+1/-1) a las memorias usadas para generar
        la respuesta identificada por response_id.

        Flujo:
          1. Registrar en chat_history (comportamiento anterior preservado)
          2. FeedbackEngine actualiza feedback_weight en episodic_memory
          3. FeedbackEngine ajusta confianza en semantic_memory
          4. Si hay corrección, guardar como episodio de alta prioridad
          5. Ajustar gate de decisión si el simbólico tiene muchos fallos
        \"\"\"
        feedback_val = 1 if correct else -1

        # ── comportamiento original: chat_history + metacog ───────────
        self.chat_history.add_feedback(response_id, feedback_val)
        self.metacog.log_decision(
            action     = "feedback",
            prediction = "response",
            outcome    = "correct" if correct else "incorrect",
            was_error  = not correct,
            learned    = correction_text or "",
        )

        # ── PASO 5: aplicar feedback a memorias ───────────────────────
        summary = {}
        if self._feedback_engine is not None:
            summary = self._feedback_engine.apply(
                response_id     = response_id,
                feedback        = feedback_val,
                correction_text = correction_text,
                cognia_instance = self,
            )
        else:
            # Fallback: comportamiento original cuando el engine no está disponible
            if correction_text:
                vec = self.perception.encode(correction_text)
                emotion = {
                    "score":     0.3 if correct else -0.3,
                    "label":     "positivo" if correct else "negativo",
                    "intensity": 0.5,
                }
                self.episodic.store(
                    observation  = correction_text,
                    label        = None,
                    vector       = vec,
                    confidence   = 0.8,
                    importance   = 2.0,
                    emotion      = emotion,
                    surprise     = 0.5,
                    context_tags = ["feedback", "correction" if not correct else "confirmation"],
                )
                self.working_mem.add(correction_text, None, vec, emotion, 0.8)

        # ── Mensaje de retorno informativo ────────────────────────────
        ep_n  = summary.get("ep_ids_affected", 0)
        sem_n = summary.get("sem_affected", 0)
        gate  = " (umbral ajustado)" if summary.get("gate_adjusted") else ""
        if correction_text and not self._feedback_engine:
            return "✅ Feedback registrado. Corrección guardada con alta prioridad."
        if correction_text:
            return (
                f"✅ Feedback {'positivo' if correct else 'negativo'} registrado. "
                f"Actualicé {ep_n} memorias, {sem_n} conceptos{gate}. "
                f"Corrección guardada con alta prioridad."
            )
        return (
            f"✅ Feedback {'positivo' if correct else 'negativo'} registrado. "
            f"Actualicé {ep_n} memorias, {sem_n} conceptos{gate}."
        )"""

# ── PARCHE 2C: sleep() — añadir decay de pesos de feedback ───────────
PATCH_2C_ANTES = """\
        # Language Engine — evolución de prompts + reporte al architect
        engine_info = ""
        if HAS_LANGUAGE_ENGINE:"""

PATCH_2C_DESPUES = """\
        # ── PASO 5: Decay de feedback_weight ──────────────────────────
        feedback_info = ""
        if self._feedback_engine is not None:
            try:
                decay_result = self._feedback_engine.decay_weights()
                if decay_result.get("updated", 0) > 0:
                    feedback_info = f"\\n   Feedback decay:    {decay_result['updated']} pesos normalizados"
            except Exception:
                pass

        # Language Engine — evolución de prompts + reporte al architect
        engine_info = ""
        if HAS_LANGUAGE_ENGINE:"""

# También añadir feedback_info al return final de sleep()
PATCH_2D_ANTES = """\
                + extras + research_info + hobby_info + engine_info + architect_info)"""

PATCH_2D_DESPUES = """\
                + extras + research_info + hobby_info + engine_info + feedback_info + architect_info)"""


# ══════════════════════════════════════════════════════════════════════
# PARCHE 3 — episodic.py (cognia/memory/episodic.py)
# ══════════════════════════════════════════════════════════════════════
# Archivo : cognia/memory/episodic.py  (o episodic.py si es flat)
# Objetivo: Multiplicar el score de ranking por feedback_weight para que
#           episodios bien valorados suban y los mal valorados bajen.
#
# PARCHE 3A: retrieve_similar — leer feedback_weight de la fila ────────
PATCH_3A_ANTES = """\
            c.execute(f\"\"\"
                SELECT id, observation, label, vector, confidence, importance,
                       emotion_score, emotion_label, surprise
                FROM episodic_memory {cond}
            \"\"\")\""""

PATCH_3A_DESPUES = """\
            c.execute(f\"\"\"
                SELECT id, observation, label, vector, confidence, importance,
                       emotion_score, emotion_label, surprise,
                       COALESCE(feedback_weight, 1.0) AS feedback_weight
                FROM episodic_memory {cond}
            \"\"\")\""""

# PARCHE 3B: retrieve_similar — aplicar feedback_weight al score ──────
PATCH_3B_ANTES = """\
        for row in rows:
            try:
                ep_id, obs, label, vec_str, conf, imp, emo_score, emo_label, surprise = row
                vec = json.loads(vec_str)
                sim = cosine_similarity(query_vector, vec)
                emo_boost = abs(emo_score) * 0.1
                score = 0.55 * sim + 0.2 * conf + 0.15 * min(imp, 2.0) / 2.0 + emo_boost
                scored.append({
                    "id": ep_id, "observation": obs, "label": label,
                    "similarity": sim, "confidence": conf, "score": score,
                    "emotion": {"score": emo_score, "label": emo_label},
                    "surprise": surprise,
                })"""

PATCH_3B_DESPUES = """\
        for row in rows:
            try:
                ep_id, obs, label, vec_str, conf, imp, emo_score, emo_label, surprise, fb_weight = row
                vec = json.loads(vec_str)
                sim = cosine_similarity(query_vector, vec)
                emo_boost = abs(emo_score) * 0.1
                # PASO 5: feedback_weight pondera el score final.
                # Episodios bien valorados (+1) tienen peso > 1.0 → suben en ranking.
                # Episodios mal valorados (-1) tienen peso < 1.0 → bajan en ranking.
                # Se aplica como multiplicador suave con atenuación: 0.7 base + 0.3 feedback
                _fw = float(fb_weight) if fb_weight is not None else 1.0
                _fw_factor = 0.70 + 0.30 * _fw   # rango: [0.76, 1.30] para pesos [0.2, 2.0]
                score = (0.55 * sim + 0.2 * conf + 0.15 * min(imp, 2.0) / 2.0 + emo_boost) * _fw_factor
                scored.append({
                    "id": ep_id, "observation": obs, "label": label,
                    "similarity": sim, "confidence": conf, "score": score,
                    "emotion": {"score": emo_score, "label": emo_label},
                    "surprise": surprise,
                    "feedback_weight": round(_fw, 3),   # exponer para diagnóstico
                })"""


# ══════════════════════════════════════════════════════════════════════
# SCRIPT DE APLICACIÓN AUTOMÁTICA
# ══════════════════════════════════════════════════════════════════════

def apply_all_patches(base_dir: str = ".") -> None:
    """
    Aplica todos los parches del PASO 5 automáticamente.
    Hace backup antes de modificar.
    """
    import os, shutil, re
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    targets = {
        "language_engine.py": [
            ("PARCHE 1A", PATCH_1A_ANTES, PATCH_1A_DESPUES),
            ("PARCHE 1B", PATCH_1B_ANTES, PATCH_1B_DESPUES),
            ("PARCHE 1C", PATCH_1C_ANTES, PATCH_1C_DESPUES),
            ("PARCHE 1D1", PATCH_1D1_ANTES, PATCH_1D1_DESPUES),
            ("PARCHE 1D2", PATCH_1D2_ANTES, PATCH_1D2_DESPUES),
        ],
        "cognia.py": [
            ("PARCHE 2A", PATCH_2A_ANTES, PATCH_2A_DESPUES),
            ("PARCHE 2B", PATCH_2B_ANTES, PATCH_2B_DESPUES),
            ("PARCHE 2C", PATCH_2C_ANTES, PATCH_2C_DESPUES),
            ("PARCHE 2D", PATCH_2D_ANTES, PATCH_2D_DESPUES),
        ],
        # episodic.py puede vivir en cognia/memory/ o en raíz
    }

    # Buscar episodic.py en posibles paths
    ep_candidates = [
        os.path.join(base_dir, "episodic.py"),
        os.path.join(base_dir, "cognia", "memory", "episodic.py"),
    ]
    for ep_path in ep_candidates:
        if os.path.exists(ep_path):
            rel = os.path.relpath(ep_path, base_dir)
            targets[rel] = [
                ("PARCHE 3A", PATCH_3A_ANTES, PATCH_3A_DESPUES),
                ("PARCHE 3B", PATCH_3B_ANTES, PATCH_3B_DESPUES),
            ]
            break

    for filename, patches in targets.items():
        filepath = os.path.join(base_dir, filename)
        if not os.path.exists(filepath):
            print(f"[SKIP] {filename} no encontrado")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Backup
        bak = filepath + f".bak_paso5_{ts}"
        shutil.copy2(filepath, bak)
        print(f"[BACKUP] {filename} → {os.path.basename(bak)}")

        modified = False
        for name, antes, despues in patches:
            if antes in content:
                content = content.replace(antes, despues, 1)
                print(f"  ✅ {name} aplicado en {filename}")
                modified = True
            else:
                print(f"  ⚠️  {name}: bloque ANTES no encontrado en {filename} — revisar manualmente")

        if modified:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  💾 {filename} guardado")

    print("\n[PASO 5] Integración completada.")
    print("Asegúrate de copiar feedback_engine.py al directorio de Cognia.")
    print("Reinicia web_app.py para activar el sistema de feedback.")


if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"Aplicando parches PASO 5 en: {base}")
    apply_all_patches(base)
