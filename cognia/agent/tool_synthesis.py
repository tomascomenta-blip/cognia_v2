"""
cognia/agent/tool_synthesis.py
=============================
Self-extending tools: Cognia writes new agent tools, PROVES they work in a
sandbox, and only then registers them. Nothing unverified ever becomes callable.

Safety model (the important part):
  - A generated tool is a PURE function ``run(args: str) -> str`` -- string in,
    string out. No ctx, no ai, no network, no filesystem. This keeps the
    verification sound (a sandboxed run fully exercises it) and the blast radius
    near zero.
  - Verification = real execution: the code is run in cognia.program_creator's
    sandbox (subprocess, timeout, blocked-import detection) against a concrete
    test input; it must run cleanly AND produce the expected output AND import
    nothing dangerous. Fail any check -> discarded, never written.
  - Only verified tools land in generated_tools/<name>.py + _manifest.json, and
    only the manifest's verified entries are loaded into the registry.

Concrete, not abstract: plain dataclass + functions, reusing the existing
sandbox rather than inventing a new one.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

from cognia.program_creator.sandbox_runner import run_in_sandbox

GENERATED_DIR = Path(__file__).parent / "generated_tools"
MANIFEST_PATH = GENERATED_DIR / "_manifest.json"

# Tool names must be simple identifiers (also used as filenames).
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")

# Generated tools are PURE: only these stdlib modules may be imported, and these
# builtins are forbidden. Checked statically before the tool is ever executed.
_ALLOWED_IMPORTS = {
    "re", "math", "json", "datetime", "string", "random", "collections",
    "itertools", "functools", "textwrap", "unicodedata", "decimal", "fractions",
    "statistics", "base64", "hashlib", "html", "urllib.parse",
}
_FORBIDDEN_NAMES = {"open", "eval", "exec", "__import__", "compile", "input",
                    "globals", "locals", "vars", "getattr", "setattr"}

# CUALQUIER referencia (no solo llamada) a estos nombres se rechaza. Cierra el
# bypass `__builtins__.eval(args)` (verificado 2026-07-03): antes el scan solo
# miraba llamadas con func=ast.Name y atributos que EMPIEZAN con "__"; una
# Attribute `__builtins__.eval` esquivaba ambos (attr 'eval' no empieza con
# "__", y el nodo no es una Call-de-Name). Ahora se caza el Name `__builtins__`
# en si (aunque no se llame) y el acceso por atributo a nombres peligrosos.
# Tambien `f = eval; f(x)` cae: la referencia Name('eval') se rechaza sola.
_NAME_BLOCKLIST = _FORBIDDEN_NAMES | {
    "__builtins__", "__globals__", "__loader__", "__spec__", "breakpoint",
    "delattr", "memoryview", "globals", "locals",
}
# Acceso por ATRIBUTO a estos (obj.<attr>) se rechaza aunque obj sea benigno.
# NO se incluyen nombres genericos que colisionan con metodos de modulos
# permitidos (json.loads, functools.reduce, etc.): los modulos peligrosos
# (os/subprocess/pickle) ya estan fuera del allowlist de imports, asi que su
# unico camino seria via __builtins__ (bloqueado por _NAME_BLOCKLIST).
_ATTR_BLOCKLIST = {
    "eval", "exec", "system", "popen", "spawn", "spawnl", "spawnv", "fdopen",
    "__import__", "compile", "open", "getattr", "setattr", "delattr",
    "check_output", "Popen", "startfile",
}


def _static_safety_scan(tree: ast.AST) -> str:
    """Return '' if the AST is safe, else a human reason. No execution.

    Defensa: allowlist de imports + blocklist de nombres peligrosos EN
    CUALQUIER POSICION (referencia, no solo llamada) + blocklist de acceso por
    atributo. El objetivo es que ningun camino a un builtin de ejecucion
    (eval/exec/open/__import__/os.system) sobreviva el scan estatico."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name not in _ALLOWED_IMPORTS and root not in _ALLOWED_IMPORTS:
                    return f"import no permitido: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod not in _ALLOWED_IMPORTS and mod.split(".")[0] not in _ALLOWED_IMPORTS:
                return f"import no permitido: from {mod}"
        elif isinstance(node, ast.Name) and node.id in _NAME_BLOCKLIST:
            return f"nombre prohibido: {node.id}"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_NAMES:
                return f"llamada prohibida: {node.func.id}()"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in _ATTR_BLOCKLIST:
                return f"acceso a atributo prohibido: .{node.attr}"
    return ""


