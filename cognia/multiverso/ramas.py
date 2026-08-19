# -*- coding: utf-8 -*-
"""
cognia/multiverso/ramas.py
==========================
MOTOR DE RAMIFICACION con contabilidad de efectos: correr K trayectorias
ALTERNATIVAS de la misma tarea, con efectos secundarios REALES sobre disco,
juzgarlas por postcondiciones verificadas y fusionar SOLO la ganadora al
workspace real.

QUE RESUELVE
------------
El "best-of-K" de la literatura se hace con muestreos de TEXTO porque nadie
sabe deshacer el mundo: si la rama 2 borro un fichero, ya esta borrado. Aqui
las ramas corren en COPIAS del workspace, se descartan por rmtree y la unica
que toca el ws real es la ganadora (`fusionar`). Y las acciones que NO se
pueden deshacer (git push, correo, POST) quedan VETADAS dentro de la rama y
ENCOLADAS para ejecutarse UNA sola vez, en el mundo real, si esa rama gana
(`guardia_de_rama`). Eso es lo que hace la ramificacion segura.

POR QUE EXISTE (huecos medidos de la revision de campo, 2026-08-18)
-------------------------------------------------------------------
1. "Rollback de efectos EXTERNOS al sandbox": nadie revierte el push, el
   correo, la fila en la BD. La respuesta de este modulo NO es revertirlos:
   es NO EJECUTARLOS mientras la trayectoria sea especulativa. Es la unica
   respuesta honesta que da un sistema de ficheros.
2. "Las acciones no estan clasificadas por REVERSIBILIDAD sino por tipo de
   herramienta": el harness pregunta "permito Bash?" cuando lo que decide si
   ramificar es viable es "esto se deshace, con que mecanismo y en cuanto".
   `guardia_de_rama` pregunta lo segundo (delegando en
   cognia/multiverso/reversibilidad.py) y deja el CONTEO en el informe
   (`contar_por_cubo`): que fraccion de las acciones reales cae en cada cubo
   es un numero HOY DESCONOCIDO y es el que decide si ramificar es viable.
3. "Mejoras con K=16 reportadas sin descontar el coste": por eso `coste()`
   devuelve pared, pasos, bytes movidos y -lo importante-
   `factor_vs_una_rama`: cuantas veces mas caro salio esto que correr una vez.

EVIDENCIA / MEDICION (hecha en esta maquina, no declarada)
----------------------------------------------------------
- k=3 sobre un ws real en tmp con correr_rama_fn determinista: informe pegado
  en el reporte de entrega; verificado LEYENDO EL DISCO que el ws real quedo
  con el contenido exacto de la ganadora y sin rastro de las perdedoras.
- Secuencial vs paralelo: `paralelo=True` existe pero el DEFAULT es
  secuencial. Motivo medido en simulacion honesta (un mutex que emula el
  UNICO slot de llama-server de esta maquina): con el recurso serializado,
  3 hilos tardan lo mismo que 3 corridas seguidas. NO esta medido contra un
  llama-server real: eso queda DECLARADO como pendiente, no afirmado.

LIMITES QUE ESTE MODULO NO ESCONDE
----------------------------------
- La "copia barata" de un workspace en NTFS es una COPIA DE BYTES. Los enlaces
  duros no se usan a proposito: las tools del repo reescriben ficheros enteros
  (open('w') TRUNCA el inodo compartido), asi que un hardlink haria que la
  rama corrompiera el ws real. El precio esta MEDIDO y sale en el informe
  (`bytes_copiados`, `pared_copias_s`).
- Solo se ramifica el ESTADO EN FICHEROS. Procesos vivos, puertos, servicios y
  BDs externas no se copian ni se revierten.
- Si cognia/multiverso/instantanea.py o reversibilidad.py no estan disponibles
  (o su API cambia), este modulo NO finge: cae a un mecanismo propio mas tosco
  y lo DICE en el informe (`instantanea.mecanismo`, `clasificador`).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

# Directorios que no se copian ni se comparan: no son estado de la tarea y
# multiplican el coste de la copia por nada.
IGNORAR = (".git", "__pycache__", ".pytest_cache", "node_modules",
           ".mypy_cache", ".ruff_cache", "venv", "venv312", ".venv")

# Cubos que la puerta considera NO especulables. Se comparan en minusculas y
# por SUBCADENA porque el vocabulario exacto lo fija reversibilidad.py (lo
# escribe otro modulo); 'irreversible', 'externo_irreversible' y
# 'irreversible_externo' tienen que casar todos.
_MARCA_IRREVERSIBLE = "irrevers"
_MARCA_DESCONOCIDO = "desconocid"


# -- ledger ---------------------------------------------------------------

def ruta_ledger(ruta=None) -> Path:
    """Donde se anota TODO lo que hace el motor (append-only, JSONL).

    Prioridad: argumento > COGNIA_MULTIVERSO_LEDGER > ~/.cognia/multiverso/
    ramas.jsonl. El argumento existe para que los tests no escriban en el HOME
    del dueno.
    """
    if ruta:
        return Path(str(ruta))
    env = os.environ.get("COGNIA_MULTIVERSO_LEDGER", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".cognia" / "multiverso" / "ramas.jsonl"


def anotar(evento: str, datos: dict, ruta=None) -> bool:
    """Una linea JSON por evento. Nunca lanza: un ledger roto no puede tumbar
    una corrida (cuando se escribe aqui, el motor ya movio ficheros reales)."""
    try:
        destino = ruta_ledger(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        fila = {"ts": time.time(), "evento": evento}
        fila.update(datos or {})
        with open(destino, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        return False


def leer_ledger(ruta=None) -> list:
    """Las filas del ledger (para auditar). Las lineas corruptas se saltan."""
    filas = []
    try:
        destino = ruta_ledger(ruta)
        if not destino.is_file():
            return filas
        for linea in destino.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                filas.append(json.loads(linea))
            except Exception:
                continue
    except Exception:
        pass
    return filas


# -- ficheros: manifiesto, copia, borrado ---------------------------------

def _saltable(partes) -> bool:
    return any(p in IGNORAR for p in partes)


def _sha1(ruta: Path) -> str:
    h = hashlib.sha1()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(1 << 16), b""):
            h.update(trozo)
    return h.hexdigest()


def manifiesto(ws) -> dict:
    """{ruta_relativa_posix: (bytes, sha1)} de todo el workspace.

    Es la unidad de comparacion del fallback: el hash decide 'modificado', no
    la mtime. Dos escrituras dentro del mismo tick son indistinguibles por
    mtime en NTFS, y ese falso negativo se llevaria por delante la fusion.
    """
    raiz = Path(str(ws))
    salida = {}
    if not raiz.is_dir():
        return salida
    for actual, dirs, ficheros in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in IGNORAR]
        for nombre in ficheros:
            ruta = Path(actual) / nombre
            try:
                rel = ruta.relative_to(raiz).as_posix()
            except Exception:
                continue
            if _saltable(Path(rel).parts):
                continue
            try:
                salida[rel] = (ruta.stat().st_size, _sha1(ruta))
            except Exception:
                # Un fichero bloqueado por otro proceso no puede fingirse
                # igual: se marca ilegible y la fusion lo tratara como cambio.
                salida[rel] = (-1, "ILEGIBLE")
    return salida


def _bytes_de(manif: dict) -> int:
    return sum(max(0, t[0]) for t in manif.values())


def copiar_workspace(origen, destino) -> dict:
    """Copia el ws entero. Devuelve {'bytes', 'ficheros', 'pared_s'}.

    NO usa enlaces duros a proposito (ver limites en la cabecera del modulo).
    """
    t0 = time.perf_counter()
    org, dst = Path(str(origen)), Path(str(destino))
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(org, dst, ignore=shutil.ignore_patterns(*IGNORAR),
                    dirs_exist_ok=True)
    manif = manifiesto(dst)
    return {"bytes": _bytes_de(manif), "ficheros": len(manif),
            "pared_s": round(time.perf_counter() - t0, 4)}


def _borrar(ruta) -> int:
    """rmtree tolerante. Devuelve bytes liberados (0 si no habia nada)."""
    ruta = Path(str(ruta))
    if not ruta.exists():
        return 0
    tam = _bytes_de(manifiesto(ruta)) if ruta.is_dir() else 0
    shutil.rmtree(ruta, ignore_errors=True)
    return tam


# -- capa de instantanea (delegada, con fallback declarado) ---------------

def _tomar_instantanea(ws, etiqueta, usar_modulo=True) -> dict:
    """{'obj', 'mecanismo', 'error'}.

    'mecanismo' es 'modulo' (cognia.multiverso.instantanea), 'fallback'
    (copia integra propia) o 'fallback_tras_error' (el modulo existia y
    reviento). Ese campo viaja al informe: nadie tiene que adivinar que
    mecanismo protegio la corrida.
    """
    err = ""
    if usar_modulo:
        try:
            from cognia.multiverso import instantanea as _inst
            obj = _inst.tomar(str(ws), etiqueta)
            if obj is not None:
                return {"obj": obj, "mecanismo": "modulo", "error": ""}
            err = "tomar() devolvio None"
        except Exception as exc:
            err = "%s: %s" % (type(exc).__name__, exc)
    espejo = Path(str(ws)).parent / (".instantanea_%s_%s" % (
        etiqueta, uuid.uuid4().hex[:8]))
    detalle = copiar_workspace(ws, espejo)
    obj = {"_fallback": True, "ws": str(ws), "espejo": str(espejo),
           "etiqueta": etiqueta, "manifiesto": manifiesto(ws),
           "bytes": detalle["bytes"]}
    mecanismo = "fallback_tras_error" if err else "fallback"
    return {"obj": obj, "mecanismo": mecanismo, "error": err}


def _restaurar_instantanea(snap: dict) -> dict:
    """Devuelve el ws al estado de la instantanea. Nunca lanza."""
    obj = (snap or {}).get("obj")
    if obj is None:
        return {"ok": False, "motivo": "sin instantanea"}
    if isinstance(obj, dict) and obj.get("_fallback"):
        try:
            ws, espejo = Path(obj["ws"]), Path(obj["espejo"])
            if not espejo.is_dir():
                return {"ok": False, "motivo": "espejo perdido"}
            shutil.rmtree(ws, ignore_errors=True)
            shutil.copytree(espejo, ws, dirs_exist_ok=True)
            return {"ok": True, "mecanismo": "fallback"}
        except Exception as exc:
            return {"ok": False,
                    "motivo": "%s: %s" % (type(exc).__name__, exc)}
    try:
        from cognia.multiverso import instantanea as _inst
        res = _inst.restaurar(obj)
        return {"ok": True, "mecanismo": "modulo", "detalle": res}
    except Exception as exc:
        return {"ok": False, "motivo": "%s: %s" % (type(exc).__name__, exc)}


def _limpiar_instantanea(snap: dict) -> int:
    """Borra el espejo del fallback (el modulo gestiona el suyo)."""
    obj = (snap or {}).get("obj")
    if isinstance(obj, dict) and obj.get("_fallback"):
        return _borrar(obj["espejo"])
    return 0


# -- diferencia entre dos workspaces (lo que la rama CAMBIO) --------------

def diferencia_ws(base_ws, rama_ws) -> dict:
    """{'creados','modificados','borrados'} de rama_ws respecto a base_ws.

    Se calcula comparando manifiestos (tamano + sha1). Es valido porque el ws
    real NO se toca mientras las ramas corren: todo delta es obra de la rama.
    """
    a, b = manifiesto(base_ws), manifiesto(rama_ws)
    creados = sorted(k for k in b if k not in a)
    borrados = sorted(k for k in a if k not in b)
    modificados = sorted(k for k in b if k in a and b[k] != a[k])
    return {"creados": creados, "modificados": modificados,
            "borrados": borrados}


# -- clasificacion por REVERSIBILIDAD (delegada, con fallback tosco) ------

# Fallback SOLO para que el modulo corra aislado: patrones de efecto externo
# que no se deshacen con ficheros. La clasificacion buena es la de
# cognia/multiverso/reversibilidad.py; esto es un cinturon, no la respuesta.
_PATRONES_IRREVERSIBLES = (
    "git push", "git tag -d", "gh pr create", "gh release", "npm publish",
    "twine upload", "pip upload", "docker push", "curl -x post",
    "curl -x put", "curl -x delete", "shutdown", "rm -rf /", "aws s3 rm",
    "smtp",
)
_TOOLS_IRREVERSIBLES = (
    "enviar_correo", "send_email", "publicar", "publicar_paquete", "subir",
    "http_post", "borrar_remoto", "desplegar", "deploy", "notificar",
)


def _clasificar_fallback(tool: str, args: str) -> dict:
    t = (tool or "").strip().lower()
    a = (args or "").lower()
    if any(t == x or t.startswith(x) for x in _TOOLS_IRREVERSIBLES):
        return {"cubo": "irreversible_externo", "compensacion": None,
                "motivo": "tool '%s' en la lista dura del fallback" % tool}
    for patron in _PATRONES_IRREVERSIBLES:
        if patron in a:
            return {"cubo": "irreversible_externo", "compensacion": None,
                    "motivo": "argumentos casan '%s'" % patron}
    return {"cubo": "reversible_local", "compensacion": "instantanea",
            "motivo": "sin marca de efecto externo (fallback TOSCO)"}


def clasificar(tool: str, args: str, usar_modulo=True) -> dict:
    """{'cubo','compensacion','clasificador',...}. Nunca lanza.

    'clasificador' dice de donde salio el veredicto ('modulo' o 'fallback'):
    una politica de seguridad que no dice quien la dicto no es auditable.
    """
    if usar_modulo:
        try:
            from cognia.multiverso import reversibilidad as _rev
            veredicto = _rev.clasificar(tool, args)
            if isinstance(veredicto, dict) and veredicto.get("cubo"):
                salida = dict(veredicto)
                salida["clasificador"] = "modulo"
                return salida
        except Exception:
            pass
    salida = _clasificar_fallback(tool, args)
    salida["clasificador"] = "fallback"
    return salida


def es_irreversible(veredicto: dict, estricto=False) -> bool:
    """True si el cubo no se puede especular.

    'desconocido' NO veta por defecto: vetarlo pararia cualquier tool que el
    clasificador no conozca y la rama no avanzaria. Con estricto=True si veta.
    Esto queda DECLARADO porque es exactamente el sitio donde un motor de
    ramas puede mentirse a si mismo.
    """
    cubo = str((veredicto or {}).get("cubo", "")).lower()
    if _MARCA_IRREVERSIBLE in cubo:
        return True
    if estricto and _MARCA_DESCONOCIDO in cubo:
        return True
    return False


# -- LA PUERTA: guardia_de_rama -------------------------------------------

def guardia_de_rama(nombre_tool: str, args: str = "", *, ctx=None,
                    permitir_irreversibles=False, estricto=False,
                    usar_modulo=True):
    """None = la accion puede correr en la rama. String = queda VETADA.

    El string es lo que LEE EL MODELO en lugar del resultado de la tool, igual
    que hace cognia/harness/interceptor.py::antes. Ademas encola la accion en
    ctx['pendientes_irreversibles'] para ejecutarla UNA sola vez, en el mundo
    real, si esta rama gana.

    La cola deduplica por (tool, args): si el modelo reintenta la misma accion
    tres veces, se ejecutara UNA. 'repeticiones' guarda cuantas lo intento (es
    la senal de que el veto le esta confundiendo).
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    veredicto = clasificar(nombre_tool, args, usar_modulo=usar_modulo)
    ledger = ctx.get("ruta_ledger")

    if not es_irreversible(veredicto, estricto=estricto):
        return None

    if permitir_irreversibles:
        # Modo NO especulativo (o el dueno lo autorizo). Se ejecuta, pero se
        # deja constancia: una accion irreversible sin traza es un agujero.
        ctx.setdefault("irreversibles_ejecutadas_en_rama", []).append(
            {"tool": nombre_tool, "args": args, "cubo": veredicto.get("cubo")})
        anotar("irreversible.permitida",
               {"rama": ctx.get("rama"), "corrida": ctx.get("corrida"),
                "tool": nombre_tool, "cubo": veredicto.get("cubo")}, ledger)
        return None

    cola = ctx.setdefault("pendientes_irreversibles", [])
    clave = (str(nombre_tool), str(args))
    for p in cola:
        if (p["tool"], p["args"]) == clave:
            p["repeticiones"] = p.get("repeticiones", 1) + 1
            return _texto_veto(nombre_tool, veredicto, ctx, repetida=True)

    cola.append({
        "id": uuid.uuid4().hex[:12],
        "tool": str(nombre_tool),
        "args": str(args),
        "cubo": veredicto.get("cubo"),
        "compensacion": veredicto.get("compensacion"),
        "clasificador": veredicto.get("clasificador"),
        "motivo": veredicto.get("motivo"),
        "repeticiones": 1,
        "ejecutada": False,
        "ts": time.time(),
    })
    anotar("irreversible.encolada",
           {"rama": ctx.get("rama"), "corrida": ctx.get("corrida"),
            "tool": nombre_tool, "cubo": veredicto.get("cubo"),
            "clasificador": veredicto.get("clasificador")}, ledger)
    return _texto_veto(nombre_tool, veredicto, ctx, repetida=False)


