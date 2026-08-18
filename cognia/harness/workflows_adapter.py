# -*- coding: utf-8 -*-
"""El puente entre el agente y su propio motor de workflows.

POR QUE EXISTE (2026-08-13): `cognia/agent/workflows.py` está completo desde el
2026-08-11 —corrida con journal, presupuesto de tokens, salida estructurada por
schema, resume desde una corrida previa, `paralelo` y `pipeline`— y **nadie lo
llamaba**: ni un comando del REPL ni una herramienta del agente. Una capacidad
que el modelo no puede invocar es una capacidad que no existe, igual que un
schema publicado como prosa. Este módulo la pone a su alcance.

QUE HACE Y QUE NO
El motor ejecuta `agente()`: prompt -> texto (o dict validado contra un schema),
**sin herramientas**. Sirve para repartir TRABAJO DE PENSAR entre varias
llamadas independientes —analizar cinco ficheros, redactar cuatro secciones,
evaluar tres enfoques— y juntar los resultados. NO sirve para tareas que tocan
disco: para eso el agente ya tiene `delegar_subtarea`, que sí lleva herramientas.
Esa frontera está escrita en la descripción de la tool porque es la forma de que
el modelo no la use mal.

TOPES (un agente que se lanza workflows a sí mismo puede irse de las manos)
Los tres numéricos se abren por entorno desde el 2026-08-17 —los defectos NO
cambian— porque eran constantes de módulo y por lo tanto un techo que nadie
podía mover sin editar el fichero: 6 pasos x 2048 tokens = 12.288 tokens de
salida por corrida, el 6,1% de los 200k que el dueño pide. Cada override tiene
tope duro y avisa si se pasa (ver `_env_int`):
  - COGNIA_WF_MAX_PASOS ....... `max_pasos()`, defecto 6, tope 64
  - COGNIA_WF_MAX_TOKENS_PASO . `max_tokens_paso()`, defecto 2048, tope 32768
  - COGNIA_WF_PRESUPUESTO ..... `presupuesto_defecto()`, defecto 60k, tope 2M
LA PALANCA BUENA ES `PASOS`, y está MEDIDO (2026-08-17, :8080): subir
max_tokens invalida el 100% de la cache de resume (mismos 3 pasos: 3 hits/0
tokens con 2048, 0 hits/3 llamadas/220 tokens con 4096), mientras que sumar
pasos deja los viejos intactos (4 pasos sobre un resume de 3: 3 hits, 1 llamada
real, 69 tokens). El porqué está en el docstring de cada función.
  - MAX_PASOS = 6 por workflow. Más pasos no es más capacidad: es más espera.
  - PROFUNDIDAD 1: dentro de un workflow la herramienta se rechaza con un motivo
    legible. Sin esto, un paso podría lanzar otro workflow y multiplicarse.
  - Presupuesto de tokens explícito, que el motor ya hace cumplir: agotado
    devuelve `{"_error": ...}` en vez de seguir gastando.
  - `paralelo` con cap=2, que es la física medida de esta máquina (un slot de
    GPU serializa; más hilos solo solapan I/O).
"""

from __future__ import annotations

import os
import re
import threading
import warnings

# DEFECTOS. Los tres son el valor de SIEMPRE y no cambian: lo que se abre es la
# posibilidad de subirlos por entorno (ver `max_pasos()` y compania). Se dejan
# como constantes de modulo porque media docena de tests y el CLI las leen por
# nombre, y porque un defecto es un numero, no una funcion.
MAX_PASOS = 6
PRESUPUESTO_DEFECTO = 60_000
MAX_TOKENS_PASO = 2048

