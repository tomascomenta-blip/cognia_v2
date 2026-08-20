# -*- coding: utf-8 -*-
"""DRIVER -- la SESION TX y el que orquesta los ciclos (ESPEC 14.2, bloque M3).

QUE ES ESTO Y QUE NO ES. `commit.py` sabe hacer UN commit; no sabe que tarea
hay abierta, ni cuantos pasos lleva, ni contra que contrato se mide. Todo eso
es la SESION, y vive aqui. El driver es la unica pieza con estado global del
subsistema, y esta puesto a proposito en un solo sitio: dos duenos del estado
de la tarea es como se llega a "una clave distinta entre modulos" (tests
verdes y cero salidas en produccion).

OPT-IN DURO: nada de este modulo corre con COGNIA_TX apagado. El REPL ni lo
importa -- la puerta (`cli._slash_tx`) comprueba el flag ANTES del import, asi
que con la variable apagada el coste es un `os.environ.get`.

EL ENGANCHE DEL CICLO (`enganchar`). `harness/interceptor._libro` llama a
`libro.registrar_tool(evento, ctx)` y saca el ciclo de `ctx['_tx_ciclo']`. Ese
ctx lo arma `agent/tools.run_tool`, que no sabe nada de TX: sin enganche TODOS
los eventos caerian en el ciclo 0 y G6 (ciclo mudo) daria rojo para siempre
-- un gate que suspende siempre es tan inutil como uno que aprueba siempre.
`enganchar()` ENVUELVE `registrar_tool` para rellenar el ciclo que falta.
Envolver y no editar `libro.py`: el ciclo es del driver, no del almacen, y
meterle al almacen una dependencia hacia arriba lo haria intestable solo.

LO QUE EL DRIVER NO DECIDE: si un gate esta verde. Eso es de `gates.py`, se
mide y no se opina. El driver decide CUANDO se intenta un commit (el
disparador: presupuesto de pasos agotado) y la compuerta la corre el commit.
"""

import json
import os
import sys
import time

from cognia.tx import bandas, claves, commit, gates
from cognia.tx import libro as almacen
from cognia.tx.errores import LibroCaido

# La sesion viva. UN diccionario, un solo dueno.
_SESION = {"s": None}

# El enganche de `registrar_tool` es idempotente: engancharlo dos veces
# apilaria dos envoltorios y el segundo veria el ciclo del primero.
_ENGANCHE = {"original": None}

ENV = "COGNIA_TX"

# Presupuesto por defecto de `/tx iniciar` (ESPEC 2.2: un ciclo son ~8 pasos).
PASOS_DEFECTO = 8
HORAS_DEFECTO = 12


def _aviso_degradado(motivo):
    """Toda degradacion se dice. Prohibido el `except: pass` mudo."""
    try:
        sys.stderr.write("[TX] driver degradado: %s\n" % motivo)
    except Exception:
        # El unico `pass` del fichero, y es el del canal de avisos: si stderr
        # esta cerrado no queda donde quejarse de que no se puede uno quejar.
        pass


def activo():
    """El flag. El env manda; la config persistida es el respaldo.

    Delega en `tx.flag`: tener la lectura duplicada aqui es como se llego a que
    el CLI dijera ACTIVO y el interceptor no escribiera nada (una clave
    distinta entre modulos, tests verdes y cero salidas en produccion).
    """
    from cognia.tx.flag import activo as _flag
    return _flag()


def activa():
    """La sesion TX viva, o None. NUNCA lanza: quien pregunta suele ser una
    linea de estado del REPL."""
    return _SESION["s"]


def ciclo_actual():
    ses = _SESION["s"]
    return int(ses["ciclo"]) if ses else 0


# --------------------------------------------------------------- enganche

def enganchar():
    """Envuelve `libro.registrar_tool` para que los eventos lleven el ciclo.

    Devuelve True si engancho ahora, False si ya estaba. Idempotente.
    """
    if _ENGANCHE["original"] is not None:
        return False
    original = almacen.registrar_tool

    def _con_ciclo(evento, ctx=None):
        ses = _SESION["s"]
        if ses is not None:
            ctx = dict(ctx or {})
            # Si el llamador YA trae ciclo, manda el suyo: un subagente con su
            # propio contador no puede ser pisado por el ciclo del padre.
            ctx.setdefault("_tx_ciclo", int(ses["ciclo"]))
            ses["tools_del_ciclo"] = int(ses.get("tools_del_ciclo") or 0) + 1
            # EL PRESUPUESTO DE PASOS SE CUENTA AQUI. `paso()` es la API, pero
            # no la llamaba nadie desde el REPL ni desde el bucle (grep: solo
            # el experimento e0), asi que `/tx estado` ensenaba "(0/8 pasos)"
            # congelado para siempre y `--pasos N` era decorativo. Una llamada
            # a tool ES un paso del agente, y este envoltorio ya corre en
            # todas. Sigue sin DISPARAR el commit solo -- eso es cablear el
            # bucle, y el panel lo dice en voz alta en vez de simularlo.
            ses["pasos_del_ciclo"] = int(ses.get("pasos_del_ciclo") or 0) + 1
        return original(evento, ctx=ctx)

    _ENGANCHE["original"] = original
    almacen.registrar_tool = _con_ciclo
    return True


def desenganchar():
    if _ENGANCHE["original"] is None:
        return False
    almacen.registrar_tool = _ENGANCHE["original"]
    _ENGANCHE["original"] = None
    return True