# ── RAMA ACTIVA (cableado, 2026-08-19) ─────────────────────────────────────
# El agente construye su propio ctx dentro de _run_agent_task, asi que el ctx de
# la rama no le llega por parametro. En vez de cablear la rama por dentro del
# bucle, se publica AQUI cual es la rama en curso y el interceptor (el punto
# unico entre el modelo y sus herramientas) consulta la puerta. Es una variable
# de HILO, no global: `paralelo=True` corre ramas en hilos distintos y una
# global haria que el veto de una rama vetara en la otra.
_LOCAL = threading.local()


def activar_rama(ctx: dict, **opciones) -> None:
    """Marca que ESTE hilo esta corriendo dentro de una rama especulativa."""
    _LOCAL.ctx = ctx if isinstance(ctx, dict) else {}
    _LOCAL.opciones = dict(opciones or {})


def desactivar_rama() -> None:
    """Sale de la rama. Idempotente."""
    _LOCAL.ctx = None
    _LOCAL.opciones = {}


def rama_activa():
    """El ctx de la rama en curso en este hilo, o None."""
    return getattr(_LOCAL, "ctx", None)


def veto_activo(nombre_tool: str, args: str = ""):
    """None si no hay rama, o si la accion puede correr. String = VETADA.

    Es lo que llama cognia/harness/interceptor.py::antes. Nunca lanza: un fallo
    del guardia no puede tumbar una tool (devolveria None y dejaria pasar una
    accion irreversible, asi que el except registra y VETA por seguridad).
    """
    ctx = getattr(_LOCAL, "ctx", None)
    if not isinstance(ctx, dict):
        return None
    try:
        return guardia_de_rama(nombre_tool, args, ctx=ctx,
                               **(getattr(_LOCAL, "opciones", None) or {}))
    except Exception as exc:
        return ("BLOQUEADO en la rama especulativa: el guardia de "
                "reversibilidad fallo (%s: %s) y una rama no ejecuta lo que no "
                "puede clasificar." % (type(exc).__name__, exc))


