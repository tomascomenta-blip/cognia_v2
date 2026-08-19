"""
cognia/monitores/guardias.py
============================
Los monitores que vigilan AL AGENTE (no a la maquina).

QUE RESUELVE
    cognia/monitores/sondas.py mira el mundo (GPU, disco, puertos). Este
    modulo mira la TAREA en curso: cuanto esta gastando, a que ritmo, cuanto
    lleva sin cerrar un paso y si esta dando vueltas sobre lo mismo. Son
    funciones PURAS: reciben un dict con el estado del turno y devuelven un
    veredicto. No leen relojes globales si les pasan la hora, no tocan el bus
    de eventos, no matan nada.

POR QUE EXISTE
    - El presupuesto por TOTAL llega tarde. Cuando `tokens_usados` cruza el
      techo ya se gasto todo; lo que avisa a tiempo es el RITMO (tokens/min) y
      la PROYECCION de agotamiento. Un agente que de golpe pasa de 300 tok/min
      a 40.000 tok/min esta en fuga, aunque todavia le quede la mitad del
      presupuesto. Eso es un circuit breaker por ritmo, no un contador.
    - El reloj de PARED es la otra averia real: una tarea que lleva N minutos
      sin cerrar un paso normalmente esta esperando algo que ya no va a llegar
      (un proceso muerto, un backend que no responde). Nadie lo nota porque no
      hay excepcion: es un vacio silencioso.
    - La repeticion ya tiene un detector serio y medido en
      cognia/hermes/guardia_bucle.py. Aqui NO se reimplementa: se delega. Si
      ese modulo no esta (paquete recortado), se degrada con un aviso honesto
      en vez de fallar; pero la degradacion se DECLARA en la evidencia, nunca
      se disfraza de 'ok' normal.

POLITICA, NO EJECUCION (regla dura)
    Ningun guardia mata procesos, cancela turnos ni lanza excepciones. Devuelve
    un veredicto y el que llama decide. Es el mismo contrato que
    `GuardiaBucle.registrar` (Hermes): "NUNCA lanzan y NUNCA ejecutan nada".

VEREDICTO (dict plano)
    {
      "estado":    "ok" | "aviso" | "corte",
      "mensaje":   str,     # una linea, apta para inyectar al modelo o loguear
      "evidencia": dict,    # los NUMEROS que sostienen el veredicto
    }
    'aviso' = decilo y segui. 'corte' = hay que parar (lo aplica el bucle).
    La evidencia lleva siempre las cifras crudas para que el veredicto sea
    auditable: un guardia que dice "vas muy rapido" sin el numero no es
    medicion, es opinion.

Solo stdlib.
"""
from __future__ import annotations

import time

# --------------------------------------------------------------------------
# Umbrales por defecto. Se pueden pisar con el dict `limites` de cada guardia:
# un parametro configurable SIEMPRE se falsifica, asi que los defaults tienen
# que ser utiles solos y los tests fijan los suyos.
# --------------------------------------------------------------------------

# Presupuesto: se avisa al 75% del techo y se corta al 100%. El corte por
# TOTAL es el suelo; lo que aporta este guardia es el ritmo.
FRAC_AVISO = 0.75
FRAC_CORTE = 1.0
# Proyeccion: si al ritmo actual el presupuesto se agota antes de estos
# segundos, se avisa aunque el total todavia este comodo.
HORIZONTE_AVISO_S = 120.0
HORIZONTE_CORTE_S = 20.0
# Fuga descarada: ningun turno sano de esta maquina sostiene este ritmo
# (Qwythos-9B local va a ~40-70 tok/s = 2.400-4.200 tok/min).
RITMO_FUGA_TPM = 30000.0
# Antes de esto no hay ritmo que medir: dos tokens en 0,2 s dan cifras absurdas.
MUESTRA_MINIMA_S = 5.0

# Pared: minutos sin cerrar un paso.
PARED_AVISO_MIN = 5.0
PARED_CORTE_MIN = 15.0


def _veredicto(estado: str = "ok", mensaje: str = "", evidencia=None) -> dict:
    return {"estado": estado, "mensaje": mensaje,
            "evidencia": dict(evidencia or {})}


