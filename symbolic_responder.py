"""
symbolic_responder.py — Cognia Language Engine
================================================
Construye respuestas en lenguaje natural usando ÚNICAMENTE el
conocimiento estructurado de Cognia (KG, inferencias, semántica,
episodios) SIN llamar al LLM.

Cuándo se usa:
  - El concepto tiene confianza >= UMBRAL_CONFIANZA
  - El tipo de pregunta es clasificable (definición, lista, estado)
  - La fatiga cognitiva es alta (modo fallback forzado)

Retorna:
  SymbolicResponse con .text (str) y .confidence (float 0-1)
  Si confidence < UMBRAL_MINIMO el HybridGenerator decide llamar al LLM.
"""

import random
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from logger_config import get_logger as _get_sr_logger

# ── PASO 4: Sintetizador multi-fuente ────────────────────────────────
try:
    from cognia.symbolic_synthesizer import get_synthesizer
    HAS_SYNTHESIZER = True
except ImportError:
    try:
        from symbolic_synthesizer import get_synthesizer
        HAS_SYNTHESIZER = True
    except ImportError:
        HAS_SYNTHESIZER = False
_sr_logger = _get_sr_logger(__name__)

# ── Umbrales de confianza para respuesta simbólica ────────────────────
UMBRAL_CONFIANZA  = 0.55   # por encima → responder sin LLM
UMBRAL_MINIMO     = 0.30   # por debajo → forzar LLM
UMBRAL_FALLBACK   = 0.42   # zona gris → respuesta parcial + LLM enriquece


@dataclass
class SymbolicResponse:
    text:         str
    confidence:   float          # 0-1: qué tan segura es la respuesta
    used_llm:     bool = False
    sources:      List[str] = field(default_factory=list)   # qué módulos contribuyeron
    question_type: str = "unknown"


# ══════════════════════════════════════════════════════════════════════
# CLASIFICADOR DE PREGUNTAS (sin dependencias externas)
# ══════════════════════════════════════════════════════════════════════

class QuestionClassifier:
    """
    Clasifica el tipo semántico de una pregunta en español/inglés.
    Sin ML — solo patrones léxicos ordenados por especificidad.
    Retorna (tipo, confianza_clasificacion).
    """

    PATTERNS: List[tuple] = [
        # (tipo, patrones_es, patrones_en, confianza)
        ("definicion",
         ["qué es", "que es", "qué son", "que son", "define", "definición",
          "definicion", "significa", "significado", "concepto de"],
         ["what is", "what are", "define", "definition", "meaning of", "what does"],
         0.9),
        ("comparacion",
         ["diferencia entre", "diferencias", "compara", "comparar",
          "versus", "vs", "mejor entre", "cuál es mejor"],
         ["difference between", "compare", "versus", "vs", "which is better"],
         0.88),
        ("lista",
         ["cuáles son", "cuales son", "menciona", "enumera", "lista de",
          "tipos de", "ejemplos de", "dame ejemplos", "características"],
         ["what are the", "list", "enumerate", "types of", "examples of",
          "characteristics of", "features of"],
         0.85),
        ("como_funciona",
         ["cómo funciona", "como funciona", "cómo trabaja", "como trabaja",
          "cómo se hace", "como se hace", "explica cómo", "explica como",
          "proceso de", "pasos para"],
         ["how does", "how do", "how to", "explain how", "process of",
          "steps to", "how it works"],
         0.87),
        ("historia",
         ["historia de", "origen de", "cuándo", "cuando", "quién inventó",
          "quien invento", "fue creado", "fue descubierto"],
         ["history of", "origin of", "when was", "who invented",
          "was created", "was discovered"],
         0.82),
        ("estado",
         ["cómo está", "como esta", "cuál es el estado", "estado actual",
          "últimas noticias", "actualmente"],
         ["what is the status", "current state", "how is", "latest"],
         0.75),
        ("confirmacion",
         ["es verdad", "es cierto", "existe", "hay", "tienes información",
          "sabes algo", "conoces"],
         ["is it true", "does it exist", "is there", "do you know about"],
         0.80),
        ("corta",       [], [], 0.70),   # fallback para preguntas <= 4 palabras
    ]

    def classify(self, question: str) -> tuple:
        q = question.lower().strip()
        words = q.split()

        # Preguntas muy cortas
        if len(words) <= 4:
            return ("corta", 0.70)

        for tipo, pats_es, pats_en, conf in self.PATTERNS[:-1]:
            for pat in pats_es + pats_en:
                if pat in q:
                    return (tipo, conf)

        return ("general", 0.60)


