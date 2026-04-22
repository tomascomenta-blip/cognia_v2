"""
cognia/reasoning/metacognition.py
===================================
Metacognición: evaluación de confianza, log de decisiones,
evaluación de predicciones y módulo de curiosidad.
"""

import time
from datetime import datetime
from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH


class MetacognitionModule:
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path
        self._introspect_cache = None
        self._introspect_ts = 0.0

    def assess_confidence(self, similar_episodes: list) -> dict:
        if not similar_episodes:
            return {"state": "ignorant", "confidence": 0.0, "top_label": None,
                    "should_ask": True, "reason": "Sin memorias relevantes"}

        top = similar_episodes[0]
        sim = top["similarity"]
        conf = top["confidence"]

        labels = [e["label"] for e in similar_episodes if e.get("label")]
        top_label = max(set(labels), key=labels.count) if labels else None

        # Bonus si el concepto tiene hechos en el KG
        kg_bonus = 0.0
        if top_label:
            try:
                conn = db_connect(self.db)
                c_cur = conn.cursor()
                c_cur.execute("""
                    SELECT COUNT(*) FROM knowledge_graph WHERE subject=? OR object=?
                """, (top_label, top_label))
                kg_edges = c_cur.fetchone()[0]
                conn.close()
                kg_bonus = min(0.10, kg_edges / 200.0)
            except Exception:
                pass

        blended = 0.55 * sim + 0.35 * conf + kg_bonus

        if blended >= 0.75:
            state = "confident"
            should_ask = False
            reason = f"Alta similitud ({sim:.0%}) con recuerdo confiable"
        elif blended >= 0.5:
            state = "uncertain"
            should_ask = False
            reason = f"Similitud moderada ({sim:.0%}), podría equivocarme"
        elif blended >= 0.3:
            state = "confused"
            should_ask = True
            reason = f"Baja similitud ({sim:.0%}), necesito más datos"
        else:
            state = "ignorant"
            should_ask = True
            reason = "No encuentro nada suficientemente similar"

        return {"state": state, "confidence": blended, "top_label": top_label,
                "should_ask": should_ask, "reason": reason,
                "kg_bonus": round(kg_bonus, 4)}

    def log_decision(self, action: str, prediction: str, outcome: str,
                     was_error: bool = False, learned: str = ""):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO decision_log (timestamp, action, prediction, outcome, was_error, learned)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), action, prediction, outcome, int(was_error), learned))
        conn.commit()
        conn.close()

    def introspect(self) -> dict:
        now = time.time()
        if self._introspect_cache and (now - self._introspect_ts) < 2.0:
            return self._introspect_cache

        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0")
            active = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten=1")
            forgotten = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM semantic_memory")
            concepts = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM hypotheses")
            hyps = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM decision_log")
            total_dec = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM decision_log WHERE was_error=1")
            errors = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM contradictions WHERE resolved=0")
            contradictions = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE next_review <= ? AND forgotten=0",
                      (datetime.now().isoformat(),))
            due_review = c.fetchone()[0]
            c.execute("SELECT emotion_label, COUNT(*) FROM episodic_memory WHERE forgotten=0 GROUP BY emotion_label")
            emotion_dist = dict(c.fetchall())
            c.execute("SELECT COUNT(*) FROM knowledge_graph")
            kg_edges = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM temporal_sequences")
            seq_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM goal_system WHERE status='pending'")
            pending_goals = c.fetchone()[0]
        finally:
            conn.close()

        error_rate = errors / max(1, total_dec)
        result = {
            "active_memories": active,
            "forgotten_memories": forgotten,
            "concepts": concepts,
            "hypotheses": hyps,
            "error_rate": round(error_rate, 3),
            "contradictions_pending": contradictions,
            "due_for_review": due_review,
            "emotion_distribution": emotion_dist,
            "total_decisions": total_dec,
            "kg_edges": kg_edges,
            "temporal_sequences": seq_count,
            "pending_goals": pending_goals,
        }
        self._introspect_cache = result
        self._introspect_ts = now
        return result


class EvaluationModule:
    def __init__(self, episodic, metacog: MetacognitionModule):
        self.episodic = episodic
        self.metacog = metacog

    def evaluate_prediction(self, predicted: str, actual: str, similar: list) -> dict:
        correct = (predicted == actual)
        self.metacog.log_decision("predict", predicted, actual,
                                  was_error=not correct,
                                  learned=f"'{actual}' no es '{predicted}'" if not correct else "")
        if not correct and similar:
            for ep in similar[:2]:
                if ep.get("label") == predicted:
                    self.episodic.mark_reviewed(ep["id"], correct=False)
        return {"correct": correct, "predicted": predicted, "actual": actual}


class CuriosityModule:
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def should_explore(self, assessment: dict) -> bool:
        return assessment.get("should_ask", False) or assessment.get("state") in ("confused", "ignorant")

    def generate_question(self, observation: str, assessment: dict, similar: list) -> str:
        state = assessment.get("state", "ignorant")
        if state == "ignorant":
            return f"No sé qué es esto: '{observation[:50]}'. ¿Puedes enseñarme con 'aprender {observation[:30]} | <etiqueta>'?"
        elif state == "confused":
            top = assessment.get("top_label", "algo")
            return f"¿Esto es '{top}'? No estoy seguro. Tengo solo {assessment['confidence']:.0%} de confianza."
        else:
            return f"Creo que entiendo, pero quiero confirmar: ¿'{assessment['top_label']}'?"
