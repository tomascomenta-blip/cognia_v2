"""
cognia/console/permissions.py
=============================
Modos de permiso para acciones del agente/REPL (/modo-permiso).

Tres modos, persistidos en ~/.cognia/config.env via cognia.first_run
(clave COGNIA_PERMISSION_MODE, default 'automatico'):

    bypass     -> nunca pide confirmacion
    manual     -> siempre pide confirmacion
    automatico -> pide confirmacion SOLO si la accion es peligrosa

Tabla de decision del clasificador (modo automatico):

    action_kind      | pide confirmacion?
    -----------------+----------------------------------------------------------
    shell_exec       | solo si detail matchea un patron peligroso (rm/del/rd,
                     | format, mkfs, diskpart, shutdown/reboot, reg add/delete,
                     | regedit, registry, system32, C:\\Windows, /etc, /usr,
                     | Program Files) o menciona rutas absolutas fuera del
                     | proyecto (cwd), de ~/.cognia y del directorio temporal
    file_write       | solo si la ruta esta fuera del proyecto, de ~/.cognia
                     | y del directorio temporal, o matchea patron peligroso
    file_delete      | SIEMPRE (borrar es irreversible; regla del repo:
                     | detenerse ante borrar datos del usuario)
    network          | solo si detail matchea patron peligroso; las URLs no se
                     | analizan como rutas (evita falsos positivos con http://)
    config_change    | solo si detail matchea patron peligroso
    model_download   | solo si detail matchea patron peligroso o la ruta destino
                     | esta fuera de las zonas seguras
    (desconocido)    | SIEMPRE (conservador ante action_kind no clasificado)

Uso:
    from cognia.console.permissions import needs_confirmation
    if needs_confirmation("shell_exec", cmd):
        ...  # pedir OK al usuario antes de ejecutar
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from cognia import first_run

MODES = ("automatico", "manual", "bypass")
_CONFIG_KEY = "COGNIA_PERMISSION_MODE"
_DEFAULT_MODE = "automatico"

# Tipos de accion que el clasificador conoce; cualquier otro pide confirmacion.
KNOWN_KINDS = (
    "shell_exec", "file_write", "file_delete",
    "network", "config_change", "model_download",
)

# Los tipos donde ademas del patron se inspeccionan rutas absolutas en detail.
_KINDS_CON_RUTAS = ("shell_exec", "file_write", "model_download")

# Patrones peligrosos (case-insensitive). Los comandos destructivos (rm, del,
# rd, rmdir, format) van anclados a posicion de comando para no disparar con
# palabras castellanas ("del", "informal") en texto libre.
_DANGER_PATTERNS = [
    r"(?:^|[;&|(]\s*)rm\b",
    r"(?:^|[;&|(]\s*)del\b",
    r"(?:^|[;&|(]\s*)rd\b",
    r"(?:^|[;&|(]\s*)rmdir\b",
    r"(?:^|[;&|(]\s*)format\b",
    r"remove-item",
    r"\bmkfs\b",
    r"\bdiskpart\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\breg(\.exe)?\s+(add|delete)\b",
    r"\bregedit\b",
    # OJO: NO usar \bregistry\b generico — falso positivo con registry.json /
    # cognia.experts.registry (verificacion adversarial tanda-1). El registro de
    # Windows ya esta cubierto por 'reg add/delete' y 'regedit' arriba.
    r"\bsystem32\b",
    r"c:\\windows",
    r"/etc/",
    r"/usr/",
    r"program files",
]
_DANGER_RX = [re.compile(p, re.IGNORECASE) for p in _DANGER_PATTERNS]

# Rutas absolutas mencionadas en detail: estilo Windows (C:\... con lookbehind
# para no morder "http://") y estilo POSIX (/... precedido de inicio o espacio).
_WIN_PATH_RX = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"';|&]*")
_POSIX_PATH_RX = re.compile(r"(?:^|\s)(/[^\s\"';|&]*)")


def get_mode() -> str:
    """Modo vigente: os.environ primero (refleja la sesion), luego config.env."""
    value = os.environ.get(_CONFIG_KEY, "").strip().lower()
    if value in MODES:
        return value
    value = first_run._load_config().get(_CONFIG_KEY, "").strip().lower()
    if value in MODES:
        return value
    return _DEFAULT_MODE


def set_mode(name: str) -> str:
    """Cambia y persiste el modo. Lanza ValueError si el nombre no es valido."""
    name = (name or "").strip().lower()
    if name not in MODES:
        raise ValueError(f"Modo invalido: {name!r}. Validos: {', '.join(MODES)}")
    first_run.set_config_value(_CONFIG_KEY, name)
    return name


def needs_confirmation(action_kind: str, detail: str) -> bool:
    """True si la accion requiere confirmacion del usuario en el modo vigente.

    Ver la tabla de decision en el docstring del modulo.
    """
    mode = get_mode()
    if mode == "bypass":
        return False
    if mode == "manual":
        return True
    return _es_peligroso(action_kind, detail or "")


# ── Clasificador (modo automatico) ────────────────────────────────────────────

def _es_peligroso(action_kind: str, detail: str) -> bool:
    kind = (action_kind or "").strip().lower()
    if kind == "file_delete":
        return True          # borrar es irreversible: siempre confirmar
    if kind not in KNOWN_KINDS:
        return True          # tipo desconocido: conservador
    if _matchea_patron_peligroso(detail):
        return True
    if kind in _KINDS_CON_RUTAS and _rutas_fuera_de_zona(detail):
        return True
    return False


def _matchea_patron_peligroso(detail: str) -> bool:
    return any(rx.search(detail) for rx in _DANGER_RX)


def _rutas_fuera_de_zona(detail: str) -> bool:
    """True si detail menciona una ruta absoluta fuera de las zonas seguras.

    Zonas seguras: el proyecto (cwd), ~/.cognia y el directorio temporal.
    Las rutas relativas no cuentan (quedan dentro del proyecto).
    """
    candidates = _WIN_PATH_RX.findall(detail)
    candidates += [m.strip() for m in _POSIX_PATH_RX.findall(detail)]
    if not candidates:
        return False
    safe_roots = [
        Path.cwd().resolve(),
        (Path.home() / ".cognia").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    ]
    for cand in candidates:
        cand = cand.rstrip(".,)")
        if not cand:
            continue
        try:
            p = Path(cand).resolve()
        except (OSError, ValueError):
            return True      # ruta rara que ni resuelve: confirmar
        if not any(_es_subruta(p, root) for root in safe_roots):
            return True
    return False


def _es_subruta(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False
