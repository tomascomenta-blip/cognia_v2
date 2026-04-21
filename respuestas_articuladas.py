"""
respuestas_articuladas.py - Cognia v3 con Ollama (gratis, local)
=================================================================
INSTALACION:
  1. Descargar Ollama: https://ollama.com/download
  2. Abrir Ollama
  3. En PowerShell: ollama pull llama3.2

USO STANDALONE:
  python respuestas_articuladas.py "Que es Python?"

INTEGRACION FLASK (en web_app.py, antes de if __name__):
  from respuestas_articuladas import register_routes_llm
  register_routes_llm(app, get_cognia)

MODELOS RECOMENDADOS:
  16GB+ RAM : ollama pull llama3.2  o  ollama pull mistral
  8GB  RAM  : ollama pull llama3.2:1b
  4GB  RAM  : ollama pull tinyllama
"""

import os, sys, json, urllib.request

# ── Language Engine híbrido (opcional pero recomendado) ───────────────────────
try:
    from language_engine import get_language_engine
    HAS_LANGUAGE_ENGINE = True
except ImportError:
    HAS_LANGUAGE_ENGINE = False

# ── PASO 3: Memoria conversacional multi-turno ────────────────────────
try:
    from conversation_memory import get_conversation_context
    HAS_CONV_MEMORY = True
except ImportError:
    HAS_CONV_MEMORY = False

# ── ModelRouter: enrutamiento inteligente de modelos ─────────────────
try:
    from model_router import get_model_router, llamar_ollama_routed
    HAS_MODEL_ROUTER = True
except ImportError:
    HAS_MODEL_ROUTER = False

# ── CodeMemory: memoria especializada en código ───────────────────────
try:
    from code_memory import get_code_memory
    HAS_CODE_MEMORY = True
except ImportError:
    HAS_CODE_MEMORY = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODELO     = os.environ.get("COGNIA_MODEL", "llama3.2")

SYSTEM_PROMPT = (
    "Eres Cognia, una IA con memoria episodica y grafo de conocimiento. "
    "Responde de forma natural y articulada usando SOLO el contexto de memoria dado. "
    "Si el contexto es escaso dilo honestamente. Maximo 3 parrafos. "
    "Responde en el mismo idioma de la pregunta."
)

def verificar_ollama():
    try:
        print(f"[Cognia LOG] Verificando Ollama en {OLLAMA_URL}/api/tags ...", flush=True)
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        modelos = [m["name"].split(":")[0] for m in data.get("models", [])]
        print(f"[Cognia LOG] Ollama OK. Modelos disponibles: {modelos}", flush=True)
        if MODELO.split(":")[0] not in modelos:
            print(f"[Cognia LOG] ERROR: Modelo '{MODELO}' no encontrado en {modelos}", flush=True)
            return {"ok": False, "error": f"Modelo '{MODELO}' no encontrado. Disponibles: {modelos}. Corre: ollama pull {MODELO}"}
        return {"ok": True, "modelos": modelos}
    except Exception as e:
        print(f"[Cognia LOG] ERROR verificando Ollama: {type(e).__name__}: {e}", flush=True)
        return {"ok": False, "error": f"Ollama no responde ({type(e).__name__}: {e}). Descarga en https://ollama.com/download y luego: ollama pull {MODELO}"}