def _texto_veto(nombre_tool, veredicto, ctx, repetida=False) -> str:
    rama = ctx.get("rama") or "especulativa"
    cubo = veredicto.get("cubo")
    cola = "Ya estaba encolada" if repetida else "Queda ENCOLADA"
    return (
        "BLOQUEADO en la rama especulativa '%s': '%s' es IRREVERSIBLE "
        "(cubo=%s). Una rama que puede perder no ejecuta acciones que no se "
        "pueden deshacer. %s y se ejecutara UNA sola vez, en el mundo real, "
        "si esta rama gana. SIGUE con el resto de la tarea dando por hecho "
        "que esa accion tendra exito; no la reintentes ni busques un rodeo "
        "(un rodeo con otra tool tambien se vetara)."
        % (rama, nombre_tool, cubo, cola)
    )


def contar_por_cubo(ramas: list) -> dict:
    """Cuantas acciones vetadas cayeron en cada cubo. Es el numero HOY
    DESCONOCIDO que decide si ramificar es viable en tareas reales."""
    conteo = {}
    for r in ramas or []:
        for p in r.get("pendientes_irreversibles", []):
            cubo = str(p.get("cubo"))
            conteo[cubo] = conteo.get(cubo, 0) + int(p.get("repeticiones", 1))
    return conteo