@dataclass
class ToolSpec:
    """What to build and how to prove it works."""
    name: str            # registry name + filename, e.g. "invertir_texto"
    doc: str             # one-line doc shown to the model
    purpose: str         # natural-language description for code generation
    test_input: str      # args passed to run() during verification
    expect_contains: str  # substring the output must contain to pass


# ── ciclo de vida (CP2, 06_AGENTE_PLAN §3): tiers + gate crear-vs-reusar ──
# Tiers de confianza: builtin (tools.py) > verified (generada, sandbox OK y
# >= VERIFY_AFTER_OK usos exitosos) > staged (generada, sin historial).
# Una staged que acumula >= RETIRE_AFTER_FAIL fallos se retira (no se carga
# mas). Explicitamente NO se imita el skip-por-contenedor de Hermes:
# defensa en profundidad, el sandbox y el scan corren SIEMPRE.

VERIFY_AFTER_OK = 3      # usos exitosos para ascender staged -> verified
RETIRE_AFTER_FAIL = 2    # fallos para retirar una staged


def find_similar_tool(name: str, doc: str = "", threshold: float = 0.75):
    """Gate crear-vs-reusar (§3.2): entry del manifest cuyo nombre (o doc)
    se parece al pedido, o None. Barato: difflib sobre nombre + primera
    linea de doc. Evita acumular near-duplicados en el registry."""
    import difflib
    target = (name or "").lower().strip()
    if not target:
        return None
    for entry in _load_manifest():
        if entry.get("tier") == "retired":
            continue
        existing = entry.get("name", "").lower()
        ratio = difflib.SequenceMatcher(None, target, existing).ratio()
        if ratio >= threshold:
            return entry
        if doc and entry.get("doc"):
            dratio = difflib.SequenceMatcher(
                None, doc.lower()[:60], entry["doc"].lower()[:60]).ratio()
            if dratio >= max(threshold, 0.8):
                return entry
    return None


def record_tool_use(name: str, ok: bool) -> str:
    """Registra un uso de una tool generada y aplica las transiciones de
    tier. Devuelve el tier resultante ('' si la tool no esta en el
    manifest). staged -> verified con VERIFY_AFTER_OK exitos; staged ->
    retired con RETIRE_AFTER_FAIL fallos (una retirada no vuelve sola)."""
    entries = _load_manifest()
    for entry in entries:
        if entry.get("name") != name:
            continue
        entry["uses_ok"] = entry.get("uses_ok", 0) + (1 if ok else 0)
        entry["uses_fail"] = entry.get("uses_fail", 0) + (0 if ok else 1)
        tier = entry.get("tier", "staged")
        if tier == "staged" and entry["uses_fail"] >= RETIRE_AFTER_FAIL:
            entry["tier"] = "retired"
        elif tier == "staged" and entry["uses_ok"] >= VERIFY_AFTER_OK:
            entry["tier"] = "verified"
        _save_manifest(entries)
        return entry["tier"]
    return ""


def _orch_from_ctx(ctx):
    """Orquestador YA vivo en el contexto del loop (ctx['ai']._orchestrator).
    NO crea uno nuevo: un fallo silencioso de una tool generada no debe
    levantar el modelo como efecto secundario. None si no hay uno --
    handle_live_failure se lo salta y el fallo cuenta como siempre."""
    ai = ctx.get("ai") if isinstance(ctx, dict) else None
    return getattr(ai, "_orchestrator", None) if ai is not None else None


