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
import atexit
import datetime
import glob as _glob
import json
import operator
import os
import re
import subprocess
import sys
import time as _time
from pathlib import Path

# Gate de escritura compartido con los workers Tier 1: confina TODA escritura
# del loop al workspace del agente (AGENT_WORKSPACE_ROOT, env-overridable via
# COGNIA_AGENT_WORKSPACE) y bloquea nombres sensibles (*.env, *secret*,
# binarios). Levanta ValueError con mensaje ASCII que nombra el workspace.
from cognia.agents.workers.dev_tools import resolve_write_path as _resolve_write_path

# name -> {"fn", "doc", "danger"}
TOOLS: dict = {}


def tool(name: str, doc: str, danger: bool = False):
    """Register a tool. ``doc`` is one line shown to the model verbatim."""
    def deco(fn):
        TOOLS[name] = {"fn": fn, "doc": doc, "danger": danger}
        return fn
    return deco


def build_tools_doc(allowed: set = None) -> str:
    """The tool list block injected into the agent prompt, built from the registry.

    ``allowed``: si se pasa, muestra SOLO esas tools (sub-agente acotado por
    rol -- delegar_subtarea). None = todas (comportamiento por defecto)."""
    return "\n".join(f"  {spec['doc']}" for name, spec in TOOLS.items()
                     if allowed is None or name in allowed)


# Roles para sub-agentes acotados (delegar_subtarea): cada rol expone SOLO un
# subconjunto de tools -- un investigador no puede escribir/ejecutar, un
# implementador si. Acota el blast-radius de una subtarea delegada.
ROLE_TOOLS = {
    "investigador": {"leer_archivo", "listar", "arbol", "contar_lineas",
                     "buscar", "recordar", "kg_buscar", "notas", "anotar",
                     "resumir", "responder"},
    "implementador": {"leer_archivo", "listar", "buscar", "escribir_archivo",
                      "apendar_archivo", "copiar_archivo", "generar_codigo",
                      "py_validar", "json_validar", "tests", "ejecutar",
                      "notas", "anotar", "responder"},
}


# ── contador de uso liviano (TAREA 5) ──────────────────────────────────
# Dict en memoria {tool: {calls, ok, fail, last}} + flush ATOMICO (mismo
# patron _save_manifest de tool_synthesis: temp + os.replace, nunca deja el
# archivo a medio escribir) cada _USAGE_FLUSH_EVERY llamadas y en atexit.
# Best-effort: si el disco falla, el loop del agente no se entera.
_USAGE_PATH = Path(__file__).parent / "generated_tools" / "_tool_usage.json"
_USAGE: dict = {}
_usage_calls_since_flush = 0
_USAGE_FLUSH_EVERY = 20


def _usage_load() -> None:
    global _USAGE
    try:
        if _USAGE_PATH.exists():
            _USAGE = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        _USAGE = {}


def _usage_flush() -> None:
    try:
        _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _USAGE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_USAGE, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _USAGE_PATH)
    except Exception:
        pass


def _record_usage(name: str, ok: bool) -> None:
    global _usage_calls_since_flush
    import datetime
    entry = _USAGE.setdefault(name, {"calls": 0, "ok": 0, "fail": 0, "last": None})
    entry["calls"] += 1
    entry["ok" if ok else "fail"] += 1
    entry["last"] = datetime.datetime.now().isoformat(timespec="seconds")
    _usage_calls_since_flush += 1
    if _usage_calls_since_flush >= _USAGE_FLUSH_EVERY:
        _usage_calls_since_flush = 0
        _usage_flush()


def get_tool_usage() -> dict:
    """Lectura de los contadores de uso (copia; no expone el dict interno)."""
    return {k: dict(v) for k, v in _USAGE.items()}


_usage_load()
atexit.register(_usage_flush)


def run_tool(name: str, args: str, ctx: dict) -> str:
    """Dispatch one tool by name. Unknown name -> a helpful error string."""
    # Sub-agente acotado: si el ctx trae un set de tools permitidas (rol de
    # delegar_subtarea), una tool fuera del rol se rechaza con señal clara --
    # el modelo ve que no la tiene y elige otra (mismo estilo que 'no existe').
    _allowed = ctx.get("_allowed_tools") if isinstance(ctx, dict) else None
    if _allowed is not None and name not in _allowed and name != "responder":
        return (f"ERROR: '{name}' no esta permitida para este rol. "
                f"Validas: {', '.join(sorted(_allowed))}")
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
        out = spec["fn"](args, ctx)
        # \bERROR\b sobre la cabeza (misma convencion que la traza de cli.py):
        # un RESULTADO exitoso que menciona 'ERROR_LOG.txt' no es un fallo.
        ok = not re.search(r"\bERROR\b", out[:120])
    except Exception as exc:  # a broken tool must not kill the loop
        out = f"RESULTADO {name} ERROR: {exc}"
        ok = False
    try:
        _record_usage(name, ok)
    except Exception:
        pass
    return out


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