# TOPES DUROS de los overrides. No son decoracion: un env no es una decision
# revisada, es un numero que alguien escribio una vez en un .env y se olvido
# (la BOMBA de LLAMA_CTX_SIZE=200192 contra un server de n_ctx=16384 es
# exactamente esa historia, medida el 2026-08-16). El techo convierte un dedazo
# en un aviso, no en una corrida de 3 horas o un HTTP 400 por prompt.
#   - 64 pasos: a los ~70 s de pared por paso medidos, 64 pasos son ~40 min con
#     cap=2. Mas que eso no es un workflow, es una obra.
#   - 32768 tokens/paso: el DOBLE del n_ctx medido del server de :8080 (16384).
#     Se deja holgura para backends con mas ventana, pero no infinito: pedir
#     mas tokens de los que el server puede dar es garantizarse un truncado.
#   - 2.000.000 de presupuesto: 100x el defecto.
TOPE_PASOS = 64
TOPE_TOKENS_PASO = 32_768
TOPE_PRESUPUESTO = 2_000_000

_ENV_PASOS = "COGNIA_WF_MAX_PASOS"
_ENV_TOKENS_PASO = "COGNIA_WF_MAX_TOKENS_PASO"
_ENV_PRESUPUESTO = "COGNIA_WF_PRESUPUESTO"


def _env_int(nombre: str, defecto: int, tope: int) -> int:
    """El override entero de `nombre`, acotado a [1, tope]. Nunca lanza.

    Se lee A CALL-TIME y no en el import (misma regla que
    `offloading.umbral_bytes()`): una constante congelada en el import no se
    puede cambiar desde un test ni desde el CLI sin recargar el modulo, y ese
    fue el motivo de que estos tres numeros fuesen inamovibles.

    Basura -> defecto CON warning. Un env que no es el que el usuario escribio
    es peor que no tener env, porque nadie lo mira (la regla ya escrita en
    `harness/limites._env_num`; no se reutiliza esa funcion porque alli '0'
    significa SIN LIMITE y aqui no existe "sin limite": cero pasos es cero
    trabajo y cero tokens por paso es una llamada que no puede contestar).
    """
    crudo = os.environ.get(nombre)
    if crudo is None or not str(crudo).strip():
        return defecto
    try:
        valor = int(float(str(crudo).strip()))
    except (TypeError, ValueError):
        warnings.warn(f"{nombre}={crudo!r} no es un numero: se usa el defecto "
                      f"{defecto}", RuntimeWarning, stacklevel=3)
        return defecto
    if valor < 1:
        warnings.warn(f"{nombre}={crudo!r} no es positivo: se usa el defecto "
                      f"{defecto}", RuntimeWarning, stacklevel=3)
        return defecto
    if valor > tope:
        warnings.warn(f"{nombre}={crudo!r} pasa el tope {tope}: se acota a "
                      f"{tope}", RuntimeWarning, stacklevel=3)
        return tope
    return valor


def max_pasos() -> int:
    """Pasos por workflow. LA PALANCA BUENA para crecer, y esto esta MEDIDO.

    Sumar pasos NO invalida la cache de resume: la clave es
    sha256({prompt, system, schema, rol, max_tokens}) por AGENTE, asi que un
    paso nuevo es una clave nueva y los viejos siguen siendo hits. Medido el
    2026-08-17 contra :8080 (qwen2.5-coder-14b): resume de una corrida de 3
    pasos pidiendo 4 (los 3 de antes + 1) -> 3 hits, 1 llamada real, 69 tokens,
    1,0 s. Comparar con `max_tokens_paso()`, que cuesta la cache ENTERA.
    """
    return _env_int(_ENV_PASOS, MAX_PASOS, TOPE_PASOS)


