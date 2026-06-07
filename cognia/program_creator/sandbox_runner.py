"""
sandbox_runner.py — Ejecucion aislada de programas generados por Cognia.

Dos capas de proteccion:
  1. AST analysis — detecta todos los vectores de escape Python-level antes de ejecutar
  2. Runtime __import__ guard inyectado en el archivo temporal — defensa en profundidad

Sin Docker ni dependencias externas. Subprocess con env reducido.
"""

import ast
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import List, Tuple

EXECUTION_TIMEOUT_SEC = 15
MAX_OUTPUT_CHARS      = 4000

# Single source of truth for both AST check and runtime guard
BLOCKED_MODULES: frozenset = frozenset({
    # NOTE: 'builtins' is intentionally NOT blocked. The real __import__ is
    # captured privately in the runtime guard (_ri default-arg), so re-importing
    # builtins can't restore it. Blocking builtins used to cascade-fail every
    # pure-Python stdlib module (re, json, string, random, collections all
    # trigger an internal `import builtins` while loading), making the sandbox
    # reject almost any non-trivial program.
    "cffi",
    "ctypes",
    "ftplib",
    "http",
    "importlib",
    "multiprocessing",
    "pickle",
    "requests",
    "shelve",
    "shutil",
    "signal",
    "smtplib",
    "socket",
    "subprocess",
    "telnetlib",
    "urllib",
    "xmlrpc",
})

BLOCKED_OS_ATTRS: frozenset = frozenset({
    "chmod", "chown", "execle", "execv", "execve", "execvp", "execvpe",
    "fork", "kill", "makedirs", "mkdir", "popen", "remove", "removedirs",
    "rename", "replace", "rmdir", "spawnl", "spawnle", "spawnv", "spawnve",
    "startfile", "system", "unlink",
})

# Runtime guard injected at the top of every sandboxed file.
# Overrides __import__ so dynamic escapes (exec, eval, importlib) are also blocked.
_RUNTIME_GUARD = (
    "import builtins as _b\n"
    "_ri = _b.__import__\n"
    "_BM = frozenset({"
    + ", ".join(f'"{m}"' for m in sorted(BLOCKED_MODULES))
    + "})\n"
    # _ri is captured as a keyword-only default so _si keeps a private reference
    # to the real __import__ even after `del _ri` removes it from the sandbox
    # namespace. Without this capture, `del _ri` left _si referencing a deleted
    # global -> NameError on EVERY import (even safe stdlib like math/re/json),
    # silently breaking all sandboxed code that imports anything.
    "def _si(name, *a, _ri=_ri, **kw):\n"
    "    if name.split('.')[0] in _BM:\n"
    "        raise ImportError('[sandbox] blocked: ' + name)\n"
    "    return _ri(name, *a, **kw)\n"
    "_b.__import__ = _si\n"
    "del _ri, _si, _b\n"
)


@dataclass
class ExecutionResult:
    success:          bool
    execution_output: str
    execution_errors: str
    exit_code:        int
    timed_out:        bool
    blocked_imports:  list = field(default_factory=list)
    code_length:      int  = 0


# ── AST analysis ───────────────────────────────────────────────────────────────