def _disp(path) -> str:
    """Ruta para MOSTRAR al modelo en el RESULTADO: relativa al workspace si esta
    adentro, si no absoluta.

    El 3B copiaba el path ABSOLUTO que devolvia escribir_archivo
    (C:\\Users\\...\\x.txt) y luego lo re-usaba/leia en loop (verificado en e2e del
    agente 2026-07-01). Mostrar la ruta relativa evita esa confusion y ademas
    coincide con los datos de fine-tune (sanitizados a relativo)."""
    try:
        import cognia.agents.workers.dev_tools as _dv
        root = Path(_dv.AGENT_WORKSPACE_ROOT).resolve()
        p = Path(path).resolve()
        if p == root:
            return "."
        if root in p.parents:
            return str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        pass
    return str(path)


# ══════════════════════════════════════════════════════════════════════
# FILE TOOLS
# ══════════════════════════════════════════════════════════════════════

@tool("leer_archivo", "leer_archivo <path>                 -- leer un archivo (hasta 4000 chars)")
def _leer_archivo(args, ctx):
    path = Path(args.strip())
    full = path.read_text(encoding="utf-8", errors="replace")
    content = full[:4000]
    if len(full) > 4000:
        # Marcador explicito: sin esto el modelo cree que vio el archivo entero y
        # lo sobrescribe con una version mas corta (perdida de datos en read-mod-write).
        content += (f"\n... [TRUNCADO: mostrando 4000 de {len(full)} chars; el archivo NO "
                    f"esta completo. NO lo sobrescribas entero; usa 'buscar' para ubicar]")
    return f"RESULTADO leer_archivo {_disp(path)}: {content}"


@tool("escribir_archivo",
      "escribir_archivo <path> | <contenido>  -- crea/sobrescribe en el workspace (crea dirs)")
def _escribir_archivo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escribir_archivo ERROR: formato (usa ruta | contenido)"
    try:
        wpath = _resolve_write_path(parts[0].strip())
    except ValueError as e:
        return f"RESULTADO escribir_archivo ERROR: {e}"
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
    return f"RESULTADO escribir_archivo {_disp(wpath)}: OK ({len(content)} chars)"


@tool("apendar_archivo",
      "apendar_archivo <path> | <texto>      -- agrega texto al final (en el workspace)")
def _apendar_archivo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO apendar_archivo ERROR: formato (usa ruta | texto)"
    try:
        wpath = _resolve_write_path(parts[0].strip())
    except ValueError as e:
        return f"RESULTADO apendar_archivo ERROR: {e}"
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
    return f"RESULTADO apendar_archivo {_disp(wpath)}: OK (+{len(text)} chars)"


