"""
exp005 - Frontera coste<->recall del backbone hibrido (Cognia-X). Mide el EJE COSTE.

PREGUNTA: Un stack mayormente de capas lineales (estado fijo) + pocas capas de atencion
full, ¿se acerca al COSTE por token del lineal puro mientras conserva el RECALL del full
puro? Aqui medimos solo el coste real por token de UN paso de decode; el recall ya esta
medido en exp002 (la atencion full da recall ~ilimitado en N, la lineal queda acotada por
su estado d^2). Juntos = la frontera H-MEZ-4.

HIPOTESIS H-MEZ-4: con k pequeno (p.ej. 3 de 24 capas full) el stack hibrido retiene solo
una fraccion pequena del coste de pure-full a L grande, porque el coste de las capas full
crece con L (leen el KV-cache (L,d)) mientras el de las lineales es constante en L (estado
fijo d^2). Prediccion falsable: a L=8192, un hibrido k=3 deberia costar <<100% del pure-full
(idealmente ~k/24 + constante), y el lineal puro (k=0) deberia ser casi plano en L mientras
el full puro (k=24) crece ~lineal en L. Se refutaria si el hibrido k pequeno no ahorrara
nada, o si el lineal puro creciera con L.

METODO (numpy puro, determinista, sin torch/numba):
  Stack de m=24 capas, k full y (m-k) lineales, ancho d=128, contexto L.
  - Capa FULL (decode step), KV-cache K,V (L,d) pre-construido, query q (d,):
      scores = (K @ q)/sqrt(d)  ->  p = softmax(scores)  ->  out = p @ V
    Coste O(L*d): lee el KV-cache, crece con L.
  - Capa LINEAL (decode step), estado S (d,d) y z (d,) pre-construidos, query q (d,):
      phi(x) = where(x>0, x+1, exp(min(x,0)))      (feature map positivo, estable)
      out = (phi(q) @ S) / (phi(q) @ z + 1e-6)
    Coste O(d^2): estado fijo, constante en L. (No actualizamos S/z: para el coste de
    lectura dominante del decode da igual; se mantiene simple, como pide la spec.)
  El token se procesa SECUENCIALMENTE por las m capas encadenando la salida de cada capa
  como query de la siguiente (out ya es (d,), no hace falta proyectar). El orden de las
  capas no afecta el coste total (suma de costes), asi que ponemos las k full primero.

VALIDEZ DE LA MEDICION:
  Todos los KV-caches (k de ellos, (L,d)) y estados lineales (m-k de ellos, S (d,d) y z (d,))
  se pre-construyen UNA VEZ fuera del bucle cronometrado. El bucle cronometrado solo ejecuta
  los matmuls del paso de decode; nunca asigna memoria grande. perf_counter, R repeticiones
  tras 1 warmup, se reporta ms/token medio.

BARRIDOS: k in {0,1,3,6,12,24} x L in {512,2048,8192}.
  Para cada (k,L): ms_por_token y pct_of_pure_full = ms(k,L)/ms(24,L)*100.

Correr: .\\venv312\\Scripts\\python.exe cognia_x\\experiments\\exp005_hybrid_decode_frontier\\run.py
"""
import json
import os
import time

import numpy as np

SEED = 7
M = 24                      # capas totales del stack
D = 128                    # ancho
KS = [0, 1, 3, 6, 12, 24]  # nº de capas full (0=lineal puro, 24=full puro)
LS = [512, 2048, 8192]     # longitudes de contexto
R = 80                     # repeticiones cronometradas (>=50)
WARMUP = 1
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def softmax(x):
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()


def phi(x):
    """Feature map positivo de la atencion lineal (estable: lineal arriba, exp abajo)."""
    return np.where(x > 0, x + 1.0, np.exp(np.minimum(x, 0.0)))


def full_step(K, V, q, d_sqrt):
    """Paso de decode de una capa de atencion full. Lee KV-cache (L,d). O(L*d)."""
    p = softmax((K @ q) / d_sqrt)   # (L,)
    return p @ V                    # (d,)


def lin_step(S, z, q):
    """Paso de decode de una capa de atencion lineal. Estado fijo (d,d). O(d^2)."""
    f = phi(q)                      # (d,)
    return (f @ S) / (f @ z + 1e-6) # (d,)


def build_stack(rng, k, L, d):
    """Pre-construye TODOS los KV-caches y estados lineales FUERA del bucle cronometrado.

    Devuelve la lista de capas en orden: k full primero, luego (M-k) lineales.
    """
    layers = []
    for _ in range(k):
        K = rng.standard_normal((L, d))
        V = rng.standard_normal((L, d))
        layers.append(("full", K, V))
    for _ in range(M - k):
        S = rng.standard_normal((d, d))
        z = rng.standard_normal((d,))
        layers.append(("lin", S, z))
    return layers


