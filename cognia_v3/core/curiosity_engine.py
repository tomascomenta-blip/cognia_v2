"""
curiosity_engine.py — Motor de Curiosidad para COGNIA v1
=========================================================
Módulo autónomo de exploración epistémica.

PROPÓSITO:
    Permite a Cognia seleccionar activamente temas para explorar durante ciclos
    de aprendizaje pasivo, priorizando aquellos que:
      - Reducen incertidumbre
      - Mejoran zonas débiles del grafo de conocimiento
      - Explican contradicciones
      - Conectan conceptos aislados

DISEÑO INVARIANTE:
    El motor PROPONE preguntas, el humano (o el sistema principal) DECIDE
    si iniciar ciclos de exploración. Nunca ejecuta búsquedas externas
    por sí mismo.

ARQUITECTURA:
    CuriosityScorer    — calcula puntuación de curiosidad por par conceptual
    KnowledgeGapFinder — detecta zonas débiles en el grafo semántico
    ContradictionHunter— encuentra pares de conceptos con creencias opuestas
    BridgeSeeker       — busca conceptos que podrían conectar clusters aislados
    QuestionGenerator  — formula preguntas en lenguaje natural
    CuriosityEngine    — orquesta todo y expone la API pública

FÓRMULA DE CURIOSIDAD:
    score = w_uncertainty * uncertainty
          + w_novelty     * novelty
          + w_gap         * knowledge_gap
          + w_hypothesis  * hypothesis_potential

CONSUMO ENERGÉTICO:
    Sólo SQL — sin embeddings durante la fase de scoring.
    Embeddings opcionales sólo para generate_deep_questions().
    Latencia típica: 15–60ms en laptop.
"""

import sqlite3
import math
import json
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# ══════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════

CURIOSITY_DB_PATH = "cognia_memory.db"

# Pesos de la fórmula de curiosidad (deben sumar 1.0)
CURIOSITY_WEIGHTS = {
    "uncertainty":          0.30,  # conceptos con baja confianza
    "novelty":              0.25,  # conceptos no explorados recientemente
    "knowledge_gap":        0.25,  # conceptos con pocas conexiones en KG
    "hypothesis_potential": 0.20,  # pares que podrían generar hipótesis
}

# Umbrales
MIN_CURIOSITY_SCORE   = 0.35   # score mínimo para incluir en propuestas
MAX_QUESTIONS_PER_RUN = 5      # máximo de preguntas generadas por ciclo
MIN_CONCEPTS_FOR_RUN  = 5      # mínimo de conceptos para activar el motor
RECENCY_WINDOW_HOURS  = 48     # ventana para definir "explorado recientemente"
MIN_CONTRADICTION_AGE = 2      # mínimo de días para considerar contradicción "crónica"