# -- invocacion flexible de los callables inyectados ----------------------

def _aridad(fn) -> int:
    try:
        params = inspect.signature(fn).parameters.values()
    except Exception:
        return 3
    n = 0
    for p in params:
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            return 3
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                      inspect.Parameter.POSITIONAL_OR_KEYWORD):
            n += 1
    return n


def _invocar_correr(fn, tarea, ws, ctx):
    n = _aridad(fn)
    if n >= 3:
        return fn(tarea, str(ws), ctx)
    if n == 2:
        return fn(tarea, str(ws))
    if n == 1:
        return fn(ctx)
    return fn()


def _invocar_juzgar(fn, ws, resultado):
    n = _aridad(fn)
    if n >= 2:
        return fn(str(ws), resultado)
    if n == 1:
        return fn(str(ws))
    return fn()


def _normalizar_juicio(bruto) -> dict:
    """Todo juicio acaba en {'puntaje': float, 'ok': bool, 'motivo': str}."""
    if bruto is None:
        return {"puntaje": 0.0, "ok": False, "motivo": "juez devolvio None"}
    if isinstance(bruto, bool):
        return {"puntaje": 1.0 if bruto else 0.0, "ok": bool(bruto),
                "motivo": "juez booleano"}
    if isinstance(bruto, (int, float)):
        return {"puntaje": float(bruto), "ok": float(bruto) > 0,
                "motivo": "juez numerico"}
    if isinstance(bruto, dict):
        if "puntaje" in bruto:
            punt = float(bruto.get("puntaje") or 0.0)
        elif "score" in bruto:
            punt = float(bruto.get("score") or 0.0)
        else:
            punt = 1.0 if bruto.get("ok") else 0.0
        ok = bool(bruto.get("ok", punt > 0))
        salida = dict(bruto)
        salida.update({"puntaje": punt, "ok": ok,
                       "motivo": str(bruto.get("motivo", ""))})
        return salida
    return {"puntaje": 0.0, "ok": False,
            "motivo": "juez devolvio %s" % type(bruto).__name__}


