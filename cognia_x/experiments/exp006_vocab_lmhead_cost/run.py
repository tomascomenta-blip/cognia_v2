"""
exp006 - Coste del lm_head (proyeccion a vocabulario) vs vocab V (Cognia-X).

Pregunta: en modelos pequenos, cuanto cuesta por token la capa de SALIDA (lm_head, la
proyeccion a vocabulario, O(V*d)) frente a un bloque transformer, y como escala con el
tamano de vocab V? Y cuanto de los parametros del modelo se va en embedding+lm_head a vocab
grande?

Hipotesis bajo prueba (D-008 / H-REP-1 / H-REP-4):
  H-REP-1: el coste por token del lm_head (GEMV O(V*d)) crece linealmente con V y, para V
           grande, puede igualar o superar el coste de un bloque transformer entero (~12*d^2
           flops) -> punto estilo FR-Spec donde la proyeccion de vocab domina el paso. El
           embedding de ENTRADA es un lookup trivial (1 fila, O(d)), despreciable frente a esto.
           Conclusion de diseno: conviene vocab MODERADO (no 256k) en modelos chicos.
  H-REP-4: embedding + lm_head son una fraccion grande (25-37%) de los parametros de un modelo
           1-3B cuando el vocab es grande (con o sin weight-tying).

Operaciones medidas (numpy puro, GEMV en decode batch=1, d=2048):
  (A) lm_head:  y = Eout @ h, Eout (V,d) float32, h (d,) -> O(V*d) flops = 2*V*d. Para V hasta
      65536 se asigna y se mide; mas alla NO se asigna (0.5GB a V=65536), se usa la formula
      analitica (escalado lineal en V del tiempo/peso medido).
  (B) 1 bloque transformer (proxy fijo, indep. de V): las 6 GEMVs dominantes del decode de 1
      token con d=2048: 4 proyecciones de atencion (d,d)@(d,) [q,k,v,o] + MLP up (4d,d)@(d,) +
      MLP down (d,4d)@(4d,). Total flops ~= 4*2d^2 + 2*(4d*d)*2 = 12*d^2 (multiply-add x2).
  (C) embedding de ENTRADA: tiempo de extraer 1 fila de la tabla (V,d) (un lookup, O(d)).
  (D) ratios: lm_head(V)/bloque ; cruce donde lm_head iguala 1 bloque ; lm_head(V)/(n_layers bloques).
  (E) MEMORIA (analitica, sin asignar): params de embed+head tied (V*d) y untied (2*V*d), y su
      fraccion sobre el total ~= n_layers*12*d^2 + (embed+head), para V grandes hasta 256000.

Metodo: tiempo medio con time.perf_counter sobre >=20 reps tras warmup. Determinista
(np.random.default_rng con semilla fija). Sin torch ni numba.

Salida -> results/results.json + results/results.md
Correr: .\\venv312\\Scripts\\python.exe cognia_x\\experiments\\exp006_vocab_lmhead_cost\\run.py
"""
import json
import os
import time

import numpy as np

SEED = 7
D_MODEL = 2048
N_LAYERS = 24
# Vocabs que SI se asignan y miden (V=65536 -> 65536*2048*4 = 0.5GB, tope de seguridad en 8-16GB).
V_TIMED = [8192, 16384, 32768, 65536]
# Vocabs solo analiticos (memoria), sin asignar.
V_MEM = [8192, 32768, 65536, 131072, 256000]
V_EMBED_LOOKUP = 65536  # tabla grande para mostrar que el lookup sigue siendo trivial
REPS = 20
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def bench(fn, reps=REPS):
    """Tiempo medio (s) de fn() sobre `reps` reps tras 1 warmup."""
    fn()  # warmup: primera asignacion del buffer de salida + carga a cache
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    return (time.perf_counter() - t0) / reps


def bench_lm_head(rng, V, d):
    """(A) GEMV de la proyeccion a vocabulario: y = Eout @ h. Eout (V,d), h (d,)."""
    Eout = rng.standard_normal((V, d), dtype=np.float32)
    h = rng.standard_normal(d, dtype=np.float32)
    t = bench(lambda: Eout @ h)
    flops = 2.0 * V * d
    return {"V": V, "time_ms": t * 1e3, "gflops": flops / t / 1e9,
            "flops": flops, "ns_per_vocab_row": t * 1e9 / V}