def tiene_suficiente_info(ai, top_label: str) -> dict:
    """
    Consulta directamente la DB para saber si Cognia ya tiene info suficiente
    sobre un concepto. Si la tiene, no vale la pena ir a Wikipedia.

    Retorna dict con:
    "suficiente": bool
    "razon":      str explicando por qué sí o no
    "score":      float 0-1 (qué tan bien conocido es el concepto)
    """
    if not top_label:
        return {"suficiente": False, "razon": "sin label", "score": 0.0}

    try:
        # Reutilizar db_connect del módulo principal en lugar de sqlite3 directo
        from cognia.database import db_connect
        db_path = getattr(ai.episodic, 'db', 'cognia_memory.db')
        conn = db_connect(db_path)
        try:
            c = conn.cursor()

            # Métricas del concepto en semantic_memory
            c.execute("""
                SELECT support, confidence
                FROM semantic_memory WHERE concept = ?
            """, (top_label,))
            row = c.fetchone()
            support    = row[0] if row else 0
            confidence = row[1] if row else 0.0

            # Episodios activos con este label
            c.execute("""
                SELECT COUNT(*) FROM episodic_memory
                WHERE label = ? AND forgotten = 0
            """, (top_label,))
            episodios = c.fetchone()[0]

            # Hechos en el knowledge graph
            c.execute("""
                SELECT COUNT(*) FROM knowledge_graph
                WHERE subject = ? OR object = ?
            """, (top_label, top_label))
            kg_edges = c.fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return {"suficiente": False, "razon": "error de DB", "score": 0.0}

    # Calcular score de suficiencia (0-1)
    score_support    = min(1.0, support / 8.0)
    score_confidence = confidence
    score_episodios  = min(1.0, episodios / 20.0)
    score_kg         = min(1.0, kg_edges / 10.0)

    score = (score_support    * 0.30 +
            score_confidence * 0.35 +
            score_episodios  * 0.20 +
            score_kg         * 0.15)

    if confidence >= 0.80:
        return {"suficiente": True,
                "razon": f"confianza alta ({confidence:.0%})",
                "score": round(score, 3)}
    if support >= 6:
        return {"suficiente": True,
                "razon": f"concepto bien reforzado (soporte={support})",
                "score": round(score, 3)}
    if episodios >= 15:
        return {"suficiente": True,
                "razon": f"muchos episodios ({episodios})",
                "score": round(score, 3)}

    return {"suficiente": False,
            "razon": f"info escasa (conf={confidence:.0%}, soporte={support}, episodios={episodios})",
            "score": round(score, 3)}


