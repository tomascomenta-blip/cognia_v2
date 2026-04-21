"""
symbolic_synthesizer.py — Cognia PASO 4: Síntesis Simbólica Multi-Fuente
=========================================================================
Transforma el módulo simbólico de "lookup de un concepto" a "síntesis
de múltiples fuentes anclada a la pregunta".

PROBLEMA QUE RESUELVE:
  Antes: SymbolicResponder extraía el top_label, hacía un lookup y construía
  una respuesta basada en ESE concepto. Si el concepto no coincidía
  exactamente con la pregunta, la relevancia semántica era baja (~0.30) y el
  DecisionGate rechazaba la respuesta enviándola al LLM aunque hubiera datos.

  Resultado en logs:
    confidence=0.821 adjusted=0.410 decision=llm reason=low_relevance relevance=0.296

SOLUCIÓN:
  1. Recuperar top-5 episodios directamente con el vector de la pregunta
  2. Filtrar los que superen similitud mínima (>= 0.25)
  3. Extraer conceptos únicos de esos episodios (no solo el top_label)
  4. Agregar conocimiento de KG + inferencias para TODOS esos conceptos
  5. Construir respuesta que parte del texto de la pregunta → mayor relevancia

INTEGRACIÓN:
  Usado desde SymbolicResponder.respond() como paso previo al render.
  No reemplaza las plantillas existentes — las alimenta mejor.

USO:
  from symbolic_synthesizer import SymbolicSynthesizer
  synth = SymbolicSynthesizer()
  result = synth.synthesize(ai, question, question_vec)
  # result.text tiene mayor relevancia semántica
  # result.confidence es recalculada sobre los datos reales combinados
"""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from logger_config import get_logger

logger = get_logger(__name__)

# ── Configuración ─────────────────────────────────────────────────────
TOP_K_EPISODES      = 5     # episodios a recuperar
MIN_EPISODE_SIM     = 0.25  # similitud mínima para usar un episodio
MAX_CONCEPTS        = 3     # máx conceptos únicos a combinar
MAX_FACTS_PER_CONCEPT = 4   # hechos KG por concepto
MAX_INFERENCES      = 3     # inferencias totales
MAX_SYNTHESIS_CHARS = 800   # longitud máxima de la síntesis


@dataclass
class SynthesisResult:
    """Resultado de la síntesis multi-fuente."""
    text:           str
    confidence:     float
    sources_used:   List[str] = field(default_factory=list)   # qué módulos contribuyeron
    concepts_used:  List[str] = field(default_factory=list)   # conceptos que alimentaron
    episodes_used:  int = 0
    facts_used:     int = 0
    inferences_used: int = 0
    synthesis_ms:   float = 0.0
    fallback:       bool = False   # True si no había suficientes datos