def max_tokens_paso() -> int:
    """Tokens de salida por paso. SUBIRLO RE-PAGA TODAS LAS CORRIDAS VIEJAS.

    `max_tokens` entra en `_clave_cache` (workflows.py:745), asi que cambiarlo
    cambia la clave de TODOS los agentes y ningun resume acierta. Medido el
    2026-08-17 contra :8080, misma corrida de 3 pasos resumida dos veces:
      - resume con max_tokens=2048 (el mismo): 3 hits, 0 llamadas, 0 tokens, 0,0 s
      - resume con max_tokens=4096 (subido):   0 hits, 3 llamadas, 220 tokens, 8,3 s
    O sea: 100% de la cache tirada. En un workflow de 6 pasos a ~2.000 tokens
    eso son ~12.000 tokens y ~70 s re-pagados para volver a leer lo que ya
    estaba en disco.
    ASI QUE: para agrandar una corrida, subir PASOS, no tokens por paso. Este
    override existe para el caso en que un paso NECESITE de verdad mas salida
    (y entonces re-pagar es el precio correcto, porque el resultado viejo
    estaba truncado), no como palanca de capacidad.
    """
    return _env_int(_ENV_TOKENS_PASO, MAX_TOKENS_PASO, TOPE_TOKENS_PASO)


def presupuesto_defecto() -> int:
    """Techo de tokens de la corrida entera. Neutro para la cache: no entra en
    `_clave_cache`, asi que subirlo no invalida ningun resume."""
    return _env_int(_ENV_PRESUPUESTO, PRESUPUESTO_DEFECTO, TOPE_PRESUPUESTO)

# Las claves del envelope de ejecutar(), EXPORTADAS: el contrato de forma fija
# se puede verificar desde fuera en vez de re-escribirse en cada test.
CLAVES_ENVELOPE = frozenset({"ok", "texto", "run_id", "pasos", "tokens",
                             "cancelados", "critica", "error"})

# Marca de "ya estamos dentro de un workflow", por hilo: `paralelo` corre los
# pasos en un pool, así que una bandera global marcaría también al hilo padre
# que espera, y una de proceso no distinguiría corridas concurrentes.
_dentro = threading.local()

_SEPARADORES = re.compile(r"\s*(?:;|\n|(?<=\S)\s\|\s(?=\S))\s*")

# Restos de OTRAS plantillas de tool-calling que el modelo cuela DENTRO del
# valor de un argumento. Medido contra Qwythos-9B el 2026-08-13: pidiendole tres
# resumenes devolvio
#   pasos="...investigar TLS</parameter>\n<parameter=modo>\nparalelo"
# o sea, sintaxis estilo XML incrustada en el JSON del tool call. Sin limpiarla,
# `partir_pasos` veia 5 subtareas —dos de ellas basura— y cada una se pagaba con
# una llamada al modelo. El server no puede filtrarlo (para el es texto), asi
# que le toca al adaptador.
_RESTOS_PLANTILLA = re.compile(
    r"</?(?:parameter|tool_call|function|invoke|arg)\b[^>]*>", re.IGNORECASE)
_CLAVE_INCRUSTADA = re.compile(
    r"<\s*parameter\s*=\s*(\w+)\s*>\s*([^<\n]*)", re.IGNORECASE)


def sanear(texto: str) -> tuple:
    """Limpia restos de plantilla y devuelve (texto_limpio, claves_incrustadas).

    `claves_incrustadas` recupera lo que el modelo queria pasar como otro
    argumento (tipicamente `modo`) y quedo atrapado dentro de este: tirarlo
    seria perder su intencion, y dejarlo seria ejecutarlo como subtarea.
    """
    crudo = str(texto or "")
    claves = {k.lower(): v.strip() for k, v in _CLAVE_INCRUSTADA.findall(crudo)}
    limpio = _RESTOS_PLANTILLA.sub("\n", crudo)
    for clave, valor in claves.items():
        # El valor ya se recupero como argumento: fuera del cuerpo de las tareas.
        if valor:
            limpio = limpio.replace(valor, "\n")
    return limpio, claves


def en_workflow() -> bool:
    """True si el hilo actual ya está ejecutando un paso de workflow."""
    return bool(getattr(_dentro, "activo", False))


def partir_pasos(texto: str) -> list:
    """El string del modelo -> lista de subtareas.

    Acepta lo que un modelo escribe de verdad: separadas por ';', por saltos de
    línea, o numeradas ('1. ...'). Se limpian viñetas y numeración porque el
    prompt del paso no debe empezar con '3.' (el modelo cree que le falta el
    contexto de los pasos 1 y 2).
    """
    if not texto:
        return []
    limpio, _ = sanear(texto)
    crudos = _SEPARADORES.split(limpio)
    pasos = []
    for c in crudos:
        limpio = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", (c or "").strip())
        if limpio:
            pasos.append(limpio)
    return pasos


