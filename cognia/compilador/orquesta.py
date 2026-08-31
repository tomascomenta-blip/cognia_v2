"""
cognia/compilador/orquesta.py
=============================
EL COMPILADOR: de una frase a un comando del CLI que funciona, o a nada.

    /compilar "quiero una herramienta que me diga cuanto ocupa cada carpeta"
        -> especificacion  (que comando, que subcomandos, que criterios)
        -> generacion      (el handler, el modulo de apoyo, los tests)
        -> injerto         (los 5 sitios del CLI, transaccional)
        -> evaluacion      (sintaxis, guardianes, tests, invocacion REAL,
                            y las postcondiciones del duenio)
        -> bitacora        (queda registrado, con su evidencia y su copia)

LA REGLA QUE LO DEFINE: **o pasa todo, o no queda nada**. Si la evaluacion
rechaza la herramienta, se retira del CLI y se restauran los ficheros. Un
comando a medias dentro de cli.py es peor que ningun comando: rompe el
producto entero para todos los demas usos.

POR QUE ESTO NO ES tool_synthesis. `cognia/agent/tool_synthesis.py` ya
sintetiza FUNCIONES PURAS que el modelo puede llamar como tool. Esto es otra
cosa: un COMANDO del CLI, con su puerta visible, su sitio en /ayuda, su cubo
de visibilidad y sus tests. El duenio lo pidio asi -- "que sean invocables
como comandos" --, y esa diferencia es justo la que ninguna maquinaria del
repo sabia cubrir: `_CMD_DESCRIPTIONS` es un dict literal y el despacho son
316 ramas elif escritas a mano.

EL PELIGRO, DECLARADO. Esto edita cli.py, que son 23.000 lineas y es el
producto. El duenio lo autorizo expresamente. Las defensas son tres y ninguna
es opcional: el injertador solo INSERTA (nunca reescribe lo que ya habia),
todo es transaccional con copia y rollback, y los 4 guardianes del catalogo
tienen que quedar verdes o se revierte.
"""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path

from cognia.compilador import injertador as inj
from cognia.compilador import receta as rec

_log = logging.getLogger(__name__)

DIR_HERRAMIENTAS = rec.RAIZ / "cognia" / "herramientas"


def _fase(nombre: str, ok: bool, detalle: str = "") -> dict:
    return {"fase": nombre, "ok": bool(ok), "detalle": detalle}


