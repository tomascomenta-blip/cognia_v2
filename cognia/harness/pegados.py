# -*- coding: utf-8 -*-
"""
cognia/harness/pegados.py -- Pastes largos COLAPSADOS en el input (2026-08-23)
==============================================================================
POR QUE EXISTE: pegar 200 lineas de log en el prompt del REPL hoy vuelca las
200 lineas al buffer visible: el prompt se vuelve una pared, la linea que el
usuario estaba escribiendo desaparece de vista y editar alrededor del paste es
imposible. Claude Code y Codex CLI colapsan el paste a una marca corta
('[Pasted text #1 +212 lines]') y lo expanden recien AL ENVIAR. Aca se replica
ese contrato con el mecanismo nativo de prompt_toolkit: el binding de
Keys.BracketedPaste recibe el paste ENTERO en un solo KeyPress
(vt100_parser.py:199-218; en Windows sin VT hay heuristica win32: un batch con
>= 1 newline cuenta como paste), asi que colapsar es decision de UN punto.

CONTRATO:
 - `registrar(texto)` guarda el paste en el registro DE SESION y devuelve la
   marca '[pegado #N: +X lineas]' que se inserta en el buffer en su lugar.
 - `expandir(linea)` sustituye cada marca por su contenido: se llama UNA vez
   al enviar el prompt, ANTES de mejora/menciones/dispatch — rio abajo nadie
   sabe que existio el colapso. Una marca desconocida queda LITERAL (nunca se
   inventa contenido) y el contenido sustituido NO se re-escanea (un paste que
   contenia una marca vieja no se expande en cascada).
 - `listar()`/`obtener(n)` alimentan el comando /pegado (inspeccion).
 - REGLA DURA: el texto del dueno JAMAS se pierde. Cualquier fallo registrando
   hace que el integrador inserte el paste literal (y avise degradado); este
   modulo por su parte no lanza en `expandir` (una marca rota queda tal cual).

CONFIG (leida a call-time, mismo patron que ux/renderer._config_colapso):
 - env COGNIA_PEGADO=0 apaga el colapso GANANDO a la config ('1' lo fuerza);
   sin la env decide la clave 'pegado' de la config del CLI (default on).
 - umbrales: claves 'pegado_lineas' (default 5) y 'pegado_chars' (default
   800); las envs COGNIA_PEGADO_LINEAS / COGNIA_PEGADO_CHARS ganan.
   NO se copia config al env: /config-resuelta no debe mentir el origen.

PUNTO DE EXTENSION: _RX_MARCA + registrar/expandir son la unica pareja que
define el formato de la marca; un formato nuevo (p. ej. '[imagen #N]') se
agrega con otra pareja registrar_*/RX sin tocar el REPL.
"""
from __future__ import annotations

import os
import re
import sys
import time

# Umbrales por defecto: 5 lineas u 800 chars (los de Claude Code estan en ese
# orden de magnitud; menos de 5 lineas se lee de un vistazo y no molesta).
UMBRAL_LINEAS = 5
UMBRAL_CHARS = 800

# La marca visible. El regex es la DEFINICION: registrar() debe producir algo
# que este regex case, y hay un test que lo verifica en las dos direcciones.
_RX_MARCA = re.compile(r"\[pegado #(\d+): \+\d+ lineas\]")

# Registro DE SESION: se limpia al arrancar el REPL (limpiar()), vive lo que
# el proceso. Lista de dicts {'n', 'texto', 'lineas', 'chars', 'ts'}.
_PEGADOS: list = []


def normalizar(data: str) -> str:
    """\\r\\n y \\r sueltos -> \\n. Lo mismo que hace el binding por defecto de
    prompt_toolkit (basic.py): un CR crudo en el buffer rompe el conteo de
    lineas y el render del prompt."""
    return (data or "").replace("\r\n", "\n").replace("\r", "\n")


def _cfg_cli() -> dict:
    """La config persistida del CLI SI ya esta cargado; {} si no. No se importa
    cli.py: un modulo suelto (tests) no paga el monolito por dos umbrales."""
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            return _cli._load_config()
    except Exception:
        pass
    return {}


def _entero_env(var: str, cfg_clave: str, defecto: int, cfg: dict | None) -> int:
    v = (os.environ.get(var) or "").strip()
    if v:
        try:
            return max(1, int(v))
        except ValueError:
            pass
    base = cfg if cfg is not None else _cfg_cli()
    try:
        return max(1, int(base.get(cfg_clave, defecto)))
    except (TypeError, ValueError):
        return defecto


def umbral_lineas(cfg: dict | None = None) -> int:
    return _entero_env("COGNIA_PEGADO_LINEAS", "pegado_lineas",
                       UMBRAL_LINEAS, cfg)


def umbral_chars(cfg: dict | None = None) -> int:
    return _entero_env("COGNIA_PEGADO_CHARS", "pegado_chars",
                       UMBRAL_CHARS, cfg)


def activo(cfg: dict | None = None) -> bool:
    """Si el colapso esta encendido. La env COGNIA_PEGADO gana a la config
    (apagado de emergencia); default ON."""
    v = (os.environ.get("COGNIA_PEGADO") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "si", "on"):
        return True
    base = cfg if cfg is not None else _cfg_cli()
    return str(base.get("pegado", "on")).strip().lower() not in (
        "off", "0", "false", "no")


def es_largo(texto: str, cfg: dict | None = None) -> bool:
    """Si ESTE paste amerita colapso: >= umbral de lineas O > umbral de chars.
    El conteo es de lineas TOTALES ('a\\nb' son 2), no de saltos."""
    t = texto or ""
    lineas = t.count("\n") + 1 if t else 0
    return lineas >= umbral_lineas(cfg) or len(t) > umbral_chars(cfg)


def registrar(texto: str) -> str:
    """Guarda el paste y devuelve la marca a insertar en el buffer."""
    t = texto or ""
    n = len(_PEGADOS) + 1
    lineas = t.count("\n") + 1 if t else 0
    _PEGADOS.append({"n": n, "texto": t, "lineas": lineas,
                     "chars": len(t), "ts": time.time()})
    return f"[pegado #{n}: +{lineas} lineas]"


def expandir(linea: str) -> str:
    """Sustituye cada marca por su contenido guardado. Una sola pasada (lo
    sustituido no se re-escanea) y una marca sin registro queda LITERAL:
    inventar vacio seria perder texto sin decirlo."""
    if not linea or "[pegado #" not in linea:
        return linea

    def _reemplazo(m):
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            return m.group(0)
        e = obtener(n)
        return e["texto"] if e is not None else m.group(0)

    return _RX_MARCA.sub(_reemplazo, linea)


def obtener(n) -> dict | None:
    """El pegado numero `n` (1-based), o None."""
    try:
        i = int(n)
    except (TypeError, ValueError):
        return None
    if 1 <= i <= len(_PEGADOS):
        return _PEGADOS[i - 1]
    return None


def listar() -> list:
    """Copia superficial del registro, para /pegado lista."""
    return [dict(e) for e in _PEGADOS]


def limpiar() -> None:
    """Vacia el registro. Se llama al arrancar el REPL para que un repl()
    llamado dos veces no herede pegados viejos (mismo criterio que
    _COLA_ENTRADA.clear())."""
    _PEGADOS.clear()