def _consolidar(pasos: list, resultados: list) -> str:
    """El texto que vuelve al modelo: un bloque por paso, con su fallo si lo hubo."""
    lineas = []
    fallos = 0
    for i, (paso, res) in enumerate(zip(pasos, resultados), 1):
        cabecera = f"--- paso {i}: {paso[:90]}"
        if res is None:
            fallos += 1
            lineas.append(f"{cabecera}\n(sin resultado: el paso no termino a tiempo)")
            continue
        if isinstance(res, dict) and res.get("_error"):
            fallos += 1
            bloque = f"{cabecera}\nERROR: {res['_error']}"
            # EL PARCIAL PAGADO VIAJA (2026-08-17). Un truncado por
            # finish_reason=length trae en `_crudo` todo lo que el modelo
            # alcanzo a generar, y esos tokens ya se cobraron al presupuesto:
            # tirarlos aqui deshace el fix de workflows.py y el usuario paga
            # dos veces por el mismo texto. Sigue contando como FALLO (el paso
            # no termino) — lo que cambia es que el fallo llega con su
            # evidencia, no con un ERROR pelado.
            crudo = res.get("_crudo")
            if crudo:
                bloque += (f"\n--- lo YA GENERADO y pagado ({len(str(crudo))} "
                           f"chars, incompleto) ---\n{crudo}")
            lineas.append(bloque)
            continue
        lineas.append(f"{cabecera}\n{res if isinstance(res, str) else res}")
    cierre = (f"\n({len(pasos) - fallos} de {len(pasos)} pasos con resultado)"
              if fallos else f"\n({len(pasos)} pasos completados)")
    return "\n\n".join(lineas) + cierre


