# -*- coding: utf-8 -*-
"""Ejecucion ESPECULATIVA de acciones, con aceptacion por EQUIVALENCIA DE EFECTO.

QUE RESUELVE
------------
El analogo del speculative decoding, pero un nivel mas arriba: mientras el
modelo grande piensa el paso n, se adelanta la ejecucion de las acciones PURAS
que probablemente pedira. Cuando el modelo por fin pide una, si su EFECTO
OBSERVABLE ya esta calculado se le entrega el resultado cacheado y el paso
cuesta ~0 ms de herramienta.

POR QUE EXISTE (el hueco)
-------------------------
Speculative Actions (arXiv 2510.04371) se queda en ~55% de aceptacion porque
compara la accion especulada con la real por SINTAXIS. Pero

    listar('dir')  ==  ejecutar('ls dir')  ==  ejecutar('dir dir')
                   ==  ejecutar('find dir -maxdepth 1')
                   ==  ejecutar('python -c "print(os.listdir(dir))"')

producen el MISMO efecto observable y hoy los cinco cuentan como fallo de
prediccion salvo que caiga el literal exacto. Este modulo acepta por efecto:
una TABLA explicita y auditable (``TABLA_EQUIVALENCIAS``) normaliza cada accion
a su efecto canonico y compara eso.

EVIDENCIA (MEDIDA aqui, no declarada)
-------------------------------------
Banco de 24 pares (accion especulada, accion real) de las tres familias,
ejecutados DE VERDAD con ``cognia.agent.tools.run_tool`` sobre un fixture
controlado y sobre directorios de este repo. Windows 11, cmd.exe como shell de
``ejecutar``, COGNIA_AUTONOMOUS=1, 2026-08-19. La columna VERDAD sale de correr
TAMBIEN la accion real y comparar el contenido normalizado:

    politica       aceptadas    igualdad  equivalencia  FALSOS  equiv. perdidos
    estricta        3/24 (12.5%)    3           0          0          12
    condicionada   13/24 (54.2%)    3          10          0           2
    permisiva      18/24 (75.0%)    3          15          3           0

    pares realmente equivalentes en el banco: 15/24
    la equivalencia sube la aceptacion de 12.5% a 54.2% (3 -> 13 pares) con
    CERO falsos aceptados; recall sobre los realmente equivalentes: 13/15

Los 3 falsos de la politica permisiva estan medidos y son reales: ``ls`` oculta
los dotfiles que ``listar`` si devuelve; ``findstr /s`` no respeta .gitignore;
y la tool ``buscar`` trunca a 15 lineas. La politica por defecto los caza con
un chequeo sobre el resultado YA CACHEADO, sin ejecutar nada extra.
Los 2 que pierde son honestos: un ``ls`` cacheado no puede PROBAR que no habia
ocultos, y ``grep -r`` frente a ``rg`` no tiene chequeo barato.

LIMITES DECLARADOS
------------------
- Solo especula acciones cuyo cubo de reversibilidad sea 'puro'. Si
  ``cognia.multiverso.reversibilidad`` no esta disponible se cae a una lista
  blanca LOCAL y conservadora (``_cubo_fallback``), que se declara en el
  resultado de ``estadisticas()['clasificador']``.
- Las equivalencias de cmd.exe (``dir``, ``type``, ``findstr``) solo valen en
  Windows; las de coreutils (``ls``, ``cat``, ``grep``) solo si estan en el
  PATH. El chequeo en caliente (``verificar_fn``) las falsea sin drama.
- ``ms_ahorrados`` es el coste MEDIDO de la ejecucion especulativa reutilizada.
  Para la via 'igualdad' es exacto (misma accion). Para 'equivalencia' es un
  PROXY del coste del alterno, y el banco lo midio: los 10 aceptados por
  equivalencia evitaron 231-299 ms de trabajo real (2 corridas) y
  ``ms_ahorrados`` conto 56-57 ms; error mediano ~98%. Es PESIMISTA si la real es
  un subprocess (`ls` cuesta ~25 ms de shell y `listar` ~0,3 ms de Python):
  toma ``ms_ahorrados`` como COTA INFERIOR del ahorro, nunca como cota superior.
- La especulacion pasa por el mismo centinela que la ejecucion normal: en esta
  maquina `rg` y `python -c` se bloquean sin COGNIA_AUTONOMOUS=1. Es la
  decision correcta (nada se salta el gate) pero recorta la superficie de
  equivalencias disponibles; medido al montar el banco.
- La comparacion de contenido en caliente es CONSERVADORA: puede rechazar un
  par verdaderamente equivalente (por topes de truncado distintos), nunca
  aceptar uno que no lo sea.
"""

from __future__ import annotations

import ast
import os
import re
import threading
import time
from dataclasses import dataclass, field

# ══════════════════════════════════════════════════════════════════════════
# TIPO DE ACCION
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Accion:
    """Una llamada a herramienta: nombre + args crudos (como los escribe el
    modelo). ``meta`` no entra en la identidad (ni en firma ni en hash)."""

    tool: str
    args: str = ""
    meta: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def firma(self) -> str:
        return firma(self)

    def a_dict(self) -> dict:
        return {"tool": self.tool, "args": self.args, "meta": dict(self.meta)}


def firma(accion) -> str:
    """Identidad SINTACTICA de una accion: 'tool|args con espacios colapsados'.

    Colapsar espacios no es aceptar por equivalencia: `ls  dir` y `ls dir` son
    literalmente el mismo comando para el shell."""
    a = _a_accion(accion)
    return "%s|%s" % (a.tool.strip(), re.sub(r"\s+", " ", a.args or "").strip())


def _a_accion(x) -> Accion:
    """Acepta Accion, dict, tupla/lista (tool, args) o 'tool args'."""
    if isinstance(x, Accion):
        return x
    if isinstance(x, dict):
        # "action" es la clave que usa el trace de agent/loop.py (linea 921):
        # sin ella, cablear predecir() al bucle exigia traducir la traza fuera.
        tool = (x.get("tool") or x.get("action") or x.get("nombre")
                or x.get("name") or "")
        args = x.get("args") or x.get("argumentos") or x.get("input") or ""
        meta = x.get("meta") if isinstance(x.get("meta"), dict) else {}
        return Accion(str(tool), str(args), dict(meta))
    if isinstance(x, (tuple, list)):
        if len(x) >= 2:
            return Accion(str(x[0]), str(x[1]))
        if len(x) == 1:
            return Accion(str(x[0]), "")
        raise ValueError("accion vacia")
    if isinstance(x, str):
        cabeza, _, cola = x.strip().partition(" ")
        return Accion(cabeza, cola.strip())
    raise TypeError("no se como convertir %r en Accion" % type(x))


