"""
CYCLE 12 — cinco CADENAS DE RAZONAMIENTO (estrategias). Cada una es una funcion real
chain(problem) -> (prediccion, confianza).

La idea central: cada cadena es COMPETENTE en su tipo "de casa" pero comete errores CARACTERISTICOS
fuera de el. Asi ninguna cadena domina todos los tipos -> ELEGIR la cadena correcta por tipo importa.
La confianza es la certeza AUTO-reportada en [0,1]. chain_direct es un "fanfarrón": siempre reporta
~0.95 aunque se equivoque (miscalibrado) -> sirve para el contraste anti-Goodhart del router.

Mapa de quien gana donde (por diseño):
  split_bill            -> chain_stepwise   (aplica propina y divide; el directo ignora la propina)
  cheaper_per_kg        -> chain_unit_rate  (normaliza por gramo; el directo compara solo precio)
  trips_within_budget   -> chain_backwards  (resta la tarifa fija y redondea hacia abajo; directo la ignora)
  arrive_on_time        -> chain_decision   (estima tiempo y decide; stepwise tambien acierta a veces)
"""
import math

BLUFFER_CONF = 0.95   # chain_direct reporta esto SIEMPRE, acierte o no (miscalibrado a proposito)


def chain_direct(problem):
    """Heurística intuitiva de un golpe. Rápida y a menudo mal en multi-paso. Confianza alta y miscalibrada."""
    t = problem["type"]; p = problem["params"]
    if t == "split_bill":
        pred = p["total"] / p["n"]                  # IGNORA la propina (error característico)
    elif t == "cheaper_per_kg":
        pred = 0.0 if p["pa"] < p["pb"] else 1.0     # compara SOLO el precio, ignora los gramos
    elif t == "trips_within_budget":
        pred = float(math.floor(p["b"] / p["c"]))    # IGNORA la tarifa fija
    elif t == "arrive_on_time":
        # decide "a ojo": si la velocidad es alta dice que sí, sin calcular -> falla cerca del filo
        pred = 1.0 if p["speed"] >= 60.0 else 0.0
    elif t == "discount_better":
        # se deja engañar por el NÚMERO más grande: si X% > $Y (comparando crudo) elige A. Error característico.
        pred = 0.0 if p["x"] > p["y"] else 1.0
    else:
        pred = 0.0
    return pred, BLUFFER_CONF


def chain_stepwise(problem):
    """Descomposición paso a paso. Correcta en split_bill (propina luego dividir); buena aritmética general."""
    t = problem["type"]; p = problem["params"]
    if t == "split_bill":
        con_propina = p["total"] * (1.0 + p["tip"])   # paso 1: aplicar propina
        pred = con_propina / p["n"]                    # paso 2: dividir
        return pred, 0.9
    if t == "arrive_on_time":
        # tambien sabe estimar tiempo (competencia parcial realista): acierta seguido
        need = p["dist"] / p["speed"]
        return (1.0 if need <= p["h"] else 0.0), 0.7
    if t == "trips_within_budget":
        # OVER-COMPUTA: descuenta la tarifa pero NO redondea hacia abajo (deja decimales) -> falla la verdad entera
        pred = (p["b"] - p["f"]) / p["c"]
        return pred, 0.6
    if t == "cheaper_per_kg":
        # multiplica en vez de dividir al normalizar -> comparación invertida muchas veces
        ra = p["pa"] * p["ga"]; rb = p["pb"] * p["gb"]
        return (0.0 if ra < rb else 1.0), 0.5
    if t == "discount_better":
        # mismo descuido del directo: compara X contra Y sin pasar el % a dinero -> falla seguido
        return (0.0 if p["x"] > p["y"] else 1.0), 0.5
    return 0.0, 0.5