def ejecutar(pasos, modo: str = "paralelo", nombre: str = "agente",
             presupuesto: int = 0,
             system: str = "", print_fn=None,
             criticar_salida: bool = False,
             interactivo: bool = False) -> dict:
    """Corre las subtareas en el motor de workflows. NUNCA lanza.

    Devuelve CLAVES_ENVELOPE — SIEMPRE las ocho, en todos los caminos. Un
    envelope de forma variable (el camino OK traía "critica" y los de error no)
    es el mismo fallo silencioso de siempre con otro disfraz: el consumidor que
    lee la clave revienta con KeyError justo cuando el workflow falla. El
    `texto` es lo que se le devuelve al modelo; `run_id` permite reanudar la
    corrida más tarde con `corrida(resume_de=run_id)`, que es la razón de
    devolverlo. Con `ok=False` el `texto` puede venir LLENO: lo ya consolidado
    sobrevive a la excepción porque está pagado, así que un consumidor que
    corte por `ok` sin mirar `texto` tira trabajo que el usuario ya costeó.

    QUÉ SIGNIFICA `ok` (regla fijada por el defecto #1, 2026-08-17):
    **la corrida entregó lo que se le pidió, entera y sin que nadie la
    cortara** — exactamente `WorkflowFin.ok`, y no una segunda opinión.
    No se calcula aquí: lo decide `Corrida.cerrar()`, que es quien tiene la
    contabilidad (cancelados, colgando, no arrancados), y este envelope se
    construye con lo que ese cierre DEVUELVE. Antes se calculaba en los dos
    sitios y divergían: tras un botón de pánico ejecutar() decía
    `ok=False error='ningun paso devolvio resultado'` —al usuario que ACABA de
    apretar cancelar se le informaba de que el workflow no produjo nada, el
    diagnóstico opuesto— y con 1 de 3 pasos cancelado ejecutar() decía
    `ok=True error=''` mientras WorkflowFin decía `ok=False cancelados=1`.
    Dos consumidores del MISMO cierre no pueden contradecirse: por eso hay un
    solo veredicto y un solo punto donde se arma el envelope.

    `cancelados` (clave aditiva, en los ocho caminos incluidos los cuatro de
    error) es cuántos agentes cortó el usuario. Existe para que una UI no tenga
    que buscar la palabra "cancelados" dentro de `error` para saber si el
    fallo lo causó el propio usuario: `error` es la línea humana (cli.py la
    imprime tal cual) y `cancelados` es el dato.

    `criticar_salida=True` añade una fase de REFUTACIÓN sobre el texto
    consolidado: tres críticos con lentes distintas (aritmética / evidencia /
    encargo) cuyo encargo es tumbarlo, y un veredicto por voto con quórum. Se
    devuelve en la clave "critica" y el veredicto se antepone al texto, para
    que el modelo que lo recibe lea PRIMERO que su propio trabajo está
    discutido. Opt-in porque cuesta una llamada por lente: en un workflow de
    3 pasos, criticar duplica el gasto.

    `interactivo=True` habilita el control por agente: la vista puede llamar
    `cancelar_agente(agente_id)` o `decirle(agente_id, texto)` con el id que
    le llega por el bus (`AgenteInicio.agente_id`). Lo enciende la VISTA, no
    el modelo: NO se publica en PARAMS_WORKFLOW. Cambia el transporte de la
    llamada a la rama SSE de chat_client, así que con `False` (el default)
    todo queda byte-idéntico a lo de hoy.
    """
    # Los tres topes se leen AQUI, a call-time: un test o el CLI pueden
    # moverlos por entorno sin recargar el modulo (ver `max_pasos()`).
    # `presupuesto` explicito del caller manda sobre el entorno; 0/None = "el
    # que toque". El defecto de la firma dejo de ser PRESUPUESTO_DEFECTO
    # porque un default de firma se evalua en el IMPORT y ahi el override
    # todavia no existe.
    tope_pasos = max_pasos()
    tokens_paso = max_tokens_paso()
    presupuesto = int(presupuesto or 0) or presupuesto_defecto()
    if isinstance(pasos, str):
        pasos = partir_pasos(pasos)
    pasos = [p for p in (pasos or []) if str(p).strip()][:tope_pasos]
    if not pasos:
        return _envelope(error="no hay subtareas: describe al menos una")
    if en_workflow():
        return _envelope(error=("ya estas DENTRO de un workflow: un paso no "
                                "puede lanzar otro workflow. Resuelve este "
                                "paso y devuelve su resultado."))

    try:
        from cognia.agent.workflows import (_etiqueta, agente, corrida,
                                            criticar, paralelo)
    except Exception as exc:  # pragma: no cover - el motor va en el paquete
        return _envelope(error=f"motor de workflows no disponible: {exc}")

    # total_agentes: el adaptador es el único que sabe cuántos pasos hay, y el
    # panel necesita el denominador ANTES del primer AgenteInicio.
    c = corrida(nombre, presupuesto_tokens=presupuesto,
                print_fn=print_fn or (lambda *_a, **_k: None),
                total_agentes=len(pasos), interactivo=bool(interactivo))

    # `_etiqueta` y no `prompt[:60]`: el slice crudo se lleva el salto de linea
    # de un paso multilinea (la firma publica acepta lista, y ahi nadie paso por
    # partir_pasos). La segunda linea sale del panel SIN marca ⏺/·/✗, asi que
    # `es_eco_renderer` no la caza y el chat del movil la anota como prosa del
    # asistente. `_etiqueta` existe exactamente para garantizar UNA linea.
    def _thunk(i: int, prompt: str):
        def _correr():
            _dentro.activo = True
            try:
                return agente(c, prompt, system=system,
                              max_tokens=tokens_paso,
                              indice=i, total=len(pasos), fase="pasos",
                              etiqueta=_etiqueta(prompt))
            finally:
                _dentro.activo = False
        return _correr

    critica = None
    # El consolidado vive FUERA del try por la misma razon que `critica`: cuesta
    # hasta 6 llamadas al LLM y una excepcion posterior no puede borrarlo.
    texto = ""
    # Lo que este adaptador PROPONE al cierre. El veredicto final no es este:
    # lo decide cerrar() con su contabilidad y vuelve en `_fin` (defecto #1).
    _ok_wf, _motivo_wf = True, ""
    _utiles = 0
    # NADA de `return` dentro del try/except: el `finally` corre DESPUES de que
    # el return evalue su expresion, asi que un envelope construido ahi dentro
    # no puede ver el veredicto del cierre — que es exactamente como los dos
    # consumidores empezaron a contradecirse. Hay UN punto de construccion, al
    # final, y los caminos de fallo llegan a el por variable.
    try:
        if (modo or "").strip().lower().startswith("sec"):
            resultados = []
            for i, p in enumerate(pasos, 1):
                resultados.append(_thunk(i, p)())
        else:
            resultados = paralelo([_thunk(i, p)
                                   for i, p in enumerate(pasos, 1)])
        _utiles = sum(1 for r in resultados
                      if r is not None
                      and not (isinstance(r, dict) and r.get("_error")))
        # Los pasos que el USUARIO corto se cuentan por la marca `_cancelado`
        # que pone el motor, no husmeando el texto de `_error`.
        _cortados = sum(1 for r in resultados
                        if isinstance(r, dict) and r.get("_cancelado"))
        _ok_wf = _utiles > 0
        # "ningun paso devolvio resultado" SOLO si hay algun fallo que no sea
        # una cancelacion. Si el unico motivo es que el usuario corto, ese
        # motivo lo pone el cierre y decirlo dos veces —"2 cancelados; ningun
        # paso devolvio resultado"— le vuelve a plantar delante al usuario el
        # diagnostico que este defecto vino a sacar.
        _motivo_wf = ("" if (_utiles or _cortados >= len(pasos))
                      else "ningun paso devolvio resultado")
        texto = _consolidar(pasos, resultados)
        if criticar_salida:
            # Dentro del try y ANTES del finally: `_cerrar(c)` cierra el
            # journal, y una crítica escrita después se perdería con un aviso
            # a stderr en vez de quedar en la corrida.
            critica = criticar(c, texto,
                               contexto="Subtareas pedidas:\n- "
                                        + "\n- ".join(str(p) for p in pasos))
    except Exception as exc:
        # `critica` y `texto` NO se vacían: si el veredicto ya se pagó con 3
        # llamadas al LLM y el consolidado con hasta 6, una excepción posterior
        # no puede borrarlos. Si la excepción vino de criticar() mismo, `critica`
        # sigue valiendo None por la inicialización; si vino antes de consolidar,
        # `texto` sigue siendo "". Devolver "" siempre era tirar trabajo YA
        # PAGADO: cli.py corta con `if not res["ok"]: print(error); return`, así
        # que el usuario perdía los pasos que sí salieron y pagaba sus tokens.
        _ok_wf, _motivo_wf = False, f"el workflow fallo: {exc}"
    finally:
        _fin = _cerrar(c, ok=_ok_wf, resumen=_motivo_wf)

    if critica:
        texto = _cabecera_critica(critica) + texto
    # EL veredicto: el que el cierre publicó en WorkflowFin, no una segunda
    # cuenta. `_fin` es None solo con un motor viejo cuyo cerrar() no devuelve
    # nada; ahí se cae a lo propuesto, que es lo que había antes.
    ok = bool(getattr(_fin, "ok", _ok_wf))
    error = str(getattr(_fin, "resumen", _motivo_wf) or "")
    cancelados = int(getattr(_fin, "cancelados", 0) or 0)
    if ok:
        # `ok` y `error` no pueden contradecirse: un cierre OK no lleva motivo.
        error = ""
    else:
        if not error:
            # ok=False sin motivo sería el silencio de siempre con otro disfraz.
            error = "el workflow no termino bien y el cierre no dijo por que"
        if cancelados and _utiles:
            # cli.py imprime `error` y corta, así que la línea tiene que decir
            # TAMBIÉN que hay trabajo pagado esperando en `texto`: si no,
            # cancelar un paso de tres se lee como perder los tres.
            error += (f" (los otros {_utiles} de {len(pasos)} pasos SI dieron "
                      f"resultado: estan en el texto del workflow)")
    return _envelope(ok=ok, texto=texto, run_id=c.run_id, pasos=len(pasos),
                     tokens=_gastado(c), cancelados=cancelados,
                     critica=critica, error=error)