def time_stack(layers, q0, d_sqrt):
    """Cronometra R pasos de decode del stack completo (1 token a traves de M capas).

    Solo matmuls del paso de decode; sin asignacion de memoria grande dentro del bucle.
    Devuelve ms/token medio.
    """
    # warmup
    for _ in range(WARMUP):
        q = q0
        for layer in layers:
            if layer[0] == "full":
                q = full_step(layer[1], layer[2], q, d_sqrt)
            else:
                q = lin_step(layer[1], layer[2], q)

    t0 = time.perf_counter()
    for _ in range(R):
        q = q0
        for layer in layers:
            if layer[0] == "full":
                q = full_step(layer[1], layer[2], q, d_sqrt)
            else:
                q = lin_step(layer[1], layer[2], q)
    t1 = time.perf_counter()
    return (t1 - t0) / R * 1000.0   # ms/token


def main():
    d_sqrt = np.sqrt(D)
    os.makedirs(OUT, exist_ok=True)

    rows = []          # filas planas {k, L, ms_per_token, pct_of_pure_full}
    ms = {}            # ms[(k, L)]
    for L in LS:
        for k in KS:
            rng = np.random.default_rng(SEED)         # determinista por (k,L)
            q0 = rng.standard_normal((D,))
            layers = build_stack(rng, k, L, D)        # FUERA del cronometro
            ms[(k, L)] = time_stack(layers, q0, d_sqrt)

    for L in LS:
        pure_full = ms[(24, L)]
        for k in KS:
            rows.append({
                "k": k, "L": L,
                "ms_per_token": ms[(k, L)],
                "pct_of_pure_full": ms[(k, L)] / pure_full * 100.0,
            })

    result = {
        "experiment": "exp005_hybrid_decode_frontier",
        "config": {"seed": SEED, "m": M, "d": D, "ks": KS, "ls": LS,
                   "reps": R, "warmup": WARMUP, "numpy": np.__version__},
        "rows": rows,
        "note": ("Mide el EJE COSTE de la frontera H-MEZ-4. El recall se toma de exp002 "
                 "(full ~ilimitado en N, lineal acotado por estado d^2). Capa full O(L*d) "
                 "lee KV-cache (crece con L); capa lineal O(d^2) estado fijo (constante en L)."),
    }
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    # results.md
    lines = ["# exp005 - frontera coste<->recall del backbone hibrido (eje COSTE)", ""]
    lines.append(f"- numpy {np.__version__} | m={M} capas | d={D} | reps={R} | seed={SEED}")
    lines.append("- Capa FULL: O(L*d), lee KV-cache (L,d) -> crece con L.")
    lines.append("- Capa LINEAL: O(d^2), estado fijo (d,d) -> constante en L.")
    lines.append("- **El recall se toma de exp002** (full ~ilimitado en N; lineal acotado por d^2).")
    lines.append("")
    lines.append("## ms/token por (k, L)")
    lines.append("")
    header = "| k (full/24) | " + " | ".join(f"L={L}" for L in LS) + " |"
    sep = "|" + "---|" * (len(LS) + 1)
    lines.append(header)
    lines.append(sep)
    for k in KS:
        cells = " | ".join(f"{ms[(k, L)]:.4f}" for L in LS)
        lines.append(f"| {k} | {cells} |")
    lines.append("")
    lines.append("## pct_of_pure_full = ms(k,L)/ms(24,L)*100")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for k in KS:
        cells = " | ".join(f"{ms[(k, L)] / ms[(24, L)] * 100:.1f}%" for L in LS)
        lines.append(f"| {k} | {cells} |")
    lines.append("")
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # consola
    print(f"exp005 | numpy {np.__version__} | m={M} d={D} reps={R} seed={SEED}")
    print("ms/token por (k, L):")
    print("  k  | " + " | ".join(f"L={L:>5d}" for L in LS))
    print("  ---+-" + "-+-".join("-" * 9 for _ in LS))
    for k in KS:
        cells = " | ".join(f"{ms[(k, L)]:9.4f}" for L in LS)
        print(f"  {k:2d} | {cells}")
    print("\npct_of_pure_full = ms(k,L)/ms(24,L)*100:")
    print("  k  | " + " | ".join(f"L={L:>5d}" for L in LS))
    print("  ---+-" + "-+-".join("-" * 9 for _ in LS))
    for k in KS:
        cells = " | ".join(f"{ms[(k, L)] / ms[(24, L)] * 100:8.1f}%" for L in LS)
        print(f"  {k:2d} | {cells}")
    print("\nOK ->", os.path.join(OUT, "results.md"))


if __name__ == "__main__":
    main()