def _survives_real_input(code: str, real_args: str) -> bool:
    """El fix de un repair debe correr LIMPIO (sin crash/timeout/import
    bloqueado) con el input REAL que disparo el fallo -- no alcanza con
    pasar solo el test_input original de la spec. Repite scan+sandbox aca
    (no solo el sandbox): la regla 9 de CLAUDE.md es que nada auto-generado
    se ejecuta sin pasar el scan estatico primero, sin excepciones."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    if _static_safety_scan(tree):
        return False
    harness = code + (
        "\n\nif __name__ == '__main__':\n"
        f"    print(run({real_args!r}))\n"
    )
    result = run_in_sandbox(harness)
    return result.success and not result.timed_out and not result.blocked_imports


def handle_live_failure(name: str, args: str, error: str, orch=None) -> str:
    """Repair-on-live-failure (TAREA 4): en el PRIMER fallo real de una tool
    generada, guarda (args, error) como caso extra en el manifest y, si hay
    orquestador disponible, intenta UN repair_tool_code con el error real.

    Si el fix pasa el pipeline completo -- el test ORIGINAL de la spec (via
    synthesize_and_register, que corre verify_tool de nuevo) Y no crashea con
    el input real que fallo (_survives_real_input) -- se re-registra (nueva
    version, con history de TAREA 3) y este fallo NO cuenta para el retiro.
    Si no hay orquestador, o el repair no alcanza, cuenta como
    record_tool_use(name, False) de siempre (regresion cubierta por test).
    Devuelve el tier resultante."""
    entries = _load_manifest()
    entry = next((e for e in entries if e.get("name") == name), None)
    if entry is None:
        return record_tool_use(name, ok=False)

    # Solo el PRIMER fallo dispara guardado+repair: fallos siguientes (tool
    # ya reparada una vez, o repair que no alcanzo) cuentan derecho hacia el
    # retiro sin gastar otro intento de modelo.
    if entry.get("uses_fail", 0) == 0:
        cases = entry.setdefault("extra_cases", [])
        cases.append({"test_input": args, "error": str(error)[:300]})
        _save_manifest(entries)

        if orch is not None:
            tool_file = GENERATED_DIR / f"{name}.py"
            if tool_file.exists():
                prev_code = tool_file.read_text(encoding="utf-8")
                spec = ToolSpec(
                    name=name, doc=entry.get("doc", name),
                    purpose=entry.get("purpose", ""),
                    test_input=entry.get("test_input", ""),
                    expect_contains=entry.get("expect_contains", ""),
                )
                try:
                    fixed = repair_tool_code(spec, prev_code, str(error), orch)
                except Exception:
                    fixed = ""
                if fixed and _survives_real_input(fixed, args):
                    res = synthesize_and_register(spec, code=fixed)
                    if res.get("ok"):
                        return res.get("tier", "staged")

    return record_tool_use(name, ok=False)


# ── manifest helpers ───────────────────────────────────────────────────

def _load_manifest() -> list:
    if not MANIFEST_PATH.exists():
        return []
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_manifest(entries: list) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    # Escritura ATOMICA (temp + os.replace): el repo corre managers
    # autonomos en paralelo; un write_text directo puede dejar el manifest a
    # medio escribir si dos procesos coinciden. os.replace es atomico en el
    # mismo volumen, asi que un lector nunca ve JSON truncado (no elimina la
    # carrera de lost-update entre dos writers, pero evita corromper el archivo).
    import os
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, MANIFEST_PATH)


# ── verification (the heart) ───────────────────────────────────────────

def verify_tool(code: str, test_input: str, expect_contains: str) -> tuple:
    """
    Prove a generated tool works by actually running it.

    Returns (ok: bool, reason: str). ``ok`` is True only when the code parses,
    defines run(), executes cleanly in the sandbox on test_input, imports nothing
    blocked, and the output contains expect_contains.
    """
    # 1. Syntax + must define a top-level run() taking one arg.
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"sintaxis: linea {e.lineno}: {e.msg}"
    run_fn = next(
        (n for n in tree.body
         if isinstance(n, ast.FunctionDef) and n.name == "run"),
        None,
    )
    if run_fn is None:
        return False, "no define una funcion run()"
    if len(run_fn.args.args) < 1:
        return False, "run() debe aceptar un argumento (args)"

    # 2. Static safety scan (allowlisted imports, no dangerous builtins).
    unsafe = _static_safety_scan(tree)
    if unsafe:
        return False, unsafe

    # 3. Real execution in the sandbox against the test input.
    harness = code + (
        "\n\nif __name__ == '__main__':\n"
        f"    print(run({test_input!r}))\n"
    )
    result = run_in_sandbox(harness)

    if result.blocked_imports:
        return False, f"imports bloqueados: {result.blocked_imports}"
    if result.timed_out:
        return False, "timeout en ejecucion"
    if not result.success:
        return False, f"error de ejecucion: {result.execution_errors[:150]}"
    if expect_contains and expect_contains not in result.execution_output:
        return False, (
            f"output no contiene lo esperado ({expect_contains!r}); "
            f"obtenido: {result.execution_output[:120]!r}"
        )
    return True, "verificada"


# ── code generation ────────────────────────────────────────────────────

_GEN_PROMPT = """Escribe UNA funcion Python pura llamada run que implemente esta herramienta.

