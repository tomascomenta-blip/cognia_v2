"""
knowledge_integrator.py — Integrador de conocimiento investigado en Cognia.

Toma los resultados de researcher.py y los escribe de forma controlada
en las estructuras de conocimiento de Cognia:

  - Knowledge Graph (KG): añade triples sujeto-predicado-objeto
  - Memoria semántica: refuerza o crea conceptos clave
  - Hypotheses: si la investigación resuelve una contradicción, registra la resolución

PRINCIPIOS DE ESCRITURA CONTROLADA:
  - Confianza siempre menor que conocimiento aprendido por observación directa
  - Máximo de triples KG por sesión para evitar inundación
  - Nunca sobreescribe conocimiento existente de alta confianza
  - Registra todo en research_log para trazabilidad
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional

from .researcher import ResearchResult

# ── Configuración ──────────────────────────────────────────────────────────────

# Confianza máxima que puede tener conocimiento de investigación
# (el aprendizaje por observación directa puede llegar a 1.0)
MAX_RESEARCH_CONFIDENCE = 0.70

# Máximo de triples KG añadidos por resultado de investigación
MAX_KG_TRIPLES_PER_RESULT = 5

# Máximo de conceptos semánticos reforzados por resultado
MAX_CONCEPTS_PER_RESULT = 4

# Fuente tag para trazabilidad
SOURCE_TAG = "research_engine"


# ── Dataclass de resultado ─────────────────────────────────────────────────────

class IntegrationResult:
    """Resultado de integrar un ResearchResult en la memoria de Cognia."""
    def __init__(self):
        self.triples_added:    int  = 0
        self.concepts_touched: int  = 0
        self.hypothesis_id:    Optional[int] = None
        self.skipped:          bool = False
        self.reason:           str  = ""

    def __repr__(self):
        return (f"IntegrationResult(triples={self.triples_added}, "
                f"concepts={self.concepts_touched}, skipped={self.skipped})")


# ── Utilidades de base de datos ────────────────────────────────────────────────

def _db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.text_factory = str
    return conn


def _ensure_research_log(db_path: str):
    """Crea la tabla de log de investigaciones si no existe."""
    conn = _db(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS research_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT NOT NULL,
            proposal_id     INTEGER,
            question        TEXT,
            topic           TEXT,
            answer          TEXT,
            triples_added   INTEGER DEFAULT 0,
            concepts_touched INTEGER DEFAULT 0,
            confidence      REAL
        )
    """)
    conn.commit()
    conn.close()


def _log_research(db_path: str, result: ResearchResult,
                   integration: IntegrationResult):
    """Registra la investigación en research_log para trazabilidad."""
    try:
        conn = _db(db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO research_log
            (timestamp, proposal_id, question, topic, answer,
             triples_added, concepts_touched, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            result.proposal_id,
            result.question,
            result.topic,
            result.answer,
            integration.triples_added,
            integration.concepts_touched,
            result.confidence,
        ))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[integrator] Log error (no crítico): {exc}")


# ── Escritura al Knowledge Graph ───────────────────────────────────────────────

def _add_to_kg(kg, relations: list, confidence: float) -> int:
    """
    Añade triples al Knowledge Graph de Cognia.
    Usa el método add_triple() existente del KG.

    Args:
        kg        : instancia de KnowledgeGraph de Cognia
        relations : lista de tuplas (sujeto, predicado, objeto)
        confidence: confianza base para los triples

    Returns:
        Número de triples efectivamente añadidos.
    """
    added = 0
    limited = relations[:MAX_KG_TRIPLES_PER_RESULT]

    for subj, pred, obj in limited:
        # Normalizar strings
        subj = subj.strip().lower()[:80]
        pred = pred.strip().lower()[:60]
        obj  = obj.strip().lower()[:80]

        if not subj or not pred or not obj:
            continue

        try:
            kg.add_triple(
                subject=subj,
                predicate=pred,
                obj=obj,
                confidence=min(confidence, MAX_RESEARCH_CONFIDENCE),
                source=SOURCE_TAG,
            )
            added += 1
        except Exception as exc:
            print(f"[integrator] KG triple error: {exc}")

    return added


# ── Escritura a memoria semántica ──────────────────────────────────────────────