def compilar(texto: str, orch=None, evaluar: bool = True,
             seco: bool = False) -> dict:
    """Compila una herramienta a partir de su descripcion.

    `seco=True` hace todo menos tocar el CLI: util para ver que saldria.
    Devuelve {'ok','cmd','espec','fases','evaluacion','motivo','ficheros'}.
    """
    fases, ficheros = [], []
    t0 = time.time()

    # -- 1. especificacion ------------------------------------------------
    try:
        from cognia.compilador import especificacion as esp
    except ImportError as exc:
        return {"ok": False, "motivo": "falta especificacion.py: %s" % exc,
                "fases": fases}
    try:
        espec = esp.desde_texto(texto, orch=orch)
    except Exception as exc:
        return {"ok": False, "fases": fases,
                "motivo": "no pude entender que herramienta quieres: %s: %s"
                          % (type(exc).__name__, exc)}
    problemas = esp.validar(espec)
    fases.append(_fase("especificacion", not problemas,
                       "; ".join(problemas) if problemas
                       else "%s con %d criterios" % (espec.cmd,
                                                     len(espec.criterios))))
    if problemas:
        return {"ok": False, "cmd": espec.cmd, "espec": esp.a_dict(espec),
                "fases": fases, "motivo": "especificacion invalida: %s"
                                          % "; ".join(problemas)}

    # -- 2. generacion ----------------------------------------------------
    try:
        from cognia.compilador import generador as gen
    except ImportError as exc:
        return {"ok": False, "motivo": "falta generador.py: %s" % exc,
                "fases": fases}
    try:
        codigo = gen.generar(espec, orch=orch)
    except Exception as exc:
        return {"ok": False, "cmd": espec.cmd, "fases": fases,
                "motivo": "la generacion fallo: %s: %s"
                          % (type(exc).__name__, exc)}
    malos = gen.validar_codigo(codigo["handler"], espec.nombre)
    fases.append(_fase("generacion", not malos,
                       "via=%s; %s" % (codigo.get("via"),
                                       "; ".join(malos) if malos else "codigo limpio")))
    if malos:
        return {"ok": False, "cmd": espec.cmd, "fases": fases,
                "motivo": "el codigo generado no pasa la validacion: %s"
                          % "; ".join(malos)}

    if seco:
        return {"ok": True, "cmd": espec.cmd, "espec": esp.a_dict(espec),
                "fases": fases, "codigo": codigo, "seco": True,
                "motivo": "ensayo: no se toco el CLI"}

    # -- 3. ficheros de apoyo y tests -------------------------------------
    try:
        if codigo.get("modulo") and codigo.get("ruta_modulo"):
            ruta = rec.RAIZ / codigo["ruta_modulo"]
            ruta.parent.mkdir(parents=True, exist_ok=True)
            (ruta.parent / "__init__.py").touch(exist_ok=True)
            io.open(ruta, "w", encoding="utf-8", newline="\n").write(codigo["modulo"])
            ficheros.append(codigo["ruta_modulo"])
        ruta_tests = ""
        if codigo.get("tests") and codigo.get("ruta_tests"):
            ruta_tests = codigo["ruta_tests"]
            rt = rec.RAIZ / ruta_tests
            io.open(rt, "w", encoding="utf-8", newline="\n").write(codigo["tests"])
            ficheros.append(ruta_tests)
    except OSError as exc:
        return {"ok": False, "cmd": espec.cmd, "fases": fases,
                "motivo": "no pude escribir los ficheros: %s" % exc}
    fases.append(_fase("ficheros", True, ", ".join(ficheros) or "(ninguno)"))

    # -- 4. injerto (transaccional) ---------------------------------------
    res_inj = inj.injertar(cmd=espec.cmd, nombre=espec.nombre,
                           descripcion=espec.descripcion,
                           handler=codigo["handler"], cubo=espec.cubo,
                           categoria=espec.categoria, pasa_ai=espec.pasa_ai)
    fases.append(_fase("injerto", res_inj.get("ok", False),
                       "sitios=%s; %s" % (res_inj.get("sitios"),
                                          res_inj.get("motivo", ""))))
    if not res_inj.get("ok"):
        _limpiar(ficheros)
        return {"ok": False, "cmd": espec.cmd, "fases": fases,
                "motivo": "el injerto fallo (repo restaurado): %s"
                          % res_inj.get("motivo", "")}

    # -- 5. evaluacion profunda -------------------------------------------
    evaluacion = {}
    if evaluar:
        try:
            from cognia.compilador import evaluador as ev
            evaluacion = ev.evaluar(espec, ruta_tests=ruta_tests, orch=orch)
        except ImportError as exc:
            evaluacion = {"veredicto": "rechazada",
                          "motivo": "falta evaluador.py: %s" % exc}
        except Exception as exc:
            evaluacion = {"veredicto": "rechazada",
                          "motivo": "la evaluacion reventó: %s: %s"
                                    % (type(exc).__name__, exc)}
        fases.append(_fase("evaluacion",
                           evaluacion.get("veredicto") == "aprobada",
                           evaluacion.get("motivo", "")))
        if evaluacion.get("veredicto") != "aprobada":
            # LA REGLA: o pasa todo, o no queda nada.
            inj.retirar(espec.cmd, espec.nombre)
            _limpiar(ficheros)
            _registrar(espec, res_inj, evaluacion, codigo, estado="fallida")
            return {"ok": False, "cmd": espec.cmd, "fases": fases,
                    "evaluacion": evaluacion,
                    "motivo": "rechazada y retirada: %s"
                              % evaluacion.get("motivo", "")}

    _registrar(espec, res_inj, evaluacion, codigo, estado="viva")
    return {"ok": True, "cmd": espec.cmd, "espec": esp.a_dict(espec),
            "fases": fases, "evaluacion": evaluacion, "ficheros": ficheros,
            "segundos": time.time() - t0,
            "motivo": "%s dada de alta y verificada" % espec.cmd}


def _limpiar(ficheros: list) -> None:
    """Borra los ficheros que este intento creo. Solo los suyos."""
    for rel in ficheros:
        try:
            p = rec.RAIZ / rel
            if p.is_file():
                p.unlink()
        except OSError as exc:
            _log.warning("no pude borrar %s: %s", rel, exc)


def _registrar(espec, res_inj, evaluacion, codigo, estado: str) -> None:
    try:
        from cognia.compilador import bitacora as bit
        reg = bit.registrar(espec, res_inj, evaluacion, codigo=codigo)
        if estado != "viva":
            bit.marcar(espec.cmd, estado,
                       (evaluacion or {}).get("motivo", ""))
        return reg
    except Exception as exc:                   # la bitacora no puede costar el turno
        _log.warning("no se pudo registrar en la bitacora: %s", exc)
        return {}


def retirar(cmd: str) -> dict:
    """Quita una herramienta compilada: del CLI, de sus ficheros y del estado."""
    try:
        from cognia.compilador import bitacora as bit
        ficha = bit.obtener(cmd) or {}
    except Exception:
        ficha = {}
    nombre = ficha.get("nombre") or cmd.strip("/").replace("-", "_")
    res = inj.retirar(cmd, nombre)
    if res.get("ok"):
        _limpiar(ficha.get("ficheros") or [])
        try:
            from cognia.compilador import bitacora as bit
            bit.marcar(cmd, "retirada", "retirada a mano")
        except Exception as exc:
            _log.warning("bitacora sin actualizar: %s", exc)
    return res


def estado() -> dict:
    """Lo que ensenia '/compilar' a secas."""
    fuera = dict(rec.estado())
    try:
        from cognia.compilador import bitacora as bit
        fuera["compiladas"] = bit.listar()
        fuera["vivas"] = [h for h in fuera["compiladas"]
                          if h.get("estado") == "viva"]
    except Exception as exc:
        fuera["compiladas"] = []
        fuera["aviso"] = "bitacora no disponible: %s" % exc
    fuera["copias"] = inj.copias()[:5]
    return fuera