@tool("copiar_archivo", "copiar_archivo <src> | <dst>          -- copia un archivo (dst en el workspace)")
def _copiar_archivo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO copiar_archivo ERROR: formato (usa src | dst)"
    import shutil
    # src puede leerse de cualquier lado (leer es legitimo); dst queda confinado.
    src = Path(parts[0].strip())
    try:
        dst = _resolve_write_path(parts[1].strip())
    except ValueError as e:
        return f"RESULTADO copiar_archivo ERROR: {e}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return f"RESULTADO copiar_archivo: {src} -> {_disp(dst)} OK"


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
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    patron = parts[0].strip()
    directorio = parts[1].strip() if len(parts) > 1 else "."

    def _scan(pat):
        """rg -> fallback regex/substring sobre contenidos. Hasta 15 'archivo:n: txt'."""
        try:
            r = subprocess.run(
                ["rg", "--no-heading", "-n", "--max-count", "3", pat, directorio],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[:15]
        except Exception:
            pass
        out = []
        try:
            compiled = re.compile(pat, re.IGNORECASE)
        except re.error:
            compiled = None
        for p in Path(directorio).rglob("*"):
            if not p.is_file() or any(x in p.parts for x in _SKIP_DIRS):
                continue
            try:
                for i, ln in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    if (compiled and compiled.search(ln)) or (not compiled and pat.lower() in ln.lower()):
                        out.append(f"{p}:{i}: {ln.strip()[:100]}")
                        if len(out) >= 15:
                            break
            except Exception:
                pass
            if len(out) >= 15:
                break
        return out

    results = _scan(patron)
    nota = ""
    # Fallback anti-degeneracion: el 3B a veces agrega spam a los args de busqueda
    # (ej 'CLAVE-FENIX tetas Incontri'). Si el patron completo (varias palabras) no
    # matcho, reintentar SOLO con un token identificador distintivo (con guion/
    # digito/guion-bajo) — asi 'CLAVE-FENIX' se encuentra pese al ruido, sin rescatar
    # palabras comunes (evita falsos positivos).
    if not results and len(re.split(r"\s+", patron)) > 1:
        ids = [t for t in re.split(r"\s+", patron)
               if len(t) >= 4 and re.search(r"[-_/.\d]", t)]
        if ids:
            alt = max(ids, key=len)
            if alt != patron:
                results = _scan(alt)
                if results:
                    nota = f" (patron acotado a '{alt}')"
    if not results:
        try:
            results = _glob.glob(f"{directorio}/**/*{patron}*", recursive=True)[:10]
        except Exception:
            pass
    return f"RESULTADO buscar '{patron}'{nota}: " + (" | ".join(results) if results else "sin resultados")


# ══════════════════════════════════════════════════════════════════════
# SHELL / DEV TOOLS
# ══════════════════════════════════════════════════════════════════════

_BLOCK = [
    "rm -rf", "del /s", "del /q", "del /f", ":(){",
    "mkfs", "dd if=", "> /dev/", "shutdown", "reboot", "rmdir /s",
]
# 'format' NO va como substring: bloqueaba comandos benignos comunes de un agente
# de codigo ('ruff format .', 'git log --pretty=format:%H', 'reformat.py'). Solo
# el 'format C:' real (borrado de disco Windows) via limite de palabra.
_BLOCK_RE = [re.compile(r"\bformat\s+[a-zA-Z]:")]


def _shell(cmd: str, ctx: dict, timeout: int = 30) -> str:
    norm = re.sub(r"\s+", " ", cmd.lower())
    if any(b in norm for b in _BLOCK) or any(rx.search(norm) for rx in _BLOCK_RE):
        return "RESULTADO ejecutar: BLOQUEADO por seguridad"
    pf = ctx.get("print_fn")
    if callable(pf):
        pf(f"[detail]$ {cmd}[/detail]")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Timeout accionable en vez de un stacktrace generico: el modelo necesita
        # saber que debe ACOTAR el comando (ruta/test mas especifico) y reintentar.
        return (f"RESULTADO ejecutar ERROR: timeout tras {timeout}s. "
                f"Acota el comando (ruta/target mas especifico) y reintenta.")
    out = (r.stdout + r.stderr).strip()
    code = "" if r.returncode == 0 else f" (exit {r.returncode})"
    return f"RESULTADO ejecutar{code}: {out[:1500] or '(sin output)'}"


@tool("ejecutar", "ejecutar <comando shell>              -- corre un comando (con bloqueos de seguridad)")
def _ejecutar(args, ctx):
    return _shell(args.strip(), ctx)


@tool("tests", "tests <ruta>                          -- corre pytest sobre una ruta ESPECIFICA (archivo o dir)")
def _tests(args, ctx):
    ruta = args.strip()
    if not ruta:
        # Sin ruta corria 'tests/' (toda la suite, ~min) con timeout 180s ->
        # SIEMPRE timeout, 0 senal, 180s quemados. Exigir una ruta especifica.
        return ("RESULTADO tests ERROR: pasa una ruta ESPECIFICA (archivo o dir), "
                "p.ej. 'tests/test_foo.py'. Correr toda la suite tarda minutos y "
                "agota el timeout.")
    # sys.executable (no 'python' pelado): el 'python' del PATH puede ser el venv
    # roto 3.14 / no traer pytest; el interprete que corre el agente es el correcto.
    return _shell(f'"{sys.executable}" -m pytest {ruta} -q --no-header', ctx, timeout=180)


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
    # retrieve_similar rankea por un score fusionado (sim+conf+imp+emocion) y SIEMPRE
    # devuelve top_k, asi que sin un piso de relevancia una consulta nueva surfacea
    # recuerdos no relacionados como si lo fueran. Piso conservador de coseno: descarta
    # solo lo ~0 (ruido), ordena por la similitud mostrada para que los numeros bajen.
    SIM_FLOOR = 0.1
    hits = sorted((h for h in hits if h.get("similarity", 0.0) >= SIM_FLOOR),
                  key=lambda h: h.get("similarity", 0.0), reverse=True)
    if not hits:
        return f"RESULTADO recordar '{query}': sin recuerdos relevantes"
    lines = [f"  ({h.get('similarity', 0):.2f}) {h.get('observation', '')[:120]}" for h in hits]
    return f"RESULTADO recordar '{query}':\n" + "\n".join(lines)


@tool("memorizar", "memorizar <texto>                     -- guarda en memoria episodica")
def _memorizar(args, ctx):
    # observe() RECHAZA entradas muy cortas ({"status":"rejected","reason":...});
    # antes se ignoraba el retorno y siempre se reportaba 'guardado' (mentira al
    # modelo). Reportar el rechazo real; en cualquier otro caso, guardado.
    res = ctx["ai"].observe(args.strip(), provided_label="agente_tarea")
    if isinstance(res, dict) and res.get("status") == "rejected":
        reason = res.get("reason", "desconocido")
        return (f"RESULTADO memorizar: NO se guardo (razon: {reason}). "
                "El texto debe ser mas largo (min ~5 chars y 2 palabras).")
    return "RESULTADO memorizar: guardado en memoria episodica"


def _fmt_kg_fact(d) -> str:
    """Formatea un hecho del KG legible para el modelo. Maneja las dos formas de
    dict (get_facts: subject/predicate/object; get_neighbors: concept/relation).
    Antes se usaba str(d)[:80], que volcaba el repr crudo de Python truncado."""
    if not isinstance(d, dict):
        return str(d)[:100]
    subj = d.get("subject", "")
    pred = d.get("predicate") or d.get("relation", "")
    obj = d.get("object") or d.get("concept", "")
    core = " ".join(str(p) for p in (subj, pred, obj) if p)
    w = d.get("weight")
    if isinstance(w, (int, float)):
        core += f" (w={w:g})"
    return core or str(d)[:100]


@tool("kg_buscar", "kg_buscar <concepto>                  -- hechos del grafo sobre un concepto")
def _kg_buscar(args, ctx):
    ai = ctx.get("ai")
    concept = args.strip()
    facts = ai.kg.get_facts(concept) or ai.kg.get_neighbors(concept)
    if not facts:
        return f"RESULTADO kg_buscar '{concept}': sin hechos"
    return f"RESULTADO kg_buscar '{concept}': " + " | ".join(_fmt_kg_fact(f) for f in facts[:10])


@tool("kg_agregar", "kg_agregar <sujeto> | <relacion> | <objeto>  -- agrega un hecho al grafo")
def _kg_agregar(args, ctx):
    parts = [p.strip() for p in re.split(r"\s*\|\s*", args)]
    if len(parts) != 3:
        return "RESULTADO kg_agregar ERROR: formato (sujeto | relacion | objeto)"
    subj, rel, obj = parts
    rel = rel.lower()   # add_triple normaliza con .lower(); igualar el pre-check
    from cognia.knowledge.graph import KnowledgeGraph
    if rel not in KnowledgeGraph.VALID_RELATIONS:
        return ("RESULTADO kg_agregar ERROR: relacion invalida. Validas: "
                + ", ".join(KnowledgeGraph.VALID_RELATIONS))
    # add_triple devuelve is_new: True=hecho nuevo, False=ya existia (lo REFUERZA,
    # sube weight). Antes False se reportaba 'no agregado' (falso: si esta en el KG).
    ok = ctx["ai"].kg.add_triple(subj, rel, obj, source="agente")
    estado = "OK (nuevo)" if ok else "OK (ya existia, reforzado)"
    return f"RESULTADO kg_agregar: ({subj} {rel} {obj}) {estado}"


@tool("anotar", "anotar <clave> | <valor>              -- guarda nota en memoria de trabajo")
def _anotar(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
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


# Best-of-N + juez EXPUESTO como tool (wire de BoN al loop /hacer, CORRIDA-2).
# Integracion aditiva: en vez de reescribir el loop ReAct (accion-por-accion),
# el agente INVOCA esta tool para escribir una funcion nueva; adentro corre el
# pipeline medido (test-first -> N candidatos temp>0 -> juez por EJECUCION de
# los tests visibles -> escribe el MEJOR). Mismo mecanismo que dio +10pp en el
# bench (cognia/agent/candidates.py), ahora usable en vivo.
_BON_N = 6  # candidatos por llamada (N-1 a temp 0.7 + 1 greedy); ~2-3 min CPU


# Umbral de dificultad para despertar el 7B (MoM fase 4): el mismo 0.30 con el
# que model_router.estimate_difficulty separa hard de easy. Pre-filtro barato:
# NO decide el escalado (eso lo decide el fallo REACTIVO de tests), solo evita
# el cold-start del 7B en tareas triviales-que-fallan.
_HEAVY_THRESHOLD = 0.30


def _bon_n(desc: str) -> tuple:
    """(N, dificultad): N adaptativo por dificultad ex-ante (cascada
    barato-primero). model_router.estimate_difficulty (cero LLM, calibrado
    contra las etiquetas del bench) decide cuanto computo invertir: pool
    chico donde el 3B casi siempre acierta, grande donde falla mas. El
    early-stop de best_of_n ya corta el caso trivial (greedy perfecto) a 1
    candidato; esto acota el costo del resto (~25s/candidato en el i3)."""
    from cognia.agent.model_router import estimate_difficulty
    d = estimate_difficulty(desc)
    if d < 0.15:
        return 3, d
    if d >= 0.50:
        return 10, d
    return _BON_N, d


# Telemetria append-only del BoN en vivo: la tupla (dificultad ex-ante,
# resultado real de los tests visibles, costo) por invocacion es EL dataset
# para recalibrar el umbral del router (hoy hand-tuned contra el bench) con
# trafico real. Best-effort: si el disco falla, la tool no se entera.
_BON_TELEMETRY = Path(__file__).parent / "generated_tools" / "_bon_telemetry.jsonl"


def _bon_log(rec: dict) -> None:
    try:
        _BON_TELEMETRY.parent.mkdir(parents=True, exist_ok=True)
        with _BON_TELEMETRY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


@tool("generar_codigo",
      "generar_codigo <ruta.py> | <descripcion con el nombre exacto `func(args)`>  "
      "-- genera N candidatos con test-first y ESCRIBE el mejor por tests")
def _generar_codigo(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO generar_codigo ERROR: formato (ruta.py | descripcion)"
    path_s, desc = parts[0].strip(), parts[1].strip()
    from cognia.agent.stepwise import extract_entry_point
    entry = extract_entry_point(desc) or extract_entry_point(path_s)
    if not entry:
        return ("RESULTADO generar_codigo ERROR: no identifique el nombre de la "
                "funcion; inclui `nombre(args)` en la descripcion.")
    try:
        wpath = _resolve_write_path(path_s)
    except ValueError as e:
        return f"RESULTADO generar_codigo ERROR: {e}"

    orch = _orch(ctx)

    def _code_gen(prompt, temperature=0.0, seed=None):
        return orch.infer(prompt, max_tokens=768, temperature=temperature).text or ""

    def _test_gen(prompt, temperature=0.0, seed=None):
        return orch.infer(prompt, max_tokens=256, temperature=temperature).text or ""

    from cognia.agent.candidates import best_of_n
    from cognia_v3.eval.benchmark_code import extract_code
    code_prompt = ("Escribe UNA funcion Python COMPLETA que cumpla esto. Responde "
                   "SOLO con un bloque ```python ...``` con la funcion, sin "
                   "explicaciones.\n\n" + desc)
    n_plan, dif = _bon_n(desc)
    _t0 = _time.time()
    try:
        out = best_of_n(_code_gen, code_prompt, desc, entry, extract_code,
                        n=n_plan, seed=42, test_gen_fn=_test_gen)
    except Exception as exc:
        return f"RESULTADO generar_codigo ERROR: {exc}"
    _best_t = out.get("ranking", [{}])[0] if out.get("ranking") else {}
    code = out.get("code", "")
    _score_3b, _total = _best_t.get("score"), _best_t.get("total")
    # Asserts visibles del test-first: los usa la mesa redonda (el escalado
    # 7B reemplaza `out` entero y los perderia).
    _visible = out.get("visible_tests") or []

    # ── Escalado REACTIVO al especialista de capacidad 7B (MoM fase 4) ──────
    # Si el mejor candidato del 3B FALLA sus tests visibles (o no produjo la
    # funcion) y la tarea es DURA, reintentar con el 7B (cascada 40->60% medida
    # en codigo duro). REACTIVO, no predictivo (el router predictivo medio
    # 45<60): el 7B solo dispara donde el 3B ya fallo -> jamas desperdicia
    # computo en lo que el 3B resolvia. Se queda con el mejor de (3B, 7B) por
    # score de tests visibles -> B nunca peor que A. Kill-switch COGNIA_HEAVY_
    # CODE OFF (default) => heavy_code_backend() es None => 0 cambios.
    # Lazy-load-usar-cerrar (RAM steady-state 0 en el i3 de 12GB).
    _escalado_7b, _score_7b = False, None
    # El 3B tiene CONFIRMACION de exito solo si genero tests visibles reales y los
    # paso TODOS. Sin tests (total=0) NO hay confirmacion: el e2e (burst_balloons,
    # 2026-07-10) cazo que el disparador viejo 'score<total' NUNCA saltaba con 0
    # tests visibles, aunque el codigo fallara los tests ocultos -> el +20pp del
    # gate no se materializaba en produccion. Ahora: en tarea dura, si el 3B no
    # CONFIRMA exito, escalar. El 'mejor de (3B,7B)' garantiza que escalar de mas
    # nunca empeora; el pre-filtro de dificultad acota el costo a tareas duras.
    _confirmado_3b = (_total and _score_3b is not None and _score_3b >= _total)
    _fallo_3b = (not _confirmado_3b) or (f"def {entry}" not in code)
    if _fallo_3b and dif >= _HEAVY_THRESHOLD:
        try:
            from node.heavy_code import heavy_code_backend, close_heavy_code
            _heavy = heavy_code_backend()
            if _heavy is not None:
                _pf = ctx.get("print_fn")
                if callable(_pf):
                    _pf("[detail]Codigo dificil: el 3B fallo sus tests -> "
                        "escalando al especialista 7B (mas lento)...[/detail]")
                try:
                    from cognia_v3.eval.benchmark_code import (
                        build_prompt, SYSTEM_PROMPT)
                    # GREEDY del 7B (1 candidato, prompt del gate), NO best_of_n.
                    # El probe (2026-07-10) MIDIO que el 7B greedy recupera 4/4
                    # tareas duras (single_number/rotate_array/min_jumps/put) que
                    # el best_of_n+juez-de-tests-visibles descartaba: el JUEZ debil
                    # (tests visibles autogenerados, 2/4) era el cuello, no el
                    # modelo ni el prompt. Greedy reproduce EXACTO el protocolo del
                    # gate bajo el que el 7B recupero 8/8 (+20pp). El 3B ya fallo/no
                    # confirmo, asi que el 7B (medido mejor en dura) es la mejor
                    # apuesta: quedarse con el si produjo la funcion.
                    _gate_prompt = build_prompt(desc, system=SYSTEM_PROMPT)
                    _raw7 = _heavy.generate(_gate_prompt, max_tokens=768,
                                            temperature=0.0, cache_prompt=False)
                    _code7 = extract_code(_raw7 or "")
                    if _code7.strip() and f"def {entry}" in _code7:
                        code = _code7
                        _best_t = {"score": None, "total": None}
                        out = {"n_generated": 1, "n_unique": 1,
                               "rank_mode": "7b_greedy", "code": _code7,
                               "ranking": [_best_t]}
                        _escalado_7b = True
                finally:
                    close_heavy_code()
        except Exception:
            pass   # cualquier falla del 7B -> quedarse con el 3B (fallback seguro)

    # ── Etapa 3 de la cascada: Qwen3.5-4B no-think (COLONIA E2, 2026-07-12) ──
    # MEDIDO (PREREG_E1_QWEN35 + union-oraculo): qwen35 RAW 17/40 > 3B 15/40
    # en el set duro, y 4 tareas las resuelve SOLO qwen35 (ni 3B ni 7B) ->
    # union de la colonia 27/40 vs 23/40 de la cascada 2-etapas. Dispara solo
    # en tarea dura cuando (a) no hay funcion valida aun, o (b) hay asserts
    # visibles y el candidato actual NO los pasa todos. El candidato q35
    # REEMPLAZA solo si (a) no habia funcion, o (b) mejora ESTRICTAMENTE el
    # score visible (keep-best; leccion del juez debil del deploy 7B).
    # Lazy-usar-cerrar (2.7GB); sin GGUF o COGNIA_FLEET30=0 -> no-op.
    _escalado_q35 = False
    if dif >= _HEAVY_THRESHOLD:
        _sin_funcion = f"def {entry}" not in code
        _score_v = None
        if not _sin_funcion and _visible:
            try:
                from cognia.agent.deliberation import (execution_feedback,
                                                       feedback_score)
                _score_v, _ = feedback_score(
                    execution_feedback(code, _visible, entry))
            except Exception:
                _score_v = None
        # Trigger por rama (cada una con su dato):
        #  (a) sin funcion valida -> q35 (adicion pura);
        #  (b) visibles fallando -> q35 compite por mejora ESTRICTA;
        #  (c) SIN visibles (0 asserts = sin confirmacion, la rama del fix
        #      burst_balloons) y el 7B NO tomo la tarea -> q35 reemplaza al
        #      greedy no-confirmado del 3B (E1: q35 17/40 > 3B 15/40 RAW).
        #      Si el 7B YA reemplazo, se respeta (su gate midio 8/8 con
        #      ocultos; no hay dato head-to-head q35-vs-7B sin oraculo).
        #      Gap cazado por el live check e2e DBG1 (2026-07-12): el
        #      trigger original exigia visibles y esta rama quedaba muda.
        _sin_confirmacion = (not _visible and not _confirmado_3b
                             and not _escalado_7b)
        if (_sin_funcion
                or (_score_v is not None and _score_v < len(_visible))
                or _sin_confirmacion):
            try:
                from node.fleet_registry import (close_fleet_member,
                                                 fleet_backend)
                _q35 = fleet_backend("qwen35_4b")
                if _q35 is not None:
                    _pf = ctx.get("print_fn")
                    if callable(_pf):
                        _pf("[detail]Etapa 3 de la colonia: probando con "
                            "Qwen3.5-4B...[/detail]")
                    try:
                        from cognia_v3.eval.benchmark_code import (
                            SYSTEM_PROMPT as _SP35, build_prompt as _bp35)
                        _raw35 = _q35.generate(
                            _bp35(desc, system=_SP35) + "<think>\n\n</think>\n\n",
                            max_tokens=640, temperature=0.0,
                            cache_prompt=False)
                        _code35 = extract_code(_raw35 or "")
                        if _code35.strip() and f"def {entry}" in _code35:
                            _usar = _sin_funcion or _sin_confirmacion
                            if not _usar and _visible:
                                from cognia.agent.deliberation import (
                                    execution_feedback as _ef35,
                                    feedback_score as _fs35)
                                _s35, _ = _fs35(_ef35(_code35, _visible, entry))
                                _usar = _s35 > (_score_v or 0)
                            if _usar:
                                code = _code35
                                _best_t = {"score": None, "total": None}
                                out = {"n_generated": out.get("n_generated"),
                                       "n_unique": out.get("n_unique"),
                                       "rank_mode": "q35_greedy",
                                       "code": _code35,
                                       "ranking": [_best_t]}
                                _escalado_q35 = True
                    finally:
                        close_fleet_member("qwen35_4b")
            except Exception:
                pass   # cualquier falla del q35 -> quedarse con lo previo

    # ── Mesa redonda FLEET-30 (deliberacion ENTRE modelos; default OFF) ─────
    # COGNIA_DELIBERACION=1 la activa (gate con tests OCULTOS pre-registrado:
    # PREREG_DELIBERACION.md; hasta que PASE, queda opt-in). Etapa ADITIVA:
    # solo corre si tras 3B (+7B si escalo) el candidato NO pasa todos sus
    # tests visibles y la tarea es dura. La critica es EJECUCION real
    # (deliberation.py, keep-best estricto): el 7B/3B se pasan el candidato
    # con el traceback del sandbox y lo reparan por turnos. Riesgo declarado:
    # con tests visibles DEBILES la mesa puede sobre-ajustar a un assert
    # equivocado (leccion del juez del escalado 7B) — por eso el gate que
    # decide el default mide con tests ocultos, y el trigger exige asserts.
    _mesa_mejoro = False
    if (os.environ.get("COGNIA_DELIBERACION", "").strip().lower()
            in ("1", "on", "true", "yes")) and _visible and dif >= _HEAVY_THRESHOLD:
        try:
            from cognia.agent.deliberation import (deliberate,
                                                   execution_feedback,
                                                   feedback_score)
            _fb0 = execution_feedback(code, _visible, entry)
            _s0, _t0v = feedback_score(_fb0)
            if _t0v and _s0 < _t0v:
                _pf = ctx.get("print_fn")
                if callable(_pf):
                    _pf("[detail]Mesa redonda: los modelos deliberan sobre el "
                        "candidato (feedback de ejecucion real)...[/detail]")
                _parts = []
                _hv = None
                try:
                    from node.heavy_code import (close_heavy_code,
                                                 heavy_code_backend)
                    _hv = heavy_code_backend()
                except Exception:
                    _hv = None
                if _hv is not None:
                    from cognia_v3.eval.benchmark_code import (
                        SYSTEM_PROMPT as _MR_SP, build_prompt as _mr_bp)

                    def _gen_7b(p, temperature=0.0, seed=None, _h=_hv):
                        return _h.generate(_mr_bp(p, system=_MR_SP),
                                           max_tokens=768, temperature=0.0,
                                           cache_prompt=False) or ""
                    _parts.append(("7b", _gen_7b))
                _parts.append(("3b", _code_gen))
                try:
                    _mesa = deliberate(desc, entry, _parts, extract_code,
                                       _visible, initial_code=code, rounds=2)
                finally:
                    if _hv is not None:
                        close_heavy_code()
                if _mesa.get("mejorado") and _mesa.get("code", "").strip():
                    code = _mesa["code"]
                    _best_t = {"score": _mesa["score"], "total": _mesa["total"]}
                    out = {"n_generated": out.get("n_generated"),
                           "n_unique": out.get("n_unique"),
                           "rank_mode": "mesa_redonda", "code": code,
                           "ranking": [_best_t]}
                    _mesa_mejoro = True
        except Exception:
            pass   # la mesa nunca rompe la tool: fallback al candidato previo

    _bon_log({
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "task_head": desc[:120], "difficulty": dif, "n_planned": n_plan,
        "n_generated": out.get("n_generated"), "rank_mode": out.get("rank_mode"),
        "score": _best_t.get("score"), "total": _best_t.get("total"),
        "secs": round(_time.time() - _t0, 1),
        "escalado_7b": _escalado_7b, "score_3b": _score_3b, "score_7b": _score_7b,
        "mesa_redonda": _mesa_mejoro, "escalado_q35": _escalado_q35,
    })
    if not code.strip() or f"def {entry}" not in code:
        return (f"RESULTADO generar_codigo ERROR: no se genero una funcion "
                f"'{entry}' valida en {out.get('n_generated', 0)} candidatos.")
    wpath.parent.mkdir(parents=True, exist_ok=True)
    wpath.write_text(code + "\n", encoding="utf-8")
    ft = ctx.setdefault("agent_state", {}).setdefault("files_touched", [])
    if str(wpath) not in ft:
        ft.append(str(wpath))
        ctx["agent_state"]["files_touched"] = ft[-15:]
    best = out.get("ranking", [{}])[0] if out.get("ranking") else {}
    _tag7 = " [escalado a 7B]" if _escalado_7b else ""
    if _escalado_q35:
        _tag7 += " [etapa 3: Qwen3.5]"
    if _mesa_mejoro:
        _tag7 += " [mesa redonda]"
    return (f"RESULTADO generar_codigo {_disp(wpath)}: OK (mejor de "
            f"{out.get('n_unique', '?')} candidatos unicos, rank={out.get('rank_mode')}, "
            f"tests visibles {best.get('score', '?')}/{best.get('total', '?')}, "
            f"{len(code)} chars){_tag7}")


# HERMES self-tooling EN VIVO: el agente puede pedir una tool nueva sin salir
# del loop /hacer. Reusa el mismo pipeline generar->scan->sandbox->registrar
# de cognia.agent.tool_synthesis (regla 8 CLAUDE.md: nada auto-generado se
# vuelve ejecutable sin pasar _static_safety_scan + sandbox); esta tool NO
# agrega un camino nuevo de ejecucion, solo lo dispara desde el loop. danger=True
# porque el resultado queda invocable (staged) sin revision humana previa.
@tool("crear_herramienta",
      "crear_herramienta <nombre> | <proposito> | <test_input> | <resultado_esperado>  "
      "-- sintetiza y REGISTRA una tool nueva (sandbox-verificada, queda staged)",
      danger=True)
def _crear_herramienta(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=3)
    if len(parts) != 4 or any(not p.strip() for p in parts):
        return ("RESULTADO crear_herramienta ERROR: formato (usa nombre | proposito | "
                "test_input | resultado_esperado), 4 partes separadas por '|'")
    nombre, proposito, test_input, esperado = (p.strip() for p in parts)

    from cognia.agent.tool_synthesis import ToolSpec, synthesize_and_register, load_generated_tools
    spec = ToolSpec(name=nombre, doc=proposito[:60], purpose=proposito,
                    test_input=test_input, expect_contains=esperado)
    res = synthesize_and_register(spec, orch=_orch(ctx), max_attempts=2)
    if not res.get("ok"):
        # motivo REAL (scan estatico, sandbox, o repair agotado) -- nunca un
        # "no se pudo" generico; el modelo/usuario necesita saber que fallo.
        return f"RESULTADO crear_herramienta ERROR: {res.get('reason', 'desconocido')}"

    load_generated_tools()  # la deja invocable YA en este proceso (TOOLS global)
    return (f"RESULTADO crear_herramienta: '{nombre}' creada y verificada "
            f"(version {res.get('version', '?')}, tier {res.get('tier', 'staged')}). "
            "Ya es invocable con su nombre.")


# Sub-agente acotado: delega una SUBTAREA a una corrida anidada de _run_agent_task
# con (a) un ROL que restringe las tools disponibles (investigador=solo lectura,
# implementador=+escritura/ejecucion), (b) un sub-presupuesto de pasos, y (c) el
# router de modelo por dificultad (el runner elige 3B/7B). El runner recursivo se
# inyecta en ctx['_run_agent'] desde cli.py (evita el import circular tools<->cli).
# Profundidad acotada (ctx['_delegation_depth']) para que un sub-agente no delegue
# infinitamente.
_MAX_DELEGATION_DEPTH = 2


@tool("delegar_subtarea",
      "delegar_subtarea <investigador|implementador> | <subtarea>  "
      "-- corre la subtarea en un sub-agente con tools acotadas por rol y su propio presupuesto")
def _delegar_subtarea(args, ctx):
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        return ("RESULTADO delegar_subtarea ERROR: formato (rol | subtarea); "
                "rol = investigador | implementador")
    rol, subtarea = parts[0].strip().lower(), parts[1].strip()
    if rol not in ROLE_TOOLS:
        return (f"RESULTADO delegar_subtarea ERROR: rol '{rol}' desconocido "
                f"(usa: {', '.join(ROLE_TOOLS)})")

    runner = ctx.get("_run_agent")
    if not callable(runner):
        return ("RESULTADO delegar_subtarea ERROR: delegacion no disponible en "
                "este contexto")

    depth = ctx.get("_delegation_depth", 0)
    if depth >= _MAX_DELEGATION_DEPTH:
        return (f"RESULTADO delegar_subtarea ERROR: profundidad maxima de "
                f"delegacion ({_MAX_DELEGATION_DEPTH}) alcanzada; resolve la "
                "subtarea directamente.")

    # Sub-presupuesto: la mitad de lo que quede (o un piso), para que la
    # subtarea no se coma el presupuesto entero del padre.
    remaining = ctx.get("_steps_remaining", 8)
    sub_budget = max(3, int(remaining) // 2)
    pf = ctx.get("print_fn")
    if callable(pf):
        pf(f"[detail]delegando a sub-agente '{rol}' (presupuesto {sub_budget})[/detail]")
    try:
        sub_result = runner(subtarea, allowed_tools=ROLE_TOOLS[rol],
                            max_steps=sub_budget, delegation_depth=depth + 1)
    except Exception as exc:
        return f"RESULTADO delegar_subtarea ERROR: {exc}"
    return f"RESULTADO delegar_subtarea ({rol}): {str(sub_result)[:600]}"
