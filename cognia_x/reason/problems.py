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