Herramienta: {name}
Proposito: {purpose}

Reglas ESTRICTAS:
- Firma exacta: def run(args: str) -> str
- args es texto de entrada; devuelve texto.
- Pura: sin import de os/sys/subprocess/socket/shutil, sin red, sin archivos.
- Solo modulos estandar seguros si hace falta: re, math, json, datetime, string.
- Sin print, sin input, sin codigo fuera de la funcion.
- Codigo completo y funcional.

Responde SOLO con el codigo de la funcion, sin explicaciones ni ```."""


def _clean_code(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", t)
    # Keep from the first 'def run' onward (drop any preamble the model added).
    idx = t.find("def run")
    if idx >= 0:
        t = t[idx:]
    # Cortar en la primera linea que sea un fence ``` : el cuerpo de una tool
    # pura NUNCA contiene ```, asi que todo desde ahi (fences anidados que el
    # 3B cierra con varios ``` seguidos, + cualquier prosa posterior) es basura
    # que rompia ast.parse. Antes se quitaba un solo fence y quedaban backticks
    # sueltos ("invalid syntax" en la ultima linea) — el codigo del modelo era
    # valido, la limpieza no.
    out = []
    for ln in t.split("\n"):
        if ln.lstrip().startswith("```"):
            break
        out.append(ln)
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out).strip()


_REPAIR_PROMPT = """Tu funcion run fallo la verificacion. Corrigela.

Herramienta: {name}
Proposito: {purpose}

Codigo anterior:
{prev}

Error de verificacion: {error}

Recuerda: def run(args: str) -> str, PURA, IMPORTA todo lo que uses (ej. import re),
sin print, sin os/sys/subprocess. Responde SOLO el codigo corregido, sin ```."""


def generate_tool_code(spec: ToolSpec, orch) -> str:
    """Ask the model to write the tool body. Returns cleaned code text."""
    prompt = _GEN_PROMPT.format(name=spec.name, purpose=spec.purpose)
    return _clean_code(orch.infer(prompt).text)


def repair_tool_code(spec: ToolSpec, prev_code: str, error: str, orch) -> str:
    """Feed the failure back to the model and ask for a corrected version."""
    prompt = _REPAIR_PROMPT.format(
        name=spec.name, purpose=spec.purpose, prev=prev_code, error=error
    )
    return _clean_code(orch.infer(prompt).text)


# ── synthesize -> verify -> register ───────────────────────────────────

def _derive_rule(purpose: str, name: str) -> dict:
    """Regla BASICA para el validador de ACCION (TAREA 6, puente auto-mejora):
    toda tool sintetizada entra a structure.RULES, aunque sea generica -- una
    tool que Cognia se construye a si misma pasa por el mismo validador que
    las tools escritas a mano.

    Si el proposito declara K campos separados por '|' (la misma convencion
    que ya usan las tools multi-arg del registry, p.ej. 'ruta | contenido')
    se infiere parts=K con esos nombres; si el primer campo suena a ruta,
    path0. Si no hay '|', la regla minima: el arg completo no puede ser vacio."""
    fields = [f.strip() for f in purpose.split("|")] if "|" in purpose else []
    if len(fields) >= 2:
        rule = {"parts": len(fields), "names": tuple(fields)}
        if any(w in fields[0].lower() for w in ("ruta", "path", "archivo", "file")):
            rule["path0"] = True
        return rule
    return {"nonempty": name}


def _register_derived_rule(name: str, purpose: str) -> None:
    """Deriva y registra la regla en structure.RULES. Local import (mismo
    patron que load_generated_tools con cognia.agent.tools): evita un ciclo
    de import al nivel de modulo. Best-effort, nunca rompe el registro."""
    try:
        from cognia.agent import structure as _structure
        _structure.register_rule(name, _derive_rule(purpose, name))
    except Exception:
        pass