def _envelope(ok: bool = False, texto: str = "", run_id: str = "",
              pasos: int = 0, tokens: int = 0, cancelados: int = 0,
              critica=None, error: str = "") -> dict:
    """CLAVES_ENVELOPE, siempre las ocho. UN solo sitio que las escriba.

    Cuatro caminos de error construían el dict a mano y por eso `critica`
    faltaba en unos y no en otros hasta 2026-08-13; la clave `cancelados` de
    hoy habría repetido la historia. Con un constructor, agregar una clave es
    agregarla en un sitio y aparece en los ocho caminos por construcción."""
    return {"ok": bool(ok), "texto": texto, "run_id": run_id,
            "pasos": int(pasos), "tokens": int(tokens),
            "cancelados": int(cancelados), "critica": critica,
            "error": error}


def _cabecera_critica(critica: dict) -> str:
    """El veredicto, ARRIBA y en una línea legible.

    Va delante del texto y no al final por la misma razón que la lista de
    tareas se reemite entera: lo que queda lejos del punto de decisión no se
    lee. Un "REFUTADO" al pie de 4.000 tokens de informe es decoración.
    """
    v = critica.get("veredicto", "INDETERMINADO")
    cab = (f"[critica: {v} — {critica.get('refutan', 0)} de "
           f"{critica.get('respondieron', 0)} criticos refutan "
           f"({critica.get('fanout', '')})]")
    mortales = critica.get("mortales") or []
    if mortales:
        cab += "\nDEFECTOS QUE INVALIDAN:"
        for d in mortales[:3]:
            cab += f"\n  - {d.get('defecto', '')}"
    if v == "INDETERMINADO":
        cab += ("\n  (sin quorum de criticos: el veredicto NO es una "
                "aprobacion, es una falta de datos)")
    return cab + "\n\n"


