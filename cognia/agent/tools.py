"""
cognia/agent/tools.py
=====================
Concrete tool registry for the Cognia agent loop.

Design (deliberately NOT abstract):
  - Each tool is a plain function ``fn(args: str, ctx: dict) -> str``.
  - ``args`` is the raw text after the tool name on the ACCION line.
  - ``ctx`` is a plain dict the loop fills in:
        ai             -> the Cognia instance (memory, kg, orchestrator)
        working_memory -> dict the agent reads/writes within a task
        agent_state    -> persisted dict (files_touched, tasks, ...)
        print_fn       -> live progress printer (markup-aware)
        show_diff      -> optional callback(old, new, path) for file writes
  - A tool returns the string that gets fed back to the model as RESULTADO.

Adding a tool = write one function + decorate it. No classes, no plugin
discovery, no inheritance. ``build_tools_doc()`` turns the registry into the
prompt text so the doc and the code can never drift apart.
"""

from __future__ import annotations

import ast
import glob as _glob
import json
import operator
import os
import re
import subprocess
from pathlib import Path

# name -> {"fn", "doc", "danger"}
TOOLS: dict = {}


def tool(name: str, doc: str, danger: bool = False):
    """Register a tool. ``doc`` is one line shown to the model verbatim."""
    def deco(fn):
        TOOLS[name] = {"fn": fn, "doc": doc, "danger": danger}
        return fn
    return deco


def build_tools_doc() -> str:
    """The tool list block injected into the agent prompt, built from the registry."""
    return "\n".join(f"  {spec['doc']}" for spec in TOOLS.values())


def run_tool(name: str, args: str, ctx: dict) -> str:
    """Dispatch one tool by name. Unknown name -> a helpful error string."""
    spec = TOOLS.get(name)
    if spec is None:
        # Signal: the agent wanted a tool that doesn't exist yet. Logged so the
        # background researcher can later turn frequent wishes into real tools.
        try:
            from cognia.agent.background_research import record_wanted_tool
            record_wanted_tool(name, hint=args[:120])
        except Exception:
            pass
        valid = ", ".join(TOOLS.keys())
        return f"ERROR: herramienta '{name}' no existe. Validas: {valid}"
    try:
        return spec["fn"](args, ctx)
    except Exception as exc:  # a broken tool must not kill the loop
        return f"RESULTADO {name} ERROR: {exc}"


# ── small shared helpers ───────────────────────────────────────────────
_SKIP_DIRS = {".git", "venv", "venv312", "__pycache__", ".pytest_cache", "node_modules"}


def _strip_fences(text: str) -> str:
    """Remove ```lang ... ``` fences a model often wraps code in."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", t)
        if t.endswith("```"):
            t = t[:-3]
    return t.strip("\n")


def _orch(ctx: dict):
    """Reuse the Cognia instance's orchestrator, building a local one if needed."""
    ai = ctx.get("ai")
    o = getattr(ai, "_orchestrator", None)
    if o is not None:
        return o
    from shattering.orchestrator import ShatteringOrchestrator
    return ShatteringOrchestrator(mode="local")


# ══════════════════════════════════════════════════════════════════════
# FILE TOOLS
# ══════════════════════════════════════════════════════════════════════

@tool("leer_archivo", "leer_archivo <path>                 -- leer un archivo (hasta 4000 chars)")
def _leer_archivo(args, ctx):
    path = Path(args.strip())
    content = path.read_text(encoding="utf-8", errors="replace")[:4000]
    return f"RESULTADO leer_archivo {path}: {content}"


@tool("escribir_archivo",
      "escribir_archivo <path> | <contenido>  -- crea/sobrescribe (crea dirs)")
def _escribir_archivo(args, ctx):
    parts = args.split(" | ", 1)
    if len(parts) != 2:
        return "RESULTADO escribir_archivo ERROR: formato (usa ruta | contenido)"
    wpath = Path(parts[0].strip())
    content = _strip_fences(parts[1])
    old = wpath.read_text(encoding="utf-8") if wpath.exists() else ""
    wpath.parent.mkdir(parents=True, exist_ok=True)
    wpath.write_text(content, encoding="utf-8")
    show_diff = ctx.get("show_diff")
    if callable(show_diff):
        try:
            show_diff(old, content, str(wpath))
        except Exception:
            pass
    ft = ctx.setdefault("agent_state", {}).setdefault("files_touched", [])
    if str(wpath) not in ft:
        ft.append(str(wpath))
        ctx["agent_state"]["files_touched"] = ft[-15:]
    return f"RESULTADO escribir_archivo {wpath}: OK ({len(content)} chars)"