def db_connect(path: str = CURIOSITY_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.text_factory = str
    return conn


# ══════════════════════════════════════════════════════════════════════
# 1. KNOWLEDGE GAP FINDER — detecta conceptos con pocas conexiones
# ══════════════════════════════════════════════════════════════════════

class KnowledgeGapFinder:
    """
    Encuentra conceptos semánticos con pocas aristas en el Knowledge Graph.
    Un concepto aislado representa un "agujero" en el conocimiento del sistema.
    """

    def __init__(self, db_path: str = CURIOSITY_DB_PATH):
        self.db = db_path

    def find_isolated_concepts(self, top_k: int = 20) -> List[Dict]:
        """
        Retorna conceptos ordenados de menor a mayor conectividad en el KG.
        Incluye metadatos de confianza y soporte para el scorer.
        """
        conn = db_connect(self.db)
        c = conn.cursor()

        try:
            c.execute("""
                SELECT
                    sm.concept,
                    sm.confidence,
                    sm.support,
                    COALESCE(kg_out.out_degree, 0) AS out_degree,
                    COALESCE(kg_in.in_degree, 0)  AS in_degree,
                    sm.updated_at
                FROM semantic_memory sm
                LEFT JOIN (
                    SELECT subject, COUNT(*) as out_degree
                    FROM knowledge_graph GROUP BY subject
                ) kg_out ON sm.concept = kg_out.subject
                LEFT JOIN (
                    SELECT object, COUNT(*) as in_degree
                    FROM knowledge_graph GROUP BY object
                ) kg_in ON sm.concept = kg_in.object
                WHERE sm.confidence > 0.1
                ORDER BY (COALESCE(kg_out.out_degree,0) + COALESCE(kg_in.in_degree,0)) ASC,
                         sm.support DESC
                LIMIT ?
            """, (top_k,))
            rows = c.fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        results = []
        for row in rows:
            concept, confidence, support, out_deg, in_deg, updated_at = row
            results.append({
                "concept":    concept,
                "confidence": confidence or 0.0,
                "support":    support or 0,
                "degree":     (out_deg or 0) + (in_deg or 0),
                "updated_at": updated_at,
            })
        return results

    def find_bridge_candidates(self, top_k: int = 10) -> List[Tuple[str, str, float]]:
        """
        Encuentra pares de conceptos que pertenecen a clusters distintos
        y que podrían estar relacionados semánticamente pero no están conectados.
        Heurística: conceptos con soporte similar pero sin aristas entre ellos.
        Retorna lista de (concepto_a, concepto_b, score_potencial).
        """
        conn = db_connect(self.db)
        c = conn.cursor()

        try:
            # Obtener conceptos con buen soporte pero pocas conexiones
            c.execute("""
                SELECT sm.concept, sm.support, sm.confidence
                FROM semantic_memory sm
                LEFT JOIN (
                    SELECT subject, COUNT(*) as deg
                    FROM knowledge_graph GROUP BY subject
                ) kg ON sm.concept = kg.subject
                WHERE sm.support >= 2 AND sm.confidence > 0.2
                ORDER BY COALESCE(kg.deg, 0) ASC, sm.support DESC
                LIMIT 30
            """)
            candidates = c.fetchall()

            # Encontrar pares sin aristas directas
            bridge_pairs = []
            for i, (a, sup_a, conf_a) in enumerate(candidates):
                for b, sup_b, conf_b in candidates[i+1:]:
                    if a == b:
                        continue
                    # Verificar que no existe arista directa en ninguna dirección
                    c.execute("""
                        SELECT COUNT(*) FROM knowledge_graph
                        WHERE (subject=? AND object=?) OR (subject=? AND object=?)
                    """, (a, b, b, a))
                    if c.fetchone()[0] == 0:
                        # Score: similaridad de soporte (conceptos co-aprendidos)
                        support_sim = 1.0 - abs(sup_a - sup_b) / max(sup_a, sup_b, 1)
                        avg_conf    = (conf_a + conf_b) / 2.0
                        score = support_sim * avg_conf
                        bridge_pairs.append((a, b, score))

            bridge_pairs.sort(key=lambda x: -x[2])
            return bridge_pairs[:top_k]

        except Exception:
            return []
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# 2. CONTRADICTION HUNTER — detecta pares con creencias opuestas
# ══════════════════════════════════════════════════════════════════════

class ContradictionHunter:
    """
    Encuentra contradicciones no resueltas crónicas, especialmente aquellas
    que involucran conceptos de alta importancia semántica.
    """

    def __init__(self, db_path: str = CURIOSITY_DB_PATH):
        self.db = db_path

    def find_chronic_contradictions(self, max_age_days: int = 7) -> List[Dict]:
        """
        Retorna contradicciones sin resolver que llevan más de `min_age` días abiertas,
        priorizadas por importancia de los conceptos implicados.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        results = []

        try:
            c.execute("""
                SELECT id, concept_a, concept_b, description, severity,
                       created_at, evidence_a, evidence_b
                FROM contradictions
                WHERE resolved = 0
                  AND created_at <= datetime('now', ? || ' days')
                ORDER BY severity DESC, created_at ASC
                LIMIT 10
            """, (f"-{MIN_CONTRADICTION_AGE}",))
            rows = c.fetchall()

            for row in rows:
                cid, ca, cb, desc, sev, created, ev_a, ev_b = row
                results.append({
                    "id":          cid,
                    "concept_a":   ca or "?",
                    "concept_b":   cb or "?",
                    "description": desc or "",
                    "severity":    sev or "medium",
                    "created_at":  created,
                    "evidence_a":  ev_a,
                    "evidence_b":  ev_b,
                })
        except Exception:
            pass
        finally:
            conn.close()

        return results


# ══════════════════════════════════════════════════════════════════════
# 3. CURIOSITY SCORER — puntúa el "valor epistémico" de explorar cada tema
# ══════════════════════════════════════════════════════════════════════

class CuriosityScorer:
    """
    Calcula un score 0.0–1.0 para cada candidato de exploración.

    score = w_uncertainty * uncertainty
          + w_novelty     * novelty
          + w_gap         * knowledge_gap
          + w_hypothesis  * hypothesis_potential

    Todos los cálculos son puramente SQL/aritméticos.
    Sin embeddings. Sin LLM.
    """

    def __init__(self, weights: Dict[str, float] = None):
        self.w = weights or CURIOSITY_WEIGHTS

    def score_concept(self, concept_data: Dict, global_stats: Dict) -> float:
        """
        Puntúa un concepto individual para exploración.
        concept_data: dict con 'confidence', 'support', 'degree', 'updated_at'
        global_stats: dict con 'avg_confidence', 'max_degree', 'max_support'
        """
        # Incertidumbre: conceptos con baja confianza tienen más que aprender
        uncertainty = max(0.0, 1.0 - (concept_data.get("confidence", 0.5)))

        # Novedad: cuánto tiempo hace que no se explora
        novelty = self._compute_novelty(concept_data.get("updated_at"))

        # Brecha de conocimiento: conceptos con pocas conexiones en KG
        max_degree = max(global_stats.get("max_degree", 1), 1)
        knowledge_gap = max(0.0, 1.0 - concept_data.get("degree", 0) / max_degree)

        # Potencial de hipótesis: conceptos con soporte medio tienen mayor potencial
        max_support = max(global_stats.get("max_support", 1), 1)
        s_norm = concept_data.get("support", 1) / max_support
        # Curva de potencial: máximo en support=50% (ni trivial ni exhausto)
        hypothesis_potential = 4.0 * s_norm * (1.0 - s_norm)

        score = (
            self.w["uncertainty"]          * uncertainty
          + self.w["novelty"]              * novelty
          + self.w["knowledge_gap"]        * knowledge_gap
          + self.w["hypothesis_potential"] * hypothesis_potential
        )
        return round(min(1.0, max(0.0, score)), 4)

    def score_pair(self, concept_a: str, concept_b: str, bridge_score: float) -> float:
        """
        Puntúa un par de conceptos candidatos a estar conectados.
        bridge_score proviene de KnowledgeGapFinder.find_bridge_candidates().
        """
        # Un par no conectado con alto soporte individual es muy interesante
        return round(min(1.0, bridge_score * 1.2), 4)

    def score_contradiction(self, contradiction: Dict) -> float:
        """Puntúa una contradicción según severidad y antigüedad."""
        severity_map = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.3}
        base = severity_map.get(contradiction.get("severity", "medium"), 0.5)
        # Bonus por antigüedad (cuanto más tiempo abierta, más urgente)
        try:
            created = datetime.fromisoformat(contradiction["created_at"])
            days_open = (datetime.now() - created).days
            age_bonus = min(0.3, days_open * 0.02)
        except Exception:
            age_bonus = 0.0
        return round(min(1.0, base + age_bonus), 4)

    @staticmethod
    def _compute_novelty(updated_at: Optional[str]) -> float:
        """Novedad = tiempo desde última actualización, normalizado a ventana."""
        if not updated_at:
            return 1.0  # nunca actualizado = máxima novedad
        try:
            last = datetime.fromisoformat(updated_at)
            hours_ago = (datetime.now() - last).total_seconds() / 3600.0
            # Escala logística: 0 horas → 0.0, 48+ horas → ≈1.0
            return round(1.0 - math.exp(-hours_ago / RECENCY_WINDOW_HOURS), 4)
        except Exception:
            return 0.5


# ══════════════════════════════════════════════════════════════════════
# 4. QUESTION GENERATOR — formula preguntas en lenguaje natural
# ══════════════════════════════════════════════════════════════════════

class QuestionGenerator:
    """
    Convierte candidatos de curiosidad en preguntas de lenguaje natural.
    No usa LLM — usa plantillas parametrizadas.

    Tipos de pregunta:
      - isolation  : "¿Qué conecta el concepto X con el resto del sistema?"
      - bridge     : "¿Qué concepto podría relacionar X e Y?"
      - contradiction: "¿Por qué X e Y parecen contradecirse?"
      - uncertainty: "¿Qué evidencia falta para confirmar X?"
      - hypothesis : "¿Qué hipótesis podría generar la relación entre X e Y?"
    """

    TEMPLATES = {
        "isolation": [
            "¿Qué otras ideas se relacionan con el concepto '{concept}'?",
            "¿Cómo se conecta '{concept}' con los demás conceptos del sistema?",
            "¿Qué falta por entender sobre '{concept}'?",
        ],
        "bridge": [
            "¿Qué concepto podría conectar '{concept_a}' y '{concept_b}'?",
            "¿Existe una idea intermedia entre '{concept_a}' y '{concept_b}'?",
            "¿Cómo se relacionan '{concept_a}' y '{concept_b}' si es que lo hacen?",
        ],
        "contradiction": [
            "¿Por qué '{concept_a}' y '{concept_b}' parecen contradecirse?",
            "¿Qué información resolvería la tensión entre '{concept_a}' y '{concept_b}'?",
            "¿Pueden '{concept_a}' y '{concept_b}' ser ambos correctos en contextos distintos?",
        ],
        "uncertainty": [
            "¿Qué evidencia adicional reforzaría la confianza en '{concept}'?",
            "¿En qué contextos podría ser falso el concepto '{concept}'?",
            "¿Cuál es el límite de validez de '{concept}'?",
        ],
        "hypothesis": [
            "¿Qué teoría explicaría la relación entre '{concept_a}' y '{concept_b}'?",
            "Si '{concept_a}' causa '{concept_b}', ¿qué mecanismo intermedio podría existir?",
        ],
    }

    def generate_isolation_question(self, concept: str, score: float) -> Dict:
        import random
        templates = self.TEMPLATES["isolation"]
        template = templates[hash(concept) % len(templates)]
        return {
            "type":     "isolation",
            "question": template.format(concept=concept),
            "topic":    concept,
            "score":    score,
            "rationale": f"Concepto '{concept}' con pocas conexiones en el grafo (score={score:.2f})",
        }

    def generate_bridge_question(self, concept_a: str, concept_b: str, score: float) -> Dict:
        templates = self.TEMPLATES["bridge"]
        template = templates[hash(concept_a + concept_b) % len(templates)]
        return {
            "type":      "bridge",
            "question":  template.format(concept_a=concept_a, concept_b=concept_b),
            "topic":     f"{concept_a} ↔ {concept_b}",
            "score":     score,
            "rationale": f"Par '{concept_a}'–'{concept_b}' con alto soporte pero sin aristas (score={score:.2f})",
        }

    def generate_contradiction_question(self, contradiction: Dict, score: float) -> Dict:
        ca = contradiction.get("concept_a", "concepto A")
        cb = contradiction.get("concept_b", "concepto B")
        templates = self.TEMPLATES["contradiction"]
        template = templates[hash(ca + cb) % len(templates)]
        return {
            "type":      "contradiction",
            "question":  template.format(concept_a=ca, concept_b=cb),
            "topic":     f"contradicción: {ca} vs {cb}",
            "score":     score,
            "rationale": (f"Contradicción crónica ({contradiction.get('severity','?')} severidad) "
                          f"sin resolver: {contradiction.get('description','')[:80]}"),
            "contradiction_id": contradiction.get("id"),
        }

    def generate_uncertainty_question(self, concept: str, confidence: float, score: float) -> Dict:
        templates = self.TEMPLATES["uncertainty"]
        template = templates[hash(concept) % len(templates)]
        return {
            "type":      "uncertainty",
            "question":  template.format(concept=concept),
            "topic":     concept,
            "score":     score,
            "rationale": f"Concepto '{concept}' con confianza baja ({confidence:.0%}) (score={score:.2f})",
        }


# ══════════════════════════════════════════════════════════════════════
# 5. CURIOSITY ENGINE — orquestador principal
# ══════════════════════════════════════════════════════════════════════

class CuriosityEngine:
    """
    Orquesta el ciclo completo de curiosidad epistémica:

    1. Recolectar conceptos candidatos (SQL, sin embeddings)
    2. Puntuar con CuriosityScorer
    3. Generar preguntas con QuestionGenerator
    4. Guardar propuestas en curiosity_proposals
    5. Exponer resultado para aprobación humana o ciclo de exploración

    IMPORTANTE: El motor NUNCA ejecuta búsquedas ni modifica memoria.
    Solo produce preguntas priorizadas para que el sistema principal decida
    si iniciar un ciclo de exploración sobre ellas.
    """

    def __init__(self, db_path: str = CURIOSITY_DB_PATH):
        self.db            = db_path
        self.gap_finder    = KnowledgeGapFinder(db_path)
        self.contr_hunter  = ContradictionHunter(db_path)
        self.scorer        = CuriosityScorer()
        self.generator     = QuestionGenerator()
        self._ensure_table()

    def _ensure_table(self):
        """Crea la tabla de propuestas de curiosidad si no existe."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS curiosity_proposals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT NOT NULL,
                question_type   TEXT NOT NULL,
                question        TEXT NOT NULL,
                topic           TEXT,
                score           REAL NOT NULL,
                rationale       TEXT,
                status          TEXT DEFAULT 'pending',
                explored_at     TEXT,
                outcome         TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _get_global_stats(self) -> Dict:
        """Estadísticas globales para normalizar scores."""
        conn = db_connect(self.db)
        c = conn.cursor()
        stats = {}
        try:
            c.execute("SELECT AVG(confidence), MAX(support) FROM semantic_memory")
            row = c.fetchone()
            stats["avg_confidence"] = row[0] or 0.5
            stats["max_support"]    = row[1] or 1

            c.execute("""
                SELECT MAX(deg) FROM (
                    SELECT subject, COUNT(*) as deg FROM knowledge_graph GROUP BY subject
                )
            """)
            row = c.fetchone()
            stats["max_degree"] = row[0] or 1
        except Exception:
            stats = {"avg_confidence": 0.5, "max_support": 1, "max_degree": 1}
        finally:
            conn.close()
        return stats

    def _concept_count(self) -> int:
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM semantic_memory")
            return c.fetchone()[0]
        except Exception:
            return 0
        finally:
            conn.close()

    def run_cycle(self, max_questions: int = MAX_QUESTIONS_PER_RUN) -> Dict:
        """
        Ejecuta un ciclo de curiosidad completo.
        Retorna un dict con:
          - questions: lista de preguntas ordenadas por score
          - stats: estadísticas del ciclo
          - message: resumen legible para el humano
        """
        if self._concept_count() < MIN_CONCEPTS_FOR_RUN:
            return {
                "questions": [],
                "stats": {"skipped": True, "reason": "insufficient_concepts"},
                "message": (f"Motor de curiosidad: base de conocimiento insuficiente "
                            f"(mínimo {MIN_CONCEPTS_FOR_RUN} conceptos necesarios)."),
            }

        global_stats = self._get_global_stats()
        candidates   = []

        # ── Conceptos aislados (pocas conexiones KG) ──────────────────
        isolated = self.gap_finder.find_isolated_concepts(top_k=15)
        for concept_data in isolated:
            score = self.scorer.score_concept(concept_data, global_stats)
            if score < MIN_CURIOSITY_SCORE:
                continue
            if concept_data["confidence"] < 0.4:
                q = self.generator.generate_uncertainty_question(
                    concept_data["concept"], concept_data["confidence"], score)
            else:
                q = self.generator.generate_isolation_question(
                    concept_data["concept"], score)
            candidates.append(q)

        # ── Pares candidatos a puentes KG ──────────────────────────────
        bridge_pairs = self.gap_finder.find_bridge_candidates(top_k=8)
        for concept_a, concept_b, bridge_score in bridge_pairs:
            score = self.scorer.score_pair(concept_a, concept_b, bridge_score)
            if score < MIN_CURIOSITY_SCORE:
                continue
            q = self.generator.generate_bridge_question(concept_a, concept_b, score)
            candidates.append(q)

        # ── Contradicciones crónicas ───────────────────────────────────
        contradictions = self.contr_hunter.find_chronic_contradictions()
        for contr in contradictions:
            score = self.scorer.score_contradiction(contr)
            if score < MIN_CURIOSITY_SCORE:
                continue
            q = self.generator.generate_contradiction_question(contr, score)
            candidates.append(q)

        # ── Ordenar por score y recortar ───────────────────────────────
        candidates.sort(key=lambda x: -x["score"])
        top_questions = candidates[:max_questions]

        # ── Guardar en DB ──────────────────────────────────────────────
        self._save_proposals(top_questions)

        # ── Mensaje para el humano ─────────────────────────────────────
        message = self._format_output(top_questions)

        return {
            "questions":     top_questions,
            "total_scored":  len(candidates),
            "selected":      len(top_questions),
            "stats":         global_stats,
            "message":       message,
        }

    def _save_proposals(self, questions: List[Dict]):
        conn = db_connect(self.db)
        c = conn.cursor()
        ts = datetime.now().isoformat()
        for q in questions:
            c.execute("""
                INSERT INTO curiosity_proposals
                (timestamp, question_type, question, topic, score, rationale, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """, (ts, q["type"], q["question"], q.get("topic"), q["score"],
                  q.get("rationale", "")))
        conn.commit()
        conn.close()

    def _format_output(self, questions: List[Dict]) -> str:
        if not questions:
            return "Motor de curiosidad: no se detectaron brechas de conocimiento significativas."

        lines = ["\n🔍 MOTOR DE CURIOSIDAD — Preguntas Propuestas\n"]
        lines.append(f"   {len(questions)} pregunta(s) generadas en este ciclo.\n")

        type_icons = {
            "isolation":     "🗺️",
            "bridge":        "🌉",
            "contradiction": "⚡",
            "uncertainty":   "❓",
            "hypothesis":    "💡",
        }
        for i, q in enumerate(questions, 1):
            icon = type_icons.get(q["type"], "•")
            lines.append(f"  {i}. {icon} [{q['score']:.0%}] {q['question']}")
            lines.append(f"      Razón: {q.get('rationale','')}")
            lines.append("")

        lines.append("→ Use '/api/curiosity/propuestas' para ver el listado completo.")
        lines.append("→ Use '/api/curiosity/explorar/<id>' para iniciar un ciclo de exploración.")
        return "\n".join(lines)

    def get_pending_proposals(self) -> List[Dict]:
        """Retorna propuestas pendientes ordenadas por score."""
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("""
                SELECT id, timestamp, question_type, question, topic, score, rationale
                FROM curiosity_proposals
                WHERE status = 'pending'
                ORDER BY score DESC
            """)
            rows = c.fetchall()
            return [
                {"id": r[0], "timestamp": r[1], "type": r[2], "question": r[3],
                 "topic": r[4], "score": r[5], "rationale": r[6]}
                for r in rows
            ]
        except Exception:
            return []
        finally:
            conn.close()

    def mark_explored(self, proposal_id: int, outcome: str = ""):
        """Marca una propuesta como explorada después del ciclo de aprendizaje."""
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("""
                UPDATE curiosity_proposals
                SET status='explored', explored_at=?, outcome=?
                WHERE id=?
            """, (datetime.now().isoformat(), outcome, proposal_id))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def get_curiosity_score(self, observation: str, similar_count: int = 0,
                             top_label: str = None) -> float:
        """Score 0-1 para una observación. Puro SQL, < 5ms. Llamado desde observe()."""
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            uncertainty = max(0.0, 1.0 - similar_count / 5.0)
            novelty = 0.5
            if top_label:
                c.execute("SELECT confidence, updated_at FROM semantic_memory WHERE concept=?", (top_label,))
                row = c.fetchone()
                if row:
                    conf, upd = row[0] or 0.5, row[1]
                    novelty = min(1.0, CuriosityScorer._compute_novelty(upd) * (1.0 + (1.0 - conf)))
                else:
                    novelty = 1.0
            kg_gap = 0.5
            if top_label:
                c.execute("SELECT COUNT(*) FROM knowledge_graph WHERE subject=? OR object=?",
                          (top_label, top_label))
                deg = c.fetchone()[0] or 0
                kg_gap = max(0.0, 1.0 - deg / 10.0)
            conn.close()
            w = CURIOSITY_WEIGHTS
            active = w["uncertainty"] + w["novelty"] + w["knowledge_gap"]
            score = (w["uncertainty"] * uncertainty + w["novelty"] * novelty +
                     w["knowledge_gap"] * kg_gap) / active
            return round(min(1.0, max(0.0, score)), 3)
        except Exception:
            return 0.0

    def status_report(self) -> str:
        """Reporte legible del estado del motor de curiosidad."""
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM curiosity_proposals WHERE status='pending'")
            pending = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM curiosity_proposals WHERE status='explored'")
            explored = c.fetchone()[0]
            c.execute("SELECT MAX(timestamp) FROM curiosity_proposals")
            last_ts = c.fetchone()[0] or "nunca"
        except Exception:
            pending, explored, last_ts = 0, 0, "n/a"
        finally:
            conn.close()

        return (
            f"\n🔍 CURIOSITY ENGINE — Estado\n"
            f"   Propuestas pendientes:  {pending}\n"
            f"   Ciclos completados:     {explored}\n"
            f"   Último ciclo:           {str(last_ts)[:16]}\n"
        )


# ══════════════════════════════════════════════════════════════════════
# INTEGRACIÓN FLASK
# ══════════════════════════════════════════════════════════════════════

def register_routes_curiosity(app, db_path: str = CURIOSITY_DB_PATH):
    """Registra los endpoints del motor de curiosidad en la app Flask."""
    from flask import request, jsonify

    engine = CuriosityEngine(db_path)

    @app.route("/api/curiosity/ciclo", methods=["POST"])
    def api_curiosity_ciclo():
        data = request.get_json() or {}
        max_q = data.get("max_questions", MAX_QUESTIONS_PER_RUN)
        result = engine.run_cycle(max_questions=max_q)
        return jsonify(result)

    @app.route("/api/curiosity/propuestas")
    def api_curiosity_propuestas():
        return jsonify(engine.get_pending_proposals())

    @app.route("/api/curiosity/explorar/<int:proposal_id>", methods=["POST"])
    def api_curiosity_explorar(proposal_id):
        data = request.get_json() or {}
        outcome = data.get("outcome", "")
        engine.mark_explored(proposal_id, outcome)
        return jsonify({"status": "ok", "marked_explored": proposal_id})

    @app.route("/api/curiosity/estado")
    def api_curiosity_estado():
        return jsonify({"status_text": engine.status_report()})

    print("[OK] CuriosityEngine v1 activo — endpoints /api/curiosity/* registrados")
    return engine
