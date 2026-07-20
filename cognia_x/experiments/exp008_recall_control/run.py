"""
exp008 — CYCLE 6: cerrar H-MEZ-4 con un CONTROL POSITIVO VALIDO.

Contexto: el run nocturno (overnight_v0) dio recall INCONCLUSO porque ni la atencion pura
resolvio MQAR (~0.09 acc). Diagnostico (ver research_log CYCLE 6, corregido por la revision
adversarial del workflow): NO era un bug del modelo (RoPE, atencion lineal y alineamiento
target/logits verificados correctos). El control positivo fallaba por SUB-RECURSOS, y los
leveres reales son (a) suficientes PASOS y (b) densidad de SUPERVISION (n_queries): con
n_queries adecuado la atencion cruza a ~1.0 en 2 pares con SOLO 2 capas en ~300-460 pasos
(reproducido). La narrativa previa de "exige 4 capas/8 cabezas/4000 pasos" estaba
sobredimensionada (y su 0.998 nunca se commiteo) — el cuello real era n_queries=1 (supervision
escasa) + pocos pasos, no la profundidad. (Ademas se agrego RoPE al modelo en este ciclo.)

OJO con la capacidad del lineal: LinearAttention es MULTI-CABEZA; su estado recurrente es
h*d_head^2 = d^2/h (NO d^2 como el estado single-head que midio exp002). Con d=64/h=8 ->
d_head=8 -> capacidad ~16 pares; para SEPARAR (lineal<<atencion) hay que barrer n_pairs por
ENCIMA de esa capacidad (np>=24), que es justo donde a la atencion le cuesta mas cruzar en CPU.

Este experimento, con esa receta, barre la DIFICULTAD (n_pairs) y compara 3 configs a igual
tamano de modelo:
  - atencion_pura (ae=1): control positivo, recall ~exacto en-contexto -> debe llegar a ~1.0.
  - lineal_puro   (ae=0): estado fijo; exp002 predice recall ACOTADO -> debe caer al subir n_pairs.
  - hibrido_3to1  (ae=3): mayoria lineal + 1/3 atencion -> hipotesis H-MEZ-4: RECUPERA el recall
    del full a una fraccion del coste (exp005).

Cierre de H-MEZ-4 = (a) atencion llega a ~1.0 (control valido) Y (b) hibrido >> lineal,
hibrido ~ atencion, en el regimen donde el lineal se satura.

Uso:
  python -m cognia_x.experiments.exp008_recall_control.run --deadline <epoch> [--pairs 4,8,16,32] [--steps 6000]
"""
import argparse
import json
import os
import time

import torch

from cognia_x.train.recall_task import train_and_eval

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

# Receta base (overridable por args). d=64/h=8 -> d_head=8 -> cap lineal ~16 pares.
# n_queries=16 = supervision densa (lever clave para que la atencion cruce mas rapido).
RECIPE = dict(d_model=64, n_layers=4, n_heads=8, n_vals=16, n_queries=16,
              batch=64, lr=1e-3)
