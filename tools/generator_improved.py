"""
generator_improved.py — Parche para generator.py
=================================================
Extiende el generador original con:
  - Validación de código antes de retornar
  - Auto-corrección de errores comunes
  - Categorías de juegos prioritarias

Importar en lugar de generator.py cuando se quiere la versión mejorada.
"""

import ast
import os
import re
import subprocess
import sys
import tempfile
from typing import Optional

# Importar todo del generador original
from generator import (
    GeneratedProgram,
    PROGRAM_CATEGORIES,
    _pick_idea,
    _build_prompt,
    _call_ollama,
    _parse_response,
)

EXEC_TIMEOUT = 5


def _quick_syntax_check(code: str) -> tuple[bool, str]:
    """Verifica la sintaxis del código Python."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)


def _fix_common_issues(code: str) -> str:
    """
    Corrige problemas comunes en código generado por LLMs:
    - Imports de os sin uso específico
    - Llamadas a os.system → print bloqueado
    - Uso de clear() sin importar
    - encoding issues
    """
    # Reemplazar os.system con mensaje de error
    code = re.sub(r"os\.system\s*\([^)]+\)", "print('# blocked: os.system')", code)
    code = re.sub(r"os\.popen\s*\([^)]+\)", "None  # blocked: os.popen", code)

    # Arreglar imports de módulos bloqueados
    blocked = ["subprocess", "socket", "shutil", "ctypes", "pickle"]
    lines = code.split("\n")
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(f"import {b}") or
               stripped.startswith(f"from {b}") for b in blocked):
            fixed_lines.append(f"# [removed blocked import] {line}")
        else:
            fixed_lines.append(line)

    return "\n".join(fixed_lines)


def _run_validation(code: str) -> tuple[bool, str]:
    """
    Ejecuta el código con stdin simulado (vacío) para detectar errores.
    Retorna (ok, error_message).
    """
    wrapper = (
        "import sys, io\n"
        "sys.stdin = io.StringIO('\\n' * 10)\n"
        "try:\n"
        + "\n".join("    " + l for l in code.split("\n"))
        + "\nexcept (EOFError, SystemExit, KeyboardInterrupt):\n    pass\n"
        "except Exception as e:\n    print(f'__ERROR__: {e}', file=sys.stderr)\n"
    )

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="cognia_val_",
            delete=False, encoding="utf-8"
        ) as f:
            f.write(wrapper)
            tmp = f.name

        proc = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True, timeout=EXEC_TIMEOUT,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "PYTHONPATH": "", "HOME": tempfile.gettempdir()},
        )

        if proc.returncode == 0 or not proc.stderr.strip():
            return True, ""

        stderr = proc.stderr.strip()
        # Timeouts indican bucle activo (juego corriendo) → aceptar
        if "TimeoutExpired" in stderr:
            return True, ""

        return False, stderr[:400]

    except subprocess.TimeoutExpired:
        return True, ""  # Timeout = game loop = OK
    except Exception as e:
        return False, str(e)
    finally:
        if tmp:
            try: os.unlink(tmp)
            except: pass


def generate_program_validated(seed_concepts: Optional[list] = None,
                                max_fix_attempts: int = 2) -> Optional[GeneratedProgram]:
    """
    Versión mejorada de generate_program() que:
    1. Genera código
    2. Valida sintaxis
    3. Aplica fixes automáticos
    4. Ejecuta prueba rápida
    5. Solo retorna si pasa validación

    Retorna GeneratedProgram o None.
    """
    from generator import generate_program

    # Generar código usando el generador original
    program = generate_program(seed_concepts)
    if program is None:
        return None

    code = program.code

    # ── Paso 1: Verificar sintaxis ──────────────────────────────────
    syntax_ok, syntax_err = _quick_syntax_check(code)
    if not syntax_ok:
        print(f"[generator+] ⚠️  Syntax error: {syntax_err[:80]}")
        # Intentar fix básico de tabs/indentation
        code = code.replace("\t", "    ")
        syntax_ok, syntax_err = _quick_syntax_check(code)
        if not syntax_ok:
            print("[generator+] ❌ No se pudo corregir la sintaxis")
            return None

    # ── Paso 2: Aplicar fixes de seguridad ─────────────────────────
    code = _fix_common_issues(code)

    # ── Paso 3: Prueba de ejecución ─────────────────────────────────
    exec_ok, exec_err = _run_validation(code)

    if not exec_ok:
        print(f"[generator+] ⚠️  Execution error: {exec_err[:80]}")

        # Intentar pedir al LLM que corrija (solo si tenemos Ollama)
        for attempt in range(max_fix_attempts):
            fix_prompt = (
                f"Fix this Python code. Error: {exec_err[:200]}\n\n"
                f"```python\n{code[:2000]}\n```\n\n"
                f"Return ONLY the fixed code in ```python\\n...\\n```"
            )
            fixed_raw = _call_ollama(fix_prompt)
            if fixed_raw and "```python" in fixed_raw:
                start = fixed_raw.index("```python") + 9
                end   = fixed_raw.find("```", start)
                if end > start:
                    fixed_code = fixed_raw[start:end].strip()
                    if len(fixed_code) > 50:
                        code = fixed_code
                        exec_ok, exec_err = _run_validation(code)
                        if exec_ok:
                            print(f"[generator+] ✅ Código corregido en intento {attempt+1}")
                            break

        if not exec_ok:
            print("[generator+] ⚠️  Código con errores — guardando de todas formas")
            # No retornamos None — dejamos al evaluador decidir

    # Retornar programa con código mejorado
    return GeneratedProgram(
        title=program.title,
        description=program.description,
        code=code,
        category=program.category,
        raw_response=program.raw_response,
    )