def _pasos_de(resultado) -> int:
    if isinstance(resultado, dict):
        for clave in ("pasos", "steps", "n_pasos"):
            if clave in resultado:
                try:
                    return int(resultado.get(clave) or 0)
                except Exception:
                    return 0
    return 0


# -- fusionar / descartar -------------------------------------------------

def fusionar(ganadora: dict, ws_real, *, borrar_faltantes=True,
             ruta_ledger_=None, usar_modulo=True) -> dict:
    """Vuelca los cambios de la rama ganadora sobre el workspace real.

    `ganadora` es el dict de rama del informe (necesita 'ws'). El delta se
    calcula contra el ws real, que NO se ha tocado desde que se sacaron las
    copias: por eso todo delta es obra de la rama.

    Devuelve {'creados','modificados','borrados','bytes','pared_s',
    'mecanismo'} - auditable, no un booleano.
    """
    t0 = time.perf_counter()
    ws_rama = Path(str(ganadora.get("ws")))
    real = Path(str(ws_real))
    if ws_rama.resolve() == real.resolve():
        return {"omitida": True, "motivo": "la rama YA es el ws real (k=1)",
                "creados": [], "modificados": [], "borrados": [],
                "bytes": 0, "pared_s": 0.0, "mecanismo": "ninguno"}

    dif = diferencia_ws(real, ws_rama)
    mecanismo = "manifiestos"

    # Si instantanea.py expone aplicar_diferencia, se usa: es su trabajo y
    # puede tener optimizaciones (delta a nivel de bloque). Si falla, se
    # aplica a mano y se DICE en el informe cual de los dos actuo.
    aplicado = False
    if usar_modulo:
        try:
            from cognia.multiverso import instantanea as _inst
            _inst.aplicar_diferencia(dif, str(ws_rama), str(real))
            aplicado = True
            mecanismo = "instantanea.aplicar_diferencia"
        except Exception as exc:
            mecanismo = "manifiestos (modulo fallo: %s)" % type(exc).__name__

    movidos = 0
    if not aplicado:
        for rel in dif["creados"] + dif["modificados"]:
            org, dst = ws_rama / rel, real / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(org, dst)
            movidos += dst.stat().st_size
        if borrar_faltantes:
            for rel in dif["borrados"]:
                try:
                    (real / rel).unlink()
                except Exception:
                    pass
    else:
        for rel in dif["creados"] + dif["modificados"]:
            try:
                movidos += (real / rel).stat().st_size
            except Exception:
                pass

    salida = {"creados": dif["creados"], "modificados": dif["modificados"],
              "borrados": dif["borrados"] if borrar_faltantes else [],
              "bytes": movidos, "pared_s": round(time.perf_counter() - t0, 4),
              "mecanismo": mecanismo, "omitida": False}
    anotar("fusion", {"rama": ganadora.get("nombre"),
                      "corrida": ganadora.get("corrida"),
                      "ws_real": str(real), "bytes": salida["bytes"],
                      "mecanismo": salida["mecanismo"],
                      "n_creados": len(salida["creados"]),
                      "n_modificados": len(salida["modificados"]),
                      "n_borrados": len(salida["borrados"])}, ruta_ledger_)
    return salida


def descartar(rama: dict, *, ruta_ledger_=None) -> dict:
    """Borra el workspace de una rama perdedora. Explicito y auditable.

    NO borra si la rama corre sobre el ws real (k=1): ese caso se revierte con
    la instantanea, no con rmtree.
    """
    ws = Path(str(rama.get("ws")))
    if rama.get("es_ws_real"):
        salida = {"nombre": rama.get("nombre"), "borrado": False,
                  "motivo": "la rama es el ws real; se revierte por instantanea",
                  "bytes_liberados": 0}
    else:
        liberados = _borrar(ws)
        salida = {"nombre": rama.get("nombre"), "borrado": not ws.exists(),
                  "motivo": "", "bytes_liberados": liberados}
    anotar("descarte", dict({"corrida": rama.get("corrida")}, **salida),
           ruta_ledger_)
    return salida