def bench_block(rng, d):
    """(B) 1 bloque transformer en decode: 6 GEMVs (q,k,v,o, mlp_up, mlp_down). Matrices fuera del timing."""
    # Pesos construidos UNA vez fuera del cronometro (no cuentan en el coste del paso).
    Wq = rng.standard_normal((d, d), dtype=np.float32)
    Wk = rng.standard_normal((d, d), dtype=np.float32)
    Wv = rng.standard_normal((d, d), dtype=np.float32)
    Wo = rng.standard_normal((d, d), dtype=np.float32)
    Wup = rng.standard_normal((4 * d, d), dtype=np.float32)    # MLP up: d -> 4d
    Wdown = rng.standard_normal((d, 4 * d), dtype=np.float32)  # MLP down: 4d -> d
    x = rng.standard_normal(d, dtype=np.float32)
    hmlp = rng.standard_normal(4 * d, dtype=np.float32)

    def block():
        Wq @ x
        Wk @ x
        Wv @ x
        Wo @ x
        Wup @ x       # (4d,d)@(d,)
        Wdown @ hmlp  # (d,4d)@(4d,)

    t = bench(block)
    # FLOPs reales de las 6 GEMVs (multiply-add = 2 flop): atencion 4*(2*d^2) + MLP 2*(2*4d^2)
    # = 8d^2 + 16d^2 = 24*d^2. (La spec lo resume como "~12*d^2", que es el MAC-count; el
    # flop-count real es 24*d^2. GFLOP/s se reporta con el flop-count real.)
    flops = 24.0 * d * d
    return {"time_ms": t * 1e3, "gflops": flops / t / 1e9, "flops": flops}


def bench_embed_lookup(rng, V, d):
    """(C) Embedding de ENTRADA: extraer 1 fila de la tabla (V,d). Lookup O(d), debe ser trivial."""
    table = rng.standard_normal((V, d), dtype=np.float32)
    idx = int(rng.integers(0, V))
    # .copy() para forzar la materializacion de la fila (evitar que numpy devuelva solo una vista).
    t = bench(lambda: table[idx].copy())
    return {"V": V, "time_ms": t * 1e3, "row_dim": d}


