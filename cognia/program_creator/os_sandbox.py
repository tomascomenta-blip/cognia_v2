"""
os_sandbox.py — Ejecucion de codigo generado con contencion a nivel de SISTEMA
OPERATIVO (Windows AppContainer). A diferencia de sandbox_runner.py, esto SI
contiene a codigo hostil, porque la frontera es el kernel de Windows y no un guard
in-process de Python que el codigo pueda desarmar.

POR QUE ESTO Y NO EL GUARD IN-PROCESS:
  Un equipo rojo (2026-07-19) rompio el guard in-process de sandbox_runner.py con
  11 escapes (gc.get_objects, `from nt import *`, importlib._gcd_import, restaurar
  builtins). La causa raiz es que Python es demasiado reflexivo para contenerse a
  si mismo. La respuesta correcta es sacar la frontera del proceso: un AppContainer
  corre con un SID de baja confianza al que el SO NIEGA, por ACL, escribir fuera de
  su workspace y, sin capabilities, abrir la red. Aunque el codigo Python haga lo
  que quiera adentro, el kernel lo contiene. Medido (planes/AUTOPROGRAMACION_COGNIA.md,
  spike G0-SO): WS_WRITE=OK, REPO_WRITE=BLOCKED, NET=BLOCKED.

COMO FUNCIONA:
  1. Un perfil de AppContainer persistente (CreateAppContainerProfile). Derivar el
     SID NO basta — hay que registrar el perfil o CreateProcess da error 2.
  2. El interprete Python necesita ACL de lectura+ejecucion para ALL APPLICATION
     PACKAGES (setup unico, sin admin — el usuario es dueño de los archivos).
  3. Por ejecucion: workspace temporal con ACL de control total para el SID del
     container; se lanza python con STARTUPINFOEX+SECURITY_CAPABILITIES (0
     capabilities = sin red); stdout/stderr y traceback se capturan en archivos
     del workspace; se limpia todo al terminar.

LIMITES HONESTOS:
  - Solo Windows. En otros SO hay que caer a otro backend (contenedor/WSL) o al
    guard best-effort. is_available() lo refleja.
  - AppContainer NO limita RAM/CPU por si solo. Eso lo cubre un Job Object
    (pendiente; hoy la unica defensa de recursos es el timeout de reloj).
  - Requiere que el interprete sea legible por el container (setup de ACL). Si el
    interprete vive en una ruta que no se puede compartir, este backend no aplica.
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import shutil
import time
from ctypes import wintypes

from cognia.program_creator.sandbox_runner import ExecutionResult, MAX_OUTPUT_CHARS

# ── Disponibilidad ──────────────────────────────────────────────────────────────

_IS_WINDOWS = sys.platform == "win32"

# SID de "ALL APPLICATION PACKAGES": todo AppContainer es miembro. Concederle
# lectura/ejecucion sobre el interprete es lo que permite que el container lo corra.
_ALL_APP_PACKAGES = "*S-1-15-2-1"

_APPCONTAINER_NAME = "cognia-code-sandbox"
_TIMEOUT_DEFAULT = 15

# HRESULT de ERROR_ALREADY_EXISTS: el perfil ya estaba creado (caso normal).
_HR_ALREADY_EXISTS = -2147024713

# Flags de CreateProcess / atributos de hilo.
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400

# Fragmentos que marcan una variable de entorno como sensible: no se le pasan al
# codigo generado. Cierra el Vector 3 del equipo rojo (herencia del entorno del
# lanzador): aunque no era un escape (sin canal para exfiltrar), no hay razon para
# que el codigo no confiable vea secretos que el proceso padre tenga cargados.
# PASS cubre PASSWORD/PASSWD/PASSPHRASE de una; PHRASE por si acaso. Verificado
# contra el .env real del repo: cubre HF_TOKEN, *_KEY, PYPI_TOKEN,
# COGNIA_ENCRYPT_PASSPHRASE, etc. La config no sensible (URLs, puertos, paths,
# modelos) se hereda sin problema.
_ENV_SENSIBLE = ("KEY", "TOKEN", "SECRET", "PASS", "PHRASE", "CREDENTIAL",
                 "APIKEY", "AUTH", "PRIVATE")


def _bloque_entorno_saneado():
    """
    Bloque de entorno para el hijo: el del padre MENOS las variables sensibles.
    Se filtra por sustraccion (no allowlist) para no romper lo que el interprete
    necesita (SYSTEMROOT, PATH, etc.) mientras se quitan *KEY/*TOKEN/*SECRET/...
    Devuelve un buffer UTF-16 con el formato "K=V\\0K=V\\0\\0" que espera CreateProcessW.
    """
    pares = []
    for k, v in os.environ.items():
        ku = k.upper()
        if any(frag in ku for frag in _ENV_SENSIBLE):
            continue
        pares.append(f"{k}={v}")
    blob = "\x00".join(pares) + "\x00\x00"
    return ctypes.create_unicode_buffer(blob)


def is_available() -> bool:
    """True si este backend de contencion dura puede usarse en esta maquina."""
    if not _IS_WINDOWS:
        return False
    try:
        ctypes.WinDLL("userenv")
        return True
    except OSError:
        return False


# ── Win32 structs ───────────────────────────────────────────────────────────────

if _IS_WINDOWS:
    _userenv = ctypes.WinDLL("userenv", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    _userenv.CreateAppContainerProfile.restype = ctypes.c_long
    _userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    _userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    _advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    class _STARTUPINFO(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                    ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                    ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                    ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                    ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
                    ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                    ("hStdError", wintypes.HANDLE)]

    class _STARTUPINFOEX(ctypes.Structure):
        _fields_ = [("StartupInfo", _STARTUPINFO), ("lpAttributeList", ctypes.c_void_p)]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    class _SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.c_void_p),
                    ("CapabilityCount", wintypes.DWORD), ("Reserved", wintypes.DWORD)]

    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.c_void_p, ctypes.c_void_p]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


# ── Setup (una vez) ─────────────────────────────────────────────────────────────

_sid_cache = None            # SID del AppContainer (c_void_p), cacheado
_str_sid_cache = None        # el SID como string, para icacls
_interpreter_acl_done = set()  # rutas de interprete ya con ACL en esta sesion


class OsSandboxError(RuntimeError):
    pass


def _ensure_profile():
    """Crea (o reutiliza) el perfil de AppContainer y cachea su SID. Idempotente."""
    global _sid_cache, _str_sid_cache
    if _sid_cache is not None:
        return _sid_cache, _str_sid_cache

    sid = ctypes.c_void_p()
    hr = _userenv.CreateAppContainerProfile(
        _APPCONTAINER_NAME, _APPCONTAINER_NAME, "Cognia code sandbox",
        None, 0, ctypes.byref(sid))
    if hr == _HR_ALREADY_EXISTS:
        if _userenv.DeriveAppContainerSidFromAppContainerName(
                _APPCONTAINER_NAME, ctypes.byref(sid)) != 0:
            raise OsSandboxError("no se pudo derivar el SID del AppContainer existente")
    elif hr != 0:
        raise OsSandboxError(f"CreateAppContainerProfile fallo: hr={hr & 0xffffffff:#010x}")

    sp = wintypes.LPWSTR()
    _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(sp))
    _sid_cache, _str_sid_cache = sid, sp.value
    return _sid_cache, _str_sid_cache


def _interpreter_root(pyexe: str) -> str:
    """El directorio del interprete que hay que hacer legible por el container."""
    return os.path.dirname(os.path.abspath(pyexe))


def ensure_interpreter_readable(pyexe: str) -> None:
    """
    Concede a ALL APPLICATION PACKAGES lectura+ejecucion sobre el arbol del
    interprete. Setup unico por interprete (idempotente en esta sesion). Sin admin:
    el usuario es dueño de sus archivos. RX no permite modificar nada.
    """
    root = _interpreter_root(pyexe)
    if root in _interpreter_acl_done:
        return
    r = subprocess.run(
        ["icacls", root, "/grant", f"{_ALL_APP_PACKAGES}:(OI)(CI)(RX)", "/T", "/Q", "/C"],
        capture_output=True, text=True)
    # /C continua ante errores puntuales (archivos bloqueados); basta con que la
    # mayoria quede legible. No abortamos por un archivo suelto.
    _interpreter_acl_done.add(root)


# ── Ejecucion ───────────────────────────────────────────────────────────────────

# Arranque que corre DENTRO del container: redirige stdout/stderr a archivos del
# workspace (el unico lugar escribible) y captura el traceback para el lazo de
# reparacion. runpy preserva los numeros de linea del programa del usuario.
_LAUNCHER = '''\
import sys, os, runpy, traceback
# -I limpia sys.path; reponemos el workspace para que los imports entre modulos
# propios de un proyecto multi-archivo resuelvan (paq/, modelo.py, etc.).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_out = open("__stdout__.txt", "w", encoding="utf-8")
_err = open("__stderr__.txt", "w", encoding="utf-8")
sys.stdout = _out
sys.stderr = _err
_code = 0
try:
    runpy.run_path("program.py", run_name="__main__")
except SystemExit as e:
    _code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
except BaseException:
    traceback.print_exc()
    _code = 1
finally:
    _out.flush(); _err.flush()
    _out.close(); _err.close()
sys.exit(_code)
'''


def _grant_workspace(str_sid: str, ws: str) -> None:
    subprocess.run(
        ["icacls", ws, "/grant", f"*{str_sid}:(OI)(CI)(F)", "/T", "/Q"],
        capture_output=True, text=True)


def _build_attr_list(sid):
    """Lista de atributos de hilo con el SID del AppContainer."""
    size = ctypes.c_size_t(0)
    _kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    buf = (ctypes.c_byte * size.value)()
    attr = ctypes.cast(buf, ctypes.c_void_p)
    if not _kernel32.InitializeProcThreadAttributeList(attr, 1, 0, ctypes.byref(size)):
        raise OsSandboxError(f"InitializeProcThreadAttributeList: {ctypes.get_last_error()}")
    sec_cap = _SECURITY_CAPABILITIES()
    sec_cap.AppContainerSid = sid
    sec_cap.Capabilities = None
    sec_cap.CapabilityCount = 0  # 0 capabilities => sin red, sin acceso a nada extra
    if not _kernel32.UpdateProcThreadAttribute(
            attr, 0, ctypes.c_void_p(_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES),
            ctypes.byref(sec_cap), ctypes.sizeof(sec_cap), None, None):
        raise OsSandboxError(f"UpdateProcThreadAttribute: {ctypes.get_last_error()}")
    # buf debe sobrevivir mientras se use attr: se devuelve para mantener la ref.
    return attr, buf, sec_cap


def run_in_appcontainer(code: str,
                        extra_files: dict = None,
                        timeout_sec: int = _TIMEOUT_DEFAULT,
                        pyexe: str = None) -> ExecutionResult:
    """
    Ejecuta `code` como program.py dentro de un AppContainer de Windows.

    `extra_files`: rutas relativas -> contenido, para proyectos multi-archivo.
    Devuelve el mismo ExecutionResult que run_in_sandbox, para ser intercambiables.
    """
    if not _IS_WINDOWS:
        raise OsSandboxError("AppContainer solo esta disponible en Windows")
    if not code or len(code.strip()) < 5:
        return ExecutionResult(success=False, execution_output="",
                               execution_errors="Empty code", exit_code=-1,
                               timed_out=False)

    # El interprete base es legible por el container; el del venv arrastra
    # site-packages con ACLs propias. Por defecto usamos el base.
    pyexe = pyexe or getattr(sys, "_base_executable", None) or sys.executable
    sid, str_sid = _ensure_profile()
    ensure_interpreter_readable(pyexe)

    ws = tempfile.mkdtemp(prefix="cognia_acbox_")
    try:
        # Archivos del proyecto (multi-archivo), sin poder escapar del workspace.
        for rel, contenido in (extra_files or {}).items():
            destino = os.path.realpath(os.path.join(ws, rel))
            if destino != os.path.realpath(ws) and not destino.startswith(os.path.realpath(ws) + os.sep):
                raise OsSandboxError(f"ruta fuera del workspace: {rel}")
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "w", encoding="utf-8") as f:
                f.write(contenido)
        with open(os.path.join(ws, "program.py"), "w", encoding="utf-8") as f:
            f.write(code)
        with open(os.path.join(ws, "__launcher__.py"), "w", encoding="utf-8") as f:
            f.write(_LAUNCHER)

        _grant_workspace(str_sid, ws)

        attr, _buf_keepalive, _sc_keepalive = _build_attr_list(sid)
        si = _STARTUPINFOEX()
        si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEX)
        si.lpAttributeList = attr
        pi = _PROCESS_INFORMATION()
        cmdline = ctypes.create_unicode_buffer(f'"{pyexe}" -I "__launcher__.py"')
        env = _bloque_entorno_saneado()

        ok = _kernel32.CreateProcessW(
            pyexe, cmdline, None, None, False,
            _EXTENDED_STARTUPINFO_PRESENT | _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT,
            env, ws, ctypes.byref(si.StartupInfo), ctypes.byref(pi))
        if not ok:
            err = ctypes.get_last_error()
            _kernel32.DeleteProcThreadAttributeList(attr)
            return ExecutionResult(
                success=False, execution_output="",
                execution_errors=f"[appcontainer] CreateProcess fallo: WinError {err}",
                exit_code=-4, timed_out=False, code_length=len(code))

        WAIT_TIMEOUT = 0x00000102
        waited = _kernel32.WaitForSingleObject(pi.hProcess, int(timeout_sec * 1000))
        timed_out = (waited == WAIT_TIMEOUT)
        if timed_out:
            _kernel32.TerminateProcess(pi.hProcess, 1)
            _kernel32.WaitForSingleObject(pi.hProcess, 2000)
            exit_code = -3
        else:
            code_dw = wintypes.DWORD()
            _kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code_dw))
            exit_code = int(code_dw.value)
            # DWORD -> int con signo para exit codes negativos (crashes).
            if exit_code >= 0x80000000:
                exit_code -= 0x100000000

        _kernel32.CloseHandle(pi.hProcess)
        _kernel32.CloseHandle(pi.hThread)
        _kernel32.DeleteProcThreadAttributeList(attr)

        stdout = _leer(os.path.join(ws, "__stdout__.txt"))
        stderr = _leer(os.path.join(ws, "__stderr__.txt"))
        if timed_out:
            stderr = (stderr + f"\n[appcontainer] Timeout after {timeout_sec}s").strip()

        success = (exit_code == 0 and not timed_out)
        return ExecutionResult(
            success=success,
            execution_output=stdout[:MAX_OUTPUT_CHARS],
            execution_errors=stderr[:MAX_OUTPUT_CHARS],
            exit_code=exit_code, timed_out=timed_out,
            blocked_imports=[], code_length=len(code))
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _leer(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""
