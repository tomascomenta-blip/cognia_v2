"""
cognia/agents/planner.py — Phase 22

SymbolicPlanner: descompone tareas en SubTasks sin llamadas LLM en ~90% de casos.
Prioridad: plan previo en memoria episódica > template simbólico > plan genérico fallback.

El LLM no se llama aquí. La inferencia LLM ocurre en el Synthesizer (Phase 24),
no durante el planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SubTask:
    id:               str
    description:      str
    tool_required:    str            # nombre registrado en ToolRegistry
    dependencies:     List[str] = field(default_factory=list)
    estimated_tokens: int        = 100
    priority:         int        = 0
    attempts:         int        = 0
    status:           str        = "pending"   # pending|running|done|failed


# ── Templates simbólicos ─────────────────────────────────────────────────────
# Cada entrada: (step_id, descripción, tool_required)

TASK_TEMPLATES: dict[str, list[tuple[str, str, str]]] = {
    "analyze_file": [
        ("explore",   "Explore file structure and extract symbols",  "file_explorer"),
        ("validate",  "Validate syntax and detect static issues",    "validate_python"),
        ("synthesize","Synthesize findings into a report",           "synthesize"),
    ],
    "run_code": [
        ("validate",  "Validate Python syntax before running",       "validate_python"),
        ("execute",   "Execute the code in sandbox",                 "execute_python"),
        ("synthesize","Report execution result to user",             "synthesize"),
    ],
    "research_topic": [
        ("search",    "Search Wikipedia for the topic",              "search_wikipedia"),
        ("query",     "Query episodic memory for related knowledge", "query_episodic"),
        ("synthesize","Synthesize research into a clear answer",     "synthesize"),
    ],
    "find_bugs": [
        ("explore",   "Explore and index the target file",           "file_explorer"),
        ("analyze",   "Static analysis for common bug patterns",     "validate_python"),
        ("synthesize","Summarize bugs found and suggest fixes",      "synthesize"),
    ],
    "explain_concept": [
        ("query",     "Query knowledge graph for the concept",       "query_episodic"),
        ("search",    "Search Wikipedia if local knowledge is thin", "search_wikipedia"),
        ("synthesize","Generate explanation from gathered knowledge","synthesize"),
    ],
}

# ── Keywords por tipo de tarea ───────────────────────────────────────────────

EPISODIC_PLAN_THRESHOLD = 0.85   # patchable by self_improvement.py

_TASK_KEYWORDS: dict[str, list[str]] = {
    "analyze_file": [
        "analiza", "analyze", "review", "revisar", "archivo", "file",
        "codigo", "code", "module", "modulo", "inspect",
    ],
    "run_code": [
        "ejecuta", "execute", "run", "corre", "correr", "prueba",
        "test", "lanza", "launch", "script",
    ],
    "research_topic": [
        "investiga", "research", "busca", "search", "que es", "what is",
        "explica", "explain", "informacion", "information",
    ],
    "find_bugs": [
        "bug", "error", "falla", "fallo", "problema", "issue", "arregla",
        "fix", "broken", "roto", "crashea", "crash", "exception",
    ],
    "explain_concept": [
        "como funciona", "how does", "como se", "how to", "diferencia",
        "difference", "ventajas", "advantages", "cuando usar", "when to use",
    ],
}


def classify_task(description: str) -> Optional[str]:
    """
    Clasifica el tipo de tarea por keyword matching.
    Retorna task_type (str) o None si no hay match.
    Misma filosofía que GlobalRouter (Phase 20.1) pero para tipos de tarea.
    """
    text = description.lower()
    best_type: Optional[str] = None
    best_score = 0
    for task_type, keywords in _TASK_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_type = task_type
    return best_type if best_score > 0 else None


def _build_from_template(task_type: str, description: str, task_id: str) -> List[SubTask]:
    steps = TASK_TEMPLATES[task_type]
    result = []
    for i, (step_id, step_desc, tool) in enumerate(steps):
        st_id = f"{task_id}_{step_id}"
        deps  = [f"{task_id}_{steps[i - 1][0]}"] if i > 0 else []
        result.append(SubTask(
            id=st_id,
            description=f"{step_desc}: {description}",
            tool_required=tool,
            dependencies=deps,
        ))
    return result


def _adapt_prior_plan(cached_plan: list, task_id: str) -> List[SubTask]:
    """Reconstruye SubTasks desde un plan cacheado en memoria episódica."""
    result = []
    for i, step in enumerate(cached_plan):
        st_id = f"{task_id}_step{i}"
        deps  = [f"{task_id}_step{i - 1}"] if i > 0 else []
        result.append(SubTask(
            id=st_id,
            description=step.get("description", ""),
            tool_required=step.get("tool_required", "synthesize"),
            dependencies=deps,
        ))
    return result


def _generic_plan(description: str, task_id: str) -> List[SubTask]:
    """
    Plan de 2 pasos para tareas que no clasifican en ningún template.
    No llama LLM — el LLM se invoca cuando el Synthesizer ejecuta su subtarea.
    """
    return [
        SubTask(
            id=f"{task_id}_research",
            description=f"Research and gather information about: {description}",
            tool_required="research_llm",
            dependencies=[],
        ),
        SubTask(
            id=f"{task_id}_synthesize",
            description=f"Synthesize gathered information into a response: {description}",
            tool_required="synthesize",
            dependencies=[f"{task_id}_research"],
        ),
    ]


def plan_task(
    description: str,
    task_id: str = "task",
    episodic_memory=None,
) -> List[SubTask]:
    """
    Retorna una lista ordenada de SubTasks para la tarea dada.

    Orden de prioridad:
      1. Plan previo similar en memoria episódica (similitud > 0.85) — 0 LLM calls
      2. Template simbólico por keyword matching — 0 LLM calls
      3. Plan genérico 2 pasos — 0 LLM calls en planning
    """
    # 1. Buscar plan previo en memoria episódica
    if episodic_memory is not None:
        try:
            prior = episodic_memory.search(description, top_k=1)
            if prior:
                ep = prior[0]
                sim = getattr(ep, "similarity", 0.0)
                cached = getattr(ep, "metadata", {}) or {}
                cached_plan = cached.get("agent_plan")
                if cached_plan and sim > EPISODIC_PLAN_THRESHOLD:
                    return _adapt_prior_plan(cached_plan, task_id)
        except Exception:
            pass

    # 2. Template simbólico (~90% de tareas)
    task_type = classify_task(description)
    if task_type is not None:
        return _build_from_template(task_type, description, task_id)

    # 3. Plan genérico (no llama LLM aquí)
    return _generic_plan(description, task_id)
