"""
refactor_guide.py — Guía de refactorización para los módulos restantes
========================================================================
Ejemplos ANTES / DESPUÉS para todos los patrones de error silencioso
encontrados en Cognia. Aplicar el mismo patrón a:
  - semantic.py
  - language_engine.py
  - symbolic_responder.py
  - prompt_optimizer.py
  - cognia.py (imports opcionales)
  - config.py (prints → logs)
  - respuestas_articuladas.py (llamadas a Ollama)
  - web_app.py
"""

# ══════════════════════════════════════════════════════════════════════
# PATRÓN 1: ACCESO A BASE DE DATOS
# ══════════════════════════════════════════════════════════════════════

# ── ANTES ─────────────────────────────────────────────────────────────
def get_concept_ANTES(self, concept):
    try:
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute("SELECT concept, vector FROM semantic_memory WHERE concept=?", (concept,))
        row = c.fetchone()
        conn.close()
        return row
    except:
        pass  # ← SILENT FAIL: nadie sabe que la DB falló

# ── DESPUÉS ───────────────────────────────────────────────────────────
def get_concept_DESPUES(self, concept):
    try:
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute("SELECT concept, vector FROM semantic_memory WHERE concept=?", (concept,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as exc:
        log_db_error(logger, "semantic.get_concept", exc,
                     extra_ctx=f"concept={concept}")
        return None


# ══════════════════════════════════════════════════════════════════════
# PATRÓN 2: CÁLCULO DE EMBEDDINGS
# ══════════════════════════════════════════════════════════════════════

# ── ANTES ─────────────────────────────────────────────────────────────
def text_to_vector_ANTES(text):
    try:
        model = get_model()
        return model.encode(text).tolist()
    except:
        pass  # ← retorna None silenciosamente, rompe cálculos aguas abajo

# ── DESPUÉS ───────────────────────────────────────────────────────────
def text_to_vector_DESPUES(text):
    t0 = time.perf_counter()
    try:
        model = get_model()
        vec = model.encode(text).tolist()
        log_slow(logger, "embed.text_to_vector", t0, threshold_ms=150)
        return vec
    except RuntimeError as exc:
        # Error de modelo (CUDA OOM, etc.) — crítico, loguear como error
        logger.error(
            "Fallo en modelo de embeddings (RuntimeError)",
            extra={"op": "embed.text_to_vector",
                   "context": f"text_len={len(text)} err={exc}"},
        )
        return _ngram_vector(text)  # fallback a n-gramas
    except Exception as exc:
        logger.warning(
            "Error calculando embedding, usando n-gramas como fallback",
            extra={"op": "embed.text_to_vector",
                   "context": f"text_len={len(text)} err={exc}"},
        )
        return _ngram_vector(text)


# ══════════════════════════════════════════════════════════════════════
# PATRÓN 3: LLAMADA A OLLAMA (LLM externo)
# ══════════════════════════════════════════════════════════════════════

# ── ANTES ─────────────────────────────────────────────────────────────
def llamar_ollama_ANTES(prompt, model="llama3", timeout=30):
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({"model": model, "prompt": prompt}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["response"]
    except:
        pass  # ← nadie sabe si Ollama está caído

# ── DESPUÉS ───────────────────────────────────────────────────────────
def llamar_ollama_DESPUES(prompt, model="llama3", timeout=30):
    import urllib.error
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({"model": model, "prompt": prompt}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())["response"]
            log_slow(logger, "ollama.generate", t0, threshold_ms=500)
            return result
    except urllib.error.URLError as exc:
        # Ollama no está corriendo o no es alcanzable
        logger.error(
            "Ollama no disponible (URLError)",
            extra={"op": "ollama.generate",
                   "context": f"model={model} timeout={timeout} err={exc}"},
        )
        return None
    except TimeoutError:
        logger.error(
            f"Ollama timeout después de {timeout}s",
            extra={"op": "ollama.generate",
                   "context": f"model={model} prompt_len={len(prompt)}"},
        )
        return None
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error(
            "Respuesta de Ollama malformada",
            extra={"op": "ollama.generate",
                   "context": f"model={model} err={exc}"},
        )
        return None
    except Exception as exc:
        logger.error(
            "Error inesperado llamando a Ollama",
            extra={"op": "ollama.generate",
                   "context": f"model={model} err={exc}"},
        )
        return None


# ══════════════════════════════════════════════════════════════════════
# PATRÓN 4: LECTURA/ESCRITURA DE ARCHIVOS
# ══════════════════════════════════════════════════════════════════════

# ── ANTES ─────────────────────────────────────────────────────────────
def load_config_ANTES(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        pass

# ── DESPUÉS ───────────────────────────────────────────────────────────
def load_config_DESPUES(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(
            "Archivo de configuración no encontrado, usando defaults",
            extra={"op": "config.load", "context": f"path={path}"},
        )
        return {}
    except json.JSONDecodeError as exc:
        logger.error(
            "Archivo de configuración tiene JSON inválido",
            extra={"op": "config.load", "context": f"path={path} err={exc}"},
        )
        return {}
    except OSError as exc:
        logger.error(
            "Error de sistema leyendo configuración",
            extra={"op": "config.load", "context": f"path={path} err={exc}"},
        )
        return {}


# ══════════════════════════════════════════════════════════════════════
# PATRÓN 5: RECUPERACIÓN DE MEMORIA EPISÓDICA
# (fila corrupta en bucle — NO abortar el bucle completo)
# ══════════════════════════════════════════════════════════════════════

# ── ANTES ─────────────────────────────────────────────────────────────
def score_episodes_ANTES(rows, query_vector):
    scored = []
    for row in rows:
        try:
            vec = json.loads(row["vector"])
            sim = cosine_similarity(query_vector, vec)
            scored.append({"id": row["id"], "sim": sim})
        except:
            pass  # ← fila silenciosamente ignorada, sin diagnóstico
    return scored

# ── DESPUÉS ───────────────────────────────────────────────────────────
def score_episodes_DESPUES(rows, query_vector):
    scored = []
    for row in rows:
        try:
            vec = json.loads(row["vector"])
            sim = cosine_similarity(query_vector, vec)
            scored.append({"id": row["id"], "sim": sim})
        except (json.JSONDecodeError, TypeError) as exc:
            # Warning (no error): fila individual corrupta, el sistema sigue
            logger.warning(
                "Episodio con vector corrupto, ignorando fila",
                extra={"op": "episodic.score_episodes",
                       "context": f"ep_id={row.get('id', '?')} err={exc}"},
            )
            continue
        except Exception as exc:
            # Cualquier otro fallo en una fila individual
            logger.warning(
                "Error inesperado puntuando episodio",
                extra={"op": "episodic.score_episodes",
                       "context": f"ep_id={row.get('id', '?')} err={exc}"},
            )
            continue
    return scored


# ══════════════════════════════════════════════════════════════════════
# PATRÓN 6: IMPORTS OPCIONALES en config.py
# (reemplazar prints por logs)
# ══════════════════════════════════════════════════════════════════════

# ── ANTES ─────────────────────────────────────────────────────────────
def imports_config_ANTES():
    try:
        import numpy as np
        HAS_NUMPY = True
    except ImportError:
        HAS_NUMPY = False
        print("⚠️  numpy no encontrado")  # ← print no va a logs estructurados

# ── DESPUÉS ───────────────────────────────────────────────────────────
def imports_config_DESPUES():
    _log = get_logger("cognia.config")
    try:
        import numpy as np
        HAS_NUMPY = True
        _log.debug("numpy cargado", extra={"op": "config.import", "context": "numpy"})
    except ImportError:
        HAS_NUMPY = False
        _log.info(
            "numpy no encontrado — clustering básico disponible",
            extra={"op": "config.import", "context": "numpy_missing"},
        )


# ══════════════════════════════════════════════════════════════════════
# PATRÓN 7: safe_execute para operaciones de una línea
# ══════════════════════════════════════════════════════════════════════

# ── ANTES ─────────────────────────────────────────────────────────────
def introspect_ANTES(self):
    try:
        return self._ai.introspect()
    except:
        pass

# ── DESPUÉS ───────────────────────────────────────────────────────────
def introspect_DESPUES(self):
    return safe_execute(
        lambda: self._ai.introspect(),
        context="cognia.introspect",
        fallback={},
        logger=logger,
        level="warning",
    )


# ══════════════════════════════════════════════════════════════════════
# GUÍA: CUÁNDO USAR WARNING vs ERROR vs CRITICAL
# ══════════════════════════════════════════════════════════════════════
"""
NIVEL       CUÁNDO USARLO                               EJEMPLO
─────────────────────────────────────────────────────────────────────
DEBUG       Flujo normal, datos de diagnóstico          "Cache hit para concept=X"
            que solo se leen durante debugging

INFO        Eventos esperados de negocio                "Episodio almacenado ep_id=42"
            (el sistema funciona, algo ocurrió)         "Corrección aplicada label=X"

WARNING     Algo inesperado pero recuperable            "Fila corrupta ignorada ep_id=5"
            El sistema usa un fallback                  "Embedding tardó 450ms (>150ms)"
            Módulo opcional no disponible               "Ollama timeout, retrying"

ERROR       Operación fallida sin recuperación           "DB write falló — datos perdidos"
            Datos que deberían guardarse no se           "Ollama caído, sin respuesta LLM"
            guardaron. El sistema sigue vivo pero        "JSON inválido en respuesta API"
            con funcionalidad reducida.

CRITICAL    El sistema NO puede continuar                "DB no inicializada"
            Fallo en inicialización core                 "Vector DIM incorrecto en toda
                                                          la memoria — sistema corrupto"

──────────────────────────────────────────────────────────────────────
CUÁNDO RELANZAR EXCEPCIONES (reraise=True):
  - En __init__ de módulos core (DB no se puede crear → sistema no puede arrancar)
  - En operaciones de migración de datos
  - Cuando el caller DEBE saber que falló (no tiene fallback seguro)
  - En tests/validaciones donde el fallo es la respuesta esperada

CUÁNDO NO RELANZAR:
  - Fila corrupta en un bucle de múltiples filas
  - Cache miss (no es un error)
  - Módulo opcional no instalado
  - Timeout en llamada externa con fallback disponible

──────────────────────────────────────────────────────────────────────
CÓMO EVITAR SPAM DE LOGS:
  1. Bucles: loguear una vez fuera del bucle, no N veces dentro
     MAL: for row in rows: logger.warning(...)  ← N warnings
     BIEN: errores = []; for row ...: errores.append(id)
           if errores: logger.warning(f"{len(errores)} filas corruptas", ...)

  2. Módulos opcionales: loguear solo en __init__, no en cada llamada
     MAL: if not self._guard: logger.warning("guard no disponible")  en correct()
     BIEN: loguear una vez en __init__ de TeacherInterface

  3. Cache misses: nivel DEBUG, no WARNING
     Un miss es comportamiento normal, no un problema.

  4. Polling / latidos: usar log_slow() solo cuando supera el umbral
     No loguear cada tick de 5ms.
"""