def _gastado(c) -> int:
    """Tokens consumidos por la corrida, o 0 si el motor no los expone.

    `PresupuestoTokens.gastado` es un METODO (thread-safe, con lock), no un
    atributo: `int(getattr(...))` devolvia el metodo, lanzaba TypeError y el
    except lo enmascaraba como 0 — el workflow informaba "0 tokens" mientras el
    journal registraba 844. Se acepta tambien la forma atributo por si el
    contrato del motor cambia.
    """
    try:
        valor = getattr(c.presupuesto, "gastado", 0)
        return int(valor() if callable(valor) else valor or 0)
    except Exception:
        return 0


def _cerrar(c, ok: bool = True, resumen: str = ""):
    """Cierra el journal de la corrida sin que un fallo aquí tape el resultado.

    El veredicto viaja al cierre porque es `cerrar()` quien emite `WorkflowFin`
    y un workflow que falló tiene que declararlo. Un motor viejo cuyo `cerrar()`
    no acepta argumentos se reintenta pelado (TypeError): cerrar es idempotente.

    DEVUELVE el WorkflowFin que se emitió (o None si el motor no lo da). Es la
    pieza que hace imposible el defecto #1: el envelope no vuelve a calcular un
    veredicto propio, lee el que fue al bus.
    """
    for nombre in ("cerrar", "close"):
        fn = getattr(c, nombre, None)
        if callable(fn):
            try:
                return fn(ok, resumen)
            except TypeError:
                try:
                    return fn()
                except Exception:
                    pass
            except Exception:
                pass
    try:
        if getattr(c, "_fh", None):
            c._fh.close()
    except Exception:
        pass
    return None


