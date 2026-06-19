"""
CYCLE 12 — problemas cotidianos con verificador de verdad-base.

Cada problema es una situacion de todos los dias que se PUEDE resolver bien con UNA forma de razonar
y mal con las otras (por eso despues importa CUAL cadena elegir). El verificador guarda la respuesta
exacta (la "verdad") para poder premiar de forma NO circular: la realidad decide, no la confianza.

Un Problem es un dict plano: {"type", "text", "answer", "params"}.
"""
import math
from random import Random

TYPES = ["split_bill", "cheaper_per_kg", "trips_within_budget", "arrive_on_time"]


def _split_bill(rng):
    # dividir la cuenta: N amigos, total $T, propina tip% -> cuanto paga cada uno (multi-paso)
    n = rng.randint(2, 8)
    total = round(rng.uniform(20.0, 200.0), 2)
    tip = rng.choice([0.0, 0.05, 0.10, 0.12, 0.15, 0.20])
    ans = total * (1.0 + tip) / n
    text = f"{n} amigos comen, la cuenta es ${total:.2f} y dejan {int(tip*100)}% de propina. ¿Cuánto paga cada uno?"
    return {"type": "split_bill", "text": text, "answer": ans,
            "params": {"n": n, "total": total, "tip": tip}}


def _cheaper_per_kg(rng):
    # ¿que paquete conviene? precio/peso de A vs B -> 0 si A es mas barato por kg, 1 si B (comparacion por tasa)
    pa = round(rng.uniform(1.0, 30.0), 2); ga = rng.randint(100, 2000)
    pb = round(rng.uniform(1.0, 30.0), 2); gb = rng.randint(100, 2000)
    rate_a = pa / ga; rate_b = pb / gb
    # evitar empates ambiguos (que arruinarian la verdad-base)
    while abs(rate_a - rate_b) < 1e-4:
        pb = round(rng.uniform(1.0, 30.0), 2); gb = rng.randint(100, 2000); rate_b = pb / gb
    ans = 0.0 if rate_a < rate_b else 1.0
    text = (f"Paquete A: ${pa:.2f} por {ga} g. Paquete B: ${pb:.2f} por {gb} g. "
            f"¿Cuál conviene? (0=A, 1=B)")
    return {"type": "cheaper_per_kg", "text": text, "answer": ans,
            "params": {"pa": pa, "ga": ga, "pb": pb, "gb": gb}}


def _trips_within_budget(rng):
    # presupuesto $B, cada viaje cuesta $c, una tarifa fija $f por sacar la tarjeta -> cuantos viajes enteros
    f = round(rng.uniform(1.0, 8.0), 2)
    c = round(rng.uniform(0.8, 5.0), 2)
    b = round(rng.uniform(f + 5 * c, f + 40 * c), 2)
    ans = float(math.floor((b - f) / c))
    text = (f"Tenés ${b:.2f}. La tarjeta cuesta ${f:.2f} una vez y cada viaje ${c:.2f}. "
            f"¿Cuántos viajes enteros podés hacer?")
    return {"type": "trips_within_budget", "text": text, "answer": ans,
            "params": {"b": b, "c": c, "f": f}}


def _discount_better(rng):
    # dos ofertas sobre un mismo precio P: A = X% off, B = $Y off -> ¿cuál ahorra más? (0=A, 1=B)
    # WHY: tipo NUEVO usado SOLO en test (CYCLE 13, fuera-de-distribución). El ahorro de A es P*X/100,
    # el de B es Y fijo -> verdad-base computable; el "directo" se deja engañar por el número grande.
    price = round(rng.uniform(20.0, 500.0), 2)
    x = rng.choice([5, 10, 15, 20, 25, 30, 40, 50])      # porcentaje de descuento de A
    y = round(rng.uniform(2.0, 120.0), 2)                # descuento fijo en $ de B
    save_a = price * x / 100.0
    save_b = y
    # evitar empates ambiguos (arruinarian la verdad-base)
    while abs(save_a - save_b) < 1e-3:
        y = round(rng.uniform(2.0, 120.0), 2); save_b = y
    ans = 0.0 if save_a > save_b else 1.0
    text = (f"Un producto sale ${price:.2f}. Oferta A: {x}% de descuento. Oferta B: ${y:.2f} de descuento. "
            f"¿Cuál ahorra más? (0=A, 1=B)")
    return {"type": "discount_better", "text": text, "answer": ans,
            "params": {"price": price, "x": x, "y": y}}


