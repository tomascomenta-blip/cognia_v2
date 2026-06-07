from enum import Enum
from typing import Optional


class ToolChoice(Enum):
    WEB_SEARCH = "web_search"            # queries sobre eventos recientes, noticias, precios
    KNOWLEDGE_GRAPH = "knowledge_graph"  # queries sobre hechos, definiciones, relaciones
    CURIOSITY_INSIGHTS = "curiosity_insights"  # queries sobre temas ya investigados
    LLM_ONLY = "llm_only"               # razonamiento, codigo, escritura, conversacion general


# Keywords que indican cada herramienta
_WEB_SIGNALS = {
    "hoy", "ahora", "latest", "recent", "today", "now", "2024", "2025", "2026",
    "precio", "price", "noticias", "news", "actual", "current", "ultimo", "latest",
    "cuando", "when", "cuándo",
}
_KG_SIGNALS = {
    "qué es", "what is", "quien es", "who is", "define", "significa", "meaning",
    "concepto", "concept", "relacion", "relation", "hereda", "tipo de", "type of",
    "es un", "is a", "pertenece", "belongs",
}


class ToolRouter:
    """
    Router determinista que elige que herramienta usar para una query.
    La logica es puramente por heuristica de keywords — sin LLM — para evitar ciclos.
    """

    def route(self, query: str) -> ToolChoice:
        q = query.lower()

        # Web signals toman prioridad (informacion temporal)
        if any(s in q for s in _WEB_SIGNALS):
            return ToolChoice.WEB_SEARCH

        # KG signals para hechos estructurados
        if any(s in q for s in _KG_SIGNALS):
            return ToolChoice.KNOWLEDGE_GRAPH

        return ToolChoice.LLM_ONLY

    def route_with_confidence(self, query: str) -> tuple:
        """
        Retorna (ToolChoice, confidence 0.0-1.0).
        Confidence = fraccion de signals que matchearon sobre total de hits.
        """
        q = query.lower()

        web_hits = sum(1 for s in _WEB_SIGNALS if s in q)
        kg_hits = sum(1 for s in _KG_SIGNALS if s in q)

        if web_hits == 0 and kg_hits == 0:
            return ToolChoice.LLM_ONLY, 0.0

        total = web_hits + kg_hits
        if web_hits >= kg_hits:
            return ToolChoice.WEB_SEARCH, min(web_hits / max(total, 1), 1.0)
        else:
            return ToolChoice.KNOWLEDGE_GRAPH, min(kg_hits / max(total, 1), 1.0)

    def execute(self, query: str, max_results: int = 3) -> dict:
        """
        Routea Y ejecuta la herramienta seleccionada.
        Retorna {"tool": str, "confidence": float, "result": dict, "error": str|None}
        """
        tool, confidence = self.route_with_confidence(query)

        result = {}
        error = None

        try:
            if tool == ToolChoice.WEB_SEARCH:
                from cognia.search.web_search import WebSearch
                ws = WebSearch()
                result = ws.search(query, max_results=max_results)

            elif tool == ToolChoice.KNOWLEDGE_GRAPH:
                from cognia.knowledge.graph import KnowledgeGraph
                kg = KnowledgeGraph()
                # Extraer keyword principal (longest token >= 4 chars)
                tokens = [t for t in query.lower().split() if len(t) >= 4]
                if tokens:
                    keyword = max(tokens, key=len)
                    facts = kg.get_inherited_facts(keyword, max_depth=2)
                    result = {"facts": facts, "keyword": keyword}
                else:
                    result = {"facts": [], "keyword": ""}

        except Exception as e:
            error = str(e)[:200]
            tool = ToolChoice.LLM_ONLY
            confidence = 0.0

        return {
            "tool": tool.value,
            "confidence": round(confidence, 3),
            "result": result,
            "error": error,
        }