# ── Control por agente, al alcance de la vista ───────────────────────────────
# El REPL/panel importa el adaptador, no el motor. Estos cuatro son un puente
# fino: el envelope de FORMA FIJA del motor se conserva tal cual, y un motor
# viejo (o un import roto) devuelve el MISMO envelope con estado
# "desconocido_corrida" en vez de lanzar — el camino de fallo de un botón de
# pánico no puede ser una excepción en la UI.
# Las tres claves de conteo van SEPARADAS (defecto #4): `pendientes` son
# mensajes en cola, `agentes` los agentes vivos alcanzados y `corridas` las
# corridas alcanzadas. El envelope de fallo tiene que traer las mismas ocho
# claves que el del motor o el consumidor revienta justo aquí.
_ENV_SIN_MOTOR = {"ok": False, "estado": "desconocido_corrida", "agente_id": "",
                  "run_id": "", "pendientes": 0, "agentes": 0, "corridas": 0,
                  "detalle": "motor de workflows no disponible"}


def _control(nombre: str, *args):
    try:
        from cognia.agent import workflows as _wf
        fn = getattr(_wf, nombre, None)
        if fn is None:
            return dict(_ENV_SIN_MOTOR,
                        detalle=f"el motor no expone {nombre}()")
        return fn(*args)
    except Exception as exc:
        return dict(_ENV_SIN_MOTOR,
                    detalle=f"motor de workflows no disponible: {exc}")


def cancelar_agente(agente_id: str, motivo: str = "el usuario corto") -> dict:
    """Corta UN agente en curso. `agente_id` es el del bus (AgenteInicio)."""
    return _control("cancelar_agente", agente_id, motivo)


def cancelar_corrida(run_id: str = "", motivo: str = "el usuario corto") -> dict:
    """Botón de pánico. Sin run_id: todas las corridas vivas."""
    return _control("cancelar_corrida", run_id, motivo)


def decirle(agente_id: str, texto: str) -> dict:
    """«Interrumpir y decir»: corta la generación y re-pregunta con el texto."""
    return _control("decirle", agente_id, texto)


def estado_agente(agente_id: str) -> str:
    try:
        from cognia.agent import workflows as _wf
        return _wf.estado_agente(agente_id)
    except Exception:
        return "desconocido_corrida"


def corridas_vivas() -> list:
    try:
        from cognia.agent import workflows as _wf
        return _wf.corridas_vivas()
    except Exception:
        return []


# Documentación para el registro nativo de la herramienta (cognia/harness/
# tools_harness.py la usa tal cual: una sola fuente de verdad para el prompt,
# el schema OpenAI y el despacho).
DESC_WORKFLOW = (
    "Resuelve DE UNA VEZ varias partes independientes de la misma tarea y te "
    "devuelve todos los resultados juntos. Usalo en cuanto el pedido tenga "
    "VARIAS piezas que no dependen entre si: 'resumi A, B y C', 'evalua estos "
    "tres enfoques', 'redacta estas secciones'. Es la opcion correcta ahi: "
    "hacerlas una por una gasta un paso por pieza, y delegar_subtarea lanza UN "
    "sub-agente para UNA subtarea, no varias en paralelo. "
    "Cada paso es una consulta al modelo SIN herramientas, asi que sirve para "
    "analizar, redactar, comparar y decidir; si la pieza necesita tocar "
    "ficheros o ejecutar algo, esa va por delegar_subtarea. "
    "Maximo 6 pasos, y un paso no puede lanzar otro workflow."
)

PARAMS_WORKFLOW = [
    {"nombre": "pasos", "tipo": "string", "requerido": True,
     "descripcion": ("las subtareas separadas por ';' — cada una autocontenida, "
                     "porque el paso no ve el resto de la conversacion")},
    {"nombre": "modo", "tipo": "string", "requerido": False, "clave": True,
     "descripcion": "'paralelo' (por defecto) o 'secuencial'"},
]
