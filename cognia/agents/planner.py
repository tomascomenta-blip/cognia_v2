"""
cognia/agents/planner.py — Phase 22

SymbolicPlanner: descompone tareas en SubTasks sin llamadas LLM en ~90% de casos.
Prioridad: plan previo en memoria episódica > template simbólico > plan genérico fallback.

El LLM no se llama aquí. La inferencia LLM ocurre en el Synthesizer (Phase 24),
no durante el planning.
"""

from __future__ import annotations

import ast
import re
import unicodedata
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
    # kwargs ya extraidos para la tool (p.ej. {'query': <tema>}). Evita que el
    # ejecutor mande el objetivo ENTERO como query a search_wikipedia.
    args:             dict       = field(default_factory=dict)


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


# Verbos de CREACION: "crear un juego HTML sobre el sistema solar con
# informacion de los planetas" clasificaba research_topic (por "informacion")
# y terminaba en search_wikipedia con el objetivo entero como query (auditoria
# 2026-08-01). Un pedido de construccion NUNCA es research/explain: VETO.
# (En forma normalizada sin acentos; ver _norm.)
#
# El match es por PALABRA COMPLETA (\b en _CREATION_RE). Con substring pelado
# "creatividad" contenia "crea" y "generacion" contenia "genera", asi que
# "que es la creatividad" e "investiga la generacion del 27" perdian su
# research_topic legitimo y caian al plan generico sin ejecucion (regresion
# medida 2026-08-01). Por eso el espanol se enumera con sus formas reales
# (infinitivo / imperativo / enclitico -me -nos -lo) en vez de por prefijo.
_CREATION_KEYWORDS = [
    "crear", "crea", "creame", "creanos", "crealo",
    "construir", "construye", "construyeme", "construyelo",
    "generar", "genera", "generame", "generalo",
    "haz un", "haz una", "haz el", "haz la", "hazme", "haznos", "hazlo",
    "programa que",
    "escribir un", "escribir una", "escribe un", "escribe una", "escribeme",
    "desarrollar", "desarrolla", "desarrollame",
    "implementar", "implementa", "implementame",
    "disenar", "disena", "disename",
    "build", "create", "make me", "make a", "write a", "write me",
    "implement", "generate",
]

# Alternancia con frontera de palabra a ambos lados; los espacios de las
# frases ("haz un") toleran cualquier separacion real.
_CREATION_RE = re.compile(
    r"\b(?:" + "|".join(
        r"\s+".join(re.escape(p) for p in kw.split()) for kw in _CREATION_KEYWORDS
    ) + r")\b"
)

# Sustantivos debiles: solos no bastan para research_topic (aparecen igual en
# pedidos que no son investigacion).
_WEAK_RESEARCH_KEYWORDS = {"informacion", "information"}


def _norm(text: str) -> str:
    """minusculas + sin acentos, para que 'qué es'/'código' matcheen keywords."""
    return unicodedata.normalize("NFKD", text.lower()) \
        .encode("ascii", "ignore").decode("ascii")


def classify_task(description: str) -> Optional[str]:
    """
    Clasifica el tipo de tarea por keyword matching.
    Retorna task_type (str) o None si no hay match.
    Misma filosofía que GlobalRouter (Phase 20.1) pero para tipos de tarea.
    """
    text = _norm(description)
    es_creacion = _CREATION_RE.search(text) is not None
    best_type: Optional[str] = None
    best_score = 0
    for task_type, keywords in _TASK_KEYWORDS.items():
        # VETO: un verbo de creacion nunca da research_topic/explain_concept
        # (el fallback generico usa research_llm, que si ve el objetivo entero).
        if es_creacion and task_type in ("research_topic", "explain_concept"):
            continue
        matched = [kw for kw in keywords if kw in text]
        score = len(matched)
        if task_type == "research_topic" and matched and \
                all(m in _WEAK_RESEARCH_KEYWORDS for m in matched):
            score = 0   # "informacion" suelta no es un pedido de investigacion
        if score > best_score:
            best_score = score
            best_type = task_type
    return best_type if best_score > 0 else None


# Prefijos de verbo que se pelan para quedarnos con el TEMA de la busqueda
# ("investiga que es el teorema de Bayes" -> "el teorema de Bayes").
_TOPIC_PREFIX_RE = re.compile(
    r"^(?:por favor[,\s]+)?(?:investiga(?:r|me)?|busca(?:r|me)?|research|"
    r"search(?:\s+for)?|explica(?:r|me)?|explain|dime|qu[eé] es|what is|"
    r"c[oó]mo funciona|como funciona|how does)\s+", re.IGNORECASE)

# kwarg que espera cada tool (ver supervisor.build_tool_kwargs)
_TOOL_ARG_NAME = {
    "search_wikipedia": "query",
    "query_episodic":   "query",
    "research_llm":     "question",
    "validate_python":  "code",
    "execute_python":   "code",
    "file_explorer":    "path",
}