# ══════════════════════════════════════════════════════════════════════════
# PUREZA: solo se especula lo que no deja huella
# ══════════════════════════════════════════════════════════════════════════

# Lista blanca LOCAL. Solo se usa cuando cognia.multiverso.reversibilidad no
# esta disponible o no sabe contestar. Es deliberadamente corta: en la duda,
# NO es puro (especular algo con efecto es el unico fallo inaceptable aqui).
_TOOLS_PURAS = frozenset({
    "listar", "leer_archivo", "leer_lote", "buscar", "buscar_ficheros",
    "arbol", "contar_lineas", "py_validar", "json_validar",
    "git_estado", "git_diff", "git_log", "repo_map", "code_grafo",
    "buscar_en_repo", "calcular", "fecha", "notas", "ctx_info", "ctx_ver",
    "ctx_grep",
})

# Cabezas de comando de SOLO LECTURA para `ejecutar`. `find` entra pero con
# veto explicito de sus acciones destructivas mas abajo.
_CMD_PUROS = frozenset({
    "ls", "dir", "cat", "type", "grep", "rg", "findstr", "find",
    "head", "tail", "wc", "stat", "file", "pwd", "whoami", "hostname",
})

# Metacaracteres que encadenan, redirigen o expanden: con cualquiera de estos
# el comando deja de ser analizable como "una lectura" y se rechaza entero.
_RE_METACHAR = re.compile(r"[;&|><`]|\$\(")

# `find` con estos predicados escribe o ejecuta: nunca es puro.
_RE_FIND_SUCIO = re.compile(r"(^|\s)-(delete|exec|execdir|ok|okdir|fprint\w*|fls)\b")

# El unico `python -c` que se considera puro: un os.listdir y nada mas.
_RE_PY_LISTDIR = re.compile(
    r"""^python[0-9.]*\s+-c\s+(?P<q>["'])\s*(?:import\s+os\s*;\s*)?"""
    r"""(?:print\s*\()?\s*os\.listdir\(\s*(?P<q2>["'])(?P<dir>[^"']*)(?P=q2)\s*\)"""
    r"""\s*\)?\s*(?P=q)\s*$""",
    re.IGNORECASE | re.VERBOSE)


def _cubo_fallback(accion: Accion) -> str:
    """Clasificador LOCAL de reversibilidad. Devuelve 'puro' o 'desconocido'."""
    tool = accion.tool.strip()
    if tool in _TOOLS_PURAS:
        return "puro"
    if tool != "ejecutar":
        return "desconocido"
    cmd = (accion.args or "").strip()
    # las claves de cola (| timeout=N | cwd=RUTA) no cambian la pureza
    cmd = re.split(r"\s*\|\s*(?:timeout|cwd)\s*=", cmd)[0].strip()
    if not cmd:
        return "desconocido"
    if _RE_PY_LISTDIR.match(cmd):
        return "puro"
    if _RE_METACHAR.search(cmd):
        return "desconocido"
    cabeza = cmd.split()[0].lower()
    cabeza = cabeza.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if cabeza.endswith(".exe"):
        cabeza = cabeza[:-4]
    if cabeza not in _CMD_PUROS:
        return "desconocido"
    if cabeza == "find" and _RE_FIND_SUCIO.search(cmd):
        return "desconocido"
    return "puro"


def _extraer_cubo(res) -> str:
    """Saca el nombre del cubo de lo que sea que devuelva clasificar()."""
    if isinstance(res, str):
        return res.strip().lower()
    if isinstance(res, dict):
        for k in ("cubo", "bucket", "clase", "categoria", "reversibilidad"):
            v = res.get(k)
            if isinstance(v, str):
                return v.strip().lower()
        return ""
    for k in ("cubo", "bucket", "clase", "categoria", "nombre", "value"):
        v = getattr(res, k, None)
        if isinstance(v, str):
            return v.strip().lower()
    return ""


def cubo_de(accion, clasificar_fn=None) -> str:
    """Cubo de reversibilidad de una accion ('puro', o lo que diga el modulo).

    ``clasificar_fn`` se inyecta en los tests. Sin el, se importa
    ``cognia.multiverso.reversibilidad.clasificar`` DENTRO de la funcion (el
    modulo puede no existir todavia: este paquete lo escriben varias manos) y
    si no esta, se cae al clasificador local declarado."""
    a = _a_accion(accion)
    fn = clasificar_fn
    if fn is None:
        try:
            from cognia.multiverso.reversibilidad import clasificar as fn  # type: ignore
        except Exception:
            fn = None
    if fn is not None:
        # La firma exacta de clasificar() no esta congelada: se prueban las
        # formas razonables y la primera que conteste algo util manda.
        for llamada in (
            lambda: fn(a.tool, a.args),
            lambda: fn(a.tool),
            lambda: fn({"tool": a.tool, "args": a.args}),
            lambda: fn(accion),
        ):
            try:
                cubo = _extraer_cubo(llamada())
            except Exception:
                continue
            if cubo:
                return cubo
    return _cubo_fallback(a)


def es_pura(accion, clasificar_fn=None) -> bool:
    return cubo_de(accion, clasificar_fn) == "puro"


# ══════════════════════════════════════════════════════════════════════════
# TABLA DE EQUIVALENCIAS  (el aporte diferencial; explicita y auditable)
# ══════════════════════════════════════════════════════════════════════════
#
# Cada regla convierte una accion en su EFECTO OBSERVABLE canonico:
#     ("LISTAR", <dir absoluto>)
#     ("LEER",   <fichero absoluto>)
#     ("BUSCAR", <patron>, <ambito absoluto>)
#
# Campos:
#   familia   LISTAR | LEER | BUSCAR
#   forma     'tool' (casa por nombre de tool) | 'cmd' (regex sobre `ejecutar`)
#   riesgo    'seguro'       el efecto es identico, sin condiciones
#             'condicionado' identico SI se cumple `condicion`, que se evalua
#                            sobre el RESULTADO YA CACHEADO (coste ~0)
#             'declarado'    hay una divergencia conocida que NO se puede
#                            comprobar barato; solo la politica 'permisiva' la
#                            acepta a ciegas
#   porque    la evidencia de por que se declara equivalente / arriesgada
#
_RE_LS = re.compile(r"^ls(?P<flags>(?:\s+-[A-Za-z0-9]+)*)\s+(?P<dir>.+?)\s*$")
_RE_DIR = re.compile(r"^dir(?P<flags>(?:\s+/[A-Za-z:]+)*)\s+(?P<dir>.+?)\s*$",
                     re.IGNORECASE)
