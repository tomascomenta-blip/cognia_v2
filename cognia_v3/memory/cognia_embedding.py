"""
cognia_embedding.py — Sistema de embeddings optimizado para Cognia v3
======================================================================
Reemplaza el modelo cargado en import-time de cognia_v3.py con tres componentes:

  1. LazyEmbeddingModel   — carga all-MiniLM-L6-v2 solo en el primer uso real
  2. AsyncEmbeddingQueue  — agrupa llamadas de TODOS los hilos en batches (máx 16 textos
                            o 200 ms, lo que ocurra primero). Elimina la race condition
                            entre el hilo principal y CuriosidadPasiva.
  3. BoundedLRUCache      — reemplaza el dict _embedding_cache con eviction O(1) y lock.

INTEGRACIÓN EN cognia_v3.py
  1. Eliminar las líneas:
         _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
         _embedding_cache: Dict[str, list] = {}
         _CACHE_MAX = 512
  2. Agregar al inicio de cognia_v3.py (después de los imports estándar):
         from cognia_v3.memory.cognia_embedding import BoundedLRUCache, get_embedding_queue, text_to_vector_fast
         _embedding_cache = BoundedLRUCache(max_entries=512)
         # _embedding_queue se inicializa en Cognia.__init__() con:
         #   self._embedding_queue = get_embedding_queue(throttle_controller=self.fatigue)
  3. Reemplazar la función text_to_vector() de cognia_v3.py con la versión de este
     módulo (ver abajo) O importarla directamente:
         from cognia_v3.memory.cognia_embedding import text_to_vector_fast as text_to_vector
"""

from __future__ import annotations

import math
import threading
import time
import os
import zlib
from collections import OrderedDict
from typing import Optional, List

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def _has_semantic_backend() -> bool:
    """True si sentence-transformers es IMPORTABLE (aunque aun no este cargado).
    Distingue 'el modelo esta cargando' (hay que esperar) de 'no existe el
    paquete' (degradar a n-gramas es lo unico posible)."""
    try:
        import importlib.util
        return importlib.util.find_spec("sentence_transformers") is not None
    except Exception:
        return False


_HAS_SEMANTIC = _has_semantic_backend()


# ══════════════════════════════════════════════════════════════════════
# 1. LAZY MODEL — carga diferida + double-checked locking
# ══════════════════════════════════════════════════════════════════════

class LazyEmbeddingModel:
    """
    Carga SentenceTransformer('all-MiniLM-L6-v2') solo cuando se necesita
    por primera vez. Thread-safe mediante double-checked locking.

    Si el ThrottleController informa modo de bajo recurso, devuelve None
    para que la capa superior use el fallback de n-gramas.
    """
    _lock  = threading.Lock()
    _model = None
    _loaded = False          # flag separado para no hacer getattr costoso

    @classmethod
    def get(cls, throttle_controller=None):
        # Fast path: fallback n-gram si sistema bajo presión
        if throttle_controller is not None and _is_low_resource(throttle_controller):
            return None

        if not cls._loaded:
            with cls._lock:
                if not cls._loaded:
                    try:
                        from sentence_transformers import SentenceTransformer
                        cls._model = SentenceTransformer(
                            "all-MiniLM-L6-v2",
                            device="cpu"
                        )
                        print("[cognia_embedding] ✅ all-MiniLM-L6-v2 cargado (lazy)")
                    except ImportError:
                        cls._model = None
                        print("[cognia_embedding] ⚠️  sentence-transformers no disponible — usando n-gramas")
                    cls._loaded = True
        return cls._model


def _is_low_resource(tc) -> bool:
    """Lee el nivel del ThrottleController sin importar su estructura exacta."""
    try:
        level = getattr(tc, "level", None) or getattr(tc, "_level", None)
        return level in ("critical", "low")
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
# 2. ASYNC EMBEDDING QUEUE — batching multi-hilo
# ══════════════════════════════════════════════════════════════════════

