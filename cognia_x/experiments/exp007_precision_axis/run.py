"""
exp007 - Eje de precision: bytes/peso vs throughput en numpy puro (Cognia-X).

Pregunta: reducir bytes por peso (float32 -> int8, 4x menos almacenamiento) acelera la GEMV
y = W @ x en numpy puro, igual que float64 -> float32 aceleraba en exp004?

Hipotesis bajo prueba (CAVEAT de D-009 / H-BIT-1):
  "Reducir bytes/peso mejora el throughput SOLO si hay kernels que exploten la baja precision.
   En numpy puro (BLAS solo acelera float), una matmul int8 ingenua NO acelera -incluso puede ser
   mas lenta- porque el ahorro es de MEMORIA, no de computo automatico. Por eso existen kernels
   especiales (T-MAC, bitnet.cpp): la proporcionalidad bytes->tok/s de exp004 (valida float32 vs
   float64, ambos BLAS) SE ROMPE en int8/ternario sin kernels dedicados (el unpack/LUT es compute)."
  Coherente con el vault: 'fused int4 kernel 1.01x - ruido, compute-bound'.
  Prediccion: el camino (2) int8 naive NO supera al float32 BLAS (puede ser >> mas lento). El ahorro
  de int8 es 4x de ALMACENAMIENTO real, pero no se traduce en speedup de computo en numpy puro.

Operacion medida: y = W @ x, con W (n, n) y x (n,) -> GEMV. Para n en {2048, 4096}.

Cuantizacion simetrica por-tensor:
  scale_W = max(abs(W))/127 ; W_i8 = round(W/scale_W).astype(int8)
  scale_x = max(abs(x))/127 ; x_i8 = round(x/scale_x).astype(int8)

Tres caminos cronometrados (>=20 reps tras warmup, time.perf_counter):
  (1) float32 (BLAS):           y = W @ x
  (2) int8 naive (sin BLAS):    y = W_i8.astype(int32) @ x_i8.astype(int32)   (matmul entera)
  (3) dequant + float32 (BLAS): y = (W_i8.astype(float32) * scale_W) @ x       (almacena int8,
      descomprime a float para multiplicar -> usa BLAS pero paga el dequant)

Para cada n se reporta time_ms de cada camino y el ratio vs float32 (ratio>1 = speedup, <1 = slowdown).
MEMORIA: bytes de W en float32 (n*n*4) vs int8 (n*n*1) -> ahorro 4x de ALMACENAMIENTO (real).

numpy puro, sin torch ni numba. Determinista (np.random.default_rng con semilla fija).
Salida -> results/results.json + results/results.md
Correr: .\\venv312\\Scripts\\python.exe cognia_x\\experiments\\exp007_precision_axis\\run.py
"""
import json
import os
import time

import numpy as np

SEED = 7
NS = [2048, 4096]
REPS = 20
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def quantize_symmetric_int8(a):
    """Cuantizacion simetrica por-tensor a int8. Devuelve (a_i8, scale)."""
    scale = float(np.max(np.abs(a))) / 127.0
    a_i8 = np.round(a / scale).astype(np.int8)
    return a_i8, scale


def bench(fn, reps=REPS):
    """Tiempo medio (s) de fn() sobre `reps` reps tras 1 warmup."""
    fn()  # warmup (asigna buffer de salida + carga a cache)
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    return (time.perf_counter() - t0) / reps


