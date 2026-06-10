"""
cognia/agents/workers/dev_tools.py - Tier 1 dev tools

Herramientas deterministas de ingenieria de software para el agent runtime:
  - search_code: busqueda regex read-only archivo-por-archivo (os.walk + re)
  - write_file / edit_file: escrituras confinadas a AGENT_WORKSPACE_ROOT
  - run_tests: pytest en subprocess aislado dentro del workspace

0 LLM calls. Solo stdlib. Seguridad: path traversal bloqueado via Path.resolve(),
nombres sensibles (.env, *secret*, binarios) y .git/ nunca escribibles, y todo
.py se valida con ast.parse ANTES de persistir (con backup .bak del original).
"""

from __future__ import annotations

import ast
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Workspace raiz para escrituras/tests del agente. Variable de modulo para que
# tests y deploys puedan redirigirlo sin tocar el environment global.
AGENT_WORKSPACE_ROOT = (
    os.environ.get("COGNIA_AGENT_WORKSPACE")
    or str(_REPO_ROOT / "agent_workspace")
)

SEARCH_TIMEOUT_S = 15
# venv* cubre venv, venv312, .venv; model_shards/checkpoints son pesados y binarios
_SEARCH_IGNORE_DIRS = {".git", "node_modules", "__pycache__", "model_shards", "checkpoints"}

# Nombres que el agente nunca puede escribir (secretos y binarios ejecutables)
_BLOCKED_WRITE_PATTERNS = (".env", "*secret*", "*.exe", "*.dll")


# --- search_code (read-only, sin confinamiento de workspace) -----------------

def _is_ignored_dir(name: str) -> bool:
    return name in _SEARCH_IGNORE_DIRS or name.startswith("venv") or name.startswith(".venv")


def search_code(pattern: str, root: str = ".", glob: str = "*.py", max_results: int = 50) -> dict:
    """Busqueda regex de contenido. Retorna matches como {file, line_no, line}."""
    rx = re.compile(pattern)
    deadline = time.monotonic() + SEARCH_TIMEOUT_S
    matches: List[dict] = []
    truncated = False
    timed_out = False

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]
        for fname in filenames:
            if time.monotonic() > deadline:
                timed_out = True
                break
            if not fnmatch.fnmatch(fname, glob):
                continue
            fpath = Path(dirpath) / fname
            try:
                with open(fpath, encoding="utf-8", errors="replace") as fh:
                    for line_no, line in enumerate(fh, 1):
                        if rx.search(line):
                            matches.append({
                                "file": str(fpath),
                                "line_no": line_no,
                                "line": line.rstrip("\r\n")[:300],  # cap anti-explosion de contexto
                            })
                            if len(matches) >= max_results:
                                truncated = True
                                break
            except OSError:
                continue
            if truncated:
                break
        if truncated or timed_out:
            break

    return {"matches": matches, "count": len(matches), "truncated": truncated, "timed_out": timed_out}


# --- gates de seguridad compartidos por write_file / edit_file / run_tests ---

def _workspace() -> Path:
    return Path(AGENT_WORKSPACE_ROOT).resolve()

def _resolve_in_workspace(path: str) -> Path:
    """Resuelve path (relativo al workspace o absoluto) y exige que quede DENTRO."""
    ws = _workspace()
    p = Path(path)
    if not p.is_absolute():
        p = ws / p
    resolved = p.resolve()
    # resolve() neutraliza ".." y symlinks antes del check de prefijo
    if resolved == ws or not resolved.is_relative_to(ws):
        raise ValueError(f"path outside agent workspace ({ws}): {path}")
    return resolved

def _check_writable(resolved: Path) -> None:
    name = resolved.name.lower()
    for pat in _BLOCKED_WRITE_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            raise ValueError(f"blocked file name (matches {pat}): {resolved.name}")
    if ".git" in resolved.parts:
        raise ValueError(f"writing under .git is blocked: {resolved}")

def _validate_py(content: str, context: str) -> None:
    try:
        ast.parse(content)
    except SyntaxError as e:
        raise ValueError(f"{context}: invalid Python syntax at line {e.lineno}: {e.msg} (not written)")


# --- write_file ---------------------------------------------------------------

def write_file(path: str, content: str) -> dict:
    """Crea/sobrescribe un archivo dentro del workspace. Backup .bak si existia."""
    resolved = _resolve_in_workspace(path)
    _check_writable(resolved)
    if resolved.suffix == ".py":
        _validate_py(content, "write_file")

    backup = None
    existed = resolved.is_file()
    if existed:
        backup = str(resolved) + ".bak"
        shutil.copy2(resolved, backup)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return {
        "path": str(resolved),
        "bytes_written": len(content.encode("utf-8")),
        "created": not existed,
        "backup": backup,
    }


# --- edit_file ----------------------------------------------------------------

def edit_file(path: str, old_string: str, new_string: str, count: int = 1) -> dict:
    """Reemplazo exacto de substring. old_string debe aparecer exactamente count veces."""
    resolved = _resolve_in_workspace(path)
    _check_writable(resolved)
    if not resolved.is_file():
        raise ValueError(f"file not found in workspace: {path}")

    text = resolved.read_text(encoding="utf-8")
    found = text.count(old_string)
    if found != count:
        raise ValueError(f"old_string appears {found} times, expected exactly {count}")

    new_text = text.replace(old_string, new_string, count)
    # validar el archivo RESULTANTE completo antes de persistir
    if resolved.suffix == ".py":
        _validate_py(new_text, "edit_file")

    backup = str(resolved) + ".bak"
    shutil.copy2(resolved, backup)
    resolved.write_text(new_text, encoding="utf-8")
    return {"path": str(resolved), "replacements": count, "backup": backup}


# --- run_tests ------------------------------------------------------------------

_SUMMARY_COUNT_RX = re.compile(r"(\d+)\s+(passed|failed|errors?)")

def _venv_python() -> str:
    cand = _REPO_ROOT / "venv312" / "Scripts" / "python.exe"
    return str(cand) if cand.is_file() else sys.executable


def run_tests(path: str, pattern: str = "", timeout_s: int = 120) -> dict:
    """Corre pytest sobre un path DENTRO del workspace, en subprocess aislado."""
    resolved = _resolve_in_workspace(path)
    if not resolved.exists():
        raise ValueError(f"test path not found in workspace: {path}")

    cmd = [_venv_python(), "-m", "pytest", str(resolved), "-x", "-q", "--tb=short",
           "-p", "no:cacheprovider"]
    if pattern:
        cmd += ["-k", pattern]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_s, cwd=str(_workspace()),
        )
    except subprocess.TimeoutExpired:
        return {"passed": 0, "failed": 0, "errors": 1,
                "summary_line": f"TIMEOUT after {timeout_s}s", "tail": "", "timed_out": True}

    out = proc.stdout or ""
    if proc.stderr:
        out += "\n" + proc.stderr

    summary_line = ""
    for line in reversed(out.splitlines()):
        if any(k in line for k in ("passed", "failed", "error", "no tests ran")):
            summary_line = line.strip()
            break

    counts = {"passed": 0, "failed": 0, "errors": 0}
    for n, kind in _SUMMARY_COUNT_RX.findall(summary_line):
        key = "errors" if kind.startswith("error") else kind
        counts[key] = int(n)

    return {**counts, "summary_line": summary_line, "tail": out[-2000:], "timed_out": False}