def _write_verified(spec: ToolSpec, code: str, reason: str) -> dict:
    """Persist a tool that has already passed verification. Internal."""
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (GENERATED_DIR / "__init__.py").touch(exist_ok=True)
    tool_file = GENERATED_DIR / f"{spec.name}.py"

    prev = next((e for e in _load_manifest() if e.get("name") == spec.name), None)
    # TAREA 3 (version history): antes de sobreescribir una version EXISTENTE,
    # preservarla en _history/<name>_v<version_vieja>.py -- permite
    # rollback_tool si la nueva version sale peor (repair-on-failure, o un
    # re-registro manual que degrada).
    if prev is not None and tool_file.exists():
        hist_dir = GENERATED_DIR / "_history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        prev_version = prev.get("version", "0.0.0")
        (hist_dir / f"{spec.name}_v{prev_version}.py").write_text(
            tool_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    header = (
        f'"""Auto-generado y verificado por Cognia. Tool: {spec.name}\n'
        f'Proposito: {spec.purpose}\n"""\n\n'
    )
    tool_file.write_text(header + code + "\n", encoding="utf-8")

    entries = [e for e in _load_manifest() if e.get("name") != spec.name]
    # Version semver simple: re-registrar una tool existente sube el minor
    # (historia de evolucion auditable en el manifest, §3.7).
    version = "0.1.0"
    if prev and prev.get("version"):
        try:
            major, minor, patch = prev["version"].split(".")
            version = f"{major}.{int(minor) + 1}.{patch}"
        except Exception:
            pass
    entries.append({
        "name": spec.name,
        "doc": spec.doc,
        "purpose": spec.purpose,
        "test_input": spec.test_input,
        "expect_contains": spec.expect_contains,
        "verified": True,
        # ciclo de vida CP2: toda tool nueva nace staged con contadores en 0
        "tier": "staged",
        "version": version,
        "uses_ok": 0,
        "uses_fail": 0,
    })
    _save_manifest(entries)
    _register_derived_rule(spec.name, spec.purpose)
    return {"ok": True, "name": spec.name, "reason": reason, "file": str(tool_file),
            "version": version, "tier": "staged"}


def rollback_tool(name: str, version: str) -> dict:
    """Restaura <name> a la <version> guardada en _history/ (TAREA 3):
    copia el archivo historico al lugar activo y ajusta el manifest --
    version vuelve a la restaurada, tier vuelve a 'staged' y uses_ok/uses_fail
    se resetean a 0 (la version restaurada arranca su propio historial de
    confianza, igual que una tool recien registrada)."""
    hist_file = GENERATED_DIR / "_history" / f"{name}_v{version}.py"
    if not hist_file.exists():
        return {"ok": False, "name": name,
                "reason": f"no hay historial de '{name}' version {version}"}
    entries = _load_manifest()
    entry = next((e for e in entries if e.get("name") == name), None)
    if entry is None:
        return {"ok": False, "name": name, "reason": f"'{name}' no esta en el manifest"}

    tool_file = GENERATED_DIR / f"{name}.py"
    tool_file.write_text(hist_file.read_text(encoding="utf-8"), encoding="utf-8")
    entry["version"] = version
    entry["tier"] = "staged"
    entry["uses_ok"] = 0
    entry["uses_fail"] = 0
    _save_manifest(entries)
    return {"ok": True, "name": name, "version": version, "file": str(tool_file)}


def synthesize_and_register(spec: ToolSpec, orch=None, code: str = None,
                            max_attempts: int = 3) -> dict:
    """
    Full pipeline. Provide ``code`` directly (deterministic, e.g. tests) or an
    ``orch`` to generate it. Verifies, and only on success writes the tool file +
    manifest entry. Returns a result dict {ok, name, reason, file, attempts}.

    When generating, retries up to ``max_attempts`` with self-repair: each failure
    feeds the previous code + error back to the model so it can fix mistakes like
    a forgotten import -- which is exactly what small models get wrong most.
    """
    if not _NAME_RE.match(spec.name):
        return {"ok": False, "name": spec.name, "reason": "nombre invalido"}

    # Gate crear-vs-reusar (§3.2): un near-duplicado existente se reusa en
    # vez de duplicarse. Re-registrar EXACTAMENTE el mismo nombre es una
    # actualizacion legitima (sube version) y pasa de largo.
    similar = find_similar_tool(spec.name, spec.doc)
    if similar and similar.get("name") != spec.name:
        return {"ok": False, "name": spec.name,
                "reason": f"similar existente: {similar['name']} "
                          f"(tier {similar.get('tier', 'staged')}) — reusar o editar esa",
                "existing": similar["name"]}

    # Deterministic single-shot path (tests / known code).
    if code is not None:
        ok, reason = verify_tool(code, spec.test_input, spec.expect_contains)
        if not ok:
            return {"ok": False, "name": spec.name, "reason": reason}
        return _write_verified(spec, code, reason)

    if orch is None:
        return {"ok": False, "name": spec.name, "reason": "sin code ni orch"}

    last_reason, prev_code = "", ""
    for attempt in range(max_attempts):
        try:
            if attempt == 0:
                cand = generate_tool_code(spec, orch)
            else:
                cand = repair_tool_code(spec, prev_code, last_reason, orch)
        except Exception as e:
            last_reason = f"generacion fallo: {e}"
            continue
        ok, reason = verify_tool(cand, spec.test_input, spec.expect_contains)
        if ok:
            res = _write_verified(spec, cand, reason)
            res["attempts"] = attempt + 1
            return res
        last_reason, prev_code = reason, cand

    return {"ok": False, "name": spec.name,
            "reason": f"tras {max_attempts} intentos: {last_reason}",
            "attempts": max_attempts}


# ── load verified generated tools into the registry ────────────────────

def synthesized_capabilities_note(limit: int = 8) -> str:
    """
    One short line describing the tools Cognia has built for itself, for folding
    into the system prompt so its self-description evolves with its capabilities.
    Empty string if it hasn't made any yet.
    """
    verified = [e for e in _load_manifest() if e.get("verified")]
    if not verified:
        return ""
    names = [e["name"] for e in verified[:limit]]
    return ("Herramientas que creaste y verificaste vos mismo: "
            + ", ".join(names) + ".")


def load_generated_tools(registry: dict = None) -> int:
    """
    Register every verified generated tool into the live tool registry.

    Each is wrapped to the standard fn(args, ctx)->str contract; the pure run()
    ignores ctx. Returns how many were loaded. Safe to call repeatedly.
    """
    from cognia.agent import tools as _tools
    reg = registry if registry is not None else _tools.TOOLS

    loaded = 0
    for entry in _load_manifest():
        if not entry.get("verified"):
            continue
        # Una tool retirada (staged con >= RETIRE_AFTER_FAIL fallos) no se
        # carga mas: la degradacion es efectiva, no decorativa (§3.7).
        if entry.get("tier") == "retired":
            continue
        name = entry.get("name", "")
        tool_file = GENERATED_DIR / f"{name}.py"
        if not _NAME_RE.match(name) or not tool_file.exists():
            continue
        ns: dict = {}
        try:
            exec(compile(tool_file.read_text(encoding="utf-8"), str(tool_file), "exec"), ns)
        except Exception:
            continue
        run = ns.get("run")
        if not callable(run):
            continue
        # TAREA 6: re-derivar la regla en cada carga (RULES en memoria no
        # sobrevive un reinicio del proceso; el manifest en disco si).
        _register_derived_rule(name, entry.get("purpose", ""))

        def _make(run_fn, tool_name):
            def _wrapped(args, ctx):
                # Cada uso alimenta los contadores de tier (ascenso staged->
                # verified / retiro). Best-effort: el registro nunca rompe
                # la ejecucion de la tool.
                err_msg = None
                try:
                    out = f"RESULTADO {tool_name}: {run_fn(args)}"
                    ok = True
                except Exception as exc:
                    err_msg = str(exc)
                    out = f"RESULTADO {tool_name} ERROR: {exc}"
                    ok = False
                try:
                    if ok:
                        record_tool_use(tool_name, True)
                    else:
                        # TAREA 4: repair-on-live-failure en vez de contar el
                        # fallo a ciegas -- solo si hay orquestador YA vivo
                        # en ctx (nunca levanta el modelo por esto).
                        handle_live_failure(tool_name, args, err_msg or "",
                                            orch=_orch_from_ctx(ctx))
                except Exception:
                    try:
                        record_tool_use(tool_name, False)
                    except Exception:
                        pass
                return out
            return _wrapped

        tier = entry.get("tier", "staged")
        reg[name] = {
            "fn": _make(run, name),
            "doc": f"{entry.get('doc', name)}  [auto-generada, {tier}]",
            "danger": False,
            "tier": tier,
        }
        loaded += 1
    return loaded