# ══════════════════════════════════════════════════════════════════════
# PLANTILLAS SEMÁNTICAS
# ══════════════════════════════════════════════════════════════════════

class SemanticTemplates:
    """
    Plantillas parametrizadas para cada tipo de pregunta.
    Los {tokens} se rellenan con datos reales del KG y memoria.
    """

    # Variantes para no repetir siempre la misma frase
    _INTROS_DEFINICION = [
        "{concepto} es {descripcion}.",
        "Según mi memoria, {concepto} se refiere a {descripcion}.",
        "{concepto} puede entenderse como {descripcion}.",
    ]
    _INTROS_IGNORANTE = [
        "No tengo información detallada sobre '{concepto}' en mi memoria aún.",
        "Mi conocimiento sobre '{concepto}' es limitado por el momento.",
        "No he aprendido suficiente sobre '{concepto}' todavía.",
    ]
    _CONECTORES_HECHOS = [
        "Además, ", "Por otro lado, ", "También es relevante que ",
        "Cabe destacar que ", "En relación a esto, ",
    ]
    _CONECTORES_INFERENCIA = [
        "A partir de esto puedo inferir que ", "Esto me lleva a concluir que ",
        "Como consecuencia, ", "Lo que implica que ",
    ]

    def render_definicion(self, concepto: str, descripcion: str,
                          hechos: List[str], inferencias: List[str],
                          confianza: float) -> str:
        partes = []

        # Párrafo 1: definición
        intro = random.choice(self._INTROS_DEFINICION)
        partes.append(intro.format(concepto=concepto, descripcion=descripcion))

        # Párrafo 2: hechos del KG (máx 3)
        if hechos:
            frases_hechos = []
            for i, h in enumerate(hechos[:3]):
                conector = self._CONECTORES_HECHOS[i % len(self._CONECTORES_HECHOS)]
                frases_hechos.append(conector + h.lower().rstrip(".") + ".")
            partes.append(" ".join(frases_hechos))

        # Párrafo 3: inferencias (máx 2)
        if inferencias:
            frases_inf = []
            for i, inf in enumerate(inferencias[:2]):
                conector = self._CONECTORES_INFERENCIA[i % len(self._CONECTORES_INFERENCIA)]
                frases_inf.append(conector + inf.lower().rstrip(".") + ".")
            partes.append(" ".join(frases_inf))

        # Nota de confianza si es baja
        if confianza < UMBRAL_CONFIANZA:
            partes.append(
                f"(Mi confianza en esta información es del {confianza:.0%}; "
                "podría beneficiarse de más aprendizaje.)"
            )

        return "\n\n".join(partes)

    def render_lista(self, concepto: str, items: List[str],
                     intro_custom: str = "") -> str:
        if not items:
            return f"No tengo una lista específica sobre {concepto} en mi memoria."
        intro = intro_custom or f"Lo que sé sobre {concepto}:"
        lista = "\n".join(f"  • {item.strip().rstrip('.')}" for item in items[:6])
        return f"{intro}\n{lista}"

    def render_comparacion(self, concepto_a: str, concepto_b: str,
                           hechos_a: List[str], hechos_b: List[str]) -> str:
        partes = [f"Comparando {concepto_a} y {concepto_b}:"]
        if hechos_a:
            partes.append(f"Sobre {concepto_a}: {'; '.join(hechos_a[:3])}.")
        if hechos_b:
            partes.append(f"Sobre {concepto_b}: {'; '.join(hechos_b[:3])}.")
        if not hechos_a and not hechos_b:
            partes.append(
                "No tengo suficiente información sobre ambos conceptos para compararlos en detalle."
            )
        return "\n\n".join(partes)

    def render_ignorante(self, concepto: str) -> str:
        return random.choice(self._INTROS_IGNORANTE).format(concepto=concepto)

    def render_episodios(self, episodios: List[Dict], max_n: int = 3) -> str:
        """Genera un resumen narrativo de episodios similares, en lenguaje natural."""
        if not episodios:
            return ""
        frases = []
        for ep in episodios[:max_n]:
            obs = ep.get("observation", "")[:120].strip()
            sim = ep.get("similarity", 0)
            lbl = ep.get("label", "")
            if not obs or sim <= 0.3:
                continue
            # Omitir si el episodio empieza con "[Cognia]:" (respuesta anterior)
            if obs.startswith("[Cognia]"):
                continue
            # Usar el label como contexto si existe y es diferente al texto
            if lbl and lbl.lower() not in obs.lower():
                frases.append(f'Recuerdo que sobre {lbl.replace("_", " ")}: "{obs}".')
            else:
                frases.append(f'Recuerdo que: "{obs}".')
        return "\n".join(frases)