def envolver_bucle(bucle):
    """Envuelve el bucle del agente: engancha antes y deja la sesion viva.

    No toca el bucle por dentro (regla del repo: no reformatear codigo ajeno).
    Lo unico que hace falta desde fuera es que el ciclo del driver llegue a los
    eventos, y eso lo da `enganchar()`.
    """
    def _envuelto(*a, **kw):
        if not activo() or _SESION["s"] is None:
            return bucle(*a, **kw)
        enganchar()
        return bucle(*a, **kw)
    return _envuelto


# ---------------------------------------------------------------- siembra

def _prov(fn, base=None):
    return {"tipo": "derivada", "fn": str(fn), "base": list(base or [])}


def _spec_criterio(cmd, workspace=None):
    """Un criterio de `/tx iniciar` -> spec de GoalContract.

    `command_succeeds` y no `file_exists`: la ESPEC 9.4 puerta 1 exige un
    criterio EJECUTABLE. Un fichero que existe se puede crear vacio; un exit 0
    hay que ganarselo.
    """
    return {"kind": "command_succeeds", "command": str(cmd),
            "description": str(cmd)[:120]}


def iniciar(objetivo, criterios=(), restricciones=(), pasos=PASOS_DEFECTO,
            horas=HORAS_DEFECTO, workspace=None, task_id=None, semilla=None,
            k_trazadores=4):
    """FASE 0 -- SIEMBRA (ESPEC 2.1). Abre el LIBRO y escribe la banda P.

    Lanza `ValueError` sin criterio verificable: es la PUERTA 1 de la ESPEC
    9.4. Sin criterio, G5 no puede medir monotonia y el sistema entero se
    queda sin la unica senal que no viene de un LLM. Empezar igualmente seria
    montar la maquinaria de verificacion sobre nada que verificar.
    """
    objetivo = str(objetivo or "").strip()
    if not objetivo:
        raise ValueError("/tx iniciar necesita un objetivo entre comillas")
    criterios = [str(c).strip() for c in (criterios or []) if str(c).strip()]
    if not criterios:
        raise ValueError(
            "/tx iniciar exige al menos un --criterio EJECUTABLE (un comando "
            "cuyo exit 0 signifique 'hecho'). Sin el, G5 no mide monotonia y "
            "el brazo verificado del sistema no existe (ESPEC 9.4 puerta 1)")
    restricciones = [str(r).strip() for r in (restricciones or []) if str(r).strip()]

    if _SESION["s"] is not None:
        raise ValueError("ya hay una tarea TX abierta (%s). Cierrala con "
                         "/tx cerrar antes de abrir otra: dos tareas vivas "
                         "significan dos libros y un sha_P0 ambiguo"
                         % _SESION["s"]["task_id"])

    task_id = str(task_id or time.strftime("tx-%Y%m%d-%H%M%S"))
    ws = str(workspace) if workspace else _workspace_defecto()

    # PUERTA 1 bis: EL CRITERIO SE CORRE UNA VEZ, ANTES DE SELLAR LA BANDA P.
    # Nada validaba jamas que el criterio fuese ejecutable, y la banda P no se
    # puede tocar despues (su sha es la referencia de G1). La secuencia del
    # DIA 1 de la ESPEC 14.2 sembraba `pytest tests/estado`, un path que NO
    # EXISTE en el repo, y G5 lo dio por `PASA` tras tirar 5465 ms: un criterio
    # invalido gastando el presupuesto de "criterio barato" y sin decir que el
    # path no estaba ni que el exit fue 4. Aqui se mide UNA vez y se cuenta:
    # exit, coste y si ya esta verde antes de empezar (un criterio que ya pasa
    # no puede medir progreso). Solo se NIEGA a sellar si ninguno llego a
    # ejecutarse -- un criterio en rojo es lo normal al abrir una tarea.
    contrato = _contrato(objetivo, criterios, ws, task_id)
    siembra = _medir_criterios(contrato)
    if not siembra["ejecutados"]:
        raise ValueError(
            "ninguno de los %d criterio(s) llego a EJECUTARSE (%s). Un "
            "criterio que no corre no puede medir progreso, y la banda P se "
            "sella con el sha_P0 y ya no se toca. Arregla el comando y vuelve "
            "a intentarlo" % (len(criterios),
                              "; ".join(siembra["motivos"])[:300]))

    libro = almacen.abrir(task_id)

    # --- banda P: objetivo, restricciones, criterios, definicion de hecho.
    # origen='usuario' y conf 1,00: lo dijo el dueno, no lo infirio nadie.
    libro.append({"t": "objetivo", "op": "add", "banda": "P", "id": "P-OBJ",
                  "quien": "usuario", "origen": "usuario", "texto": objetivo[:400],
                  "estado": "verificado",
                  "prov": _prov("driver.iniciar", ["cli:/tx iniciar"])}, ciclo=0)
    for i, r in enumerate(restricciones, 1):
        libro.append({"t": "restriccion", "op": "add", "banda": "P",
                      "id": "P-R%02d" % i, "quien": "usuario", "origen": "usuario",
                      "texto": r[:400], "estado": "verificado",
                      "prov": _prov("driver.iniciar", ["cli:--restriccion"])},
                     ciclo=0)
    for i, c in enumerate(criterios, 1):
        libro.append({"t": "criterio", "op": "add", "banda": "P",
                      "id": "P-C%02d" % i, "quien": "usuario", "origen": "usuario",
                      "clave": "cmd:" + c[:120], "valor": None,
                      "texto": ("criterio %d: %s" % (i, c))[:400],
                      "estado": "hipotesis",
                      "prov": _prov("driver.iniciar", ["cli:--criterio"])},
                     ciclo=0)
    libro.append({"t": "definicion", "op": "add", "banda": "P", "id": "P-DOD",
                  "quien": "usuario", "origen": "usuario",
                  "texto": ("HECHO = los %d criterios pasan a la vez, medidos "
                            "por GoalContract con cwd=%s" % (len(criterios), ws))[:400],
                  "estado": "verificado",
                  "prov": _prov("driver.iniciar", ["cli:--criterio"])}, ciclo=0)

    # --- banda T: los trazadores. Van al LIBRO *y* al estado del canal: el
    # LIBRO los proyecta, el canal los corrige contra la RESPUESTA (G2). Son
    # los dos lados de la misma medida y por eso se siembran juntos.
    estado_canal = _sembrar_canal(objetivo, restricciones, k_trazadores, semilla)
    for trz in estado_canal.get("trazadores") or []:
        libro.append({"t": "trazador", "op": "add", "banda": "T",
                      "id": trz["id"], "quien": "harness", "origen": "derivado",
                      "texto": str(trz["texto"])[:400], "estado": "verificado",
                      "prov": _prov("canal.sembrar_trazadores",
                                    ["semilla:%s" % semilla])}, ciclo=0)

    eventos = libro.leer()
    sha_p0 = bandas.sha_banda_permanente(eventos)
    libro.escribir_cabecera(bandas.render_banda_permanente(eventos))

    ses = {
        "task_id": task_id,
        "objetivo": objetivo,
        "criterios": criterios,
        "restricciones": restricciones,
        "pasos": max(1, int(pasos or PASOS_DEFECTO)),
        "horas": float(horas or HORAS_DEFECTO),
        "workspace": ws,
        "sha_p0": sha_p0,
        "libro": libro,
        # El MISMO contrato que ya corrio en la siembra: reconstruirlo aqui
        # tiraria el `coste_ms` medido y G5 volveria a pagar los criterios
        # caros en el ciclo 1.
        "contrato": contrato,
        "siembra": siembra,
        "estado_canal": estado_canal,
        "salud": commit.salud_nueva(),
        "ciclo": 1,
        "pasos_del_ciclo": 0,
        "tools_del_ciclo": 0,
        "tools_en_vuelo": 0,
        "forzar_ancho": False,
        "t0": time.time(),
        "maquinaria_ms": 0.0,
        "ventana_inicio": None,
        "ventana": None,
        "history": None,
        "lineas": [],
    }
    _SESION["s"] = ses
    enganchar()
    _guardar_meta(ses)
    return ses