def _arrive_on_time(rng):
    # ¿llegás a tiempo? distancia km, velocidad km/h, plazo H horas -> 1 si dist/vel <= H, si no 0 (decision)
    dist = round(rng.uniform(10.0, 300.0), 1)
    speed = round(rng.uniform(20.0, 120.0), 1)
    h = round(rng.uniform(0.5, 6.0), 1)
    need = dist / speed
    # evitar el filo exacto (decision ambigua)
    while abs(need - h) < 1e-3:
        h = round(rng.uniform(0.5, 6.0), 1); need = dist / speed
    ans = 1.0 if need <= h else 0.0
    text = (f"Tenés que recorrer {dist:.1f} km a {speed:.1f} km/h y llegar en {h:.1f} horas. "
            f"¿Llegás a tiempo? (1=sí, 0=no)")
    return {"type": "arrive_on_time", "text": text, "answer": ans,
            "params": {"dist": dist, "speed": speed, "h": h}}


# tipo NUEVO de CYCLE 13: NO está en TYPES (que sigue siendo los 4 originales para no romper cycle12).
# Se agrega SOLO cuando se pide explícitamente (out-of-distribution: presente solo en el test set).
OOD_TYPE = "discount_better"


# ============================================================================
# CYCLE 14 — problemas COMPUESTOS (multi-paso): NINGUNA cadena de un solo paso los resuelve.
# La respuesta necesita el OUTPUT del paso 1 como ENTRADA del paso 2 (un pequeño "programa" de
# razonamiento = una SECUENCIA de cadenas). Se agregan en un generador APARTE (gen_composed) para
# que TYPES/gen_problems sigan byte-a-byte iguales -> cycle12/13 no se tocan.
#
# Modelo de ejecución (concreto y explícito): cada problema compuesto guarda en params un
# "intermediate" = el valor que produce el paso 1 correcto, y la "answer" = lo que produce el paso 2
# al consumir ese intermediate. Una cadena de paso-2 consume el intermediate por un argumento opcional.
# ============================================================================
COMPOSED_TYPES = ["afford_packs", "split_then_check", "stock_then_days"]


def _afford_packs(rng):
    # PASO 1 (tasa/comparación): ¿qué paquete es más barato por kg? -> precio del más barato.
    # PASO 2 (hacia atrás): con un presupuesto y una tarifa fija de envío, ¿cuántos del más barato entran?
    pa = round(rng.uniform(2.0, 30.0), 2); ga = rng.randint(200, 2000)
    pb = round(rng.uniform(2.0, 30.0), 2); gb = rng.randint(200, 2000)
    rate_a = pa / ga; rate_b = pb / gb
    while abs(rate_a - rate_b) < 1e-4:
        pb = round(rng.uniform(2.0, 30.0), 2); gb = rng.randint(200, 2000); rate_b = pb / gb
    cheaper_price = pa if rate_a < rate_b else pb        # intermediate del paso 1
    fee = round(rng.uniform(1.0, 10.0), 2)
    budget = round(rng.uniform(fee + 2 * cheaper_price, fee + 25 * cheaper_price), 2)
    ans = float(math.floor((budget - fee) / cheaper_price))   # paso 2 consume cheaper_price
    text = (f"Paquete A: ${pa:.2f} por {ga} g. Paquete B: ${pb:.2f} por {gb} g. Elegí el más barato por kg. "
            f"Tenés ${budget:.2f} y el envío fijo cuesta ${fee:.2f}. ¿Cuántos del más barato podés comprar?")
    return {"type": "afford_packs", "text": text, "answer": ans,
            "params": {"pa": pa, "ga": ga, "pb": pb, "gb": gb, "fee": fee, "budget": budget,
                       "intermediate": cheaper_price}}


