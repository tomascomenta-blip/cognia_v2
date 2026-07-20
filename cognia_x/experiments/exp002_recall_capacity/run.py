"""
exp002 - Capacidad de recall asociativo: el contrapeso a exp001 (Cognia-X).

exp001 mostro que el mezclador lineal es ~70x mas barato que la atencion full. Pero,
QUE PIERDE? Esta es la pregunta honesta que decide si "reemplazar atencion" es viable.

Hipotesis H-MEZ-3: la capacidad de recall asociativo exacto de un mezclador de ESTADO
ACOTADO (atencion lineal, estado d x d) esta limitada por su tamano de estado (~d), mientras
que la atencion full tiene capacidad ~L (puede direccionar cualquier posicion). Prediccion
falsable: la accuracy de la atencion lineal caera por debajo de 0.9 alrededor de N ~ d pares,
y la capacidad (max N con acc>=0.9) crecera ~proporcional a d; la atencion full se mantendra
alta para todo N probado. Se refutaria si el lineal no se degradara con N, o si su capacidad
no escalara con d.

Tarea (training-free, sin hacks de temperatura): se almacenan N pares (k_j -> v_j) con k_j, v_j
~ N(0, I_d) (componentes de varianza unidad, el regimen estandar de la atencion escalada). Se
consulta cada k_i y se cuenta acierto si el valor recuperado tiene como vecino mas cercano
(maximo coseno entre los N valores almacenados) al v_i correcto.

  - full:   r_i = softmax(K @ k_i / sqrt(d)) @ V      (atencion escalada estandar; capacidad ~ L)
  - linear: S = sum_j k_j v_j^T  (d x d);  r_i = k_i^T S   (estado acotado; capacidad ~ d)

Reproducible: semilla fija, TRIALS promedios. Salida -> results/results.json + results/results.md
Correr: .\\venv312\\Scripts\\python.exe cognia_x\\experiments\\exp002_recall_capacity\\run.py
"""
import json
import os

import numpy as np

SEED = 7
DS = [32, 64, 128]
NS = [8, 16, 32, 64, 128, 256, 512]
TRIALS = 3
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def softmax(x):
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()


def nn_hit(rec, V, i):
    """Acierto si v_i es el vecino mas cercano (coseno) del vector recuperado."""
    rn = rec / (np.linalg.norm(rec) + 1e-12)
    Vn = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-12)
    return int(np.argmax(Vn @ rn) == i)


def acc_full(K, V):
    N, d = K.shape
    hits = 0
    for i in range(N):
        w = softmax(K @ K[i] / np.sqrt(d))   # atencion escalada estandar
        hits += nn_hit(w @ V, V, i)
    return hits / N


def acc_linear(K, V):
    N, d = K.shape
    S = K.T @ V                              # estado d x d = sum_j k_j v_j^T
    hits = 0
    for i in range(N):
        hits += nn_hit(K[i] @ S, V, i)       # r_i = k_i^T S
    return hits / N


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for d in DS:
        for N in NS:
            af = al = 0.0
            for _ in range(TRIALS):
                K = rng.standard_normal((N, d))
                V = rng.standard_normal((N, d))
                af += acc_full(K, V)
                al += acc_linear(K, V)
            rows.append({"d": d, "N": N,
                         "acc_full": af / TRIALS, "acc_linear": al / TRIALS})

    # capacidad: max N con acc_linear >= 0.9, por d
    cap = {}
    for d in DS:
        good = [r["N"] for r in rows if r["d"] == d and r["acc_linear"] >= 0.9]
        cap[d] = max(good) if good else 0

    result = {
        "experiment": "exp002_recall_capacity",
        "config": {"seed": SEED, "ds": DS, "ns": NS, "trials": TRIALS,
                   "numpy": np.__version__},
        "rows": rows,
        "linear_capacity_per_d_acc>=0.9": cap,
        "note": "atencion full usa escalado estandar 1/sqrt(d); ningun hack de temperatura.",
    }
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    lines = ["# exp002 - resultados (capacidad de recall asociativo)", ""]
    lines.append(f"- numpy {np.__version__} | trials={TRIALS} | seed={SEED}")
    lines.append(f"- **Capacidad de la atencion lineal (max N con acc>=0.9):** {cap}")
    lines.append("- Atencion full = escalado estandar 1/sqrt(d), sin trucos de temperatura.")
    lines.append("")
    lines.append("| d | N | acc_full | acc_linear |")
    lines.append("|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r['d']} | {r['N']} | {r['acc_full']:.3f} | {r['acc_linear']:.3f} |")
    lines.append("")
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("Capacidad lineal (max N con acc>=0.9) por d:", cap)
    for r in rows:
        print(f"d={r['d']:4d} N={r['N']:4d} | full {r['acc_full']:.3f} | linear {r['acc_linear']:.3f}")
    print("\nOK ->", os.path.join(OUT, "results.md"))


if __name__ == "__main__":
    main()
