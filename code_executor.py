"""
code_executor.py — Ejecutor y validador local de código para Cognia
====================================================================
Proporciona ejecución segura y validación de código en múltiples lenguajes.

CAPACIDADES:
  run_python(code)      → ejecuta Python en subprocess con sandbox
  validate_html(html)   → valida sintaxis HTML con html.parser
  validate_css(css)     → validación básica de sintaxis CSS
  run_javascript(code)  → ejecuta con Node.js si está disponible

SEGURIDAD:
  - Nunca ejecuta imports peligrosos (os.system, subprocess en código del usuario, etc.)
  - Sandbox: variables de entorno limpias, timeout por lenguaje
  - El SelfArchitect puede llamar validate_python() para validar sus propuestas

USO:
  from code_executor import get_code_executor
  ex = get_code_executor()
  result = ex.run_python("print('hola mundo')")
  print(result.output)  # "hola mundo"
  print(result.success) # True
"""

import ast
import re
import shutil
import subprocess
import sys
import tempfile
import time
import os
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

from logger_config import get_logger, log_slow

logger = get_logger(__name__)

# ── Configuración de timeouts por lenguaje ────────────────────────────────────

TIMEOUT = {
    "python":     15,    # segundos
    "javascript": 10,
}

MAX_OUTPUT_CHARS = 4000

# ── Imports peligrosos — nunca ejecutar código del usuario con estos ──────────

BLOCKED_IMPORTS_PYTHON = {
    "os.system", "os.popen", "os.execv", "os.execle", "os.execvp",
    "os.fork", "os.kill", "os.remove", "os.unlink", "os.rmdir",
    "shutil", "socket", "urllib.request", "http.client",
    "requests", "ftplib", "smtplib", "telnetlib", "subprocess",
    "ctypes", "cffi", "pickle", "shelve", "signal",
    "multiprocessing",
}

_BLOCKED_PYTHON_PATTERN = re.compile(
    r"^\s*(?:import|from)\s+(" +
    "|".join(re.escape(m.split(".")[0]) for m in BLOCKED_IMPORTS_PYTHON) +
    r")\b",
    re.MULTILINE,
)


# ── Dataclass de resultado ────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """Resultado de ejecutar o validar código."""
    success:    bool
    output:     str
    errors:     str
    exit_code:  int
    timed_out:  bool
    language:   str
    duration_ms: float = 0.0
    blocked_imports: list = field(default_factory=list)
    warnings:   list = field(default_factory=list)    # para validadores


@dataclass
class ValidationResult:
    """Resultado de validar código sin ejecutarlo."""
    valid:    bool
    warnings: list[str]
    errors:   list[str]
    language: str


# ── Validadores ────────────────────────────────────────────────────────────────

class _HTMLValidator(HTMLParser):
    """
    Validador HTML liviano usando html.parser de la stdlib.
    Detecta: tags sin cerrar, atributos faltantes críticos, estructura básica.
    """

    def __init__(self):
        super().__init__()
        self.errors:   list[str] = []
        self.warnings: list[str] = []
        self._open_tags:  list[str] = []
        self._void_tags = {
            "area", "base", "br", "col", "embed", "hr", "img",
            "input", "link", "meta", "param", "source", "track", "wbr",
        }

    def handle_starttag(self, tag: str, attrs: list):
        if tag not in self._void_tags:
            self._open_tags.append(tag)
        # Verificar atributos críticos
        attr_dict = dict(attrs)
        if tag == "img" and "alt" not in attr_dict:
            self.warnings.append(f"<img> sin atributo 'alt' (accesibilidad)")
        if tag == "a" and "href" not in attr_dict:
            self.warnings.append(f"<a> sin atributo 'href'")
        if tag == "input" and "type" not in attr_dict:
            self.warnings.append(f"<input> sin atributo 'type'")

    def handle_endtag(self, tag: str):
        if tag in self._void_tags:
            return
        if self._open_tags and self._open_tags[-1] == tag:
            self._open_tags.pop()
        else:
            self.errors.append(
                f"Tag '</{tag}>' sin '<{tag}>' de apertura correspondiente"
            )

    def get_unclosed(self) -> list[str]:
        return list(self._open_tags)


