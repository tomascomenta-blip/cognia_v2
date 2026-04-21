"""
cognia/reasoning/hypothesis.py
================================
Generación de hipótesis creativas entre pares de conceptos.
Usa Ollama si está disponible, con fallback a plantillas.
"""

from collections import Counter
from datetime import datetime
from typing import Optional
from ..database import db_connect
from ..vectors import cosine_similarity
from ..config import DB_PATH


class HypothesisModule:
    def __init__(self, db_path: str = DB_PATH, semantic=None):
        self.db = db_path
        # Se inyecta SemanticMemory para evitar importación circular
        self.semantic = semantic

    def _hechos_de(self, concept: str, kg) -> str:
        try:
            hechos = kg.get_facts(concept)
            return "; ".join(f"{h['subject']} {h['predicate']} {h['object']}" for h in hechos[:5])
        except Exception:
            return ""

    def generate(self, concept_a: str, concept_b: str,
                 kg=None, usar_ollama: bool = True) -> Optional[dict]:
        """
        Genera una hipótesis creativa entre dos conceptos.
        Con Ollama: temperature alta para ideas originales.
        Sin Ollama: plantilla como fallback.
        """
        ca = self.semantic.get_concept(concept_a)
        cb = self.semantic.get_concept(concept_b)
        if not ca or not cb:
            missing = concept_a if not ca else concept_b
            return {"error": f"No conozco suficiente sobre '{missing}' todavía"}

        sim = cosine_similarity(ca["vector"], cb["vector"])
        hyp_conf = max(0.25, 0.55 - abs(sim - 0.4) * 0.3)
        text = None

        if usar_ollama:
            try:
                import urllib.request as _req, json as _json
                desc_a = ca.get("description", "") or concept_a
                desc_b = cb.get("description", "") or concept_b
                hechos_a = self._hechos_de(concept_a, kg) if kg else ""
                hechos_b = self._hechos_de(concept_b, kg) if kg else ""

                if sim < 0.3:
                    instruccion = ("Estos conceptos son MUY distintos. "
                                   "Encuentra una conexión sorprendente y no obvia. "
                                   "Puede ser metafórica, causal o analógica. Sé audaz.")
                elif sim < 0.6:
                    instruccion = "Propón una hipótesis no evidente que los relacione."
                else:
                    instruccion = "Son similares. ¿En qué difieren fundamentalmente?"

                prompt_hyp = (
                    f"Concepto A: {concept_a}\nDescripción: {desc_a[:160]}\n"
                    + (f"Hechos: {hechos_a}\n" if hechos_a else "")
                    + f"\nConcepto B: {concept_b}\nDescripción: {desc_b[:160]}\n"
                    + (f"Hechos: {hechos_b}\n" if hechos_b else "")
                    + f"\n{instruccion}\n"
                    "UNA hipótesis en 2-3 oraciones. Sin introducción. Directo al punto."
                )
                payload = _json.dumps({
                    "model": "llama3.2", "prompt": prompt_hyp,
                    "system": ("Eres el motor de hipótesis de Cognia. "
                               "Generas hipótesis originales y especulativas pero plausibles. "
                               "Afirma con confianza aunque sea especulativo. "
                               "Máximo 3 oraciones. Responde en español."),
                    "stream": False,
                    "options": {"temperature": 0.92, "num_predict": 200}
                }).encode("utf-8")
                req = _req.Request("http://localhost:11434/api/generate",
                                   data=payload, headers={"Content-Type": "application/json"})
                with _req.urlopen(req, timeout=120) as r:
                    text = _json.loads(r.read()).get("response", "").strip()
                if len(text or "") < 20:
                    text = None
            except Exception:
                text = None

        if not text:
            if sim > 0.7:
                text = (f"'{concept_a}' y '{concept_b}' comparten estructura semántica profunda "
                        f"(sim={sim:.2f}) — podrían ser instancias del mismo principio abstracto.")
            elif sim > 0.4:
                text = (f"'{concept_a}' y '{concept_b}' operan en dominios distintos pero "
                        f"comparten un mecanismo subyacente (sim={sim:.2f}).")
            else:
                text = (f"'{concept_a}' y '{concept_b}' son semánticamente distantes (sim={sim:.2f}): "
                        f"candidatos a una analogía estructural no obvia.")
            hyp_conf *= 0.8

        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("INSERT INTO hypotheses (hypothesis, confidence, created_at) VALUES (?,?,?)",
                  (text, hyp_conf, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        self.semantic.add_association(concept_a, concept_b, max(0.2, sim))
        return {"hypothesis": text, "confidence": round(hyp_conf, 3),
                "similarity": round(sim, 3), "via_ollama": text is not None and "sim=" not in text}

    def generate_from_pattern(self, similar_episodes: list) -> Optional[str]:
        if len(similar_episodes) < 2:
            return None
        labels = [e["label"] for e in similar_episodes if e.get("label")]
        if not labels:
            return None
        top = Counter(labels).most_common(1)[0]
        label, count = top
        ratio = count / len(labels)
        if ratio >= 0.6:
            return f"Observaciones similares parecen ser '{label}' ({ratio:.0%} coincidencia)"
        return None

    def list_hypotheses(self) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT hypothesis, confidence, created_at FROM hypotheses ORDER BY created_at DESC LIMIT 10")
        rows = [{"hypothesis": r[0], "confidence": r[1], "created_at": r[2]} for r in c.fetchall()]
        conn.close()
        return rows