_RE_FIND1 = re.compile(r"^find\s+(?P<dir>.+?)\s+-maxdepth\s+1\s*$")
_RE_CAT = re.compile(r"^(?:cat|type)\s+(?P<path>.+?)\s*$", re.IGNORECASE)
_RE_GREPR = re.compile(
    r"^grep(?P<flags>(?:\s+-[A-Za-z]+)*)\s+(?P<pat>.+?)\s+(?P<dir>\S+)\s*$")
_RE_RG = re.compile(
    r"^rg(?P<flags>(?:\s+(?:-[A-Za-z]+|--[a-z-]+(?:\s+\d+)?))*)"
    r"\s+(?P<pat>.+?)\s+(?P<dir>\S+)\s*$")
_RE_FINDSTR = re.compile(
    r"^findstr(?P<flags>(?:\s+/[A-Za-z]+)*)\s+(?P<pat>.+?)\s+(?P<dir>\S+)\s*$",
    re.IGNORECASE)

# Flags que CAMBIAN el conjunto devuelto: si aparecen, no hay equivalencia.
_LS_FLAGS_ROMPEN = ("a", "A", "R", "l")   # ocultos / recursivo / formato largo
_GREP_FLAGS_ROMPEN = ("i", "w", "x", "v", "l", "c", "o", "E", "F", "P")


def _sin_comillas(s: str) -> str:
    s = (s or "").strip()
    if len(s) > 1 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return s.strip()


def _abs(ruta: str, base=None) -> str:
    ruta = _sin_comillas(ruta) or "."
    base = base or os.getcwd()
    if not os.path.isabs(ruta):
        ruta = os.path.join(base, ruta)
    return os.path.normcase(os.path.normpath(os.path.abspath(ruta)))


def _cmd_limpio(args: str) -> str:
    """Comando de `ejecutar` sin las claves de cola (| timeout= | cwd=)."""
    return re.split(r"\s*\|\s*(?:timeout|cwd)\s*=", (args or "").strip())[0].strip()


def _cwd_de(args: str) -> str:
    m = re.search(r"\|\s*cwd\s*=\s*(.+?)\s*$", args or "")
    return _sin_comillas(m.group(1)) if m else ""


# --- condiciones evaluables sobre el resultado cacheado -------------------

_RE_LISTADO_TOOL = re.compile(r"^RESULTADO listar .*?: (\[.*\])\s*$", re.S)
_TOPE_LISTAR_TOOL = 40      # cognia/agent/tools.py::_listar corta en 40
_TOPE_BUSCAR_TOOL = 15      # cognia/agent/tools.py::_buscar corta en 15 lineas


def _nombres_de_listado_tool(texto: str):
    """['D a', 'F b'] -> {'a','b'}; None si el texto no es un listado de la tool."""
    m = _RE_LISTADO_TOOL.match((texto or "").strip())
    if not m:
        return None
    try:
        crudo = ast.literal_eval(m.group(1))
    except Exception:
        return None
    if not isinstance(crudo, list):
        return None
    out = set()
    for e in crudo:
        e = str(e)
        out.add(e[2:] if len(e) > 2 and e[:2] in ("D ", "F ") else e)
    return out


def _cond_sin_ocultos(entrada: dict) -> tuple:
    """(ok, motivo). `ls` sin -a OCULTA los dotfiles; `listar` (Path.iterdir)
    los devuelve. Solo son el mismo conjunto si no hay ninguno. Se comprueba
    sobre el listado YA cacheado: cuesta 0 ejecuciones."""
    nombres = _nombres_de_listado_tool(entrada.get("resultado", ""))
    if nombres is None:
        return (False, "no puedo leer el listado cacheado para ver si hay ocultos")
    if len(nombres) >= _TOPE_LISTAR_TOOL:
        return (False, "listado cacheado en el tope de %d: puede estar truncado"
                % _TOPE_LISTAR_TOOL)
    ocultos = sorted(n for n in nombres if n.startswith("."))
    if ocultos:
        return (False, "hay %d ocultos que `ls` no mostraria (%s)"
                % (len(ocultos), ", ".join(ocultos[:3])))
    return (True, "0 ocultos en el listado cacheado (%d entradas)" % len(nombres))


def _cond_listado_completo(entrada: dict) -> tuple:
    nombres = _nombres_de_listado_tool(entrada.get("resultado", ""))
    if nombres is None:
        return (True, "resultado no es un listado de la tool: sin tope que comprobar")
    if len(nombres) >= _TOPE_LISTAR_TOOL:
        return (False, "listado en el tope de %d: truncado" % _TOPE_LISTAR_TOOL)
    return (True, "%d entradas, por debajo del tope %d"
            % (len(nombres), _TOPE_LISTAR_TOOL))


def _cond_lectura_completa(entrada: dict) -> tuple:
    """`leer_archivo` corta a 2000 lineas y lo AVISA en el texto. Con el aviso,
    el contenido no es el de `cat`."""
    txt = entrada.get("resultado", "") or ""
    if re.search(r"offset=\d+|sigue el archivo|truncad", txt, re.I):
        return (False, "la lectura cacheada esta truncada")
    return (True, "lectura sin marca de truncado")


def _cond_busqueda_completa(entrada: dict) -> tuple:
    """La tool `buscar` corta a 15 lineas y pide a rg --max-count 3 por fichero.
    Si el resultado cacheado esta cerca de cualquiera de los dos topes, no se
    puede afirmar que sea el mismo conjunto que el de un rg sin topes."""
    txt = entrada.get("resultado", "") or ""
    if "sin coincidencias" in txt:
        return (True, "0 hits: el conjunto vacio no puede estar truncado")
    if "scan cortado" in txt:
        return (False, "el scan cacheado se corto por deadline")
    # Sirve tanto si lo cacheado es la tool como si es un rg/grep crudo: los
    # topes de la tool solo importan si el CONJUNTO de hits llega a rozarlos,
    # y eso se cuenta igual en las dos formas.
    hits = _hits_busqueda(txt)
    if hits is None:
        return (False, "no puedo contar los hits del resultado cacheado")
    if len(hits) >= _TOPE_BUSCAR_TOOL:
        return (False, "%d hits: en el tope de %d, truncado"
                % (len(hits), _TOPE_BUSCAR_TOOL))
    por_fichero = {}
    for f, _n, _t in hits:
        por_fichero[f] = por_fichero.get(f, 0) + 1
    saturados = [f for f, c in por_fichero.items() if c >= 3]
    if saturados:
        return (False, "%d fichero(s) con 3 hits: rg --max-count 3 pudo cortar"
                % len(saturados))
    return (True, "%d hits, ningun tope alcanzado" % len(hits))