@tool("apendar_archivo",
      "apendar_archivo <path> | <texto>      -- agrega texto al final del archivo")
def _apendar_archivo(args, ctx):
    parts = args.split(" | ", 1)
    if len(parts) != 2:
        return "RESULTADO apendar_archivo ERROR: formato (usa ruta | texto)"
    wpath = Path(parts[0].strip())
    text = _strip_fences(parts[1])
    wpath.parent.mkdir(parents=True, exist_ok=True)
    # Start on a fresh line if the file has content not ending in a newline,
    # so "append a line" never glues onto the previous one.
    prefix = ""
    if wpath.exists():
        existing = wpath.read_text(encoding="utf-8", errors="replace")
        if existing and not existing.endswith("\n"):
            prefix = "\n"
    with wpath.open("a", encoding="utf-8") as fh:
        fh.write(prefix + (text if text.endswith("\n") else text + "\n"))
    return f"RESULTADO apendar_archivo {wpath}: OK (+{len(text)} chars)"


@tool("copiar_archivo", "copiar_archivo <src> | <dst>          -- copia un archivo")
def _copiar_archivo(args, ctx):
    parts = args.split(" | ", 1)
    if len(parts) != 2:
        return "RESULTADO copiar_archivo ERROR: formato (usa src | dst)"
    import shutil
    src, dst = Path(parts[0].strip()), Path(parts[1].strip())
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return f"RESULTADO copiar_archivo: {src} -> {dst} OK"


@tool("listar", "listar <directorio>                   -- lista archivos/carpetas")
def _listar(args, ctx):
    base = Path(args.strip() or ".")
    entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name))[:40]
    listing = [f"{'D' if e.is_dir() else 'F'} {e.name}" for e in entries]
    return f"RESULTADO listar {base}: {listing}"


@tool("arbol", "arbol <directorio>                    -- arbol de archivos (2 niveles)")
def _arbol(args, ctx):
    base = Path(args.strip() or ".")
    out = []
    for p in sorted(base.rglob("*")):
        if any(x in p.parts for x in _SKIP_DIRS):
            continue
        rel = p.relative_to(base)
        if len(rel.parts) > 2:
            continue
        out.append(("  " * (len(rel.parts) - 1)) + ("[D] " if p.is_dir() else "") + rel.parts[-1])
        if len(out) >= 60:
            break
    return "RESULTADO arbol:\n" + "\n".join(out)


@tool("contar_lineas", "contar_lineas <path>                  -- cuenta lineas de un archivo")
def _contar_lineas(args, ctx):
    p = Path(args.strip())
    n = sum(1 for _ in p.open("r", encoding="utf-8", errors="replace"))
    size = p.stat().st_size
    return f"RESULTADO contar_lineas {p}: {n} lineas, {size} bytes"


# ══════════════════════════════════════════════════════════════════════
# SEARCH TOOLS
# ══════════════════════════════════════════════════════════════════════

