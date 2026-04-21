"""
PASO 3 — PARCHES DE INTEGRACIÓN
================================
Aplica estos cambios sobre respuestas_articuladas.py y language_engine.py.
Cada sección muestra EXACTAMENTE qué líneas reemplazar.

NO toques nada más. El resto del pipeline queda intacto.
"""

# ══════════════════════════════════════════════════════════════════════
# ARCHIVO 1: respuestas_articuladas.py
# ══════════════════════════════════════════════════════════════════════

# ── PARCHE 1A ─────────────────────────────────────────────────────────
# Ubicación: bloque de imports al inicio del archivo (después de los imports de HAS_LANGUAGE_ENGINE)
# Añadir estas líneas:

PATCH_1A_ADD_AFTER_IMPORTS = """
# ── PASO 3: Memoria conversacional multi-turno ────────────────────────
try:
    from conversation_memory import get_conversation_context
    HAS_CONV_MEMORY = True
except ImportError:
    HAS_CONV_MEMORY = False
"""

# ── PARCHE 1B ─────────────────────────────────────────────────────────
# Ubicación: función construir_contexto(), líneas 174-186
#
# ANTES:
PATCH_1B_ANTES = """
    # ── HILO DE CONVERSACIÓN: últimos mensajes del chat ──────────────
    # Inyecta los últimos turnos desde working_mem para dar continuidad.
    # Zero cost: solo lee de memoria RAM, sin DB ni embeddings.
    try:
        recientes = ai.working_mem.get_recent(n=6)
        hilo = [f"- '{e['observation'][:180]}'"
                for e in recientes
                if e.get("observation") and e["observation"] != pregunta
                and len(e.get("observation", "")) > 8]
        if hilo:
            bloques.append("CONVERSACIÓN RECIENTE:\\n" + "\\n".join(hilo[-4:]))
    except Exception:
        pass
"""

# DESPUÉS:
PATCH_1B_DESPUES = """
    # ── PASO 3: Contexto conversacional semántico multi-turno ─────────
    # Sustituye el bloque working_mem.get_recent anterior.
    # Selecciona turnos por similitud + recencia + detección de tema.
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
        # Fallback: comportamiento original sin conversation_memory
        try:
            recientes = ai.working_mem.get_recent(n=6)
            hilo = [f"- '{e['observation'][:180]}'"
                    for e in recientes
                    if e.get("observation") and e["observation"] != pregunta
                    and len(e.get("observation", "")) > 8]
            if hilo:
                bloques.append("CONVERSACIÓN RECIENTE:\\n" + "\\n".join(hilo[-4:]))
        except Exception:
            pass
"""

# ── PARCHE 1C ─────────────────────────────────────────────────────────
# Ubicación: función _postprocess_response(), al final del bloque
#            "working_memory — hilo conversacional" (después de la línea con ai.working_mem.add)
#
# ANTES (líneas ~433-443):
PATCH_1C_ANTES = """
    # working_memory — hilo conversacional
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
"""

# DESPUÉS:
PATCH_1C_DESPUES = """
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

    # ── PASO 3: Registrar turno en ConversationContext ─────────────────
    # El vector de la PREGUNTA (no de la respuesta) es el que usamos para
    # búsqueda semántica futura. Lo calculamos aquí para no repetir cómputo.
    if HAS_CONV_MEMORY:
        try:
            _conv_ctx = get_conversation_context(ai)
            # Reutilizar el vector ya calculado en _preprocess_question
            # que está guardado en ai.working_mem (último elemento)
            _pregunta_original = ""
            _vec_pregunta = None
            try:
                # Extraer pregunta y vector del último item de working_mem
                # (añadido en _preprocess_question antes de esta función)
                _recientes = ai.working_mem.get_recent(n=1)
                if _recientes:
                    _pregunta_original = _recientes[-1].get("observation", "")
                    _vec_pregunta      = _recientes[-1].get("vector")
            except Exception:
                pass

            if not _vec_pregunta:
                _vec_pregunta = text_to_vector(_pregunta_original or engine_result.response[:100])

            _conv_ctx.add_turn(
                user_text   = _pregunta_original or "(pregunta no recuperada)",
                cognia_text = engine_result.response,
                vector      = _vec_pregunta,
            )
        except Exception as _e:
            from logger_config import get_logger as _gl
            _gl(__name__).warning(
                "Error registrando turno en ConversationContext",
                extra={"op": "_postprocess_response.conv", "context": str(_e)},
            )
"""