def _split_then_check(rng):
    # PASO 1 (paso-a-paso): dividir la cuenta con propina entre N -> cuánto paga cada uno.
    # PASO 2 (decisión/umbral): ¿esa cuota por persona supera un límite L? (1=supera, 0=no).
    n = rng.randint(2, 8)
    total = round(rng.uniform(20.0, 200.0), 2)
    tip = rng.choice([0.0, 0.05, 0.10, 0.12, 0.15, 0.20])
    share = total * (1.0 + tip) / n               # intermediate del paso 1
    limit = round(rng.uniform(5.0, 60.0), 2)
    while abs(share - limit) < 1e-3:              # evitar el filo exacto (decisión ambigua)
        limit = round(rng.uniform(5.0, 60.0), 2)
    ans = 1.0 if share > limit else 0.0           # paso 2 consume share
    text = (f"{n} amigos comen, la cuenta es ${total:.2f} con {int(tip*100)}% de propina. "
            f"¿La cuota por persona supera ${limit:.2f}? (1=sí, 0=no)")
    return {"type": "split_then_check", "text": text, "answer": ans,
            "params": {"n": n, "total": total, "tip": tip, "limit": limit, "intermediate": share}}


def _stock_then_days(rng):
    # PASO 1 (paso-a-paso): consumo diario total = personas * unidades por persona por día.
    # PASO 2 (hacia atrás): con un stock dado, ¿cuántos días ENTEROS alcanza? floor(stock/consumo).
    people = rng.randint(2, 10)
    per = rng.randint(1, 6)
    daily = float(people * per)                   # intermediate del paso 1
    stock = rng.randint(int(daily) + 1, int(daily) * 30 + 1)
    ans = float(math.floor(stock / daily))        # paso 2 consume daily
    text = (f"Sos {people} personas y cada una consume {per} por día. Tenés un stock de {stock}. "
            f"¿Para cuántos días ENTEROS alcanza?")
    return {"type": "stock_then_days", "text": text, "answer": ans,
            "params": {"people": people, "per": per, "stock": stock, "intermediate": daily}}

_GENS = {
    "split_bill": _split_bill,
    "cheaper_per_kg": _cheaper_per_kg,
    "trips_within_budget": _trips_within_budget,
    "arrive_on_time": _arrive_on_time,
    "discount_better": _discount_better,
    "afford_packs": _afford_packs,
    "split_then_check": _split_then_check,
    "stock_then_days": _stock_then_days,
}


def gen_composed(n, seed, types=None):
    """
    CYCLE 14 — genera n problemas COMPUESTOS balanceados entre COMPOSED_TYPES. Determinista por `seed`.
    APARTE de gen_problems a propósito: cycle12/13 nunca ven estos tipos (siguen byte-a-byte iguales).
    """
    use = list(types) if types is not None else COMPOSED_TYPES
    rng = Random(seed)
    out = []
    for i in range(n):
        t = use[i % len(use)]
        out.append(_GENS[t](rng))
    rng.shuffle(out)
    return out


def gen_problems(n, seed, types=None):
    """
    Genera n problemas balanceados entre los tipos pedidos. Determinista por `seed` (Random local).
    Backward-compatible: sin `types` usa los 4 tipos originales (TYPES) -> cycle12 corre igual.
    Pasar types=["discount_better", ...] para incluir el tipo NUEVO (CYCLE 13).
    """
    use = list(types) if types is not None else TYPES
    rng = Random(seed)
    out = []
    for i in range(n):
        t = use[i % len(use)]
        out.append(_GENS[t](rng))
    rng.shuffle(out)
    return out