@tool("buscar", "buscar <patron> | <directorio>        -- busca texto en archivos")
def _buscar(args, ctx):
    parts = args.split(" | ", 1)
    patron = parts[0].strip()
    directorio = parts[1].strip() if len(parts) > 1 else "."

    # El modelo entrecomilla el patron: escribe `buscar "class" | ruta`. Sin
    # quitarlas, se busca el literal `"class"` — con comillas — y no casa nunca.
    # Medido el 2026-07-20: el agente gasto 8 pasos reintentando la misma
    # busqueda con y sin comillas y acabo concluyendo, en falso, que el fichero
    # no tenia clases.
    for comilla in ('"', "'"):
        if len(patron) > 1 and patron.startswith(comilla) and patron.endswith(comilla):
            patron = patron[1:-1].strip()
            break
    directorio = directorio.strip("\"'")

    # El separador " | " es poco habitual y el modelo no lo usa: escribe
    # `buscar class cognia/mcp_libre.py`. Sin esto, el patron pasaba a ser la
    # frase entera, no encontraba nada y devolvia "sin resultados" — y el
    # agente concluia que el fichero NO TIENE clases, teniendo tres. Medido el
    # 2026-07-20 en una tarea real. Un vacio silencioso que produce una
    # conclusion falsa es peor que un error.
    if len(parts) == 1 and " " in patron:
        cabeza, _, cola = patron.rpartition(" ")
        if cola and Path(cola).exists():
            patron, directorio = cabeza.strip(), cola
    results = []
    try:
        r = subprocess.run(
            ["rg", "--no-heading", "-n", "--max-count", "3", patron, directorio],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            results = r.stdout.strip().splitlines()[:15]
    except Exception:
        pass
    if not results:
        try:
            compiled = re.compile(patron, re.IGNORECASE)
        except re.error:
            compiled = None
        # Un FICHERO tambien es un ambito valido. `Path(fichero).rglob("*")`
        # devuelve 0 elementos, asi que acotar la busqueda a un fichero
        # concreto no funcionaba nunca por este camino — y este camino es el
        # unico que hay, porque `rg` no esta instalado en esta maquina, con lo
        # que el subprocess de arriba siempre falla. Medido el 2026-07-20.
        raiz = Path(directorio)
        candidatos = [raiz] if raiz.is_file() else raiz.rglob("*")

        for p in candidatos:
            if not p.is_file() or any(x in p.parts for x in _SKIP_DIRS):
                continue
            try:
                for i, ln in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    if (compiled and compiled.search(ln)) or (not compiled and patron.lower() in ln.lower()):
                        results.append(f"{p}:{i}: {ln.strip()[:100]}")
                        if len(results) >= 15:
                            break
            except Exception:
                pass
            if len(results) >= 15:
                break
    if not results:
        try:
            results = _glob.glob(f"{directorio}/**/*{patron}*", recursive=True)[:10]
        except Exception:
            pass
    if results:
        return f"RESULTADO buscar '{patron}': " + " | ".join(results)
    # Decir DONDE se busco: "sin resultados" a secas hacia que el agente
    # concluyera cosas falsas sobre el codigo sin poder sospechar del ambito.
    return (f"RESULTADO buscar '{patron}': sin coincidencias en '{directorio}'. "
            f"Para acotar a un fichero o carpeta: buscar <patron> | <ruta>")


# ══════════════════════════════════════════════════════════════════════
# SHELL / DEV TOOLS
# ══════════════════════════════════════════════════════════════════════

_BLOCK = [
    "rm -rf", "format", "del /s", "del /q", "del /f", ":(){",
    "mkfs", "dd if=", "> /dev/", "shutdown", "reboot", "rmdir /s",
]


def _shell(cmd: str, ctx: dict, timeout: int = 30) -> str:
    norm = re.sub(r"\s+", " ", cmd.lower())
    if any(b in norm for b in _BLOCK):
        return "RESULTADO ejecutar: BLOQUEADO por seguridad"
    pf = ctx.get("print_fn")
    if callable(pf):
        pf(f"[detail]$ {cmd}[/detail]")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout + r.stderr).strip()
    code = "" if r.returncode == 0 else f" (exit {r.returncode})"
    return f"RESULTADO ejecutar{code}: {out[:1500] or '(sin output)'}"


@tool("ejecutar", "ejecutar <comando shell>              -- corre un comando (con bloqueos de seguridad)")
def _ejecutar(args, ctx):
    return _shell(args.strip(), ctx)


@tool("tests", "tests <ruta>                          -- corre pytest sobre una ruta")
def _tests(args, ctx):
    ruta = args.strip() or "tests/"
    return _shell(f"python -m pytest {ruta} -q --no-header", ctx, timeout=180)


@tool("py_validar", "py_validar <path>                     -- chequea sintaxis de un .py")
def _py_validar(args, ctx):
    p = Path(args.strip())
    try:
        ast.parse(p.read_text(encoding="utf-8"))
        return f"RESULTADO py_validar {p}: sintaxis OK"
    except SyntaxError as e:
        return f"RESULTADO py_validar {p}: ERROR linea {e.lineno}: {e.msg}"


@tool("json_validar", "json_validar <path>                   -- valida un archivo JSON")
def _json_validar(args, ctx):
    p = Path(args.strip())
    try:
        json.loads(p.read_text(encoding="utf-8"))
        return f"RESULTADO json_validar {p}: JSON valido"
    except Exception as e:
        return f"RESULTADO json_validar {p}: ERROR: {e}"


@tool("git_estado", "git_estado                            -- git status resumido")
def _git_estado(args, ctx):
    return _shell("git status --short --branch", ctx, timeout=15)


@tool("git_diff", "git_diff [ruta]                       -- git diff (cambios sin commitear)")
def _git_diff(args, ctx):
    return _shell(f"git diff --stat {args.strip()}".strip(), ctx, timeout=15)


@tool("git_log", "git_log                               -- ultimos 5 commits")
def _git_log(args, ctx):
    return _shell("git log --oneline -5", ctx, timeout=15)


# ══════════════════════════════════════════════════════════════════════
# MATH / TIME / WEB
# ══════════════════════════════════════════════════════════════════════