# -- coste ----------------------------------------------------------------

def coste(informe: dict) -> dict:
    """Pared, pasos y bytes movidos de una corrida completa.

    `factor_vs_una_rama` es la cifra que la literatura de best-of-K omite:
    cuantas veces mas caro salio esto que haber corrido UNA sola trayectoria
    (se compara contra la pared de la ganadora, que es la corrida que se
    habria hecho de todos modos). Sale >1 siempre; si el juez no aporta, ese
    exceso es puro gasto.
    """
    ramas = informe.get("ramas", []) or []
    pared_ramas = sum(float(r.get("pared_s") or 0.0) for r in ramas)
    pared_copias = sum(float((r.get("copia") or {}).get("pared_s") or 0.0)
                       for r in ramas)
    bytes_copiados = sum(int((r.get("copia") or {}).get("bytes") or 0)
                         for r in ramas)
    fusion = informe.get("fusion") or {}
    bytes_fusion = int(fusion.get("bytes") or 0)
    pasos = sum(_pasos_de(r.get("resultado")) for r in ramas)
    total = float(informe.get("pared_total_s") or 0.0)

    ganadora = None
    for r in ramas:
        if r.get("nombre") == informe.get("ganadora"):
            ganadora = r
            break
    pared_ganadora = float((ganadora or {}).get("pared_s") or 0.0)
    factor = round(total / pared_ganadora, 2) if pared_ganadora > 0 else None

    return {
        "pared_total_s": round(total, 4),
        "pared_ramas_s": round(pared_ramas, 4),
        "pared_copias_s": round(pared_copias, 4),
        "pared_instantanea_s": round(
            float((informe.get("instantanea") or {}).get("pared_s") or 0.0), 4),
        "pared_fusion_s": round(float(fusion.get("pared_s") or 0.0), 4),
        "overhead_s": round(max(0.0, total - pared_ramas), 4),
        "pasos": pasos,
        "bytes_copiados": bytes_copiados,
        "bytes_fusionados": bytes_fusion,
        "bytes_movidos": bytes_copiados + bytes_fusion,
        "ramas": len(ramas),
        "pared_ganadora_s": round(pared_ganadora, 4),
        "factor_vs_una_rama": factor,
        "irreversibles_por_cubo": contar_por_cubo(ramas),
    }


# -- el motor -------------------------------------------------------------

