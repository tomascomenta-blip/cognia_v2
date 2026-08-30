r"""
cognia/agent/flows.py — flujos estilo n8n (DAG de tools) para Cognia
====================================================================
Mandato del dueño (2026-07-13): programar flujos estilo n8n, manual o
pidiéndole a Cognia que los organice. La investigación (AGENCIA_RESEARCH):
formato Node-RED `{id, type, wires}` (fácil de escribir/leer para el 3B) que
carga directo a un DAG; features de OpenFlow (retries, timeout, condicional)
que además curan cuelgues que el agente ya sufrió.

Un FLUJO = grafo dirigido acíclico de NODOS; cada nodo ejecuta una TOOL del
registro (cognia.agent.tools) con sus args, y sus salidas fluyen a los nodos
siguientes (wires). Convención n8n: la salida de un nodo se puede interpolar
en los args del siguiente con `{{id}}` (el RESULTADO del nodo `id`).

Modelo de datos (JSON serializable):
  {"nombre": str,
   "nodos": [{"id": str, "tool": str, "args": str, "wires": [ids...],
              "reintentos": int?, "timeout_s": float?, "saltar_si": str?}]}

Determinista y plano (sin clases de más): valida (DAG, tools existen), ordena
topológicamente y ejecuta. El "Cognia organiza el flujo" (desde lenguaje
natural) se apoya en el planner existente (from_plan) — cero LLM nuevo acá.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time as _time
from typing import Callable


class FlowError(ValueError):
    pass


def validar(flujo: dict, tool_existe: Callable[[str], bool] | None = None) -> list:
    """Valida estructura + DAG. Devuelve el orden topológico de ids.
    Levanta FlowError con mensaje claro (ciclo, id duplicado, wire colgado,
    args que no son texto, tool inexistente si se pasa tool_existe).

    ARGS TIENE QUE SER TEXTO (2026-08-29). Antes esto no se miraba y el
    agujero se pagaba dos veces: `_interpolar` recibe los args de un nodo y
    el lienzo (`flow_view`) los recorta, o sea que un dict ahí no es un
    flujo raro sino un flujo ROTO — se guardaba con 200 y luego el editor
    devolvía 404 al releerlo (`KeyError: slice(None, 46, None)`), con el
    flujo ya escrito en disco e inabrible. Se aceptan str, los escalares
    convertibles (int/float/bool) y la ausencia; se rechazan dict, lista y
    cualquier objeto, diciendo el nodo y el tipo que llegó. La UI propia no
    los genera (arma el string con `armar_args`) y `flujo_ia._sanear` ya
    pasaba los suyos por str(): quien los cuela es /api/guardar, un import
    de la flujoteca o un flujo tecleado a mano."""
    nodos = flujo.get("nodos")
    if not isinstance(nodos, list) or not nodos:
        raise FlowError("el flujo no tiene 'nodos'")
    ids = [n.get("id") for n in nodos]
    if any(not i for i in ids):
        raise FlowError("hay nodos sin 'id'")
    if len(set(ids)) != len(ids):
        raise FlowError("ids de nodo duplicados")
    idset = set(ids)
    for n in nodos:
        if not n.get("tool"):
            raise FlowError(f"nodo '{n['id']}' sin 'tool'")
        if tool_existe is not None and not tool_existe(n["tool"]):
            raise FlowError(f"nodo '{n['id']}': tool '{n['tool']}' no existe")
        args = n.get("args")
        if args is not None and not isinstance(args, (str, int, float)):
            raise FlowError(
                f"nodo '{n['id']}': 'args' tiene que ser texto, llego "
                f"{type(args).__name__} ({str(args)[:60]}). Los argumentos de "
                f"una tool van en UN string (ej: 'informe.md | {{{{paso1}}}}')")
        for w in (n.get("wires") or []):
            if w not in idset:
                raise FlowError(f"nodo '{n['id']}': wire a id inexistente '{w}'")
    # orden topológico (Kahn) — detecta ciclos
    hijos = {i: list(n.get("wires") or []) for i, n in zip(ids, nodos)}
    indeg = {i: 0 for i in ids}
    for i in ids:
        for w in hijos[i]:
            indeg[w] += 1
    cola = [i for i in ids if indeg[i] == 0]
    orden = []
    while cola:
        i = cola.pop(0)
        orden.append(i)
        for w in hijos[i]:
            indeg[w] -= 1
            if indeg[w] == 0:
                cola.append(w)
    if len(orden) != len(ids):
        raise FlowError("el flujo tiene un CICLO (no es un DAG)")
    return orden


_INTERP = re.compile(r"\{\{\s*([A-Za-z0-9_\-]+)\s*\}\}")

# Las dos tools de ENTRADA del flujo (PEDIDO 3). El modo va en el NOMBRE de la
# tool, no en un campo nuevo: `tool` esta en la whitelist de
# `flujo_ia.sanear_flujo` y en la tupla de 7 campos de `flujoteca.comparar`,
# asi que sobrevive a una edicion conversacional y SALE en el diff.
TOOLS_ENTRADA = ("prompt", "prompt_fijo")

# Tope normal de cada sustitucion de `{{id}}`, y el tope AMPLIADO para las
# salidas de los nodos de entrada: el objetivo que teclea el dueno no puede
# truncarse en silencio a 2000 chars (PLAN2, PEDIDO 3).
_TOPE_INTERP = 2000
_TOPE_INTERP_CRUDO = 8000


def _interpolar(args, salidas: dict, crudos=()) -> str:
    """Reemplaza {{id}} por el RESULTADO (recortado) del nodo id ya ejecutado.

    `crudos` es el conjunto de ids cuya salida se recorta a 8000 en vez de
    2000 (los nodos `prompt`/`prompt_fijo`, ver TOOLS_ENTRADA).

    str() sobre los args: `validar` acepta los escalares convertibles
    (args: 3), y `re.sub` sobre un int levanta 'expected string or
    bytes-like object' en mitad de la ejecucion — el sitio mas caro para
    enterarse."""
    return _interpolar_con_faltantes(args, salidas, crudos)[0]


def _interpolar_con_faltantes(args, salidas: dict, crudos=()) -> tuple:
    """`(texto, [marcadores_sin_salida])`. El segundo elemento son los
    `{{loquesea}}` que quedaron en HUECO porque no hay ningun nodo (ni
    variable sembrada) con ese id: hoy se sustituyen por "" en silencio y el
    flujo sigue, y eso es exactamente lo que hace que un flujo "no entregue
    nada" sin decir por que. No se endurece a FlowError en esta ola (romperia
    flujos vivos que dependen del hueco): se REPORTA."""
    faltan: list = []

    def _sub(m):
        nid = m.group(1)
        if nid not in salidas:
            if nid not in faltan:
                faltan.append(nid)
            return ""
        tope = _TOPE_INTERP_CRUDO if nid in crudos else _TOPE_INTERP
        return str(salidas.get(nid, ""))[:tope]

    return _INTERP.sub(_sub, str(args) if args else ""), faltan


# De que nodos se deduce la lista de FICHEROS entregados, y cual de sus
# argumentos posicionales nombra la ruta PRODUCIDA (indice 0-based).
# `copiar_archivo`/`mover_archivo` llevan el 1 y no el 0 a proposito: su
# primer posicional es el ORIGEN, que ya existia; lo que el flujo produjo es
# el destino. Decir "produje src" seria mentir por seguir la letra.
TOOLS_ESCRITURA = {
    "escribir_archivo": 0,
    "apendar_archivo": 0,
    "editar_archivo": 0,
    "crear_directorio": 0,
    "copiar_archivo": 1,
    "mover_archivo": 1,
}


def _fichero_de_nodo(tool, args: str) -> str:
    """La ruta que produjo un nodo de escritura, del `args` YA INTERPOLADO.
    Determinista y sin tocar el disco: se parte por el separador oficial
    (' | ', el mismo `re.split(r"\\s*\\|\\s*")` que usan las tools) y se toma
    el posicional que declara TOOLS_ESCRITURA. Sin ese posicional -> ""."""
    idx = TOOLS_ESCRITURA.get(tool)
    if idx is None:
        return ""
    partes = re.split(r"\s*\|\s*", str(args or ""))
    if len(partes) <= idx:
        return ""
    return partes[idx].strip().strip("\"'")


# ══════════════════════════════════════════════════════════════════════
# DENEGACIONES DEL GATE DE PERMISOS — reconocidas en el MOTOR, sin regex
# ══════════════════════════════════════════════════════════════════════
# EL FALLO QUE ESTO ARREGLA (revision adversarial 2026-08-30, REPRODUCIDO).
# Un nodo `ejecutar` que el gate DENIEGA devuelve
#     "RESULTADO ejecutar: no confirmado por el usuario (lleva codigo en
#      linea)."
# — texto sin la palabra ERROR. La heuristica `\bERROR\b` de `_correr_nodo`
# lo daba por bueno, el nodo no entraba en `errores`, la fila salia VERDE, el
# retorno decia `ok=True` / "0 con error" y, por ser el ultimo del orden
# topologico, SU TEXTO se convertia en el ENTREGABLE. `ok=True` significaba
# "no hizo nada, pero bien". Y por el camino del AGENTE no habia ni el aviso:
# el motivo se imprime por consola (`_denegar_sin_humano`) pero NO viaja en el
# valor de retorno, asi que lo que LEE EL MODELO no tenia una sola senal de
# que el gate freno la unica accion del flujo.
#
# POR QUE NO UN REGEX SOBRE LA SALIDA. Es lo que hace `cli._RE_FLUJO_DENEGADO`
# ("confirma|cancelad|denegad|bloquead|...") y produce FALSOS POSITIVOS sobre
# el nodo `prompt`, que devuelve el texto CRUDO del dueno y no pasa por ningun
# `confirm`: "/flujoteca ejecutar sano confirma los datos del informe" acusaba
# de denegado un flujo perfectamente sano (MEDIDO). Con la primera falsa
# alarma el dueno aprende a ignorar la linea que si importa.
#
# LAS DOS SENALES ESTRUCTURALES QUE SI EXISTEN, las dos escritas por el propio
# gate en `cognia/agent/tools.py`:
#
#   (A) EL CANAL DE CONFIRMACION DIJO QUE NO. El gate deniega llamando a
#       `ctx["confirm"](motivo, detalle)` y leyendo False:
#       `sentinel.evaluar_shell` (sentinel.py:3310-3316) para `ejecutar` /
#       `ejecutar_fondo` / `git`, y `borrar_archivo` (tools.py:1585 y 1611)
#       para el borrado fuera del workspace y el borrado masivo. Envolver ese
#       callable es la deteccion EXACTA: no mira ni un caracter del texto de
#       salida, y un nodo `prompt` jamas puede dispararla porque nunca lo
#       llama.
#
#   (B) `run_tool` YA PUBLICA SU VEREDICTO. tools.run_tool escribe
#       `ctx["_ultimo_ok"]` y `ctx["_ultimo_exit"]` en cada llamada (P0-1):
#       para un comando denegado, `_shell` deja `_exit=None` ANTES del gate
#       (tools.py:2127) y run_tool baja el ok a False aunque el texto no diga
#       ERROR. `flows` se calculaba el suyo con la MISMA regex que P0-1 vino a
#       sustituir. Honrar `_ultimo_ok` cierra el agujero incluso cuando NO hay
#       canal de confirmacion en la sesion (default-deny mudo).
#
# El envoltorio NO se instala si el ctx no trae `confirm` callable: sentinel y
# `borrar_archivo` distinguen "el dueno dijo que no" de "no hay canal" por ese
# mismo `callable(...)`, y falsear el canal cambiaria el mensaje que lee el
# modelo. Ese caso lo cubre la senal (B).
#
# LO QUE ESTO NO CUBRE, dicho para que no se cuente por cubierto: sin canal de
# confirmacion en el ctx, una denegacion de `ejecutar_fondo` o de
# `borrar_archivo` no la ve ninguna de las dos senales, porque esas dos no
# pasan por `_marcar_exit(ctx, None)` y run_tool no baja su ok. Con canal --
# que es lo que arma `cli._ctx_agente` -- la (A) las coge. Cerrarlo del todo
# pide una marca en tools.py, y eso es de otro dueno.

_DENEGACIONES = threading.local()


def _anotar_denegacion(motivo: str, detalle: str = "",
                       registro: list | None = None) -> None:
    """Deja constancia de una denegacion por las DOS vias, porque ninguna
    sola vale:

      - el marco THREAD-LOCAL del nodo que esta corriendo, que es la unica
        que atribuye bien cuando varios hermanos corren a la vez;
      - el `registro` del propio envoltorio, que vive en el ctx y por tanto
        es el MISMO objeto en cualquier hilo. Hace falta porque `run_tool`
        corre la tool bajo el deadline por tool (harness/timeout_tool) EN
        OTRO HILO: alli el marco no existe y la denegacion se perdia
        (medido en el camino real del agente).
    """
    txt = f"{motivo}: {detalle}" if detalle else str(motivo)
    txt = " ".join(str(txt).split())[:200]
    pila = getattr(_DENEGACIONES, "pila", None)
    if pila is not None and txt not in pila:
        pila.append(txt)
    if registro is not None:
        registro.append(txt)


class _ConfirmVigilado:
    """Envuelve `ctx['confirm']` para ENTERARSE de las denegaciones.

    No decide nada: delega en el confirm real y devuelve exactamente lo que
    el devuelva. Lo unico que anade es dejar constancia cuando la respuesta
    es NO, para que el motor pueda decir que nodo se quedo sin hacer.
    Un confirm que revienta cuenta como denegacion (es lo que ya hacia
    `sentinel.evaluar_shell`: `except Exception: pass` y a denegar)."""

    __slots__ = ("_original", "registro")

    def __init__(self, original):
        self._original = original
        self.registro: list = []

    def __call__(self, motivo="", detalle="", *a, **k):
        try:
            ok = bool(self._original(motivo, detalle, *a, **k))
        except TypeError:
            ok = bool(self._original(motivo, detalle))
        except Exception:
            _anotar_denegacion(motivo, detalle, self.registro)
            raise
        if not ok:
            _anotar_denegacion(motivo, detalle, self.registro)
        return ok


def _ctx_vigilado(ctx: dict) -> dict:
    """Copia SUPERFICIAL del ctx con el `confirm` envuelto (idempotente).

    Copia y no mutacion: el ctx es del llamador y un envoltorio pegado para
    siempre sobreviviria al flujo. Superficial a proposito, como
    `_t_ejecutar_flujo` con `ctx_hijo`: `agent_state`, `working_memory` y
    `print_fn` se comparten porque son el estado vivo de la sesion."""
    if not isinstance(ctx, dict):
        return ctx
    confirm = ctx.get("confirm")
    if not callable(confirm) or isinstance(confirm, _ConfirmVigilado):
        return ctx
    nuevo = dict(ctx)
    nuevo["confirm"] = _ConfirmVigilado(confirm)
    return nuevo


def _clave_cache(tool: str, args: str) -> str:
    """Clave de cache de un nodo: sha256 de tool + args YA interpolados.
    El separador NUL evita colisiones por concatenacion ambigua (tool 'ab'
    con args 'c' vs tool 'a' con args 'bc')."""
    return hashlib.sha256(f"{tool}\x00{args}".encode("utf-8")).hexdigest()


def _correr_nodo(n: dict, args: str, ctx: dict, run_tool, log,
                 ctx_compartido: bool = False) -> tuple:
    """Corre UN nodo (reintentos + timeout). Devuelve (res, ok, motivos),
    donde `motivos` es la lista (vacia lo normal) de por que el GATE DE
    PERMISOS denego este nodo -- ver el bloque "DENEGACIONES DEL GATE".
    Extraido de ejecutar() sin cambiar semantica para que el despacho
    paralelo reuse exactamente el mismo camino que el secuencial.

    LOS NODOS DE ENTRADA NO PASAN POR LA HEURISTICA `\\bERROR\\b` (PLAN2 5.6).
    Esa heuristica mira los primeros 120 chars del texto devuelto, y las tools
    `prompt`/`prompt_fijo` devuelven el texto CRUDO del dueno: un objetivo que
    empiece "arregla el ERROR de la web" marcaba el nodo de entrada como
    fallido y el flujo entero salia con `ok=False` sin que nada hubiera
    fallado. Para ellas solo cuenta el fallo DURO (excepcion o timeout)."""
    nid = n["id"]
    intentos = max(1, int(n.get("reintentos", 0)) + 1)
    timeout = n.get("timeout_s")
    crudo = n.get("tool") in TOOLS_ENTRADA
    res, ok, motivos = "", False, []
    for k in range(intentos):
        t0 = _time.time()
        duro = False
        motivos = []            # por INTENTO: el ultimo manda
        # MARCO DE DENEGACIONES del hilo (senal A). Se apila y se
        # restaura: un nodo `ejecutar_flujo` corre un sub-flujo EN ESTE
        # MISMO HILO y su `_correr_nodo` anidado abre su propio marco;
        # sin la pila, el marco del padre se perderia. Al cerrar, lo del
        # hijo se HEREDA al padre: si al sub-flujo le denegaron su unica
        # accion, el nodo que lo invoco tampoco hizo nada.
        previo = getattr(_DENEGACIONES, "pila", None)
        _DENEGACIONES.pila = []
        _vig = ctx.get("confirm") if isinstance(ctx, dict) else None
        _vig = _vig if isinstance(_vig, _ConfirmVigilado) else None
        _corte = len(_vig.registro) if _vig is not None else 0
        # El veredicto publicado por run_tool se limpia ANTES de llamar:
        # el real lo reescribe siempre, pero un run_tool inyectado no lo
        # toca y este nodo heredaria el del anterior -- el "evento
        # sellado con el reloj rancio" otra vez. Ausencia != False.
        if isinstance(ctx, dict):
            ctx.pop("_ultimo_ok", None)
            ctx.pop("_ultimo_exit", None)
        try:
            try:
                res = run_tool(n["tool"], args, ctx)
            except Exception as exc:
                res = f"RESULTADO {n['tool']} ERROR: {exc}"
                duro = True
        finally:
            mias = list(getattr(_DENEGACIONES, "pila", None) or [])
            if not mias and _vig is not None and not ctx_compartido:
                # el marco del hilo no vio nada porque la tool corrio en
                # otro hilo (deadline por tool): el registro del
                # envoltorio si. En paralelo NO se usa: ahi los hermanos
                # comparten ctx y con el, el envoltorio.
                mias = list(_vig.registro[_corte:])
            _DENEGACIONES.pila = previo
            if previo is not None:
                for _m in mias:
                    if _m not in previo:
                        previo.append(_m)
        dt = _time.time() - t0
        if timeout is not None and dt > float(timeout):
            res = (f"RESULTADO {n['tool']} ERROR: timeout "
                   f"({dt:.1f}s > {timeout}s)")
            duro = True
        ok = (not duro) if crudo else not re.search(r"\bERROR\b", res[:120])
        # SENAL (B): el veredicto que `run_tool` YA calculo y publico en
        # el ctx (tools.py, P0-1). Manda sobre la heuristica de texto y
        # solo en UNA direccion -- puede tumbar un ok, nunca resucitarlo,
        # igual que hace el exit real dentro de run_tool. Asi un comando
        # BLOQUEADO o no confirmado (texto SIN la palabra ERROR) deja de
        # contar como exito. Los nodos de ENTRADA quedan fuera: su texto
        # es el del dueno, y un objetivo que diga "arregla el ERROR de la
        # web" hace que run_tool devuelva ok=False sin que nada haya
        # fallado (seria la regresion del arreglo de hoy, dos lineas
        # arriba).
        # CARRERA: en paralelo los hermanos del nivel COMPARTEN el ctx y
        # `_ultimo_ok` de uno lo puede leer el otro. Ahi la senal (B) se
        # apaga entera; la (A) es thread-local y sigue siendo exacta.
        _leible = isinstance(ctx, dict) and not ctx_compartido
        _ult_ok = ctx.get("_ultimo_ok") if _leible else None
        _ult_exit = ctx.get("_ultimo_exit") if _leible else 0
        if not crudo:
            if mias:
                # (A) EL CANAL DIJO QUE NO. Tumba el ok POR SI SOLA: el
                # texto de una denegacion no lleva la palabra ERROR (ese
                # es justo el defecto), asi que si esta senal no bajara
                # el ok, el nodo seguiria saliendo verde y la rama que
                # apunta el motivo ni se miraria.
                ok = False
                motivos = list(mias)
            else:
                if ok and _ult_ok is False:
                    ok = False
                if (not ok and _ult_ok is False and _ult_exit is None
                        and not re.search(r"\bERROR\b", str(res)[:120])):
                    # (B) sin canal de confirmacion no hay a quien
                    # preguntar y el gate deniega por default-deny.
                    # run_tool solo baja el ok de un texto SANO cuando la
                    # tool paso por el shell y no hubo exit real, que es
                    # exactamente "no llego a ejecutarse".
                    _sin_canal = not callable(ctx.get("confirm"))
                    motivos = ["%s: el gate de permisos no dejo correr "
                               "la accion%s" % (
                                   n["tool"],
                                   " (esta sesion no tiene canal de "
                                   "confirmacion)" if _sin_canal else "")]
        if log:
            _et = "ok" if ok else ("DENEGADO" if motivos else "error")
            log(f"[flujo] {nid} ({n['tool']}) intento {k+1}/{intentos}: "
                f"{_et}")
        if ok:
            break
    return res, ok, motivos


def asegurar_prompt(flujo: dict) -> dict:
    """Devuelve el flujo con un nodo de ENTRADA (`prompt`/`prompt_fijo`) al
    inicio, anadiendolo si no lo tiene. Idempotente. Funcion pura: no muta el
    flujo que recibe.

    CONTRATO (PLAN2, PEDIDO 3 "El nodo PROMPT obligatorio al inicio"):
      El modo va en el NOMBRE DE LA TOOL, no en un campo nuevo:
        {"id": "prompt", "tool": "prompt",      "args": "<texto por defecto>",
         "wires": ["<raices previas>"]}
        {"id": "prompt", "tool": "prompt_fijo", "args": "<la constante>",
         "wires": ["<raices previas>"]}
      - `prompt` = VARIABLE (el argumento del CLI la pisa).
      - `prompt_fijo` = CONSTANTE (ignora el argumento y avisa).
      Razon (trampas medidas): `tool` esta en la whitelist de
      `flujo_ia.sanear_flujo`, asi que sobrevive a una edicion conversacional
      (un campo `prompt_modo` desapareceria en silencio: MEDIDO); y `tool`
      esta en la tupla de 7 campos de `flujoteca.comparar`, asi que pasar de
      constante a variable SALE en el diff del historial.

      - idempotente: comprueba TOOL, no id (restaurar() reguarda un flujo que
        ya lo tiene).
      - id 'prompt' ocupado por otra tool -> 'prompt_0', 'prompt_1', ...
      - wires = las raices previas (ids que no aparecen en ningun wires).

      DONDE se hace obligatorio: SOLO en el borde de guardado
      (`flujoteca.guardar` lo llama justo antes del `if validar:`). NO en
      `flows.validar` — medido: rompe 126 de 293 tests (43%) y vuelve
      inabribles los flujos ya guardados. La lectura sigue permisiva.
    """
    if not isinstance(flujo, dict):
        return flujo
    nodos = flujo.get("nodos")
    if not isinstance(nodos, list) or not nodos:
        # un flujo sin nodos no se arregla anadiendole uno: lo rechaza
        # `validar` con su mensaje, que es el que hay que leer.
        return flujo
    nodos = [n for n in nodos if isinstance(n, dict)]
    if len(nodos) != len(flujo["nodos"]):
        return flujo                    # basura: que hable `validar`
    # IDEMPOTENTE POR TOOL, NO POR ID: `restaurar()` reguarda un flujo que ya
    # tiene su nodo de entrada, y comprobar el id 'prompt' fallaria en cuanto
    # el dueno lo renombre a 'objetivo' (le anadiria un segundo nodo en cada
    # guardado, para siempre).
    if any(n.get("tool") in TOOLS_ENTRADA for n in nodos):
        return flujo
    ids = {n.get("id") for n in nodos}
    nid, k = "prompt", 0
    while nid in ids:
        nid, k = f"prompt_{k}", k + 1
    # Los wires del nodo nuevo son las RAICES previas: los ids a los que no
    # apunta ningun wire. Colgarlo solo del primer nodo de la lista dejaria
    # las demas raices sueltas (un flujo con dos ramas de arranque perderia
    # una) y colgarlo de TODOS crearia dependencias falsas.
    apuntados = set()
    for n in nodos:
        for w in (n.get("wires") or []):
            apuntados.add(w)
    raices = [n.get("id") for n in nodos if n.get("id") not in apuntados]
    entrada = {"id": nid, "tool": "prompt", "args": "", "wires": raices}
    copia = dict(flujo)
    copia["nodos"] = [entrada] + [dict(n) for n in nodos]
    return copia


def normalizar_args(flujo: dict, *, n_posicionales=None) -> tuple:
    r"""Arregla el separador de argumentos posicionales de los nodos legacy.
    Devuelve `(flujo, [ids_arreglados])`. Funcion pura: no muta la entrada ni
    reescribe nada en disco.

    CONTRATO (PLAN2, 5.1 "El separador de args", la causa raiz MEDIDA):
      La convencion es que los argumentos posicionales de una tool van
      separados por ' | ' en el orden que declara la tool; el salto de linea
      NO separa argumentos. `flujo_ia` ensenaba `args: "informe.md\n{{hallar}}"`
      y la tool exige `ruta | contenido`. Contrafactual medido: mismo flujo,
      solo cambiando '\n' por ' | ' -> 0 errores e `informe.md` de 1001 bytes.

      Para cada nodo cuya tool tenga >=2 params posicionales, cuyo `args`
      contenga "\n", NO contenga " | ", y cuyo numero de trozos coincida con
      el numero de posicionales: sustituye "\n" por " | " y anota su id.

      Se aplica en LECTURA (`flujoteca.cargar` y `flows.ejecutar`) y se
      REPORTA ("arregle el separador de 1 nodo; guardalo con /flujoteca
      editar para dejarlo fijo"). NO se reescribe la version en disco: las
      versiones del dueno son historial, no cache.
    """
    if not isinstance(flujo, dict):
        return flujo, []
    nodos = flujo.get("nodos")
    if not isinstance(nodos, list):
        return flujo, []
    contar = n_posicionales or _posicionales_de
    arreglados: list = []
    nuevos: list = []
    for n in nodos:
        if not isinstance(n, dict):
            nuevos.append(n)
            continue
        args = n.get("args")
        # Solo texto con salto de linea Y sin el separador bueno. Que baste
        # con encontrar " | " para NO tocar el nodo es deliberado: un
        # contenido con tabla markdown ("| a | b |") ya trae el separador y
        # partirlo lo destrozaria. Falso negativo barato, falso positivo caro.
        if not isinstance(args, str) or "\n" not in args or " | " in args:
            nuevos.append(n)
            continue
        tool = n.get("tool")
        try:
            n_pos = int(contar(tool))
        except Exception:
            n_pos = 0
        if n_pos < 2:
            nuevos.append(n)
            continue
        if tool in TOOLS_SEPARADOR_OBLIGATORIO:
            # Regla 2 (ver TOOLS_SEPARADOR_OBLIGATORIO): estas tools NO
            # arrancan sin el separador, asi que solo se parten los primeros
            # n_pos-1 saltos y TODO el resto es el ultimo argumento. Un
            # contenido de 40 lineas llega entero.
            trozos = args.split("\n", n_pos - 1)
        else:
            trozos = args.split("\n")
        # Regla 1 (el caso general): el numero de trozos TIENE que coincidir
        # con el de posicionales. Sin esa condicion, un contenido de 40 lineas
        # para una tool que SI tolera saltos se convertiria en 40 argumentos y
        # el fichero saldria con una linea.
        if len(trozos) != n_pos:
            nuevos.append(n)
            continue
        copia = dict(n)
        copia["args"] = " | ".join(trozos)
        nuevos.append(copia)
        arreglados.append(n.get("id"))
    if not arreglados:
        return flujo, []
    salida = dict(flujo)
    salida["nodos"] = nuevos
    return salida, arreglados


# Tools cuyo parser EXIGE el separador: sin un ' | ' devuelven "ERROR:
# formato" y no hacen absolutamente nada. Para ellas, un `args` con saltos de
# linea y sin pipe tiene HOY un resultado medido y unico -- fallo total, disco
# intacto -- asi que partir por los primeros n-1 saltos no puede empeorar
# nada, y es lo que hace que un contenido de 40 lineas llegue entero.
#
# LA LISTA SALE DE UNA MEDIDA, NO DE UNA SUPOSICION (2026-08-29): se llamo a
# TODA tool de >=2 posicionales con "a.txt\nlinea1\nlinea2" y se miro que
# devolvia. `buscar`, `buscar_ficheros` y `consultar_oraculo` SI toleran los
# saltos y hacen algo razonable -- por eso NO estan aqui, y por eso la regla
# general (numero exacto de trozos) sigue existiendo para ellas.
# `test_flujo_e2e_real.py` reejecuta esa medida en cada corrida: si una tool
# de la lista deja de exigir el separador, el test se pone rojo antes de que
# la heuristica le parta un argumento legitimo.
TOOLS_SEPARADOR_OBLIGATORIO = frozenset({
    "escribir_archivo", "apendar_archivo", "editar_archivo",
    "generar_codigo", "mover_archivo",
})


def _posicionales_de(tool) -> int:
    """Cuantos argumentos POSICIONALES declara `tool` en el registro real.
    Import local: `tools.py` importa este modulo al registrar, asi que un
    import a nivel de modulo seria un ciclo. Tool desconocida o registro no
    cargado -> 0 (y `normalizar_args` no la toca: nunca adivina)."""
    try:
        from cognia.agent.tools import TOOLS
    except Exception:
        return 0
    spec = TOOLS.get(tool) or {}
    return sum(1 for p in (spec.get("params") or []) if not p.get("clave"))


def aviso_normalizacion(arreglados: list) -> str:
    """El texto que se le ensena al dueno cuando `normalizar_args` arreglo
    algo. Vive aqui para que el CLI, el editor y las tools digan lo MISMO."""
    if not arreglados:
        return ""
    n = len(arreglados)
    return (f"arregle el separador de {n} nodo{'s' if n != 1 else ''} "
            f"({', '.join(str(i) for i in arreglados)}); guardalo con "
            f"/flujoteca editar para dejarlo fijo")


def ejecutar(flujo: dict, ctx: dict, run_tool: Callable[[str, str, dict], str],
             tool_existe: Callable[[str], bool] | None = None,
             log: Callable[[str], None] | None = None,
             paralelo: bool = False, cap: int = 2,
             cache: dict | None = None, *,
             variables: dict | None = None) -> dict:
    r"""Ejecuta el flujo en orden topológico. run_tool(name,args,ctx)->str es
    el dispatcher del registro (cognia.agent.tools.run_tool). Devuelve
    {"salidas": {id: resultado}, "orden": [...], "errores": {id: msg},
     "saltados": [ids], "cacheados": [ids]}.

    Por nodo: interpola {{deps}} en args, aplica `saltar_si` (si el texto
    aparece en alguna salida previa QUE NO SEA DE ENTRADA → se salta; el
    texto que teclea el dueño no salta nodos, ver `entradas` más abajo),
    reintenta `reintentos` veces
    y respeta `timeout_s` (best-effort por wall-clock; el tool corre igual,
    pero se marca timeout si excede). Un nodo que falla NO frena el flujo:
    se registra y sus dependientes reciben su error interpolado.

    paralelo=True (opt-in): despacho por NIVELES topológicos — un nivel son
    los nodos cuyas dependencias (padres) ya terminaron; los hermanos del
    mismo nivel corren juntos en un ThreadPoolExecutor(cap). cap default 2:
    la física medida de esta máquina es que un solo slot de GPU serializa y
    2-3 hilos solo solapan I/O, más no compra nada.
    DESVÍO SEMÁNTICO (por esto es opt-in y el default queda intacto): con
    paralelo, `saltar_si` y la interpolación {{id}} ven las salidas de los
    NIVELES previos COMPLETOS, nunca las de hermanos del mismo nivel. En
    secuencial un hermano posterior sí veía al anterior (el orden de Kahn los
    serializaba); en paralelo ese orden no existe, así que un `saltar_si` que
    dependía de un hermano deja de dispararse y un {{hermano}} interpola "".

    cache (opcional): dict {clave: salida} con clave = sha256(tool + args ya
    interpolados). Un nodo cuya clave está en el cache con salida ok se reusa
    sin ejecutar (queda anotado en "cacheados"); las salidas con ERROR no se
    guardan ni se reusan (un error viejo no debe enmascarar un reintento).
    El dict se MUTA con las salidas ok nuevas: el llamador decide si persiste.

    CONTRATO de `variables` (PLAN2, PEDIDO 3 "Interpolacion y ejecucion") —
    STUB EN F0: el parametro existe con default None y HOY NO HACE NADA (el
    comportamiento sin el es identico al de siempre). Lo implementa el agente
    B en F1:
      - siembra `salidas` con `variables` ANTES del primer nodo, y SOLO con
        claves que no sean id de nodo (una variable nunca pisa un nodo).
      - `_INTERP` ya casa `{{prompt}}`; el regex NO se toca.
      - `_interpolar` recorta cada sustitucion a 2000 chars: para las salidas
        de nodos `prompt`/`prompt_fijo` el tope sube a 8000 (el objetivo del
        dueno no puede truncarse en silencio). Se implementa pasando el
        conjunto de ids "crudos" desde `ejecutar`.

    CONTRATO del RESULTADO ampliado (PLAN2, 5.5 y 5.6) — aditivo, NUNCA
    renombrar (`flow_view`/`flujoteca_view`/`editor_html` consumen este dict).
    `ejecutar` devuelve ademas:
      - "ok": bool                = `not errores` Y no cancelado (un flujo que
                                    el dueno corto a mitad no es un flujo que
                                    salio bien: `errores` esta vacio justo
                                    porque los nodos que faltaban no corrieron)
      - "entregable": str         = salida del ultimo nodo del orden
                                    topologico que no sea `prompt`/`prompt_fijo`
                                    (y que haya corrido: con un corte a mitad,
                                    el ultimo que si llego a producir algo)
      - "ficheros": [str]         = rutas deducidas de forma determinista de
                                    los nodos cuya tool esta en
                                    `TOOLS_ESCRITURA` y cuyo nodo salio OK
      - "cancelado": bool         = `ctx["_cancelado"]` disparo a mitad
      - "marcadores_vacios": [ids] = `{{desconocido}}` que quedo en hueco
      - "args_normalizados": [ids] = nodos legacy a los que se les arreglo el
                                    separador AL LEER (ver `normalizar_args`)
      - "denegados": [ids]        = nodos que el GATE DE PERMISOS no dejo
                                    correr. NO son un fallo del nodo: no
                                    hicieron nada. Entran tambien en
                                    `errores` y tumban `ok`, porque "no hizo
                                    nada" no puede volver a salir en verde
                                    con "0 con error"; y ninguno puede ser el
                                    `entregable`
      - "motivos_denegacion": {id: motivo} = por que, para que el modelo y el
                                    dueno lean algo accionable en vez de un
                                    flujo mudo
    Y los dos bordes de 5.6: `_correr_nodo` exceptua `prompt`/`prompt_fijo` de
    la heuristica `re.search(r"\bERROR\b", res[:120])`; y el bucle consulta
    `ctx["_cancelado"]` al principio de cada nodo."""
    orden = validar(flujo, tool_existe)
    # El separador se arregla EN LECTURA, aqui y en `flujoteca.cargar`: los
    # flujos ya guardados del dueno usan "\n" donde la tool exige " | " y
    # devolvian "ERROR: formato" sin tocar el disco. No se reescribe nada.
    flujo, args_normalizados = normalizar_args(flujo)
    if args_normalizados and log:
        log("[flujo] " + aviso_normalizacion(args_normalizados))
    by_id = {n["id"]: n for n in flujo["nodos"]}
    # ids cuyas salidas se interpolan con el tope AMPLIADO (8000)
    crudos = frozenset(i for i, n in by_id.items()
                       if n.get("tool") in TOOLS_ENTRADA)
    salidas: dict[str, str] = {}
    errores: dict[str, str] = {}
    saltados: list = []
    cacheados: list = []
    marcadores_vacios: list = []
    ficheros: list = []
    denegados: list = []
    motivos_denegacion: dict[str, str] = {}
    cancelado = False
    # El gate deniega llamando a `ctx["confirm"]`; envolverlo es la
    # unica deteccion EXACTA de una denegacion (ver "DENEGACIONES DEL
    # GATE"). Copia superficial: el ctx es del llamador.
    ctx = _ctx_vigilado(ctx)

    # VARIABLES SEMBRADAS (PEDIDO 3): entran en `salidas` ANTES del primer
    # nodo, y SOLO con claves que no sean id de nodo — una variable nunca
    # pisa un nodo (si lo hiciera, el flujo dejaria de correr ese nodo y
    # nadie sabria por que).
    sembradas: set = set()
    if variables:
        for k, v in dict(variables).items():
            k = str(k)
            if k in by_id:
                if log:
                    log(f"[flujo] variable '{k}' IGNORADA: hay un nodo con "
                        f"ese id (una variable nunca pisa un nodo)")
                continue
            salidas[k] = "" if v is None else str(v)
            sembradas.add(k)

    def _corte_pedido() -> bool:
        """`ctx['_cancelado']` es un callable (lo inyecta cli.py cuando la
        tarea corre en el carril de fondo), pero se acepta tambien un valor
        pelado: un hook que rompe jamas puede tumbar el flujo."""
        marca = ctx.get("_cancelado") if isinstance(ctx, dict) else None
        if callable(marca):
            try:
                return bool(marca())
            except Exception:
                return False
        return bool(marca)

    # DE QUE SALIDAS NO PUEDE DISPARAR `saltar_si`: las de ENTRADA.
    # El nodo `prompt` se inserta HOY al inicio de todo flujo y devuelve el
    # texto CRUDO que teclea el dueno, asi que `saltar_si` pasaba a
    # comprobarse contra el objetivo del dueno. No es rebuscado: el valor de
    # ejemplo documentado de `saltar_si` en el editor es literalmente
    # "ERROR" (editor_html.py:158) y la tecla D ("deshabilitar el nodo")
    # escribe saltar_si="RESULTADO" (editor_html.py:2726). MEDIDO: flujo
    # prompt -> escribir_archivo con saltar_si "ERROR" y el dueno pegando un
    # log ("arregla el ERROR de la web") daba ok=True, saltados=['w'],
    # entregable "(saltado: 'ERROR')" y CERO ficheros en disco -- la queja
    # del dueno ("no hacen nada") producida por su propio texto. Y el tope
    # de interpolacion de los nodos de entrada subio hoy a 8000 chars
    # precisamente para que pueda pegar objetivos largos: pegar un log, donde
    # ERROR en mayusculas abunda, es el uso PREVISTO.
    # Es el hermano del bug que se arreglo hoy en `_correr_nodo` (exceptuar
    # TOOLS_ENTRADA de la heuristica \bERROR\b); aqui va la otra mitad.
    # Entran tambien las VARIABLES SEMBRADAS: un flujo viejo sin nodo de
    # entrada recibe el objetivo del dueno por `variables={"prompt": ...}`,
    # y es el mismo texto por otra puerta.
    entradas = frozenset(crudos) | frozenset(sembradas)

    def _paso(nid: str, vista: dict) -> tuple:
        """Procesa un nodo mirando SOLO `vista` (las salidas que le tocan
        ver: todas las previas en secuencial, los niveles completos en
        paralelo). Devuelve (res, ok, estado, args, faltan, motivos) con
        estado en {'ok','error','saltado','cacheado'}."""
        n = by_id[nid]
        cond = (n.get("saltar_si") or "").strip()
        if cond and any(cond in v for k, v in vista.items()
                        if k not in entradas):
            if log:
                log(f"[flujo] {nid} saltado (saltar_si '{cond}')")
            return f"(saltado: '{cond}')", True, "saltado", "", [], []
        args, faltan = _interpolar_con_faltantes(n.get("args", ""), vista,
                                                 crudos)
        if cache is not None:
            clave = _clave_cache(n["tool"], args)
            prev = cache.get(clave)
            # solo se reusa una salida SANA: un ERROR cacheado no vale
            if prev is not None and not re.search(r"\bERROR\b", str(prev)[:120]):
                if log:
                    log(f"[flujo] {nid} ({n['tool']}) cacheado")
                return str(prev), True, "cacheado", args, faltan, []
        res, ok, motivos = _correr_nodo(n, args, ctx, run_tool, log,
                                        ctx_compartido=paralelo)
        if cache is not None and ok:
            cache[clave] = res
        return (res, ok, ("ok" if ok else "error"), args, faltan, motivos)

    def _anotar(nid: str, res: str, ok: bool, estado: str,
                args: str = "", faltan=(), motivos=()) -> None:
        salidas[nid] = res
        if estado == "saltado":
            saltados.append(nid)
        elif estado == "cacheado":
            cacheados.append(nid)
        if motivos and not ok:
            # DENEGADO: el nodo no fallo, es que no se le dejo correr. Entra
            # ademas en `errores` a proposito -- "no hizo nada" nunca puede
            # volver a salir en verde ni contar como "0 con error".
            if nid not in denegados:
                denegados.append(nid)
            motivos_denegacion[nid] = "; ".join(str(m) for m in motivos)[:300]
        if not ok:
            errores[nid] = res[:200]
        for m in faltan:
            if m not in marcadores_vacios:
                marcadores_vacios.append(m)
        if ok and estado in ("ok", "cacheado"):
            ruta = _fichero_de_nodo(by_id[nid].get("tool"), args)
            if ruta and ruta not in ficheros:
                ficheros.append(ruta)

    if not paralelo:
        for nid in orden:
            if _corte_pedido():
                cancelado = True
                if log:
                    log(f"[flujo] CORTE pedido: se detiene antes de '{nid}'")
                break
            res, ok, estado, args, faltan, motivos = _paso(nid, salidas)
            _anotar(nid, res, ok, estado, args, faltan, motivos)
    else:
        from concurrent.futures import ThreadPoolExecutor
        # padres (dependencias) de cada nodo, invirtiendo los wires
        padres: dict[str, set] = {i: set() for i in orden}
        for n in flujo["nodos"]:
            for w in (n.get("wires") or []):
                padres[w].add(n["id"])
        pendientes = list(orden)
        hechos: set = set()
        with ThreadPoolExecutor(max_workers=max(1, int(cap))) as pool:
            while pendientes:
                if _corte_pedido():
                    cancelado = True
                    if log:
                        log("[flujo] CORTE pedido: se detiene antes del "
                            "siguiente nivel")
                    break
                nivel = [i for i in pendientes if padres[i] <= hechos]
                # snapshot: los hermanos del nivel NO se ven entre si (el
                # desvio semantico documentado arriba)
                vista = dict(salidas)
                futs = {i: pool.submit(_paso, i, vista) for i in nivel}
                for i in nivel:
                    res, ok, estado, args, faltan, motivos = futs[i].result()
                    _anotar(i, res, ok, estado, args, faltan, motivos)
                    hechos.add(i)
                pendientes = [i for i in pendientes if i not in hechos]
    # ENTREGABLE: el ultimo nodo del orden topologico que produjo algo y que
    # no es de entrada. Sin esto, `ejecutar` devolvia cinco claves y NINGUNA
    # decia que se habia producido — literalmente la queja del dueno ("los
    # workflows no entregan nada al final").
    # Un nodo DENEGADO tampoco entrega: su texto es el del gate ("no
    # confirmado por el usuario"), y darlo como entregable es lo que hacia
    # que `/flujoteca ejecutar` imprimiera la denegacion en verde como si
    # fuera el producto del flujo. Un nodo que FALLA si entrega su error: se
    # ensena, no se traga (hay test que lo fija).
    entregable = ""
    for nid in reversed(orden):
        if nid in crudos or nid in denegados or nid not in salidas:
            continue
        entregable = str(salidas.get(nid, ""))
        break
    return {"salidas": salidas, "orden": orden, "errores": errores,
            "saltados": saltados, "cacheados": cacheados,
            "ok": (not errores) and not cancelado and not denegados,
            "entregable": entregable, "ficheros": ficheros,
            "cancelado": cancelado, "marcadores_vacios": marcadores_vacios,
            "args_normalizados": args_normalizados,
            "denegados": denegados,
            "motivos_denegacion": motivos_denegacion}


# El planner (`agents/planner.py`) habla el vocabulario de SU mundo
# (research_llm, synthesize, validate_python...), que NO es el registro de
# tools de Cognia: `crear_flujo` guardaba flujos con siete tools que no
# existen y el fallo aparecia al EJECUTAR, nodo por nodo, en vez de al crear.
# Esta tabla es el puente, y esta verificada contra `tools.TOOLS`.
TRADUCCION_PLANNER = {
    "research_llm": "buscar",
    "synthesize": "resumir",
    "validate_python": "py_validar",
    "execute_python": "ejecutar",
    "file_explorer": "arbol",
    "search_wikipedia": "buscar",
    "query_episodic": "recordar",
    "responder": "resumir",             # el default del planner
}


def traducir_tool(tool: str) -> str:
    """El nombre del planner -> el nombre real de la tool. Lo que no esta en
    la tabla se devuelve TAL CUAL (una tool real no se toca)."""
    return TRADUCCION_PLANNER.get(str(tool or ""), tool)


def from_plan(nombre: str, pasos: list) -> dict:
    """Construye un flujo LINEAL desde una lista de pasos (planner.SubTask o
    dicts con 'description'/'tool_required'). Cada paso → un nodo encadenado
    al siguiente. Es el puente "Cognia organiza el flujo": el planner
    determinista arma los pasos, esto los vuelve un DAG ejecutable.

    Traduce el vocabulario del planner al registro real (TRADUCCION_PLANNER):
    sin eso, el 100% de los flujos de `crear_flujo` salia con tools
    inexistentes y `ejecutar_flujo` devolvia un error por nodo."""
    nodos = []
    prev = None
    for i, p in enumerate(pasos):
        pid = f"n{i}"
        tool = (getattr(p, "tool_required", None)
                or (p.get("tool_required") if isinstance(p, dict) else None)
                or (p.get("tool") if isinstance(p, dict) else None)
                or "responder")
        tool = traducir_tool(tool)
        desc = (getattr(p, "description", None)
                or (p.get("description") if isinstance(p, dict) else "")
                or (p.get("args") if isinstance(p, dict) else "") or "")
        # modelo recomendado por Cognia para ese paso (color del nodo)
        try:
            from cognia.oficina.identidad import recomendar_modelo
            modelo = recomendar_modelo(tool)
        except Exception:
            modelo = None
        nodos.append({"id": pid, "tool": tool, "args": desc, "wires": [],
                      "modelo": modelo})
        if prev is not None:
            nodos[prev]["wires"].append(pid)
        prev = i
    return {"nombre": nombre, "nodos": nodos}


def organizar_flujo(texto: str) -> dict:
    """"Cognia organiza el flujo": desde una descripción en lenguaje natural,
    usa el planner simbólico (0-LLM) para descomponer en pasos y los vuelve un
    flujo (DAG) ejecutable. Devuelve el flujo. Cero modelo (plan_task es
    determinista por templates).

    VALIDA CONTRA EL REGISTRO REAL antes de devolver (PLAN2 5.4): con la
    validacion pelada (solo forma del grafo), `crear_flujo` persistia flujos
    cuyas 7 tools no existen y el dueno se enteraba al EJECUTAR, con un error
    por nodo y cero entregable. Ahora el fallo aparece al CREAR, nombrando el
    paso. Si el registro no se puede importar, se valida como siempre: un
    entorno sin tools no es motivo para no poder dibujar un flujo."""
    from cognia.agents.planner import plan_task
    subtasks = plan_task(texto, task_id="flujo")
    flujo = from_plan(texto[:60], subtasks)
    existe = None
    try:
        from cognia.agent.tools import TOOLS
        existe = lambda n: n in TOOLS        # noqa: E731
    except Exception:
        existe = None
    if existe is not None:
        for i, n in enumerate(flujo["nodos"]):
            if not existe(n.get("tool")):
                raise FlowError(
                    f"el paso {i + 1} ({str(n.get('args') or '')[:60]}) pide "
                    f"la tool '{n.get('tool')}', que no existe en Cognia; "
                    f"no se guarda nada")
    validar(flujo, tool_existe=existe)   # asegura DAG + tools REALES
    return flujo


def to_json(flujo: dict) -> str:
    import json
    return json.dumps(flujo, ensure_ascii=False, indent=1)


def from_json(texto: str) -> dict:
    import json
    f = json.loads(texto)
    if "nodos" not in f:
        raise FlowError("JSON sin 'nodos'")
    return f


# ── resolucion de la ruta de un flujo guardado (para ejecutar_flujo) ────────
def _resolver_ruta_flujo(args: str):
    """Ruta del .flujo.json a ejecutar. Sin args -> el .flujo.json del
    workspace (donde persiste crear_flujo). Con args: ruta literal si existe,
    si no se busca en el workspace (con y sin el sufijo .flujo.json).
    Devuelve un Path existente o None."""
    from pathlib import Path
    nombre = (args or "").strip()
    candidatos = []
    try:
        from cognia.agents.workers.dev_tools import _root_actual
        root = Path(_root_actual())
    except Exception:
        root = None
    if not nombre:
        if root is not None:
            candidatos.append(root / ".flujo.json")
    else:
        candidatos.append(Path(nombre))
        if root is not None:
            candidatos.append(root / nombre)
            if not nombre.endswith(".flujo.json"):
                candidatos.append(root / f"{nombre}.flujo.json")
    for c in candidatos:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


# Motivo del ultimo fallo al mirar la flujoteca desde `_resolver_flujo`.
# Existe para que "no hay ningun flujo asi" y "la biblioteca esta rota" no se
# vean igual desde fuera, que es el modo de fallo caro de esta casa.
_ULTIMO_FALLO_RESOLVER = [""]


def _resolver_flujo(args: str) -> tuple:
    """Resuelve el flujo a ejecutar. Devuelve `(flujo, origen)`, donde
    `flujo` es el dict ya cargado (o None si no se encuentra) y `origen` es
    un texto corto que dice DE DONDE salio ("ruta", "workspace",
    "flujoteca:<nombre> v<N>"), para poder anunciarlo en la salida.

    CONTRATO (PLAN2, PEDIDO 4 punto 6 "ejecutar_flujo alcanza la flujoteca"):
      Parte de `_resolver_ruta_flujo` (que solo mira el disco del workspace).
      Precedencia EXPLICITA y anunciada en la salida:
          ruta literal > workspace > flujoteca
      Asi el agente y `/hacer` tambien pueden correr lo que el dueno dibuja
      en el editor visual, no solo el `.flujo.json` del workspace.
      `_resolver_ruta_flujo` se conserva (lo usan los llamadores viejos).
    """
    from pathlib import Path
    nombre = (args or "").strip()
    # 1. RUTA LITERAL. Va primero porque es lo unico INEQUIVOCO: quien
    #    escribe una ruta no quiere que se le busque un homonimo.
    if nombre:
        try:
            p = Path(nombre)
            if p.is_file():
                return from_json(p.read_text(encoding="utf-8")), f"ruta {p}"
        except OSError:
            pass                        # nombre con caracteres imposibles
    # 2. WORKSPACE (el .flujo.json que persiste crear_flujo).
    ruta = _resolver_ruta_flujo(nombre)
    if ruta is not None:
        return (from_json(ruta.read_text(encoding="utf-8")),
                f"workspace {ruta.name}")
    # 3. FLUJOTECA: lo que el dueno dibuja en el editor visual. Sin este
    #    escalon, `ejecutar_flujo` no alcanzaba NADA de la biblioteca y el
    #    agente solo podia correr el fichero suelto del workspace.
    if nombre:
        try:
            from cognia.agent import flujoteca as _fl
            if _fl.existe(nombre):
                flujo = _fl.cargar(nombre)
                v = next((e.get("v") for e in _fl.versiones(nombre)
                          if e.get("actual")), 0)
                return flujo, f"flujoteca:{nombre} v{v}"
        except Exception as exc:
            # NUNCA mudo: "no existe" y "la biblioteca esta rota" piden cosas
            # distintas del dueno, y desde fuera se veian igual. El motivo
            # viaja hasta el mensaje de 'no lo encontre'.
            _ULTIMO_FALLO_RESOLVER[0] = f"{type(exc).__name__}: {exc}"
    return None, ""


# ── tools `crear_flujo` + `ejecutar_flujo` ──────────────────────────────────
def register(tool_decorator) -> None:
    # ── ENTRADA del flujo (PEDIDO 3) ────────────────────────────────────
    # Registradas DESDE AQUI (no desde tools.py) para no tocar el fichero de
    # 4.000 lineas que tiene otro dueno en esta obra.
    #
    # DEVUELVEN EL TEXTO CRUDO, sin el prefijo "RESULTADO <tool>: " que
    # llevan las demas: la salida de este nodo se interpola en los args de
    # TODOS los nodos siguientes via {{prompt}}, asi que un prefijo se
    # colaria dentro de cada fichero escrito y de cada busqueda. Hay test de
    # contrato para esto (tests/test_flows_prompt.py).
    @tool_decorator(
        "prompt",
        "prompt <texto por defecto>            -- ENTRADA del flujo: el "
        "objetivo/tema. El argumento de /flujoteca ejecutar lo PISA",
        danger=False,
        desc="Nodo de ENTRADA de un flujo: entrega el objetivo/tema con el "
             "que corre el flujo, para interpolarlo en los demas nodos con "
             "{{prompt}}. Es VARIABLE: si quien ejecuta el flujo pasa un "
             "prompt, ese gana; si no, se usa el texto por defecto del nodo.",
        params=[
            {"nombre": "texto", "tipo": "string", "requerido": False,
             "descripcion": "texto por defecto si nadie pasa uno al ejecutar"},
        ])
    def _t_prompt(args, ctx):
        ctx = ctx if isinstance(ctx, dict) else {}
        return str(ctx.get("prompt_flujo") or args or "")

    @tool_decorator(
        "prompt_fijo",
        "prompt_fijo <la constante>            -- ENTRADA del flujo CONSTANTE: "
        "ignora el prompt que pasen al ejecutar",
        danger=False,
        desc="Nodo de ENTRADA de un flujo, en modo CONSTANTE: entrega "
             "siempre el mismo texto, ignorando el prompt que pasen al "
             "ejecutar el flujo. Para flujos que siempre hacen lo mismo.",
        params=[
            {"nombre": "texto", "tipo": "string", "requerido": True,
             "descripcion": "la constante que recibe el flujo"},
        ])
    def _t_prompt_fijo(args, ctx):
        return str(args or "")

    @tool_decorator(
        "crear_flujo",
        "crear_flujo <descripcion> -- organiza la tarea en un flujo (DAG de "
        "pasos estilo n8n) desde lenguaje natural, y lo guarda",
        danger=False)
    def _t_crear_flujo(args, ctx):
        texto = (args or "").strip()
        if not texto:
            return "RESULTADO crear_flujo ERROR: falta la descripcion"
        try:
            flujo = organizar_flujo(texto)
        except Exception as exc:
            return f"RESULTADO crear_flujo ERROR: {exc}"
        # persistir en el workspace del agente
        try:
            from cognia.agents.workers.dev_tools import _root_actual
            from pathlib import Path
            dest = Path(_root_actual()) / ".flujo.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(to_json(flujo), encoding="utf-8")
            # lienzo visual estilo n8n al lado del JSON (flow_view.export
            # estaba escrito y sin llamador de produccion): best-effort, el
            # flujo queda usable aunque el HTML falle.
            try:
                from cognia.agent.flow_view import export as _export_html
                _export_html(flujo, str(dest.with_suffix("")) + ".html",
                             title=f"Cognia · Flujo: {texto[:50]}")
            except Exception:
                pass
        except Exception:
            pass
        pasos = "\n".join(f"  {i+1}. [{n['tool']}] {n['args'][:60]}"
                          for i, n in enumerate(flujo["nodos"]))
        return (f"RESULTADO crear_flujo: {len(flujo['nodos'])} pasos\n{pasos}\n"
                "(guardado en .flujo.json; lienzo en .flujo.html)")

    @tool_decorator(
        "ejecutar_flujo",
        "ejecutar_flujo <nombre|ruta.flujo.json> -- ejecuta un flujo guardado "
        "(DAG de tools) en orden topologico; sin args usa el .flujo.json del "
        "workspace",
        danger=False)
    def _t_ejecutar_flujo(args, ctx):
        import json as _json
        import os
        ctx = ctx if isinstance(ctx, dict) else {}
        # guardia anti-recursion: antes era la bandera _flujo_en_curso (cero
        # anidamiento); ahora es un contador de profundidad con techo 2 — un
        # flujo puede ejecutar UN nivel de sub-flujo, al tercer nivel ERROR.
        depth = ctx.get("_flujo_depth")
        if depth is None:
            # compat: llamadores viejos marcaban la bandera sin contador;
            # respetarla como "sin presupuesto de anidamiento"
            depth = 2 if ctx.get("_flujo_en_curso") else 0
        if depth >= 2:
            return ("RESULTADO ejecutar_flujo ERROR: ya hay un flujo en "
                    "ejecucion (profundidad maxima de sub-flujos: 2)")
        # ruta literal > workspace > flujoteca, y el ORIGEN se anuncia en la
        # salida: dos flujos con el mismo nombre en sitios distintos son un
        # accidente esperable, y no decir cual corrio es como no correrlo.
        _ULTIMO_FALLO_RESOLVER[0] = ""
        try:
            flujo, origen = _resolver_flujo(args)
        except Exception as exc:
            return (f"RESULTADO ejecutar_flujo ERROR: el flujo "
                    f"'{(args or '').strip()}' es invalido: {exc}")
        if flujo is None:
            porque = _ULTIMO_FALLO_RESOLVER[0]
            return ("RESULTADO ejecutar_flujo ERROR: no encontre el flujo "
                    f"'{(args or '').strip() or '.flujo.json'}' (crealo antes "
                    "con crear_flujo, o guardalo en la flujoteca)"
                    + (f" [la flujoteca fallo: {porque}]" if porque else ""))
        # dispatcher REAL del registro: import local (tools.py importa este
        # modulo al registrar -> import a nivel de modulo seria un ciclo).
        from cognia.agent.tools import TOOLS, run_tool
        log = ctx.get("print_fn") if callable(ctx.get("print_fn")) else None
        # opt-in estrictos por env (== "1", el parse de la casa): el paralelo
        # cambia la semantica de saltar_si entre hermanos y el cache persiste
        # estado en disco — ninguno debe activarse solo.
        paralelo = os.environ.get("COGNIA_FLOWS_PARALELO", "") == "1"
        cache, cache_ruta = None, None
        if os.environ.get("COGNIA_FLOWS_CACHE", "") == "1":
            cache = {}
            try:
                from pathlib import Path
                from cognia.agents.workers.dev_tools import _root_actual
                cache_ruta = Path(_root_actual()) / ".flujo_cache.json"
                if cache_ruta.is_file():
                    prev = _json.loads(cache_ruta.read_text(encoding="utf-8"))
                    if isinstance(prev, dict):
                        cache = prev
            except Exception:
                cache_ruta = None       # sin workspace/JSON roto: cache en RAM
        # la profundidad viaja POR RAMA en una copia superficial del ctx, no
        # como contador mutado en el ctx compartido: con paralelo, dos nodos
        # ejecutar_flujo hermanos comparten ctx y el patron leer/incrementar/
        # decrementar sufria carrera (ambos leian 1, ambos escribian 2 y sus
        # dos finally lo bajaban a 0 -> el sub-flujo del nivel siguiente
        # arrancaba como top-level y su cadena anidada burlaba la guardia).
        # Los objetos anidados (agent_state, working_memory, print_fn) se
        # comparten igual por ser copia superficial; el padre nunca ve su
        # nivel alterado porque su dict ya no se toca.
        ctx_hijo = dict(ctx)
        ctx_hijo["_flujo_depth"] = depth + 1
        # Flujo VIEJO sin nodo de entrada: si el llamador trae un prompt, se
        # siembra igual como variable {{prompt}} para que un flujo de antes
        # del PEDIDO 3 pueda usarlo sin reescribirlo (los flujos del dueno
        # son historial, no se tocan).
        variables = None
        _prompt = ctx.get("prompt_flujo")
        if _prompt and not any((n or {}).get("tool") in TOOLS_ENTRADA
                               for n in (flujo.get("nodos") or [])):
            variables = {"prompt": _prompt}
        try:
            res = ejecutar(flujo, ctx_hijo, run_tool,
                           tool_existe=lambda n: n in TOOLS, log=log,
                           paralelo=paralelo, cache=cache,
                           variables=variables)
        except FlowError as exc:
            return f"RESULTADO ejecutar_flujo ERROR: {exc}"
        if cache_ruta is not None:
            # persistencia atomica tmp+replace (patron estado_tarea.py).
            # Fusion con lo que haya en disco ANTES de escribir (fix
            # 2026-08-11): un sub-flujo hijo persiste SU cache mientras este
            # flujo corre, y escribir solo `cache` (el snapshot leido al
            # arrancar + los nodos propios) PISABA las claves del hijo. En
            # colision de clave gana lo propio: es lo mas fresco de ESTA
            # corrida.
            try:
                fusion = {}
                try:
                    if cache_ruta.is_file():
                        prev = _json.loads(
                            cache_ruta.read_text(encoding="utf-8"))
                        if isinstance(prev, dict):
                            fusion = prev
                except Exception:
                    pass        # JSON roto en disco: se escribe lo propio
                fusion.update(cache)
                tmp = cache_ruta.with_suffix(".json.tmp")
                tmp.write_text(_json.dumps(fusion, ensure_ascii=False),
                               encoding="utf-8")
                os.replace(tmp, cache_ruta)
            except Exception:
                pass                    # el cache es aceleracion, no estado
        # LO QUE LEE EL MODELO tiene que traer la denegacion. Hasta hoy no
        # la traia: `_RE_FLUJO_DENEGADO` solo existe en cli.py, asi que el
        # gate frenaba la unica accion del flujo, el motivo se imprimia por
        # consola (`_denegar_sin_humano`) y la OBSERVACION del modelo decia
        # "0 con error" con el texto de la denegacion de entregable. Es el
        # "se bloquea mudo" que el docstring de `_ctx_agente` se propuso
        # evitar: se evito en la consola y NO en el contrato.
        denegados = list(res.get("denegados") or [])
        motivos = res.get("motivos_denegacion") or {}
        lineas = []
        for nid in res["orden"]:
            estado = ("saltado" if nid in res["saltados"]
                      else "cacheado" if nid in res.get("cacheados", [])
                      else "DENEGADO" if nid in denegados
                      else "error" if nid in res["errores"]
                      else "sin correr" if nid not in res["salidas"] else "ok")
            lineas.append(f"  {nid}: {estado} - "
                          f"{str(res['salidas'].get(nid, ''))[:80]}")
        n_err = len(res["errores"])
        cabeza = (f"RESULTADO ejecutar_flujo {origen}: "
                  f"{len(res['orden'])} nodos, {n_err} con error, "
                  f"{len(res['saltados'])} saltados")
        if denegados:
            cabeza += f", {len(denegados)} DENEGADOS por permisos"
        if cache is not None:
            cabeza += f", {len(res.get('cacheados', []))} cacheados"
        # EL ENTREGABLE Y LOS FICHEROS, en el texto que lee el modelo y el
        # dueno. Sin esta cola, un flujo que escribio tres ficheros devolvia
        # una tabla de estados y nada mas: "no entregan nada al final".
        cola = []
        if denegados:
            # Primero de la cola y en imperativo: es lo unico accionable.
            cola.append(
                "DENEGADO por el gate de permisos: "
                + ", ".join(denegados)
                + ". Esos nodos NO se ejecutaron, asi que el flujo no hizo "
                  "esa parte del trabajo. Motivo: "
                + " | ".join(f"{k}: {v}" for k, v in motivos.items())
                + ". Para permitirlo: aprobarlo cuando lo pregunte, o "
                  "guardarlo con /permisos permitir <accion>; con "
                  "/modo-permiso se cambia la politica.")
        if res.get("cancelado"):
            cola.append("CANCELADO por el usuario a mitad del flujo")
        if res.get("args_normalizados"):
            cola.append(aviso_normalizacion(res["args_normalizados"]))
        if res.get("marcadores_vacios"):
            cola.append("marcadores sin valor: "
                        + ", ".join("{{%s}}" % m
                                    for m in res["marcadores_vacios"]))
        if res.get("ficheros"):
            cola.append("Ficheros: " + ", ".join(res["ficheros"]))
        if res.get("entregable"):
            cola.append("Entregable:\n" + str(res["entregable"])[:2000])
        return cabeza + "\n" + "\n".join(lineas + cola)
