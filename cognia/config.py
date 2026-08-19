"""
cognia/config.py
================
Constantes globales, rutas, e imports opcionales compartidos.
"""

import importlib.util
import os
from pathlib import Path

# Los avisos de import-time van al logger, no a print(): `import cognia` no
# debe ensuciar stdout (2026-08-09; antes imprimia 3-4 lineas [OK]/[WARN] en
# cada import, incluidas las corridas de pytest y el remoto). Lo sano es
# DEBUG (al archivo); la degradacion real (dependencia faltante) es WARNING.
from .logger_config import get_logger
logger = get_logger(__name__)

# ── Base de datos ──────────────────────────────────────────────────────
# Absolute path so the DB is the same regardless of working directory.
# Respects COGNIA_DB_PATH env var for custom installations.
_DB_DIR = Path(os.environ.get("COGNIA_DB_PATH", Path.home() / ".cognia"))
_DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(_DB_DIR / "cognia_memory.db")

# ── Monitor de fatiga cognitiva ────────────────────────────────────────
try:
    from .fatiga_cognitiva import get_fatigue_monitor, CognitiveFatigueMonitor
    _FATIGUE_MONITOR = get_fatigue_monitor()
    HAS_FATIGUE = True
except ImportError:
    HAS_FATIGUE = False
    _FATIGUE_MONITOR = None
    logger.warning("fatiga_cognitiva.py no encontrado - sin monitor de fatiga")

NORMAL_CYCLE_MS_ENERGY = 80.0  # ref para normalizar energy_estimate

# ── Módulos opcionales ────────────────────────────────────────────────
try:
    from cognia_v3.core.cognia_modules_adicionales import ReasoningPlanner
    HAS_PLANNER = True
except ImportError:
    HAS_PLANNER = False
    ReasoningPlanner = None
    logger.warning("ReasoningPlanner no disponible")

try:
    from cognia_v3.core.curiosity_engine import CuriosityEngine as ActiveCuriosityEngine
    HAS_CURIOSITY_ENGINE = True
except ImportError:
    HAS_CURIOSITY_ENGINE = False
    ActiveCuriosityEngine = None
    logger.warning("CuriosityEngine no disponible")

try:
    from .language_engine import get_language_engine
    HAS_LANGUAGE_ENGINE = True
except ImportError:
    HAS_LANGUAGE_ENGINE = False

try:
    from cognia.research_engine import run_research_session, format_sleep_summary
    HAS_RESEARCH_ENGINE = True
except ImportError:
    HAS_RESEARCH_ENGINE = False

try:
    from cognia.program_creator import maybe_run_hobby, show_library, get_session_stats
    HAS_PROGRAM_CREATOR = True
except ImportError:
    HAS_PROGRAM_CREATOR = False

# ── Dependencias de embeddings ────────────────────────────────────────
from .cognia_embedding import (
    LazyEmbeddingModel, BoundedLRUCache,
    get_embedding_queue, text_to_vector_fast, _ngram_vector,
)

HAS_SEMANTIC = importlib.util.find_spec("sentence_transformers") is not None
# VECTOR_DIM is FIXED at 384 whether or not sentence-transformers is installed.
# all-MiniLM-L6-v2 produces 384-dim vectors, and the n-gram fallback
# (_ngram_vector) takes an arbitrary dim, so 384 works for both backends.
# Historically this was `384 if HAS_SEMANTIC else 64`, which meant uninstalling
# sentence-transformers silently flipped new vectors (and queries) to dim 64
# while the DB still held 384-dim vectors. The VectorCache builds on the
# dominant dim (384), so 64-dim queries hit `(N,384) @ (64,)` -> matmul crash
# -> 6s slow-path fallback on every search. Pinning to 384 keeps queries and
# stored vectors dimensionally consistent across the ST-installed/uninstalled
# boundary. See scripts/migrate_vector_dim.py to re-embed any legacy 64-dim rows.
VECTOR_DIM   = 384