_MATH_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _MATH_OPS:
        return _MATH_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _MATH_OPS:
        return _MATH_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("expresion no permitida (solo aritmetica)")


@tool("calcular", "calcular <expresion>                  -- aritmetica exacta (+ - * / // % **)")
def _calcular(args, ctx):
    expr = args.strip()
    # Models often wrap the expression in quotes/backticks or trail junk after a
    # pipe; keep only the arithmetic part.
    expr = expr.split("|", 1)[0].strip().strip("\"'`")
    val = _safe_eval(ast.parse(expr, mode="eval").body)
    return f"RESULTADO calcular: {expr} = {val}"


@tool("fecha", "fecha                                 -- fecha y hora actual")
def _fecha(args, ctx):
    import datetime
    return "RESULTADO fecha: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool("http_get", "http_get <url>                        -- descarga texto de una URL (http/https)")
def _http_get(args, ctx):
    import urllib.request
    url = args.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "RESULTADO http_get ERROR: solo http/https"
    req = urllib.request.Request(url, headers={"User-Agent": "Cognia/3.2"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read(200_000).decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", raw)          # crude tag strip
    text = re.sub(r"\s+", " ", text).strip()
    return f"RESULTADO http_get {url[:60]}: {text[:1500]}"


# ══════════════════════════════════════════════════════════════════════
# MCP TOOLS — servidores libres, sin registro ni clave
# ══════════════════════════════════════════════════════════════════════
#
# Van por cognia/mcp_libre.py, que habla el protocolo a mano con stdlib. Sin
# esto el cliente MCP seria una curiosidad de CLI: el valor esta en que Cognia
# pueda consultarlos MIENTRAS trabaja, que es lo que hace un agente de coding.
#
# Ambas leen; ninguna escribe ni gasta dinero, asi que danger=False.

def _partir(args: str, n: int):
    """Parte 'a b resto' en n trozos, el ultimo se queda con lo que sobre."""
    trozos = args.strip().split(None, n - 1)
    return trozos + [""] * (n - len(trozos))


@tool("docs_repo",
      "docs_repo <owner> <repo>              -- documentacion de un repo de GitHub (MCP libre)")
def _docs_repo(args, ctx):
    from cognia.mcp_libre import ErrorMCP, cliente
    owner, repo = _partir(args, 2)
    if not owner or not repo:
        return "RESULTADO docs_repo ERROR: uso: docs_repo <owner> <repo>"
    try:
        salida = cliente("gitmcp").llamar(
            "fetch_generic_documentation", {"owner": owner, "repo": repo})
    except ErrorMCP as exc:
        return f"RESULTADO docs_repo ERROR: {exc}"
    return f"RESULTADO docs_repo {owner}/{repo}: {salida[:2000]}"


@tool("preguntar_repo",
      "preguntar_repo <owner/repo> <pregunta>  -- pregunta en lenguaje natural sobre un repo")
def _preguntar_repo(args, ctx):
    from cognia.mcp_libre import ErrorMCP, cliente
    repo, pregunta = _partir(args, 2)
    if "/" not in repo or not pregunta:
        return ("RESULTADO preguntar_repo ERROR: uso: "
                "preguntar_repo <owner/repo> <pregunta>")
    try:
        salida = cliente("deepwiki").llamar(
            "ask_question", {"repoName": repo, "question": pregunta})
    except ErrorMCP as exc:
        return f"RESULTADO preguntar_repo ERROR: {exc}"
    return f"RESULTADO preguntar_repo {repo}: {salida[:2500]}"


@tool("docs_libreria",
      "docs_libreria <nombre> <tema>         -- documentacion al dia de una libreria")
def _docs_libreria(args, ctx):
    """Contra la API que el modelo recuerda de su entrenamiento, que envejece."""
    from cognia.mcp_libre import ErrorMCP, cliente
    nombre, tema = _partir(args, 2)
    if not nombre:
        return "RESULTADO docs_libreria ERROR: uso: docs_libreria <nombre> <tema>"
    try:
        c = cliente("context7")
        ident = c.llamar("resolve-library-id", {"libraryName": nombre})
        salida = c.llamar("query-docs",
                          {"libraryId": ident.strip().splitlines()[0][:120],
                           "query": tema or nombre})
    except (ErrorMCP, IndexError) as exc:
        return f"RESULTADO docs_libreria ERROR: {exc}"
    return f"RESULTADO docs_libreria {nombre}: {salida[:2500]}"


@tool("buscar_en_repo",
      "buscar_en_repo <owner> <repo> <query> -- busca codigo en un repo de GitHub (MCP libre)")
def _buscar_en_repo(args, ctx):
    from cognia.mcp_libre import ErrorMCP, cliente
    owner, repo, query = _partir(args, 3)
    if not (owner and repo and query):
        return "RESULTADO buscar_en_repo ERROR: uso: buscar_en_repo <owner> <repo> <query>"
    try:
        salida = cliente("gitmcp").llamar(
            "search_generic_code",
            {"owner": owner, "repo": repo, "query": query})
    except ErrorMCP as exc:
        return f"RESULTADO buscar_en_repo ERROR: {exc}"
    return f"RESULTADO buscar_en_repo {owner}/{repo} '{query}': {salida[:2000]}"


# ══════════════════════════════════════════════════════════════════════
# MEMORY TOOLS (Cognia's own brain as tools -> RAG)
# ══════════════════════════════════════════════════════════════════════

@tool("recordar", "recordar <consulta>                   -- busca en la memoria episodica (RAG)")
def _recordar(args, ctx):
    ai = ctx.get("ai")
    query = args.strip()
    try:
        from cognia.vectors import text_to_vector
    except ImportError:
        from vectors import text_to_vector
    vec = text_to_vector(query)
    hits = ai.episodic.retrieve_similar(vec, top_k=5)
    if not hits:
        return f"RESULTADO recordar '{query}': sin recuerdos relevantes"
    lines = [f"  ({h.get('similarity', 0):.2f}) {h.get('observation', '')[:120]}" for h in hits]
    return f"RESULTADO recordar '{query}':\n" + "\n".join(lines)


@tool("memorizar", "memorizar <texto>                     -- guarda en memoria episodica")
def _memorizar(args, ctx):
    ctx["ai"].observe(args.strip(), provided_label="agente_tarea")
    return "RESULTADO memorizar: guardado en memoria episodica"


@tool("kg_buscar", "kg_buscar <concepto>                  -- hechos del grafo sobre un concepto")
def _kg_buscar(args, ctx):
    ai = ctx.get("ai")
    concept = args.strip()
    facts = ai.kg.get_facts(concept) or ai.kg.get_neighbors(concept)
    if not facts:
        return f"RESULTADO kg_buscar '{concept}': sin hechos"
    return f"RESULTADO kg_buscar '{concept}': " + " | ".join(str(f)[:80] for f in facts[:10])


@tool("kg_agregar", "kg_agregar <sujeto> | <relacion> | <objeto>  -- agrega un hecho al grafo")
def _kg_agregar(args, ctx):
    parts = [p.strip() for p in args.split(" | ")]
    if len(parts) != 3:
        return "RESULTADO kg_agregar ERROR: formato (sujeto | relacion | objeto)"
    subj, rel, obj = parts
    from cognia.knowledge.graph import KnowledgeGraph
    if rel not in KnowledgeGraph.VALID_RELATIONS:
        return ("RESULTADO kg_agregar ERROR: relacion invalida. Validas: "
                + ", ".join(KnowledgeGraph.VALID_RELATIONS))
    ok = ctx["ai"].kg.add_triple(subj, rel, obj, source="agente")
    return f"RESULTADO kg_agregar: ({subj} {rel} {obj}) {'OK' if ok else 'no agregado'}"


@tool("anotar", "anotar <clave> | <valor>              -- guarda nota en memoria de trabajo")
def _anotar(args, ctx):
    parts = args.split(" | ", 1)
    if len(parts) != 2:
        return "RESULTADO anotar ERROR: formato (clave | valor)"
    ctx.setdefault("working_memory", {})[parts[0].strip()] = parts[1].strip()
    return f"RESULTADO anotar: '{parts[0].strip()}' guardado"


@tool("notas", "notas                                 -- lee la memoria de trabajo")
def _notas(args, ctx):
    wm = ctx.get("working_memory", {})
    if not wm:
        return "RESULTADO notas: (vacia)"
    return "RESULTADO notas:\n" + "\n".join(f"  {k}: {v}" for k, v in wm.items())


# ══════════════════════════════════════════════════════════════════════
# LLM-BACKED TOOLS
# ══════════════════════════════════════════════════════════════════════

@tool("resumir", "resumir <texto>                       -- resume un texto con el modelo")
def _resumir(args, ctx):
    text = args.strip()
    prompt = f"Resume en 2-3 frases claras, en espanol:\n\n{text[:3000]}"
    out = _orch(ctx).infer(prompt).text.strip()
    return f"RESULTADO resumir: {out[:800]}"
