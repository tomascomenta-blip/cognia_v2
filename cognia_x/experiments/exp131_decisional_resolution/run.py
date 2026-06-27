r"""
exp131 — CYCLE 149 / H-V4-9i (FRONTERA REAL §4.2 del capstone: RESOLVER el limbo "underpowered/diluyendo" que arrastran 140-141):
el CYCLE 140 halló una ventaja de RANKING (AUROC) del brazo durable (unlikelihood = cura 119) sobre el naive en el lazo torch REAL,
pero la declaró underpowered (N=4); el CYCLE 141 la potenció a N=8 y la dejó MIXTA -- la SIGNIFICANCIA era frágil (sign-test p=0.07)
y la magnitud DILUÍA con más seeds (winner's curse: los seeds nuevos ~4× más débiles). Cada seed era "lento", así que N se quedó en 8.

DESCUBRIMIENTO HABILITANTE (este ciclo): el lazo real es RÁPIDO (~36 s/seed en este CPU; el HybridLM byte-level es diminuto). El
"underpowered" NO era una restricción de tiempo. => se puede RESOLVER definitivamente corriendo N=24 y preguntando con una métrica de
potencia LIMPIA: ¿el INTERVALO DE CONFIANZA (bootstrap 95%) del gap AUROC durable−naive EXCLUYE el cero, o lo INCLUYE (la ventaja no
se distingue del ruido a potencia)? Y ¿la media-corriente se ESTABILIZA positiva o sigue DILUYENDO hacia cero?

DISEÑO. Reusa el lazo real de exp124 (run_seed: HybridLM genera 'N=a*b' -> verificador REAL sandbox -> confianza ENDÓGENA -> self-
train con ancla; durable agrega unlikelihood sobre lo verificado-incorrecto = cura 119). N=24 seeds, mismos params powered de 141
(rounds 8, pool 64). Métrica primaria: gap AUROC por seed (durable−naive, promediado sobre rondas; AUROC es base-rate-INVARIANTE, la
defensa que 140-141 establecieron contra el confound). POTENCIA: (a) CI bootstrap 95% del gap medio (10k resamples); (b) trayectoria
de la media-corriente (¿estabiliza o diluye?); (c) dilución por TERCIOS (1er/2do/3er tercio de seeds); (d) sign-test + t pareado.

PREGUNTA FALSABLE:
  - APOYADA si a N=24 el CI bootstrap 95% del gap EXCLUYE el cero (lo>0) Y la media-corriente NO diluye hacia cero (el 3er tercio no
    es ~0) -> la ventaja de calibración del durable (cura 119) es REAL y sobrevive a la potencia.
  - REFUTADA si el CI INCLUYE el cero (lo<=0) -> la ventaja NO se distingue del ruido a potencia (confirma la dilución de 141: era
    winner's curse).
  - MIXTA si el CI excluye el cero por poco PERO la magnitud sigue diluyendo / el 3er tercio es ~0.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp131_decisional_resolution.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp131_decisional_resolution.run --seeds 0-23
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import LO, HI
from cognia_x.experiments.exp124_decisional_real_loop.run import run_seed, ARMS, _seed_auc, _mean, _f

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def _parse_seeds(s):
    if "-" in s and "," not in s:
        a, b = s.split("-"); return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


def _bootstrap_ci(gaps, n_boot=10000, alpha=0.05, seed=0):
    rng = np.random.default_rng(seed)
    g = np.array(gaps, dtype=float)
    means = np.array([rng.choice(g, size=len(g), replace=True).mean() for _ in range(n_boot)])
    lo = float(np.percentile(means, 100 * alpha / 2))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return lo, hi


def _running_mean(gaps):
    c = np.cumsum(gaps)
    return [round(float(c[i] / (i + 1)), 4) for i in range(len(gaps))]


def _thirds(gaps):
    n = len(gaps); t = n // 3
    return (round(_mean(gaps[:t]), 4), round(_mean(gaps[t:2 * t]), 4), round(_mean(gaps[2 * t:]), 4))


def build_summary(per_seed, n_boot=10000):
    gaps = [_seed_auc(s, "durable", "auroc") - _seed_auc(s, "naive", "auroc") for s in per_seed]
    nc_dur = [_mean(s["hist"]["durable"]["ncorrect"]) for s in per_seed]
    nc_nai = [_mean(s["hist"]["naive"]["ncorrect"]) for s in per_seed]
    n = len(gaps)
    mean_gap = float(np.mean(gaps)); med = float(np.median(gaps))
    se = float(np.std(gaps, ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    tstat = mean_gap / se if se > 0 else 0.0
    n_pos = int(np.sum(np.array(gaps) > 0))
    lo, hi = _bootstrap_ci(gaps, n_boot=n_boot)
    run_mean = _running_mean(gaps)
    t1, t2, t3 = _thirds(gaps)

    ci_excludes_zero = lo > 0.0
    third_not_zero = t3 > 0.01
    diluting = t3 < t1 - 0.02 and t3 < 0.02     # la magnitud cae hacia cero en el último tercio
    dur_auroc = float(np.mean([_seed_auc(s, "durable", "auroc") for s in per_seed]))
    nai_auroc = float(np.mean([_seed_auc(s, "naive", "auroc") for s in per_seed]))

    if ci_excludes_zero and third_not_zero and not diluting:
        status = "apoyada"
        verdict = (
            "H-V4-9i APOYADA (RESOLUCIÓN a potencia N={n}): la ventaja de RANKING (AUROC) del durable (cura 119) sobre el naive en "
            "el lazo torch REAL es REAL y SOBREVIVE la potencia que 140-141 no pudieron alcanzar. El CI bootstrap 95% del gap "
            "durable−naive EXCLUYE el cero ([{lo}, {hi}], media +{mg}, mediana +{md}, {npos}/{n} seeds positivos, t={ts}); la "
            "media-corriente NO diluye hacia cero (tercios +{t1}/+{t2}/+{t3}); AUROC durable {da} vs naive {na}. => la mejor "
            "calibración del durable (unlikelihood sobre lo verificado-incorrecto) produce una señal endógena MÁS informativa sobre "
            "la correctness real, de forma estadísticamente robusta. Cierra el limbo 'underpowered' de 140-141: NO era ruido, era "
            "falta de N (el lazo es rápido, ~36 s/seed)."
        ).format(n=n, lo=_f(lo), hi=_f(hi), mg=_f(mean_gap), md=_f(med), npos=n_pos, ts=_f(tstat),
                 t1=_f(t1), t2=_f(t2), t3=_f(t3), da=_f(dur_auroc), na=_f(nai_auroc))
    elif not ci_excludes_zero:
        status = "refutada"
        verdict = (
            "H-V4-9i REFUTADA (RESOLUCIÓN a potencia N={n}): la ventaja AUROC del durable NO se distingue del ruido a potencia. El CI "
            "bootstrap 95% del gap durable−naive INCLUYE el cero ([{lo}, {hi}], media +{mg}, {npos}/{n} positivos, t={ts}); la "
            "media-corriente diluye (tercios +{t1}/+{t2}/+{t3}). => CONFIRMA la sospecha de 141 (winner's curse): la 'ventaja de "
            "calibración' de la cura 119 en el lazo real era un artefacto de N chico; a N={n} no sobrevive. RESULTADO HONESTO Y "
            "DEFINITIVO: el lazo real es rápido, así que el 'underpowered' se RESOLVIÓ -- y el veredicto es que la ventaja del "
            "durable en este lazo no es estadísticamente real. La cura 119 mejora la CALIBRACIÓN toy (119) pero NO produce una "
            "ventaja de ranking robusta en el lazo de auto-entrenamiento real."
        ).format(n=n, lo=_f(lo), hi=_f(hi), mg=_f(mean_gap), npos=n_pos, ts=_f(tstat), t1=_f(t1), t2=_f(t2), t3=_f(t3))
    else:
        status = "mixta"
        verdict = (
            "H-V4-9i MIXTA (RESOLUCIÓN a potencia N={n}): el CI bootstrap 95% del gap EXCLUYE el cero por poco ([{lo}, {hi}], media "
            "+{mg}, {npos}/{n} pos) PERO la magnitud sigue DILUYENDO (tercios +{t1}/+{t2}/+{t3}, 3er tercio ~0) -> la ventaja del "
            "durable es POSITIVA en agregado pero se concentra en los primeros seeds; no es una ventaja estable a través de seeds. "
            "Estadísticamente distinguible de cero pero práctica/establemente marginal."
        ).format(n=n, lo=_f(lo), hi=_f(hi), mg=_f(mean_gap), npos=n_pos, t1=_f(t1), t2=_f(t2), t3=_f(t3))

    return {"n": n, "gaps": [round(g, 4) for g in gaps], "mean_gap": round(mean_gap, 4), "median_gap": round(med, 4),
            "se": round(se, 4), "tstat": round(tstat, 3), "n_positive": n_pos,
            "ci95": [round(lo, 4), round(hi, 4)], "ci_excludes_zero": bool(ci_excludes_zero),
            "running_mean": run_mean, "thirds": [t1, t2, t3], "third_not_zero": bool(third_not_zero),
            "diluting": bool(diluting), "auroc_durable": round(dur_auroc, 4), "auroc_naive": round(nai_auroc, 4),
            "mean_ncorrect_durable": round(float(np.mean(nc_dur)), 2), "mean_ncorrect_naive": round(float(np.mean(nc_nai)), 2),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0-23")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.15)
    ap.add_argument("--temp", type=float, default=1.3)
    ap.add_argument("--replay_frac", type=float, default=0.5)
    ap.add_argument("--neg_w", type=float, default=0.5)
    ap.add_argument("--top_k", type=int, default=0)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--n_seed", type=int, default=200)
    ap.add_argument("--base_steps", type=int, default=250)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()
    if args.top_k <= 0:
        args.top_k = None
    n_boot = 10000
    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0-3", 5, 48, 60, 200
        n_boot = 2000

    seeds = _parse_seeds(args.seeds)
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp131] CYCLE 149 / H-V4-9i — RESOLUCIÓN a potencia (N=%d): ¿la ventaja AUROC del durable (140-141) sobrevive la potencia (CI excluye 0) o diluye a cero?" % len(seeds))
    log(f"[exp131] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} pool={args.pool} (reusa el lazo real de exp124; ~36s/seed)")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed, n_boot=n_boot)

    log("[exp131] --- RESOLUCIÓN a potencia (N=%d) ---" % sm["n"])
    log(f"[exp131] gap AUROC durable−naive por seed: {sm['gaps']}")
    log(f"[exp131] media +{sm['mean_gap']:.3f} mediana +{sm['median_gap']:.3f} ({sm['n_positive']}/{sm['n']} pos) t={sm['tstat']}")
    log(f"[exp131] CI bootstrap 95% = [{sm['ci95'][0]:+.3f}, {sm['ci95'][1]:+.3f}] -> EXCLUYE cero={sm['ci_excludes_zero']}")
    log(f"[exp131] media-corriente: {sm['running_mean']}")
    log(f"[exp131] DILUCIÓN por tercios: +{sm['thirds'][0]:.3f} / +{sm['thirds'][1]:.3f} / +{sm['thirds'][2]:.3f} -> 3er tercio>0={sm['third_not_zero']} diluyendo={sm['diluting']}")
    log(f"[exp131] AUROC durable={sm['auroc_durable']:.3f} naive={sm['auroc_naive']:.3f} | base-rate durable={sm['mean_ncorrect_durable']:.1f} naive={sm['mean_ncorrect_naive']:.1f}")
    log(f"[exp131] VEREDICTO H-V4-9i: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp131_decisional_resolution", "cycle": 149, "hypothesis": "H-V4-9i",
           "claim": "RESUELVE a POTENCIA (N=24) el limbo 'underpowered/diluyendo' de 140-141: el lazo real es RAPIDO (~36s/seed -> el "
                    "underpowered NO era restriccion de tiempo). Pregunta con metrica de potencia LIMPIA: el CI bootstrap 95% del gap "
                    "AUROC durable-naive EXCLUYE el cero (ventaja real) o lo INCLUYE (ruido, confirma la dilucion de 141). AUROC es "
                    "base-rate-INVARIANTE (la defensa de 140-141 contra el confound). Reusa el lazo torch real de exp124 (verificador "
                    "REAL, confianza endogena, durable=cura 119).",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp131] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
