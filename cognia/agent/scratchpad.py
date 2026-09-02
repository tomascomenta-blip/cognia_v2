# -*- coding: utf-8 -*-
"""
cognia/agent/scratchpad.py
==========================
Carpeta TEMPORAL por tarea del agente: pruebas, tests de usar-y-tirar,
capturas, ficheros de depuracion. Se crea al arrancar la tarea y se BORRA al
terminarla (pedido del dueno, 2026-09-02: "archivos temporales que despues de
terminar la tarea se eliminan, pero antes ahi entrarian los tests").

POR QUE. Medido en las tareas largas: el modelo escribe debug3.js, prueba_x.py,
test_tmp.py al lado de los entregables y los deja ahi; el arnes los cuenta
como "espiral de depuracion" y la ENTREGA los lista como si fueran producto.
Con una carpeta propia, el modelo sabe DONDE probar y el dueno se queda solo
con lo pedido.

DONDE VIVE. Dentro del workspace del agente (`<workspace>/.cognia_scratch/<id>/`)
a proposito: el gate de escritura (dev_tools.resolve_write_path) confina toda
escritura al workspace, y una carpeta fuera obligaria a abrir un agujero en
ese gate. El nombre empieza por punto para que no ensucie `listar` ni git.

CONTRATO
    abrir(raiz=None) -> Path            crea la carpeta (idempotente por id)
    cerrar(ruta, conservar=None) -> bool borra (salvo conservar); True si borro
    activo() -> bool                     config 'scratchpad' / COGNIA_SCRATCHPAD
    conservar() -> bool                  config 'scratchpad_conservar' / env
    nota_para_el_modelo(ruta) -> str     la linea que va en el primer user
    es_del_scratch(ruta, scratch) -> bool

Nunca lanza hacia el bucle: cualquier fallo degrada con aviso y sin carpeta.
"""
from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path

NOMBRE_DIR = ".cognia_scratch"
ENV_ACTIVO = "COGNIA_SCRATCHPAD"
ENV_CONSERVAR = "COGNIA_SCRATCHPAD_CONSERVAR"

# Ultimo scratchpad abierto/cerrado en este proceso, para la puerta /scratchpad.
_ULTIMO: dict = {"ruta": "", "abierto": 0.0, "cerrado": 0.0, "borrado": None,
                 "ficheros": 0, "error": ""}


def _config() -> dict:
    """La config persistida del CLI si esta cargado; {} si no (renderer
    suelto, tests). Sin importar cli.py a proposito (15k lineas)."""
    try:
        import sys
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            return dict(_cli._load_config() or {})
    except Exception:
        pass
    return {}


def _on(valor, default: bool) -> bool:
    if valor is None:
        return default
    return str(valor).strip().lower() not in ("0", "off", "false", "no", "apagado")


def activo() -> bool:
    """Env manda; despues la config 'scratchpad'; default ON."""
    env = os.environ.get(ENV_ACTIVO)
    if env is not None and env.strip() != "":
        return _on(env, True)
    return _on(_config().get("scratchpad"), True)


def conservar() -> bool:
    """True = no se borra al terminar (para inspeccionar). Default OFF."""
    env = os.environ.get(ENV_CONSERVAR)
    if env is not None and env.strip() != "":
        return _on(env, False)
    return _on(_config().get("scratchpad_conservar"), False)


def raiz_workspace() -> Path:
    try:
        from cognia.agents.workers.dev_tools import AGENT_WORKSPACE_ROOT
        return Path(AGENT_WORKSPACE_ROOT).resolve()
    except Exception:
        return Path(os.getcwd()).resolve()


def abrir(raiz=None, id: str = "") -> Path:
    """Crea `<raiz>/.cognia_scratch/<id>/` y la devuelve. Lanza OSError si el
    disco no deja: el llamador (cli) decide seguir sin scratchpad."""
    base = Path(raiz).resolve() if raiz else raiz_workspace()
    ident = id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    ruta = base / NOMBRE_DIR / ident
    ruta.mkdir(parents=True, exist_ok=True)
    _ULTIMO.update({"ruta": str(ruta), "abierto": time.time(), "cerrado": 0.0,
                    "borrado": None, "ficheros": 0, "error": ""})
    return ruta


def _contar(ruta: Path) -> int:
    try:
        return sum(1 for p in ruta.rglob("*") if p.is_file())
    except Exception:
        return 0


def cerrar(ruta, conservar_=None) -> bool:
    """Borra el scratchpad (y la carpeta .cognia_scratch si quedo vacia).
    Devuelve True si borro. Con conservar (arg o config) no toca nada."""
    if not ruta:
        return False
    p = Path(str(ruta))
    keep = conservar() if conservar_ is None else bool(conservar_)
    _ULTIMO["cerrado"] = time.time()
    _ULTIMO["ficheros"] = _contar(p) if p.exists() else 0
    if keep:
        _ULTIMO["borrado"] = False
        return False
    # Solo se borra lo que este bajo un .cognia_scratch: una ruta cualquiera
    # (bug del llamador) no puede costar el workspace del dueno.
    if NOMBRE_DIR not in p.parts:
        _ULTIMO["error"] = "ruta fuera de %s: no se borra" % NOMBRE_DIR
        _ULTIMO["borrado"] = False
        return False
    try:
        if p.exists():
            shutil.rmtree(p, ignore_errors=False)
        padre = p.parent
        if padre.name == NOMBRE_DIR and padre.exists() and not any(padre.iterdir()):
            padre.rmdir()
        _ULTIMO["borrado"] = True
        return True
    except Exception as exc:
        # En Windows un proceso hijo (servidor lanzado desde el scratch) puede
        # tener un fichero abierto: se avisa, no se revienta el cierre.
        _ULTIMO["error"] = "%s: %s" % (type(exc).__name__, exc)
        _ULTIMO["borrado"] = False
        return False


def es_del_scratch(ruta, scratch) -> bool:
    """¿`ruta` cae dentro del scratchpad `scratch`? Para que la ENTREGA y el
    contador de ficheros sueltos no cuenten lo temporal como producto."""
    if not scratch or not ruta:
        return False
    try:
        r = Path(str(ruta)).resolve()
        s = Path(str(scratch)).resolve()
        return s == r or s in r.parents
    except Exception:
        return False


def nota_para_el_modelo(ruta) -> str:
    """La linea del primer user que le dice al modelo donde probar."""
    if not ruta:
        return ""
    try:
        rel = os.path.relpath(str(ruta), str(raiz_workspace()))
    except Exception:
        rel = str(ruta)
    rel = rel.replace("\\", "/")
    return ("SCRATCHPAD: %s/ — carpeta TEMPORAL para tests de usar-y-tirar, "
            "scripts de prueba, capturas y depuracion. Se BORRA al terminar la "
            "tarea. Los entregables van FUERA de ella (en el workspace). Escribe "
            "ahi los tests que verifiquen tu trabajo antes de responder."
            % rel)


def ultimo() -> dict:
    return dict(_ULTIMO)