# ============================================================================
# CYCLE 15 — competencia GRADUADA: el mundo de todos los días no es perfecto.
#
# El problema honesto que arrastraban CYCLE 12/13/14: los solvers son DETERMINISTAS y EXACTOS, así que
# el oráculo da 1.000 y la política aprendida también -> "techo sintético perfecto" como caveat repetido.
# CYCLE 15 lo ROMPE introduciendo dificultad real y controlable: cada problema trae un parámetro
# `difficulty` en [0,1] (un instance MÁS DURO: comparaciones casi-empatadas, plazos al filo, propinas que
# obligan a redondeos finos). Sobre eso, una cadena "patina" a veces (ver chains.py graded_chain) y patina
# MÁS cuanto más duro es el problema. Resultado: ninguna estrategia es perfecta, el oráculo cae < 1.0 y la
# cercanía del router al oráculo pasa a ser un número con SIGNIFICADO (la brecha honesta).
#
# Esto es OPT-IN: gen_problems/gen_composed NO cambian (cycle12/13/14 corren byte-a-byte iguales). La
# dureza se inyecta SOLO acá, marcando cada problema con params["difficulty"] (los generadores viejos no
# lo ponen -> graded_chain trata "sin difficulty" como difficulty=0 = competencia base, comportamiento
# antiguo). El generador graduado además fuerza instancias DUROS (cerca del filo) según la dificultad.
# ============================================================================

def _harden(problem, rng, difficulty):
    """
    Endurece una instancia ya generada según `difficulty` en [0,1]: acerca la decisión al FILO para que
    un patinazo chico de la cadena pueda DAR VUELTA la respuesta (decisiones casi-empate / plazos ajustados).
    No cambia el TIPO ni rompe la verdad-base: recomputa la answer de forma consistente con los params.
    WHY: la dureza tiene que vivir en el problema (no solo en la cadena) para que el patinazo importe.
    """
    t = problem["type"]; p = problem["params"]
    # margen objetivo: a más dificultad, MÁS cerca del filo (pero nunca empate exacto -> verdad-base nítida)
    near = (1.0 - difficulty)            # 1.0 fácil (lejos del filo), ~0 duro (casi al filo)
    if t == "cheaper_per_kg":
        # acercar rate_b a rate_a proporcional a la dureza (casi-empate de precio por gramo)
        rate_a = p["pa"] / p["ga"]
        gap = rate_a * (0.02 + 0.30 * near)        # separación relativa deseada
        sign = 1.0 if rng.random() < 0.5 else -1.0
        rate_b = rate_a * (1.0 + sign * gap)
        p["pb"] = round(max(0.01, rate_b * p["gb"]), 2)
        rate_b = p["pb"] / p["gb"]
        if abs(rate_a - rate_b) < 1e-6:
            p["pb"] = round(p["pb"] + 0.01, 2); rate_b = p["pb"] / p["gb"]
        problem["answer"] = 0.0 if rate_a < rate_b else 1.0
    elif t == "arrive_on_time":
        # poner el plazo H cerca del tiempo necesario (decisión al filo cuando es duro)
        need = p["dist"] / p["speed"]
        slack = need * (0.02 + 0.30 * near)
        sign = 1.0 if rng.random() < 0.5 else -1.0
        p["h"] = round(max(0.1, need + sign * slack), 1)
        if abs(p["dist"] / p["speed"] - p["h"]) < 1e-3:
            p["h"] = round(p["h"] + 0.1, 1)
        problem["answer"] = 1.0 if need <= p["h"] else 0.0
    elif t == "discount_better":
        # acercar el descuento fijo Y al ahorro porcentual de A (casi-empate de ahorro)
        save_a = p["price"] * p["x"] / 100.0
        gap = save_a * (0.02 + 0.30 * near)
        sign = 1.0 if rng.random() < 0.5 else -1.0
        p["y"] = round(max(0.5, save_a + sign * gap), 2)
        if abs(save_a - p["y"]) < 1e-3:
            p["y"] = round(p["y"] + 0.5, 2)
        problem["answer"] = 0.0 if save_a > p["y"] else 1.0
    elif t == "trips_within_budget":
        # dejar el presupuesto JUSTO sobre un múltiplo entero de viajes (resto chico -> floor sensible)
        k = math.floor((p["b"] - p["f"]) / p["c"])
        k = max(1, k)
        resto = p["c"] * (0.05 + 0.40 * near)      # cuánto sobra por encima de k viajes (chico = duro)
        p["b"] = round(p["f"] + k * p["c"] + resto, 2)
        problem["answer"] = float(math.floor((p["b"] - p["f"]) / p["c"]))
    elif t == "split_bill":
        # split_bill no tiene "filo" binario; la dureza vive en el patinazo de redondeo de la cadena.
        problem["answer"] = p["total"] * (1.0 + p["tip"]) / p["n"]
    p["difficulty"] = float(difficulty)
    return problem