def _reinforce_concepts(semantic_mem, key_concepts: list,
                         topic: str, answer: str,
                         confidence: float) -> int:
    """
    Refuerza o crea conceptos clave en la memoria semántica.

    Estrategia conservadora:
    - Si el concepto YA existe: solo actualiza description si era vacía
    - Si NO existe: lo crea con confianza baja (marcado como aprendido via investigación)
    - Nunca reduce la confianza de un concepto existente
    """
    touched = 0
    zero_vector = [0.0] * 384   # Vector neutro — sin embedding real

    # Incluir el topic como concepto principal
    all_concepts = ([topic] if topic else []) + key_concepts
    limited = all_concepts[:MAX_CONCEPTS_PER_RESULT]

    for concept in limited:
        concept = concept.strip().lower()[:80]
        if not concept or len(concept) < 3:
            continue

        try:
            existing = semantic_mem.get_concept(concept)

            if existing:
                # Concepto existe — solo añadimos descripción si no tenía
                if not existing.get("description") and answer:
                    conn = _db(semantic_mem.db)
                    c = conn.cursor()
                    c.execute(
                        "UPDATE semantic_memory SET description=? WHERE concept=?",
                        (answer[:200], concept)
                    )
                    conn.commit()
                    conn.close()
                    touched += 1
            else:
                # Concepto nuevo — crearlo con confianza conservadora
                semantic_mem.update_concept(
                    concept=concept,
                    vector=zero_vector,
                    description=answer[:200] if concept == topic else "",
                    confidence_delta=min(confidence, MAX_RESEARCH_CONFIDENCE) - 0.5,
                )
                touched += 1

        except Exception as exc:
            print(f"[integrator] Semantic concept error ({concept}): {exc}")

    return touched


# ── Registro de hipótesis de resolución ───────────────────────────────────────

def _register_resolution_hypothesis(db_path: str, result: ResearchResult) -> Optional[int]:
    """
    Si la investigación fue sobre una contradicción, registra la resolución
    como una hipótesis en la tabla de hypotheses.
    Solo se llama cuando question_type == 'contradiction'.
    """
    if result.question_type != "contradiction":
        return None

    try:
        conn = _db(db_path)
        c = conn.cursor()
        hypothesis_text = (
            f"[Resolución investigada] Sobre '{result.topic}': {result.answer}"
        )
        c.execute(
            "INSERT INTO hypotheses (hypothesis, confidence, created_at) VALUES (?, ?, ?)",
            (hypothesis_text, result.confidence * 0.8, datetime.now().isoformat())
        )
        hyp_id = c.lastrowid
        conn.commit()
        conn.close()
        return hyp_id
    except Exception as exc:
        print(f"[integrator] Hypothesis registration error: {exc}")
        return None


# ── API pública ────────────────────────────────────────────────────────────────

def integrate_research(
    result:       ResearchResult,
    cognia_instance,
    db_path:      str,
) -> IntegrationResult:
    """
    Integra los hallazgos de una investigación en la memoria de Cognia.

    Escribe en:
      - cognia.kg          → triples de relaciones encontradas
      - cognia.semantic    → conceptos clave reforzados
      - hypotheses table   → si resuelve una contradicción

    Nunca toca:
      - working_memory
      - episodic_memory (no añade episodios de aprendizaje)
      - curiosity_proposals (eso lo hace el research_orchestrator)

    Args:
        result           : ResearchResult de researcher.py
        cognia_instance  : Instancia de Cognia para acceder a kg y semantic
        db_path          : Path a la base de datos

    Returns:
        IntegrationResult con estadísticas de lo que se escribió.
    """
    integration = IntegrationResult()

    _ensure_research_log(db_path)

    if not result or not result.success:
        integration.skipped = True
        integration.reason  = "research result was unsuccessful"
        return integration

    # ── Añadir al Knowledge Graph ──────────────────────────────────────
    if result.relations and hasattr(cognia_instance, "kg"):
        try:
            integration.triples_added = _add_to_kg(
                cognia_instance.kg,
                result.relations,
                result.confidence,
            )
        except Exception as exc:
            print(f"[integrator] KG integration error: {exc}")

    # ── Reforzar memoria semántica ─────────────────────────────────────
    if result.key_concepts and hasattr(cognia_instance, "semantic"):
        try:
            integration.concepts_touched = _reinforce_concepts(
                cognia_instance.semantic,
                result.key_concepts,
                result.topic,
                result.answer,
                result.confidence,
            )
        except Exception as exc:
            print(f"[integrator] Semantic integration error: {exc}")

    # ── Registrar hipótesis de resolución (solo contradicciones) ───────
    if result.question_type == "contradiction":
        integration.hypothesis_id = _register_resolution_hypothesis(db_path, result)

    # ── Log de trazabilidad ────────────────────────────────────────────
    _log_research(db_path, result, integration)

    print(f"[integrator] 📥 Integrado: +{integration.triples_added} triples KG, "
          f"+{integration.concepts_touched} conceptos semánticos")

    return integration


def get_research_log(db_path: str, limit: int = 20) -> list:
    """
    Retorna el historial de investigaciones realizadas.
    Útil para introspección y monitoreo.
    """
    _ensure_research_log(db_path)
    try:
        conn = _db(db_path)
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, question, topic, triples_added,
                   concepts_touched, confidence
            FROM research_log
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        conn.close()
        return [
            {
                "timestamp":       r[0],
                "question":        r[1],
                "topic":           r[2],
                "triples_added":   r[3],
                "concepts_touched": r[4],
                "confidence":      r[5],
            }
            for r in rows
        ]
    except Exception:
        return []
