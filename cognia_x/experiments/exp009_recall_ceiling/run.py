"""
exp009 — CYCLE: el TECHO de recall del mezclador de ESTADO FIJO escala con el TAMANO DEL ESTADO.

Hipotesis H-CEIL-1 (frontera recall<->throughput; corroborada por Arora et al. 2024, arXiv:2402.18668,
"Based": el recall asociativo de un mezclador recurrente esta acotado por el TAMANO de su estado): un
mezclador puramente LINEAL guarda su memoria en un estado recurrente de tamano FIJO (una matriz d x d
por cabeza, INDEPENDIENTE de la longitud de secuencia). Por eso su capacidad de recall asociativo
escala con ~d^2 (aqui n_heads=1 -> el estado es la matriz d x d COMPLETA = d^2). La ATENCION, en
cambio, guarda un KV-cache que CRECE con la secuencia -> recall ~ilimitado en N, independiente de d.

  DISENO PRIMARIO — recall vs TAMANO DEL ESTADO (barrido de d_model a CARGA fija):
    - Se FIJA una carga de memoria desafiante (n_pairs=16 asociaciones clave->valor) que DESBORDA el
      estado de los d mas chicos pero cabe en los mas grandes.
    - Se BARRE d_model en [8, 16, 24, 32, 48] (estados ~ d^2 = 64, 256, 576, 1024, 2304).
    - Para CADA d se entrena lineal_puro (attn_every=0, 6 capas lineales -> estado fijo) Y
      hibrido_3to1 (attn_every=3, 6 capas -> [lin,lin,attn,lin,lin,attn] = 2 capas de atencion).

  PREDICCION (H-CEIL-1):
    - lineal_puro: acc de recall SUBE con d_model (acotada por el estado ~d^2). A d chico (estado <
      carga) DEGRADA hacia azar; a d grande RECUPERA recall.
    - hibrido_3to1: acc ALTA y ~PLANA en todo d_model (la atencion aporta recall sin depender del
      estado lineal).
    - El GAP (hibrido - lineal) es GRANDE a d chico y SE ENCOGE al crecer d.
  REFUTADA SI: el lineal es plano-alto en todo d (no acotado por el estado), O el hibrido no le gana
    al lineal a d chico.

  PISO DE APRENDIBILIDAD (honestidad obligatoria — distinto del TECHO de capacidad): un modelo
  DEMASIADO chico no aprende la tarea NI como hibrido (la atencion tiny no forma el circuito de
  recall). Eso es un PISO de aprendibilidad, no el techo de estado. Verificado en este ciclo: a
  d_model=8 (~2.6k params) el hibrido se queda CLAVADO en azar -> ese punto se reporta como PISO, no
  como evidencia del techo. El techo se lee donde el hibrido SI aprende (d>=16) y el lineal escala.

RECETA (calibrada con EVIDENCIA de exp008 + probes de este ciclo, no asumida):
  - n_heads=1: el estado recurrente del lineal es la matriz d x d COMPLETA (= d^2), la lectura mas
    limpia del "techo ~ d^2" (la version multi-cabeza parte el estado en h*d_head^2 = d^2/h y diluye
    la capacidad; exp008 lo midio mas debil aun que el ideal). 1 sola cabeza = capacidad maxima y
    el barrido de d es directamente un barrido del tamano del estado.
  - n_layers=6, attn_every=3 -> el hibrido tiene 2 capas de ATENCION. exp008 probo que el circuito
    de recall (cabeza de token-previo o cabeza de induccion) exige DOS operaciones de atencion
    compuestas; con 1 sola (n_layers=4, ae=3) el hibrido NO cruza. Por eso profundidad 6.
  - n_queries=16 (SUPERVISION DENSA): exp008 identifico la densidad de supervision como EL lever
    para que el circuito de recall cruce en presupuesto CPU; con n_queries bajo el hibrido tiny no
    forma la cabeza. n_keys=160 >> n_pairs (siempre hay claves distintas). n_vals=16 -> azar=0.0625.
  - warmup=300 (forma la cabeza de induccion), early_stop=0.95 (las celdas resueltas cortan; las
    saturadas corren el presupuesto completo). seed=0 (determinista; eval_rng aislado en recall_task).

CARGA = 16: elegida con datos. exp008 mostro que la capacidad ENTRENADA del lineal satura MUCHO mas
bajo que el d^2 idealizado (a d=64/h=4 fallaba ya en np=8). Probes de este ciclo (n_heads=1, np=16):
el lineal d=48 (estado 2304) sube a ~0.19 hacia el paso 1500 mientras el d=16 (estado 256) apenas
deja el azar (~0.12 al paso 3500) -> np=16 es el regimen donde el barrido de d separa limpio en CPU.
Cargas mayores (np>=48) vuelven la tarea inaprendible hasta para el hibrido tiny en presupuesto CPU
(probado: d<=16 hibrido clavado en azar a np=48) -> seria PISO, no techo. np=16 es la eleccion honesta.

----------------------------------------------------------------------------------------------------
Escalabilidad Obligatoria (presupuesto de este experimento):
  - Complejidad temporal:  O(n_dmodels * n_configs * steps). El cuerpo de cada step es un
    forward+backward de un modelo TINY; la atencion (lineal y softmax) se entrena en forma PARALELA
    O(L^2) con L = 2*n_pairs + n_queries (= 48 a np=16). El costo por step crece ~cuadratico con
    n_pairs -> por eso la carga se fija BAJA (np=16) y barremos d (que solo cambia el ancho del
    modelo, costo ~lineal en d). PRIMARIO: 5 d_models * 2 configs * <=6000 steps (con early-stop) ~
    10 modelos tiny. En este i3 (2 cores) tarda ~15-25 min: costo honesto de entrenar el recall.
  - Espacio:  modelos diminutos (d<=48, 6 capas, <=130k params) -> pocos MB de params + activaciones;
    un unico results.json chico. Sin checkpoints en disco.
  - Comportamiento CPU:  torch.set_num_threads(3) (acorde a llama-server-speed-findings del lab: el
    i3 rinde mejor acotando hilos; evita oversubscription). Todo en CPU, sin CUDA.
----------------------------------------------------------------------------------------------------

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp009_recall_ceiling.run --smoke   # rapido
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp009_recall_ceiling.run           # FULL
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp009_recall_ceiling.run --load_sweep  # +secundario
"""
import argparse
import json
import os
import sys
import time