def gen_graded(n, seed, types=None, dmin=0.0, dmax=1.0):
    """
    CYCLE 15 — genera n problemas GRADUADOS: como gen_problems pero (a) marca cada uno con una dificultad
    en [dmin,dmax] y (b) lo ENDURECE (acerca la decisión al filo según la dureza). Determinista por `seed`.
    APARTE de gen_problems a propósito -> cycle12/13/14 nunca ven `difficulty` (siguen idénticos).
    """
    use = list(types) if types is not None else TYPES
    rng = Random(seed)
    out = []
    for i in range(n):
        t = use[i % len(use)]
        prob = _GENS[t](rng)
        difficulty = rng.uniform(dmin, dmax)
        out.append(_harden(prob, rng, difficulty))
    rng.shuffle(out)
    return out


# ============================================================================
# CYCLE 17 — PARÁFRASIS + VOCABULARIO AMBIGUO: que rutear desde el texto se GANE de verdad.
#
# CYCLE 16 ruteaba desde el texto, PERO llegó a una brecha PERFECTA (pureza 1.000) porque cada tipo
# sintético usaba su PROPIO vocabulario único: hasta un control crudo separaba los tipos. El caveat
# honesto: demostró el MECANISMO, no la robustez a paráfrasis / redacción ambigua. CYCLE 17 retira ese
# caveat haciendo el ruteo desde texto genuinamente DURO:
#   1) MUCHAS formas de superficie por tipo (varias plantillas, sinónimos, cláusulas reordenadas), todas
#      con la MISMA answer y MISMO type label (el label se usa SOLO para evaluar held-out, nunca para rutear).
#   2) un knob `ambiguity` en [0,1] que (a) hace que los tipos COMPARTAN vocabulario (mismas palabras de
#      "presupuesto"/"plata"/"$" aparecen en varios tipos) y (b) inyecta palabras DISTRACTORAS, para que una
#      firma de keywords ingenua CONFUNDA tipos. A más ambigüedad, más solapamiento + más distractores.
#
# Es OPT-IN total: gen_problems/gen_graded/gen_composed NO cambian (CYCLE 12–16 corren byte-a-byte iguales).
# Solo paraphrasea los 4 tipos base (los que una cadena de un paso resuelve limpio), reusando los MISMOS
# params/answers que _split_bill/_cheaper_per_kg/_trips_within_budget/_arrive_on_time.
# ============================================================================

# sinónimos por "ranura" semántica: variar la superficie SIN cambiar el significado ni la answer.
_SYN = {
    "amigos": ["amigos", "compañeros", "colegas", "personas", "comensales"],
    "cuenta": ["la cuenta", "el total a pagar", "la factura", "lo que salió", "el ticket"],
    "propina": ["propina", "de yapa para el mozo", "extra para el servicio", "de tip"],
    "cada_uno": ["cada uno", "por cabeza", "por persona", "cada comensal"],
    "paquete": ["paquete", "presentación", "envase", "bolsa"],
    "conviene": ["conviene", "rinde más", "es mejor compra", "te sale mejor por kilo"],
    "tenes": ["tenés", "disponés de", "contás con", "tu presupuesto es de"],
    "viaje": ["viaje", "boleto", "pasaje", "trayecto"],
    "tarjeta": ["la tarjeta", "la SUBE", "la tarjeta de transporte", "el abono"],
    "enteros": ["enteros", "completos", "que entran"],
    "recorrer": ["recorrer", "manejar", "viajar", "cubrir"],
    "a_tiempo": ["a tiempo", "sin llegar tarde", "antes del plazo", "puntual"],
}