def memory_analysis(d, n_layers):
    """(E) Params embed+head (tied=V*d, untied=2*V*d) y su fraccion sobre el total del modelo."""
    block_params = 12.0 * d * d  # mismas 6 matrices del bloque: 4*d^2 + 2*(4d*d) = 12*d^2
    backbone = n_layers * block_params
    rows = []
    for V in V_MEM:
        tied = float(V) * d          # weight-tying: embedding y lm_head comparten la matriz
        untied = 2.0 * float(V) * d  # sin tying: dos matrices V*d independientes
        total_tied = backbone + tied
        total_untied = backbone + untied
        rows.append({
            "V": V,
            "embed_head_params_tied": tied,
            "embed_head_params_untied": untied,
            "total_params_tied": total_tied,
            "total_params_untied": total_untied,
            "frac_tied_pct": 100.0 * tied / total_tied,
            "frac_untied_pct": 100.0 * untied / total_untied,
        })
    return backbone, block_params, rows


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUT, exist_ok=True)
    d = D_MODEL

    print(f"== exp006: coste lm_head(V) vs bloque transformer (d={d}, n_layers={N_LAYERS}) ==")
    print(f"   numpy {np.__version__} | reps={REPS} | seed={SEED} | cpu_count={os.cpu_count()}")

    # (B) bloque de referencia primero (lo necesitamos para los ratios).
    print("\n-- (B) coste de 1 bloque transformer (6 GEMVs, proxy fijo) --")
    block = bench_block(rng, d)
    print(f"   bloque: {block['time_ms']:8.4f} ms | {block['gflops']:7.2f} GFLOP/s")

    # (A) lm_head para cada V (medido).
    print("\n-- (A) coste lm_head = Eout @ h (GEMV O(V*d)), medido --")
    lm_rows = []
    for V in V_TIMED:
        r = bench_lm_head(rng, V, d)
        r["ratio_vs_block"] = r["time_ms"] / block["time_ms"]
        r["ratio_vs_n_layers"] = r["time_ms"] / (block["time_ms"] * N_LAYERS)
        lm_rows.append(r)
        print(f"   V={V:6d} | {r['time_ms']:8.4f} ms | {r['gflops']:7.2f} GFLOP/s | "
              f"lm_head/bloque = x{r['ratio_vs_block']:.3f} | "
              f"lm_head/{N_LAYERS}bloques = {r['ratio_vs_n_layers']*100:5.2f}%")

    # (C) embedding lookup (entrada).
    print("\n-- (C) embedding de ENTRADA: 1 fila de tabla (V,d), lookup O(d) --")
    emb = bench_embed_lookup(rng, V_EMBED_LOOKUP, d)
    # Comparacion contra el lm_head al mismo V para evidenciar lo trivial del lookup.
    lm_same_V = next((r for r in lm_rows if r["V"] == V_EMBED_LOOKUP), lm_rows[-1])
    emb["vs_lm_head_same_V"] = lm_same_V["time_ms"] / emb["time_ms"] if emb["time_ms"] else None
    print(f"   V={emb['V']:6d} | lookup {emb['time_ms']:10.6f} ms (extraer fila d={d}) | "
          f"lm_head(V={lm_same_V['V']}) es ~{emb['vs_lm_head_same_V']:.0f}x mas caro")

    # (D) cruce: a que V el lm_head iguala 1 bloque. Tiempo del lm_head es lineal en V, asi que
    # extrapolamos con el coste por fila de vocab medido en el V mayor (mas estable).
    ref = lm_rows[-1]  # V mayor medido
    ns_per_row = ref["ns_per_vocab_row"]            # ns por fila de vocab (pendiente de la recta)
    block_ns = block["time_ms"] * 1e6               # bloque en ns
    v_cross_block = block_ns / ns_per_row           # V al que lm_head == 1 bloque
    v_cross_n_layers = (block_ns * N_LAYERS) / ns_per_row  # V al que lm_head == n_layers bloques
    print("\n-- (D) cruce lm_head vs bloque (extrapolacion lineal en V) --")
    print(f"   pendiente medida: {ns_per_row:.4f} ns por fila de vocab (de V={ref['V']})")
    print(f"   lm_head iguala 1 bloque a   V ~= {v_cross_block:,.0f}")
    print(f"   lm_head iguala {N_LAYERS} bloques a  V ~= {v_cross_n_layers:,.0f}")

    # (E) memoria analitica.
    print("\n-- (E) memoria: params embed+head y fraccion del modelo (analitico) --")
    backbone, block_params, mem_rows = memory_analysis(d, N_LAYERS)
    print(f"   backbone = n_layers*12*d^2 = {backbone:,.0f} params")
    for m in mem_rows:
        print(f"   V={m['V']:7d} | tied {m['embed_head_params_tied']/1e6:7.1f}M -> "
              f"{m['frac_tied_pct']:5.2f}% | untied {m['embed_head_params_untied']/1e6:7.1f}M -> "
              f"{m['frac_untied_pct']:5.2f}% | total(tied) {m['total_params_tied']/1e6:6.0f}M")

    result = {
        "experiment": "exp006_vocab_lmhead_cost",
        "config": {
            "seed": SEED, "d_model": D_MODEL, "n_layers": N_LAYERS,
            "v_timed": V_TIMED, "v_mem": V_MEM, "v_embed_lookup": V_EMBED_LOOKUP,
            "reps": REPS, "numpy": np.__version__, "cpu_count": os.cpu_count(),
        },
        "block": block,
        "lm_head": lm_rows,
        "embed_lookup": emb,
        "crossover": {
            "ns_per_vocab_row": ns_per_row, "from_V": ref["V"],
            "v_lm_head_equals_1_block": v_cross_block,
            "v_lm_head_equals_n_layers_blocks": v_cross_n_layers,
        },
        "memory": {"backbone_params": backbone, "block_params": block_params, "rows": mem_rows},
    }
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    lines = ["# exp006 - coste lm_head(V) vs bloque transformer + memoria embed/head", ""]
    lines.append(f"- numpy {np.__version__} | reps={REPS} | seed={SEED} | d={D_MODEL} | "
                 f"n_layers={N_LAYERS} | cpu_count={os.cpu_count()}")
    lines.append(f"- 1 bloque (6 GEMVs): {block['time_ms']:.4f} ms | {block['gflops']:.2f} GFLOP/s")
    lines.append("")
    lines.append("## (A) coste lm_head = Eout @ h (GEMV O(V*d))")
    lines.append("| V | time (ms) | GFLOP/s | lm_head/bloque | lm_head / n_layers bloques |")
    lines.append("|---|---|---|---|---|")
    for r in lm_rows:
        lines.append(f"| {r['V']} | {r['time_ms']:.4f} | {r['gflops']:.2f} | "
                     f"x{r['ratio_vs_block']:.3f} | {r['ratio_vs_n_layers']*100:.2f}% |")
    lines.append("")
    lines.append("## (C) embedding de ENTRADA (lookup de 1 fila)")
    lines.append(f"- V={emb['V']} | lookup = {emb['time_ms']:.6f} ms | "
                 f"el lm_head al mismo V es ~{emb['vs_lm_head_same_V']:.0f}x mas caro -> lookup trivial.")
    lines.append("")
    lines.append("## (D) cruce lm_head vs bloque (extrapolacion lineal en V)")
    lines.append(f"- pendiente: {ns_per_row:.4f} ns/fila de vocab (medida en V={ref['V']})")
    lines.append(f"- lm_head iguala **1 bloque** a V ~= {v_cross_block:,.0f}")
    lines.append(f"- lm_head iguala **{N_LAYERS} bloques** a V ~= {v_cross_n_layers:,.0f}")
    lines.append("")
    lines.append("## (E) memoria: params embed+head y fraccion del modelo (analitico)")
    lines.append(f"- backbone = n_layers*12*d^2 = {backbone:,.0f} params")
    lines.append("| V | embed+head tied (M) | % tied | embed+head untied (M) | % untied | total tied (M) |")
    lines.append("|---|---|---|---|---|---|")
    for m in mem_rows:
        lines.append(f"| {m['V']} | {m['embed_head_params_tied']/1e6:.1f} | {m['frac_tied_pct']:.2f}% | "
                     f"{m['embed_head_params_untied']/1e6:.1f} | {m['frac_untied_pct']:.2f}% | "
                     f"{m['total_params_tied']/1e6:.0f} |")
    lines.append("")
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\nOK ->", os.path.join(OUT, "results.md"))


if __name__ == "__main__":
    main()