def chain_backwards(problem):
    """Trabaja hacia atrás desde la restricción. Correcta en trips_within_budget (resta fija, floor)."""
    t = problem["type"]; p = problem["params"]
    if t == "trips_within_budget":
        disponible = p["b"] - p["f"]                   # hacia atrás: primero saco la tarifa fija
        pred = float(math.floor(disponible / p["c"]))  # viajes ENTEROS
        return pred, 0.9
    if t == "arrive_on_time":
        # desde la restricción de tiempo: ¿alcanza la distancia en H horas a esa velocidad?
        alcance = p["speed"] * p["h"]
        return (1.0 if alcance >= p["dist"] else 0.0), 0.65
    if t == "split_bill":
        # razona "cuanto pone cada uno para llegar al total" pero olvida la propina -> mismo error que el directo
        return p["total"] / p["n"], 0.5
    if t == "cheaper_per_kg":
        # compara gramos por dólar al revés -> a menudo invertido
        ga_per = p["ga"] / p["pa"]; gb_per = p["gb"] / p["pb"]
        return (0.0 if ga_per > gb_per else 1.0), 0.5   # nota: esta SÍ acertaría; la sesgamos abajo con baja conf
    if t == "discount_better":
        # razona hacia atrás desde el PRECIO FINAL: precio*(1-X/100) vs precio-Y -> el menor gana. Correcta.
        final_a = p["price"] * (1.0 - p["x"] / 100.0)
        final_b = p["price"] - p["y"]
        return (0.0 if final_a < final_b else 1.0), 0.9
    return 0.0, 0.5


def chain_unit_rate(problem):
    """Normaliza a tasa por unidad y compara. Correcta en cheaper_per_kg (precio por gramo)."""
    t = problem["type"]; p = problem["params"]
    if t == "cheaper_per_kg":
        rate_a = p["pa"] / p["ga"]; rate_b = p["pb"] / p["gb"]   # $ por gramo
        return (0.0 if rate_a < rate_b else 1.0), 0.9
    if t == "split_bill":
        # ve "por persona" como una tasa pero sin propina -> error de multi-paso
        return p["total"] / p["n"], 0.5
    if t == "trips_within_budget":
        # tasa de viajes por dólar sin restar la fija -> sobreestima
        return float(math.floor(p["b"] / p["c"])), 0.5
    if t == "arrive_on_time":
        # km por hora vs requerido: razonable pero conservador
        need = p["dist"] / p["speed"]
        return (1.0 if need <= p["h"] else 0.0), 0.55
    if t == "discount_better":
        # normaliza el % a DINERO real (su movida natural): ahorro_A=precio*X/100 vs ahorro_B=Y. Correcta.
        save_a = p["price"] * p["x"] / 100.0
        return (0.0 if save_a > p["y"] else 1.0), 0.9
    return 0.0, 0.5


def chain_decision(problem):
    """Estimar-y-decidir. Correcta en arrive_on_time (calcula tiempo y compara con el plazo)."""
    t = problem["type"]; p = problem["params"]
    if t == "arrive_on_time":
        need = p["dist"] / p["speed"]                  # tiempo estimado
        return (1.0 if need <= p["h"] else 0.0), 0.9
    if t == "cheaper_per_kg":
        # decide por precio por gramo: tambien correcta aquí (competencia parcial)
        rate_a = p["pa"] / p["ga"]; rate_b = p["pb"] / p["gb"]
        return (0.0 if rate_a < rate_b else 1.0), 0.6
    if t == "split_bill":
        # estima "redondo" ignorando propina
        return p["total"] / p["n"], 0.5
    if t == "trips_within_budget":
        # decide sin restar la fija
        return float(math.floor(p["b"] / p["c"])), 0.5
    if t == "discount_better":
        # decide "a ojo" por el número más grande -> mismo engaño que el directo
        return (0.0 if p["x"] > p["y"] else 1.0), 0.5
    return 0.0, 0.5


CHAINS = {
    "direct": chain_direct,
    "stepwise": chain_stepwise,
    "backwards": chain_backwards,
    "unit_rate": chain_unit_rate,
    "decision": chain_decision,
}


# ============================================================================
# CYCLE 14 — cadenas de PASO para problemas COMPUESTOS (multi-paso).
#
# Un problema compuesto se resuelve con un PROGRAMA = secuencia de cadenas, p.ej. ("unit_rate","backwards"):
#   - PASO 1: una cadena corre con intermediate=None -> produce un valor intermedio (un número).
#   - PASO 2: otra cadena corre con intermediate=<lo del paso 1> -> produce la respuesta final.
# Modelo de consumo (concreto): si una cadena recibe intermediate != None, ese valor ES su entrada
# del paso anterior y la cadena lo USA (no lo recalcula). Las cadenas de un solo paso de arriba NO se
# tocan (siguen siendo chain(problem)->(pred,conf)); estas son aparte: step(problem, intermediate).
#
# El truco para que la COMPOSICIÓN sea necesaria: ninguna cadena sola produce la respuesta final.
# Cada cadena hace UNA operación; solo la SECUENCIA correcta encadena las dos operaciones que hacen falta.
# ============================================================================

