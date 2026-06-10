"""
cognia_v3 — paquete de la arquitectura cognitiva v3.

Estructura (ver AUDIT.md / ARCHITECTURE.md):
  core/        KnowledgeGraph, InferenceEngine, GoalSystem, fatiga, curiosidad, logging
  memory/      EpisodicMemory ext., consolidación, conversación, embeddings
  interfaces/  LanguageEngine, DecisionGate, TeacherInterface, ejecución de código
  training/    DatasetGen, QLoRA, SDPC
  eval/        baseline y experimentos

Compat: `from cognia_v3 import Cognia` (y cualquier símbolo del módulo principal)
sigue funcionando vía __getattr__ lazy — delega en cognia_v3.core.cognia_v3 sin
pagar el costo de import si nadie lo pide.
"""
__version__ = "3.0.0"


def __getattr__(name):
    # PEP 562: re-export lazy del módulo principal (clase Cognia, helpers, etc.)
    if name.startswith("_"):
        raise AttributeError(f"module 'cognia_v3' has no attribute {name!r}")
    from cognia_v3.core import cognia_v3 as _core
    return getattr(_core, name)