def construir_contexto(ai, pregunta):
    """
    Construye el contexto cognitivo completo para Ollama.
    - Usa adaptaciones de fatiga para ajustar cuánto contexto recuperar
    - Incluye inferencias simbólicas del InferenceEngine
    - Incluye predicciones temporales
    - Incluye hechos del KnowledgeGraph
    """
    from cognia.vectors import text_to_vector

    # Obtener adaptaciones de fatiga para no sobrecargar si el sistema está cansado
    top_k = 5
    enable_inference = True
    enable_temporal  = True
    if hasattr(ai, 'fatigue') and ai.fatigue:
        adaps = ai.fatigue.get_adaptations()
        top_k = min(adaps["top_k_retrieval"], 7)
        enable_inference = adaps["inference_max_steps"] > 0
        enable_temporal  = adaps["enable_temporal"]

    vec = text_to_vector(pregunta)
    similares = ai.episodic.retrieve_similar(vec, top_k=top_k)
    assessment = ai.metacog.assess_confidence(similares)
    top_label = assessment.get("top_label")
    # ── Generar hipótesis nuevas si hay patrones ─────────
    try:
        if hasattr(ai, "_hyp_scheduler"):
            nuevas = ai._hyp_scheduler.maybe_run(similares)
            if nuevas and hasattr(ai, "hypothesis"):
                ai.hypothesis.store_generated(top_label, nuevas)
    except Exception:
        pass

    bloques = []

    # ── PASO 3: Contexto conversacional semántico multi-turno ─────────
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
        try:
            recientes = ai.working_mem.get_recent(n=6)
            hilo = [f"- '{e['observation'][:180]}'"
                    for e in recientes
                    if e.get("observation") and e["observation"] != pregunta
                    and len(e.get("observation", "")) > 8]
            if hilo:
                bloques.append("CONVERSACIÓN RECIENTE:\n" + "\n".join(hilo[-4:]))
        except Exception:
            pass

    # ── Memorias episódicas ─────────────────────────────────────────
    eps = [
        f"- '{e['observation'][:120]}' (etiqueta: {e['label'] or 'ninguna'}, "
        f"similitud: {e['similarity']:.0%}, confianza: {e.get('confidence', 0):.0%})"
        for e in similares if e["similarity"] > 0.2
    ]
    if eps:
        bloques.append("MEMORIAS EPISÓDICAS:\n" + "\n".join(eps))

    if top_label:
        # ── Conceptos semánticos relacionados ──────────────────────
        acts = ai.semantic.spreading_activation(top_label, depth=2)
        if acts:
            concept_lines = [f"- {a['concept']} (activación: {a['activation']:.2f})"
                             for a in acts[:6]]
            bloques.append("CONCEPTOS RELACIONADOS:\n" + "\n".join(concept_lines))

        # ── Knowledge Graph ─────────────────────────────────────────
        hechos = ai.kg.get_facts(top_label)
        kg_lines = [
            f"- {h['subject']} --{h['predicate']}--> {h['object']} (peso: {h['weight']:.1f})"
            for h in hechos[:10]
        ]
        jerarquia = ai.kg.get_ancestors(top_label)
        if jerarquia:
            kg_lines.append(f"- Jerarquía: {top_label} → {' → '.join(jerarquia)}")
        if kg_lines:
            bloques.append("GRAFO DE CONOCIMIENTO:\n" + "\n".join(kg_lines))

        # ── Inferencias simbólicas (solo si no hay fatiga crítica) ──
        if enable_inference:
            infs = ai.inference.infer(top_label, max_steps=3)
            props = ai.inference.infer_properties(top_label)
            inf_lines = [
                f"- {i.get('justification', '')[:120]}"
                for i in infs[:4]
            ]
            inf_lines += [
                f"- {top_label} {p['property']} {p['value']} "
                f"(heredado de: {p['inherited_from']})"
                for p in props[:3]
            ]
            if inf_lines:
                bloques.append("INFERENCIAS SIMBÓLICAS:\n" + "\n".join(inf_lines))

        # ── Hipótesis generadas sobre el concepto ───────────────────
        hyp_lines = []
        try:
            hyp_result = ai.hypothesis.get_hypotheses_for(top_label)
            for h in (hyp_result or [])[:2]:
                hyp_lines.append(f"- {h.get('hypothesis', '')[:100]} "
                                  f"(conf: {h.get('confidence', 0):.0%})")
        except Exception:
            pass
        if hyp_lines:
            bloques.append("HIPÓTESIS PREVIAS:\n" + "\n".join(hyp_lines))

    # ── Predicciones temporales (si no hay fatiga alta) ─────────────
    if enable_temporal:
        preds = ai.temporal_mem.predict_from_context()
        if preds:
            pred_lines = [
                f"- {p['concept']} (probabilidad: {p['probability']:.0%})"
                for p in preds[:3]
            ]
            bloques.append("PREDICCIONES TEMPORALES:\n" + "\n".join(pred_lines))

    # ── Estado de confianza metacognitiva ────────────────────────────
    state = assessment.get("state", "ignorant")
    conf  = assessment.get("confidence", 0.0)
    state_labels = {
        "confident": "segura", "uncertain": "incierta",
        "confused":  "confundida", "ignorant": "sin datos"
    }
    meta_line = (f"- Estado: {state_labels.get(state, state)} "
                 f"(confianza metacognitiva: {conf:.0%})")
    if top_label:
        meta_line += f", concepto principal: '{top_label}'"
    bloques.append("ESTADO COGNITIVO:\n" + meta_line)

    return "\n\n".join(bloques)

def detectar_tipo_pregunta(pregunta: str) -> dict:
    """
    Clasifica el tipo de pregunta para ajustar el prompt y num_predict.
    """
    p = pregunta.lower()
    
    # Preguntas de explicación larga (merecen respuesta estructurada y larga)
    if any(w in p for w in ["cómo","como","explica","explícame","paso a paso",
                              "tutorial","guía","guia","proceso","procedimiento",
                              "diferencia entre","compara","ventajas","desventajas"]):
        return {"tipo": "explicacion", "num_predict": 800, "structured": True}
    
    # Preguntas de definición (respuesta media)
    if any(w in p for w in ["qué es","que es","qué son","que son","define",
                              "definición","definicion","significa","significado"]):
        return {"tipo": "definicion", "num_predict": 500, "structured": False}
    
    # Preguntas de historia/contexto (respuesta media-larga)
    if any(w in p for w in ["historia","histori","origen","cuándo","cuando",
                              "quién","quien","por qué","por que","razón","razon"]):
        return {"tipo": "contexto", "num_predict": 600, "structured": False}
    
    # Preguntas cortas / conversacionales
    if len(pregunta.split()) <= 5:
        return {"tipo": "corta", "num_predict": 300, "structured": False}
    
    # Default
    return {"tipo": "general", "num_predict": 600, "structured": False}


