"""
paso3_fragmentos_listos.py
==========================
Fragmentos completos y listos para sustituir directamente en los archivos.
Copia cada función entera y pégala reemplazando la original.
"""

# ══════════════════════════════════════════════════════════════════════
# FRAGMENTO 1
# Archivo : respuestas_articuladas.py
# Función : construir_contexto()  (líneas ~139-268)
# Acción  : REEMPLAZAR la función completa
# ══════════════════════════════════════════════════════════════════════

CONSTRUIR_CONTEXTO = '''
# ── PASO 3: import al inicio del archivo (añadir junto a los otros imports) ──
# try:
#     from conversation_memory import get_conversation_context
#     HAS_CONV_MEMORY = True
# except ImportError:
#     HAS_CONV_MEMORY = False


def construir_contexto(ai, pregunta):
    """
    Construye el contexto cognitivo completo para Ollama.
    PASO 3: inyecta bloque conversacional semántico multi-turno.
    """
    from cognia.vectors import text_to_vector

    top_k = 5
    enable_inference = True
    enable_temporal  = True
    if hasattr(ai, "fatigue") and ai.fatigue:
        adaps = ai.fatigue.get_adaptations()
        top_k = min(adaps["top_k_retrieval"], 7)
        enable_inference = adaps["inference_max_steps"] > 0
        enable_temporal  = adaps["enable_temporal"]

    vec = text_to_vector(pregunta)
    similares = ai.episodic.retrieve_similar(vec, top_k=top_k)
    assessment = ai.metacog.assess_confidence(similares)
    top_label = assessment.get("top_label")

    try:
        if hasattr(ai, "_hyp_scheduler"):
            nuevas = ai._hyp_scheduler.maybe_run(similares)
            if nuevas and hasattr(ai, "hypothesis"):
                ai.hypothesis.store_generated(top_label, nuevas)
    except Exception:
        pass

    bloques = []

    # ── PASO 3: Contexto conversacional semántico ──────────────────────
    # Sustituye el bloque working_mem.get_recent() anterior.
    # Detecta tema, filtra por similitud, respeta límite de chars.
    if HAS_CONV_MEMORY:
        try:
            _conv_ctx = get_conversation_context(ai)
            _conv_block = _conv_ctx.build_context_block(pregunta, vec)
            if _conv_block:
                bloques.append(_conv_block)
        except Exception as _e:
            from logger_config import get_logger as _gl
            _gl(__name__).warning(
                "Error construyendo contexto conversacional",
                extra={"op": "construir_contexto.conv", "context": str(_e)},
            )
    else:
        # Fallback: comportamiento original
        try:
            recientes = ai.working_mem.get_recent(n=6)
            hilo = [f"- \'{e[\'observation\'][:180]}\'"
                    for e in recientes
                    if e.get("observation") and e["observation"] != pregunta
                    and len(e.get("observation", "")) > 8]
            if hilo:
                bloques.append("CONVERSACIÓN RECIENTE:\\n" + "\\n".join(hilo[-4:]))
        except Exception:
            pass

    # ── Memorias episódicas ─────────────────────────────────────────
    eps = [
        f"- \'{e[\'observation\'][:120]}\' (etiqueta: {e[\'label\'] or \'ninguna\'}, "
        f"similitud: {e[\'similarity\']:.0%}, confianza: {e.get(\'confidence\', 0):.0%})"
        for e in similares if e["similarity"] > 0.2
    ]
    if eps:
        bloques.append("MEMORIAS EPISÓDICAS:\\n" + "\\n".join(eps))

    if top_label:
        acts = ai.semantic.spreading_activation(top_label, depth=2)
        if acts:
            concept_lines = [f"- {a[\'concept\']} (activación: {a[\'activation\']:.2f})"
                             for a in acts[:6]]
            bloques.append("CONCEPTOS RELACIONADOS:\\n" + "\\n".join(concept_lines))

        hechos = ai.kg.get_facts(top_label)
        kg_lines = [
            f"- {h[\'subject\']} --{h[\'predicate\']}--> {h[\'object\']} (peso: {h[\'weight\']:.1f})"
            for h in hechos[:10]
        ]
        jerarquia = ai.kg.get_ancestors(top_label)
        if jerarquia:
            kg_lines.append(f"- Jerarquía: {top_label} → {' → '.join(jerarquia)}")
        if kg_lines:
            bloques.append("GRAFO DE CONOCIMIENTO:\\n" + "\\n".join(kg_lines))

        if enable_inference:
            infs = ai.inference.infer(top_label, max_steps=3)
            props = ai.inference.infer_properties(top_label)
            inf_lines = [f"- {i.get(\'justification\', \'\')[:120]}" for i in infs[:4]]
            inf_lines += [
                f"- {top_label} {p[\'property\']} {p[\'value\']} (heredado de: {p[\'inherited_from\']})"
                for p in props[:3]
            ]
            if inf_lines:
                bloques.append("INFERENCIAS SIMBÓLICAS:\\n" + "\\n".join(inf_lines))

        hyp_lines = []
        try:
            hyp_result = ai.hypothesis.get_hypotheses_for(top_label)
            for h in (hyp_result or [])[:2]:
                hyp_lines.append(f"- {h.get(\'hypothesis\', \'\')[:100]} "
                                  f"(conf: {h.get(\'confidence\', 0):.0%})")
        except Exception:
            pass
        if hyp_lines:
            bloques.append("HIPÓTESIS PREVIAS:\\n" + "\\n".join(hyp_lines))

    if enable_temporal:
        preds = ai.temporal_mem.predict_from_context()
        if preds:
            pred_lines = [f"- {p[\'concept\']} (probabilidad: {p[\'probability\']:.0%})"
                          for p in preds[:3]]
            bloques.append("PREDICCIONES TEMPORALES:\\n" + "\\n".join(pred_lines))

    state = assessment.get("state", "ignorant")
    conf  = assessment.get("confidence", 0.0)
    state_labels = {
        "confident": "segura", "uncertain": "incierta",
        "confused":  "confundida", "ignorant": "sin datos"
    }
    meta_line = (f"- Estado: {state_labels.get(state, state)} "
                 f"(confianza metacognitiva: {conf:.0%})")
    if top_label:
        meta_line += f", concepto principal: \'{top_label}\'"
    bloques.append("ESTADO COGNITIVO:\\n" + meta_line)

    return "\\n\\n".join(bloques)
'''