# pozo de palabras DISTRACTORAS compartidas entre tipos: cuando se inyectan, las firmas de keywords se
# pisan (p.ej. "presupuesto"/"plata"/"oferta" aparecen en tipos donde no son la pista real). El verificador
# y la answer NO cambian: el distractor va en una cláusula de relleno (contexto cotidiano irrelevante).
_DISTRACTORS = [
    "ojo con el presupuesto", "salí de oferta", "ese día estaba la promo",
    "tené en cuenta la plata", "compará bien por kilo", "no llegues tarde",
    "fijate los descuentos", "la tarjeta a veces falla", "andá rápido",
    "calculá el ahorro", "es para varios amigos", "mirá el peso en gramos",
]


def _syn(rng, slot):
    return rng.choice(_SYN[slot])


def _maybe_distract(rng, ambiguity):
    """Con probabilidad proporcional a la ambigüedad, devuelve 0..2 cláusulas distractoras (relleno)."""
    if rng.random() >= ambiguity:
        return ""
    k = 1 if rng.random() > ambiguity else 2     # más ambigüedad -> a veces dos distractores
    picks = [rng.choice(_DISTRACTORS) for _ in range(k)]
    return " (" + "; ".join(picks) + ")"


def _para_split_bill(rng, ambiguity):
    # reusa la lógica/answer de _split_bill, pero con MUCHAS plantillas + sinónimos + distractores.
    base = _split_bill(rng); p = base["params"]
    n, total, tip = p["n"], p["total"], int(p["tip"] * 100)
    amigos, cuenta, propina, cada = _syn(rng, "amigos"), _syn(rng, "cuenta"), _syn(rng, "propina"), _syn(rng, "cada_uno")
    tmpls = [
        f"Salimos {n} {amigos}; {cuenta} fue ${total:.2f} y sumamos {tip}% de {propina}. ¿Cuánto pone {cada}?",
        f"Entre {n} {amigos} hay que dividir ${total:.2f}, más {tip}% {propina}. ¿{cada.capitalize()} cuánto abona?",
        f"{cuenta.capitalize()} dio ${total:.2f}, le agregamos {tip}% {propina} y lo partimos entre {n}. ¿Cuánto sale {cada}?",
        f"Con {tip}% {propina} sobre ${total:.2f}, repartido en {n} {amigos}, ¿qué monto va {cada}?",
    ]
    base["text"] = rng.choice(tmpls) + _maybe_distract(rng, ambiguity)
    return base


def _para_cheaper_per_kg(rng, ambiguity):
    base = _cheaper_per_kg(rng); p = base["params"]
    pa, ga, pb, gb = p["pa"], p["ga"], p["pb"], p["gb"]
    paq, conv = _syn(rng, "paquete"), _syn(rng, "conviene")
    tmpls = [
        f"Un {paq} sale ${pa:.2f} por {ga} g y otro ${pb:.2f} por {gb} g. ¿Cuál {conv}? (0=A, 1=B)",
        f"Comparando: A trae {ga} g a ${pa:.2f}, B trae {gb} g a ${pb:.2f}. ¿Qué {conv}? (0=A, 1=B)",
        f"¿Me llevo el de {ga} g a ${pa:.2f} o el de {gb} g a ${pb:.2f}? Decime cuál {conv} (0=A, 1=B).",
        f"Opción A: {ga} g cuestan ${pa:.2f}. Opción B: {gb} g cuestan ${pb:.2f}. ¿Cuál {conv}? (0=A, 1=B)",
    ]
    base["text"] = rng.choice(tmpls) + _maybe_distract(rng, ambiguity)
    return base