SYSTEM_PROMPT_ESTRUCTURADO = (
    "Eres Cognia, una IA con memoria episodica y grafo de conocimiento. "
    "Responde con una explicación clara y estructurada usando el contexto de memoria dado. "
    "Usa numeración o pasos cuando sea apropiado. Máximo 5 puntos o secciones. "
    "Responde en el mismo idioma de la pregunta."
)


def _calcular_num_predict(tipo: str, pregunta: str) -> int:
    """Tokens de salida según tipo y longitud — conservador para CPU sin GPU."""
    base = {"tutorial": 380, "comparacion": 320, "lista": 300, "complejo": 360, "general": 260}
    tokens = base.get(tipo, 260)
    tokens += min(60, len(pregunta) // 10)
    return min(420, tokens)


def _construir_system_prompt(tipo: str) -> str:
    base = (
        "Eres Cognia, una IA con memoria episódica y grafo de conocimiento. "
        "Usa el contexto de memoria dado. Si hay una sección CONVERSACIÓN RECIENTE, "
        "úsala para mantener la continuidad de la charla. "
        "Responde en el mismo idioma de la pregunta."
    )
    if tipo == "tutorial":
        return base + " Pasos numerados (1. 2. 3.). Máximo 5 pasos de 1 oración cada uno."
    if tipo == "comparacion":
        return base + " 2-3 diferencias clave. Máximo 2 párrafos."
    if tipo == "lista":
        return base + " Lista máximo 5 ítems con 1 oración cada uno."
    return base + " Máximo 2 párrafos breves y directos."


def llamar_ollama(prompt, num_predict=280, structured=False, tipo="general", pregunta=""):
    """
    Llama a Ollama con streaming.
    Si ModelRouter esta disponible, enruta al modelo correcto segun el tipo de tarea
    (codigo -> qwen2.5-coder, general -> llama3.2).
    """
    # Rama con ModelRouter
    if HAS_MODEL_ROUTER:
        try:
            code_ctx = ""
            if HAS_CODE_MEMORY:
                try:
                    cm = get_code_memory()
                    code_ctx = cm.get_context_for_prompt(pregunta or prompt[:300])
                except Exception:
                    code_ctx = ""
            return llamar_ollama_routed(
                prompt      = prompt,
                pregunta    = pregunta,
                num_predict = num_predict,
                structured  = structured,
                tipo        = tipo,
                code_context= code_ctx,
            )
        except Exception as _router_exc:
            print(f"[Cognia LOG] ModelRouter fallo ({_router_exc}), usando fallback directo", flush=True)

    # Fallback: llamada directa sin router
    if not structured:
        num_predict = _calcular_num_predict(tipo, pregunta)
        system = _construir_system_prompt(tipo)
    else:
        system = SYSTEM_PROMPT_ESTRUCTURADO
    payload = json.dumps({
        "model": MODELO, "prompt": prompt, "system": system,
        "stream": True, "options": {"temperature": 0.7, "num_predict": num_predict}
    }).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    import time as _time
    print(f"[Cognia LOG] Enviando prompt a Ollama (modelo={MODELO}, num_predict={num_predict}, tipo={tipo}) ...", flush=True)
    _t0 = _time.time()
    resultado = []
    with urllib.request.urlopen(req, timeout=180) as r:
        for linea in r:
            if not linea.strip():
                continue
            try:
                chunk = json.loads(linea.decode("utf-8"))
            except Exception:
                continue
            token = chunk.get("response", "")
            if token:
                resultado.append(token)
            if chunk.get("done"):
                _elapsed = _time.time() - _t0
                print(f"[Cognia LOG] Ollama respondio en {_elapsed:.1f}s — tokens: {len(resultado)}", flush=True)
                break
    return "".join(resultado).strip()


def _preprocess_question(ai, pregunta: str) -> dict:
    """
    Registro de la pregunta: working_memory, chat_history, user_profile.

    Ya NO hace suficiencia ni investigacion — esas decisiones pertenecen al
    engine (Stage 0 lazy en _maybe_investigate). El wrapper solo registra
    la interaccion y devuelve un response_id unico.

    Retorna dict con claves:
      response_id, _suficiencia (None — el engine la evalua internamente)
    """
    import uuid as _uuid
    response_id = _uuid.uuid4().hex[:12]

    # ── Registro en chat_history y working_memory ─────────────────────
    try:
        if hasattr(ai, "chat_history"):
            ai.chat_history.log(
                role        = "user",
                content     = pregunta,
                response_id = response_id,
                confidence  = 0.0,
            )
        try:
            from cognia.vectors import text_to_vector, analyze_emotion
        except ImportError:
            from vectors import text_to_vector, analyze_emotion
        vec = text_to_vector(pregunta)
        emotion = analyze_emotion(pregunta)
        ai.working_mem.add(pregunta, None, vec, emotion, 0.3)
        if hasattr(ai, "user_profile"):
            lang = "es" if any(c in pregunta.lower() for c in "aeiouuáéíóúñ") else "en"
            ai.user_profile.set("lang", lang)
            ai.user_profile.set("last_seen", __import__("datetime").datetime.now().isoformat())
    except Exception:
        pass

    return {
        "response_id":         response_id,
        "_suficiencia":        None,   # evaluada internamente por el engine
        "_skip_investigacion": False,  # el engine decide
    }


def _postprocess_response(ai, engine_result, pre: dict) -> dict:
    """
    Stage 5 (post): persiste la respuesta del engine en chat_history y working_memory,
    y construye el dict de resultado normalizado que consume web_app.py.
    """
    try:
        from cognia.vectors import text_to_vector, analyze_emotion
    except ImportError:
        from vectors import text_to_vector, analyze_emotion

    # chat_history — respuesta del asistente
    try:
        if hasattr(ai, "chat_history"):
            ai.chat_history.log(
                role        = "assistant",
                content     = engine_result.response[:500],
                response_id = engine_result.response_id,
                confidence  = engine_result.confidence,
            )
    except Exception:
        pass

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
    if HAS_CONV_MEMORY:
        try:
            _conv_ctx = get_conversation_context(ai)
            _pregunta_orig = ""
            _vec_preg = None
            try:
                _recientes = ai.working_mem.get_recent(n=2)
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

    resultado = {
        "response":         engine_result.response,
        "modelo":           engine_result.modelo or MODELO,
        "tipo_pregunta":    engine_result.tipo_pregunta or "general",
        "tiene_contexto":   engine_result.tiene_contexto,
        "episodios_usados": engine_result.episodios_usados,
        "investigado":      engine_result.investigated,
        "info_suficiente":  engine_result.info_suficiente,
        "suficiencia":      pre["_suficiencia"],
        "response_id":      engine_result.response_id,
        "language_engine":  {
            "stage":      engine_result.stage_used,
            "confidence": engine_result.confidence,
            "used_llm":   engine_result.used_llm,
        },
    }
    return resultado


def responder_articulado(ai, pregunta):
    """
    Thin wrapper sobre LanguageEngine.

    Flujo:
      _preprocess_question             — registro: working_mem, chat_history, user_profile
      Stages 0-5  (engine.respond)     — Stage 0 lazy (contexto + investigacion) →
                                         cache → simbolico → hibrido → LLM → fallback
      _postprocess_response            — chat_history (respuesta), working_mem

    El flujo directo de Ollama solo se activa si el engine no pudo importarse
    o lanzo una excepcion no recuperable. No es el camino normal.
    """
    print(f"[Cognia LOG] === Nueva pregunta: {pregunta[:80]!r} ===", flush=True)

    # ── Stage 0: pre-proceso ──────────────────────────────────────────
    pre = _preprocess_question(ai, pregunta)

    # ── Stages 1-5: Language Engine ───────────────────────────────────
    if HAS_LANGUAGE_ENGINE:
        try:
            engine = get_language_engine(ai)
            engine_result = engine.respond(
                cognia_instance = ai,
                question        = pregunta,
            )
            print(
                f"[Cognia LOG] LanguageEngine respondió "
                f"(stage={engine_result.stage_used}, "
                f"llm={'sí' if engine_result.used_llm else 'no'})",
                flush=True,
            )
            return _postprocess_response(ai, engine_result, pre)
        except Exception as _le:
            print(
                f"[Cognia LOG] LanguageEngine error: {_le} — "
                f"activando fallback Ollama directo",
                flush=True,
            )

    # ── Fallback: Ollama directo (solo si engine no disponible) ──────
    # Esta rama solo se ejecuta cuando language_engine.py no pudo importarse
    # o lanzó una excepción no recuperada. No es el camino normal.
    print(f"[Cognia LOG] Fallback Ollama directo (engine no disponible)", flush=True)

    # Fallback: construir contexto aqui porque el engine no llego a hacerlo
    response_id = pre["response_id"]
    _suficiencia = pre["_suficiencia"]
    contexto = construir_contexto(ai, pregunta)
    investigado = False
    info_inv = None
    try:
        from investigador import investigar_si_necesario
        contexto, investigado, info_inv = investigar_si_necesario(ai, pregunta, contexto)
    except Exception:
        pass

    tipo_info = detectar_tipo_pregunta(pregunta)
    tipo_pregunta = tipo_info.get("tipo", "general")

    if contexto:
        inv_nota = "\n(Nota: investigué esto ahora en Wikipedia y lo guardé en mi memoria.)" if investigado else ""
        contexto_trim = contexto[:1200] + ("..." if len(contexto) > 1200 else "")
        prompt = (f"PREGUNTA: {pregunta[:400]}\n\n"
                  f"CONTEXTO DE MI MEMORIA:\n{contexto_trim}{inv_nota}\n\n"
                  "Responde basandote en el contexto de forma natural.")
    else:
        prompt = (f"PREGUNTA: {pregunta[:400]}\n\n"
                  "No tengo información específica en mi memoria sobre esto. "
                  "Usa tu conocimiento general, razona sobre los conceptos involucrados "
                  "y responde de forma directa. Sin listas. Máximo 2 párrafos. "
                  "Responde en el mismo idioma de la pregunta.")

    estado = verificar_ollama()
    if not estado["ok"]:
        return {"error": estado["error"]}

    try:
        respuesta = llamar_ollama(
            prompt,
            tipo      = tipo_pregunta,
            pregunta  = pregunta,
            structured = tipo_info.get("structured", False),
        )
        try:
            try:
                from cognia.vectors import text_to_vector, analyze_emotion
            except ImportError:
                from vectors import text_to_vector, analyze_emotion
            _vec_r = text_to_vector(respuesta[:200]) if respuesta else None
            if _vec_r:
                ai.working_mem.add(f"[Cognia]: {respuesta[:280]}", None,
                                   _vec_r, analyze_emotion(respuesta[:100]), 0.5)
        except Exception:
            pass
        try:
            if hasattr(ai, "chat_history"):
                ai.chat_history.log(
                    role        = "assistant",
                    content     = respuesta[:500],
                    response_id = response_id,
                    confidence  = _suficiencia["score"] if _suficiencia else 0.0,
                )
        except Exception:
            pass
        resultado = {
            "response":         respuesta,
            "modelo":           MODELO,
            "tipo_pregunta":    tipo_pregunta,
            "tiene_contexto":   bool(contexto),
            "episodios_usados": contexto.count("- '") if contexto else 0,
            "investigado":      investigado,
            "info_suficiente":  False,
            "suficiencia":      _suficiencia,
            "response_id":      response_id,
        }
        if investigado and info_inv:
            resultado["investigacion"] = {
                "titulo":    info_inv["titulo"],
                "url":       info_inv["url"],
                "hipotesis": len(info_inv.get("hipotesis", [])),
            }
        return resultado
    except Exception as e:
        print(f"[Cognia LOG] EXCEPCION en llamar_ollama: {type(e).__name__}: {e}", flush=True)
        return {"error": f"Error llamando a Ollama: {type(e).__name__}: {e}"}

def register_routes_llm(app, ai_getter):
    from flask import request, jsonify

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        data = request.get_json()
        pregunta = data.get("text", "").strip()
        if not pregunta:
            return jsonify({"error": "Texto vacio"})

        ai = ai_getter()
        result = responder_articulado(ai, pregunta)

        # ── Tick del SelfArchitect integrado ────────────────────────
        # Evaluación automática cada EVAL_INTERVAL interacciones.
        # Si encuentra problemas, genera propuestas en DB para revisión humana.
        # Nunca interrumpe el flujo de respuesta.
        try:
            from self_architect import SelfArchitect
            if not hasattr(api_chat, "_architect"):
                api_chat._architect = SelfArchitect(cognia_instance=ai)
            eval_result = api_chat._architect.tick(ai.interaction_count)
            if eval_result and eval_result.get("proposals_generated", 0) > 0:
                result["_architect"] = {
                    "score":     eval_result["score"],
                    "proposals": eval_result["proposals_generated"],
                    "critical":  eval_result.get("has_critical", False),
                }
        except Exception:
            pass

        # ── Incluir datos de fatiga en la respuesta ──────────────────
        try:
            if hasattr(ai, 'fatigue') and ai.fatigue:
                fatigue_state = ai.fatigue.get_state()
                result["fatigue"] = {
                    "score":        fatigue_state["fatigue_score"],
                    "level":        fatigue_state["fatigue_level"],
                    "trend":        fatigue_state["fatigue_trend"],
                    "mode":         fatigue_state["active_strategies"][:2] if fatigue_state["active_strategies"] else [],
                    "cpu":          fatigue_state["current_cpu_pct"],
                    "mem_mb":       fatigue_state["current_mem_mb"],
                    "energy_watts": fatigue_state.get("energy_watts", 0.0),
                    "cache_hit_rate": fatigue_state.get("cache_hit_rate", 0.0),
                    "avg_cycle_ms": fatigue_state.get("avg_cycle_ms", 0.0),
                }
                # Si el sistema necesita propuesta arquitectural por fatiga crítica
                if result.get("_needs_arch_optimization"):
                    try:
                        if not hasattr(api_chat, "_architect"):
                            from self_architect import SelfArchitect
                            api_chat._architect = SelfArchitect(cognia_instance=ai)
                        api_chat._architect.run_evaluation(triggered_by="fatigue_critical")
                    except Exception:
                        pass
        except Exception:
            pass

        return jsonify(result)

    @app.route("/api/ollama_status")
    def api_ollama_status():
        return jsonify(verificar_ollama())

    @app.route("/api/fatiga")
    def api_fatiga():
        """Estado completo del monitor de fatiga cognitiva."""
        ai = ai_getter()
        if hasattr(ai, 'fatigue') and ai.fatigue:
            return jsonify(ai.fatigue.get_state())
        return jsonify({"error": "Monitor de fatiga no disponible"})

    print(f"[OK] /api/chat activo con modelo: {MODELO}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python respuestas_articuladas.py "Tu pregunta"')
        print()
        print("Variables de entorno:")
        print("  COGNIA_MODEL=llama3.2   (default)")
        print("  OLLAMA_URL=http://localhost:11434   (default)")
        print()
        print("Primero descarga un modelo:")
        print("  ollama pull llama3.2      (2GB, bueno)")
        print("  ollama pull llama3.2:1b   (1GB, rapido)")
        print("  ollama pull tinyllama     (600MB, PC basico)")
        sys.exit(1)

    pregunta = " ".join(sys.argv[1:])

    print(f"\nVerificando Ollama...")
    estado = verificar_ollama()
    if not estado["ok"]:
        print(f"ERROR: {estado['error']}")
        sys.exit(1)
    print(f"OK - modelo: {MODELO}")

    print(f"\nIniciando Cognia...")
    from cognia import Cognia
    ai = Cognia()

    print(f"\nPregunta: {pregunta}")
    contexto = construir_contexto(ai, pregunta)
    if contexto:
        print(f"\n{contexto}\n")
    else:
        print("(sin contexto relevante)\n")

    print("-" * 50)
    print(f"\nGenerando respuesta con {MODELO}...\n")
    resultado = responder_articulado(ai, pregunta)

    if "error" in resultado:
        print(f"ERROR: {resultado['error']}")
    else:
        print(resultado["response"])
        print(f"\n[Modelo: {resultado['modelo']} | Memorias usadas: {resultado['episodios_usados']}]")