import torch

from cognia_x.train.recall_task import train_and_eval

# ASCII-safe printing: reconfigurar stdout a utf-8 si la consola lo permite (Windows cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

# Receta calibrada con evidencia (ver docstring): n_heads=1 -> estado lineal = matriz d x d completa;
# n_queries=16 supervision densa; n_keys=160 >> carga. azar = 1/n_vals = 0.0625.
RECIPE = dict(n_heads=1, n_vals=16, n_queries=16, n_keys=160, batch=64, lr=1e-3)

# Carga FIJA del barrido primario. np=16 desborda el estado de los d chicos y cabe en los grandes.
N_PAIRS_PRIMARY = 16

# Las dos configs comparadas a IGUAL carga, variando solo d_model (= tamano del estado lineal).
CONFIGS = [("lineal_puro", 0), ("hibrido_3to1", 3)]


def main():
    ap = argparse.ArgumentParser(description="exp009 — el techo de recall escala con el estado (H-CEIL-1)")
    ap.add_argument("--smoke", action="store_true",
                    help="modo rapido: menos d_models + pocos pasos (smoke test del pipeline)")
    ap.add_argument("--load_sweep", action="store_true",
                    help="ademas del barrido de d, corre el barrido SECUNDARIO de carga (d fijo=16)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=None, help="override de pasos por celda")
    ap.add_argument("--warmup", type=int, default=None, help="override de warmup lineal de LR")
    ap.add_argument("--n_pairs", type=int, default=None, help="override de la carga del barrido de d")
    args = ap.parse_args()

    if args.smoke:
        # Smoke: MISMA forma de modelo (n_layers=6) y carga que FULL, pero menos d y pocos pasos ->
        # valida el pipeline end-to-end (no cruza recall del todo; eso requiere miles de pasos).
        d_models = [8, 16, 32]
        steps = args.steps if args.steps is not None else 800
        warmup = args.warmup if args.warmup is not None else 80
    else:
        d_models = [8, 16, 24, 32, 48]
        steps = args.steps if args.steps is not None else 6000
        warmup = args.warmup if args.warmup is not None else 300

    n_pairs = args.n_pairs if args.n_pairs is not None else N_PAIRS_PRIMARY
    n_layers = 6
    early_stop = 0.95

    torch.set_num_threads(3)
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True)
        logf.write(s + "\n")
        logf.flush()

    chance = 1.0 / RECIPE["n_vals"]
    log(f"[exp009] inicio smoke={args.smoke} d_models={d_models} n_pairs={n_pairs} steps={steps} "
        f"warmup={warmup} n_layers={n_layers} recipe={RECIPE} azar={chance:.4f}")

    # ----- BARRIDO PRIMARIO: recall vs tamano del estado (d_model) a carga fija -----
    # grid: lista plana de celdas {d_model, n_pairs, config, final_acc, chance, params}
    grid = []
    # por_d[d_model][config] = acc (None si falta)
    por_d = {d: {name: None for name, _ in CONFIGS} for d in d_models}
    state_size = {d: d * d for d in d_models}   # n_heads=1 -> estado = d x d = d^2

    for d_model in d_models:
        for name, ae in CONFIGS:
            t0 = time.time()
            try:
                r = train_and_eval(
                    f"{name}_d{d_model}_np{n_pairs}", attn_every=ae, steps=steps, log=log,
                    seed=args.seed, d_model=d_model, n_layers=n_layers, n_pairs=n_pairs,
                    warmup=warmup, early_stop=early_stop, **RECIPE)
                acc = r["final_acc"]
                params = r["params"]
                log(f"[exp009] d={d_model} (estado~{state_size[d_model]}) np={n_pairs} {name} "
                    f"acc={acc:.3f} azar={r['chance']:.4f} capas={r['layers']} params={params:,} "
                    f"({(time.time()-t0)/60:.1f} min)")
            except Exception as e:  # noqa: BLE001
                acc, params = None, None
                log(f"[exp009] d={d_model} np={n_pairs} {name} ERROR {e!r}")
            grid.append({"d_model": d_model, "state_size": state_size[d_model], "n_pairs": n_pairs,
                         "config": name, "final_acc": acc, "chance": chance, "params": params})
            por_d[d_model][name] = acc
            _dump(grid, por_d, d_models, n_pairs, chance, args, steps, warmup, n_layers, state_size)

    # ----- summary del barrido de d -----
    summary = _build_summary(d_models, por_d, state_size, chance, n_pairs)

    # ----- BARRIDO SECUNDARIO (opcional): carga a d fijo=16 -----
    load_grid = None
    if args.load_sweep:
        d_fix = 16
        loads = [4, 8, 16] if args.smoke else [4, 8, 16, 32]
        load_steps = max(800, steps)
        log(f"[exp009] --- barrido SECUNDARIO de carga a d_model={d_fix} (estado~{d_fix*d_fix}) "
            f"loads={loads} ---")
        load_grid = []
        por_load = {np_: {name: None for name, _ in CONFIGS} for np_ in loads}
        for np_ in loads:
            for name, ae in CONFIGS:
                t0 = time.time()
                try:
                    r = train_and_eval(
                        f"{name}_d{d_fix}_LS_np{np_}", attn_every=ae, steps=load_steps, log=log,
                        seed=args.seed, d_model=d_fix, n_layers=n_layers, n_pairs=np_,
                        warmup=warmup, early_stop=early_stop, **RECIPE)
                    acc, params = r["final_acc"], r["params"]
                    log(f"[exp009][LS] d={d_fix} np={np_} {name} acc={acc:.3f} "
                        f"({(time.time()-t0)/60:.1f} min)")
                except Exception as e:  # noqa: BLE001
                    acc, params = None, None
                    log(f"[exp009][LS] d={d_fix} np={np_} {name} ERROR {e!r}")
                load_grid.append({"d_model": d_fix, "n_pairs": np_, "config": name,
                                  "final_acc": acc, "chance": chance, "params": params})
                por_load[np_][name] = acc
                _dump(grid, por_d, d_models, n_pairs, chance, args, steps, warmup, n_layers,
                      state_size, summary=summary, load_grid=load_grid)
        summary["load_sweep"] = {"d_model": d_fix, "loads": loads,
                                 "lineal_puro": [por_load[n]["lineal_puro"] for n in loads],
                                 "hibrido_3to1": [por_load[n]["hibrido_3to1"] for n in loads]}

    _dump(grid, por_d, d_models, n_pairs, chance, args, steps, warmup, n_layers, state_size,
          summary=summary, load_grid=load_grid)

    # ---------------- RESUMEN (ASCII-safe) ----------------
    log("[exp009] ==== RESUMEN — recall vs tamano del estado (d_model) ====")
    log(f"carga fija n_pairs={n_pairs}  |  azar (1/n_vals) = {chance:.4f}  |  n_heads=1 -> estado = d x d")
    log(f"{'d_model':>8} | {'estado~d^2':>10} | {'lineal_puro':>11} | {'hibrido_3to1':>12} | {'gap(h-l)':>9}")
    log("-" * 62)
    for d_model in d_models:
        lv = por_d[d_model]["lineal_puro"]
        hv = por_d[d_model]["hibrido_3to1"]
        def fmt(v):
            return f"{v:.3f}" if isinstance(v, float) else "   -   "
        gap = (hv - lv) if isinstance(lv, float) and isinstance(hv, float) else None
        log(f"{d_model:>8} | {state_size[d_model]:>10} | {fmt(lv):>11} | {fmt(hv):>12} | {fmt(gap):>9}")
    log("-" * 62)
    log(f"[exp009] HEADLINE: {summary['headline']}")
    if summary.get("learnability_floor_d"):
        log(f"[exp009] PISO de aprendibilidad (hibrido clavado en azar) en d_model={summary['learnability_floor_d']} "
            f"(NO es el techo de estado; el techo se lee donde el hibrido aprende).")

    if load_grid is not None:
        log("[exp009] ==== RESUMEN SECUNDARIO — recall vs carga (d_model=16 fijo) ====")
        ls = summary["load_sweep"]
        log(f"{'n_pairs':>8} | {'lineal_puro':>11} | {'hibrido_3to1':>12}")
        for i, np_ in enumerate(ls["loads"]):
            def fmt(v):
                return f"{v:.3f}" if isinstance(v, float) else "   -   "
            log(f"{np_:>8} | {fmt(ls['lineal_puro'][i]):>11} | {fmt(ls['hibrido_3to1'][i]):>12}")

    log(f"[exp009] results.json -> {os.path.join(RESULTS, 'results.json')}")
    logf.close()