def _workspace_defecto():
    try:
        from cognia.agents import goal_contract as gc
        return gc.workspace_por_defecto() or os.getcwd()
    except Exception as exc:
        _aviso_degradado("no pude resolver el workspace por defecto: %r; uso "
                         "el CWD del proceso" % exc)
        return os.getcwd()


def _medir_criterios(contrato):
    """Corre los criterios UNA vez y devuelve lo medido de cada uno.

    Se llama en la siembra, antes de sellar la banda P. `check()` entero (no
    `solo_baratos`): aqui es justo cuando hay que pagar el coste, porque es la
    unica pasada que MIDE `coste_ms` -- el numero del que depende despues toda
    la regla del criterio barato de G5.
    """
    out = {"filas": [], "ejecutados": 0, "verdes": 0, "motivos": []}
    try:
        estado = contrato.check()
    except Exception as exc:
        out["motivos"].append("el contrato reviento: %r" % exc)
        return out
    for res in estado.results:
        detalle = str(res.detail or "")
        # "no llego a ejecutarse" = el checker no pudo lanzar el proceso
        # (fichero inexistente, permiso). Un exit != 0 SI es una ejecucion.
        corrio = not detalle.startswith("error:") and not detalle.startswith("unknown kind")
        out["filas"].append({
            "criterio": res.criterion.description,
            "ok": bool(res.satisfied),
            "detalle": detalle,
            "coste_ms": res.coste_ms,
            "timeout": bool(res.timeout),
            "corrio": corrio,
        })
        if corrio:
            out["ejecutados"] += 1
        else:
            out["motivos"].append("%s -> %s" % (res.criterion.description[:60],
                                                detalle[:80]))
        if res.satisfied:
            out["verdes"] += 1
    return out


def _contrato(objetivo, criterios, workspace, task_id):
    from cognia.agents.goal_contract import GoalContract
    return GoalContract.from_spec(
        objetivo, [_spec_criterio(c) for c in criterios],
        session_id=str(task_id), workspace=workspace)


def _sembrar_canal(objetivo, restricciones, k, semilla):
    from cognia.estado import canal
    est = canal.EstadoVerificado(objetivo=objetivo)
    for r in restricciones:
        canal.anotar_restriccion(est, r)
    canal.sembrar_trazadores(est, k=int(k), semilla=semilla)
    return est


def _meta_ruta(ses):
    return os.path.join(almacen.dir_tarea(ses["task_id"]), "sesion.json")


def _guardar_meta(ses):
    """La metadata de la sesion, para que `/tx estado` sobreviva a un reinicio
    del REPL. NO es fuente de verdad de nada: todo lo que decide sale del
    LIBRO. Si esto no se puede escribir se avisa y se sigue -- perder el
    marcador no es perder la memoria."""
    meta = {k: ses[k] for k in ("task_id", "objetivo", "criterios",
                                "restricciones", "pasos", "horas", "workspace",
                                "sha_p0", "ciclo")}
    meta["salud"] = {k: v for k, v in ses["salud"].items() if k != "historial"}
    meta["estado_canal"] = ses["estado_canal"]
    meta["t0"] = ses["t0"]
    try:
        with open(_meta_ruta(ses), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=True, indent=1)
    except Exception as exc:
        _aviso_degradado("no pude guardar sesion.json (%r): /tx estado no "
                         "sobrevivira a un reinicio del REPL" % exc)