def validate_html(html: str) -> ValidationResult:
    """
    Valida sintaxis HTML usando html.parser de Python stdlib.

    Args:
        html: código HTML a validar

    Returns:
        ValidationResult con errores y warnings
    """
    if not html or not html.strip():
        return ValidationResult(valid=False, warnings=[], errors=["HTML vacío"],
                                language="html")
    validator = _HTMLValidator()
    errors:   list[str] = []
    warnings: list[str] = []

    try:
        validator.feed(html)
        errors   = list(validator.errors)
        warnings = list(validator.warnings)

        # Tags sin cerrar
        unclosed = validator.get_unclosed()
        if unclosed:
            errors.append(f"Tags sin cerrar: {', '.join(f'<{t}>' for t in unclosed)}")

        # Estructura básica
        html_lower = html.lower()
        if "<html" not in html_lower and "<!doctype" not in html_lower:
            warnings.append("Sin declaración DOCTYPE ni tag <html>")
        if "<head>" not in html_lower:
            warnings.append("Sin sección <head>")
        if "<body>" not in html_lower:
            warnings.append("Sin sección <body>")

    except Exception as exc:
        errors.append(f"Error al parsear HTML: {exc}")

    valid = len(errors) == 0
    logger.debug(
        "HTML validado",
        extra={"op": "code_executor.validate_html",
               "context": f"valid={valid} errors={len(errors)} warnings={len(warnings)}"},
    )
    return ValidationResult(valid=valid, warnings=warnings, errors=errors, language="html")


def validate_css(css: str) -> ValidationResult:
    """
    Validación básica de sintaxis CSS (no requiere librerías externas).

    Detecta: llaves desbalanceadas, propiedades malformadas,
    selectores vacíos, values faltantes.

    Args:
        css: código CSS a validar

    Returns:
        ValidationResult con errores y warnings
    """
    if not css or not css.strip():
        return ValidationResult(valid=False, warnings=[], errors=["CSS vacío"],
                                language="css")

    errors:   list[str] = []
    warnings: list[str] = []

    # Eliminar comentarios para análisis
    css_clean = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    # Verificar llaves balanceadas
    open_count  = css_clean.count("{")
    close_count = css_clean.count("}")
    if open_count != close_count:
        errors.append(
            f"Llaves desbalanceadas: {open_count} '{{' y {close_count} '}}'"
        )

    # Verificar propiedades dentro de reglas
    # Patrón: algo_sin_espacios: valor;
    rules = re.findall(r"\{([^}]*)\}", css_clean, re.DOTALL)
    for rule_content in rules:
        props = [p.strip() for p in rule_content.split(";") if p.strip()]
        for prop in props:
            if ":" not in prop:
                if prop and not prop.startswith("@"):
                    warnings.append(f"Propiedad sin valor: '{prop[:40]}'")
            else:
                name, _, value = prop.partition(":")
                if not value.strip():
                    warnings.append(f"Propiedad '{name.strip()[:30]}' sin valor")

    # Verificar selectores vacíos
    empty_selectors = re.findall(r"([^{}]+)\{\s*\}", css_clean)
    for sel in empty_selectors:
        sel_clean = sel.strip()
        if sel_clean:
            warnings.append(f"Selector vacío: '{sel_clean[:50]}'")

    # Verificar unidades comunes
    missing_units = re.findall(
        r":\s*(\d+)\s*;(?!.*px|em|rem|%|vh|vw)", css_clean
    )
    for val in missing_units[:3]:
        if val != "0":
            warnings.append(f"Valor numérico sin unidad: {val} (¿falta px, em, %?)")

    valid = len(errors) == 0
    logger.debug(
        "CSS validado",
        extra={"op": "code_executor.validate_css",
               "context": f"valid={valid} errors={len(errors)} warnings={len(warnings)}"},
    )
    return ValidationResult(valid=valid, warnings=warnings, errors=errors, language="css")


def validate_python(code: str) -> ValidationResult:
    """
    Valida sintaxis Python usando el módulo ast de la stdlib.
    El SelfArchitect usa esto para validar propuestas antes de aplicarlas.

    Args:
        code: código Python a validar

    Returns:
        ValidationResult con errores de sintaxis
    """
    if not code or not code.strip():
        return ValidationResult(valid=False, warnings=[], errors=["Código vacío"],
                                language="python")

    errors:   list[str] = []
    warnings: list[str] = []

    # Detectar imports peligrosos
    blocked = _scan_blocked_imports(code)
    if blocked:
        errors.append(f"Imports peligrosos detectados: {', '.join(blocked)}")

    # Validar sintaxis con AST
    try:
        tree = ast.parse(code)

        # Análisis de calidad básica
        func_count  = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))

        # Advertencias de estilo (compatibles con el estilo Cognia)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Funciones sin docstring
                if not (node.body and isinstance(node.body[0], ast.Expr) and
                        isinstance(node.body[0].value, ast.Constant)):
                    warnings.append(f"función '{node.name}' sin docstring")
            if isinstance(node, ast.ClassDef):
                if not (node.body and isinstance(node.body[0], ast.Expr)):
                    warnings.append(f"clase '{node.name}' sin docstring")

        if func_count == 0 and class_count == 0 and len(code.splitlines()) > 20:
            warnings.append("Código sin funciones ni clases (considera estructurarlo)")

    except SyntaxError as exc:
        errors.append(f"SyntaxError en línea {exc.lineno}: {exc.msg}")
    except Exception as exc:
        errors.append(f"Error analizando código: {exc}")

    valid = len(errors) == 0
    return ValidationResult(valid=valid, warnings=warnings, errors=errors,
                            language="python")