class _SandboxVisitor(ast.NodeVisitor):
    """
    Walks the AST collecting policy violations.
    Catches what regex cannot: __import__(), importlib.import_module(), os.system(), etc.
    """

    def __init__(self) -> None:
        self.violations: List[str] = []

    def _flag(self, msg: str, lineno: int) -> None:
        self.violations.append(f"line {lineno}: {msg}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in BLOCKED_MODULES:
                self._flag(f"import {alias.name}", node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            if root in BLOCKED_MODULES:
                self._flag(f"from {node.module} import ...", node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # __import__("socket")
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            if node.args and isinstance(node.args[0], ast.Constant):
                mod = str(node.args[0].value).split(".")[0]
                if mod in BLOCKED_MODULES:
                    self._flag(f"__import__('{node.args[0].value}')", node.lineno)
            else:
                self._flag("dynamic __import__ call", node.lineno)
        # importlib.import_module(...)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
            if node.args and isinstance(node.args[0], ast.Constant):
                mod = str(node.args[0].value).split(".")[0]
                if mod in BLOCKED_MODULES:
                    self._flag(f"import_module('{node.args[0].value}')", node.lineno)
            else:
                self._flag("dynamic import_module call", node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == "os":
            if node.attr in BLOCKED_OS_ATTRS:
                self._flag(f"os.{node.attr}", node.lineno)
        self.generic_visit(node)


def _ast_scan(code: str) -> Tuple[List[str], str]:
    """
    Parse code and walk the AST.
    Returns (violations, parse_error). parse_error is "" on success.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [], f"SyntaxError: {e}"
    visitor = _SandboxVisitor()
    visitor.visit(tree)
    return visitor.violations, ""


# ── Ejecucion en subproceso ────────────────────────────────────────────────────

def run_in_sandbox(code: str) -> ExecutionResult:
    """
    Executes Python code with two-layer protection:
    1. AST scan rejects code with dangerous imports or os.* calls before any execution.
    2. _RUNTIME_GUARD is prepended to the temp file to block dynamic-import escapes.
    """
    if not code or len(code.strip()) < 5:
        return ExecutionResult(success=False, execution_output="",
                               execution_errors="Empty code", exit_code=-1,
                               timed_out=False)

    violations, parse_error = _ast_scan(code)

    if parse_error:
        return ExecutionResult(success=False, execution_output="",
                               execution_errors=parse_error, exit_code=-1,
                               timed_out=False, code_length=len(code))

    if violations:
        return ExecutionResult(success=False, execution_output="",
                               execution_errors="Sandbox violation: " + violations[0],
                               exit_code=-2, timed_out=False,
                               blocked_imports=violations, code_length=len(code))

    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="cognia_prog_",
            dir=tempfile.gettempdir(), delete=False, encoding="utf-8",
        ) as f:
            tmp_file = f.name
            f.write(_RUNTIME_GUARD + "\n" + code)

        try:
            proc = subprocess.run(
                [sys.executable, tmp_file],
                capture_output=True, text=True,
                timeout=EXECUTION_TIMEOUT_SEC,
                env={
                    "PATH":       os.environ.get("PATH", "/usr/bin:/bin"),
                    "PYTHONPATH": "",
                    "HOME":       tempfile.gettempdir(),
                    "TMPDIR":     tempfile.gettempdir(),
                    "TERM":       "dumb",
                },
            )
            timed_out = False
            exit_code = proc.returncode
            stdout    = proc.stdout or ""
            stderr    = proc.stderr or ""

        except subprocess.TimeoutExpired as tex:
            timed_out = True
            exit_code = -3
            stdout    = (tex.stdout or b"").decode("utf-8", errors="replace") \
                        if isinstance(tex.stdout, bytes) else (tex.stdout or "")
            stderr    = f"[sandbox] Timeout after {EXECUTION_TIMEOUT_SEC}s"

    except Exception as exc:
        return ExecutionResult(success=False, execution_output="",
                               execution_errors=f"Sandbox error: {exc}",
                               exit_code=-4, timed_out=False,
                               code_length=len(code))
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.unlink(tmp_file)
            except Exception:
                pass

    stdout  = stdout[:MAX_OUTPUT_CHARS]
    stderr  = stderr[:MAX_OUTPUT_CHARS]
    success = exit_code == 0 and not timed_out and len(stdout.strip()) > 0
    if timed_out and len(stdout.strip()) > 10:
        success = True

    return ExecutionResult(
        success=success, execution_output=stdout, execution_errors=stderr,
        exit_code=exit_code, timed_out=timed_out,
        blocked_imports=violations, code_length=len(code),
    )
