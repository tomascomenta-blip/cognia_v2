# -*- coding: utf-8 -*-
"""
cognia/autopsia/causal.py
=========================
ATRIBUCION CAUSAL DEL FALLO por replay contrafactual: de mis 200 pasos, CUAL
causo el fallo.

QUE RESUELVE
------------
Un agente corre 200 pasos y la tarea sale mal. Hoy el harness sabe QUE fallo
(la postcondicion) pero no QUIEN. Las dos defensas que existen en el campo son
heuristicas SIN contrafactual:
  (a) mirar el ultimo paso — culpa al mensajero: el paso que revela el dano casi
      nunca es el que lo causo;
  (b) darle la traza a un LLM y pedirle que senale — un juicio sin experimento,
      con la tasa de acierto de quien nunca vuelve a correr nada.
Este modulo hace el EXPERIMENTO: vuelve a juzgar prefijos de la trayectoria y
localiza el primer paso a partir del cual el veredicto ya condena. Es una
medicion, no una opinion.

POR QUE EXISTE (hueco medido, investigacion 2026-08-18)
-------------------------------------------------------
DeltaBox (arXiv 2605.22781) restaura un paso en ~5 ms; Causal Agent Replay
(arXiv 2606.08275) exige re-ejecutar desde el paso i. Son comunidades DISJUNTAS
y nadie las ha juntado: el que sabe restaurar barato no pregunta por la causa,
y el que pregunta por la causa paga re-ejecucion lineal. Aca se juntan: la
restauracion (`reproducir_fn`, inyectada) es la primitiva barata, y encima va
una BUSQUEDA BINARIA que cuesta log2(n) reproducciones en vez de n. Con 200
pasos son ~8 reproducciones en vez de 200: la diferencia entre "se puede" y
"no se puede".

LA CONDICION QUE HACE VALIDA LA BUSQUEDA BINARIA (leer esto antes de usar)
--------------------------------------------------------------------------
La biseccion sobre prefijos SOLO es correcta si el veredicto es MONOTONO en el
prefijo: una vez que el prefijo condena, todo prefijo mas largo condena tambien.
Eso vale para propiedades de SEGURIDAD / INVARIANTES ("el fichero requerido
sigue existiendo y con el contenido correcto", "ningun valor invalido entro en
el acumulador", "no se hizo push a main"): el dano no se repara solo.
NO vale para propiedades de VIVACIDAD ("la tarea esta completa"): el prefijo
vacio ya las incumple, porque el trabajo no esta hecho todavia.

Esto NO se declara en prosa y ya: `atribuir` lo COMPRUEBA en tiempo de
ejecucion antes de bisecar, con dos evaluaciones de frontera:
  - prefijo VACIO -> tiene que PASAR. Si ya falla, la tarea era imposible (o el
    veredicto no depende de la trayectoria) y se devuelve `paso_culpable=None`
    con confianza minima. NO se inventa un culpable.
  - trayectoria COMPLETA -> tiene que FALLAR. Si pasa, no hay nada que atribuir.
Y despues de bisecar, si queda presupuesto, se corre el CONTRAFACTUAL de verdad:
se ABLACIONA el paso senalado de la trayectoria COMPLETA. Si sin el la tarea
pasa, la atribucion queda confirmada ("sin este paso pasa; con el, falla"). Si
sigue fallando, hay mas de una causa y la confianza BAJA — no se disimula.

API PUBLICA
-----------
    atribuir(trayectoria, veredicto_fn, *, reproducir_fn=None, presupuesto=12)
        -> Informe (dict): {paso_culpable, confianza, evidencia, reproducciones,
                            ms, alternativas, motivo, motor_ablacion, truncado}
    explicar(informe, trayectoria) -> str
    banco_inyeccion(n=10, semilla=0) -> list de casos con culpable CONOCIDO
    medir_precision(banco, presupuesto=12) -> dict con precision@1 del metodo y
        de las DOS lineas base obligatorias (ultimo paso / ultimo paso fallido)
    linea_base_ultimo_paso(trayectoria) -> int | None
    linea_base_ultimo_fallido(trayectoria) -> int | None
    ablacionar(trayectoria, indices) -> list   (preserva el formato de entrada)
    ablacionar_via_replay(trayectoria, indices, modo="saltar")  (puente explicito)

INYECCION DE DEPENDENCIAS (tests sin modelo ni red)
---------------------------------------------------
`veredicto_fn(estado) -> bool` (True = la tarea PASA) y
`reproducir_fn(subtrayectoria) -> estado` son callables inyectados. En
produccion `reproducir_fn` restaura el sandbox y re-ejecuta el prefijo, y
`veredicto_fn` corre las postcondiciones reales. Por defecto `reproducir_fn` es
la identidad (el estado ES la subtrayectoria), que es lo que permite testear
todo el algoritmo sin tocar disco, red ni LLM.

EVIDENCIA (medida, no declarada)
--------------------------------
`medir_precision(banco_inyeccion(24, semilla=7))` sobre 24 trayectorias con
fallo inyectado en un paso CONOCIDO. La tabla comparativa contra las dos lineas
base esta en el informe de entrega y se reproduce con:
    PYTHONUTF8=1 ./venv312/Scripts/python.exe -m cognia.autopsia.causal
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable, Sequence

# Informe es un dict plano a proposito: se serializa a JSON sin adaptadores y
# se imprime con pprint. No hace falta una clase para 8 claves.
Informe = dict

__all__ = [
    "atribuir", "explicar", "banco_inyeccion", "medir_precision",
    "ablacionar", "ablacionar_via_replay",
    "linea_base_ultimo_paso", "linea_base_ultimo_fallido",
    "MOTIVO_OK", "MOTIVO_NO_FALLA", "MOTIVO_VACIA", "MOTIVO_IMPOSIBLE",
    "MOTIVO_TRUNCADO",
]

# Motivos: strings estables para que un cableado pueda ramificar por igualdad
# en vez de por substring de un mensaje en prosa.
MOTIVO_OK = "atribuido"
MOTIVO_NO_FALLA = "la trayectoria completa NO falla: no hay nada que atribuir"
MOTIVO_VACIA = "trayectoria vacia"
MOTIVO_IMPOSIBLE = ("falla ya con CERO pasos: la tarea era imposible o el "
                    "veredicto no depende de la trayectoria")
MOTIVO_TRUNCADO = "presupuesto agotado antes de aislar un solo paso"


# ---------------------------------------------------------------------------
# Ablacion: local y PRESERVANDO EL FORMATO del llamante (ver ablacionar()).
# ---------------------------------------------------------------------------
def _ablacionar_local(trayectoria: Sequence[Any], indices) -> list:
    """Ablacion de referencia: quita por INDICE y devuelve los MISMOS objetos.

    Sin copia ni normalizacion a proposito: los pasos que salen son los que
    entraron, asi que el `reproducir_fn` del llamante los lee igual que a la
    trayectoria original. Es la propiedad que hace comparable el contrafactual.
    """
    fuera = {int(i) for i in indices}
    return [p for i, p in enumerate(trayectoria) if i not in fuera]


def ablacionar(trayectoria: Sequence[Any], indices) -> list:
    """Quita los pasos `indices` y devuelve una lista EN EL FORMATO DE ENTRADA.

    POR QUE NO DELEGA en `cognia.autopsia.replay.ablacionar` (medido el
    2026-08-19 sobre el modulo hermano real, no supuesto): su firma es
    `ablacionar(trayectoria, i:int, modo:str)` y devuelve un objeto
    `Trayectoria` cuyos pasos pasaron por `normalizar()`, que RENOMBRA la clave
    `action` a `tool` y coacciona `args`. Como `reproducir_fn` lo escribe el
    LLAMANTE y lee el formato del llamante, delegar le entregaria pasos con
    otro esquema. SONDA CORRIDA (scratchpad/sonda_delegacion.py, 2026-08-19):
    tras delegar, `paso.get("action")` vale None en TODOS los pasos, el
    reproducir_fn del llamante no ve ninguna operacion, y ablacionar un paso
    INOCENTE devuelve "la tarea pasa" -> el contrafactual lo coronaria culpable
    con confianza 0.95. No es una degradacion: es una INVERSION silenciosa del
    resultado. Preservar el formato del llamante no es preferencia de estilo,
    es la condicion para que el contrafactual signifique algo.

    Para quien YA trabaja en el esquema de `replay`, el puente explicito es
    `ablacionar_via_replay()`, que no promete preservar formato.
    """
    return _ablacionar_local(trayectoria, indices)


def ablacionar_via_replay(trayectoria, indices, modo: str = "saltar"):
    """Puente EXPLICITO al modulo hermano, para quien ya usa su esquema.

    Devuelve lo que devuelva `replay.ablacionar` (una `Trayectoria`), con los
    indices aplicados de mayor a menor para que el renumerado de cada `saltar`
    no corra los indices que faltan por quitar. Lanza si el hermano no esta:
    no hay respaldo silencioso, porque el formato de salida es OTRO y fingir
    que es el mismo seria el bug que este modulo evita.
    """
    from cognia.autopsia import replay as _rp  # ImportError explicito

    salida = trayectoria
    for i in sorted({int(x) for x in indices}, reverse=True):
        salida = _rp.ablacionar(salida, i, modo)
    return salida


def _motor_ablacion():
    """(callable, nombre) del motor que usa `atribuir` para el contrafactual.

    Se deja como funcion (y no como constante) para que el informe pueda
    nombrarlo y para que un cableado futuro pueda sustituirlo sin tocar
    `atribuir`. Hoy siempre es el local, por la razon del docstring de
    `ablacionar()`.
    """
    return _ablacionar_local, "causal._ablacionar_local (preserva el formato)"


def _ablacionar_con(motor, trayectoria, indices):
    """Aplica el motor; si su firma no encaja, cae al local y lo DECLARA."""
    try:
        salida = motor(trayectoria, indices)
        if isinstance(salida, (list, tuple)):
            return list(salida), False
    except Exception:
        pass
    return _ablacionar_local(trayectoria, indices), True


# ---------------------------------------------------------------------------
# Normalizacion del veredicto
# ---------------------------------------------------------------------------
def _pasa(valor: Any) -> bool:
    """True = la tarea PASA. Tolera bool, dict {'ok'|'pasa'|'exito'} o truthy.

    POR QUE: en produccion el veredicto lo produce un runner de postcondiciones
    que devuelve un dict con detalle. Obligar a que devuelva un bool pelado
    tiraria la parte util. `None` es un ERROR explicito y no "falla": un fallo
    silencioso del verificador y un veredicto negativo piden decisiones opuestas.
    """
    if valor is None:
        raise ValueError(
            "veredicto_fn devolvio None. None NO se interpreta como fallo: "
            "un verificador roto y una tarea reprobada exigen decisiones "
            "distintas. Devuelve True/False o un dict con 'ok'.")
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, dict):
        for clave in ("ok", "pasa", "exito", "passed"):
            if clave in valor:
                return bool(valor[clave])
        raise ValueError(
            "veredicto_fn devolvio un dict sin clave 'ok'/'pasa'/'exito'/"
            f"'passed': {sorted(valor)[:6]}")
    return bool(valor)


# ---------------------------------------------------------------------------
# atribuir: la busqueda binaria contrafactual
# ---------------------------------------------------------------------------
def atribuir(trayectoria: Sequence[Any],
             veredicto_fn: Callable[[Any], Any],
             *,
             reproducir_fn: Callable[[Sequence[Any]], Any] | None = None,
             presupuesto: int = 12) -> Informe:
    """Localiza el paso culpable por biseccion sobre prefijos + contrafactual.

    trayectoria  : lista de pasos. Formato libre; el del bucle de Cognia es
                   {"action","args","ok","result_head"} (cognia/agent/loop.py).
    veredicto_fn : (estado) -> True si la tarea PASA. Inyectado.
    reproducir_fn: (subtrayectoria) -> estado. Por defecto la identidad.
                   En produccion: restaura el sandbox y re-ejecuta el prefijo.
    presupuesto  : tope DURO de reproducciones (llamadas no cacheadas a
                   veredicto_fn). Incluye las 2 evaluaciones de frontera y la
                   ablacion final. Con presupuesto < 2 no se puede ni comprobar
                   la precondicion y se devuelve truncado sin culpable.

    Devuelve un Informe (dict). `paso_culpable` es None cuando NO hay culpable
    atribuible: eso es un resultado, no un fallo, y `motivo` dice por que.
    """
    t0 = time.perf_counter()
    pasos = list(trayectoria)
    n = len(pasos)
    if reproducir_fn is None:
        # Identidad: el "estado" es la propia subtrayectoria. Es lo que permite
        # probar el algoritmo sin sandbox, y es lo correcto cuando el veredicto
        # se calcula leyendo la traza (p.ej. invariantes sobre los args).
        reproducir_fn = lambda sub: sub  # noqa: E731

    motor, nombre_motor = _motor_ablacion()
    estado = {
        "reproducciones": 0,
        "cache": {},          # clave -> bool (pasa)
        "evidencia": [],
        "degradado": False,
    }

    def _evaluar(sub, clave, etiqueta):
        """Una reproduccion + un veredicto, con cache y tope duro.

        Devuelve (pasa, agotado). `agotado=True` significa "no se ejecuto":
        nunca se devuelve un veredicto inventado por falta de presupuesto.
        """
        if clave in estado["cache"]:
            return estado["cache"][clave], False
        if estado["reproducciones"] >= presupuesto:
            return None, True
        estado["reproducciones"] += 1
        pasa = _pasa(veredicto_fn(reproducir_fn(sub)))
        estado["cache"][clave] = pasa
        estado["evidencia"].append({
            "tipo": etiqueta,
            "clave": clave,
            "veredicto": "pasa" if pasa else "falla",
        })
        return pasa, False

    def _informe(paso_culpable, confianza, motivo, alternativas=None):
        return {
            "paso_culpable": paso_culpable,
            "confianza": round(float(confianza), 3),
            "evidencia": estado["evidencia"],
            "reproducciones": estado["reproducciones"],
            "ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "alternativas": list(alternativas or []),
            "motivo": motivo,
            "motor_ablacion": (nombre_motor + " (degradado)"
                               if estado["degradado"] else nombre_motor),
            "truncado": motivo == MOTIVO_TRUNCADO,
            "n_pasos": n,
        }

    if n == 0:
        return _informe(None, 0.0, MOTIVO_VACIA)

    # --- Frontera 1: la trayectoria COMPLETA tiene que fallar -------------
    completa, agotado = _evaluar(pasos, ("prefijo", n), "prefijo")
    if agotado:
        return _informe(None, 0.0, MOTIVO_TRUNCADO)
    if completa:
        return _informe(None, 0.0, MOTIVO_NO_FALLA)

    # --- Frontera 2: el prefijo VACIO tiene que pasar ---------------------
    # Si falla con cero pasos, ningun paso puede ser la causa. Aca es donde el
    # modulo se niega a inventar un culpable: el error mas caro de un atribuidor
    # es senalar a alguien cuando la tarea ya venia rota.
    vacio, agotado = _evaluar([], ("prefijo", 0), "prefijo")
    if agotado:
        return _informe(None, 0.0, MOTIVO_TRUNCADO)
    if not vacio:
        return _informe(None, 0.05, MOTIVO_IMPOSIBLE)

    # --- Biseccion: primer k tal que prefijo[:k] ya condena ---------------
    # Invariante: prefijo[:lo] PASA (medido) y prefijo[:hi] FALLA (medido).
    lo, hi = 0, n
    truncado = False
    while hi - lo > 1:
        medio = (lo + hi) // 2
        pasa, agotado = _evaluar(pasos[:medio], ("prefijo", medio), "prefijo")
        if agotado:
            truncado = True
            break
        if pasa:
            lo = medio
        else:
            hi = medio

    culpable = hi - 1
    # Ventana de incertidumbre que queda: el culpable esta en [lo, hi-1]. Se
    # devuelve hi-1 (el mas tardio compatible) y el resto como alternativas,
    # de mas cercano a mas lejano.
    ventana = list(range(lo, hi - 1))[::-1][:8]

    if truncado:
        # Honestidad: no se aisló un solo paso. Se dice, con la ventana.
        conf = 0.25 if len(ventana) <= 3 else 0.15
        return _informe(culpable, conf, MOTIVO_TRUNCADO, ventana)

    # --- Contrafactual real: ablacionar el paso senalado ------------------
    # Hasta aca solo se sabe "el prefijo hasta k condena y hasta k-1 no". Eso
    # es correlacion posicional. El contrafactual es quitar ESE paso de la
    # trayectoria COMPLETA: si sin el la tarea pasa, la atribucion esta hecha.
    confianza = 0.70   # biseccion convergida, sin contrafactual todavia
    ablada, degradado = _ablacionar_con(motor, pasos, [culpable])
    estado["degradado"] = estado["degradado"] or degradado
    pasa_sin, agotado = _evaluar(ablada, ("ablacion", (culpable,)), "ablacion")
    if agotado:
        return _informe(culpable, confianza,
                        MOTIVO_OK + " (sin contrafactual: presupuesto agotado)",
                        ventana)
    if pasa_sin:
        confianza = 0.95
        motivo = MOTIVO_OK + " (contrafactual confirmado)"
    else:
        # Sin el paso la tarea SIGUE fallando: o hay varias causas, o el
        # veredicto no es monotono. En los dos casos la respuesta de un solo
        # culpable es incompleta y la confianza tiene que reflejarlo.
        confianza = 0.45
        motivo = (MOTIVO_OK + " (contrafactual NO confirmado: al quitar el paso "
                  "la tarea sigue fallando -> hay mas de una causa, o el "
                  "veredicto no es monotono en el prefijo)")
    return _informe(culpable, confianza, motivo, ventana)


# ---------------------------------------------------------------------------
# explicar
# ---------------------------------------------------------------------------
def _describe_paso(paso: Any) -> tuple:
    """(accion, args_cortos, ok) tolerante a formatos distintos de paso."""
    if isinstance(paso, dict):
        accion = str(paso.get("action") or paso.get("accion")
                     or paso.get("tool") or "?")
        args = paso.get("args", paso.get("argumentos", ""))
        ok = paso.get("ok", None)
    else:
        accion, args, ok = str(paso), "", None
    if not isinstance(args, str):
        args = repr(args)
    if len(args) > 160:
        args = args[:157] + "..."
    return accion, args, ok


def explicar(informe: Informe, trayectoria: Sequence[Any]) -> str:
    """El parrafo que lee el humano. Cita el paso, sus args y el contrafactual.

    Nunca afirma mas de lo medido: si no hubo contrafactual, lo dice; si la
    ventana quedo abierta, lista las alternativas.
    """
    pasos = list(trayectoria)
    idx = informe.get("paso_culpable")
    reps = informe.get("reproducciones", 0)
    ms = informe.get("ms", 0.0)
    conf = informe.get("confianza", 0.0)
    motivo = informe.get("motivo", "")
    n = informe.get("n_pasos", len(pasos))

    if idx is None:
        return (f"SIN CULPABLE ATRIBUIBLE ({n} pasos, {reps} reproducciones, "
                f"{ms:.1f} ms). Motivo: {motivo}. "
                f"Confianza {conf:.2f}. No se senala ningun paso: hacerlo seria "
                f"inventar. Revisa la especificacion de la tarea o el "
                f"verificador antes de culpar al agente.")

    accion, args, ok = _describe_paso(pasos[idx]) if 0 <= idx < len(pasos) \
        else ("?", "", None)
    marca_ok = "" if ok is None else (" [la tool reporto OK]" if ok
                                      else " [la tool reporto FALLO]")

    lineas = [
        f"PASO CULPABLE: #{idx} de {n} -- {accion}({args}){marca_ok}",
        f"Confianza {conf:.2f}. {reps} reproducciones, {ms:.1f} ms "
        f"(una busqueda lineal habria costado {n}).",
    ]
    # El contrafactual, con las palabras exactas de lo que se midio.
    tiene_abl = any(e.get("tipo") == "ablacion" for e in informe.get("evidencia", []))
    if tiene_abl and conf >= 0.9:
        lineas.append(
            f"CONTRAFACTUAL: con el paso #{idx}, la tarea FALLA; ablacionado de "
            f"la trayectoria completa, la tarea PASA. Es la causa.")
    elif tiene_abl:
        lineas.append(
            f"CONTRAFACTUAL: al ablacionar el paso #{idx} la tarea SIGUE "
            f"fallando. El paso #{idx} es el primero que condena el prefijo, "
            f"pero NO es causa suficiente por si solo: hay al menos otra.")
    else:
        lineas.append(
            f"SIN CONTRAFACTUAL de ablacion (presupuesto agotado). Lo medido es "
            f"que el prefijo hasta el paso #{idx} inclusive ya condena y el "
            f"prefijo anterior no.")
    alts = informe.get("alternativas") or []
    if alts:
        lineas.append(
            "Ventana sin aislar (el culpable podria ser cualquiera de estos): "
            + ", ".join(f"#{i}" for i in alts))
    if informe.get("truncado"):
        lineas.append(
            "AVISO: presupuesto agotado antes de aislar un solo paso. Sube "
            "`presupuesto` y vuelve a correr para cerrar la ventana.")
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Lineas base obligatorias (contra que se compara)
# ---------------------------------------------------------------------------
def linea_base_ultimo_paso(trayectoria: Sequence[Any]):
    """(a) 'fue el ultimo paso'. Lo que hace un harness sin autopsia."""
    n = len(trayectoria)
    return (n - 1) if n else None


def linea_base_ultimo_fallido(trayectoria: Sequence[Any]):
    """(b) 'fue el ultimo paso que reporto fallo'.

    Si ningun paso reporto fallo, degrada a (a): es lo que haria cualquier
    implementacion real, y darle un None gratis inflaria su precision.
    """
    for i in range(len(trayectoria) - 1, -1, -1):
        paso = trayectoria[i]
        if isinstance(paso, dict) and paso.get("ok") is False:
            return i
    return linea_base_ultimo_paso(trayectoria)


# ---------------------------------------------------------------------------
# Banco de inyeccion de fallos (fault injection, estilo AgenTracer)
# ---------------------------------------------------------------------------
# Maquina de estados minima con la que se simula la trayectoria. El veredicto
# es un INVARIANTE (propiedad de seguridad), no una comprobacion de tarea
# completa: eso es exactamente lo que hace valida la biseccion sobre prefijos
# (ver la cabecera). El invariante:
#   - ningun valor fuera de [0, 1000) entro en el acumulador;
#   - todo fichero que se llego a escribir sigue existiendo y con el contenido
#     que le tocaba.
# Ninguna operacion del generador REPARA una violacion, asi que el invariante
# es monotono POR CONSTRUCCION y el culpable es unico y conocido.
_TOPE_VALOR = 1000


def _vm_ejecutar(subtrayectoria: Sequence[Any]) -> dict:
    """Re-ejecuta un prefijo/ablacion y devuelve el estado. Determinista."""
    est = {"acc": [], "ficheros": {}, "escritos": []}
    for paso in subtrayectoria:
        accion = paso.get("action")
        args = paso.get("args") or {}
        if accion == "sumar":
            est["acc"].append(int(args.get("v", 0)))
        elif accion == "guardar":
            ruta = args.get("path", "")
            est["ficheros"][ruta] = args.get("texto", "")
            if ruta not in est["escritos"]:
                est["escritos"].append(ruta)
        elif accion == "borrar":
            est["ficheros"].pop(args.get("path", ""), None)
        # "leer" y "pensar" no tocan el estado: son el ruido de una traza real.
    return est


def _vm_invariante(estado: dict, esperado: dict) -> bool:
    for v in estado["acc"]:
        if not (0 <= v < _TOPE_VALOR):
            return False
    for ruta in estado["escritos"]:
        if ruta not in estado["ficheros"]:
            return False                      # se borro algo ya escrito
        if ruta in esperado and estado["ficheros"][ruta] != esperado[ruta]:
            return False                      # se escribio contenido erroneo
    return True


def banco_inyeccion(n: int = 10, semilla: int = 0,
                    pasos: tuple = (8, 20)) -> list:
    """Genera `n` trayectorias sinteticas con un fallo inyectado CONOCIDO.

    POR QUE ESTE BANCO Y NO TRAZAS REALES: medir precision@1 sobre trazas reales
    exige que un humano etiquete el paso culpable de cada una — caro y, peor,
    subjetivo. La inyeccion de fallos (AgenTracer y toda la tradicion de fault
    injection) da verdad EXACTA por construccion. El precio, que se declara: el
    banco mide la capacidad de LOCALIZAR dado un veredicto fiable; no mide nada
    sobre la calidad del veredicto.

    Cada caso es un dict:
        trayectoria   lista de pasos {"action","args","ok","result_head"}
        culpable      indice del paso inyectado (verdad)
        tipo          "valor_corrupto" | "borrado" | "sobrescritura"
        reproducir_fn (subtrayectoria) -> estado
        veredicto_fn  (estado) -> bool
        n_fallidos    cuantos pasos llevan ok=False (contexto para la base (b))

    `pasos` es el rango (min, max) de longitud de trayectoria. Se expone para
    poder MEDIR el escalado log2 con trazas largas (200 pasos) en vez de
    declararlo: con (8,20) el ahorro no se ve, con (150,250) si.

    Reproducible: mismo `semilla` -> mismo banco, byte a byte.
    """
    rng = random.Random(semilla)
    casos = []
    for _ in range(int(n)):
        casos.append(_un_caso(rng, int(pasos[0]), int(pasos[1])))
    return casos


def _un_caso(rng: random.Random, min_pasos: int = 8,
             max_pasos: int = 20) -> dict:
    n_pasos = rng.randint(min_pasos, max_pasos)
    n_ficheros = rng.randint(1, 2)
    rutas = [f"salida/parte_{i}.txt" for i in range(n_ficheros)]
    # Las posiciones donde se escribe cada fichero: UNA sola vez cada uno, para
    # que nada repare despues (requisito de monotonia del invariante).
    pos_guardar = rng.sample(range(n_pasos), n_ficheros)

    tray = []
    for i in range(n_pasos):
        if i in pos_guardar:
            ruta = rutas[pos_guardar.index(i)]
            tray.append({"action": "guardar",
                         "args": {"path": ruta, "texto": f"contenido-{ruta}"},
                         "ok": True, "result_head": f"escrito {ruta}"})
        else:
            tipo = rng.choice(["sumar", "sumar", "leer", "pensar"])
            if tipo == "sumar":
                tray.append({"action": "sumar",
                             "args": {"v": rng.randrange(0, _TOPE_VALOR)},
                             "ok": True, "result_head": "ok"})
            else:
                tray.append({"action": tipo,
                             "args": {"q": f"consulta-{i}"},
                             "ok": True, "result_head": "ok"})

    # Contenido esperado: el que produce la trayectoria LIMPIA.
    esperado = {r: f"contenido-{r}" for r in rutas}

    # --- inyeccion --------------------------------------------------------
    # Se eligen los tipos posibles segun lo que ofrezca esta trayectoria.
    idx_sumar = [i for i, p in enumerate(tray) if p["action"] == "sumar"]
    idx_ruido = [i for i, p in enumerate(tray) if p["action"] in ("leer", "pensar")]
    # Para "borrado" hace falta un hueco de ruido DESPUES de algun guardar.
    idx_borrable = [(i, tray[g]["args"]["path"])
                    for g in pos_guardar for i in idx_ruido if i > g]
    posibles = []
    if idx_sumar:
        posibles.append("valor_corrupto")
    if idx_borrable:
        posibles.append("borrado")
    posibles.append("sobrescritura")
    tipo = rng.choice(posibles)

    if tipo == "valor_corrupto":
        culpable = rng.choice(idx_sumar)
        # Fuera del rango valido -> el invariante queda roto para siempre.
        malo = rng.choice([-rng.randint(1, 50), _TOPE_VALOR + rng.randint(1, 500)])
        tray[culpable]["args"] = {"v": malo}
        tray[culpable]["result_head"] = f"sumado {malo}"
    elif tipo == "borrado":
        culpable, ruta = rng.choice(idx_borrable)
        tray[culpable] = {"action": "borrar", "args": {"path": ruta},
                          "ok": True, "result_head": f"borrado {ruta}"}
    else:  # sobrescritura
        culpable = rng.choice(pos_guardar)
        ruta = tray[culpable]["args"]["path"]
        tray[culpable]["args"] = {"path": ruta, "texto": "BASURA"}
        tray[culpable]["result_head"] = f"escrito {ruta}"

    # --- ruido de fallos (ok=False) --------------------------------------
    # Pasos que "fallaron" pero de los que el agente se recupero: no afectan al
    # invariante. Sin este ruido, la linea base (b) seria un espantapajaros.
    candidatos_ruido = [i for i in idx_ruido if i != culpable]
    rng.shuffle(candidatos_ruido)
    for i in candidatos_ruido[:rng.randint(0, 3)]:
        tray[i]["ok"] = False
        tray[i]["result_head"] = "ERROR: timeout"
    # En ~30% de los casos el propio paso culpable se marca fallido: es lo que
    # le da a la base (b) su unica via de acierto. La fraccion se declara y se
    # reporta, porque la precision de (b) esta ACOTADA por ella.
    if rng.random() < 0.30:
        tray[culpable]["ok"] = False

    n_fallidos = sum(1 for p in tray if p["ok"] is False)
    return {
        "trayectoria": tray,
        "culpable": culpable,
        "tipo": tipo,
        "n_fallidos": n_fallidos,
        "reproducir_fn": _vm_ejecutar,
        "veredicto_fn": (lambda est, _e=esperado: _vm_invariante(est, _e)),
    }


# ---------------------------------------------------------------------------
# medir_precision
# ---------------------------------------------------------------------------
def medir_precision(banco: Sequence[dict], presupuesto: int = 12) -> dict:
    """Corre `atribuir` sobre el banco y compara contra las DOS lineas base.

    Devuelve precision@1 de las tres, el coste en reproducciones y el detalle
    por caso. Un KILL medido (si el metodo no bate a las bases) es un resultado
    valido y sale del mismo dict.
    """
    aciertos = base_a = base_b = 0
    reps_total = 0
    ms_total = 0.0
    abstenciones = 0
    confs = []
    detalle = []
    por_tipo = {}
    for caso in banco:
        tray = caso["trayectoria"]
        verdad = caso["culpable"]
        inf = atribuir(tray, caso["veredicto_fn"],
                       reproducir_fn=caso["reproducir_fn"],
                       presupuesto=presupuesto)
        ok = (inf["paso_culpable"] == verdad)
        a = (linea_base_ultimo_paso(tray) == verdad)
        b = (linea_base_ultimo_fallido(tray) == verdad)
        aciertos += int(ok)
        base_a += int(a)
        base_b += int(b)
        reps_total += inf["reproducciones"]
        ms_total += inf["ms"]
        confs.append(inf["confianza"])
        if inf["paso_culpable"] is None:
            abstenciones += 1
        t = caso.get("tipo", "?")
        agg = por_tipo.setdefault(t, {"n": 0, "ok": 0, "a": 0, "b": 0})
        agg["n"] += 1
        agg["ok"] += int(ok)
        agg["a"] += int(a)
        agg["b"] += int(b)
        detalle.append({
            "tipo": t, "n_pasos": len(tray), "verdad": verdad,
            "metodo": inf["paso_culpable"], "ok": ok,
            "base_a": linea_base_ultimo_paso(tray),
            "base_b": linea_base_ultimo_fallido(tray),
            "reproducciones": inf["reproducciones"],
            "confianza": inf["confianza"],
        })
    n = max(1, len(banco))
    return {
        "n": len(banco),
        "presupuesto": presupuesto,
        "precision_metodo": round(aciertos / n, 4),
        "precision_base_ultimo_paso": round(base_a / n, 4),
        "precision_base_ultimo_fallido": round(base_b / n, 4),
        "reproducciones_media": round(reps_total / n, 3),
        "reproducciones_total": reps_total,
        "pasos_media": round(sum(len(c["trayectoria"]) for c in banco) / n, 2),
        "ms_media": round(ms_total / n, 4),
        "abstenciones": abstenciones,
        "confianza_media": round(sum(confs) / n, 3),
        "por_tipo": por_tipo,
        "detalle": detalle,
    }


def tabla_comparativa(res: dict) -> str:
    """Formatea el dict de `medir_precision` como la tabla del informe."""
    n = res["n"]
    filas = [
        ("METODO (biseccion + contrafactual)", res["precision_metodo"],
         f"{res['reproducciones_media']:.2f}"),
        ("BASE (a) el ultimo paso", res["precision_base_ultimo_paso"], "0.00"),
        ("BASE (b) el ultimo paso fallido", res["precision_base_ultimo_fallido"],
         "0.00"),
    ]
    out = [
        f"n={n} trayectorias | pasos/tray media={res['pasos_media']} | "
        f"presupuesto={res['presupuesto']}",
        "",
        f"{'metodo':<36} {'precision@1':>12} {'aciertos':>10} {'reprod/tray':>12}",
        "-" * 74,
    ]
    for nombre, prec, coste in filas:
        out.append(f"{nombre:<36} {prec:>12.3f} {int(round(prec*n)):>7}/{n:<2} "
                   f"{coste:>12}")
    out.append("-" * 74)
    out.append(f"confianza media={res['confianza_media']} | "
               f"abstenciones={res['abstenciones']} | "
               f"ms/tray={res['ms_media']:.3f}")
    out.append("")
    out.append("por tipo de fallo inyectado:")
    for t, a in sorted(res["por_tipo"].items()):
        out.append(f"  {t:<16} n={a['n']:<3} metodo={a['ok']}/{a['n']}  "
                   f"base_a={a['a']}/{a['n']}  base_b={a['b']}/{a['n']}")
    return "\n".join(out)


if __name__ == "__main__":  # pragma: no cover
    import sys
    n_tray = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    sem = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    lo_p = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    hi_p = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    pres = int(sys.argv[5]) if len(sys.argv) > 5 else 12
    banco = banco_inyeccion(n_tray, semilla=sem, pasos=(lo_p, hi_p))
    res = medir_precision(banco, presupuesto=pres)
    print(f"banco_inyeccion(n={n_tray}, semilla={sem})")
    print(tabla_comparativa(res))
    print()
    caso = banco[0]
    inf = atribuir(caso["trayectoria"], caso["veredicto_fn"],
                   reproducir_fn=caso["reproducir_fn"])
    print("--- explicar() sobre el caso 0 (verdad = paso "
          f"#{caso['culpable']}, tipo {caso['tipo']}) ---")
    print(explicar(inf, caso["trayectoria"]))