def _num_opt(estado: dict, claves):
    """Primer valor numerico presente entre varios nombres posibles, o None.

    El estado del turno lo arma el bucle y los nombres han ido cambiando
    (tokens/tokens_usados, t0/inicio_ts). Aceptar sinonimos aqui es mas barato
    que obligar a tocar el bucle, y evita que el guardia quede MUDO por un
    rename (que es el peor fallo posible: un guardia que no avisa nunca).

    Devuelve None y no 0.0 cuando falta: un timestamp 0.0 es FALSY y la
    primera version de este modulo lo trataba como "sin dato", de modo que un
    reloj monotono que empieza en cero dejaba ciegos a los dos guardias de
    tiempo. Ausente y cero no son lo mismo.
    """
    for clave in claves:
        if clave in estado and estado[clave] is not None:
            try:
                return float(estado[clave])
            except (TypeError, ValueError):
                continue
    return None


def _num(estado: dict, claves, defecto=0.0) -> float:
    valor = _num_opt(estado, claves)
    return float(defecto) if valor is None else valor


def _limite(limites: dict, clave: str, defecto: float) -> float:
    try:
        return float(limites.get(clave, defecto))
    except (TypeError, ValueError):
        return float(defecto)


def _blindar(fn):
    """Envuelve un guardia para que jamas rompa el turno.

    Un guardia roto no puede matar una tarea sana (misma regla que el bus de
    eventos y que GuardiaBucle). Sale como 'ok', pero la evidencia dice que
    fallo: silenciarlo del todo seria fabricar un guardia fantasma que aprueba
    siempre, y esa es justo la clase de instrumento que aprueba lo roto.
    """
    def envuelto(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return _veredicto("ok", f"guardia {fn.__name__} fallo: {exc}",
                              {"error": f"{type(exc).__name__}: {exc}",
                               "guardia_roto": True})
    envuelto.__name__ = fn.__name__
    envuelto.__doc__ = fn.__doc__
    return envuelto


# --------------------------------------------------------------------------
# A. Presupuesto: circuit breaker por RITMO
# --------------------------------------------------------------------------

def _ritmo_reciente(muestras, ahora: float, usados: float) -> tuple:
    """(tokens_por_min, ventana_s, origen) a partir de la serie de muestras.

    `muestras` es [(ts, tokens_acumulados), ...] tal como la puede ir
    apendando el bucle en cada paso. Se usan las DOS puntas de la serie (o la
    ultima muestra contra ahora) porque lo que interesa es el ritmo del tramo
    reciente, no el promedio de toda la tarea: una tarea que penso 10 min y
    ahora vomita tokens tiene un promedio tranquilizador y un ritmo de fuga.
    """
    pares = []
    for m in (muestras or []):
        try:
            if isinstance(m, dict):
                pares.append((float(m.get("ts")), float(m.get("tokens"))))
            else:
                pares.append((float(m[0]), float(m[1])))
        except (TypeError, ValueError, IndexError):
            continue
    if len(pares) < 2:
        return 0.0, 0.0, "sin_muestras"
    pares.sort(key=lambda p: p[0])
    # Se cierra la serie con el estado ACTUAL: si el bucle no apendo la ultima
    # muestra, el tramo vivo se perderia justo cuando mas importa.
    if ahora > pares[-1][0] and usados >= pares[-1][1]:
        pares.append((ahora, usados))
    ini, fin = pares[0], pares[-1]
    ventana = fin[0] - ini[0]
    if ventana <= 0:
        return 0.0, 0.0, "ventana_nula"
    return max(0.0, (fin[1] - ini[1])) * 60.0 / ventana, ventana, "muestras"


@_blindar
def guardia_presupuesto(estado: dict, limites=None, ahora=None) -> dict:
    """Vigila el gasto de tokens por TOTAL y sobre todo por RITMO.

    estado (todo opcional, con sinonimos tolerados):
      tokens_usados | tokens ......... acumulado del turno
      presupuesto_tokens | presupuesto techo (0 = sin techo)
      inicio_ts | t0 | inicio ........ cuando arranco el turno
      ahora | ts ..................... reloj inyectado (para tests)
      muestras ....................... [(ts, tokens), ...] serie del turno
    limites: frac_aviso, frac_corte, horizonte_aviso_s, horizonte_corte_s,
             ritmo_fuga_tpm, muestra_minima_s.

    Devuelve 'corte' si se paso del techo, si a este ritmo se lo come en menos
    de horizonte_corte_s, o si el ritmo es directamente una fuga.
    """
    estado = estado or {}
    limites = limites or {}
    momento = float(ahora) if ahora is not None else _num(
        estado, ("ahora", "ts"), time.time())
    usados = _num(estado, ("tokens_usados", "tokens", "tokens_predichos"), 0.0)
    techo = _num(estado, ("presupuesto_tokens", "presupuesto", "techo"), 0.0)
    inicio = _num_opt(estado, ("inicio_ts", "t0", "inicio"))

    transcurrido = max(0.0, momento - inicio) if inicio is not None else 0.0
    ritmo_medio = (usados * 60.0 / transcurrido) if transcurrido > 0 else 0.0
    ritmo, ventana, origen = _ritmo_reciente(estado.get("muestras"), momento, usados)
    if origen != "muestras" or ventana < _limite(limites, "muestra_minima_s", MUESTRA_MINIMA_S):
        # Sin serie utilizable se cae al promedio del turno; peor resolucion,
        # pero es medicion y no invento. El origen viaja en la evidencia.
        ritmo, origen = ritmo_medio, "promedio"

    restantes = max(0.0, techo - usados) if techo > 0 else 0.0
    seg_para_agotar = (restantes * 60.0 / ritmo) if (techo > 0 and ritmo > 0) else -1.0
    frac = (usados / techo) if techo > 0 else 0.0

    ev = {"tokens_usados": round(usados), "presupuesto": round(techo),
          "fraccion": round(frac, 3), "ritmo_tpm": round(ritmo, 1),
          "ritmo_medio_tpm": round(ritmo_medio, 1), "origen_ritmo": origen,
          "ventana_s": round(ventana, 1),
          "transcurrido_s": round(transcurrido, 1),
          "seg_para_agotar": round(seg_para_agotar, 1)}

    fuga = _limite(limites, "ritmo_fuga_tpm", RITMO_FUGA_TPM)
    if techo > 0 and frac >= _limite(limites, "frac_corte", FRAC_CORTE):
        return _veredicto("corte",
                          f"Presupuesto agotado: {ev['tokens_usados']} de "
                          f"{ev['presupuesto']} tokens.", ev)
    if ritmo >= fuga and origen == "muestras":
        # Solo con muestras reales: el promedio de un turno de 2 s da cifras
        # enormes y cortar por eso seria matar tareas sanas.
        return _veredicto("corte",
                          f"Ritmo de fuga: {ev['ritmo_tpm']} tok/min en los "
                          f"ultimos {ev['ventana_s']} s (techo {fuga:g}).", ev)
    if 0 <= seg_para_agotar <= _limite(limites, "horizonte_corte_s", HORIZONTE_CORTE_S):
        return _veredicto("corte",
                          f"A {ev['ritmo_tpm']} tok/min el presupuesto se agota "
                          f"en {ev['seg_para_agotar']} s.", ev)
    if techo > 0 and frac >= _limite(limites, "frac_aviso", FRAC_AVISO):
        return _veredicto("aviso",
                          f"Presupuesto al {int(frac * 100)}% "
                          f"({ev['tokens_usados']}/{ev['presupuesto']} tokens): "
                          "cerra con lo que tengas.", ev)
    if 0 <= seg_para_agotar <= _limite(limites, "horizonte_aviso_s", HORIZONTE_AVISO_S):
        return _veredicto("aviso",
                          f"A {ev['ritmo_tpm']} tok/min quedan "
                          f"{ev['seg_para_agotar']} s de presupuesto.", ev)
    return _veredicto("ok", "", ev)


# --------------------------------------------------------------------------
# B. Pared: minutos sin cerrar un paso
# --------------------------------------------------------------------------

@_blindar
def guardia_pared(estado: dict, limites=None, ahora=None) -> dict:
    """Vigila cuanto lleva la tarea sin CERRAR un paso.

    estado:
      ultimo_paso_ts | ultimo_evento_ts | ultimo_ts  cuando se cerro el ultimo paso
      inicio_ts | t0 | inicio ..................... arranque (referencia si aun
                                                   no cerro ninguno)
      paso ....................................... numero de paso en curso
      ahora | ts ................................. reloj inyectado
    limites: aviso_min, corte_min.

    Por que la referencia cae al inicio: la tarea que NUNCA cierra un paso es
    el caso peor (se colgo en el primero) y es justo el que se escaparia si el
    guardia exigiera un `ultimo_paso_ts` que nunca llega.
    """
    estado = estado or {}
    limites = limites or {}
    momento = float(ahora) if ahora is not None else _num(
        estado, ("ahora", "ts"), time.time())
    inicio = _num_opt(estado, ("inicio_ts", "t0", "inicio"))
    ultimo = _num_opt(estado, ("ultimo_paso_ts", "ultimo_evento_ts", "ultimo_ts"))
    referencia = ultimo if ultimo is not None else inicio
    if referencia is None:
        # Sin ninguna marca de tiempo no hay pared que medir. Se declara en la
        # evidencia en vez de inventar un 0 que pareceria "recien empezado".
        return _veredicto("ok", "", {"medible": False,
                                     "motivo": "sin marcas de tiempo"})
    quieto_s = max(0.0, momento - referencia)
    quieto_min = quieto_s / 60.0
    hay_pasos = ultimo is not None
    ev = {"medible": True, "quieto_min": round(quieto_min, 2),
          "quieto_s": round(quieto_s, 1), "paso": int(_num(estado, ("paso",), 0)),
          "referencia": "ultimo_paso" if hay_pasos else "inicio_tarea",
          "sin_pasos_cerrados": not hay_pasos}
    corte_min = _limite(limites, "corte_min", PARED_CORTE_MIN)
    aviso_min = _limite(limites, "aviso_min", PARED_AVISO_MIN)
    que = "cerrar un paso" if hay_pasos else "cerrar su PRIMER paso"
    if quieto_min >= corte_min:
        return _veredicto("corte",
                          f"La tarea lleva {ev['quieto_min']} min sin {que} "
                          f"(paso {ev['paso']}): se da por colgada.", ev)
    if quieto_min >= aviso_min:
        return _veredicto("aviso",
                          f"La tarea lleva {ev['quieto_min']} min sin {que} "
                          f"(paso {ev['paso']}).", ev)
    return _veredicto("ok", "", ev)


# --------------------------------------------------------------------------
# C. Repeticion: delega en cognia/hermes/guardia_bucle.py
# --------------------------------------------------------------------------

# Mapa del veredicto de GuardiaBucle al de este modulo. 'bloqueo' alli es
# 'corte' aqui: el vocabulario de los tres guardias tiene que ser uno solo o el
# bucle termina con tres ramas distintas de politica.
_MAPA_BUCLE = {"ok": "ok", "aviso": "aviso", "bloqueo": "corte"}


def _fabrica_por_defecto():
    """Construye el GuardiaBucle real con las exentas de Cognia."""
    from cognia.hermes.guardia_bucle import GuardiaBucle, EXENTAS_COGNIA
    return GuardiaBucle(ventana=10, umbral=3, max_avisos=2, exentas=EXENTAS_COGNIA)


def _repeticion_degradada(historial: list) -> dict:
    """Deteccion minima cuando guardia_bucle no esta disponible.

    Solo cuenta repeticiones CONSECUTIVAS identicas al final del historial: no
    ve ping-pong ni ciclos. Es deliberadamente pobre — su unico trabajo es que
    la ausencia del modulo bueno no deje al agente sin ninguna vigilancia, y
    que la evidencia diga a gritos que esto es un sustituto.
    """
    if len(historial) < 3:
        return _veredicto("ok", "", {"degradado": True, "repeticiones": len(historial)})
    ultimo = historial[-1]
    repes = 0
    for item in reversed(historial):
        if item != ultimo:
            break
        repes += 1
    ev = {"degradado": True, "repeticiones": repes, "accion": str(ultimo)[:120]}
    if repes >= 3:
        return _veredicto("aviso",
                          f"AVISO DE BUCLE (deteccion degradada, sin "
                          f"cognia.hermes.guardia_bucle): '{ev['accion']}' se "
                          f"repitio {repes} veces seguidas.", ev)
    return _veredicto("ok", "", ev)


@_blindar
def guardia_repeticion(estado: dict, fabrica=None) -> dict:
    """Vigila que el agente no este dando vueltas sobre las mismas acciones.

    estado:
      historial | llamadas | acciones -> lista de acciones en orden. Cada item
      puede ser (tool, args), {'tool':..,'args':..} o una cadena.

    La deteccion REAL la hace cognia/hermes/guardia_bucle.py (ventana
    deslizante, repeticion / ping-pong / ciclo de periodo N, escalada
    aviso->bloqueo y tools exentas por polling legitimo). Aqui solo se re-corre
    el historial sobre una instancia fresca, para que la funcion sea PURA:
    mismo historial, mismo veredicto, sin estado escondido entre llamadas.

    `fabrica` se inyecta en los tests (incluido el caso en que no exista el
    modulo: entonces se degrada con aviso en vez de fallar).
    """
    estado = estado or {}
    crudo = (estado.get("historial") or estado.get("llamadas")
             or estado.get("acciones") or [])
    historial = []
    for item in crudo:
        if isinstance(item, dict):
            historial.append((str(item.get("tool", "")), item.get("args", "")))
        elif isinstance(item, (list, tuple)) and item:
            historial.append((str(item[0]), item[1] if len(item) > 1 else ""))
        else:
            historial.append((str(item), ""))
    if not historial:
        return _veredicto("ok", "", {"repeticiones": 0, "pasos": 0})

    try:
        guardia = (fabrica or _fabrica_por_defecto)()
    except Exception as exc:
        # Sin el modulo bueno NO se falla: se degrada y se DECLARA. Una via
        # degradada en silencio es el modo de fallo historico del repo.
        salida = _repeticion_degradada(historial)
        salida["evidencia"]["motivo"] = f"{type(exc).__name__}: {exc}"
        if salida["estado"] == "ok":
            salida["mensaje"] = ("guardia_repeticion degradado: "
                                 "cognia.hermes.guardia_bucle no disponible")
        return salida

    veredicto = {"estado": "ok"}
    for tool, args in historial:
        veredicto = guardia.registrar(tool, args)
    estado_final = _MAPA_BUCLE.get(str(veredicto.get("estado", "ok")), "ok")
    ev = {"degradado": False, "pasos": len(historial),
          "patron": veredicto.get("patron", ""),
          "repeticiones": int(veredicto.get("repeticiones", 0) or 0),
          "avisos": int(veredicto.get("avisos", 0) or 0),
          "tool": veredicto.get("tool", ""), "firma": veredicto.get("firma", "")}
    return _veredicto(estado_final, str(veredicto.get("mensaje", "")), ev)


# --------------------------------------------------------------------------
# Registro + veredicto combinado
# --------------------------------------------------------------------------

GUARDIAS = {
    "presupuesto": guardia_presupuesto,
    "pared": guardia_pared,
    "repeticion": guardia_repeticion,
}

# Orden de severidad: el peor veredicto manda.
_SEVERIDAD = {"ok": 0, "aviso": 1, "corte": 2}


def evaluar_guardias(estado: dict, cuales=None) -> dict:
    """Corre los guardias y devuelve el PEOR veredicto, con el detalle de todos.

    El bucle necesita UNA decision, no tres: si cualquiera pide corte, se corta;
    si ninguno corta pero alguno avisa, se avisa (y se inyectan los mensajes).
    """
    nombres = list(cuales) if cuales else list(GUARDIAS)
    detalle = {}
    peor = "ok"
    mensajes = []
    for nombre in nombres:
        fn = GUARDIAS.get(nombre)
        if fn is None:
            continue
        v = fn(estado)
        detalle[nombre] = v
        if _SEVERIDAD.get(v["estado"], 0) > _SEVERIDAD.get(peor, 0):
            peor = v["estado"]
        if v["estado"] != "ok" and v["mensaje"]:
            mensajes.append(f"[{nombre}] {v['mensaje']}")
    return {"estado": peor, "mensaje": " ".join(mensajes),
            "evidencia": {"guardias": detalle}}