# ══════════════════════════════════════════════════════════════════════
# ARCHIVO 2: language_engine.py
# ══════════════════════════════════════════════════════════════════════

# ── PARCHE 2A ─────────────────────────────────────────────────────────
# Ubicación: método respond(), justo ANTES de la línea:
#   context = pre_built_context or self._build_context(ai, question)
#
# ANTES (líneas ~254-256):
PATCH_2A_ANTES = """
        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM
        # va a ser necesario. Si pre_built_context ya existe y es suficiente,
        # se reutiliza. Si no, se intenta investigación autónoma primero.
        context = pre_built_context or self._build_context(ai, question)
        context, investigated = self._maybe_investigate(ai, question, context)
"""

# DESPUÉS:
PATCH_2A_DESPUES = """
        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM
        # va a ser necesario. Si pre_built_context ya existe y es suficiente,
        # se reutiliza. Si no, se intenta investigación autónoma primero.
        #
        # PASO 3: construir_contexto ya inyecta el bloque conversacional
        # via get_conversation_context(ai).build_context_block() —
        # aquí solo nos aseguramos de que el contexto incluya ese bloque.
        context = pre_built_context or self._build_context(ai, question)
        context, investigated = self._maybe_investigate(ai, question, context)

        # ── PASO 3: enriquecer system prompt con estado del tema ───────
        # Si hubo cambio de tema, añadir nota al system prompt para que
        # el LLM no mezcle el tema anterior con el nuevo.
        try:
            from conversation_memory import get_conversation_context
            _conv_ctx = get_conversation_context(ai)
            if _conv_ctx.topic_changed_last():
                # Se añade en _get_system_prompt via parámetro extra
                self._topic_changed_hint = True
            else:
                self._topic_changed_hint = False
        except Exception:
            self._topic_changed_hint = False
"""

# ── PARCHE 2B ─────────────────────────────────────────────────────────
# Ubicación: método _get_system_prompt(), al final del método
#
# ANTES (líneas ~394-405):
PATCH_2B_ANTES = """
    def _get_system_prompt(self, question_type: str) -> str:
        base = (
            "Eres Cognia, una IA con memoria episódica y grafo de conocimiento. "
            "Usa el contexto de memoria dado. Responde en el mismo idioma de la pregunta."
        )
        extras = {
            "lista":         " Lista máx 5 ítems, 1 oración cada uno.",
            "como_funciona": " Pasos numerados, máx 5 pasos.",
            "comparacion":   " 2-3 diferencias clave, máx 2 párrafos.",
            "definicion":    " 1-2 párrafos directos.",
        }
        return base + extras.get(question_type, " Máx 2 párrafos breves.")
"""

# DESPUÉS:
PATCH_2B_DESPUES = """
    def _get_system_prompt(self, question_type: str) -> str:
        base = (
            "Eres Cognia, una IA con memoria episódica y grafo de conocimiento. "
            "Usa el contexto de memoria dado. "
            "Si hay una sección CONVERSACIÓN RECIENTE en el contexto, "
            "úsala para mantener la coherencia y continuidad de la charla: "
            "evita repetir información que ya explicaste y responde conectando "
            "con lo dicho antes si es relevante. "
            "Responde en el mismo idioma de la pregunta."
        )
        extras = {
            "lista":         " Lista máx 5 ítems, 1 oración cada uno.",
            "como_funciona": " Pasos numerados, máx 5 pasos.",
            "comparacion":   " 2-3 diferencias clave, máx 2 párrafos.",
            "definicion":    " 1-2 párrafos directos.",
        }
        # PASO 3: si hubo cambio de tema, instruir al LLM para resetear el hilo
        topic_hint = ""
        if getattr(self, "_topic_changed_hint", False):
            topic_hint = (
                " IMPORTANTE: el usuario acaba de cambiar de tema. "
                "Responde únicamente sobre la nueva pregunta, "
                "sin mezclar información del tema anterior."
            )
        return base + extras.get(question_type, " Máx 2 párrafos breves.") + topic_hint
"""