def reanudar(task_id):
    """Reabre una tarea ya sembrada. El sha_P0 se RECALCULA del LIBRO y se
    compara con el guardado: si no casan, la banda P cambio en disco y eso se
    dice AQUI, no dos gates mas tarde."""
    if _SESION["s"] is not None:
        raise ValueError("ya hay una tarea TX abierta (%s)"
                         % _SESION["s"]["task_id"])
    ruta = os.path.join(almacen.dir_tarea(task_id), "sesion.json")
    if not os.path.exists(ruta):
        raise ValueError("no hay sesion.json para '%s' en %s"
                         % (task_id, almacen.dir_tarea(task_id)))
    with open(ruta, "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    libro = almacen.abrir(task_id)
    eventos = libro.leer()
    sha_ahora = bandas.sha_banda_permanente(eventos)
    ses = {
        "task_id": task_id,
        "objetivo": meta.get("objetivo", ""),
        "criterios": list(meta.get("criterios") or []),
        "restricciones": list(meta.get("restricciones") or []),
        "pasos": int(meta.get("pasos") or PASOS_DEFECTO),
        "horas": float(meta.get("horas") or HORAS_DEFECTO),
        "workspace": meta.get("workspace") or _workspace_defecto(),
        "sha_p0": meta.get("sha_p0") or sha_ahora,
        "libro": libro,
        "contrato": _contrato(meta.get("objetivo", ""),
                              list(meta.get("criterios") or []),
                              meta.get("workspace"), task_id),
        "estado_canal": meta.get("estado_canal") or {},
        "salud": dict(commit.salud_nueva(), **(meta.get("salud") or {})),
        "ciclo": int(meta.get("ciclo") or 1),
        "pasos_del_ciclo": 0,
        "tools_del_ciclo": 0,
        "tools_en_vuelo": 0,
        "forzar_ancho": False,
        "t0": float(meta.get("t0") or time.time()),
        "maquinaria_ms": 0.0,
        "ventana_inicio": None,
        "ventana": None,
        "history": None,
        "lineas": [],
    }
    ses["salud"].setdefault("historial", [])
    _SESION["s"] = ses
    enganchar()
    if sha_ahora != ses["sha_p0"]:
        _aviso_degradado(
            "el sha de la banda P al reanudar (%s) NO casa con el sembrado "
            "(%s): la banda P cambio en disco. G1 va a abortar todos los "
            "commits hasta que se explique" % (sha_ahora, ses["sha_p0"]))
    return ses


def cerrar():
    """Cierra la sesion. Deja constancia en el LIBRO ANTES de soltar nada."""
    ses = _SESION["s"]
    if ses is None:
        return None
    try:
        commit._append_tx(ses["libro"], ses["ciclo"],
                          "cierre de la tarea %s tras %d ciclo(s)"
                          % (ses["task_id"], ses["salud"].get("ciclos") or 0),
                          clave="cfg:tx.cierre", valor=ses["task_id"])
    except LibroCaido as exc:
        _aviso_degradado("no pude dejar constancia del cierre: %s" % exc)
    _guardar_meta(ses)
    _SESION["s"] = None
    desenganchar()
    almacen.cerrar()
    return ses["task_id"]


# ------------------------------------------------------------------- ctx

def ctx(responder=None, destruir=None, criterios_satisfechos=None):
    """El `ctx` que comen `commit.preparar` y `commit.ejecutar`.

    Se construye aqui y en un solo sitio: dos sitios armando este dict es como
    un gate acaba mirando un `sha_p0` distinto del que se sembro.
    """
    ses = _SESION["s"]
    if ses is None:
        raise ValueError("no hay tarea TX abierta (/tx iniciar)")
    return {
        "libro": ses["libro"],
        "ciclo": ses["ciclo"],
        "sha_p0": ses["sha_p0"],
        "workspace": ses["workspace"],
        "contrato": ses["contrato"],
        "estado_canal": ses["estado_canal"],
        "salud": ses["salud"],
        "tools_en_vuelo": int(ses.get("tools_en_vuelo") or 0),
        "criterios_satisfechos": criterios_satisfechos or (),
        "responder": responder,
        "destruir": destruir,
    }


def responder_por_defecto(max_tokens=1024):
    """El canal de respuesta de c3: UNA llamada FRESCA al cerebro.

    Una llamada nueva a `completar` ES la sesion nueva -- no hay historial que
    arrastrar. Eso es justo lo que Q1..Q3 quieren medir: si el modelo puede
    reconstruir el contrato leyendo SOLO la proyeccion.
    """
    def _responder(texto):
        from cognia.agent.chat_client import completar
        r = completar(
            [{"role": "system",
              "content": "Responde SOLO con las citas literales pedidas."},
             {"role": "user", "content": texto}],
            max_tokens=max_tokens, temperature=0.0, via="tx_control")
        if getattr(r, "error", ""):
            _aviso_degradado("la sesion nueva no contesto: %s" % r.error)
            return ""
        # `.texto`, NO `.content`: RespuestaChat no tiene `content` y el
        # getattr con defecto devolvia "" SIEMPRE. Con eso, Q1..Q3 sacaban
        # 0/3 y G2 suspendia por "respuesta VACIA" en cada commit: el sistema
        # entero caia a MODO ANCHO sin que nada dijera por que. Es el vacio
        # silencioso, cazado por E0 al cablear el brazo TX (2026-08-19).
        texto = getattr(r, "texto", "") or ""
        if not texto.strip():
            _aviso_degradado("la sesion nueva contesto VACIO (finish_reason=%s, "
                             "usage=%s)" % (getattr(r, "finish_reason", "?"),
                                            getattr(r, "usage", {})))
        return texto
    return _responder


def destruir_por_defecto(ses=None):
    """El destructor del MVP: `history = [system, proyeccion]`.

    Sin bucle enganchado no hay ventana real que destruir, y decir HECHO sobre
    una ventana que nadie toco seria mentir en la direccion comoda. Por eso
    esto GUARDA la ventana nueva en la sesion y la deja visible en `/tx estado`
    -- se ve exactamente que quedo vivo.
    """
    ses = ses or _SESION["s"]

    def _destruir(proyeccion):
        if ses is None:
            raise ValueError("no hay sesion donde aplicar el reset")
        ses["history"] = [
            {"role": "system", "content": "Tarea larga TX. La memoria vive en "
                                          "el LIBRO; esto es su proyeccion."},
            {"role": "user", "content": proyeccion},
        ]
        ses["ventana"] = _tokens(proyeccion)
    return _destruir


def _tokens(texto):
    return (len(str(texto or "")) + 3) // 4


def marcar_ventana(tokens):
    """El bucle dice cuanto ocupa la ventana. Sin esto la linea del ciclo lo
    dice: `ctx sin-medidor`, en vez de inventarse un numero."""
    ses = _SESION["s"]
    if ses is None:
        return
    if ses.get("ventana_inicio") is None:
        ses["ventana_inicio"] = int(tokens)
    ses["ventana"] = int(tokens)


# -------------------------------------------------------------- los ciclos

def paso():
    """UN paso del agente dentro del ciclo. Devuelve si toca intentar commit.

    EL DISPARADOR es el presupuesto de pasos (ESPEC 9.1); LA COMPUERTA la
    corre el commit. Los dos por separado: un disparador que ademas decidiera
    seria un reset que se aprueba a si mismo.

    OJO: en el REPL el contador lo lleva `enganchar()._con_ciclo` (una llamada
    a tool = un paso). Esta funcion es para un bucle que quiera contar pasos
    que NO son tools; llamarla ademas desde ese bucle contaria doble.
    """
    ses = _SESION["s"]
    if ses is None:
        return False
    ses["pasos_del_ciclo"] = int(ses.get("pasos_del_ciclo") or 0) + 1
    return ses["pasos_del_ciclo"] >= int(ses["pasos"])


def _cerrar_ciclo(ses, res):
    ses["ciclo"] = int(ses["ciclo"]) + 1
    ses["pasos_del_ciclo"] = 0
    ses["tools_del_ciclo"] = 0
    ses["forzar_ancho"] = False
    if res.get("destruido"):
        ses["ventana_inicio"] = ses.get("ventana")
    _guardar_meta(ses)


def probar():
    """`/tx probar`: G1,G3,G4,G5,G6 AHORA, contra el contexto vivo, SIN
    resetear y SIN tocar el LIBRO."""
    ses = _SESION["s"]
    if ses is None:
        raise ValueError("no hay tarea TX abierta (/tx iniciar)")
    t0 = time.perf_counter()
    prep = commit.preparar(ctx(), topes=dict(ses["salud"].get("topes") or {}))
    ses["maquinaria_ms"] += (time.perf_counter() - t0) * 1000.0
    return prep


def commit_ya(responder=None, destruir=None, criterios_satisfechos=None):
    """`/tx commit`: fuerza el 2PC completo AHORA.

    Si `/tx ancho` marco el ciclo, no se intenta el commit: se cuenta el ancho
    y se dice. Forzar un commit sobre un ciclo que el dueno declaro ancho seria
    ignorar la orden mas reciente.
    """
    ses = _SESION["s"]
    if ses is None:
        raise ValueError("no hay tarea TX abierta (/tx iniciar)")
    t0 = time.perf_counter()
    if ses.get("forzar_ancho"):
        res = _ancho_forzado(ses)
    else:
        c = ctx(responder=responder or responder_por_defecto(),
                destruir=destruir or destruir_por_defecto(ses),
                criterios_satisfechos=criterios_satisfechos)
        res = commit.ejecutar(c)
    ses["maquinaria_ms"] += (time.perf_counter() - t0) * 1000.0
    ciclo = ses["ciclo"]
    linea = linea_ciclo(res, ciclo)
    ses["lineas"].append(linea)
    ses["lineas"] = ses["lineas"][-40:]
    _cerrar_ciclo(ses, res)
    res["linea"] = linea
    return res


def forzar_ancho():
    """`/tx ancho`: el proximo commit de ESTE ciclo no destruye."""
    ses = _SESION["s"]
    if ses is None:
        raise ValueError("no hay tarea TX abierta (/tx iniciar)")
    ses["forzar_ancho"] = True
    return ses["ciclo"]


def _ancho_forzado(ses):
    """MODO ANCHO pedido a mano. Se contabiliza EXACTAMENTE igual que el que
    dispara la escalera: si el ancho manual no contase, el tope del 10 % se
    esquivaria tecleando, y el tope existe porque el brazo ancho degrada en
    silencio pasados ~20 ciclos."""
    prep = commit.preparar(ctx(), topes=dict(ses["salud"].get("topes") or {}))
    salud = ses["salud"]
    salud["ciclos"] = int(salud.get("ciclos") or 0) + 1
    puede, porque = commit._puede_ancho(salud)
    commit._contar_ancho(salud)
    commit._append_tx(ses["libro"], ses["ciclo"],
                      "ANCHO forzado a mano (/tx ancho)",
                      clave="cfg:tx.ancho", valor=salud["anchos_seguidos"])
    detalle = "ANCHO forzado a mano: no destruyo"
    if not puede:
        detalle += (". OJO: el presupuesto de anchos ya estaba agotado (%s); "
                    "el proximo commit automatico dara HARD_STOP" % porque)
    return commit._resultado("ANCHO", "prepare", False, detalle, prep, salud,
                             anchos_seguidos=salud["anchos_seguidos"],
                             forzado=True)


# ------------------------------------------------------------- los paneles

def ratio_maquinaria():
    """Ratio de MAQUINARIA: ms gastados en gates+proyeccion+Q sobre la pared.

    Es la definicion-de-hecho (c) del MVP y tiene que quedar por debajo del
    15 %. Se MIDE con perf_counter en cada llamada al commit; no se declara.
    """
    ses = _SESION["s"]
    if ses is None:
        return None
    pared = max(1e-6, (time.time() - float(ses["t0"])) * 1000.0)
    return 100.0 * float(ses.get("maquinaria_ms") or 0.0) / pared


def panel_estado():
    """Los datos de `/tx estado`. Devuelve un dict; el formateo es del CLI."""
    ses = _SESION["s"]
    if ses is None:
        return None
    diag = {}
    eventos = ses["libro"].leer(diag=diag)
    informe = {}
    bandas.proyectar(eventos, topes=dict(ses["salud"].get("topes") or {}),
                     informe=informe)
    estado = bandas.fold(eventos)
    return {
        "diag": diag,
        "task_id": ses["task_id"],
        "objetivo": ses["objetivo"],
        "criterios": ses["criterios"],
        "restricciones": ses["restricciones"],
        "workspace": ses["workspace"],
        "sha_p0": ses["sha_p0"],
        "sha_p_ahora": bandas.sha_banda_permanente(eventos),
        "ciclo": ses["ciclo"],
        "pasos": ses["pasos"],
        "pasos_del_ciclo": ses.get("pasos_del_ciclo") or 0,
        "presupuesto_agotado": (int(ses.get("pasos_del_ciclo") or 0)
                                >= int(ses["pasos"])),
        "bucle_enganchado": ses.get("history") is not None,
        "horas": ses["horas"],
        "horas_gastadas": (time.time() - float(ses["t0"])) / 3600.0,
        "eventos": len(eventos),
        "vivos": len(estado["vivos"]),
        "invalidados": len(estado["invalidados"]),
        "salud": ses["salud"],
        "informe": informe,
        "ratio": ratio_maquinaria(),
        "ventana": ses.get("ventana"),
        "lineas": list(ses.get("lineas") or []),
        "forzar_ancho": bool(ses.get("forzar_ancho")),
    }


def panel_bandas():
    """`/tx bandas`: tokens por banda y QUE se esta cayendo por el tope."""
    ses = _SESION["s"]
    if ses is None:
        return None
    eventos = ses["libro"].leer()
    informe = {}
    topes = dict(bandas.TOPES)
    topes.update(ses["salud"].get("topes") or {})
    bandas.proyectar(eventos, topes=topes, informe=informe)
    filas = []
    for b in bandas.ORDEN:
        d = (informe.get("bandas") or {}).get(b) or {}
        filas.append({
            "banda": b,
            "tokens": d.get("tokens"),
            "tope": bandas.TOPE_P if b == "P" else topes.get(b),
            "filas": d.get("filas"),
            "fuera": d.get("fuera") or 0,
        })
    return {"filas": filas, "total": informe.get("tokens"),
            "sha": informe.get("sha"),
            "p_desborda": informe.get("p_desborda")}


# --------------------------------------------------------------- /tx mutar

def _mut_restriccion_borrada(eventos, ses):
    """Mutacion 1: se borra una fila de la banda P. G1 tiene que abortar."""
    fuera = None
    mut = []
    for e in eventos:
        if fuera is None and e.get("banda") == "P" and e.get("t") == "restriccion":
            fuera = e
            continue
        mut.append(e)
    if fuera is None:
        # Sin restricciones se borra el objetivo: la mutacion tiene que existir
        # de verdad, no "no aplica". Un drill que se salta a si mismo no mide.
        mut = [e for e in eventos if not (e.get("banda") == "P"
                                          and e.get("t") == "objetivo")]
        fuera = {"id": "P-OBJ"}
    sano = gates.g1_banda_permanente(eventos, ses["sha_p0"])
    roto = gates.g1_banda_permanente(mut, ses["sha_p0"])
    return {"nombre": "restriccion borrada", "gate": "G1",
            "que": "quito %s de la banda P" % fuera.get("id"),
            "sano": sano, "mutado": roto}


def _mut_trazador_cambiado(eventos, ses):
    """Mutacion 2: un digito del trazador cambia en LA RESPUESTA. G2 aborta.

    Se muta la RESPUESTA y no la proyeccion a proposito: G2 se mide sobre lo
    que escribio el modelo (ESPEC 6.5). Mutar la proyeccion mediria la
    tautologia que P0-4 vino a eliminar.
    """
    trzs = (ses["estado_canal"] or {}).get("trazadores") or []
    sana = " ".join(t.get("texto", "") for t in trzs)
    if not trzs:
        return {"nombre": "digito de trazador cambiado", "gate": "G2",
                "que": "NO HAY TRAZADORES SEMBRADOS",
                "sano": gates.veredicto("G2", False, "0 trazadores"),
                "mutado": gates.veredicto("G2", False, "0 trazadores")}
    victima = trzs[0]
    ident = str(victima.get("id"))
    # Un solo caracter hexadecimal distinto: si el gate tolerase esto, un
    # trazador reconstruido de memoria pasaria por sobreviviente.
    ult = ident[-1]
    nuevo = "0" if ult != "0" else "1"
    mala = sana.replace(ident, ident[:-1] + nuevo)
    sano = gates.g2_trazadores(ses["estado_canal"], sana)
    roto = gates.g2_trazadores(ses["estado_canal"], mala)
    return {"nombre": "digito de trazador cambiado", "gate": "G2",
            "que": "%s -> %s en la respuesta" % (ident, ident[:-1] + nuevo),
            "sano": sano, "mutado": roto}


def _mut_sha_falseado(eventos, ses):
    """Mutacion 3: el sha de un artefacto vivo se falsea. G3 aborta.

    Si la tarea todavia no tiene artefactos, se siembra uno REAL (un fichero
    en el directorio de la tarea con su sha medido del disco) en vez de
    declarar "no aplica": un drill que no corre no prueba nada.
    """
    art = [e for e in eventos if e.get("banda") == "A"
           and str(e.get("clave") or "").startswith("archivo:")]
    sembrado = None
    if not art:
        ruta = os.path.join(almacen.dir_tarea(ses["task_id"]), "mutar_testigo.txt")
        try:
            with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("testigo de /tx mutar\n")
        except Exception as exc:
            return {"nombre": "sha falseado", "gate": "G3",
                    "que": "no pude sembrar el testigo: %r" % exc,
                    "sano": gates.veredicto("G3", False, "sin testigo"),
                    "mutado": gates.veredicto("G3", False, "sin testigo")}
        sembrado = {
            "t": "fichero", "op": "add", "banda": "A", "id": "A-MUT",
            "quien": "harness", "origen": "medido", "estado": "verificado",
            "clave": "archivo:" + ruta.replace("\\", "/"),
            "valor": claves.sha_de_fichero(ruta),
            "texto": "testigo efimero de /tx mutar",
            "prov": {"tipo": "ejecutada", "fn": "driver.mutar",
                     "cmd": "sha_de_fichero", "base": [ruta]},
        }
        eventos = list(eventos) + [dict(sembrado, n=10 ** 9, sha="", prev="")]
        art = [eventos[-1]]

    victima = art[0]
    real = victima.get("valor")
    falso = ("0" * 14) if real != "0" * 14 else ("1" * 14)
    mut = [dict(e, valor=falso) if e is victima else e for e in eventos]
    sano = gates.g3_artefactos(eventos, workspace=ses["workspace"])
    roto = gates.g3_artefactos(mut, workspace=ses["workspace"])
    if sembrado is not None:
        try:
            os.remove(os.path.join(almacen.dir_tarea(ses["task_id"]),
                                   "mutar_testigo.txt"))
        except Exception as exc:
            _aviso_degradado("no pude borrar el testigo de /tx mutar: %r" % exc)
    return {"nombre": "sha falseado", "gate": "G3",
            "que": "%s: %s -> %s" % (victima.get("id"), real, falso),
            "sano": sano, "mutado": roto}


def mutar():
    """`/tx mutar`: corrompe la proyeccion A PROPOSITO y EXIGE que el gate aborte.

    LA PIEZA QUE HACE HONESTO AL SISTEMA. Un gate que nunca aborta es una
    AVERIA, no salud: mide cero y aprueba todo, y desde fuera se ve identico a
    un sistema sano. Cada mutacion se corre DOS veces -- sana y mutada -- y
    las dos tienen que dar lo suyo: si el gate suspende tambien la version
    sana, no discrimina, y eso tampoco es un gate.

    Nada de esto toca el LIBRO: las mutaciones son copias en RAM. Lo unico que
    se escribe es el RESULTADO del drill, para que quede auditado.
    """
    ses = _SESION["s"]
    if ses is None:
        raise ValueError("no hay tarea TX abierta (/tx iniciar)")
    eventos = ses["libro"].leer()
    pruebas = [
        _mut_restriccion_borrada(eventos, ses),
        _mut_trazador_cambiado(eventos, ses),
        _mut_sha_falseado(eventos, ses),
    ]
    for p in pruebas:
        p["aborta"] = (not p["mutado"]["ok"])
        p["discrimina"] = bool(p["sano"]["ok"]) and p["aborta"]
    abortan = sum(1 for p in pruebas if p["aborta"])
    discriminan = sum(1 for p in pruebas if p["discrimina"])
    ok = (abortan == len(pruebas)) and (discriminan == len(pruebas))
    try:
        commit._append_tx(ses["libro"], ses["ciclo"],
                          "mutar: abortan %d/%d, discriminan %d/%d"
                          % (abortan, len(pruebas), discriminan, len(pruebas)),
                          clave="cfg:tx.mutar", valor=abortan)
    except LibroCaido as exc:
        _aviso_degradado("no pude dejar constancia del drill: %s" % exc)
    return {"pruebas": pruebas, "abortan": abortan, "discriminan": discriminan,
            "total": len(pruebas), "ok": ok}


# ---------------------------------------------------------------- /tx vram

def leer_vram():
    """VRAM usada/total en MiB, medida con nvidia-smi. None si no hay GPU.

    Se MIDE, no se declara. Y si no se puede medir se devuelve None con el
    motivo: 'no hay GPU' y 'no pude preguntar' piden decisiones distintas.
    """
    import subprocess
    try:
        salida = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.used,memory.total,name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return None, "nvidia-smi no esta en el PATH (sin GPU NVIDIA o sin driver)"
    except Exception as exc:
        return None, "no pude preguntar a nvidia-smi: %r" % exc
    if salida.returncode != 0:
        return None, ("nvidia-smi devolvio exit %d: %s"
                      % (salida.returncode, (salida.stderr or "").strip()[:160]))
    linea = (salida.stdout or "").strip().splitlines()
    if not linea:
        return None, "nvidia-smi no devolvio ninguna GPU"
    trozos = [t.strip() for t in linea[0].split(",")]
    try:
        return {"usada": int(trozos[0]), "total": int(trozos[1]),
                "gpu": trozos[2] if len(trozos) > 2 else "?"}, ""
    except Exception as exc:
        return None, "no entendi la salida de nvidia-smi (%s): %r" % (linea[0], exc)


# El axioma MEDIDO: el KV se reserva ENTERO al cargar el modelo. Destruir la
# ventana no devuelve un solo MiB. `/tx vram --verificar` existe para que eso
# se pueda COMPROBAR en esta maquina en vez de creerselo.
DELTA_VRAM_ESPERADO_PCT = 3.0


def vram_verificar():
    """`/tx vram --verificar`: mide la VRAM antes y despues de un reset.

    Lo que se espera es DELTA ~0: la lobotomia NO ahorra VRAM porque el KV ya
    esta reservado entero. Si sale un ahorro grande, el axioma es falso EN
    ESTA maquina y hay que re-medirlo -- eso tambien es un resultado.
    """
    antes, motivo = leer_vram()
    ses = _SESION["s"]
    out = {"antes": antes, "motivo": motivo, "despues": None, "delta_pct": None,
           "reset": False, "esperado_pct": DELTA_VRAM_ESPERADO_PCT}
    if antes is None:
        return out
    if ses is None:
        out["motivo"] = ("sin tarea TX abierta no hay ventana que destruir: "
                         "solo se lee la VRAM actual (/tx iniciar para el "
                         "delta real)")
        return out
    prep = commit.preparar(ctx())
    destruir_por_defecto(ses)(prep["proyeccion"])
    out["reset"] = True
    despues, motivo2 = leer_vram()
    out["despues"] = despues
    if despues is None:
        out["motivo"] = motivo2
        return out
    out["delta_pct"] = (100.0 * (antes["usada"] - despues["usada"])
                        / max(1, antes["usada"]))
    out["ok"] = abs(out["delta_pct"]) <= DELTA_VRAM_ESPERADO_PCT
    return out


# ------------------------------------------------------ la linea del ciclo

def _k(tokens):
    if tokens is None:
        return "?"
    if tokens < 1000:
        return "%d" % tokens
    return ("%.1fk" % (tokens / 1000.0)).replace(".", ",")


def linea_ciclo(res, ciclo=None):
    """LA linea por ciclo del REPL (ESPEC 14.2).

        [TX] c41 COMMIT TX-0041 ok . P 9f3c1a . trz 6/6 . art 12/12 . Q 3/3
             . crit 4/7 . 1,4 s . maq 4,1 % . ctx 3,5k->11,8k

    Separador ' . ' y no el punto medio de la ESPEC: el codigo de este repo es
    ASCII puro, y `commit.linea_repl` ya usa ese separador (igualar al vecino).
    Lo que NO se puede medir se dice ('sin-medidor'), nunca se rellena con un
    numero plausible.
    """
    ses = _SESION["s"]
    ciclo = ciclo if ciclo is not None else (ses["ciclo"] if ses else 0)
    inf = res.get("informe") or {}
    g = {v["gate"]: v for v in (res.get("gates") or [])}
    salida = res.get("salida")
    etiqueta = {"HECHO": "COMMIT", "ANCHO": "ANCHO", "HARD_STOP": "HARD_STOP"}.get(
        salida, str(salida))
    trozos = ["[TX] c%d %s" % (ciclo, etiqueta)]
    corrupto = commit._corrupto(res)
    if corrupto:
        # PRIMERO. Todo lo que viene detras se calculo sobre un prefijo
        # incompleto del LIBRO, y sin esta linea el unico sintoma era un G6
        # diciendo "0 eventos medidos" -- la causa equivocada.
        trozos.append(corrupto)
    if res.get("tx"):
        trozos[0] += " " + str(res["tx"])
    if salida == "HECHO":
        trozos[0] += " ok"
    if "G1" in g:
        trozos.append("P %s" % str(g["G1"]["datos"].get("sha") or "?")[:6])
    if res.get("g2"):
        d = res["g2"]["datos"]
        trozos.append("trz %s/%s" % (d.get("presentes"), d.get("total")))
    if "G3" in g:
        trozos.append("art %s/%s" % (g["G3"]["datos"].get("ok_n"),
                                     g["G3"]["datos"].get("total")))
    if res.get("q"):
        trozos.append("Q %d/%d" % (res["q"]["aciertos"], res["q"]["total"]))
    if "G5" in g:
        trozos.append("crit %s/%s" % (g["G5"]["datos"].get("progreso"),
                                      g["G5"]["datos"].get("total")))
    ms = (res.get("ms_proy") or 0) + (res.get("ms_gates") or 0)
    trozos.append(("%.1f s" % (ms / 1000.0)).replace(".", ","))
    ratio = ratio_maquinaria()
    trozos.append("maq %s" % (("%.1f %%" % ratio).replace(".", ",")
                              if ratio is not None else "sin-medidor"))
    if ses and ses.get("ventana_inicio") is not None:
        trozos.append("ctx %s->%s" % (_k(ses.get("ventana_inicio")),
                                      _k(ses.get("ventana") or inf.get("tokens"))))
    else:
        trozos.append("ctx sin-medidor")
    if salida != "HECHO":
        trozos.append(str(res.get("detalle") or "")[:160])
    return " . ".join(trozos)
