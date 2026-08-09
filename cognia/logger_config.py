"""
logger_config.py — Cognia Logging System
==========================================
Sistema de logging estructurado para todos los módulos de Cognia.

Uso básico en cualquier módulo:
    from .logger_config import get_logger
    logger = get_logger(__name__)

    logger.info("Operación OK", extra={"op": "store_episode", "label": label})
    logger.warning("Fallo no crítico", extra={"op": "cache_search", "error": str(e)})
    logger.error("Fallo crítico", extra={"op": "db_write", "table": "episodic_memory"})

Uso del helper safe_execute:
    from .logger_config import safe_execute
    result = safe_execute(lambda: risky_function(), context="nombre_operacion", fallback=None)
"""

import logging
import logging.handlers
import os
import sys
import time
import traceback
import functools
from typing import Any, Callable, Optional, TypeVar

# ── Configuración global ───────────────────────────────────────────────
# POR QUE WARNING en consola (2026-08-09): el arranque del REPL mostraba ~12
# lineas INFO con formato de servidor (vector_cache, mesh_node, key_manager...)
# ANTES del banner, y mas INFO en medio de cada turno — ruido que tapaba la
# respuesta (evidencia baseline 2026-08-09). La consola es para el usuario:
# WARNING+ en formato corto humano. El detalle INFO/DEBUG va SIEMPRE al
# archivo (~/.cognia/logs/cognia.log), donde se diagnostica sin ensuciar el
# turno. COGNIA_LOG_LEVEL=INFO|DEBUG (o /debug en el REPL) sube la consola.
LOG_LEVEL      = os.environ.get("COGNIA_LOG_LEVEL", "WARNING").upper()
LOG_TO_FILE    = os.environ.get("COGNIA_LOG_FILE", "")        # path o vacío
LOG_MAX_BYTES  = 5 * 1024 * 1024   # 5 MB por archivo de log
LOG_BACKUP_COUNT = 3               # mantener 3 archivos históricos

# Archivo por defecto si COGNIA_LOG_FILE no lo pisa. Vive junto a la DB para
# que "todo lo de Cognia esta en ~/.cognia" siga siendo verdad.
_LOG_DIR_DEFAULT = os.path.join(os.path.expanduser("~"), ".cognia", "logs")

# ── Formato de log ─────────────────────────────────────────────────────
# Columnas fijas para facilitar grep y parseo en producción (ARCHIVO)
LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
    " | %(op)s | %(context)s"
)
# Consola: corto y humano. El asctime/op/context son para el archivo; en
# pantalla solo importa quien avisa y que dice.
LOG_FORMAT_CONSOLA = "%(levelname)s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── Campos extra por defecto ───────────────────────────────────────────
# Evita KeyError en el formatter cuando no se pasan extras
_DEFAULTS = {"op": "-", "context": "-"}


class _DefaultsFilter(logging.Filter):
    """Inyecta valores por defecto en campos extra para el formatter."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        for key, val in _DEFAULTS.items():
            if not hasattr(record, key):
                setattr(record, key, val)
        return True


# ── Colores para consola (ANSI) ───────────────────────────────────────
_COLORS = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # verde
    "WARNING":  "\033[33m",   # amarillo
    "ERROR":    "\033[31m",   # rojo
    "CRITICAL": "\033[35m",   # magenta
    "RESET":    "\033[0m",
}

_USE_COLOR = sys.stderr.isatty()


class _ColorFormatter(logging.Formatter):
    """Formatter con colores ANSI para salida de consola."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if _USE_COLOR:
            color = _COLORS.get(record.levelname, "")
            reset = _COLORS["RESET"]
            return f"{color}{msg}{reset}"
        return msg


# ── Construcción del logger raíz de Cognia ────────────────────────────
# El handler de consola vive en el modulo para que /debug pueda subirle el
# nivel en caliente sin reconstruir nada.
_CONSOLE_HANDLER: Optional[logging.Handler] = None


def _nivel(nombre: str, fallback: int) -> int:
    return getattr(logging, (nombre or "").upper(), fallback)


def _build_root_logger() -> logging.Logger:
    global _CONSOLE_HANDLER
    root = logging.getLogger("cognia")
    nivel_consola = _nivel(LOG_LEVEL, logging.WARNING)
    # El raiz deja pasar como minimo INFO (para el archivo) y baja a DEBUG
    # solo si la consola lo pide: formatear DEBUG de todos los modulos en
    # cada turno costaria mas que lo que informa.
    root.setLevel(min(nivel_consola, logging.INFO))

    if root.handlers:
        return root  # ya inicializado (p.ej. en tests o reload)

    # Handler de consola: WARNING+ por defecto, formato corto humano.
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(nivel_consola)
    console.setFormatter(_ColorFormatter(LOG_FORMAT_CONSOLA))
    console.addFilter(_DefaultsFilter())
    root.addHandler(console)
    _CONSOLE_HANDLER = console

    # Handler de archivo: SIEMPRE activo (antes era opt-in via COGNIA_LOG_FILE
    # y en la practica nadie lo activaba: el INFO iba a la pantalla o a ningun
    # lado). COGNIA_LOG_FILE pisa la ruta por defecto.
    ruta_log = LOG_TO_FILE
    try:
        if not ruta_log:
            os.makedirs(_LOG_DIR_DEFAULT, exist_ok=True)
            ruta_log = os.path.join(_LOG_DIR_DEFAULT, "cognia.log")
        file_handler = logging.handlers.RotatingFileHandler(
            ruta_log,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # archivo guarda todo lo que llegue
        file_handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        )
        file_handler.addFilter(_DefaultsFilter())
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning(
            "No se pudo abrir el archivo de log",
            extra={"op": "logger_init", "context": f"path={ruta_log} err={exc}"},
        )

    root.propagate = False
    return root