def ramificar(tarea, ws_real, k, correr_rama_fn, juzgar_fn, *,
              permitir_irreversibles=False, ejecutar_irreversible_fn=None,
              raiz_ramas=None, ruta_ledger_=None, paralelo=False,
              estricto=False, restaurar_si_falla=True, usar_modulos=True,
              conservar_perdedoras=False) -> dict:
    """Corre K trayectorias de la misma tarea y fusiona SOLO la ganadora.

    correr_rama_fn: inyectado (en produccion, el agente). Se le llama segun su
        aridad: (tarea, ws, ctx), (tarea, ws) o (ctx). El ctx trae 'guardia'
        (la puerta de irreversibles), 'rama', 'ws' y
        'pendientes_irreversibles'.
    juzgar_fn: inyectado. (ws, resultado) o (ws). Devuelve bool, numero o dict
        {'ok','puntaje','motivo'}. POSTCONDICIONES VERIFICADAS: que lea el
        disco, no el texto del modelo.
    paralelo: hilos. DEFAULT False porque esta maquina tiene UN slot de
        llama-server y N agentes contra un slot se serializan igual (ver
        cabecera del modulo). Con correr_rama_fn de CPU puro si acelera.

    Devuelve el informe completo (ver `coste` para el resumen economico).
    """
    t0 = time.perf_counter()
    real = Path(str(ws_real))
    if not real.is_dir():
        raise ValueError("ws_real no es un directorio: %s" % real)
    try:
        k = int(k)
    except Exception:
        raise ValueError("k invalido: %r" % (k,))
    if k < 1:
        raise ValueError("k tiene que ser >= 1, llego %s" % k)

    corrida = uuid.uuid4().hex[:12]
    modo = "directo" if k == 1 else "ramificado"
    raiz = Path(str(raiz_ramas)) if raiz_ramas else (
        real.parent / (".ramas_%s" % corrida))

    anotar("ramificar.inicio",
           {"corrida": corrida, "tarea": str(tarea)[:200], "k": k,
            "modo": modo, "ws_real": str(real), "paralelo": bool(paralelo),
            "permitir_irreversibles": bool(permitir_irreversibles)},
           ruta_ledger_)

    # 1) INSTANTANEA del ws real: la red de seguridad. En modo directo es lo
    #    unico que permite volver atras; en modo ramificado es el testigo de
    #    que el ws real no se movio.
    t_snap = time.perf_counter()
    snap = _tomar_instantanea(real, "base_%s" % corrida, usar_modulo=usar_modulos)
    snap["pared_s"] = round(time.perf_counter() - t_snap, 4)
    anotar("instantanea.tomada",
           {"corrida": corrida, "mecanismo": snap["mecanismo"],
            "error": snap.get("error", ""), "pared_s": snap["pared_s"]},
           ruta_ledger_)

    # 2) WORKSPACES-RAMA
    ramas = []
    for i in range(k):
        nombre = "rama_%d" % i
        if modo == "directo":
            # k=1 degrada a "correr normal": ni copia ni fusion. El unico
            # coste extra es la instantanea (la red de seguridad).
            ramas.append({"nombre": nombre, "indice": i, "ws": str(real),
                          "es_ws_real": True, "corrida": corrida,
                          "copia": {"bytes": 0, "ficheros": 0, "pared_s": 0.0},
                          "estado": "pendiente", "error": "",
                          "pendientes_irreversibles": []})
            continue
        ws_i = raiz / nombre
        try:
            copia = copiar_workspace(real, ws_i)
            estado, err = "pendiente", ""
        except Exception as exc:
            copia = {"bytes": 0, "ficheros": 0, "pared_s": 0.0}
            estado = "error_copia"
            err = "%s: %s" % (type(exc).__name__, exc)
        ramas.append({"nombre": nombre, "indice": i, "ws": str(ws_i),
                      "es_ws_real": False, "corrida": corrida, "copia": copia,
                      "estado": estado, "error": err,
                      "pendientes_irreversibles": []})
        anotar("rama.creada", {"corrida": corrida, "rama": nombre,
                               "ws": str(ws_i), "estado": estado,
                               "bytes": copia["bytes"],
                               "pared_s": copia["pared_s"]}, ruta_ledger_)

    # 3) CORRER
    def _correr_una(rama):
        if rama["estado"] == "error_copia":
            rama["pared_s"] = 0.0
            rama["resultado"] = None
            rama["pasos"] = 0
            return
        ctx = {
            "rama": rama["nombre"], "corrida": corrida, "tarea": tarea,
            "ws": rama["ws"], "workspace": rama["ws"],
            "ruta_ledger": ruta_ledger_,
            "pendientes_irreversibles": rama["pendientes_irreversibles"],
            "especulativa": modo == "ramificado",
        }
        # La puerta que el ctx de la rama usa para VETAR. Firma identica a la
        # del interceptor del repo: (nombre_tool, args) -> str|None.
        ctx["guardia"] = lambda tool, args="": guardia_de_rama(
            tool, args, ctx=ctx,
            permitir_irreversibles=permitir_irreversibles,
            estricto=estricto, usar_modulo=usar_modulos)
        ctx["guardia_de_rama"] = ctx["guardia"]
        rama["ctx"] = ctx
        t = time.perf_counter()
        try:
            rama["resultado"] = _invocar_correr(
                correr_rama_fn, tarea, rama["ws"], ctx)
            rama["estado"] = "corrida"
            rama["error"] = ""
        except Exception as exc:
            # Una rama que revienta NO contamina: su ws es una copia y se
            # descartara entera. Solo se guarda el motivo.
            rama["resultado"] = None
            rama["estado"] = "error"
            rama["error"] = "%s: %s" % (type(exc).__name__, exc)
            rama["traza"] = traceback.format_exc()[-1200:]
        rama["pared_s"] = round(time.perf_counter() - t, 4)
        rama["pasos"] = _pasos_de(rama.get("resultado"))
        anotar("rama.corrida",
               {"corrida": corrida, "rama": rama["nombre"],
                "estado": rama["estado"], "pared_s": rama["pared_s"],
                "pasos": rama["pasos"], "error": rama.get("error", ""),
                "n_vetadas": len(rama["pendientes_irreversibles"])},
               ruta_ledger_)

    if paralelo and len(ramas) > 1:
        import threading
        hilos = [threading.Thread(target=_correr_una, args=(r,))
                 for r in ramas]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
    else:
        for rama in ramas:
            _correr_una(rama)

    # 4) JUZGAR (postcondiciones sobre el DISCO de cada rama)
    for rama in ramas:
        if rama["estado"] != "corrida":
            rama["juicio"] = {"puntaje": float("-inf"), "ok": False,
                              "motivo": "rama en estado %s" % rama["estado"]}
            continue
        try:
            rama["juicio"] = _normalizar_juicio(
                _invocar_juzgar(juzgar_fn, rama["ws"], rama.get("resultado")))
        except Exception as exc:
            rama["juicio"] = {
                "puntaje": float("-inf"), "ok": False,
                "motivo": "juez reviento: %s: %s" % (type(exc).__name__, exc)}
        anotar("rama.juzgada",
               {"corrida": corrida, "rama": rama["nombre"],
                "puntaje": rama["juicio"]["puntaje"],
                "ok": rama["juicio"]["ok"],
                "motivo": rama["juicio"].get("motivo", "")}, ruta_ledger_)

    # 5) GANADORA: mayor puntaje entre las que el juez aprueba. Empate -> el
    #    indice mas bajo (determinista y declarado; no al azar).
    candidatas = [r for r in ramas
                  if r["estado"] == "corrida" and r["juicio"]["ok"]]
    ganadora = None
    if candidatas:
        mejor = max(c["juicio"]["puntaje"] for c in candidatas)
        empatadas = [c for c in candidatas if c["juicio"]["puntaje"] == mejor]
        ganadora = min(empatadas, key=lambda c: c["indice"])
        razon = ("puntaje %s, mejor de %d aprobadas de %d%s"
                 % (mejor, len(candidatas), len(ramas),
                    "; empate resuelto por indice" if len(empatadas) > 1
                    else ""))
    else:
        razon = "ninguna rama paso el juez: el ws real NO se toca"

    # 6) FUSION / DESCARTE
    fusion = {"omitida": True, "motivo": razon, "bytes": 0, "pared_s": 0.0,
              "creados": [], "modificados": [], "borrados": []}
    descartadas = []
    restauracion = None

    if ganadora is not None and modo == "ramificado":
        fusion = fusionar(ganadora, real, ruta_ledger_=ruta_ledger_,
                          usar_modulo=usar_modulos)
        ganadora["estado"] = "fusionada"
    elif ganadora is not None and modo == "directo":
        fusion = {"omitida": True,
                  "motivo": "k=1: la rama ES el ws real, no hay que fusionar",
                  "bytes": 0, "pared_s": 0.0, "creados": [],
                  "modificados": [], "borrados": []}
        ganadora["estado"] = "aceptada_en_sitio"
    elif modo == "directo" and restaurar_si_falla:
        # k=1 y el juez la rechaza: la instantanea es lo unico que salva el ws.
        restauracion = _restaurar_instantanea(snap)
        anotar("restauracion", dict({"corrida": corrida}, **restauracion),
               ruta_ledger_)

    for rama in ramas:
        if ganadora is not None and rama is ganadora:
            continue
        if conservar_perdedoras or rama.get("es_ws_real"):
            descartadas.append(
                {"nombre": rama["nombre"], "borrado": False,
                 "motivo": ("conservada por peticion" if conservar_perdedoras
                            else "es el ws real"),
                 "bytes_liberados": 0})
            continue
        det = descartar(rama, ruta_ledger_=ruta_ledger_)
        rama["estado"] = "descartada"
        descartadas.append(det)

    # 7) IRREVERSIBLES DE LA GANADORA: se ejecutan UNA sola vez, aqui, en el
    #    mundo real. Las de las perdedoras se tiran (nunca ocurrieron).
    ejecutadas = []
    pendientes_sin_ejecutar = []
    if ganadora is not None:
        for p in ganadora["pendientes_irreversibles"]:
            if p.get("ejecutada"):
                continue
            if ejecutar_irreversible_fn is None:
                pendientes_sin_ejecutar.append(dict(p))
                continue
            t = time.perf_counter()
            # Marcada ANTES de llamar: si el ejecutor revienta a medias, la
            # accion NO se repite. "Una sola vez" pesa mas que "seguro que se
            # hizo": repetir un push o un correo no tiene vuelta atras.
            p["ejecutada"] = True
            try:
                res = ejecutar_irreversible_fn(p["tool"], p["args"], p)
                ok, err = True, ""
            except Exception as exc:
                res, ok = None, False
                err = "%s: %s" % (type(exc).__name__, exc)
            p["resultado"] = res
            p["ok"] = ok
            p["error"] = err
            fila = {"id": p["id"], "tool": p["tool"], "cubo": p["cubo"],
                    "ok": ok, "error": err, "repeticiones": p["repeticiones"],
                    "pared_s": round(time.perf_counter() - t, 4)}
            ejecutadas.append(fila)
            anotar("irreversible.ejecutada",
                   dict({"corrida": corrida, "rama": ganadora["nombre"]},
                        **fila), ruta_ledger_)

    descartadas_pendientes = sum(
        len(r["pendientes_irreversibles"]) for r in ramas
        if ganadora is None or r is not ganadora)

    # 8) LIMPIEZA: el ws de la ganadora (ya fusionado), la raiz de ramas y el
    #    espejo de la instantanea propia.
    bytes_liberados = sum(int(d.get("bytes_liberados") or 0)
                          for d in descartadas)
    if modo == "ramificado" and ganadora is not None and not conservar_perdedoras:
        bytes_liberados += _borrar(ganadora["ws"])
    if modo == "ramificado" and not conservar_perdedoras:
        try:
            if raiz.is_dir() and not any(raiz.iterdir()):
                raiz.rmdir()
        except Exception:
            pass
    _limpiar_instantanea(snap)

    for rama in ramas:
        rama.pop("ctx", None)

    informe = {
        "corrida": corrida,
        "tarea": tarea,
        "ws_real": str(real),
        "k": k,
        "modo": modo,
        "paralelo": bool(paralelo),
        "instantanea": {"mecanismo": snap["mecanismo"],
                        "error": snap.get("error", ""),
                        "pared_s": snap["pared_s"]},
        "ramas": ramas,
        "ganadora": ganadora["nombre"] if ganadora else None,
        "razon": razon,
        "fusion": fusion,
        "descartadas": descartadas,
        "restauracion": restauracion,
        "irreversibles_ejecutadas": ejecutadas,
        "irreversibles_pendientes_sin_ejecutar": pendientes_sin_ejecutar,
        "irreversibles_descartadas": descartadas_pendientes,
        "bytes_liberados": bytes_liberados,
        "ledger": str(ruta_ledger(ruta_ledger_)),
        "pared_total_s": round(time.perf_counter() - t0, 4),
    }
    if pendientes_sin_ejecutar:
        informe["aviso"] = (
            "%d accion(es) irreversible(s) de la ganadora NO se ejecutaron: "
            "no se inyecto ejecutar_irreversible_fn. El mundo exterior NO "
            "refleja esta corrida." % len(pendientes_sin_ejecutar))
    informe["coste"] = coste(informe)
    anotar("ramificar.fin",
           {"corrida": corrida, "ganadora": informe["ganadora"],
            "razon": razon, "coste": informe["coste"]}, ruta_ledger_)
    return informe
