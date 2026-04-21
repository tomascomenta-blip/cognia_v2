"""
cognia/config.py
================
Constantes globales, rutas, e imports opcionales compartidos.
"""

import importlib.util

# ── Base de datos ──────────────────────────────────────────────────────
DB_PATH = "cognia_memory.db"

# ── Monitor de fatiga cognitiva ────────────────────────────────────────
try:
    from fatiga_cognitiva import get_fatigue_monitor, CognitiveFatigueMonitor
    _FATIGUE_MONITOR = get_fatigue_monitor()
    HAS_FATIGUE = True
except ImportError:
    HAS_FATIGUE = False
    _FATIGUE_MONITOR = None
    print("⚠️  fatiga_cognitiva.py no encontrado — sin monitor de fatiga")

NORMAL_CYCLE_MS_ENERGY = 80.0  # ref para normalizar energy_estimate

# ── Módulos opcionales ────────────────────────────────────────────────
try:
    from cognia_modules_adicionales import ReasoningPlanner
    HAS_PLANNER = True
except ImportError:
    HAS_PLANNER = False
    ReasoningPlanner = None
    print("⚠️  ReasoningPlanner no disponible")

try:
    from curiosity_engine import CuriosityEngine as ActiveCuriosityEngine
    HAS_CURIOSITY_ENGINE = True
except ImportError:
    HAS_CURIOSITY_ENGINE = False
    ActiveCuriosityEngine = None
    print("⚠️  CuriosityEngine no disponible")

try:
    from language_engine import get_language_engine
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
from cognia_embedding import (
    LazyEmbeddingModel, BoundedLRUCache,
    get_embedding_queue, text_to_vector_fast, _ngram_vector,
)

HAS_SEMANTIC = importlib.util.find_spec("sentence_transformers") is not None
VECTOR_DIM   = 384 if HAS_SEMANTIC else 64

if HAS_SEMANTIC:
    print("✅ sentence-transformers detectado (se cargará en primer uso)")
else:
    print("⚠️  sentence-transformers no encontrado. Usando n-gramas.")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("⚠️  numpy no encontrado. Clustering básico disponible.")

try:
    import networkx as nx
    HAS_NETWORKX = True
    print("✅ networkx cargado (knowledge graph activo)")
except ImportError:
    HAS_NETWORKX = False
    print("⚠️  networkx no encontrado. Instala con: pip install networkx")

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