# ══════════════════════════════════════════════════════════════════════
# SYMBOLIC RESPONDER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class SymbolicResponder:
    """
    Genera respuestas usando solo conocimiento estructurado de Cognia.

    Pipeline:
      1. Clasificar pregunta → tipo semántico
      2. Extraer conocimiento (KG, semántica, inferencias, episodios)
      3. Calcular confianza de respuesta
      4. Renderizar plantilla semántica
      5. Retornar SymbolicResponse con confianza

    Si confianza < UMBRAL_MINIMO → el HybridGenerator enviará al LLM.
    Si confianza entre UMBRAL_FALLBACK y UMBRAL_CONFIANZA → respuesta
    parcial que el LLM puede enriquecer opcionalmente.
    """

    def __init__(self):
        self.classifier = QuestionClassifier()
        self.templates  = SemanticTemplates()

    def respond(self, cognia_instance, question: str,
                cognitive_context: Dict[str, Any] = None) -> SymbolicResponse:
        """
        Genera una respuesta simbólica.

        Args:
            cognia_instance: instancia de Cognia (acceso a todos los módulos)
            question:        pregunta del usuario
            cognitive_context: resultado previo de construir_contexto() si existe

        Returns:
            SymbolicResponse
        """
        ai = cognia_instance
        q_type, q_conf = self.classifier.classify(question)
        sources = []

        # ── PASO 4: Intentar síntesis multi-fuente primero ───────────
        # La síntesis ancla la respuesta al vector de la pregunta,
        # produciendo mayor relevancia semántica que el lookup por concepto.
        # Si produce texto suficiente, se usa directamente.
        # Si no, se cae al pipeline de lookup original (compatibilidad).
        if HAS_SYNTHESIZER:
            try:
                _synth = get_synthesizer()
                _vec_q = None
                try:
                    from cognia.vectors import text_to_vector as _ttv
                    _vec_q = _ttv(question)
                except ImportError:
                    try:
                        from vectors import text_to_vector as _ttv
                        _vec_q = _ttv(question)
                    except Exception:
                        pass

                _sr   = _synth.synthesize(ai, question, _vec_q)

                _sr_logger.info(
                    f"synthesis used={not _sr.fallback} "
                    f"episodes={_sr.episodes_used} facts={_sr.facts_used} "
                    f"inferences={_sr.inferences_used} "
                    f"confidence={_sr.confidence:.3f} "
                    f"concepts={_sr.concepts_used[:3]} "
                    f"synthesis_ms={_sr.synthesis_ms:.1f}",
                    extra={
                        "op":      "symbolic_responder.respond",
                        "context": f"q_type={q_type} synthesizer=paso4",
                    },
                )

                # Usar síntesis si tiene texto suficiente y confianza mínima
                if not _sr.fallback and _sr.confidence >= 0.12:
                    return SymbolicResponse(
                        text          = _sr.text,
                        confidence    = _sr.confidence,
                        used_llm      = False,
                        sources       = _sr.sources_used,
                        question_type = q_type,
                    )
            except Exception as _synth_exc:
                _sr_logger.warning(
                    "Síntesis multi-fuente falló, usando lookup original",
                    extra={
                        "op":      "symbolic_responder.respond",
                        "context": str(_synth_exc),
                    },
                )

        # ── Fallback: pipeline de lookup original ─────────────────────
        # Se ejecuta si HAS_SYNTHESIZER=False o si la síntesis no produjo
        # resultado suficiente. Compatibilidad total con pasos anteriores.

        # ── 1. Identificar concepto principal ────────────────────────
        concepto = self._extract_main_concept(ai, question)
        if not concepto:
            return SymbolicResponse(
                text=self.templates.render_ignorante("este tema"),
                confidence=0.10,
                question_type=q_type,
            )

        # ── 2. Recopilar conocimiento ─────────────────────────────────
        descripcion  = self._get_description(ai, concepto)
        hechos_kg    = self._get_kg_facts(ai, concepto)
        inferencias  = self._get_inferences(ai, concepto)
        episodios    = self._get_similar_episodes(ai, question)
        activaciones = self._get_activations(ai, concepto)

        if hechos_kg:    sources.append("knowledge_graph")
        if inferencias:  sources.append("inference_engine")
        if episodios:    sources.append("episodic_memory")
        if activaciones: sources.append("semantic_memory")

        # ── 3. Calcular confianza de respuesta ────────────────────────
        conf = self._estimate_confidence(ai, concepto, descripcion,
                                         hechos_kg, inferencias, episodios,
                                         question=question)

        # ── 4. Renderizar según tipo de pregunta ──────────────────────
        if conf < 0.15 or (not descripcion and not hechos_kg and not episodios):
            text = self.templates.render_ignorante(concepto)
            conf = 0.12
        elif q_type == "lista":
            items = self._collect_list_items(hechos_kg, activaciones, inferencias)
            text = self.templates.render_lista(concepto, items)
        elif q_type == "comparacion":
            concepto_b = self._extract_second_concept(question, concepto)
            hechos_b   = self._get_kg_facts(ai, concepto_b) if concepto_b else []
            text = self.templates.render_comparacion(
                concepto, concepto_b or "el otro concepto", hechos_kg, hechos_b
            )
        else:
            ep_text = self.templates.render_episodios(episodios)
            hechos_combinados = hechos_kg.copy()
            if ep_text:
                hechos_combinados.insert(0, ep_text)
            text = self.templates.render_definicion(
                concepto=concepto,
                descripcion=descripcion or f"un concepto en mi memoria con confianza {conf:.0%}",
                hechos=hechos_combinados,
                inferencias=inferencias,
                confianza=conf,
            )

        return SymbolicResponse(
            text=text,
            confidence=conf,
            used_llm=False,
            sources=sources,
            question_type=q_type,
        )

    # ── Helpers privados ─────────────────────────────────────────────

    def _extract_main_concept(self, ai, question: str) -> Optional[str]:
        """Usa el pipeline cognitivo existente para extraer el concepto principal."""
        try:
            from cognia.vectors import text_to_vector
            vec = text_to_vector(question)
            similares = ai.episodic.retrieve_similar(vec, top_k=5)
            assessment = ai.metacog.assess_confidence(similares)
            label = assessment.get("top_label")
            return label
        except Exception:
            return None

    def _get_description(self, ai, concepto: str) -> str:
        """Busca descripción en semantic_memory."""
        try:
            import sqlite3
            conn = sqlite3.connect(ai.db)
            conn.text_factory = str
            row = conn.execute(
                "SELECT description FROM semantic_memory WHERE concept=?",
                (concepto,)
            ).fetchone()
            conn.close()
            if row and row[0]:
                return row[0][:300]
        except Exception:
            pass
        return ""

    # ── Mapa de predicados → plantillas de lenguaje natural ──────────
    _PRED_TEMPLATES = {
        "is_a":         lambda s, o: f"{s} es un tipo de {o}",
        "is_an":        lambda s, o: f"{s} es {o}",
        "part_of":      lambda s, o: f"{s} es parte de {o}",
        "has_part":     lambda s, o: f"{s} tiene como parte {o}",
        "causes":       lambda s, o: f"{s} causa {o}",
        "caused_by":    lambda s, o: f"{s} es causado por {o}",
        "related_to":   lambda s, o: f"{s} está relacionado con {o}",
        "similar_to":   lambda s, o: f"{s} es similar a {o}",
        "opposite_of":  lambda s, o: f"{s} es lo contrario de {o}",
        "used_for":     lambda s, o: f"{s} se usa para {o}",
        "created_by":   lambda s, o: f"{s} fue creado por {o}",
        "belongs_to":   lambda s, o: f"{s} pertenece a {o}",
        "has_property": lambda s, o: f"{s} tiene la propiedad de {o}",
        "instance_of":  lambda s, o: f"{s} es una instancia de {o}",
        "type_of":      lambda s, o: f"{s} es un tipo de {o}",
        "defined_as":   lambda s, o: f"{s} se define como {o}",
        "located_in":   lambda s, o: f"{s} se encuentra en {o}",
        "made_of":      lambda s, o: f"{s} está hecho de {o}",
        "capable_of":   lambda s, o: f"{s} es capaz de {o}",
        "derives_from": lambda s, o: f"{s} deriva de {o}",
        "subcategory_of": lambda s, o: f"{s} es una subcategoría de {o}",
        "enables":      lambda s, o: f"{s} permite {o}",
        "requires":     lambda s, o: f"{s} requiere {o}",
        "produces":     lambda s, o: f"{s} produce {o}",
        "influences":   lambda s, o: f"{s} influye en {o}",
        "contains":     lambda s, o: f"{s} contiene {o}",
    }

    @staticmethod
    def _clean_kg_field(value: str) -> str:
        """
        Elimina artefactos de datos del sistema que se cuelan en campos del KG:
          - Numeros flotantes residuales (.0, 0.0, ,0.5)
          - Niveles de fatiga (baja, moderada, alta, critica)
          - Puntuacion residual al final
        """
        import re
        value = re.sub(r"[,.]?\s*\d+\.\d+\s*$", "", value).strip()
        value = re.sub(
            r"\s*(baja|moderada|alta|critica|normal|low|high|critical)\s*$",
            "", value, flags=re.IGNORECASE
        ).strip()
        value = value.rstrip(",.;:").strip()
        return value

    def _triple_to_natural(self, subj: str, pred: str, obj: str) -> str:
        """Convierte una tripla del KG en lenguaje natural legible."""
        import re
        # Limpiar guiones bajos de todos los campos + artefactos de sistema
        s = self._clean_kg_field(subj.replace("_", " ").strip())
        p = self._clean_kg_field(pred.lower().replace("_", " ").strip())
        o = self._clean_kg_field(obj.replace("_", " ").strip())

        # Omitir triplas con terminos tecnicos internos o muy cortos
        if len(s) < 2 or len(o) < 2:
            return ""
        if any(t in o for t in ["concepto_investigado", "en_ingles"]):
            m = re.search(r'\(([^)]+)\)', o)
            o = m.group(1) if m else o.split("_")[0]

        # Buscar plantilla exacta primero
        pred_key = pred.lower().strip()
        tpl = self._PRED_TEMPLATES.get(pred_key)
        if tpl:
            return tpl(s, o).rstrip(".")

        # Buscar plantilla por prefijo/substring
        for key, tpl in self._PRED_TEMPLATES.items():
            if key in pred_key or pred_key in key:
                return tpl(s, o).rstrip(".")

        # Fallback genérico: construir frase natural con el predicado limpio
        return f"{s} {p} {o}".rstrip(".")

    def _get_kg_facts(self, ai, concepto: str) -> List[str]:
        """Extrae hechos del KG como frases en lenguaje natural."""
        try:
            hechos = ai.kg.get_facts(concepto)
            result = []
            seen = set()
            for h in hechos[:12]:
                subj = h.get("subject", "")
                pred = h.get("predicate", "")
                obj  = h.get("object", "")
                if not (subj and pred and obj):
                    continue
                frase = self._triple_to_natural(subj, pred, obj)
                if not frase:
                    continue
                key = frase.lower()[:60]
                if key in seen:
                    continue
                seen.add(key)
                result.append(frase)
                if len(result) >= 6:
                    break
            return result
        except Exception:
            return []

    def _get_inferences(self, ai, concepto: str) -> List[str]:
        """Corre el motor de inferencia simbólico y retorna frases en lenguaje natural."""
        try:
            infs  = ai.inference.infer(concepto, max_steps=2)
            props = ai.inference.infer_properties(concepto)
            result = []
            seen = set()
            for i in infs[:3]:
                j = i.get("justification", "")
                if j and len(j) > 10:
                    # Limpiar guiones bajos residuales
                    j_clean = j.replace("_", " ")[:150]
                    key = j_clean.lower()[:50]
                    if key not in seen:
                        seen.add(key)
                        result.append(j_clean)
            for p in props[:2]:
                prop = p.get("property", "").replace("_", " ")
                val  = p.get("value", "").replace("_", " ")
                conc = concepto.replace("_", " ")
                if prop and val:
                    frase = self._triple_to_natural(conc, prop, val)
                    key = frase.lower()[:50]
                    if frase and key not in seen:
                        seen.add(key)
                        result.append(frase)
            return result
        except Exception:
            return []

    def _get_similar_episodes(self, ai, question: str) -> List[Dict]:
        """Recupera episodios similares de memoria episódica."""
        try:
            from cognia.vectors import text_to_vector
            vec = text_to_vector(question)
            return ai.episodic.retrieve_similar(vec, top_k=4)
        except Exception:
            return []

    def _get_activations(self, ai, concepto: str) -> List[str]:
        """Obtiene conceptos relacionados por spreading activation, limpios."""
        try:
            acts = ai.semantic.spreading_activation(concepto, depth=1)
            result = []
            for a in acts[:6]:
                c = a.get("concept", "")
                if c:
                    # Omitir conceptos con nombres técnicos internos
                    if "concepto_investigado" in c or "en_inglés" in c:
                        continue
                    result.append(c.replace("_", " "))
            return result
        except Exception:
            return []

    def _estimate_confidence(self, ai, concepto: str, descripcion: str,
                              hechos: List, inferencias: List,
                              episodios: List,
                              question: str = "") -> float:
        """
        Calcula la confianza de la respuesta simbólica.
        PASO 4: penalización por baja similitud semántica pregunta-episodios.
        Corrige el fallo donde el simbólico obtenía confianza alta con datos
        genéricos no relacionados con la pregunta específica del usuario.
        Pesos: sem 0.35 / kg 0.22 / ep 0.18 / inf 0.10 / desc 0.05 / rel 0.10
        """
        try:
            import sqlite3
            conn = sqlite3.connect(ai.db)
            conn.text_factory = str
            row = conn.execute(
                "SELECT confidence, support FROM semantic_memory WHERE concept=?",
                (concepto,)
            ).fetchone()
            conn.close()
            sem_conf    = float(row[0]) if row else 0.0
            sem_support = int(row[1])   if row else 0
        except Exception:
            sem_conf, sem_support = 0.0, 0

        score_sem   = sem_conf * 0.35
        score_kg    = min(1.0, len(hechos)      / 5.0) * 0.22
        score_ep    = min(1.0, len(episodios)   / 4.0) * 0.18
        score_inf   = min(1.0, len(inferencias) / 3.0) * 0.10
        score_desc  = 0.05 if descripcion else 0.0

        # PASO 4: penalización por relevancia semántica
        # sim < 0.20 -> score_relevance = 0.0  (penalizacion maxima)
        # sim = 0.40 -> score_relevance = 0.10 (neutro)
        # sim > 0.60 -> score_relevance = 0.20 (bonificacion)
        score_relevance = 0.10
        if question and episodios:
            try:
                sims = [ep.get("similarity", 0.0) for ep in episodios[:4]
                        if ep.get("similarity", 0.0) > 0.0]
                if sims:
                    avg_sim = sum(sims) / len(sims)
                    if avg_sim < 0.20:
                        score_relevance = 0.0
                    elif avg_sim < 0.40:
                        score_relevance = 0.10 * ((avg_sim - 0.20) / 0.20)
                    elif avg_sim < 0.60:
                        score_relevance = 0.10 + 0.10 * ((avg_sim - 0.40) / 0.20)
                    else:
                        score_relevance = 0.20
            except Exception:
                pass

        total = score_sem + score_kg + score_ep + score_inf + score_desc + score_relevance
        result = round(min(1.0, total), 3)

        _sr_logger.debug(
            f"confidence_calc concept={concepto} "
            f"sem={score_sem:.3f} kg={score_kg:.3f} ep={score_ep:.3f} "
            f"inf={score_inf:.3f} desc={score_desc:.2f} rel={score_relevance:.3f} "
            f"total={result:.3f}",
            extra={
                "op":      "symbolic_responder._estimate_confidence",
                "context": (
                    f"concept={concepto} sem_conf={sem_conf:.2f} "
                    f"support={sem_support} n_hechos={len(hechos)} "
                    f"n_episodios={len(episodios)}"
                ),
            },
        )
        return result

    def _collect_list_items(self, hechos: List[str], activaciones: List[str],
                             inferencias: List[str]) -> List[str]:
        """Reúne elementos para una respuesta de tipo lista."""
        items = []
        items.extend(hechos[:4])
        items.extend(activaciones[:3])
        items.extend(inferencias[:2])
        # Deduplicar preservando orden
        seen = set()
        result = []
        for item in items:
            key = item.lower()[:50]
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result[:7]

    def _extract_second_concept(self, question: str, first: str) -> Optional[str]:
        """Intenta extraer el segundo concepto en preguntas de comparación."""
        q = question.lower()
        for sep in [" y ", " vs ", " versus ", " o ", " and "]:
            if sep in q:
                parts = q.split(sep, 1)
                candidate = parts[-1].strip().split()[0] if parts else ""
                if candidate and candidate != first.lower():
                    return candidate.capitalize()
        return None