def _para_trips_within_budget(rng, ambiguity):
    base = _trips_within_budget(rng); p = base["params"]
    b, f, c = p["b"], p["f"], p["c"]
    tenes, tarjeta, viaje, ent = _syn(rng, "tenes"), _syn(rng, "tarjeta"), _syn(rng, "viaje"), _syn(rng, "enteros")
    tmpls = [
        f"{tenes.capitalize()} ${b:.2f}. Sacar {tarjeta} cuesta ${f:.2f} una vez y cada {viaje} ${c:.2f}. ¿Cuántos {viaje}s {ent}?",
        f"Con ${b:.2f} en el bolsillo, {tarjeta} sale ${f:.2f} fija y el {viaje} ${c:.2f}. ¿Cuántos {viaje}s {ent} hacés?",
        f"Pagás ${f:.2f} por {tarjeta} y después ${c:.2f} por {viaje}. Si {tenes} ${b:.2f}, ¿cuántos {viaje}s {ent}?",
        f"{tarjeta.capitalize()} ${f:.2f} de entrada, ${c:.2f} el {viaje}, {tenes} ${b:.2f}. ¿Cantidad de {viaje}s {ent}?",
    ]
    base["text"] = rng.choice(tmpls) + _maybe_distract(rng, ambiguity)
    return base


def _para_arrive_on_time(rng, ambiguity):
    base = _arrive_on_time(rng); p = base["params"]
    dist, speed, h = p["dist"], p["speed"], p["h"]
    rec, atiempo = _syn(rng, "recorrer"), _syn(rng, "a_tiempo")
    tmpls = [
        f"Tenés que {rec} {dist:.1f} km a {speed:.1f} km/h y llegar {atiempo} en {h:.1f} horas. ¿Llegás? (1=sí, 0=no)",
        f"Son {dist:.1f} km, vas a {speed:.1f} km/h y el plazo es {h:.1f} horas. ¿Llegás {atiempo}? (1=sí, 0=no)",
        f"A {speed:.1f} km/h, ¿alcanzás a {rec} {dist:.1f} km en {h:.1f} horas y quedar {atiempo}? (1=sí, 0=no)",
        f"El viaje es de {dist:.1f} km en {h:.1f} horas como mucho; tu velocidad {speed:.1f} km/h. ¿{atiempo.capitalize()}? (1=sí, 0=no)",
    ]
    base["text"] = rng.choice(tmpls) + _maybe_distract(rng, ambiguity)
    return base


# los 4 tipos base que SÍ paraphrasea CYCLE 17 (los que una cadena de un paso resuelve limpio).
_PARA_GENS = {
    "split_bill": _para_split_bill,
    "cheaper_per_kg": _para_cheaper_per_kg,
    "trips_within_budget": _para_trips_within_budget,
    "arrive_on_time": _para_arrive_on_time,
}


def gen_paraphrased(n, seed, ambiguity=0.0, types=None):
    """
    CYCLE 17 — genera n problemas PARAFRASEADOS balanceados entre los 4 tipos base. Cada problema:
      - usa los MISMOS params/answer/type que el generador original (verdad-base intacta),
      - pero su TEXTO se redacta con una de varias plantillas + sinónimos (muchas formas de superficie),
      - y según `ambiguity` (en [0,1]) inyecta cláusulas DISTRACTORAS con vocabulario COMPARTIDO entre
        tipos (presupuesto/oferta/plata/kilo...) para que una firma de keywords ingenua los CONFUNDA.
    El `type` queda en el dict SOLO para evaluación held-out (pureza/ceiling): los routers de texto jamás
    lo leen. Determinista por `seed`. APARTE de gen_problems -> CYCLE 12–16 corren idénticos.
    """
    use = list(types) if types is not None else list(_PARA_GENS.keys())
    rng = Random(seed)
    out = []
    for i in range(n):
        t = use[i % len(use)]
        out.append(_PARA_GENS[t](rng, ambiguity))
    rng.shuffle(out)
    return out


def is_correct(problem, predicted, tol=1e-6):
    """Verificador de verdad-base: float con tolerancia; las decisiones 0/1 son exactas."""
    if predicted is None:
        return False
    ans = problem["answer"]
    # decisiones binarias y conteos ENTEROS: exacto (afford_packs/stock_then_days son floor -> enteros)
    if problem["type"] in ("cheaper_per_kg", "arrive_on_time", "discount_better",
                           "split_then_check", "afford_packs", "stock_then_days"):
        return float(predicted) == float(ans)
    return abs(float(predicted) - float(ans)) <= tol