def run_for_n(rng, n):
    """Mide los tres caminos para un tamano n. Devuelve dict con tiempos y ratios."""
    W = rng.standard_normal((n, n)).astype(np.float32)
    x = rng.standard_normal(n).astype(np.float32)

    W_i8, scale_W = quantize_symmetric_int8(W)
    x_i8, _scale_x = quantize_symmetric_int8(x)

    # Pre-castear dentro de cada lambda mide el coste real de cada camino tal cual se ejecutaria:
    # (2) la matmul entera incluye el upcast int8->int32 (numpy no tiene GEMM int8 nativa via BLAS).
    # (3) el dequant int8->float32 + escala es parte del coste del camino "almacenar int8".
    def path_f32():
        return W @ x

    def path_int8_naive():
        return W_i8.astype(np.int32) @ x_i8.astype(np.int32)

    def path_dequant_f32():
        return (W_i8.astype(np.float32) * scale_W) @ x

    t_f32 = bench(path_f32)
    t_int8 = bench(path_int8_naive)
    t_dequant = bench(path_dequant_f32)

    bytes_f32 = n * n * 4
    bytes_i8 = n * n * 1

    row = {
        "n": n,
        "time_ms": {
            "float32_blas": t_f32 * 1e3,
            "int8_naive": t_int8 * 1e3,
            "dequant_float32_blas": t_dequant * 1e3,
        },
        "ratio_vs_float32": {  # >1 = mas rapido que float32 ; <1 = mas lento
            "float32_blas": 1.0,
            "int8_naive": (t_f32 / t_int8) if t_int8 else None,
            "dequant_float32_blas": (t_f32 / t_dequant) if t_dequant else None,
        },
        "memory_bytes_W": {
            "float32": bytes_f32,
            "int8": bytes_i8,
            "storage_saving_x": bytes_f32 / bytes_i8,
        },
        "scale_W": scale_W,
    }

    print(f"n={n}")
    print(f"  (1) float32 (BLAS)            : {row['time_ms']['float32_blas']:9.4f} ms"
          f"  (ratio x1.00, referencia)")
    print(f"  (2) int8 naive (sin BLAS)     : {row['time_ms']['int8_naive']:9.4f} ms"
          f"  (ratio x{row['ratio_vs_float32']['int8_naive']:.3f} vs f32)")
    print(f"  (3) dequant + float32 (BLAS)  : {row['time_ms']['dequant_float32_blas']:9.4f} ms"
          f"  (ratio x{row['ratio_vs_float32']['dequant_float32_blas']:.3f} vs f32)")
    print(f"  memoria W: float32 = {bytes_f32/1e6:.2f} MB | int8 = {bytes_i8/1e6:.2f} MB"
          f"  -> ahorro almacenamiento x{row['memory_bytes_W']['storage_saving_x']:.0f}")
    return row


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUT, exist_ok=True)

    print("== exp007: eje de precision (GEMV y = W @ x), numpy puro ==")
    print(f"   numpy {np.__version__} | reps={REPS} | seed={SEED} | cpu_count={os.cpu_count()}")
    print(f"   Prediccion (D-009/H-BIT-1 caveat): int8 naive NO supera a float32 BLAS;")
    print(f"   el ahorro de int8 es de MEMORIA (4x), no de computo en numpy puro.\n")

    rows = [run_for_n(rng, n) for n in NS]

    result = {
        "experiment": "exp007_precision_axis",
        "config": {
            "seed": SEED, "ns": NS, "reps": REPS,
            "numpy": np.__version__, "cpu_count": os.cpu_count(),
        },
        "rows": rows,
    }
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    lines = ["# exp007 - resultados (eje de precision: bytes/peso vs throughput, GEMV)", ""]
    lines.append(f"- numpy {np.__version__} | reps={REPS} | seed={SEED} | "
                 f"cpu_count={os.cpu_count()} | op = y = W @ x (GEMV)")
    lines.append("- Hipotesis (D-009/H-BIT-1 caveat): en numpy puro, int8 naive NO acelera vs "
                 "float32 BLAS;")
    lines.append("  el ahorro de int8 es de MEMORIA (4x almacenamiento), no de computo.")
    lines.append("")
    lines.append("## Tiempos por camino y ratio vs float32 (ratio>1 = mas rapido, <1 = mas lento)")
    lines.append("| n | float32 BLAS (ms) | int8 naive (ms) | ratio int8 | dequant+f32 (ms) | "
                 "ratio dequant |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        tm = r["time_ms"]
        rt = r["ratio_vs_float32"]
        lines.append(
            f"| {r['n']} | {tm['float32_blas']:.4f} | {tm['int8_naive']:.4f} | "
            f"x{rt['int8_naive']:.3f} | {tm['dequant_float32_blas']:.4f} | "
            f"x{rt['dequant_float32_blas']:.3f} |"
        )
    lines.append("")
    lines.append("## Memoria de W: float32 vs int8 (ahorro de ALMACENAMIENTO real)")
    lines.append("| n | float32 (MB) | int8 (MB) | ahorro |")
    lines.append("|---|---|---|---|")
    for r in rows:
        mem = r["memory_bytes_W"]
        lines.append(f"| {r['n']} | {mem['float32']/1e6:.2f} | {mem['int8']/1e6:.2f} | "
                     f"x{mem['storage_saving_x']:.0f} |")
    lines.append("")
    lines.append("## Lectura")
    lines.append("- int8 naive vs float32: si el ratio < 1, NO acelero (confirma el caveat: el "
                 "ahorro de bytes no compra computo en numpy puro).")
    lines.append("- dequant+float32: usa BLAS pero paga el unpack int8->float; el ratio dice si "
                 "almacenar int8 y descomprimir da speedup neto.")
    lines.append("- El ahorro 4x es de MEMORIA/almacenamiento, no de FLOPs: requiere kernels "
                 "dedicados (T-MAC, bitnet.cpp) para volverse throughput.")
    lines.append("")
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\nOK ->", os.path.join(OUT, "results.md"))


if __name__ == "__main__":
    main()
