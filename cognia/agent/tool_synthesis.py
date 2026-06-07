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


def _static_safety_scan(tree: ast.AST) -> str:
    """Return '' if the AST is safe, else a human reason. No execution."""
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
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_NAMES:
                return f"llamada prohibida: {node.func.id}()"
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"acceso a dunder prohibido: .{node.attr}"
    return ""


@dataclass
class ToolSpec:
    """What to build and how to prove it works."""
    name: str            # registry name + filename, e.g. "invertir_texto"
    doc: str             # one-line doc shown to the model
    purpose: str         # natural-language description for code generation
    test_input: str      # args passed to run() during verification
    expect_contains: str  # substring the output must contain to pass


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
    MANIFEST_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
        if t.endswith("```"):
            t = t[:-3]
    # Keep from the first 'def run' onward (drop any preamble the model added).
    idx = t.find("def run")
    return t[idx:].strip() if idx >= 0 else t.strip()


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

def _write_verified(spec: ToolSpec, code: str, reason: str) -> dict:
    """Persist a tool that has already passed verification. Internal."""
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (GENERATED_DIR / "__init__.py").touch(exist_ok=True)
    tool_file = GENERATED_DIR / f"{spec.name}.py"
    header = (
        f'"""Auto-generado y verificado por Cognia. Tool: {spec.name}\n'
        f'Proposito: {spec.purpose}\n"""\n\n'
    )
    tool_file.write_text(header + code + "\n", encoding="utf-8")

    entries = [e for e in _load_manifest() if e.get("name") != spec.name]
    entries.append({
        "name": spec.name,
        "doc": spec.doc,
        "purpose": spec.purpose,
        "test_input": spec.test_input,
        "expect_contains": spec.expect_contains,
        "verified": True,
    })
    _save_manifest(entries)
    return {"ok": True, "name": spec.name, "reason": reason, "file": str(tool_file)}


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

        def _make(run_fn, tool_name):
            def _wrapped(args, ctx):
                try:
                    return f"RESULTADO {tool_name}: {run_fn(args)}"
                except Exception as exc:
                    return f"RESULTADO {tool_name} ERROR: {exc}"
            return _wrapped

        reg[name] = {
            "fn": _make(run, name),
            "doc": f"{entry.get('doc', name)}  [auto-generada]",
            "danger": False,
        }
        loaded += 1
    return loaded