TABLA_EQUIVALENCIAS = (
    # ---------------- familia LISTAR ----------------
    {"id": "listar.tool", "familia": "LISTAR", "forma": "tool",
     "tool": "listar", "riesgo": "seguro",
     "porque": "forma canonica de la familia (Path.iterdir, incluye ocultos)"},
    {"id": "listar.ls", "familia": "LISTAR", "forma": "cmd", "re": _RE_LS,
     "riesgo": "condicionado", "condicion": _cond_sin_ocultos,
     "porque": "`ls` sin -a oculta dotfiles; iguales solo si no hay ninguno. "
               "-a/-A/-R/-l cambian el conjunto o el formato: no casan"},
    {"id": "listar.dir", "familia": "LISTAR", "forma": "cmd", "re": _RE_DIR,
     "riesgo": "condicionado", "condicion": _cond_sin_ocultos,
     "porque": "cmd.exe DIR oculta lo que tiene el atributo HIDDEN (.git lo "
               "tiene). Condicion conservadora: ningun nombre con punto"},
    {"id": "listar.find1", "familia": "LISTAR", "forma": "cmd", "re": _RE_FIND1,
     "riesgo": "condicionado", "condicion": _cond_listado_completo,
     "porque": "find -maxdepth 1 lista lo mismo (ocultos incluidos) pero "
               "IMPRIME ADEMAS el propio directorio base: el normalizador de "
               "contenido lo descuenta explicitamente"},
    {"id": "listar.py", "familia": "LISTAR", "forma": "cmd",
     "re": _RE_PY_LISTDIR, "riesgo": "condicionado",
     "condicion": _cond_listado_completo,
     "porque": "os.listdir es literalmente lo que usa la tool"},
    # ---------------- familia LEER ----------------
    {"id": "leer.tool", "familia": "LEER", "forma": "tool",
     "tool": "leer_archivo", "riesgo": "seguro",
     "porque": "forma canonica; con offset=/limit= NO entra (lectura parcial)"},
    {"id": "leer.cat", "familia": "LEER", "forma": "cmd", "re": _RE_CAT,
     "riesgo": "condicionado", "condicion": _cond_lectura_completa,
     "porque": "cat/type vuelcan el fichero entero; la tool corta a 2000 "
               "lineas y lo avisa en el texto, que es lo que se comprueba"},
    # ---------------- familia BUSCAR ----------------
    {"id": "buscar.tool", "familia": "BUSCAR", "forma": "tool",
     "tool": "buscar", "riesgo": "seguro",
     "porque": "forma canonica (rg --no-heading -H -n --max-count 3)"},
    {"id": "buscar.rg", "familia": "BUSCAR", "forma": "cmd", "re": _RE_RG,
     "riesgo": "condicionado", "condicion": _cond_busqueda_completa,
     "porque": "la tool ES rg; solo divergen por sus topes (15 lineas, "
               "--max-count 3), que es justo lo que mira la condicion"},
    {"id": "buscar.grep", "familia": "BUSCAR", "forma": "cmd", "re": _RE_GREPR,
     "riesgo": "declarado",
     "porque": "MEDIDO: grep -r NO respeta .gitignore y rg SI. Sobre un repo "
               "con venv/ ignorado los conjuntos difieren en ordenes de "
               "magnitud. No hay chequeo barato: solo politica permisiva"},
    {"id": "buscar.findstr", "familia": "BUSCAR", "forma": "cmd",
     "re": _RE_FINDSTR, "riesgo": "declarado",
     "porque": "findstr /s no respeta .gitignore y su dialecto de regex no es "
               "el de rg; mismo caso que grep"},
)

_REGLAS_POR_ID = {r["id"]: r for r in TABLA_EQUIVALENCIAS}


def _flags_ls(txt: str):
    return set(re.sub(r"[\s-]", "", txt or ""))


def efecto_observable(accion, base=None) -> dict:
    """Normaliza una accion a su EFECTO OBSERVABLE canonico.

    Devuelve {'efecto': tupla-canonica, 'regla': id, 'familia': ...} o
    {'efecto': None, 'motivo': ...} si la accion no cae en la tabla."""
    a = _a_accion(accion)
    tool = a.tool.strip()
    base = base or os.getcwd()

    # --- formas 'tool' -----------------------------------------------------
    if tool == "listar":
        return _ok(("LISTAR", _abs(a.args or ".", base)), "listar.tool")
    if tool == "leer_archivo":
        crudo = (a.args or "").strip()
        if re.search(r"\b(offset|limit)\s*=", crudo):
            return _no("leer_archivo con offset/limit es una lectura PARCIAL")
        return _ok(("LEER", _abs(crudo, base)), "leer.tool")
    if tool == "buscar":
        partes = re.split(r"\s*\|\s*", a.args or "", maxsplit=1)
        patron = _sin_comillas(partes[0])
        ambito = _sin_comillas(partes[1]) if len(partes) > 1 else "."
        if not patron:
            return _no("buscar sin patron")
        return _ok(("BUSCAR", patron, _abs(ambito, base)), "buscar.tool")
    if tool != "ejecutar":
        return _no("tool '%s' fuera de la tabla de equivalencias" % tool)

    # --- formas 'cmd' ------------------------------------------------------
    cmd = _cmd_limpio(a.args)
    base = _cwd_de(a.args) or base
    if not cmd:
        return _no("ejecutar sin comando")

    m = _RE_PY_LISTDIR.match(cmd)
    if m:
        return _ok(("LISTAR", _abs(m.group("dir"), base)), "listar.py")
    m = _RE_LS.match(cmd)
    if m:
        rotos = _flags_ls(m.group("flags")) & set(_LS_FLAGS_ROMPEN)
        if rotos:
            return _no("ls con flags que cambian el conjunto: -%s"
                       % "".join(sorted(rotos)))
        return _ok(("LISTAR", _abs(m.group("dir"), base)), "listar.ls")
    m = _RE_DIR.match(cmd)
    if m:
        fl = (m.group("flags") or "").lower()
        if "/s" in fl or "/a" in fl or "/b" in fl:
            return _no("dir con /s, /a o /b cambia el conjunto o el formato")
        return _ok(("LISTAR", _abs(m.group("dir"), base)), "listar.dir")
    m = _RE_FIND1.match(cmd)
    if m:
        return _ok(("LISTAR", _abs(m.group("dir"), base)), "listar.find1")
    m = _RE_CAT.match(cmd)
    if m:
        p = _sin_comillas(m.group("path"))
        if " " in p and not os.path.exists(_abs(p, base)):
            return _no("cat/type con varios ficheros: concatena, no es un LEER")
        return _ok(("LEER", _abs(p, base)), "leer.cat")
    m = _RE_RG.match(cmd)
    if m:
        rotos = _flags_ls(re.sub(r"--\S+|\d+", "", m.group("flags") or "")) \
            & set(_GREP_FLAGS_ROMPEN)
        if rotos:
            return _no("rg con flags que cambian el conjunto: -%s"
                       % "".join(sorted(rotos)))
        return _ok(("BUSCAR", _sin_comillas(m.group("pat")),
                    _abs(m.group("dir"), base)), "buscar.rg")
    m = _RE_GREPR.match(cmd)
    if m:
        fl = _flags_ls(m.group("flags"))
        if not (fl & {"r", "R"}):
            return _no("grep sin -r no recorre el directorio")
        rotos = fl & set(_GREP_FLAGS_ROMPEN)
        if rotos:
            return _no("grep con flags que cambian el conjunto: -%s"
                       % "".join(sorted(rotos)))
        return _ok(("BUSCAR", _sin_comillas(m.group("pat")),
                    _abs(m.group("dir"), base)), "buscar.grep")
    m = _RE_FINDSTR.match(cmd)
    if m:
        fl = (m.group("flags") or "").lower()
        if "/s" not in fl:
            return _no("findstr sin /s no recorre el directorio")
        return _ok(("BUSCAR", _sin_comillas(m.group("pat")),
                    _abs(m.group("dir"), base)), "buscar.findstr")
    return _no("comando fuera de la tabla: %s" % cmd.split()[0])