class AsyncEmbeddingQueue:
    """
    Agrupa llamadas encode() de múltiples hilos (hilo principal + CuriosidadPasiva)
    en batches de hasta BATCH_SIZE textos o BATCH_TIMEOUT segundos.

    Resultado: un único forward-pass del modelo por batch en lugar de N llamadas
    secuenciales. Elimina la race condition sin necesidad de un lock global.

    Uso:
        queue = AsyncEmbeddingQueue(throttle_controller=fatigue_monitor)
        vector = queue.encode("Hola mundo")   # bloqueante, retorna list[float]
    """

    BATCH_SIZE    = 16
    BATCH_TIMEOUT = 0.20   # segundos
    # Espera extra cuando el timeout se debe a la CARGA del modelo (primer uso
    # en frio: ~10-30s). Sin esto, la PRIMERA query de cada proceso caia en
    # silencio al espacio n-gram mientras el 96.8% del corpus esta en el
    # espacio MiniLM -> top-k basura (0.32 vs 0.711 medido en la auditoria).
    COLD_LOAD_TIMEOUT = 60.0

    def __init__(self, throttle_controller=None, vector_dim: int = 384):
        self._throttle  = throttle_controller
        self._dim       = vector_dim
        self._pending: dict[str, threading.Event] = {}
        self._results:  dict[str, list]           = {}
        self._queue:    list[str]                 = []
        self._lock      = threading.Lock()
        self._trigger   = threading.Event()
        self._worker    = threading.Thread(
            target=self._run, daemon=True, name="EmbeddingBatcher"
        )
        self._worker.start()

    # ── API pública ────────────────────────────────────────────────────

    def encode(self, text: str) -> list:
        """
        Encola el texto y bloquea hasta que el batch worker lo procese.
        Timeout de seguridad de 5s — si expira, retorna fallback n-gram.
        """
        key = text[:200]

        event = threading.Event()
        with self._lock:
            # Si ya está en cola (mismo texto pedido simultáneamente) reutilizar
            if key not in self._pending:
                self._pending[key] = event
                self._queue.append(key)
            else:
                event = self._pending[key]   # esperar al mismo evento
        self._trigger.set()

        if not event.wait(timeout=5.0):
            # Timeout: distinguir "modelo CARGANDO" (esperar) de "colgado/ausente"
            # (degradar, pero NUNCA en silencio: el vector n-gram vive en otro
            # espacio vectorial y envenena el retrieval).
            if _HAS_SEMANTIC and not LazyEmbeddingModel._loaded:
                if not event.wait(timeout=self.COLD_LOAD_TIMEOUT):
                    print("[cognia_embedding] AVISO: modelo semantico no cargo en "
                          f"{self.COLD_LOAD_TIMEOUT:.0f}s -- vector n-gram degradado "
                          f"para '{key[:40]}...'")
                    return _ngram_vector(key, self._dim)
            else:
                print("[cognia_embedding] AVISO: timeout de encode (5s) sin modelo "
                      f"semantico -- vector n-gram degradado para '{key[:40]}...'")
                return _ngram_vector(key, self._dim)

        result = self._results.pop(key, None)
        if result is None:
            print(f"[cognia_embedding] AVISO: sin resultado del batcher para "
                  f"'{key[:40]}...' -- vector n-gram degradado")
            return _ngram_vector(key, self._dim)
        return result

    # ── Worker interno ─────────────────────────────────────────────────

    def _run(self):
        while True:
            self._trigger.wait(timeout=self.BATCH_TIMEOUT)
            # FIX: _trigger.clear() dentro del lock para evitar race condition
            # donde otro hilo setea el trigger justo después del clear y antes del lock
            with self._lock:
                self._trigger.clear()
                batch = self._queue[:self.BATCH_SIZE]
                self._queue = self._queue[self.BATCH_SIZE:]

            if not batch:
                continue

            model = LazyEmbeddingModel.get(self._throttle)

            if model is None:
                # Fallback n-gram para todo el batch
                for key in batch:
                    self._results[key] = _ngram_vector(key, self._dim)
                    self._pending.pop(key, threading.Event()).set()
                continue

            try:
                vecs = model.encode(
                    batch,
                    normalize_embeddings=True,
                    batch_size=self.BATCH_SIZE,
                    show_progress_bar=False,
                ).tolist()
                for key, vec in zip(batch, vecs):
                    self._results[key] = vec
                    self._pending.pop(key, threading.Event()).set()
            except Exception as exc:
                print(f"[EmbeddingBatcher] Error en encode: {exc} — usando n-gramas")
                for key in batch:
                    self._results[key] = _ngram_vector(key, self._dim)
                    self._pending.pop(key, threading.Event()).set()


# ══════════════════════════════════════════════════════════════════════
# 3. BOUNDED LRU CACHE — thread-safe, eviction O(1)
# ══════════════════════════════════════════════════════════════════════

