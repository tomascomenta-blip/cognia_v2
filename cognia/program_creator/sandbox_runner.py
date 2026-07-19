"""
sandbox_runner.py — Ejecucion de programas generados por Cognia.

################################################################################
# ADVERTENCIA DE SEGURIDAD — LEER ANTES DE CONFIAR EN ESTO
#
# ESTO NO CONTIENE A UN ADVERSARIO. Un equipo rojo (2026-07-19, plan
# planes/AUTOPROGRAMACION_COGNIA.md, gate G0) reprodujo 11 escapes ejecutando de
# verdad: lanzo cmd.exe, abrio sockets, escribio en la raiz del repo y DESARMO
# el guard entero en 2 lineas. La causa raiz no son 11 bugs sueltos: es que un
# guard IN-PROCESS de Python no puede contener codigo Python. El lenguaje es
# demasiado reflexivo — gc.get_objects() alcanza cualquier funcion built-in, en
# Windows `os` re-exporta de `nt` (intocado), importlib._gcd_import esquiva
# __import__, y las closures devuelven los originales. Tapas 11 agujeros y
# aparece el 12. Por eso PyPy abandono su sandbox in-process.
#
# QUE ES ESTO ENTONCES: contencion BEST-EFFORT contra un LLM que se EQUIVOCA, no
# contra un atacante. Sube el liston contra el accidente tipico (un open() con
# ruta relativa mal calculada, un shutil.rmtree equivocado, un import peligroso
# por descuido), y desbloquea la stdlib benigna que un programa complejo
# necesita. NADA de su seguridad debe darse por dura.
#
# PARA AUTO-MODIFICACION (Cognia editando su repo) ESTO NO ALCANZA. Ese flujo
# exige contencion a nivel de SO (WSL/Docker/AppContainer). Ver el plan G0-WSL.
# Fugas conocidas sin cerrar (todas reproducidas):
#   - importlib.import_module usa _gcd_import y esquiva el guard de __import__
#   - frame.f_globals['__file__'] es falsificable via exec -> el gate por origen
#     del workspace se puede enganar
#   - `import _cognia_guard` expone _real_import / _real_open (los originales)
#   - os.open/os.write/os.fdopen y io.open/pathlib escriben fuera del workspace
#   - en Windows `from nt import *` y gc.get_objects() alcanzan os.system real
################################################################################

Capas presentes (best-effort, en orden de valor real):

  1. WORKSPACE AISLADO. El programa corre con cwd en un directorio temporal
     propio y descartable, no en la raiz del repo. Contiene el accidente comun de
     escribir con una ruta relativa; NO contiene a quien escribe por fd crudo.
  2. NEUTRALIZACION EN RUNTIME de os.system/popen/exec/spawn. Ataja la
     indireccion trivial (getattr(os,'sys'+'tem')); NO ataja `nt`/gc.
  3. SCAN AST. Defensa en profundidad para lo obvio. Evadible a proposito.

REGLA DEL GUARD DE IMPORTS (la parte que SI es correcta y valiosa): la politica
se aplica solo a imports que nacen de un archivo del workspace. Antes se
sobreescribia `builtins.__import__` de forma global y la denylist atrapaba los
imports INTERNOS de la stdlib, volviendo inimportables `pathlib` (-> urllib.parse),
`dataclasses` y `unittest` (-> importlib.machinery) y `tempfile` (-> shutil).
Ninguno estuvo nunca en BLOCKED_MODULES: morian por su cadena transitiva. Son los
cuatro pilares de un programa complejo —modelar estado, tocar archivos, escribir
tests, tener workspace— y estaban prohibidos por accidente. El chequeo "el frame
llamador vive en el workspace?" arregla ese accidente y soporta multi-archivo.
(Ese mismo gate por origen es falsificable por un adversario; ver la advertencia.)

El guard se inyecta como MODULO APARTE (_cognia_guard.py), no como prefijo del
archivo, para que los numeros de linea de los tracebacks apunten al codigo real.
El lazo de reparacion (G1) depende de eso.
"""