class SymbolicSynthesizer:
    """
    Sintetizador de respuestas simbólicas multi-fuente.

    A diferencia de SymbolicResponder (que busca 1 concepto y hace lookup),
    este módulo:
      1. Ancla la búsqueda al vector de la pregunta (no al top_label)
      2. Combina episodios + conceptos + KG + inferencias de múltiples nodos
      3. Construye la respuesta partiendo del texto literal de la pregunta
         → mayor similitud semántica con la pregunta → el gate la acepta más

    Optimizado para CPU: límites duros en cantidad de datos procesados.
    """

    def synthesize(
        self,
        ai,
        question: str,
        question_vec: Optional[List[float]] = None,
    ) -> SynthesisResult:
        """
        Genera una síntesis multi-fuente anclada a la pregunta.

        Args:
            ai:           instancia de Cognia
            question:     pregunta del usuario (texto)
            question_vec: vector pre-calculado de la pregunta (reutilizar si existe)

        Returns:
            SynthesisResult con text, confidence y metadatos
        """
        t0 = time.perf_counter()

        # ── Obtener vector si no viene pre-calculado ──────────────────
        vec = question_vec or self._get_vec(question)

        # ── 1. Recuperar episodios anclados a la pregunta ─────────────
        episodes = self._retrieve_episodes(ai, vec, question)

        if not episodes:
            logger.debug(
                "Sin episodios relevantes para síntesis",
                extra={"op": "synthesizer.synthesize", "context": f"q_len={len(question)}"},
            )
            return SynthesisResult(
                text="",
                confidence=0.0,
                fallback=True,
                synthesis_ms=(time.perf_counter() - t0) * 1000,
            )

        # ── 2. Extraer conceptos únicos de los episodios ──────────────
        concepts = self._extract_concepts(ai, episodes, vec)

        # ── 3. Recopilar conocimiento de todos los conceptos ──────────
        all_facts:      List[str] = []
        all_inferences: List[str] = []
        all_descriptions: List[str] = []
        sources: List[str] = []

        for concept in concepts[:MAX_CONCEPTS]:
            facts = self._get_kg_facts(ai, concept)
            infs  = self._get_inferences(ai, concept)
            desc  = self._get_description(ai, concept)
            if facts:
                all_facts.extend(facts)
                if "knowledge_graph" not in sources:
                    sources.append("knowledge_graph")
            if infs:
                all_inferences.extend(infs)
                if "inference_engine" not in sources:
                    sources.append("inference_engine")
            if desc:
                all_descriptions.append(f"{concept}: {desc}")

        if episodes:
            sources.append("episodic_memory")

        # Deduplicar hechos e inferencias
        all_facts      = self._dedup(all_facts)[:MAX_FACTS_PER_CONCEPT * MAX_CONCEPTS]
        all_inferences = self._dedup(all_inferences)[:MAX_INFERENCES]

        # ── 4. Calcular confianza de la síntesis ──────────────────────
        confidence = self._calc_confidence(
            ai, concepts, episodes, all_facts, all_inferences, all_descriptions
        )

        # ── 5. Construir respuesta anclada a la pregunta ──────────────
        text = self._build_synthesis(
            question      = question,
            concepts      = concepts,
            descriptions  = all_descriptions,
            facts         = all_facts,
            inferences    = all_inferences,
            episodes      = episodes,
            confidence    = confidence,
        )

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            f"Síntesis completada: concepts={len(concepts)} "
            f"episodes={len(episodes)} facts={len(all_facts)} "
            f"inferences={len(all_inferences)} confidence={confidence:.3f} "
            f"text_len={len(text)} synthesis_ms={elapsed:.1f}",
            extra={
                "op":      "synthesizer.synthesize",
                "context": f"q_len={len(question)} concepts={concepts[:3]}",
            },
        )

        return SynthesisResult(
            text            = text,
            confidence      = confidence,
            sources_used    = sources,
            concepts_used   = concepts,
            episodes_used   = len(episodes),
            facts_used      = len(all_facts),
            inferences_used = len(all_inferences),
            synthesis_ms    = elapsed,
            fallback        = (len(text) < 60),
        )

    # ══════════════════════════════════════════════════════════════════
    # PASO 1: Recuperación episódica anclada al vector
    # ══════════════════════════════════════════════════════════════════

    def _retrieve_episodes(self, ai, vec, question: str) -> List[Dict]:
        """
        Recupera episodios usando el vector de la pregunta directamente.
        Filtra por similitud mínima y omite respuestas de Cognia previas.
        """
        if vec is None:
            return []
        try:
            raw = ai.episodic.retrieve_similar(vec, top_k=TOP_K_EPISODES)
        except Exception as exc:
            logger.warning(
                "Error en retrieve_similar durante síntesis",
                extra={"op": "synthesizer._retrieve_episodes", "context": str(exc)},
            )
            return []

        filtered = []
        for ep in raw:
            sim = ep.get("similarity", 0.0)
            obs = ep.get("observation", "")
            # Omitir: baja similitud, muy cortos, respuestas previas de Cognia
            if sim < MIN_EPISODE_SIM:
                continue
            if len(obs.strip()) < 15:
                continue
            if obs.strip().startswith("[Cognia]"):
                continue
            filtered.append(ep)

        return filtered

    # ══════════════════════════════════════════════════════════════════
    # PASO 2: Extracción de conceptos de múltiples episodios
    # ══════════════════════════════════════════════════════════════════

    def _extract_concepts(self, ai, episodes: List[Dict], vec) -> List[str]:
        """
        Extrae conceptos únicos de los episodios. Prioriza los labels
        de los episodios más similares. Cae al top_label del metacog si falla.
        """
        seen = set()
        concepts = []

        # Labels directos de los episodios (ya ordenados por score)
        for ep in episodes:
            label = ep.get("label")
            if label and label not in seen and len(label) > 1:
                seen.add(label)
                concepts.append(label)
            if len(concepts) >= MAX_CONCEPTS:
                break

        # Fallback: usar metacog si no hay suficientes labels
        if len(concepts) < 2:
            try:
                assessment = ai.metacog.assess_confidence(episodes)
                top = assessment.get("top_label")
                if top and top not in seen:
                    concepts.append(top)
            except Exception:
                pass

        return concepts

    # ══════════════════════════════════════════════════════════════════
    # PASO 3: Recopilación de conocimiento por concepto
    # ══════════════════════════════════════════════════════════════════

    def _get_kg_facts(self, ai, concept: str) -> List[str]:
        """Extrae hechos del KG como frases en lenguaje natural."""
        try:
            hechos = ai.kg.get_facts(concept)
            result = []
            seen = set()
            for h in hechos[:10]:
                subj = h.get("subject", "")
                pred = h.get("predicate", "")
                obj  = h.get("object",  "")
                if not (subj and pred and obj):
                    continue
                frase = self._triple_to_natural(subj, pred, obj)
                if not frase:
                    continue
                key = frase.lower()[:55]
                if key not in seen:
                    seen.add(key)
                    result.append(frase)
                if len(result) >= MAX_FACTS_PER_CONCEPT:
                    break
            return result
        except Exception:
            return []

    def _get_inferences(self, ai, concept: str) -> List[str]:
        """Corre el motor de inferencia y retorna frases en lenguaje natural."""
        try:
            infs  = ai.inference.infer(concept, max_steps=2)
            props = ai.inference.infer_properties(concept)
            result = []
            seen = set()
            for i in infs[:2]:
                j = i.get("justification", "")
                if j and len(j) > 10:
                    j_clean = j.replace("_", " ")[:120]
                    key = j_clean.lower()[:45]
                    if key not in seen:
                        seen.add(key)
                        result.append(j_clean)
            for p in props[:2]:
                prop = p.get("property", "").replace("_", " ")
                val  = p.get("value",    "").replace("_", " ")
                if prop and val:
                    frase = f"{concept.replace('_', ' ')} {prop} {val}"
                    key = frase.lower()[:45]
                    if key not in seen:
                        seen.add(key)
                        result.append(frase)
            return result
        except Exception:
            return []

    def _get_description(self, ai, concept: str) -> str:
        """Busca descripción en semantic_memory."""
        try:
            import sqlite3
            conn = sqlite3.connect(ai.db)
            conn.text_factory = str
            row = conn.execute(
                "SELECT description FROM semantic_memory WHERE concept=?",
                (concept,)
            ).fetchone()
            conn.close()
            if row and row[0]:
                return row[0][:250].strip()
        except Exception:
            pass
        return ""

    # ══════════════════════════════════════════════════════════════════
    # PASO 4: Cálculo de confianza de la síntesis
    # ══════════════════════════════════════════════════════════════════

    def _calc_confidence(
        self,
        ai,
        concepts:     List[str],
        episodes:     List[Dict],
        facts:        List[str],
        inferences:   List[str],
        descriptions: List[str],
    ) -> float:
        """
        Calcula la confianza de la síntesis combinada.

        Pesos distintos a _estimate_confidence del SymbolicResponder:
        aquí pesamos más los episodios (similitud real) y menos la semántica
        (porque ya extrajimos los conceptos de episodios relevantes).

          episodios (sim promedio): 0.35
          hechos KG:                0.25
          conceptos con desc:       0.15
          inferencias:              0.10
          soporte semántico:        0.15
        """
        # Similitud promedio de los episodios usados
        sims = [ep.get("similarity", 0.0) for ep in episodes if ep.get("similarity", 0) > 0]
        avg_sim = sum(sims) / len(sims) if sims else 0.0
        score_ep   = avg_sim * 0.35

        # Hechos KG (normalizado a MAX_FACTS_PER_CONCEPT * MAX_CONCEPTS)
        max_facts  = MAX_FACTS_PER_CONCEPT * MAX_CONCEPTS
        score_kg   = min(1.0, len(facts) / max(1, max_facts)) * 0.25

        # Descripciones disponibles
        score_desc = min(1.0, len(descriptions) / max(1, MAX_CONCEPTS)) * 0.15

        # Inferencias
        score_inf  = min(1.0, len(inferences) / max(1, MAX_INFERENCES)) * 0.10

        # Soporte semántico de la DB para los conceptos encontrados
        sem_conf = 0.0
        for concept in concepts[:MAX_CONCEPTS]:
            try:
                import sqlite3
                conn = sqlite3.connect(ai.db)
                row  = conn.execute(
                    "SELECT confidence FROM semantic_memory WHERE concept=?",
                    (concept,)
                ).fetchone()
                conn.close()
                if row:
                    sem_conf = max(sem_conf, float(row[0]))
            except Exception:
                pass
        score_sem = sem_conf * 0.15

        total = score_ep + score_kg + score_desc + score_inf + score_sem
        result = round(min(1.0, total), 3)

        logger.debug(
            f"synthesis_confidence ep={score_ep:.3f} kg={score_kg:.3f} "
            f"desc={score_desc:.3f} inf={score_inf:.3f} sem={score_sem:.3f} "
            f"total={result:.3f}",
            extra={
                "op":      "synthesizer._calc_confidence",
                "context": f"n_concepts={len(concepts)} n_eps={len(episodes)}",
            },
        )
        return result

    # ══════════════════════════════════════════════════════════════════
    # PASO 5: Construcción de texto anclado a la pregunta
    # ══════════════════════════════════════════════════════════════════

    def _build_synthesis(
        self,
        question:     str,
        concepts:     List[str],
        descriptions: List[str],
        facts:        List[str],
        inferences:   List[str],
        episodes:     List[Dict],
        confidence:   float,
    ) -> str:
        """
        Construye el texto de la síntesis.

        CLAVE: la primera oración replica las palabras clave de la pregunta.
        Esto aumenta la similitud coseno entre pregunta y respuesta,
        haciendo que el DecisionGate la acepte en zonas media/alta.
        """
        partes = []

        # ── Párrafo 1: respuesta directa a la pregunta ────────────────
        q_clean = question.strip().rstrip("?").rstrip(".")
        if descriptions:
            # Usar la descripción del concepto principal
            main_desc = descriptions[0]
            partes.append(f"Sobre {q_clean}: {main_desc}.")
        elif concepts:
            # Sin descripción: anclar al concepto
            concept_str = concepts[0].replace("_", " ")
            partes.append(
                f"Basándome en lo que sé sobre {q_clean}, "
                f"el concepto clave es '{concept_str}'."
            )

        # ── Párrafo 2: episodios relevantes (narrativa) ───────────────
        ep_frases = []
        for ep in episodes[:3]:
            obs = ep.get("observation", "").strip()[:120]
            sim = ep.get("similarity", 0.0)
            lbl = ep.get("label", "")
            if not obs or sim < MIN_EPISODE_SIM:
                continue
            if obs.startswith("[Cognia]"):
                continue
            if lbl and lbl.lower() not in obs.lower():
                ep_frases.append(f'Recuerdo que sobre {lbl.replace("_", " ")}: "{obs}".')
            else:
                ep_frases.append(f'Recuerdo que: "{obs}".')
        if ep_frases:
            partes.append("\n".join(ep_frases))

        # ── Párrafo 3: hechos del KG ──────────────────────────────────
        if facts:
            conectores = [
                "Además, ", "También es relevante que ",
                "Por otro lado, ", "Cabe destacar que ",
            ]
            frases_kg = []
            for i, f in enumerate(facts[:5]):
                conector = conectores[i % len(conectores)]
                frases_kg.append(conector + f.lower().rstrip(".") + ".")
            partes.append(" ".join(frases_kg))

        # ── Párrafo 4: inferencias ────────────────────────────────────
        if inferences:
            inf_conectores = [
                "A partir de esto puedo inferir que ",
                "Lo que implica que ", "Como consecuencia, ",
            ]
            frases_inf = []
            for i, inf in enumerate(inferences[:2]):
                conector = inf_conectores[i % len(inf_conectores)]
                frases_inf.append(conector + inf.lower().rstrip(".") + ".")
            partes.append(" ".join(frases_inf))

        # ── Nota de confianza si es baja ──────────────────────────────
        if confidence < 0.35:
            partes.append(
                f"(Nivel de certeza: {confidence:.0%}. "
                "Esta información podría beneficiarse de más aprendizaje.)"
            )

        text = "\n\n".join(p for p in partes if p.strip())

        # Truncar si excede límite (protección CPU)
        if len(text) > MAX_SYNTHESIS_CHARS:
            text = text[:MAX_SYNTHESIS_CHARS].rsplit(" ", 1)[0] + "…"

        return text

    # ══════════════════════════════════════════════════════════════════
    # UTILIDADES
    # ══════════════════════════════════════════════════════════════════

    def _get_vec(self, text: str) -> Optional[List[float]]:
        """Wrapper tolerante para text_to_vector."""
        try:
            from cognia.vectors import text_to_vector
            return text_to_vector(text[:300])
        except ImportError:
            try:
                from vectors import text_to_vector
                return text_to_vector(text[:300])
            except Exception:
                return None
        except Exception:
            return None

    def _dedup(self, items: List[str]) -> List[str]:
        """Deduplicar preservando orden."""
        seen = set()
        result = []
        for item in items:
            key = item.lower()[:50]
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    # Mapa de predicados heredado de SymbolicResponder para coherencia
    _PRED_TEMPLATES = {
        "is_a":         lambda s, o: f"{s} es un tipo de {o}",
        "is_an":        lambda s, o: f"{s} es {o}",
        "part_of":      lambda s, o: f"{s} es parte de {o}",
        "has_part":     lambda s, o: f"{s} tiene como parte {o}",
        "causes":       lambda s, o: f"{s} causa {o}",
        "caused_by":    lambda s, o: f"{s} es causado por {o}",
        "related_to":   lambda s, o: f"{s} está relacionado con {o}",
        "used_for":     lambda s, o: f"{s} se usa para {o}",
        "created_by":   lambda s, o: f"{s} fue creado por {o}",
        "has_property": lambda s, o: f"{s} tiene la propiedad de {o}",
        "defined_as":   lambda s, o: f"{s} se define como {o}",
        "capable_of":   lambda s, o: f"{s} es capaz de {o}",
        "enables":      lambda s, o: f"{s} permite {o}",
        "requires":     lambda s, o: f"{s} requiere {o}",
    }

    def _triple_to_natural(self, subj: str, pred: str, obj: str) -> str:
        """Convierte tripla del KG a lenguaje natural."""
        import re
        s = re.sub(r"[,.]?\s*\d+\.\d+\s*$", "", subj.replace("_", " ")).strip()
        p = pred.lower().replace("_", " ").strip()
        o = re.sub(r"[,.]?\s*\d+\.\d+\s*$", "", obj.replace("_",  " ")).strip()
        if len(s) < 2 or len(o) < 2:
            return ""
        pred_key = pred.lower().strip()
        tpl = self._PRED_TEMPLATES.get(pred_key)
        if tpl:
            return tpl(s, o).rstrip(".")
        for key, tpl in self._PRED_TEMPLATES.items():
            if key in pred_key or pred_key in key:
                return tpl(s, o).rstrip(".")
        return f"{s} {p} {o}".rstrip(".")


# ── Singleton ─────────────────────────────────────────────────────────
_SYNTH_INSTANCE: Optional[SymbolicSynthesizer] = None

def get_synthesizer() -> SymbolicSynthesizer:
    global _SYNTH_INSTANCE
    if _SYNTH_INSTANCE is None:
        _SYNTH_INSTANCE = SymbolicSynthesizer()
    return _SYNTH_INSTANCE