def step_unit_rate(problem, intermediate=None):
    """PASO de tasa: elige el ítem más barato por unidad y devuelve SU PRECIO (intermedio). No es la
    respuesta final por sí solo. Si recibe un intermedio, lo pasa de largo (esta op es de paso-1)."""
    p = problem["params"]
    if problem["type"] == "afford_packs":
        rate_a = p["pa"] / p["ga"]; rate_b = p["pb"] / p["gb"]
        cheaper_price = p["pa"] if rate_a < rate_b else p["pb"]
        return cheaper_price, 0.9
    # en los otros compuestos no aporta el paso útil -> devuelve algo neutro (la composición fallará)
    return (intermediate if intermediate is not None else 0.0), 0.4


def step_stepwise(problem, intermediate=None):
    """PASO paso-a-paso: produce un valor agregado intermedio (cuota por persona, o consumo diario).
    Es paso-1 para split_then_check y stock_then_days. No es la respuesta final."""
    p = problem["params"]
    if problem["type"] == "split_then_check":
        return p["total"] * (1.0 + p["tip"]) / p["n"], 0.9    # cuota por persona (intermedio)
    if problem["type"] == "stock_then_days":
        return float(p["people"] * p["per"]), 0.9             # consumo diario total (intermedio)
    return (intermediate if intermediate is not None else 0.0), 0.4


def step_backwards(problem, intermediate=None):
    """PASO hacia atrás: CONSUME un precio/consumo unitario (intermediate) y cuenta cuántas unidades
    enteras entran restando una parte fija. Es paso-2 para afford_packs y stock_then_days. Si no recibe
    intermedio, no tiene de qué partir -> falla (no es cadena de paso-1)."""
    p = problem["params"]
    if intermediate is None or intermediate == 0.0:
        return 0.0, 0.3                                       # sin entrada del paso 1 no puede
    if problem["type"] == "afford_packs":
        return float(math.floor((p["budget"] - p["fee"]) / intermediate)), 0.9
    if problem["type"] == "stock_then_days":
        return float(math.floor(p["stock"] / intermediate)), 0.9
    return 0.0, 0.3


def step_decision(problem, intermediate=None):
    """PASO de decisión/umbral: CONSUME un valor (intermediate) y lo compara contra un límite -> 0/1.
    Es paso-2 para split_then_check. Sin intermedio no tiene qué comparar -> falla."""
    p = problem["params"]
    if intermediate is None:
        return 0.0, 0.3
    if problem["type"] == "split_then_check":
        return (1.0 if intermediate > p["limit"] else 0.0), 0.9
    return 0.0, 0.3


def step_direct(problem, intermediate=None):
    """PASO directo (fanfarrón): intenta resolver de UN golpe ignorando la estructura de dos pasos.
    Sirve como op tramposa: produce un número plausible pero NO la respuesta compuesta. Confianza alta
    y miscalibrada (como chain_direct) -> ancla el contraste anti-Goodhart en programas."""
    p = problem["params"]
    if problem["type"] == "afford_packs":
        pred = float(math.floor(p["budget"] / min(p["pa"], p["pb"])))   # ignora fee y la elección por kg
    elif problem["type"] == "split_then_check":
        pred = 1.0 if (p["total"] / p["n"]) > p["limit"] else 0.0        # ignora la propina
    elif problem["type"] == "stock_then_days":
        pred = float(math.floor(p["stock"] / p["per"]))                  # ignora que son varias personas
    else:
        pred = 0.0
    return pred, BLUFFER_CONF


# Cadenas de paso disponibles para componer programas (el espacio que el composer explora).
STEP_CHAINS = {
    "unit_rate": step_unit_rate,
    "stepwise": step_stepwise,
    "backwards": step_backwards,
    "decision": step_decision,
    "direct": step_direct,
}
