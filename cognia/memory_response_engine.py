"""
cognia/memory_response_engine.py
=================================
MemoryContextBuilder: construye un bloque de contexto rico desde los sistemas
de memoria de Cognia para que el LLM lo articule — no lo genere.

El coverage score (0-1) mide qué tan bien las memorias recuperadas cubren la
pregunta. Si coverage >= umbral, el sistema prompt de Ollama cambia de
"responde usando tu conocimiento" a "articula SOLO lo que hay en este contexto".

Esto invierte el rol de Ollama: de fuente de conocimiento a capa de lenguaje.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class MemoryContext:
    text:          str
    coverage:      float        # 0-1
    episode_ids:   List[int]    = field(default_factory=list)
    top_label:     Optional[str] = None
    episode_count: int           = 0
    fact_count:    int           = 0


class MemoryContextBuilder:
    """
    Stage 0 del pipeline de LanguageEngine.
    Se ejecuta antes del gate simbólico para construir contexto y decidir
    si Ollama debe actuar como articulador restringido o como LLM libre.
    """

    _TOP_K           = 15
    _SIM_MIN         = 0.25    # umbral mínimo para incluir episodio
    _SIM_DIRECT      = 0.55    # umbral para episodio "directamente relevante"

    def build(self, cognia, question: str, vec: list) -> MemoryContext:
        if not vec:
            return MemoryContext("")

        # top_k adaptativo a fatiga cognitiva
        top_k = self._TOP_K
        if hasattr(cognia, "fatigue") and cognia.fatigue:
            adaps = cognia.fatigue.get_adaptations()
            top_k = min(self._TOP_K, adaps.get("top_k_retrieval", self._TOP_K) + 5)

        # 1. Recuperar episodios
        episodes = cognia.episodic.retrieve_similar(vec, top_k=top_k)
        relevant = [e for e in episodes if e.get("similarity", 0) >= self._SIM_MIN]
        direct   = [e for e in relevant  if e.get("similarity", 0) >= self._SIM_DIRECT]
        ep_ids   = [e["id"] for e in relevant if e.get("id")]

        # 2. Metacognición — label principal y confianza
        assessment = cognia.metacog.assess_confidence(relevant[:5] if relevant else [])
        top_label  = assessment.get("top_label")
        confidence = float(assessment.get("confidence", 0.0))

        # 3. Knowledge Graph
        kg_facts = cognia.kg.get_facts(top_label)[:8] if top_label else []

        # 3b. Hechos heredados via cadena is_a
        _inherited_facts: list = []
        if top_label:
            try:
                _inherited_facts = cognia.kg.get_inherited_facts(top_label)
            except Exception:
                pass

        # 4. Activación semántica
        concepts = cognia.semantic.spreading_activation(top_label, depth=2)[:5] if top_label else []

        # 5. Inferencias
        inferences: list = []
        if top_label:
            try:
                inferences = cognia.inference.infer(top_label, max_steps=2)[:3]
                inferences += cognia.inference.infer_properties(top_label)[:2]
            except Exception:
                pass

        # 6. Predicciones temporales
        temporal: list = []
        try:
            temporal = cognia.temporal_mem.predict_from_context()[:2]
        except Exception:
            pass

        # 7. Crystallized concepts — stable high-confidence knowledge (max 3)
        _cryst: list = []
        try:
            if hasattr(cognia, 'semantic') and hasattr(cognia.semantic, 'get_crystallized'):
                _cryst = cognia.semantic.get_crystallized()[:3]
        except Exception:
            pass

        coverage = self._coverage(relevant, direct, kg_facts, concepts, confidence)
        text     = self._format(
            relevant, direct, kg_facts, concepts, inferences, temporal,
            top_label, confidence, assessment.get("state", "ignorant"),
            crystallized=_cryst,
            inherited_facts=_inherited_facts,
        )

        return MemoryContext(
            text          = text,
            coverage      = coverage,
            episode_ids   = ep_ids,
            top_label     = top_label,
            episode_count = len(relevant),
            fact_count    = len(kg_facts),
        )

    # ── Cálculo de coverage ───────────────────────────────────────────

    def _coverage(self, relevant, direct, kg_facts, concepts, confidence) -> float:
        top_sim      = direct[0]["similarity"] if direct else (
                       relevant[0]["similarity"] if relevant else 0.0)
        ep_score     = min(1.0, len(relevant) / 10.0)
        direct_score = min(1.0, len(direct)   / 3.0)
        kg_score     = min(1.0, len(kg_facts)  / 6.0)
        sem_score    = min(1.0, len(concepts)  / 4.0)

        return round(min(1.0,
            top_sim      * 0.30 +
            ep_score     * 0.20 +
            direct_score * 0.20 +
            kg_score     * 0.15 +
            confidence   * 0.10 +
            sem_score    * 0.05
        ), 3)

    # ── Formateo de contexto ──────────────────────────────────────────

    def _format(self, relevant, direct, kg_facts, concepts, inferences, temporal,
                top_label, confidence, state, crystallized=None, inherited_facts=None) -> str:
        if not relevant and not kg_facts and not concepts:
            return ""

        blocks: list = []

        # Crystallized concepts — prepended as highest-priority stable knowledge
        if crystallized:
            cryst_lines = "; ".join(
                f"{c['concept']} (conf={c['confidence']:.2f})" for c in crystallized
            )
            blocks.append(f"[Conocimiento consolidado: {cryst_lines}]")

        # Episodios — los directamente relevantes primero, luego el resto
        ordered = direct + [e for e in relevant if e not in direct]
        if ordered:
            lines = []
            for e in ordered[:10]:
                sim   = e.get("similarity", 0)
                obs   = e.get("observation", "")[:150].strip()
                label = e.get("label") or ""
                conf  = e.get("confidence", 0)
                tag   = f" [{label}]" if label else ""
                lines.append(f"- \"{obs}\"{tag} (relevancia: {sim:.0%}, conf: {conf:.0%})")
            blocks.append(
                f"MEMORIAS EPISODICAS ({len(relevant)} recuperadas):\n" + "\n".join(lines)
            )

        # Hechos del Knowledge Graph
        if kg_facts:
            lines = [
                f"- {f['subject']} --{f['predicate']}--> {f['object']} (peso: {f['weight']:.1f})"
                for f in kg_facts[:6]
            ]
            blocks.append("HECHOS CONOCIDOS:\n" + "\n".join(lines))

        # Hechos heredados por herencia is_a
        if inherited_facts:
            blocks.append("HECHOS INFERIDOS POR HERENCIA:\n" + "\n".join(f"- {f}" for f in inherited_facts))

        # Conceptos semánticos activados
        if concepts:
            lines = [f"- {c['concept']} (activacion: {c['activation']:.2f})" for c in concepts]
            blocks.append("CONCEPTOS RELACIONADOS:\n" + "\n".join(lines))

        # Inferencias derivadas
        inf_lines = [
            f"- {inf.get('justification', inf.get('property', ''))[:130]}"
            for inf in inferences[:4]
            if inf.get("justification") or inf.get("property")
        ]
        if inf_lines:
            blocks.append("INFERENCIAS:\n" + "\n".join(inf_lines))

        # Predicciones temporales
        if temporal:
            preds = ", ".join(f"{p['concept']} ({p['score']:.2f})" for p in temporal)
            blocks.append(f"PREDICCIONES TEMPORALES: {preds}")

        # Estado cognitivo meta
        if top_label:
            blocks.append(
                f"ESTADO COGNITIVO: concepto='{top_label}', "
                f"confianza={confidence:.0%}, estado={state}"
            )

        return "\n\n".join(blocks)
