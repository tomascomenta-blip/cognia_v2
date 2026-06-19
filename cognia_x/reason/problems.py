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

_GENS = {
    "split_bill": _split_bill,
    "cheaper_per_kg": _cheaper_per_kg,
    "trips_within_budget": _trips_within_budget,
    "arrive_on_time": _arrive_on_time,
    "discount_better": _discount_better,
}


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
    if problem["type"] in ("cheaper_per_kg", "arrive_on_time", "discount_better"):
        return float(predicted) == float(ans)   # decision binaria: exacto
    return abs(float(predicted) - float(ans)) <= tol
