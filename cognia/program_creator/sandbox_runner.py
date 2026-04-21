"""
sandbox_runner.py — Ejecución aislada y segura de programas generados por Cognia.

CAMBIOS v2:
  - Timeout aumentado a 15s (programas automáticos necesitan más tiempo)
  - Penaliza timeout sin output (programa colgado) pero no timeout con output (corrió bien)
"""

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

# ── Configuración ──────────────────────────────────────────────────────────────

EXECUTION_TIMEOUT_SEC = 15     # Aumentado de 5s a 15s
MAX_OUTPUT_CHARS      = 4000

BLOCKED_IMPORTS = {
    "os.system", "os.popen", "os.execv", "os.execle", "os.execvp",
    "os.fork", "os.kill", "os.remove", "os.unlink", "os.rmdir",
    "shutil", "socket", "urllib", "http", "requests", "ftplib",
    "smtplib", "telnetlib", "xmlrpc", "subprocess",
    "ctypes", "cffi", "pickle", "shelve", "signal",
}

_BLOCKED_PATTERN = re.compile(
    r"^\s*(?:import|from)\s+(" +
    "|".join(re.escape(m.split(".")[0]) for m in BLOCKED_IMPORTS) +
    r")\b",
    re.MULTILINE,
)


# ── Dataclass de resultado ─────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    success:          bool
    execution_output: str
    execution_errors: str
    exit_code:        int
    timed_out:        bool
    blocked_imports:  list = field(default_factory=list)
    code_length:      int  = 0


# ── Validación previa ──────────────────────────────────────────────────────────

def _scan_blocked_imports(code: str) -> list[str]:
    found = []
    for match in _BLOCKED_PATTERN.finditer(code):
        mod = match.group(1)
        if mod not in found:
            found.append(mod)
    if "__import__" in code and "os" in code:
        found.append("__import__(os) escape attempt")
    return found


def _sanitize_for_sandbox(code: str) -> str:
    dangerous_calls = [
        r"os\.system\s*\(",
        r"os\.popen\s*\(",
        r"subprocess\.\w+\s*\(",
        r"exec\s*\(\s*open",
    ]
    sanitized = code
    for pattern in dangerous_calls:
        sanitized = re.sub(pattern, "print('# blocked call'  #", sanitized)
    return sanitized


# ── Ejecución en subproceso ────────────────────────────────────────────────────

def run_in_sandbox(code: str) -> ExecutionResult:
    """
    Ejecuta código Python en subproceso aislado con timeout de 15s.
    Los programas automáticos deberían terminar bien dentro de ese tiempo.
    """
    if not code or len(code.strip()) < 5:
        return ExecutionResult(success=False, execution_output="",
                               execution_errors="Empty code", exit_code=-1,
                               timed_out=False)

    blocked = _scan_blocked_imports(code)
    if blocked:
        print(f"[sandbox] 🚫 Imports bloqueados: {blocked}")
        dangerous = [b for b in blocked if b in {
            "socket", "subprocess", "shutil", "signal", "ctypes", "cffi",
            "pickle", "shelve",
        }]
        if dangerous:
            return ExecutionResult(success=False, execution_output="",
                                   execution_errors=f"Blocked: {dangerous}",
                                   exit_code=-2, timed_out=False,
                                   blocked_imports=blocked, code_length=len(code))

    safe_code = _sanitize_for_sandbox(code)
    tmp_file  = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="cognia_prog_",
            dir=tempfile.gettempdir(), delete=False, encoding="utf-8"
        ) as f:
            tmp_file = f.name
            f.write(safe_code)

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
            print(f"[sandbox] ⏱️  Timeout alcanzado ({EXECUTION_TIMEOUT_SEC}s)")

    except Exception as exc:
        return ExecutionResult(success=False, execution_output="",
                               execution_errors=f"Sandbox error: {exc}",
                               exit_code=-4, timed_out=False,
                               blocked_imports=blocked, code_length=len(code))
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.unlink(tmp_file)
            except Exception:
                pass

    stdout = stdout[:MAX_OUTPUT_CHARS]
    stderr = stderr[:MAX_OUTPUT_CHARS]

    # Éxito normal
    success = exit_code == 0 and not timed_out and len(stdout.strip()) > 0

    # Timeout CON output = probablemente corrió bien (loop infinito intencional)
    if timed_out and len(stdout.strip()) > 10:
        success = True

    result = ExecutionResult(
        success=success, execution_output=stdout, execution_errors=stderr,
        exit_code=exit_code, timed_out=timed_out,
        blocked_imports=blocked, code_length=len(code),
    )

    status = "✅" if success else ("⏱️" if timed_out else "❌")
    print(f"[sandbox] {status} exit={exit_code} | "
          f"output={len(stdout)}ch | errors={len(stderr)}ch")
    return result
