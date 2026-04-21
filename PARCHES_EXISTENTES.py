"""
PARCHES PARA ARCHIVOS EXISTENTES
=================================
Este archivo documenta exactamente qué líneas cambiar en los archivos
que NO se reemplazaron completamente.

Aplica los cambios en este orden:
  1. cognia_v3.py        (3 secciones)
  2. respuestas_articuladas.py  (1 sección)
  3. web_app.py          (2 líneas de import)

Los archivos nuevos ya están listos:
  - cognia_embedding.py
  - cognia_deferred.py
  - curiosidad_adaptativa.py
"""

# ══════════════════════════════════════════════════════════════════════
# PARCHE 1 — cognia_v3.py
# Sección A: reemplazar carga del modelo en import-time
# ══════════════════════════════════════════════════════════════════════
#
# BUSCAR (aprox. líneas 108-113):
# ──────────────────────────────────────────────────────────────────────
BUSCAR_1A = """
try:
    from sentence_transformers import SentenceTransformer
    _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    VECTOR_DIM = 384
    HAS_SEMANTIC = True
    print("✅ sentence-transformers cargado (vectores semánticos reales)")
except ImportError:
    HAS_SEMANTIC = False
    VECTOR_DIM = 64
    print("⚠️  sentence-transformers no encontrado. Usando n-gramas.")
"""

# REEMPLAZAR POR:
# ──────────────────────────────────────────────────────────────────────
REEMPLAZAR_1A = """
# ── Embeddings: lazy + async batching (cognia_embedding.py) ───────────
from cognia_embedding import (
    LazyEmbeddingModel,
    BoundedLRUCache,
    get_embedding_queue,
    text_to_vector_fast,
    _ngram_vector,
)
# Detectar si sentence-transformers está disponible sin cargarlo todavía
try:
    import importlib.util
    HAS_SEMANTIC = importlib.util.find_spec("sentence_transformers") is not None
    VECTOR_DIM   = 384 if HAS_SEMANTIC else 64
    if HAS_SEMANTIC:
        print("✅ sentence-transformers detectado (se cargará en primer uso)")
    else:
        print("⚠️  sentence-transformers no encontrado. Usando n-gramas.")
except Exception:
    HAS_SEMANTIC = False
    VECTOR_DIM   = 64
"""

# ══════════════════════════════════════════════════════════════════════
# PARCHE 1 — cognia_v3.py
# Sección B: reemplazar _embedding_cache y text_to_vector
# ══════════════════════════════════════════════════════════════════════
#
# BUSCAR (aprox. líneas 153-197):
# ──────────────────────────────────────────────────────────────────────
BUSCAR_1B = """
# Cache LRU para embeddings — reduce cómputo repetido (eficiencia energética)
_embedding_cache: Dict[str, list] = {}
_CACHE_MAX = 512
"""

# REEMPLAZAR POR:
# ──────────────────────────────────────────────────────────────────────
REEMPLAZAR_1B = """
# Cache LRU thread-safe (BoundedLRUCache de cognia_embedding.py)
_embedding_cache = BoundedLRUCache(max_entries=512)
"""

# Y reemplazar la función text_to_vector completa:
BUSCAR_1B2 = """
def text_to_vector(text: str, dim: int = VECTOR_DIM) -> list:
    \"\"\"
    Vectorización con cache LRU para reducir consumo energético.
    Solo calcula embedding si el texto no fue visto antes.
    Notifica al monitor de fatiga sobre cache hits/misses.
    \"\"\"
    cache_key = text[:200]  # clave truncada para evitar leaks de memoria
    if cache_key in _embedding_cache:
        # Cache hit — operación barata
        if HAS_FATIGUE and _FATIGUE_MONITOR:
            _FATIGUE_MONITOR.record_embedding_cached()
        return _embedding_cache[cache_key]

    if HAS_SEMANTIC:
        vec = _ST_MODEL.encode(text, normalize_embeddings=True).tolist()
    else:
        # Fallback: n-gramas de caracteres
        vec = [0.0] * dim
        text_lower = text.lower().strip()
        for i, ch in enumerate(text_lower):
            idx = (ord(ch) * 31 + i) % dim
            vec[idx] += 1.0
        for i in range(len(text_lower) - 1):
            h = (hash(text_lower[i:i+2]) & 0x7FFFFFFF) % dim
            vec[h] += 0.7
        for word in text_lower.split():
            h = (hash(word) & 0x7FFFFFFF) % dim
            vec[h] += 1.5
        norm = vec_norm(vec)
        if norm > 0:
            vec = [x / norm for x in vec]

    # Cache miss — operación costosa, notificar al monitor
    if HAS_FATIGUE and _FATIGUE_MONITOR:
        _FATIGUE_MONITOR.record_embedding_computed()

    # Gestión del cache con límite de tamaño
    if len(_embedding_cache) >= _CACHE_MAX:
        oldest_key = next(iter(_embedding_cache))
        del _embedding_cache[oldest_key]
    _embedding_cache[cache_key] = vec
    return vec
"""

