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


_GENS = {
    "split_bill": _split_bill,
    "cheaper_per_kg": _cheaper_per_kg,
    "trips_within_budget": _trips_within_budget,
    "arrive_on_time": _arrive_on_time,
}


def gen_problems(n, seed):
    """Genera n problemas balanceados entre los 4 tipos. Determinista por `seed` (Random local)."""
    rng = Random(seed)
    out = []
    for i in range(n):
        t = TYPES[i % len(TYPES)]
        out.append(_GENS[t](rng))
    rng.shuffle(out)
    return out


def is_correct(problem, predicted, tol=1e-6):
    """Verificador de verdad-base: float con tolerancia; las decisiones 0/1 son exactas."""
    if predicted is None:
        return False
    ans = problem["answer"]
    if problem["type"] in ("cheaper_per_kg", "arrive_on_time"):
        return float(predicted) == float(ans)   # decision binaria: exacto
    return abs(float(predicted) - float(ans)) <= tol