# ── Argumento REAL para las tools de codigo/archivo ──────────────────────────
# Antes el ejecutor mandaba la DESCRIPCION del paso como 'code'
# ({'code': 'Validate Python syntax before running: ejecuta print(2+2)...'}):
# el sandbox devolvia ToolResult.success=True con basura y synthesize la
# consumia como resultado real (auditoria 2026-08-01). Ahora el codigo se
# EXTRAE del pedido y se valida con ast; si no hay nada extraible se deja
# vacio y el ejecutor marca la etapa como 'sin ejecutar'.

_FENCED_RE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```", re.S)
_INLINE_RE = re.compile(r"`([^`\n]+)`")
_EXEC_PREFIX_RE = re.compile(
    r"^(?:por favor[,\s]+)?"
    r"(?:ejecut(?:a|ar|ame)|corre(?:r|me)?|lanza(?:r|me)?|run|execute|"
    r"valida(?:r|me)?|validate|prueba|testea)\b\s*"
    r"(?:(?:este|ese|el|un|mi)\s+)?"
    r"(?:codigo|script|programa|code|snippet)?\s*:?\s*",
    re.IGNORECASE)
# El pedido mezcla codigo y prosa ("ejecuta print(2+2) y dime que da"): los
# conectores marcan donde puede terminar el codigo.
_CONECTOR_RE = re.compile(
    r"\s+(?:y|e|luego|despues|después|entonces|then|and)\s+", re.IGNORECASE)

# Ruta de archivo con extension conocida (para file_explorer).
_PATH_RE = re.compile(
    r"['\"]?((?:[A-Za-z]:[\\/])?[\w.\-/\\]*[\w\-]+"
    r"\.(?:py|pyw|txt|md|rst|json|ya?ml|toml|ini|cfg|csv|sql|sh|bat))['\"]?")


def es_codigo_ejecutable(texto: str) -> bool:
    """True si `texto` compila como Python Y hace algo. Un identificador
    suelto ('hola') tambien compila, pero no es un programa: exigimos al
    menos una sentencia que no sea un nombre/constante pelado."""
    if not texto or not texto.strip():
        return False
    try:
        tree = ast.parse(texto)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return False
    return any(
        not (isinstance(n, ast.Expr)
             and isinstance(n.value, (ast.Name, ast.Constant, ast.Attribute)))
        for n in tree.body
    )


def _extract_code(description: str) -> str:
    """Codigo Python REAL del pedido, o '' si no hay ninguno extraible."""
    for m in _FENCED_RE.finditer(description):
        if es_codigo_ejecutable(m.group(1)):
            return m.group(1).strip("\r\n")
    for m in _INLINE_RE.finditer(description):
        if es_codigo_ejecutable(m.group(1)):
            return m.group(1).strip()
    resto = _EXEC_PREFIX_RE.sub("", description.strip(), count=1).strip()
    if not resto:
        return ""
    # Del candidato mas largo al mas corto; gana el primero que COMPILE.
    cortes = [resto] + [resto[:m.start()]
                        for m in reversed(list(_CONECTOR_RE.finditer(resto)))]
    for cand in cortes:
        cand = cand.strip().rstrip(".?!,;:").strip()
        if es_codigo_ejecutable(cand):
            return cand
    return ""


def _extract_path(description: str) -> str:
    """Ruta de archivo mencionada en el pedido, o '' si no hay ninguna.
    Sin ruta NO se explora: el '.' de antes devolvia el repo entero como si
    fuera la respuesta al pedido."""
    m = _PATH_RE.search(description)
    return m.group(1) if m else ""


def _extract_topic(description: str) -> str:
    """Pela verbos/conectores iniciales y comillas; el resto es el tema."""
    t = description.strip().strip("\"'")
    prev = None
    while prev != t:
        prev = t
        t = _TOPIC_PREFIX_RE.sub("", t).strip()
    t = re.sub(r"^(?:sobre|acerca de|about|on)\s+", "", t, flags=re.IGNORECASE)
    return t.strip().strip("\"'").rstrip("?").strip() or description.strip()


def _build_from_template(task_type: str, description: str, task_id: str) -> List[SubTask]:
    steps = TASK_TEMPLATES[task_type]
    # Un valor por nombre de kwarg: el TEMA para las busquedas, el objetivo
    # entero para el que razona, el CODIGO real para el sandbox y la RUTA para
    # el explorador. Vacio = sin argumento extraible -> el ejecutor no corre la
    # tool y marca la etapa como 'sin ejecutar'.
    valores = {
        "query":    _extract_topic(description),
        "question": description.strip(),
        "code":     _extract_code(description),
        "path":     _extract_path(description),
    }
    result = []
    for i, (step_id, step_desc, tool) in enumerate(steps):
        st_id = f"{task_id}_{step_id}"
        deps  = [f"{task_id}_{steps[i - 1][0]}"] if i > 0 else []
        arg   = _TOOL_ARG_NAME.get(tool)
        valor = valores.get(arg, "") if arg else ""
        result.append(SubTask(
            id=st_id,
            description=f"{step_desc}: {description}",
            tool_required=tool,
            dependencies=deps,
            args={arg: valor} if arg and valor else {},
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
            # research_llm SI debe ver el objetivo entero (razona, no busca)
            args={"question": description.strip()},
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