REEMPLAZAR_1B2 = """
def text_to_vector(text: str, dim: int = VECTOR_DIM) -> list:
    \"\"\"
    Wrapper que delega a text_to_vector_fast de cognia_embedding.py.
    Thread-safe, lazy model, async batching, LRU cache con eviction O(1).
    \"\"\"
    return text_to_vector_fast(
        text,
        dim=dim,
        fatigue_monitor=_FATIGUE_MONITOR if HAS_FATIGUE else None,
    )
"""

# ══════════════════════════════════════════════════════════════════════
# PARCHE 1 — cognia_v3.py
# Sección C: inicializar queue y módulos diferidos en Cognia.__init__()
# ══════════════════════════════════════════════════════════════════════
#
# Agregar al FINAL de Cognia.__init__(), justo antes del último return
# (o antes del primer uso de self.episodic / self.working_mem):
# ──────────────────────────────────────────────────────────────────────
AGREGAR_EN_INIT = """
        # ── Módulos de optimización ───────────────────────────────────
        from cognia_embedding import get_embedding_queue
        from cognia_deferred  import DeferredMaintenance, IdleHypothesisScheduler

        # Inicializar el queue de embeddings con el throttle real
        self._embedding_queue = get_embedding_queue(
            throttle_controller=self.fatigue,
            vector_dim=VECTOR_DIM,
        )

        # Mantenimiento diferido (consolidation + forgetting)
        self._maintenance = DeferredMaintenance(
            self, throttle_controller=self.fatigue
        )

        # Hipótesis solo en idle
        self._hyp_scheduler = IdleHypothesisScheduler(
            self,
            min_idle_s=60.0,
            cpu_threshold=40.0,
        )
"""

# ══════════════════════════════════════════════════════════════════════
# PARCHE 1 — cognia_v3.py
# Sección D: reemplazar el bloque de hipótesis y mantenimiento en observe()
# ══════════════════════════════════════════════════════════════════════
#
# BUSCAR en el bloque "MODO INFERENCIA" de observe():
BUSCAR_1D = """
            pattern_hypothesis = None
            if len(similar) >= 2:
                pattern_hypothesis = self.hypothesis.generate_from_pattern(similar)
"""

REEMPLAZAR_1D = """
            # Hipótesis solo cuando CPU < 40% y han pasado ≥ 60 s (no bloquea)
            pattern_hypothesis = self._hyp_scheduler.maybe_run(similar)
"""

# Y al final de observe(), reemplazar el bloque de mantenimiento:
BUSCAR_1D2 = """
        # Mantenimiento periódico — diferir si fatiga alta
        defer_consolidation = adaptations.get("consolidation_defer", False)

        if (self.interaction_count % self.consolidation_interval == 0
                and not defer_consolidation):
            n = self.consolidation.consolidate()
            if n > 0:
                result["_consolidated"] = n

        if self.interaction_count % self.forgetting_interval == 0:
            stats = self.forgetting.decay_cycle()
            result["_forgetting"] = stats
"""

REEMPLAZAR_1D2 = """
        # Mantenimiento en hilo de fondo — nunca bloquea observe()
        self._maintenance.tick(self.interaction_count)
"""

# ══════════════════════════════════════════════════════════════════════
# PARCHE 1 — cognia_v3.py
# Sección E: añadir índices SQLite en init_db()
# ══════════════════════════════════════════════════════════════════════
#
# Buscar en init_db(), justo ANTES de conn.commit():
BUSCAR_1E = """
    conn.commit()
    conn.close()
"""
# (hay varios conn.commit() — agregar SOLO en el de init_db(),
#  que es la función de inicialización de tablas)