_ROOT_LOGGER = _build_root_logger()


def poner_nivel_consola(nivel: str) -> None:
    """Sube/baja el nivel de la CONSOLA en caliente (lo usa /debug del REPL).
    El archivo no se toca: siempre recibe el detalle."""
    n = _nivel(nivel, logging.WARNING)
    if _CONSOLE_HANDLER is not None:
        _CONSOLE_HANDLER.setLevel(n)
    # el raiz debe dejar pasar lo que la consola quiere ver
    _ROOT_LOGGER.setLevel(min(n, logging.INFO))


def get_logger(module_name: str) -> logging.Logger:
    """
    Obtiene un logger hijo del namespace 'cognia'.

    Uso:
        logger = get_logger(__name__)
        # → logger 'cognia.mi_modulo'

    Si __name__ ya empieza con 'cognia.' lo respeta; si no, lo prefija.
    """
    if not module_name.startswith("cognia"):
        module_name = f"cognia.{module_name}"
    return logging.getLogger(module_name)


# ── Helper safe_execute ───────────────────────────────────────────────
T = TypeVar("T")


def safe_execute(
    func: Callable[[], T],
    context: str,
    fallback: T = None,
    logger: Optional[logging.Logger] = None,
    level: str = "warning",
    reraise: bool = False,
) -> T:
    """
    Ejecuta func() de forma segura, logueando cualquier excepción.

    Parámetros:
        func      — callable sin argumentos (usar lambda si necesitas args)
        context   — descripción de la operación para el log (ej: "db_write:episodic")
        fallback  — valor a retornar si falla (default: None)
        logger    — logger a usar (si None, usa el logger raíz de cognia)
        level     — "warning" | "error" | "critical"
        reraise   — si True, relanza la excepción después de logearla

    Ejemplos:
        # Acceso a DB con fallback a lista vacía
        rows = safe_execute(
            lambda: conn.execute("SELECT ...").fetchall(),
            context="db_query:episodic_memory",
            fallback=[],
        )

        # Operación crítica que debe relanzar
        result = safe_execute(
            lambda: init_db(path),
            context="db_init",
            reraise=True,
        )
    """
    _logger = logger or _ROOT_LOGGER
    log_fn = getattr(_logger, level, _logger.warning)

    try:
        return func()
    except Exception as exc:
        tb_line = traceback.format_exc().strip().splitlines()[-1]
        log_fn(
            f"Excepción en [{context}]: {type(exc).__name__}: {exc}",
            extra={"op": context, "context": tb_line},
        )
        if reraise:
            raise
        return fallback


# ── Decorador @log_errors ─────────────────────────────────────────────
def log_errors(
    context: str = "",
    fallback: Any = None,
    level: str = "warning",
    reraise: bool = False,
):
    """
    Decorador equivalente a safe_execute para métodos completos.

    Uso:
        @log_errors(context="cache.search", fallback=None)
        def _search_ram(self, vector):
            ...
    """
    def decorator(func: Callable) -> Callable:
        op = context or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _logger = _ROOT_LOGGER
            # Intentar usar self.logger si existe
            if args and hasattr(args[0], "logger"):
                _logger = args[0].logger
            log_fn = getattr(_logger, level, _logger.warning)
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                tb_line = traceback.format_exc().strip().splitlines()[-1]
                log_fn(
                    f"Excepción en [{op}]: {type(exc).__name__}: {exc}",
                    extra={"op": op, "context": tb_line},
                )
                if reraise:
                    raise
                return fallback

        return wrapper
    return decorator


# ── Utilidades de diagnóstico ─────────────────────────────────────────
def log_slow(logger: logging.Logger, op: str, t0: float, threshold_ms: float = 200.0):
    """
    Loguea una advertencia si la operación superó el umbral de latencia.

    Uso:
        t0 = time.perf_counter()
        result = do_heavy_work()
        log_slow(logger, "embed:text_to_vector", t0, threshold_ms=150)
    """
    elapsed = (time.perf_counter() - t0) * 1000
    if elapsed > threshold_ms:
        logger.warning(
            f"Operación lenta: {elapsed:.1f}ms (umbral {threshold_ms}ms)",
            extra={"op": op, "context": f"latency_ms={elapsed:.1f}"},
        )


def log_db_error(logger: logging.Logger, op: str, exc: Exception, extra_ctx: str = ""):
    """
    Especializado para errores de SQLite. Incluye clase de error y contexto.
    """
    import sqlite3
    level = "error" if isinstance(exc, sqlite3.OperationalError) else "warning"
    log_fn = getattr(logger, level, logger.warning)
    log_fn(
        f"Error de base de datos en [{op}]: {type(exc).__name__}: {exc}",
        extra={"op": op, "context": extra_ctx or "-"},
    )