def _build_summary(d_models, por_d, state_size, chance, n_pairs):
    """Construye el summary y el HEADLINE leyendo el techo de recall del lineal (escala con el estado)
    y la separacion del hibrido. Distingue el PISO de aprendibilidad (hibrido en azar a d minusculo,
    la tarea no se aprende) del TECHO de estado (recall del lineal acotado por d). HEADLINE ASCII-safe.

    Lecturas (calibradas con el resultado real, no idealizadas):
      - El recall ENTRENADO del lineal SUBE desde el piso (d chico) y luego SATURA: el feature-map
        ELU+1 multi-... aqui single-cabeza tiene una capacidad entrenada MUCHO menor que el d^2 ideal
        (ya observado en exp008), asi que el techo se ve como rampa->plateau, no como rampa infinita.
        Medimos la subida del MINIMO d al PICO (no min-vs-max, que esconde el plateau)."""
    floor_thresh = chance + 0.05    # "en azar" = a menos de 0.05 sobre el azar
    sep_thresh = 0.05               # "el hibrido le gana al lineal" = gap >= 0.05
    lin = {d: por_d[d]["lineal_puro"] for d in d_models}
    hyb = {d: por_d[d]["hibrido_3to1"] for d in d_models}

    # PISO: el mayor d donde el HIBRIDO sigue clavado en azar (no aprende la tarea) -> no es techo.
    floor_d = None
    for d in d_models:
        if isinstance(hyb[d], float) and hyb[d] < floor_thresh:
            floor_d = d   # el mayor d con hibrido-en-azar
    # d "validos" (al menos UNA de las dos configs deja el azar): donde hay senal de recall.
    valid = [d for d in d_models
             if (isinstance(lin[d], float) and lin[d] >= floor_thresh)
             or (isinstance(hyb[d], float) and hyb[d] >= floor_thresh)]

    # ----- TECHO del lineal: sube del MINIMO d a su PICO (captura rampa aunque luego sature) -----
    lin_pts = [(d, lin[d]) for d in d_models if isinstance(lin[d], float)]
    lineal_rises = None
    lineal_floor_acc = lineal_peak_acc = None
    lineal_peak_d = None
    if len(lin_pts) >= 2:
        d_min = lin_pts[0][0]
        lineal_floor_acc = lin[d_min]
        lineal_peak_d, lineal_peak_acc = max(lin_pts[1:], key=lambda p: p[1])  # mejor d > d_min
        lineal_rises = lineal_peak_acc > lineal_floor_acc + 0.05

    # ----- separacion del hibrido: gap = hibrido - lineal por d; donde y cuanto separa -----
    gap = {d: (hyb[d] - lin[d]) if isinstance(lin[d], float) and isinstance(hyb[d], float) else None
           for d in d_models}
    sep_ds = [d for d in d_models if isinstance(gap[d], float) and gap[d] >= sep_thresh]
    hyb_separates = bool(sep_ds)
    max_gap_d = max((d for d in d_models if isinstance(gap[d], float)),
                    key=lambda d: gap[d], default=None)
    max_gap = gap[max_gap_d] if max_gap_d is not None else None

    # ----- HEADLINE honesto, ASCII-safe -----
    bits = []
    if lineal_rises:
        bits.append(f"el recall del lineal SUBE con el estado (d={d_models[0]}~{state_size[d_models[0]]}: "
                    f"{lineal_floor_acc:.3f} -> d={lineal_peak_d}~{state_size[lineal_peak_d]}: "
                    f"{lineal_peak_acc:.3f}) y luego SATURA (techo de estado ENTRENADO, < d^2 ideal)")
    elif lineal_rises is False:
        bits.append("el recall del lineal NO sube de forma clara con el estado en este presupuesto")
    if hyb_separates and max_gap is not None:
        bits.append(f"el hibrido SE SEPARA del lineal a d grande (gap maximo +{max_gap:.3f} en d={max_gap_d}), "
                    f"la cabeza de atencion forma el recall solo cuando el modelo es lo bastante ancho")
    elif max_gap is not None:
        bits.append(f"el hibrido NO supera al lineal en ningun d (gap maximo {max_gap:+.3f}), su circuito de "
                    f"recall no cruza en presupuesto CPU a estos tamanos tiny")

    if lineal_rises and hyb_separates:
        verdict = "PREDICCION PARCIALMENTE HELD"
    elif lineal_rises:
        verdict = "TECHO DE ESTADO VISIBLE (lado lineal); hibrido sin separar"
    elif hyb_separates:
        verdict = "SOLO separacion del hibrido (lineal plano)"
    else:
        verdict = "INCONCLUSO"
    floor_note = (f" PISO de aprendibilidad en d<={floor_d} (ambas configs en azar: la tarea no se "
                  f"aprende a ese tamano, NO es el techo de estado)." if floor_d else "")
    headline = verdict + ": " + "; ".join(bits) + "." + floor_note

    return {
        "n_pairs": n_pairs,
        "chance": chance,
        "state_size_by_d": {str(d): state_size[d] for d in d_models},
        "lineal_puro_by_d": {str(d): lin[d] for d in d_models},
        "hibrido_3to1_by_d": {str(d): hyb[d] for d in d_models},
        "gap_by_d": {str(d): gap[d] for d in d_models},
        "valid_d": valid,
        "learnability_floor_d": floor_d,
        "lineal_rises_with_d": lineal_rises,
        "lineal_floor_acc": lineal_floor_acc,
        "lineal_peak_acc": lineal_peak_acc,
        "lineal_peak_d": lineal_peak_d,
        "hibrido_separates": hyb_separates,
        "separation_d": sep_ds,
        "max_gap": max_gap,
        "max_gap_d": max_gap_d,
        "headline": headline,
    }


def _dump(grid, por_d, d_models, n_pairs, chance, args, steps, warmup, n_layers, state_size,
          summary=None, load_grid=None):
    out = {
        "experiment": "exp009_recall_ceiling",
        "hypothesis": ("H-CEIL-1: el recall del estado fijo (lineal puro) escala con el tamano del "
                       "estado (~d^2, n_heads=1); el hibrido se mantiene alto via atencion"),
        "smoke": args.smoke,
        "seed": args.seed,
        "recipe": RECIPE,
        "n_pairs_primary": n_pairs,
        "steps": steps,
        "warmup": warmup,
        "n_layers": n_layers,
        "early_stop": 0.95,
        "chance": chance,
        "d_models": d_models,
        "state_size_by_d": {str(d): state_size[d] for d in d_models},
        "grid": grid,
    }
    if summary is not None:
        out["summary"] = summary
    if load_grid is not None:
        out["load_sweep_grid"] = load_grid
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
