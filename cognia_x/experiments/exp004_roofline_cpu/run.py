"""
exp004 - Roofline de CPU para el decode autoregresivo batch=1 (Cognia-X).

Pregunta: el decode batch=1 en CPU, cuya operacion nucleo es un GEMV (W @ x, no un GEMM),
esta limitado por ancho de banda de memoria o por computo?
Hipotesis bajo prueba (H-BW-1 / A-008): el decode autoregresivo batch=1 es memory-bandwidth-bound
(intensidad aritmetica baja: cada peso de W se lee 1 vez y participa en 2 FLOPs -> ~2 FLOP/elem,
es decir 0.25-0.5 FLOP/byte), por lo que:
  (a) reducir bytes/peso (float64 -> float32) mejora el throughput cuasi-proporcionalmente (~2x), y
  (b) anadir hilos satura rapido (en este 2c/4t, 1->3 sublineal y el 4o hilo logico compite por banda).

Operacion medida: y = W @ x, con W (n, n) y x (n,) -> GEMV.
  FLOPs   = 2*n*n                         (un multiply-add por elemento de W)
  bytes   = n*n*bytes_por_elem            (W domina la lectura; x e y son O(n), despreciables)
  intensidad aritmetica = 2 / bytes_por_elem FLOP/byte (0.25 en f64, 0.5 en f32): muy a la
  izquierda del codo del roofline -> regimen memory-bound, GFLOP/s << pico de la CPU.

Metodo: tiempo medio con time.perf_counter sobre >=30 reps tras 1 warmup. numpy puro, sin torch
ni numba. Determinista (np.random.default_rng con semilla fija).

Barrido 1 (eje BYTES/peso): n en {1024,2048,4096} x dtype en {float64, float32}. Se reporta
time_ms, GFLOP/s, GB/s y el speedup f32/f64 por n. Prediccion: f32 ~2x f64, GB/s ~plano al crecer n.

Barrido 2 (eje HILOS): n=4096, float32, hilos de BLAS en {1,2,3,4} via threadpoolctl. Si
threadpoolctl no esta instalado, se mide a hilos por defecto, se anota "threadpoolctl": false y el
nº de hilos que reporta OpenBLAS; NO se falla. Prediccion: speedup 1->3 sublineal, satura/empeora en 4.

Salida -> results/results.json + results/results.md
Correr: .\\venv312\\Scripts\\python.exe cognia_x\\experiments\\exp004_roofline_cpu\\run.py
"""
import json
import os
import time

import numpy as np

SEED = 7
NS = [1024, 2048, 4096]
DTYPES = [("float64", np.float64, 8), ("float32", np.float32, 4)]
REPS = 30
THREAD_COUNTS = [1, 2, 3, 4]
THREADS_N = 4096
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def bench_gemv(W, x, reps=REPS):
    """Tiempo medio (s) de y = W @ x sobre `reps` reps tras 1 warmup."""
    W @ x  # warmup (primera asignacion del buffer de salida + carga a cache)
    t0 = time.perf_counter()
    for _ in range(reps):
        W @ x
    return (time.perf_counter() - t0) / reps


def metrics(n, bytes_per_elem, t_s):
    flops = 2.0 * n * n
    read_bytes = float(n) * n * bytes_per_elem  # W domina; x,y son O(n)
    return {
        "time_ms": t_s * 1e3,
        "gflops": flops / t_s / 1e9,
        "gbps": read_bytes / t_s / 1e9,
    }


def openblas_num_threads():
    """Nº de hilos que OpenBLAS usa por defecto (mejor esfuerzo, sin dependencias extra)."""
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"):
        if os.environ.get(var):
            return int(os.environ[var])
    # OpenBLAS sin variables de entorno usa por defecto el nº de nucleos fisicos/logicos.
    return os.cpu_count()


def run_sweep_bytes(rng):
    """Barrido 1: GEMV variando n y bytes/peso. Devuelve filas + speedup f32 vs f64 por n."""
    rows = []
    times_ms = {}  # (n, dtype_name) -> time_ms, para el speedup
    for n in NS:
        for name, dt, bpe in DTYPES:
            W = rng.standard_normal((n, n)).astype(dt)
            x = rng.standard_normal(n).astype(dt)
            t = bench_gemv(W, x)
            m = metrics(n, bpe, t)
            times_ms[(n, name)] = m["time_ms"]
            rows.append({"n": n, "dtype": name, "bytes_per_elem": bpe, **m})
            print(f"n={n:5d} | {name:8s} | {m['time_ms']:8.3f} ms | "
                  f"{m['gflops']:7.2f} GFLOP/s | {m['gbps']:7.2f} GB/s")
    speedup = {}
    for n in NS:
        t64 = times_ms[(n, "float64")]
        t32 = times_ms[(n, "float32")]
        speedup[str(n)] = (t64 / t32) if t32 else None
    return rows, speedup


