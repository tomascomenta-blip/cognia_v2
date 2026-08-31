"""
cognia/compilador/injertador.py
===============================
Escribir un comando nuevo DENTRO del CLI de Cognia, sin romperlo.

ESTO ES LA PARTE PELIGROSA Y EL DUENIO LO AUTORIZO EXPRESAMENTE ("dale permiso
a cognia para que pueda editar su propio cli aunque sea peligroso"). El
permiso no quita el peligro: cli.py son 23.000 lineas y es el producto entero.
Asi que el injerto se hace con las mismas garantias con las que se toca una
base de datos:

  1. COPIA DE SEGURIDAD de los tres ficheros ANTES de tocar nada.
  2. Los cambios se aplican en memoria y se escriben de golpe.
  3. Tras escribir, se VALIDA: compile() de cada fichero.
  4. Despues, los GUARDIANES: los 4 ficheros de tests que examinan el
     catalogo. Si uno se pone rojo, el comando NO esta bien puesto.
  5. Si algo de 3 o 4 falla -> ROLLBACK COMPLETO y se devuelve el motivo.

O sea: el injerto es una TRANSACCION. O queda el comando entero y verde, o
queda el repo exactamente como estaba. Nunca a medias, que es el unico estado
del que no se sale solo.

QUE NO HACE, Y ES A PROPOSITO. No reescribe codigo existente: solo INSERTA
bloques nuevos en puntos de anclaje conocidos. Un compilador que pueda
modificar lineas que ya estaban puede romper cualquier cosa del producto; uno
que solo inserta, como mucho, aniade algo que no funciona -- y para eso estan
los guardianes. La frontera es esa y no se mueve.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from cognia.compilador import receta as rec

_log = logging.getLogger(__name__)

RAIZ = rec.RAIZ
DIR_COPIAS = Path.home() / ".cognia" / "compilador" / "copias"

# Ficheros que el injerto puede tocar. Lista CERRADA: si un dia hace falta
# tocar otro, se aniade aqui a mano y con motivo. Un injertador que pueda
# escribir en cualquier sitio no es un compilador, es un agujero.
TOCABLES = (rec.CLI, rec.VISIBILIDAD, rec.AYUDA)


class ErrorInjerto(Exception):
    """El injerto no se pudo aplicar. Lleva el motivo legible."""


# ── Copias de seguridad ──────────────────────────────────────────────────────

def _copiar(sello: str) -> dict:
    DIR_COPIAS.mkdir(parents=True, exist_ok=True)
    destino = DIR_COPIAS / sello
    destino.mkdir(parents=True, exist_ok=True)
    copias = {}
    for rel in TOCABLES:
        origen = RAIZ / rel
        dst = destino / rel.replace("/", "__")
        shutil.copy2(origen, dst)
        copias[rel] = dst
    return copias


def _restaurar(copias: dict) -> None:
    for rel, dst in copias.items():
        try:
            shutil.copy2(dst, RAIZ / rel)
        except OSError as exc:                 # nunca en silencio
            _log.error("ROLLBACK INCOMPLETO de %s: %s", rel, exc)


# ── Inserciones ──────────────────────────────────────────────────────────────

def _leer(rel: str) -> str:
    return io.open(RAIZ / rel, encoding="utf-8").read()


def _escribir(rel: str, txt: str) -> None:
    io.open(RAIZ / rel, "w", encoding="utf-8", newline="\n").write(txt)


def _insertar_tras_linea(txt: str, ancla: str, bloque: str) -> str:
    """Inserta `bloque` justo DESPUES de la linea que contiene `ancla`."""
    i = txt.find(ancla)
    if i < 0:
        raise ErrorInjerto("no encuentro el ancla %r" % ancla[:60])
    fin = txt.find("\n", i)
    fin = len(txt) if fin < 0 else fin + 1
    return txt[:fin] + bloque + txt[fin:]


def _insertar_antes(txt: str, ancla: str, bloque: str) -> str:
    i = txt.find(ancla)
    if i < 0:
        raise ErrorInjerto("no encuentro el ancla %r" % ancla[:60])
    return txt[:i] + bloque + txt[i:]


def _rama_despacho(cmd: str, nombre: str, pasa_ai: bool) -> str:
    cola = ", ai" if pasa_ai else ""
    return (
        '            elif raw == "%(c)s" or raw.startswith("%(c)s "):\n'
        '                _slash_%(n)s(\n'
        '                    raw[len("%(c)s "):]\n'
        '                    if raw.startswith("%(c)s ") else ""%(a)s)\n'
        % {"c": cmd, "n": nombre, "a": cola})


def _ancla_despacho(cmd: str, fuente: str) -> str:
    """Donde meter la rama nueva.

    Va ANTES del primer comando del que este sea extension por prefijo (para
    que el corto no se lo coma si alguien relaja su despacho), y si no hay
    ninguno, antes del fallback de 'Comando desconocido'.
    """
    candidatos = []
    for otro in rec.catalogo():
        if cmd.startswith(otro) and cmd != otro:
            m = re.search(r'\n(            elif raw == "%s" or raw\.startswith)'
                          % re.escape(otro), fuente)
            if m:
                candidatos.append((len(otro), m.group(1)))
    if candidatos:
        candidatos.sort(reverse=True)
        return candidatos[0][1]
    m = re.search(r'\n(            elif raw\.startswith\("/"\):)', fuente)
    if not m:
        raise ErrorInjerto("no encuentro donde acaba la cadena de comandos")
    return m.group(1)


# ── El injerto completo ──────────────────────────────────────────────────────

def injertar(cmd: str, nombre: str, descripcion: str, handler: str,
             cubo: str = "AVANZADO", categoria: str = "",
             pasa_ai: bool = False, correr_guardianes: bool = True) -> dict:
    """Da de alta `cmd` en los 5 sitios. Transaccional.

    `handler` es el codigo COMPLETO de la funcion `_slash_<nombre>`, ya escrito
    y con su docstring. `categoria` vacia = se elige la mas holgada de las que
    tienen hueco (la receta lo mide en vivo; suponer cual esta libre es como
    se rompio la suite dos veces).

    Devuelve {'ok','sitios','copia','motivo','guardianes'}.
    """
    cmd = (cmd or "").strip()
    ok_nombre, motivo_nombre = rec.validar_nombre(cmd)
    if not ok_nombre:
        return {"ok": False, "motivo": motivo_nombre, "sitios": []}
    if cubo not in ("NUCLEO", "AVANZADO", "LABORATORIO"):
        return {"ok": False, "motivo": "cubo invalido: %r" % cubo, "sitios": []}
    if not re.match(r"^def _slash_%s\(" % re.escape(nombre), handler.strip()):
        return {"ok": False, "sitios": [],
                "motivo": ("el handler tiene que empezar por "
                           "'def _slash_%s(' y empieza por %r"
                           % (nombre, handler.strip()[:40]))}

    if not categoria:
        libres = rec.categorias_con_hueco()
        if not libres:
            return {"ok": False, "sitios": [],
                    "motivo": "ninguna categoria de /ayuda admite un comando mas"}
        categoria = libres[0]

    sello = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), cmd.strip("/"))
    copia = _copiar(sello)
    sitios = []
    try:
        # 1. descripcion
        cli = _leer(rec.CLI)
        if '"%s":' % cmd not in cli:
            linea = '    "%s":%s"%s",\n' % (
                cmd, " " * max(1, 20 - len(cmd)), descripcion.replace('"', "'"))
            cli = _insertar_tras_linea(cli, '    "/ventana":', linea)
            sitios.append("descripcion")

        # 2. la funcion
        if "def _slash_%s(" % nombre not in cli:
            cli = _insertar_antes(cli, "def _slash_horizonte(",
                                  handler.rstrip("\n") + "\n\n\n")
            sitios.append("funcion")

        # 3. el despacho
        if 'raw == "%s"' % cmd not in cli:
            ancla = _ancla_despacho(cmd, cli)
            cli = _insertar_antes(cli, ancla,
                                  _rama_despacho(cmd, nombre, pasa_ai))
            sitios.append("despacho")
        _escribir(rec.CLI, cli)

        # 4. el cubo
        vis = _leer(rec.VISIBILIDAD)
        if '"%s"' % cmd not in vis:
            ancla = "%s: frozenset = frozenset({\n" % cubo
            vis = _insertar_tras_linea(vis, ancla, '    "%s",\n' % cmd)
            _escribir(rec.VISIBILIDAD, vis)
            sitios.append("cubo")

        # 5. la categoria
        ay = _leer(rec.AYUDA)
        if '"%s"' % cmd not in ay:
            ancla = '    "%s": (\n' % categoria
            if ancla not in ay:
                raise ErrorInjerto("no existe la categoria %r" % categoria)
            ay = _insertar_tras_linea(ay, ancla, '        "%s",\n' % cmd)
            _escribir(rec.AYUDA, ay)
            sitios.append("categoria")

        # -- validacion --------------------------------------------------
        for rel in TOCABLES:
            fuente = _leer(rel)
            try:
                compile(fuente, rel, "exec")
            except SyntaxError as exc:
                raise ErrorInjerto("%s quedo con sintaxis rota en la linea %s: %s"
                                   % (rel, exc.lineno, exc.msg))

        guardianes = {}
        if correr_guardianes:
            guardianes = correr_los_guardianes()
            if not guardianes.get("ok"):
                raise ErrorInjerto("los guardianes del catalogo se pusieron "
                                   "rojos: %s" % guardianes.get("resumen", ""))
        return {"ok": True, "sitios": sitios, "copia": str(copia and sello),
                "motivo": motivo_nombre, "categoria": categoria, "cubo": cubo,
                "guardianes": guardianes}

    except Exception as exc:
        _restaurar(copia)
        return {"ok": False, "sitios": [], "copia": sello,
                "motivo": "%s: %s (repo restaurado)" % (type(exc).__name__, exc)}


def correr_los_guardianes(timeout: float = 600.0) -> dict:
    """Corre los 4 ficheros de tests que examinan el catalogo.

    Se lanzan con el MISMO interprete que corre Cognia y en un subproceso: un
    pytest dentro del proceso del REPL importaria a medias el modulo que
    acabamos de reescribir y daria un veredicto sobre codigo viejo cacheado.
    """
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly"]
    cmd += list(rec.GUARDIANES)
    try:
        p = subprocess.run(cmd, cwd=str(RAIZ), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "resumen": "los guardianes no acabaron en %ds"
                                        % int(timeout)}
    except OSError as exc:
        return {"ok": False, "resumen": "no pude lanzar pytest: %s" % exc}
    salida = (p.stdout or "") + (p.stderr or "")
    ultima = [l for l in salida.splitlines() if l.strip()][-1:] or [""]
    fallos = [l for l in salida.splitlines() if l.startswith("FAILED")]
    return {"ok": p.returncode == 0, "resumen": ultima[0][:300],
            "fallos": fallos[:10], "codigo": p.returncode}


def retirar(cmd: str, nombre: str = "") -> dict:
    """Quita un comando de los 5 sitios. Es el deshacer del compilador.

    Solo borra lineas que contengan EXACTAMENTE ese comando (y el bloque de su
    funcion y su rama de despacho, delimitados). Si algo no cuadra, no toca
    nada: mejor un comando de mas que un cli.py cortado por la mitad.
    """
    nombre = nombre or cmd.strip("/").replace("-", "_")
    sello = "%s-retirar-%s" % (time.strftime("%Y%m%d-%H%M%S"), cmd.strip("/"))
    copia = _copiar(sello)
    try:
        cli = _leer(rec.CLI)
        # la funcion entera: de 'def _slash_x(' hasta el siguiente 'def ' a
        # nivel de modulo
        # Se sustituye por CADENA VACIA, no por "\n". El patron ya se come el
        # salto que abre el bloque, asi que devolver uno dejaba una linea en
        # blanco de mas por cada retirada: el fichero crecia un poco cada vez
        # y la ida y vuelta dejaba de ser byte a byte. Medido: injertar y
        # retirar cambiaba el sha256 de cli.py por UN caracter.
        pat = re.compile(r"\ndef _slash_%s\(.*?(?=\ndef )" % re.escape(nombre),
                         re.DOTALL)
        cli, n_fn = pat.subn("", cli)
        # la rama del despacho (4 lineas nuestras)
        pat_r = re.compile(
            r"\n            elif raw == \"%s\" or raw\.startswith\(\"%s \"\):"
            r"\n(?:                .*\n|                    .*\n)+?"
            r"(?=            elif |            else)" % (re.escape(cmd), re.escape(cmd)))
        cli, n_r = pat_r.subn("\n", cli)
        # la descripcion
        cli, n_d = re.subn(r'\n    "%s":.*?,(?=\n)' % re.escape(cmd), "", cli)
        _escribir(rec.CLI, cli)

        vis = _leer(rec.VISIBILIDAD)
        vis, n_c = re.subn(r'\n?    "%s",' % re.escape(cmd), "", vis)
        vis = re.sub(r'"%s", ' % re.escape(cmd), "", vis)
        _escribir(rec.VISIBILIDAD, vis)

        ay = _leer(rec.AYUDA)
        ay, n_a = re.subn(r'\n?        "%s",' % re.escape(cmd), "", ay)
        _escribir(rec.AYUDA, ay)

        for rel in TOCABLES:
            compile(_leer(rel), rel, "exec")
        g = correr_los_guardianes()
        if not g.get("ok"):
            raise ErrorInjerto("tras retirar, los guardianes fallan: %s"
                               % g.get("resumen", ""))
        return {"ok": True, "quitado": {"funcion": n_fn, "despacho": n_r,
                                        "descripcion": n_d, "cubo": n_c,
                                        "categoria": n_a}}
    except Exception as exc:
        _restaurar(copia)
        return {"ok": False, "motivo": "%s: %s (repo restaurado)"
                                       % (type(exc).__name__, exc)}


def copias() -> list:
    """Las copias de seguridad que hay, de la mas nueva a la mas vieja."""
    if not DIR_COPIAS.is_dir():
        return []
    return sorted((d.name for d in DIR_COPIAS.iterdir() if d.is_dir()),
                  reverse=True)


def revertir_a(sello: str) -> dict:
    """Restaura los tres ficheros desde una copia concreta."""
    d = DIR_COPIAS / sello
    if not d.is_dir():
        return {"ok": False, "motivo": "no existe la copia %r" % sello}
    copias_ = {rel: d / rel.replace("/", "__") for rel in TOCABLES}
    faltan = [r for r, p in copias_.items() if not p.is_file()]
    if faltan:
        return {"ok": False, "motivo": "copia incompleta, faltan: %s"
                                       % ", ".join(faltan)}
    _restaurar(copias_)
    return {"ok": True, "restaurados": list(copias_)}
