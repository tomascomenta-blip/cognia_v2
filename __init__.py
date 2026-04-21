"""
cognia/__init__.py
==================
Paquete Cognia v3 — Arquitectura Cognitiva Híbrida.

Uso rápido:
    from cognia import Cognia
    ai = Cognia()
    ai.process("el cielo es azul")
    ai.learn("los perros ladran", "perro")

Uso del REPL:
    python -m cognia
"""

from .cognia import Cognia
from .database import db_connect, init_db
from .vectors import cosine_similarity, text_to_vector, analyze_emotion
from .config import DB_PATH, VECTOR_DIM

# Módulos individuales accesibles si se necesitan
from .memory import (
    EpisodicMemory, SemanticMemory, WorkingMemory, PerceptionModule,
    ChatHistory, UserProfile, ForgettingModule, ConsolidationModule,
)
from .reasoning import (
    ContradictionDetector, WorldModelModule, HypothesisModule,
    MetacognitionModule, EvaluationModule, CuriosityModule,
)
from .knowledge import KnowledgeGraph, InferenceEngine, TemporalMemory, GoalSystem
from .attention import AttentionSystem
from .compression import ConceptCompressor, GraphEpisodicBridge

__version__ = "3.2.0"
__all__ = [
    "Cognia",
    # DB
    "db_connect", "init_db", "DB_PATH", "VECTOR_DIM",
    # Vectores
    "cosine_similarity", "text_to_vector", "analyze_emotion",
    # Memoria
    "EpisodicMemory", "SemanticMemory", "WorkingMemory", "PerceptionModule",
    "ChatHistory", "UserProfile", "ForgettingModule", "ConsolidationModule",
    # Razonamiento
    "ContradictionDetector", "WorldModelModule", "HypothesisModule",
    "MetacognitionModule", "EvaluationModule", "CuriosityModule",
    # Conocimiento
    "KnowledgeGraph", "InferenceEngine", "TemporalMemory", "GoalSystem",
    # Atención y compresión
    "AttentionSystem", "ConceptCompressor", "GraphEpisodicBridge",
]