class BoundedLRUCache:
    """
    Reemplaza el dict _embedding_cache de cognia_v3.py.

    Mejoras sobre la implementación original:
      - Lock de threading → sin race conditions entre hilos
      - OrderedDict + popitem(last=False) → eviction O(1) en lugar de O(n)
      - shrink_if_pressured() → libera 25% de entradas si RAM > umbral
    """

    def __init__(self, max_entries: int = 512):
        self._cache  = OrderedDict()
        self._max    = max_entries
        self._lock   = threading.Lock()

    def get(self, key: str) -> Optional[list]:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)      # LRU: marcar como reciente
            return self._cache[key]

    def set(self, key: str, value: list) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            if len(self._cache) > self._max:
                self._cache.popitem(last=False)   # O(1): eliminar el más antiguo

    def shrink_if_pressured(self, threshold_pct: int = 85) -> int:
        """Libera ~25% de entradas si la RAM del sistema supera el umbral."""
        if not HAS_PSUTIL:
            return 0
        if psutil.virtual_memory().percent <= threshold_pct:
            return 0
        evicted = 0
        with self._lock:
            to_remove = max(1, len(self._cache) // 4)
            for _ in range(to_remove):
                if self._cache:
                    self._cache.popitem(last=False)
                    evicted += 1
        return evicted

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


# ══════════════════════════════════════════════════════════════════════
# 4. SINGLETON DEL QUEUE — una instancia para todo el proceso
# ══════════════════════════════════════════════════════════════════════

_global_queue: Optional[AsyncEmbeddingQueue] = None
_global_queue_lock = threading.Lock()

def get_embedding_queue(throttle_controller=None, vector_dim: int = 384) -> AsyncEmbeddingQueue:
    """
    Retorna (o crea) el singleton del AsyncEmbeddingQueue.
    Llamar desde Cognia.__init__() para pasar el ThrottleController real.
    """
    global _global_queue
    if _global_queue is None:
        with _global_queue_lock:
            if _global_queue is None:
                _global_queue = AsyncEmbeddingQueue(
                    throttle_controller=throttle_controller,
                    vector_dim=vector_dim,
                )
                print("[cognia_embedding] ✅ AsyncEmbeddingQueue iniciado")
    return _global_queue


def warm_up_embedding_model(throttle_controller=None) -> None:
    """
    Dispara la carga del modelo semantico en un hilo daemon.
    Llamar desde Cognia.__init__: asi la carga (~10-30s en frio) ocurre en
    paralelo al arranque y la primera query del usuario ya encuentra el
    modelo listo en vez de degradar a n-gramas por timeout.
    """
    if not _HAS_SEMANTIC:
        return
    threading.Thread(
        target=lambda: LazyEmbeddingModel.get(throttle_controller),
        daemon=True, name="EmbeddingWarmup",
    ).start()


# ══════════════════════════════════════════════════════════════════════
# 5. FALLBACK N-GRAM (sin dependencias externas)
# ══════════════════════════════════════════════════════════════════════

def _stable_hash(s: str) -> int:
    """Hash ESTABLE entre procesos. hash() de Python esta aleatorizado por
    PYTHONHASHSEED: el mismo texto producia vectores n-gram distintos en cada
    sesion (cos(guardado, mismo texto) = 0.559 medido, deberia ser 1.0)."""
    return zlib.crc32(s.encode("utf-8", "ignore"))


def _ngram_vector(text: str, dim: int = 384) -> list:
    """
    Vector de n-gramas de caracteres. Igual al fallback de cognia_v3.py
    pero aceptando dim como parámetro.
    """
    vec = [0.0] * dim
    text_lower = text.lower().strip()
    for i, ch in enumerate(text_lower):
        idx = (ord(ch) * 31 + i) % dim
        vec[idx] += 1.0
    for i in range(len(text_lower) - 1):
        h = _stable_hash(text_lower[i:i+2]) % dim
        vec[h] += 0.7
    for word in text_lower.split():
        h = _stable_hash(word) % dim
        vec[h] += 1.5
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


# ══════════════════════════════════════════════════════════════════════
# 6. text_to_vector_fast — reemplazo directo de cognia_v3.text_to_vector
# ══════════════════════════════════════════════════════════════════════

# Cache global (se puede compartir con cognia_v3.py o reemplazarlo)
_embedding_cache = BoundedLRUCache(max_entries=512)


def text_to_vector_fast(
    text: str,
    dim: int = 384,
    fatigue_monitor=None,
) -> list:
    """
    Versión optimizada de text_to_vector():
      - Usa BoundedLRUCache (thread-safe, O(1) eviction)
      - Delega al AsyncEmbeddingQueue (batching, thread-safe)
      - Compatible con la firma original: retorna list[float]

    Para reemplazar en cognia_v3.py:
        from cognia_v3.memory.cognia_embedding import text_to_vector_fast as text_to_vector
    """
    key = text[:200]

    # Cache hit
    cached = _embedding_cache.get(key)
    if cached is not None:
        if fatigue_monitor is not None:
            try:
                fatigue_monitor.record_embedding_cached()
            except Exception:
                pass
        return cached

    # Cache miss — usar el queue async (batch + lazy model)
    queue = get_embedding_queue(vector_dim=dim)
    vec   = queue.encode(text)

    if fatigue_monitor is not None:
        try:
            fatigue_monitor.record_embedding_computed()
        except Exception:
            pass

    _embedding_cache.set(key, vec)

    # Oportunidad de liberar memoria si hay presión
    _embedding_cache.shrink_if_pressured()

    return vec