import ast
import os
import shutil as _shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

EXECUTION_TIMEOUT_SEC = 15
MAX_OUTPUT_CHARS      = 4000

# Modulos que el codigo DEL USUARIO no puede importar (best-effort — ver la
# advertencia de seguridad de la cabecera; esta denylist es evadible). Los imports
# internos de la stdlib no pasan por esta lista gracias al gate por origen del
# guard. 'builtins' queda fuera a proposito: bloquearlo hacia cascada-fallar casi
# todo modulo puro de la stdlib, que dispara `import builtins` al cargar.
BLOCKED_MODULES: frozenset = frozenset({
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

# Ejecutar procesos o cambiar privilegios: no hay caso de uso legitimo para un
# programa generado. Se neutralizan en runtime, que es lo que atrapa la
# indireccion.
BLOCKED_OS_EXEC: frozenset = frozenset({
    "chmod", "chown", "execl", "execle", "execlp", "execv", "execve", "execvp",
    "execvpe", "fork", "forkpty", "kill", "killpg", "popen", "posix_spawn",
    "posix_spawnp", "spawnl", "spawnle", "spawnlp", "spawnv", "spawnve",
    "spawnvp", "startfile", "system",
})

# Tocar el sistema de archivos SI es legitimo — un programa con estado necesita
# crear su directorio de datos y limpiar sus temporales. No se prohiben: se
# CONFINAN al workspace. Prohibirlos era parte de por que nada complejo pasaba.
CONFINED_OS_FS: frozenset = frozenset({
    "makedirs", "mkdir", "remove", "removedirs", "rename", "renames",
    "replace", "rmdir", "truncate", "unlink",
})

# Compatibilidad: habia un unico BLOCKED_OS_ATTRS y algo externo podria importarlo.
BLOCKED_OS_ATTRS: frozenset = BLOCKED_OS_EXEC | CONFINED_OS_FS

_GUARD_MODULE_NAME = "_cognia_guard"
_USER_PROGRAM_NAME = "program.py"

# Guard que corre ANTES del codigo del usuario, en su propio modulo.
_GUARD_SOURCE = '''\
"""Guard del sandbox de Cognia. Se importa antes del programa del usuario."""
import builtins as _b
import os as _o
import sys as _s

_WS = _o.path.realpath(_o.path.dirname(_o.path.abspath(__file__)))
_BM = frozenset(__BLOCKED_MODULES__)
_EXEC_ATTRS = frozenset(__BLOCKED_OS_EXEC__)
_FS_ATTRS = frozenset(__CONFINED_OS_FS__)

_real_import = _b.__import__
_real_open = _b.open


def _en_workspace(ruta):
    """True si `ruta` cae dentro del workspace. Resuelve symlinks y '..'."""
    try:
        if isinstance(ruta, int):        # descriptor ya abierto
            return True
        real = _o.path.realpath(_o.path.abspath(_o.fspath(ruta)))
    except Exception:
        return False
    return real == _WS or real.startswith(_WS + _o.sep)


def _nace_en_workspace(profundidad):
    """
    True si el frame llamador vive en el workspace.

    Es el corazon del arreglo: la politica aplica al codigo del usuario, no a los
    imports internos que hace la stdlib mientras carga. Sin `__file__` (exec,
    eval, -c) se asume workspace, que es la respuesta conservadora.
    """
    try:
        frame = _s._getframe(profundidad)
    except Exception:
        return True
    try:
        origen = frame.f_globals.get("__file__") or ""
    finally:
        del frame
    if not origen:
        return True
    try:
        return _en_workspace(origen)
    except Exception:
        return True


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] in _BM and _nace_en_workspace(2):
        raise ImportError("[sandbox] blocked: " + name)
    return _real_import(name, globals, locals, fromlist, level)


def _guarded_open(file, mode="r", *args, **kwargs):
    # Leer se permite; escribir queda confinado al workspace.
    if any(c in mode for c in "wax+") and not _en_workspace(file):
        raise PermissionError(
            "[sandbox] escritura fuera del workspace: %s" % (file,))
    return _real_open(file, mode, *args, **kwargs)


def _hacer_denegado(nombre):
    def _denegado(*args, **kwargs):
        raise PermissionError("[sandbox] os.%s deshabilitado" % nombre)
    _denegado.__name__ = nombre
    return _denegado


def _hacer_confinado(nombre, real):
    def _confinado(path, *args, **kwargs):
        if not _en_workspace(path):
            raise PermissionError(
                "[sandbox] os.%s fuera del workspace: %s" % (nombre, path))
        return real(path, *args, **kwargs)
    _confinado.__name__ = nombre
    return _confinado


for _attr in _EXEC_ATTRS:
    if hasattr(_o, _attr):
        try:
            setattr(_o, _attr, _hacer_denegado(_attr))
        except Exception:
            pass

for _attr in _FS_ATTRS:
    _real_fn = getattr(_o, _attr, None)
    if _real_fn is not None:
        try:
            setattr(_o, _attr, _hacer_confinado(_attr, _real_fn))
        except Exception:
            pass

_b.__import__ = _guarded_import
_b.open = _guarded_open

del _attr, _real_fn
'''


@dataclass
class ExecutionResult:
    success:          bool
    execution_output: str
    execution_errors: str
    exit_code:        int
    timed_out:        bool
    blocked_imports:  list = field(default_factory=list)
    code_length:      int  = 0


# ── AST analysis (defensa en profundidad, no frontera) ─────────────────────────

class _SandboxVisitor(ast.NodeVisitor):
    """
    Recorre el AST juntando violaciones evidentes.

    Solo marca lo que NO tiene uso legitimo (ejecutar procesos, importar modulos
    prohibidos). Las operaciones de archivos NO se marcan: quedan confinadas en
    runtime, que es donde el confinamiento se puede sostener de verdad.
    """

    def __init__(self) -> None:
        self.violations: List[str] = []

    def _flag(self, msg: str, lineno: int) -> None:
        self.violations.append(f"line {lineno}: {msg}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] in BLOCKED_MODULES:
                self._flag(f"import {alias.name}", node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.module.split(".")[0] in BLOCKED_MODULES:
            self._flag(f"from {node.module} import ...", node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            if node.args and isinstance(node.args[0], ast.Constant):
                if str(node.args[0].value).split(".")[0] in BLOCKED_MODULES:
                    self._flag(f"__import__('{node.args[0].value}')", node.lineno)
            else:
                self._flag("dynamic __import__ call", node.lineno)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
            if node.args and isinstance(node.args[0], ast.Constant):
                if str(node.args[0].value).split(".")[0] in BLOCKED_MODULES:
                    self._flag(f"import_module('{node.args[0].value}')", node.lineno)
            else:
                self._flag("dynamic import_module call", node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == "os":
            if node.attr in BLOCKED_OS_EXEC:
                self._flag(f"os.{node.attr}", node.lineno)
        self.generic_visit(node)


def _ast_scan(code: str) -> Tuple[List[str], str]:
    """Devuelve (violaciones, error_de_parseo). error_de_parseo es "" si compilo."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [], f"SyntaxError: {e}"
    visitor = _SandboxVisitor()
    visitor.visit(tree)
    return visitor.violations, ""


# ── Ejecucion en subproceso ────────────────────────────────────────────────────

def _armar_workspace(directorio: str, code: str,
                     extra_files: Optional[Dict[str, str]]) -> str:
    """
    Escribe el guard, el programa y los archivos extra en el workspace.
    Devuelve la ruta del programa principal.
    """
    # replace y no format: el guard es codigo Python lleno de llaves y format las
    # interpretaria como placeholders.
    guard = (_GUARD_SOURCE
             .replace("__BLOCKED_MODULES__", repr(sorted(BLOCKED_MODULES)))
             .replace("__BLOCKED_OS_EXEC__", repr(sorted(BLOCKED_OS_EXEC)))
             .replace("__CONFINED_OS_FS__", repr(sorted(CONFINED_OS_FS))))
    with open(os.path.join(directorio, _GUARD_MODULE_NAME + ".py"),
              "w", encoding="utf-8") as f:
        f.write(guard)

    # extra_files habilita proyectos multi-archivo (G3). Las rutas se resuelven
    # contra el workspace y no pueden escapar de el.
    for rel, contenido in (extra_files or {}).items():
        destino = os.path.realpath(os.path.join(directorio, rel))
        raiz = os.path.realpath(directorio)
        if destino != raiz and not destino.startswith(raiz + os.sep):
            raise ValueError(f"ruta fuera del workspace: {rel}")
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "w", encoding="utf-8") as f:
            f.write(contenido)

    principal = os.path.join(directorio, _USER_PROGRAM_NAME)
    with open(principal, "w", encoding="utf-8") as f:
        f.write(code)
    return principal


def run_in_sandbox(code: str,
                   extra_files: Optional[Dict[str, str]] = None,
                   timeout_sec: int = EXECUTION_TIMEOUT_SEC) -> ExecutionResult:
    """
    Ejecuta codigo Python en un workspace temporal aislado.

    `extra_files` mapea ruta relativa -> contenido, para proyectos de varios
    modulos que se importan entre si. El programa principal siempre es program.py.
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

    workspace = None
    try:
        workspace = tempfile.mkdtemp(prefix="cognia_ws_")
        principal = _armar_workspace(workspace, code, extra_files)

        # El guard se importa primero y despues se corre el programa con
        # run_path, para que __file__ y los numeros de linea del traceback sean
        # los del codigo del usuario y no queden corridos por un prefijo.
        arranque = (
            f"import {_GUARD_MODULE_NAME}, runpy; "
            f"runpy.run_path({principal!r}, run_name='__main__')"
        )

        try:
            proc = subprocess.run(
                # -s (sin site-packages del usuario) pero NO -I: el modo aislado
                # descarta PYTHONPATH y el cwd, y entonces el guard no se puede
                # importar. Nada del guard depende de site-packages.
                [sys.executable, "-s", "-c", arranque],
                capture_output=True, text=True,
                timeout=timeout_sec,
                cwd=workspace,
                env={
                    "PATH":             os.environ.get("PATH", ""),
                    "PYTHONPATH":       workspace,
                    "PYTHONIOENCODING": "utf-8",
                    "HOME":             workspace,
                    "USERPROFILE":      workspace,
                    "TMPDIR":           workspace,
                    "TEMP":             workspace,
                    "TMP":              workspace,
                    "TERM":             "dumb",
                    "SYSTEMROOT":       os.environ.get("SYSTEMROOT", ""),
                },
                stdin=subprocess.DEVNULL,
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
            stderr    = f"[sandbox] Timeout after {timeout_sec}s"

    except Exception as exc:
        return ExecutionResult(success=False, execution_output="",
                               execution_errors=f"Sandbox error: {exc}",
                               exit_code=-4, timed_out=False,
                               code_length=len(code))
    finally:
        if workspace and os.path.isdir(workspace):
            _shutil.rmtree(workspace, ignore_errors=True)

    stdout = stdout[:MAX_OUTPUT_CHARS]
    stderr = stderr[:MAX_OUTPUT_CHARS]

    # Un timeout es un fallo. Antes se marcaba exito si habia >10 chars de
    # stdout, con lo que un programa que imprime un menu y se cuelga en input()
    # contaba como exito — y de ahi salieron los EOFError de la biblioteca.
    success = exit_code == 0 and not timed_out

    return ExecutionResult(
        success=success, execution_output=stdout, execution_errors=stderr,
        exit_code=exit_code, timed_out=timed_out,
        blocked_imports=violations, code_length=len(code),
    )