def _ok(efecto, regla_id) -> dict:
    r = _REGLAS_POR_ID[regla_id]
    return {"efecto": efecto, "regla": regla_id, "familia": r["familia"],
            "riesgo": r["riesgo"], "porque": r["porque"]}


def _no(motivo) -> dict:
    return {"efecto": None, "regla": None, "familia": None,
            "riesgo": None, "motivo": motivo}


# ══════════════════════════════════════════════════════════════════════════
# NORMALIZACION DE CONTENIDO (para el chequeo EN CALIENTE, opcional)
# ══════════════════════════════════════════════════════════════════════════

# Una fila de la tabla de cmd.exe DIR. MEDIDO en esta maquina: el bloque de
# hora depende del LOCALE ('12:36a.<U+202F>m.' en es-ES) y el tamano va pegado
# al nombre por UN solo espacio, asi que no hay un patron de columnas fiable.
# Lo estable es: la fila EMPIEZA por fecha, y el nombre es lo que sigue a
# '<DIR>' o al ULTIMO campo numerico. Las filas de pie ('4 archivos ... bytes')
# no empiezan por fecha y quedan fuera solas.
_RE_DIR_FECHA = re.compile(r"^\d{2}[/.\-]\d{2}[/.\-]\d{4}\s")
_RE_DIR_TAM = re.compile(r"^.*\s[\d.,]+\s(?P<nombre>\S.*)$")


def _nombre_fila_dir(linea: str):
    if not _RE_DIR_FECHA.match(linea):
        return None
    if "<DIR>" in linea:
        return linea.split("<DIR>", 1)[1].strip() or None
    m = _RE_DIR_TAM.match(linea)
    return m.group("nombre").strip() if m else None
# Toda salida de `ejecutar` viene con esta cabecera pegada a la 1a linea.
_RE_CAB_EJEC = re.compile(r"^RESULTADO ejecutar(?: \([^)]*\))?:[ \t]*")


def _nombres_listado(texto: str, base_abs: str = "") -> frozenset:
    """Cualquier salida de la familia LISTAR -> conjunto de NOMBRES.

    Cubre: el formato de la tool, `ls`, la tabla de cmd.exe DIR, `find` (rutas)
    y la lista de python. El nombre base del propio directorio se descuenta
    (find lo imprime, los demas no) — normalizacion DECLARADA."""
    txt = (texto or "").strip()
    tool = _nombres_de_listado_tool(txt)
    if tool is not None:
        return frozenset(tool)
    # 'RESULTADO ejecutar: __init__.py\n...' -- la cabecera va PEGADA al
    # primer nombre; saltar la linea entera se comia una entrada, y quitarla
    # DESPUES del literal_eval hacia fallar la salida de os.listdir.
    txt = _RE_CAB_EJEC.sub("", txt).strip()
    try:
        lit = ast.literal_eval(txt)
        if isinstance(lit, list):
            return frozenset(str(x) for x in lit)
    except Exception:
        pass
    es_win = ("<DIR>" in txt) or bool(
        re.search(r"Director(?:y of|io de)", txt))
    out = set()
    for linea in txt.splitlines():
        linea = linea.rstrip()
        if not linea.strip():
            continue
        if es_win:
            nombre = _nombre_fila_dir(linea.strip())
            if nombre and nombre not in (".", ".."):
                out.add(nombre)
            continue
        s = linea.strip()
        if s.lower().startswith("resultado "):
            continue
        # `find` imprime rutas; `ls` nombres. basename normaliza las dos.
        s = s.replace("\\", "/").rstrip("/")
        nombre = s.rsplit("/", 1)[-1]
        if nombre and nombre not in (".", ".."):
            out.add(nombre)
    if base_abs:
        out.discard(os.path.basename(base_abs.rstrip("/\\")))
    return frozenset(out)


