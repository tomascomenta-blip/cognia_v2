"""
exp003 (=E3) - El FedAvg ingenuo de adapters LoRA es matematicamente INEXACTO.

Hipotesis H-CF-2 (ciclo-1): promediar A y B por separado != promediar las delta-W reconstruidas.
    avg_k(B_k) @ avg_k(A_k)  !=  avg_k(B_k @ A_k)
El error crece con la heterogeneidad de clientes y con el numero de clientes. Impacto directo:
coordinator/federated_store.py de Cognia agrega k_A,k_B,v_A,v_B linealmente por separado (Pass 3)
= exactamente este patron inexacto. La afirmacion no depende de ningun paper: es algebra.

Demostracion (numpy puro, sin entrenar, deterministica):
  - K clientes, cada uno con adapter LoRA delta_k = B_k @ A_k (rango r).
  - Exacto:  Delta_exact = mean_k(B_k @ A_k)            (rango <= K*r)
  - Ingenuo: Delta_naive = mean_k(B_k) @ mean_k(A_k)    (rango <= r)
  - Error relativo Frobenius = ||Delta_naive - Delta_exact||_F / ||Delta_exact||_F
Sanity check: con heterogeneidad 0 (clientes identicos) el error debe ser ~0.
Hallazgo estructural extra: el ingenuo colapsa el adapter agregado a rango r, tirando la
diversidad de los K clientes (rango efectivo <= r vs <= K*r del exacto).

Salida -> results/results.json + results/results.md
Correr: .\\venv312\\Scripts\\python.exe cognia_x\\experiments\\exp003_fedavg_lora_inexactness\\run.py
"""
import json
import os

import numpy as np

SEED = 11
M = N = 256
R = 8            # = _RANK_MAX de federated_store.py de Cognia
TRIALS = 20
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def make_clients(rng, K, r, hetero):
    """Adapters = direccion compartida A0/B0 + componente heterogenea escalada por `hetero`."""
    A0 = rng.standard_normal((r, N))
    B0 = rng.standard_normal((M, r))
    A = [A0 + hetero * rng.standard_normal((r, N)) for _ in range(K)]
    B = [B0 + hetero * rng.standard_normal((M, r)) for _ in range(K)]
    return A, B


def eff_rank(X):
    s = np.linalg.svd(X, compute_uv=False)
    return int((s > 1e-6 * s[0]).sum())


def measure(A, B):
    K = len(A)
    deltas = [B[k] @ A[k] for k in range(K)]
    exact = sum(deltas) / K
    naive = (sum(B) / K) @ (sum(A) / K)
    rel = float(np.linalg.norm(naive - exact) / (np.linalg.norm(exact) + 1e-12))
    return rel, eff_rank(exact), eff_rank(naive)


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUT, exist_ok=True)

    # Barrido 1: error vs heterogeneidad (K=4 fijo)
    HET = [0.0, 0.1, 0.25, 0.5, 1.0, 2.0]
    by_het = []
    for h in HET:
        rels, re_, rn_ = [], 0, 0
        for _ in range(TRIALS):
            A, B = make_clients(rng, 4, R, h)
            rel, ee, en = measure(A, B)
            rels.append(rel); re_ += ee; rn_ += en
        by_het.append({"hetero": h, "rel_error": float(np.mean(rels)),
                       "rank_exact": re_ / TRIALS, "rank_naive": rn_ / TRIALS})

    # Barrido 2: error vs numero de clientes (hetero=0.5 fijo)
    KS = [2, 3, 4, 8, 16]
    by_k = []
    for K in KS:
        rels = []
        for _ in range(TRIALS):
            A, B = make_clients(rng, K, R, 0.5)
            rel, _, _ = measure(A, B)
            rels.append(rel)
        by_k.append({"K": K, "rel_error": float(np.mean(rels))})

    result = {
        "experiment": "exp003_fedavg_lora_inexactness",
        "config": {"seed": SEED, "m": M, "n": N, "r": R, "trials": TRIALS},
        "error_vs_heterogeneity_K4": by_het,
        "error_vs_clients_h0.5": by_k,
        "sanity_zero_hetero_rel_error": by_het[0]["rel_error"],
    }
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    lines = ["# exp003 - resultados (inexactitud del FedAvg de LoRA)", ""]
    lines.append(f"- numpy {np.__version__} | m=n={M} | r={R} (=_RANK_MAX de Cognia) | "
                 f"trials={TRIALS} | seed={SEED}")
    lines.append(f"- **Sanity (heterogeneidad 0 -> error 0):** rel_error = {by_het[0]['rel_error']:.2e}")
    lines.append("")
    lines.append("## Error relativo vs heterogeneidad de clientes (K=4)")
    lines.append("| heterogeneidad | error relativo Frobenius | rango efectivo exacto | rango efectivo ingenuo |")
    lines.append("|---|---|---|---|")
    for r in by_het:
        lines.append(f"| {r['hetero']} | {r['rel_error']:.4f} | {r['rank_exact']:.0f} | {r['rank_naive']:.0f} |")
    lines.append("")
    lines.append("## Error relativo vs numero de clientes (heterogeneidad=0.5)")
    lines.append("| K clientes | error relativo Frobenius |")
    lines.append("|---|---|")
    for r in by_k:
        lines.append(f"| {r['K']} | {r['rel_error']:.4f} |")
    lines.append("")
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Sanity (hetero=0): rel_error = {by_het[0]['rel_error']:.2e}  (debe ser ~0)")
    for r in by_het:
        print(f"hetero={r['hetero']:4} | rel_error={r['rel_error']:.4f} | "
              f"rank exact={r['rank_exact']:.0f} naive={r['rank_naive']:.0f}")
    print("--- vs K (hetero=0.5) ---")
    for r in by_k:
        print(f"K={r['K']:3d} | rel_error={r['rel_error']:.4f}")
    print("\nOK ->", os.path.join(OUT, "results.md"))


if __name__ == "__main__":
    main()