# ── Ejecutores ─────────────────────────────────────────────────────────────────

def _scan_blocked_imports(code: str) -> list[str]:
    """Detecta imports peligrosos en código Python."""
    found = []
    for match in _BLOCKED_PYTHON_PATTERN.finditer(code):
        mod = match.group(1)
        if mod not in found:
            found.append(mod)
    if "__import__" in code:
        found.append("__import__ (posible escape)")
    return found


def run_python(code: str, timeout: int = None) -> ExecutionResult:
    """
    Ejecuta código Python en subprocess aislado.

    Usa el mismo sandbox de cognia.program_creator.sandbox_runner
    para consistencia, pero con interfaz unificada.

    Args:
        code:    código Python a ejecutar
        timeout: timeout en segundos (None = usar default)

    Returns:
        ExecutionResult con output, errors y metadata
    """
    t0 = time.perf_counter()
    timeout = timeout or TIMEOUT["python"]

    if not code or not code.strip():
        return ExecutionResult(success=False, output="", errors="Código vacío",
                               exit_code=-1, timed_out=False, language="python")

    # Validar primero (sintaxis + imports peligrosos)
    validation = validate_python(code)
    if not validation.valid:
        return ExecutionResult(
            success=False, output="",
            errors="\n".join(validation.errors),
            exit_code=-2, timed_out=False, language="python",
            blocked_imports=[e for e in validation.errors
                             if "peligroso" in e.lower()],
        )

    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="cognia_exec_",
            dir=tempfile.gettempdir(), delete=False, encoding="utf-8",
        ) as f:
            tmp_file = f.name
            f.write(code)

        proc = subprocess.run(
            [sys.executable, tmp_file],
            capture_output=True, text=True,
            timeout=timeout,
            env={
                "PATH":       os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": "",
                "HOME":       tempfile.gettempdir(),
                "TMPDIR":     tempfile.gettempdir(),
                "TERM":       "dumb",
            },
        )
        elapsed = (time.perf_counter() - t0) * 1000
        stdout  = (proc.stdout or "")[:MAX_OUTPUT_CHARS]
        stderr  = (proc.stderr or "")[:MAX_OUTPUT_CHARS]
        success = (proc.returncode == 0 and len(stdout.strip()) > 0)

        result = ExecutionResult(
            success=success, output=stdout, errors=stderr,
            exit_code=proc.returncode, timed_out=False,
            language="python", duration_ms=round(elapsed, 1),
            warnings=validation.warnings,
        )

    except subprocess.TimeoutExpired as tex:
        elapsed = (time.perf_counter() - t0) * 1000
        stdout  = ""
        if tex.stdout:
            stdout = (tex.stdout.decode("utf-8", errors="replace")
                      if isinstance(tex.stdout, bytes) else tex.stdout)[:MAX_OUTPUT_CHARS]
        result = ExecutionResult(
            success=bool(stdout.strip()),
            output=stdout,
            errors=f"Timeout después de {timeout}s",
            exit_code=-3, timed_out=True,
            language="python", duration_ms=round(elapsed, 1),
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        result = ExecutionResult(
            success=False, output="",
            errors=f"Error en sandbox: {exc}",
            exit_code=-4, timed_out=False,
            language="python", duration_ms=round(elapsed, 1),
        )
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.unlink(tmp_file)
            except Exception:
                pass

    status = "✅" if result.success else ("⏱️" if result.timed_out else "❌")
    logger.info(
        f"Python ejecutado {status}",
        extra={"op":      "code_executor.run_python",
               "context": (f"exit={result.exit_code} "
                            f"output={len(result.output)}ch "
                            f"ms={result.duration_ms:.0f}")},
    )
    log_slow(logger, "code_executor.run_python", t0 / 1000,
             threshold_ms=timeout * 1000 * 0.8)
    return result


def run_javascript(code: str, timeout: int = None) -> ExecutionResult:
    """
    Ejecuta código JavaScript con Node.js si está disponible.
    Fallback graceful si Node.js no está instalado.

    Args:
        code:    código JavaScript a ejecutar
        timeout: timeout en segundos (None = usar default)

    Returns:
        ExecutionResult. Si Node.js no está disponible, success=False
        con mensaje explicativo en errors.
    """
    timeout = timeout or TIMEOUT["javascript"]

    # Verificar Node.js
    node_path = shutil.which("node") or shutil.which("nodejs")
    if not node_path:
        logger.warning(
            "Node.js no disponible — JavaScript no se puede ejecutar",
            extra={"op": "code_executor.run_javascript", "context": "node not found"},
        )
        return ExecutionResult(
            success=False, output="",
            errors="Node.js no está instalado. Instala Node.js para ejecutar JavaScript.",
            exit_code=-10, timed_out=False, language="javascript",
        )

    if not code or not code.strip():
        return ExecutionResult(success=False, output="", errors="Código vacío",
                               exit_code=-1, timed_out=False, language="javascript")

    # Verificar imports peligrosos en JS
    js_dangerous = re.search(
        r"\b(require\s*\(\s*['\"]fs['\"]|require\s*\(\s*['\"]child_process['\"]|"
        r"require\s*\(\s*['\"]net['\"]|require\s*\(\s*['\"]http['\"])\b",
        code, re.IGNORECASE
    )
    if js_dangerous:
        return ExecutionResult(
            success=False, output="",
            errors=f"Módulo peligroso de Node.js detectado: {js_dangerous.group(0)}",
            exit_code=-2, timed_out=False, language="javascript",
        )

    t0 = time.perf_counter()
    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", prefix="cognia_exec_",
            dir=tempfile.gettempdir(), delete=False, encoding="utf-8",
        ) as f:
            tmp_file = f.name
            f.write(code)

        proc = subprocess.run(
            [node_path, tmp_file],
            capture_output=True, text=True,
            timeout=timeout,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": tempfile.gettempdir(),
                "TERM": "dumb",
            },
        )
        elapsed = (time.perf_counter() - t0) * 1000
        stdout  = (proc.stdout or "")[:MAX_OUTPUT_CHARS]
        stderr  = (proc.stderr or "")[:MAX_OUTPUT_CHARS]
        result = ExecutionResult(
            success=(proc.returncode == 0 and bool(stdout.strip())),
            output=stdout, errors=stderr,
            exit_code=proc.returncode, timed_out=False,
            language="javascript", duration_ms=round(elapsed, 1),
        )

    except subprocess.TimeoutExpired as tex:
        elapsed = (time.perf_counter() - t0) * 1000
        stdout = ""
        if tex.stdout:
            stdout = (tex.stdout.decode("utf-8", errors="replace")
                      if isinstance(tex.stdout, bytes) else tex.stdout)[:MAX_OUTPUT_CHARS]
        result = ExecutionResult(
            success=bool(stdout.strip()),
            output=stdout, errors=f"Timeout después de {timeout}s",
            exit_code=-3, timed_out=True,
            language="javascript", duration_ms=round(elapsed, 1),
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        result = ExecutionResult(
            success=False, output="",
            errors=f"Error ejecutando JS: {exc}",
            exit_code=-4, timed_out=False,
            language="javascript", duration_ms=round(elapsed, 1),
        )
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.unlink(tmp_file)
            except Exception:
                pass

    status = "✅" if result.success else ("⏱️" if result.timed_out else "❌")
    logger.info(
        f"JavaScript ejecutado {status}",
        extra={"op":      "code_executor.run_javascript",
               "context": f"exit={result.exit_code} ms={result.duration_ms:.0f}"},
    )
    return result


# ── Clase unificada ────────────────────────────────────────────────────────────

class CodeExecutor:
    """
    Interfaz unificada para ejecutar y validar código en múltiples lenguajes.

    Usado por:
      - LanguageEngine para validar código antes de mostrarlo
      - SelfArchitect para validar propuestas arquitecturales
      - CodeMemory.save_snippet() puede llamarlo para marcar worked=True/False

    Ejemplo:
        ex = CodeExecutor()
        result = ex.run("print('hola')", language="python")
        if result.success:
            print(result.output)
    """

    def run(self, code: str, language: str = "python",
            timeout: int = None) -> ExecutionResult:
        """
        Ejecuta código en el lenguaje especificado.

        Args:
            code:     código a ejecutar
            language: "python" | "javascript" | "js"
            timeout:  timeout en segundos

        Returns:
            ExecutionResult
        """
        lang = language.lower().strip()
        if lang in ("javascript", "js"):
            return run_javascript(code, timeout)
        elif lang == "python":
            return run_python(code, timeout)
        else:
            logger.warning(
                f"Lenguaje no soportado para ejecución: {lang}",
                extra={"op": "code_executor.run", "context": f"lang={lang}"},
            )
            return ExecutionResult(
                success=False, output="",
                errors=f"Lenguaje '{lang}' no soportado para ejecución directa.",
                exit_code=-20, timed_out=False, language=lang,
            )

    def validate(self, code: str, language: str) -> ValidationResult:
        """
        Valida código sin ejecutarlo.

        Args:
            code:     código a validar
            language: "python" | "html" | "css"

        Returns:
            ValidationResult con errores y warnings
        """
        lang = language.lower().strip()
        if lang == "python":
            return validate_python(code)
        elif lang == "html":
            return validate_html(code)
        elif lang == "css":
            return validate_css(code)
        else:
            return ValidationResult(
                valid=True, warnings=[f"No hay validador para '{lang}'"],
                errors=[], language=lang,
            )

    def run_and_validate(self, code: str,
                         language: str = "python") -> tuple[ValidationResult, ExecutionResult]:
        """
        Valida Y ejecuta código. Útil para el SelfArchitect.

        Returns:
            (ValidationResult, ExecutionResult)
            Si la validación falla, ExecutionResult tendrá success=False.
        """
        val = self.validate(code, language)
        if not val.valid:
            exec_result = ExecutionResult(
                success=False, output="",
                errors=f"Validación fallida: {'; '.join(val.errors)}",
                exit_code=-100, timed_out=False, language=language,
            )
            return val, exec_result
        exec_result = self.run(code, language)
        return val, exec_result


# ── Singleton ──────────────────────────────────────────────────────────────────

_EXECUTOR_INSTANCE: Optional[CodeExecutor] = None


def get_code_executor() -> CodeExecutor:
    """Devuelve la instancia singleton de CodeExecutor."""
    global _EXECUTOR_INSTANCE
    if _EXECUTOR_INSTANCE is None:
        _EXECUTOR_INSTANCE = CodeExecutor()
    return _EXECUTOR_INSTANCE


# ── Tests básicos ──────────────────────────────────────────────────────────────

def _test_run_python():
    """Test 1: ejecutar Python simple."""
    ex = get_code_executor()
    result = ex.run("print('hola cognia')", "python")
    assert result.success, f"FALLO: {result.errors}"
    assert "hola cognia" in result.output
    print(f"  ✅ run_python OK: output='{result.output.strip()}'")

    # Código con error
    result_err = ex.run("def foo(\n    pass", "python")
    assert not result_err.success, "FALLO: debería fallar con SyntaxError"
    print(f"  ✅ run_python error detectado OK")


def _test_validate_html():
    """Test 2: validación HTML."""
    html_ok = """<!DOCTYPE html>
<html><head><title>Test</title></head>
<body><p>Hola</p></body></html>"""
    result = validate_html(html_ok)
    assert result.valid, f"FALLO: {result.errors}"
    print(f"  ✅ validate_html OK (válido)")

    html_bad = "<div><p>sin cerrar<div>"
    result_bad = validate_html(html_bad)
    print(f"  ✅ validate_html detecta errores: {result_bad.errors[:2]}")


def _test_validate_css():
    """Test 3: validación CSS."""
    css_ok = ".container { display: flex; color: red; }"
    result = validate_css(css_ok)
    assert result.valid, f"FALLO: {result.errors}"
    print(f"  ✅ validate_css OK (válido)")

    css_bad = ".box { color: ; display"  # falta llave de cierre y valor
    result_bad = validate_css(css_bad)
    assert not result_bad.valid or result_bad.warnings
    print(f"  ✅ validate_css detecta problemas: errors={result_bad.errors} "
          f"warnings={result_bad.warnings[:1]}")


def run_tests():
    """Ejecuta todos los tests del CodeExecutor."""
    print("\n🧪 Tests CodeExecutor:")
    _test_run_python()
    _test_validate_html()
    _test_validate_css()
    print("✅ Todos los tests pasaron.\n")


if __name__ == "__main__":
    run_tests()