# DEGRADADOS DEL ARRANQUE (2026-08-18). Antes esto eran logger.warning() en el
# cuerpo del modulo, y como cli.py importa .config en su linea 22, el usuario
# veia dos lineas amarillas con formato de servidor ("WARNING cognia.config:
# ...") colgando ENCIMA del banner, en cada sesion, para siempre. Un aviso que
# no puedes accionar y que ademas ensucia la primera pantalla no es informacion:
# es ruido. Ahora se REGISTRAN y quien quiera los muestra donde corresponde
# (`cognia doctor`, /doctor, o COGNIA_DEBUG=1), en vez de imponerse a todos.
_DEGRADADOS: list = []


def registrar_degradado(que: str, efecto: str, arreglo: str = "") -> None:
    """Anota una capacidad ausente sin escribir en la pantalla del usuario."""
    _DEGRADADOS.append({"que": que, "efecto": efecto, "arreglo": arreglo})
    logger.debug("degradado: %s -> %s (%s)", que, efecto, arreglo or "sin arreglo")


def degradados() -> list:
    """Lo que falta y en que se nota. Lo consume el doctor, no el arranque."""
    return list(_DEGRADADOS)


if HAS_SEMANTIC:
    logger.debug("sentence-transformers detectado (se cargara en primer uso)")
else:
    registrar_degradado("sentence-transformers",
                        "la busqueda semantica cae a n-gramas",
                        "pip install sentence-transformers")

# PORQUE find_spec: el simbolo `np` NO se usaba en este modulo y HAS_NUMPY no
# tiene ningun consumidor en todo el repo (grep 2026-07-23), asi que el import
# era 49ms de arranque puros de deuda. Se conserva la constante por compatibilidad
# con codigo externo. Los modulos que SI usan numpy (memory/episodic_fast.py,
# memory/semantic_search.py, semantic_cache.py) lo importan por su cuenta.
HAS_NUMPY = importlib.util.find_spec("numpy") is not None
if not HAS_NUMPY:
    registrar_degradado("numpy", "solo clustering basico", "pip install numpy")

# PORQUE find_spec y no `import networkx`: importar networkx aca costaba 110ms
# de los 436ms de `import cognia` (medido con -X importtime en la maquina del
# dueno; en el i3-10110U el factor es ~3x). Nadie usa el simbolo `nx` desde
# config: el unico consumidor es cognia/knowledge/graph.py, que ahora lo
# importa dentro de las dos funciones que lo necesitan (_get_graph y
# find_path). find_spec solo mira el sys.path, no ejecuta el paquete, asi que
# HAS_NETWORKX sigue significando exactamente lo mismo.
HAS_NETWORKX = importlib.util.find_spec("networkx") is not None
if HAS_NETWORKX:
    logger.debug("networkx cargado (knowledge graph activo)")
else:
    registrar_degradado("networkx", "el grafo de conocimiento queda inactivo",
                        "pip install networkx")

# ── Cache de embeddings ───────────────────────────────────────────────
_embedding_cache = BoundedLRUCache(max_entries=512)

# ── Palabras de emoción ───────────────────────────────────────────────
POSITIVE_WORDS = {
    "bueno","bien","excelente","genial","perfecto","correcto","sí","yes","true",
    "positivo","feliz","amor","gran","mejor","éxito","logro","fácil","claro",
    "útil","importante","interesante","nuevo","bonito","alegre","seguro",
    "good","great","excellent","perfect","correct","happy","love","success","easy"
}
NEGATIVE_WORDS = {
    "malo","mal","terrible","error","incorrecto","no","false","negativo","triste",
    "difícil","complicado","problema","fallo","equivocado","peligro","riesgo",
    "bad","wrong","terrible","error","incorrect","sad","fail","difficult","danger"
}

# ── Stopwords para el Knowledge Graph ────────────────────────────────
KG_STOPWORDS = {
    "el","la","los","las","un","una","unos","unas","de","del","al","en",
    "que","con","por","para","como","pero","más","este","esta","estos",
    "estas","son","fue","ser","está","tiene","han","hay","cuando","donde",
    "cual","cuyo","entre","desde","hasta","sobre","bajo","sus","les","nos",
    "ellos","ellas","también","solo","así","si","no","ni","ya","aunque",
    "porque","pues","luego","antes","después","mientras","según","sin",
    "the","a","an","of","to","in","is","are","was","were","it","and",
    "or","but","for","at","by","with","from","not","be","been","has",
    "have","had","its","their","they","this","that","these","those",
}