def run_sweep_threads(rng):
    """Barrido 2: GEMV n=4096 float32 variando hilos de BLAS. Degrada con elegancia sin threadpoolctl."""
    n = THREADS_N
    W = rng.standard_normal((n, n)).astype(np.float32)
    x = rng.standard_normal(n).astype(np.float32)

    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        # Sin threadpoolctl no se puede variar hilos de BLAS en caliente de forma fiable.
        # Se mide a hilos por defecto y se reporta honestamente (no se falla).
        t = bench_gemv(W, x)
        m = metrics(n, 4, t)
        default_threads = openblas_num_threads()
        print(f"[threads] threadpoolctl NO instalado -> medicion a hilos por defecto "
              f"(~{default_threads}): {m['time_ms']:.3f} ms | {m['gbps']:.2f} GB/s")
        return {
            "threadpoolctl": False,
            "default_threads_reported": default_threads,
            "blas": "scipy-openblas",
            "measurement_default": {"n": n, "dtype": "float32", **m},
            "by_threads": None,
        }

    by_threads = []
    base_gbps = None
    for tcount in THREAD_COUNTS:
        with threadpool_limits(limits=tcount, user_api="blas"):
            t = bench_gemv(W, x)
        m = metrics(n, 4, t)
        if tcount == 1:
            base_gbps = m["gbps"]
        speedup = (m["gbps"] / base_gbps) if base_gbps else None
        by_threads.append({"threads": tcount, **m, "speedup_vs_1": speedup})
        print(f"[threads] t={tcount} | {m['time_ms']:8.3f} ms | {m['gbps']:7.2f} GB/s | "
              f"speedup x{speedup:.2f}")
    return {
        "threadpoolctl": True,
        "blas": "scipy-openblas",
        "n": n,
        "dtype": "float32",
        "by_threads": by_threads,
    }


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUT, exist_ok=True)

    print("== Barrido 1: bytes/peso (GEMV y = W @ x) ==")
    rows, speedup = run_sweep_bytes(rng)
    print("\n  speedup f32 vs f64 por n:")
    for n in NS:
        print(f"    n={n:5d} -> x{speedup[str(n)]:.2f}")

    print("\n== Barrido 2: hilos de BLAS (n=4096, float32) ==")
    threads = run_sweep_threads(rng)

    result = {
        "experiment": "exp004_roofline_cpu",
        "config": {
            "seed": SEED, "ns": NS, "dtypes": [d[0] for d in DTYPES], "reps": REPS,
            "thread_counts": THREAD_COUNTS, "threads_n": THREADS_N,
            "numpy": np.__version__, "cpu_count": os.cpu_count(),
        },
        "sweep_bytes": rows,
        "speedup_f32_vs_f64": speedup,
        "sweep_threads": threads,
    }
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    lines = ["# exp004 - resultados (roofline de CPU, GEMV decode batch=1)", ""]
    lines.append(f"- numpy {np.__version__} | reps={REPS} | seed={SEED} | "
                 f"cpu_count={os.cpu_count()} | op = y = W @ x (GEMV)")
    lines.append("- Memory-bound si: GFLOP/s << pico CPU, GB/s ~plano al crecer n, f32 ~2x f64.")
    lines.append("")
    lines.append("## Barrido 1 - bytes/peso")
    lines.append("| n | dtype | time (ms) | GFLOP/s | GB/s |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r['n']} | {r['dtype']} | {r['time_ms']:.3f} | "
                     f"{r['gflops']:.2f} | {r['gbps']:.2f} |")
    lines.append("")
    lines.append("### Speedup f32 vs f64 (prediccion ~2x)")
    lines.append("| n | speedup f32/f64 |")
    lines.append("|---|---|")
    for n in NS:
        lines.append(f"| {n} | {speedup[str(n)]:.2f} |")
    lines.append("")
    lines.append("## Barrido 2 - hilos de BLAS (n=4096, float32)")
    if threads.get("by_threads"):
        lines.append("| hilos | time (ms) | GB/s | speedup vs 1 |")
        lines.append("|---|---|---|---|")
        for r in threads["by_threads"]:
            lines.append(f"| {r['threads']} | {r['time_ms']:.3f} | {r['gbps']:.2f} | "
                         f"x{r['speedup_vs_1']:.2f} |")
    else:
        m = threads["measurement_default"]
        lines.append(f"- threadpoolctl NO instalado -> medido a hilos por defecto "
                     f"(~{threads['default_threads_reported']}).")
        lines.append("")
        lines.append("| hilos (defecto) | time (ms) | GB/s |")
        lines.append("|---|---|---|")
        lines.append(f"| ~{threads['default_threads_reported']} | {m['time_ms']:.3f} | {m['gbps']:.2f} |")
    lines.append("")
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\nOK ->", os.path.join(OUT, "results.md"))


if __name__ == "__main__":
    main()