CONFIGS = [("atencion_pura", 1), ("hibrido_3to1", 3), ("lineal_puro", 0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deadline", type=float, default=None, help="epoch time límite global")
    ap.add_argument("--pairs", type=str, default="4,8,16,32", help="lista de n_pairs (dificultad)")
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--min_steps", type=int, default=0,
                    help="piso de pasos: no cortar una celda por deadline antes de esto (que la "
                         "atención cruce la transición de fase antes de aceptar su acc)")
    ap.add_argument("--warmup", type=int, default=0, help="pasos de warmup lineal de LR")
    ap.add_argument("--early_stop", type=float, default=0.99,
                    help="cortar una celda si acc >= esto (resuelto); 1.01 lo desactiva")
    ap.add_argument("--hybrid_ae", type=int, default=3,
                    help="attn_every del híbrido (a n_layers=2 usar 2 -> [linear,attn]; a 4 usar 3)")
    ap.add_argument("--n_queries", type=int, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--abs_pos", action="store_true",
                    help="embeddings de posición absolutos en TODAS las configs (justicia: la rama "
                         "lineal no tiene atención/RoPE; sin esto compararía sin señal posicional)")
    # overrides de la receta (para calibrar coste<->separación)
    ap.add_argument("--d_model", type=int, default=None)
    ap.add_argument("--n_layers", type=int, default=None)
    ap.add_argument("--n_heads", type=int, default=None)
    ap.add_argument("--n_vals", type=int, default=None)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--configs", type=str, default=None,
                    help="subconjunto de configs por nombre, coma-separado (atencion_pura,hibrido_3to1,lineal_puro)")
    args = ap.parse_args()

    for k in ("d_model", "n_layers", "n_heads", "n_vals", "n_queries", "lr"):
        v = getattr(args, k)
        if v is not None:
            RECIPE[k] = v
    configs_all = [("atencion_pura", 1), ("hibrido_3to1", args.hybrid_ae), ("lineal_puro", 0)]
    configs = configs_all
    if args.configs:
        want = set(args.configs.split(","))
        configs = [c for c in configs_all if c[0] in want]

    torch.set_num_threads(3)
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True)
        logf.write(s + "\n"); logf.flush()

    pairs = [int(p) for p in args.pairs.split(",")]
    n_keys = max(pairs) * 2  # suficientes claves distintas para el n_pairs mayor
    log(f"[exp008] inicio. pairs={pairs} steps={args.steps} recipe={RECIPE} "
        f"n_keys={n_keys} abs_pos={args.abs_pos}")

    grid = {}  # n_pairs -> {config: acc}
    # Cada (dificultad, config) recibe una porcion igual del tiempo restante.
    n_cells = len(pairs) * len(configs)
    cell = 0
    for np_ in pairs:
        grid[np_] = {}
        for name, ae in configs:
            cell += 1
            # corte global ANTES de arrancar la celda (no sobrepasar el deadline por una celda entera)
            if args.deadline is not None and time.time() > args.deadline:
                log("[exp008] deadline global alcanzado antes de la celda; corte.")
                break
            per = None
            if args.deadline is not None:
                rem = args.deadline - time.time()
                cells_left = n_cells - (cell - 1)
                per = time.time() + max(60.0, rem / max(1, cells_left))
            t0 = time.time()
            try:
                r = train_and_eval(
                    f"{name}_np{np_}", attn_every=ae, steps=args.steps, log=log, seed=args.seed,
                    n_keys=n_keys, n_pairs=np_, deadline=per, min_steps=args.min_steps,
                    warmup=args.warmup, early_stop=args.early_stop, abs_pos=args.abs_pos, **RECIPE)
                grid[np_][name] = r["final_acc"]
                log(f"[exp008] np={np_} {name} acc={r['final_acc']:.3f} azar={r['chance']:.3f} "
                    f"capas={r['layers']} ({(time.time()-t0)/60:.1f} min)")
            except Exception as e:  # noqa: BLE001
                grid[np_][name] = None
                log(f"[exp008] np={np_} {name} ERROR {e!r}")
            # snapshot incremental (no perder progreso si se corta)
            with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
                json.dump({"recipe": RECIPE, "steps": args.steps, "abs_pos": args.abs_pos,
                           "grid": grid}, f, indent=2)
            if args.deadline is not None and time.time() > args.deadline:
                log("[exp008] deadline global alcanzado; corte.")
                break
        else:
            continue
        break

    log("[exp008] ==== RESUMEN (acc de recall) ====")
    log(f"{'n_pairs':>8} | {'atencion':>9} | {'hibrido':>9} | {'lineal':>9}")
    for np_ in pairs:
        g = grid.get(np_, {})
        def fmt(k):
            v = g.get(k); return f"{v:.3f}" if isinstance(v, float) else "  -  "
        log(f"{np_:>8} | {fmt('atencion_pura'):>9} | {fmt('hibrido_3to1'):>9} | {fmt('lineal_puro'):>9}")
    logf.close()


if __name__ == "__main__":
    main()