REEMPLAZAR_1E = """
    # ── Índices para queries frecuentes ───────────────────────────────
    # Reducen O(n) → O(log n) con 10k+ episodios
    c.execute("CREATE INDEX IF NOT EXISTS idx_episodic_label "
              "ON episodic_memory(label, forgotten)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_episodic_timestamp "
              "ON episodic_memory(timestamp DESC) WHERE forgotten=0")
    c.execute("CREATE INDEX IF NOT EXISTS idx_semantic_concept "
              "ON semantic_memory(concept, confidence DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_kg_subject "
              "ON knowledge_graph(subject, weight DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_kg_object "
              "ON knowledge_graph(object, weight DESC)")
    conn.commit()
    conn.close()
"""

# ══════════════════════════════════════════════════════════════════════
# PARCHE 2 — respuestas_articuladas.py
# Ajustar contexto_trim dinámicamente según nivel de fatiga
# ══════════════════════════════════════════════════════════════════════
#
# BUSCAR (aprox. línea 430):
BUSCAR_2 = """
        contexto_trim = contexto[:1200] + (\"...\" if len(contexto) > 1200 else \"\")
        prompt = (f\"PREGUNTA: {pregunta[:400]}\\n\\n\"
                  f\"CONTEXTO DE MI MEMORIA:\\n{contexto_trim}{inv_nota}\\n\\n\"
                  \"Responde basandote en el contexto de forma natural.\")
"""

REEMPLAZAR_2 = """
        # Límite dinámico según nivel de fatiga/throttle
        _ctx_limit = 1200
        try:
            if hasattr(ai, "fatigue") and ai.fatigue:
                _adaps = ai.fatigue.get_adaptations()
                _mode  = _adaps.get("mode", "normal")
                _ctx_limit = {
                    "normal":   1200,
                    "moderate": 900,
                    "low":      600,
                    "critical": 400,
                }.get(_mode, 1200)
        except Exception:
            pass
        contexto_trim = contexto[:_ctx_limit] + ("..." if len(contexto) > _ctx_limit else "")
        prompt = (f"PREGUNTA: {pregunta[:400]}\\n\\n"
                  f"CONTEXTO DE MI MEMORIA:\\n{contexto_trim}{inv_nota}\\n\\n"
                  "Responde basandote en el contexto de forma natural.")
"""

# ══════════════════════════════════════════════════════════════════════
# PARCHE 3 — web_app.py
# ══════════════════════════════════════════════════════════════════════
#
# BUSCAR:
BUSCAR_3 = """
from curiosidad_pasiva import CuriosidadPasiva, register_routes_curiosidad
curiosidad = CuriosidadPasiva(get_cognia)
"""

REEMPLAZAR_3 = """
from curiosidad_adaptativa import AdaptiveCuriosity, register_routes_curiosidad
curiosidad = AdaptiveCuriosity(get_cognia)
"""

# ── Nota adicional: si web_app.py pasa 'intervalo=X' al constructor, ──
# AdaptiveCuriosity acepta ese parámetro (lo ignora silenciosamente por
# compatibilidad — ya no controla un sleep fijo).

# ══════════════════════════════════════════════════════════════════════
# PARCHE 4 — curiosidad_pasiva.py
# Agregar notify de actividad en observe() de cognia_v3.py
# ══════════════════════════════════════════════════════════════════════
#
# En Cognia.observe(), al inicio del método (después de self.interaction_count += 1):
AGREGAR_EN_OBSERVE = """
        # Notificar al scheduler de curiosidad que hay actividad
        if hasattr(self, "_curiosidad") and self._curiosidad is not None:
            try:
                self._curiosidad.notify_user_activity()
            except Exception:
                pass
"""
# Y en web_app.py, al crear curiosidad, asignarla al objeto ai:
# (o desde el getter de ai)
NOTA_WEB_APP = """
# Después de:
#   curiosidad = AdaptiveCuriosity(get_cognia)
#   curiosidad.iniciar()
#
# Agregar un hook para que cognia conozca el scheduler:
#   def _init_cognia_curiosidad():
#       ai = get_cognia()
#       if not hasattr(ai, "_curiosidad"):
#           ai._curiosidad = curiosidad
# Y llamarlo una vez después de que Cognia cargue.
"""