# ══════════════════════════════════════════════════════════════════════
# FRAGMENTO 2
# Archivo : respuestas_articuladas.py
# Función : _postprocess_response()  (líneas ~411-461)
# Acción  : REEMPLAZAR solo el bloque "working_memory — hilo conversacional"
#           añadiendo el registro en ConversationContext al final
# ══════════════════════════════════════════════════════════════════════

POSTPROCESS_CONV_BLOCK = '''
    # working_memory — hilo conversacional (comportamiento original preservado)
    try:
        _vec_r = text_to_vector(engine_result.response[:200])
        if _vec_r:
            ai.working_mem.add(
                f"[Cognia]: {engine_result.response[:280]}",
                None, _vec_r,
                analyze_emotion(engine_result.response[:100]), 0.5,
            )
    except Exception:
        pass

    # ── PASO 3: Registrar turno completo en ConversationContext ────────
    # Guarda (pregunta_usuario, respuesta_cognia, vector_pregunta) en el
    # buffer circular para que el próximo turno tenga contexto relevante.
    if HAS_CONV_MEMORY:
        try:
            _conv_ctx = get_conversation_context(ai)
            # Recuperar pregunta y su vector desde working_mem
            # (_preprocess_question los añadió como último elemento)
            _pregunta_orig = ""
            _vec_preg = None
            try:
                _recientes = ai.working_mem.get_recent(n=2)
                # El penúltimo es la pregunta del usuario
                # (el último es la respuesta de Cognia que acabamos de añadir)
                for _item in reversed(_recientes):
                    _obs = _item.get("observation", "")
                    if _obs and not _obs.startswith("[Cognia]:"):
                        _pregunta_orig = _obs
                        _vec_preg = _item.get("vector")
                        break
            except Exception:
                pass

            if not _vec_preg:
                _vec_preg = text_to_vector(_pregunta_orig[:200]) if _pregunta_orig else None

            if _vec_preg:
                _conv_ctx.add_turn(
                    user_text   = _pregunta_orig or "(pregunta no recuperada)",
                    cognia_text = engine_result.response,
                    vector      = _vec_preg,
                )
        except Exception as _e:
            from logger_config import get_logger as _gl
            _gl(__name__).warning(
                "Error registrando turno en ConversationContext",
                extra={"op": "_postprocess_response.conv", "context": str(_e)},
            )
'''


# ══════════════════════════════════════════════════════════════════════
# FRAGMENTO 3
# Archivo : language_engine.py
# Función : _get_system_prompt()
# Acción  : REEMPLAZAR la función completa
# ══════════════════════════════════════════════════════════════════════

GET_SYSTEM_PROMPT = '''
    def _get_system_prompt(self, question_type: str) -> str:
        """
        Construye el system prompt para Ollama.
        PASO 3: incluye instrucción de coherencia conversacional
        y nota de cambio de tema si se detectó.
        """
        base = (
            "Eres Cognia, una IA con memoria episódica y grafo de conocimiento. "
            "Usa el contexto de memoria dado. "
            "Si hay una sección CONVERSACIÓN RECIENTE en el contexto, "
            "úsala para mantener la coherencia y continuidad de la charla: "
            "evita repetir lo que ya explicaste y conecta tu respuesta con "
            "lo dicho antes cuando sea relevante. "
            "Responde en el mismo idioma de la pregunta."
        )
        extras = {
            "lista":         " Lista máx 5 ítems, 1 oración cada uno.",
            "como_funciona": " Pasos numerados, máx 5 pasos.",
            "comparacion":   " 2-3 diferencias clave, máx 2 párrafos.",
            "definicion":    " 1-2 párrafos directos.",
        }
        # PASO 3: señal de cambio de tema → instrucción de reset al LLM
        topic_hint = ""
        if getattr(self, "_topic_changed_hint", False):
            topic_hint = (
                " IMPORTANTE: el usuario ha cambiado de tema. "
                "Responde únicamente sobre la nueva pregunta, "
                "sin mezclar información del tema anterior."
            )
        return base + extras.get(question_type, " Máx 2 párrafos breves.") + topic_hint
'''


# ══════════════════════════════════════════════════════════════════════
# FRAGMENTO 4
# Archivo : language_engine.py
# Método  : respond()  — bloque Stage 0 lazy (líneas ~254-256)
# Acción  : REEMPLAZAR solo esas 3 líneas con las siguientes
# ══════════════════════════════════════════════════════════════════════

RESPOND_STAGE0_PATCH = '''
        # Stage 0 (lazy): construir contexto cuando el LLM es necesario.
        # PASO 3: construir_contexto() ya incluye el bloque conversacional
        # semántico via ConversationContext.build_context_block().
        context = pre_built_context or self._build_context(ai, question)
        context, investigated = self._maybe_investigate(ai, question, context)

        # ── PASO 3: detectar cambio de tema para ajustar system prompt ─
        try:
            from conversation_memory import get_conversation_context
            _conv_ctx = get_conversation_context(ai)
            self._topic_changed_hint = _conv_ctx.topic_changed_last()
        except Exception:
            self._topic_changed_hint = False
'''
