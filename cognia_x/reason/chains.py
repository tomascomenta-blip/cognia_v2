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
