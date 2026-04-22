"""
cognia/knowledge/inference.py
==============================
Motor de inferencia simbólica ligero.
Encadenamiento hacia adelante + herencia de propiedades vía is_a.
"""

from datetime import datetime
from typing import List, Optional
from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH
from .graph import KnowledgeGraph


class InferenceEngine:
    """
    Motor de inferencia simbólica ligero.

    - Encadenamiento hacia adelante (forward chaining) sobre el KG
    - Inferencia transitiva para is_a (herencia de propiedades)
    - Modus ponens básico sobre reglas almacenadas
    - Máximo 3 pasos de inferencia (eficiencia energética)
    """

    TRANSITIVITY_RULES = {
        ("is_a", "is_a"): "is_a",
        ("part_of", "part_of"): "part_of",
        ("causes", "causes"): "causes",
    }

    def __init__(self, db_path: str = DB_PATH, kg: KnowledgeGraph = None):
        self.db = db_path
        self.kg = kg or KnowledgeGraph(db_path)

    def infer(self, concept: str, max_steps: int = 3) -> List[dict]:
        inferences = []
        visited = set()

        facts = self.kg.get_facts(concept)
        for fact in facts:
            chain = self._chain_forward(fact["subject"], fact["predicate"],
                                        fact["object"], depth=0, max_depth=max_steps,
                                        visited=visited)
            inferences.extend(chain)

        seen = set()
        unique = []
        for inf in inferences:
            key = (inf["conclusion_subject"], inf["conclusion_predicate"], inf["conclusion_object"])
            if key not in seen:
                seen.add(key)
                unique.append(inf)

        return unique[:10]

    def _chain_forward(self, subj: str, pred: str, obj: str,
                       depth: int, max_depth: int, visited: set) -> list:
        if depth >= max_depth:
            return []
        key = (subj, pred, obj)
        if key in visited:
            return []
        visited.add(key)

        inferences = []
        next_facts = self.kg.get_neighbors(obj, predicate=pred)
        for next_fact in next_facts:
            next_obj = next_fact["concept"]
            new_pred = self.TRANSITIVITY_RULES.get((pred, pred))
            if new_pred and next_obj != subj:
                existing = self.kg.get_facts(subj, predicate=new_pred)
                already_known = any(e["object"] == next_obj for e in existing)
                if not already_known:
                    inferences.append({
                        "conclusion_subject": subj,
                        "conclusion_predicate": new_pred,
                        "conclusion_object": next_obj,
                        "confidence": 0.75,
                        "justification": f"{subj} {pred} {obj} + {obj} {pred} {next_obj} → {subj} {new_pred} {next_obj}",
                        "type": "transitivity"
                    })
                sub_chain = self._chain_forward(subj, new_pred, next_obj,
                                                depth + 1, max_depth, visited)
                inferences.extend(sub_chain)

        return inferences

    def infer_properties(self, concept: str) -> list:
        """Hereda propiedades a través de la jerarquía is_a."""
        inherited = []
        ancestors = self.kg.get_ancestors(concept)

        for ancestor in ancestors:
            ancestor_facts = self.kg.get_facts(ancestor)
            direct_facts = {(f["predicate"], f["object"]) for f in self.kg.get_facts(concept)}

            for fact in ancestor_facts:
                if fact["subject"] == ancestor and fact["predicate"] != "is_a":
                    key = (fact["predicate"], fact["object"])
                    if key not in direct_facts:
                        inherited.append({
                            "property": fact["predicate"],
                            "value": fact["object"],
                            "inherited_from": ancestor,
                            "confidence": fact["weight"] * 0.7,
                            "justification": f"{concept} is_a {ancestor}, {ancestor} {fact['predicate']} {fact['object']}"
                        })

        return inherited[:8]

    def can_answer(self, question: str) -> Optional[dict]:
        """Intenta responder preguntas simples usando inferencia sobre el grafo."""
        q = question.lower().strip().rstrip("?").strip()

        for pat in ["es un ", "es una ", "is a ", "is an "]:
            if pat in q:
                parts = q.split(pat)
                if len(parts) >= 2:
                    subj_part = parts[0].strip()
                    subj = subj_part.split()[-1] if subj_part else ""
                    obj = parts[1].strip().split()[0]
                    if subj and obj:
                        facts = self.kg.get_facts(subj, "is_a")
                        for f in facts:
                            if f["object"] == obj or obj in self.kg.get_ancestors(subj):
                                return {
                                    "answer": True,
                                    "confidence": f["weight"] / 3.0,
                                    "justification": f"Sí: {subj} is_a {f['object']}"
                                }
                        ancestors = self.kg.get_ancestors(subj)
                        if obj in ancestors:
                            return {
                                "answer": True,
                                "confidence": 0.65,
                                "justification": f"Por herencia: {subj} → {'→'.join(ancestors[:ancestors.index(obj)+1])}"
                            }
        return None

    def add_rule(self, premise_a: str, pred_a: str, premise_b: str,
                 pred_b: str, conclusion: str, confidence: float = 0.7):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO inference_rules
            (premise_a, predicate_a, premise_b, predicate_b, conclusion, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (premise_a, pred_a, premise_b, pred_b, conclusion, confidence,
              datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def apply_stored_rules(self, concept: str) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT premise_a, predicate_a, premise_b, predicate_b, conclusion, confidence
            FROM inference_rules WHERE premise_a=?
        """, (concept,))
        rows = c.fetchall()
        conn.close()

        results = []
        for p_a, pred_a, p_b, pred_b, conclusion, conf in rows:
            facts_a = self.kg.get_facts(p_a, pred_a)
            facts_b = self.kg.get_facts(p_b, pred_b) if p_b else [True]
            if facts_a and facts_b:
                results.append({
                    "conclusion": conclusion,
                    "confidence": conf,
                    "rule": f"IF {p_a} {pred_a} AND {p_b} {pred_b} THEN {conclusion}"
                })
        return results
