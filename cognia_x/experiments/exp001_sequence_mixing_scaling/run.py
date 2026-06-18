"""
exp001 - Escalado empirico del coste de mezcla de secuencia en CPU (Cognia-X).

Pregunta obligatoria del meta-prompt: "Que parte consume mas recursos?"
Hipotesis bajo prueba (H-MEZ-1): la atencion full (O(L^2)) es el cuello de botella
de escalado en CPU frente a un mezclador de tiempo lineal (O(L)); existe un L de cruce
a partir del cual el mezclador lineal es estrictamente mas barato en tiempo, y su memoria
del tensor intermedio dominante crece O(L) en vez de O(L^2).

Mezcladores (mismo d, batch=1, float32, version global no-causal para A y B):
  (A) attn_full:   scores=Q@K.T/sqrt(d); softmax; out=P@V      O(L^2 d) tiempo,  O(L^2) memoria (matriz scores)
  (B) attn_linear: feature map elu+1, out=phi(Q)@(phi(K).T@V)/Z O(L d^2) tiempo,  O(d^2) memoria (matriz KV)
  (C) ssm_scan:    recurrencia diagonal h_t=a*h_{t-1}+b*x_t      O(L d) tiempo (bucle py), O(d) estado
       NOTA: (C) carga el sobrecoste del bucle Python; un Mamba real usa un scan fusionado.
       Se mide igual para exponer la trampa del "factor constante" (asintotica buena, constante mala).

Memoria: se reporta el tamano ANALITICO del tensor intermedio dominante (numpy no pasa por
tracemalloc de forma fiable), que es exacto y defendible.

Metrica de tiempo: wall-clock medio sobre R reps tras 1 warmup (time.perf_counter).
Reproducible: semilla fija. Salida -> results/results.json + results/results.md
Correr: .\\venv312\\Scripts\\python.exe cognia_x\\experiments\\exp001_sequence_mixing_scaling\\run.py
"""
import json
import os
import time

import numpy as np

SEED = 1234
D = 64
R = 3
LENGTHS = [128, 256, 512, 1024, 2048, 4096]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def softmax(x, axis=-1):
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


def attn_full(Q, K, V):
    d = Q.shape[-1]
    scores = (Q @ K.T) / np.sqrt(d)          # (L, L)  <- tensor cuadratico
    P = softmax(scores, axis=-1)
    return P @ V


def attn_linear(Q, K, V):
    def phi(x):
        return np.where(x > 0, x + 1.0, np.exp(np.minimum(x, 0.0)))  # elu+1, estable
    Qp = phi(Q)
    Kp = phi(K)
    KV = Kp.T @ V                             # (d, d)  <- tensor de tamano fijo en L
    Z = Kp.sum(axis=0)                        # (d,)
    num = Qp @ KV                             # (L, d)
    den = (Qp @ Z)[:, None] + 1e-6
    return num / den


def ssm_scan(X, a, b, c):
    L, d = X.shape
    h = np.zeros(d, dtype=X.dtype)
    Y = np.empty((L, d), dtype=X.dtype)
    for t in range(L):
        h = a * h + b * X[t]
        Y[t] = c * h
    return Y


def bench_time(fn, args, reps=R):
    fn(*args)  # warmup (incluye costes de primera asignacion / cache)
    t0 = time.perf_counter()
    for _ in range(reps):
        fn(*args)
    return (time.perf_counter() - t0) / reps


def mb(nbytes):
    return nbytes / (1024 * 1024)


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for L in LENGTHS:
        Q = rng.standard_normal((L, D)).astype(np.float32)
        K = rng.standard_normal((L, D)).astype(np.float32)
        V = rng.standard_normal((L, D)).astype(np.float32)
        a = rng.uniform(0.90, 0.999, size=D).astype(np.float32)
        b = rng.standard_normal(D).astype(np.float32)
        c = rng.standard_normal(D).astype(np.float32)

        t_full = bench_time(attn_full, (Q, K, V))
        t_lin = bench_time(attn_linear, (Q, K, V))
        t_ssm = bench_time(ssm_scan, (V, a, b, c))

        # memoria analitica del tensor intermedio dominante (float32 = 4 bytes)
        m_full = mb(L * L * 4)          # matriz de scores
        m_lin = mb(D * D * 4)           # matriz KV (independiente de L)
        m_ssm = mb(D * 4)               # estado h

        rows.append({
            "L": L,
            "attn_full_s": t_full, "attn_full_mem_mb": m_full,
            "attn_linear_s": t_lin, "attn_linear_mem_mb": m_lin,
            "ssm_scan_s": t_ssm, "ssm_scan_mem_mb": m_ssm,
            "speedup_lin_vs_full": (t_full / t_lin) if t_lin else None,
            "mem_ratio_full_vs_lin": (m_full / m_lin) if m_lin else None,
        })
        print(f"L={L:5d} | full {t_full*1e3:8.2f} ms / {m_full:8.2f} MB"
              f" | linear {t_lin*1e3:8.2f} ms / {m_lin:7.4f} MB"
              f" | ssm-loop {t_ssm*1e3:8.2f} ms | lin x{t_full/t_lin:6.1f} | mem x{m_full/m_lin:8.0f}")

    crossover_time = next((r["L"] for r in rows if r["attn_linear_s"] < r["attn_full_s"]), None)

    result = {
        "experiment": "exp001_sequence_mixing_scaling",
        "config": {"seed": SEED, "d": D, "reps": R, "lengths": LENGTHS,
                   "numpy": np.__version__, "cpu_count": os.cpu_count(), "dtype": "float32"},
        "rows": rows,
        "crossover_L_linear_beats_full_time": crossover_time,
    }
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    lines = ["# exp001 - resultados (escalado de mezcla de secuencia en CPU)", ""]
    lines.append(f"- numpy {np.__version__} | d={D} | reps={R} | seed={SEED} | "
                 f"cpu_count={os.cpu_count()} | dtype=float32")
    lines.append(f"- **Cruce en tiempo (linear < full):** L = {crossover_time}")
    lines.append("- Memoria = tamano analitico del tensor intermedio dominante (scores LxL vs KV dxd).")
    lines.append("")
    lines.append("| L | full (ms) | full mem (MB) | linear (ms) | linear mem (MB) | ssm-loop (ms) | "
                 "speedup lin/full | mem full/lin |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r['L']} | {r['attn_full_s']*1e3:.2f} | {r['attn_full_mem_mb']:.2f} | "
                     f"{r['attn_linear_s']*1e3:.2f} | {r['attn_linear_mem_mb']:.4f} | "
                     f"{r['ssm_scan_s']*1e3:.2f} | {r['speedup_lin_vs_full']:.1f} | "
                     f"{r['mem_ratio_full_vs_lin']:.0f} |")
    lines.append("")
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\nOK ->", os.path.join(OUT, "results.md"))


if __name__ == "__main__":
    main()