def _texto_leido(texto: str) -> str:
    """Salida de la familia LEER -> texto comparable: sin la cabecera
    'RESULTADO leer_archivo <p>:', con finales de linea unificados, sin
    espacios al final de cada linea y sin lineas vacias del final."""
    txt = (texto or "").strip()
    # OJO: la ruta lleva ':' (C:\...). Con [^:]* la cabecera se cortaba en
    # 'RESULTADO leer_archivo C' y el resto de la ruta entraba como contenido
    # (falso DISTINTO en todo par leer_archivo/cat con ruta absoluta, medido).
    # Non-greedy + exigir espacio/fin TRAS los dos puntos lo resuelve.
    txt = re.sub(r"^RESULTADO leer_archivo .*?:(?=[ \t]|$)[ \t]*", "", txt)
    txt = _RE_CAB_EJEC.sub("", txt)
    lineas = [l.rstrip() for l in txt.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lineas and not lineas[-1]:
        lineas.pop()
    return "\n".join(lineas)


def _partir_hit(linea: str):
    """'fichero[:linea]:texto' -> (fichero, nlinea|None, texto), o None.

    No se puede partir por el primer ':': en Windows la ruta empieza por 'C:'
    y ademas `rg`/`grep` SIN -n no emiten numero de linea (MEDIDO: el parser
    ingenuo devolvia CERO hits para `rg pat dir` y el conjunto vacio se
    comparaba como si fuese una busqueda sin resultados -- un vacio silencioso
    de manual)."""
    linea = (linea or "").strip()
    for m in re.finditer(r":", linea):
        i = m.start()
        if i == 1 and linea[0].isalpha():
            continue                      # letra de unidad: 'C:'
        if i + 1 < len(linea) and linea[i + 1] in "\\/":
            continue                      # ':' de una ruta UNC/absoluta
        resto = linea[i + 1:]
        mm = re.match(r"(\d+):(.*)$", resto, re.S)
        if mm:
            return (linea[:i], int(mm.group(1)), mm.group(2))
        return (linea[:i], None, resto)
    return None


def _hits_de_buscar_tool(texto: str):
    """'RESULTADO buscar ...: f:n: t | f:n: t' -> [(f, n, t)] o None."""
    m = re.match(r"^RESULTADO buscar .*?:\s*(?P<cuerpo>.*)$", (texto or "").strip(), re.S)
    if not m:
        return None
    cuerpo = m.group("cuerpo")
    if "sin coincidencias" in cuerpo:
        return []
    return _hits_sueltos(cuerpo.split(" | "))


def _hits_sueltos(lineas):
    """[(fichero, nlinea|None, texto)]. None si HABIA lineas y no parseo
    ninguna: devolver un conjunto vacio ahi seria decir 'no hay resultados'
    cuando lo que pasa es 'no se leer esto'."""
    out, con_texto = [], 0
    for l in lineas:
        if not (l or "").strip():
            continue
        con_texto += 1
        p = _partir_hit(l)
        if p is None:
            continue
        out.append((os.path.normcase(p[0].replace("\\", "/")), p[1],
                    re.sub(r"\s+", " ", p[2]).strip()))
    if con_texto and not out:
        return None
    return out


def _hits_busqueda(texto: str):
    """Salida de la familia BUSCAR -> conjunto de (fichero, linea|None, texto),
    o None si no es interpretable."""
    tool = _hits_de_buscar_tool(texto)
    if tool is not None:
        return frozenset(tool)
    txt = _RE_CAB_EJEC.sub("", (texto or "").strip())
    sueltos = _hits_sueltos(txt.splitlines())
    return None if sueltos is None else frozenset(sueltos)


def normalizar_contenido(familia: str, texto: str, efecto=None):
    """Contenido comparable de un resultado, por familia. None = no comparable."""
    if familia == "LISTAR":
        base = efecto[1] if efecto and len(efecto) > 1 else ""
        return _nombres_listado(texto, base)
    if familia == "LEER":
        return _texto_leido(texto)
    if familia == "BUSCAR":
        return _hits_busqueda(texto)
    return None


def contenidos_iguales(familia: str, a, b) -> bool:
    """Compara dos contenidos ya normalizados. None (no interpretable) NUNCA
    es igual a nada: en la duda, se rechaza.

    En BUSCAR el numero de linea solo existe si quien corrio la busqueda uso
    -n (la tool si, `rg pat dir` a secas no). Cuando un lado no lo trae, la
    comparacion baja a (fichero, texto) EN LOS DOS LADOS: es el observable
    comun de la familia, y se declara aqui en vez de esconderlo."""
    if a is None or b is None:
        return False
    if familia == "BUSCAR":
        falta_n = any(h[1] is None for h in a) or any(h[1] is None for h in b)
        if falta_n:
            a = frozenset((f, t) for f, _n, t in a)
            b = frozenset((f, t) for f, _n, t in b)
    return a == b


# ══════════════════════════════════════════════════════════════════════════
# PREDICTOR
# ══════════════════════════════════════════════════════════════════════════


def _historial(contexto) -> list:
    if isinstance(contexto, (list, tuple)):
        crudo = contexto
    elif isinstance(contexto, dict):
        crudo = (contexto.get("historial") or contexto.get("traza")
                 or contexto.get("pasos") or [])
    else:
        crudo = []
    out = []
    for x in crudo:
        try:
            out.append(_a_accion(x))
        except Exception:
            continue
    return out


def predecir(contexto, k: int = 3, predictor_fn=None,
             clasificar_fn=None) -> list:
    """Hasta ``k`` acciones PURAS probables para el paso siguiente.

    Con ``predictor_fn`` (un modelo chico) se usa lo que proponga; sin el, un
    predictor DETERMINISTICO y barato: bigramas sobre la traza. Si tras
    'listar' el agente pidio 'leer_archivo' el 70% de las veces, eso es una
    prediccion legitima que no cuesta ni un token.

    La lista devuelta SIEMPRE esta filtrada por pureza, venga de donde venga
    la propuesta: un predictor inyectado no puede colar un `git push`."""
    hist = _historial(contexto)
    propuestas = []
    if predictor_fn is not None:
        try:
            crudo = predictor_fn(contexto, k)
        except TypeError:
            crudo = predictor_fn(contexto)
        for x in (crudo or []):
            try:
                a = _a_accion(x)
            except Exception:
                continue
            a.meta.setdefault("via", "predictor_fn")
            propuestas.append(a)
    else:
        propuestas = _predecir_bigrama(hist)

    salida, vistas = [], set()
    for a in propuestas:
        f = firma(a)
        if f in vistas:
            continue
        if not es_pura(a, clasificar_fn):
            a.meta["descartada"] = "cubo != puro"
            continue
        vistas.add(f)
        salida.append(a)
        if len(salida) >= max(0, int(k)):
            break
    return salida


def _predecir_bigrama(hist: list) -> list:
    """Bigramas tool->(tool, args) sobre la traza. Sin traza util, [].

    Se cuentan PARES COMPLETOS (que args acompanaron a esa tool detras de
    aquella otra): predecir 'leer_archivo' sin decir QUE fichero no sirve para
    ejecutar nada por adelantado."""
    if len(hist) < 2:
        return []
    ultimo = hist[-1].tool
    conteo, reciente, total = {}, {}, 0
    for i in range(len(hist) - 1):
        prev, sig = hist[i], hist[i + 1]
        if prev.tool != ultimo:
            continue
        total += 1
        clave = (sig.tool, re.sub(r"\s+", " ", (sig.args or "").strip()))
        conteo[clave] = conteo.get(clave, 0) + 1
        reciente[clave] = i
    if not conteo:
        return []
    ordenadas = sorted(conteo.items(),
                       key=lambda kv: (-kv[1], -reciente[kv[0]]))
    out = []
    for (tool, args), n in ordenadas:
        out.append(Accion(tool, args, {
            "via": "bigrama", "conteo": n, "de": total,
            "prob": round(n / float(total), 4)}))
    return out


# ══════════════════════════════════════════════════════════════════════════
# EJECUCION ESPECULATIVA
# ══════════════════════════════════════════════════════════════════════════

_LOCK = threading.Lock()
_ESTADO = {
    "especuladas": 0, "vetadas": 0,
    "aceptadas_igualdad": 0, "aceptadas_equivalencia": 0, "rechazadas": 0,
    "ms_especulados": 0.0, "ms_ahorrados": 0.0,
    "por_familia": {}, "por_regla": {},
    "clasificador": "sin-determinar",
}


def reiniciar():
    """Pone el contador a cero. Los tests lo llaman; el CLI, al abrir sesion."""
    with _LOCK:
        _ESTADO.update({
            "especuladas": 0, "vetadas": 0, "aceptadas_igualdad": 0,
            "aceptadas_equivalencia": 0, "rechazadas": 0,
            "ms_especulados": 0.0, "ms_ahorrados": 0.0,
            "por_familia": {}, "por_regla": {},
            "clasificador": "sin-determinar",
        })


def _marcar_clasificador():
    try:
        from cognia.multiverso import reversibilidad  # noqa: F401
        _ESTADO["clasificador"] = "reversibilidad.clasificar"
    except Exception:
        _ESTADO["clasificador"] = "fallback local (_CUBO_FALLBACK declarado)"


def ejecutar_especulativo(acciones, run_tool_fn, ctx=None,
                          clasificar_fn=None, esperar=False) -> dict:
    """Corre las acciones en un hilo aparte y cachea {firma: resultado, ms}.

    Vuelve a comprobar la pureza JUSTO ANTES de correr cada una (defensa en
    profundidad: entre predecir() y aqui puede haber pasado cualquier cosa, y
    el coste de un `git push` especulado no se deshace).

    Devuelve el cache: {'entradas', 'indice_efecto', 'hilo', 'esperar',
    'vetadas'}. ``esperar(timeout)`` bloquea hasta que el hilo termine."""
    ctx = ctx if isinstance(ctx, dict) else {}
    base = ctx.get("cwd") or ctx.get("workspace") or os.getcwd()
    cache = {"entradas": {}, "indice_efecto": {}, "vetadas": [],
             "base": base, "lock": threading.Lock()}
    _marcar_clasificador()

    pendientes = []
    for x in (acciones or []):
        a = _a_accion(x)
        if not es_pura(a, clasificar_fn):
            cache["vetadas"].append({"accion": a.a_dict(),
                                     "motivo": "cubo != puro (2o chequeo)"})
            with _LOCK:
                _ESTADO["vetadas"] += 1
            continue
        pendientes.append(a)

    def _correr():
        for a in pendientes:
            t0 = time.perf_counter()
            try:
                res = run_tool_fn(a.tool, a.args, ctx)
                ok = True
            except Exception as exc:                       # pragma: no cover
                res, ok = "ERROR especulativo: %s" % exc, False
            ms = (time.perf_counter() - t0) * 1000.0
            ef = efecto_observable(a, base)
            entrada = {"accion": a, "resultado": res, "ok": ok,
                       "ms": ms, "efecto": ef.get("efecto"),
                       "familia": ef.get("familia"), "regla": ef.get("regla"),
                       "consumida": False}
            with cache["lock"]:
                cache["entradas"][firma(a)] = entrada
                if ef.get("efecto") is not None:
                    cache["indice_efecto"].setdefault(ef["efecto"], firma(a))
            with _LOCK:
                _ESTADO["especuladas"] += 1
                _ESTADO["ms_especulados"] += ms

    hilo = threading.Thread(target=_correr, name="especulacion", daemon=True)
    cache["hilo"] = hilo
    cache["esperar"] = lambda timeout=None: hilo.join(timeout)
    hilo.start()
    if esperar:
        hilo.join()
    return cache


# ══════════════════════════════════════════════════════════════════════════
# ACEPTACION — EL CORAZON
# ══════════════════════════════════════════════════════════════════════════

POLITICAS = {
    # solo firma identica: es la linea base de la literatura (55%)
    "estricta": {"equivalencia": False, "riesgos": frozenset()},
    # por defecto: equivalencias seguras + las condicionadas cuya condicion
    # se cumple sobre el resultado YA cacheado (coste ~0 ejecuciones)
    "condicionada": {"equivalencia": True,
                     "riesgos": frozenset({"seguro", "condicionado"})},
    # todo lo que diga la tabla, sin comprobar nada: sirve para MEDIR el techo
    # y para contar los falsos aceptados. No usar en produccion.
    "permisiva": {"equivalencia": True,
                  "riesgos": frozenset({"seguro", "condicionado", "declarado"})},
}


def _entradas(cache) -> dict:
    if isinstance(cache, dict) and "entradas" in cache:
        return cache["entradas"]
    return cache if isinstance(cache, dict) else {}


def aceptar(accion_real, cache, politica: str = "condicionada",
            verificar_fn=None, esperar_ms: float = 0.0) -> dict:
    """Intenta servir ``accion_real`` desde el cache especulativo.

    Devuelve {'aceptada', 'via', 'resultado', 'evidencia'} donde ``via`` es
    'igualdad' | 'equivalencia' | None.

    Camino:
      1) firma identica -> aceptada por igualdad (coste 0, riesgo 0);
      2) mismo EFECTO OBSERVABLE segun la tabla, con la condicion de la regla
         evaluada sobre el resultado cacheado;
      3) si se pasa ``verificar_fn`` (modo AUDITORIA: corre la accion real y
         devuelve su texto), ademas se compara el CONTENIDO normalizado y una
         diferencia VETA la aceptacion;
      4) si nada casa, rechazo con motivo.
    """
    if politica not in POLITICAS:
        raise ValueError("politica desconocida: %r (validas: %s)"
                         % (politica, ", ".join(sorted(POLITICAS))))
    pol = POLITICAS[politica]
    real = _a_accion(accion_real)
    if esperar_ms and isinstance(cache, dict) and callable(cache.get("esperar")):
        cache["esperar"](esperar_ms / 1000.0)
    ents = _entradas(cache)
    base = cache.get("base") if isinstance(cache, dict) else None
    ev = {"firma_real": firma(real), "politica": politica,
          "especuladas_en_cache": len(ents)}

    # --- 1) igualdad exacta -------------------------------------------------
    ent = ents.get(firma(real))
    if ent is not None:
        ev["regla"] = "igualdad-de-firma"
        ev["ms_de_la_especulacion"] = round(ent["ms"], 3)
        return _sellar(True, "igualdad", ent, ev, cache)

    ef_real = efecto_observable(real, base)
    ev["efecto_real"] = ef_real.get("efecto")
    ev["regla_real"] = ef_real.get("regla")
    if not pol["equivalencia"]:
        ev["motivo"] = "politica 'estricta': solo igualdad de firma"
        return _sellar(False, None, None, ev, cache)
    if ef_real.get("efecto") is None:
        ev["motivo"] = "accion real fuera de la tabla: %s" % ef_real.get("motivo")
        return _sellar(False, None, None, ev, cache)

    # --- 2) equivalencia de efecto -----------------------------------------
    f_cache = None
    if isinstance(cache, dict) and "indice_efecto" in cache:
        with (cache.get("lock") or _LOCK):
            f_cache = cache["indice_efecto"].get(ef_real["efecto"])
    if f_cache is None:
        for f, e in ents.items():
            if e.get("efecto") == ef_real["efecto"]:
                f_cache = f
                break
    if f_cache is None:
        ev["motivo"] = "ninguna especulacion tiene el efecto %r" % (ef_real["efecto"],)
        return _sellar(False, None, None, ev, cache)

    ent = ents[f_cache]
    ev["firma_especulada"] = f_cache
    ev["regla_especulada"] = ent.get("regla")
    ev["familia"] = ef_real["familia"]
    ev["ms_de_la_especulacion"] = round(ent["ms"], 3)

    # riesgo de la pareja = el PEOR de las dos reglas implicadas
    orden = {"seguro": 0, "condicionado": 1, "declarado": 2}
    reglas = [r for r in (ent.get("regla"), ef_real.get("regla")) if r]
    riesgo = max((_REGLAS_POR_ID[r]["riesgo"] for r in reglas),
                 key=lambda x: orden[x])
    ev["riesgo"] = riesgo
    ev["porque"] = [_REGLAS_POR_ID[r]["porque"] for r in reglas]
    if riesgo not in pol["riesgos"]:
        ev["motivo"] = ("regla de riesgo '%s' no admitida por la politica '%s'"
                        % (riesgo, politica))
        return _sellar(False, None, None, ev, cache)

    # condiciones evaluadas sobre el RESULTADO CACHEADO (0 ejecuciones)
    if politica != "permisiva":
        for r in reglas:
            cond = _REGLAS_POR_ID[r].get("condicion")
            if cond is None:
                continue
            ok, motivo = cond(ent)
            ev.setdefault("condiciones", []).append(
                {"regla": r, "ok": bool(ok), "detalle": motivo})
            if not ok:
                ev["motivo"] = "condicion de %s no se cumple: %s" % (r, motivo)
                return _sellar(False, None, None, ev, cache)

    # --- 3) chequeo EN CALIENTE (opcional, modo auditoria) -----------------
    if verificar_fn is not None:
        try:
            texto_real = verificar_fn(real.tool, real.args)
        except Exception as exc:                            # pragma: no cover
            texto_real = None
            ev["verificacion"] = "fallo: %s" % exc
        if texto_real is not None:
            fam = ef_real["familia"]
            a = normalizar_contenido(fam, ent["resultado"], ef_real["efecto"])
            b = normalizar_contenido(fam, texto_real, ef_real["efecto"])
            igual = contenidos_iguales(fam, a, b)
            ev["contenido_igual"] = bool(igual)
            if not igual:
                ev["motivo"] = "el contenido normalizado DIFIERE"
                ev["diferencia"] = _diferencia(fam, a, b)
                return _sellar(False, None, None, ev, cache)

    return _sellar(True, "equivalencia", ent, ev, cache)


def _diferencia(familia, a, b):
    if isinstance(a, frozenset) and isinstance(b, frozenset):
        return {"solo_especulada": sorted(map(str, a - b))[:8],
                "solo_real": sorted(map(str, b - a))[:8]}
    if isinstance(a, str) and isinstance(b, str):
        return {"len_especulada": len(a), "len_real": len(b)}
    return {"especulada": type(a).__name__, "real": type(b).__name__}


def _sellar(aceptada, via, ent, ev, cache) -> dict:
    with _LOCK:
        if aceptada:
            _ESTADO["aceptadas_igualdad" if via == "igualdad"
                    else "aceptadas_equivalencia"] += 1
            _ESTADO["ms_ahorrados"] += ent["ms"]
            fam = ent.get("familia") or "?"
            _ESTADO["por_familia"][fam] = _ESTADO["por_familia"].get(fam, 0) + 1
            reg = ev.get("regla") or "%s->%s" % (ev.get("regla_especulada"),
                                                 ev.get("regla_real"))
            _ESTADO["por_regla"][reg] = _ESTADO["por_regla"].get(reg, 0) + 1
        else:
            _ESTADO["rechazadas"] += 1
    if aceptada and isinstance(cache, dict):
        with (cache.get("lock") or _LOCK):
            ent["consumida"] = True
    return {"aceptada": bool(aceptada), "via": via,
            "resultado": ent["resultado"] if aceptada else None,
            "evidencia": ev}


# ══════════════════════════════════════════════════════════════════════════
# ESTADISTICAS — la tasa de aceptacion es la METRICA PRIMARIA
# ══════════════════════════════════════════════════════════════════════════


def estadisticas() -> dict:
    with _LOCK:
        e = dict(_ESTADO)
    aceptadas = e["aceptadas_igualdad"] + e["aceptadas_equivalencia"]
    intentos = aceptadas + e["rechazadas"]
    e["aceptadas"] = aceptadas
    e["intentos"] = intentos
    e["tasa_aceptacion"] = round(aceptadas / intentos, 4) if intentos else 0.0
    e["tasa_solo_igualdad"] = (round(e["aceptadas_igualdad"] / intentos, 4)
                               if intentos else 0.0)
    e["ganancia_equivalencia"] = round(
        e["tasa_aceptacion"] - e["tasa_solo_igualdad"], 4)
    e["ms_desperdiciados"] = round(
        max(0.0, e["ms_especulados"] - e["ms_ahorrados"]), 3)
    e["ms_ahorrados"] = round(e["ms_ahorrados"], 3)
    e["ms_especulados"] = round(e["ms_especulados"], 3)
    e["por_familia"] = dict(e["por_familia"])
    e["por_regla"] = dict(e["por_regla"])
    e["nota_ahorro"] = ("ms_ahorrados = coste MEDIDO de la especulacion "
                        "reutilizada; exacto en la via 'igualdad'. En la via "
                        "'equivalencia' es COTA INFERIOR: en el banco los "
                        "aceptados evitaron 231-299 ms reales y aqui se "
                        "cuentan 56-57 (la real suele ser un subprocess)")
    return e
