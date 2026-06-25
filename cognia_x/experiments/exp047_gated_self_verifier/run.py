r"""
exp047 — CYCLE 62 / H-V4-2j (cierre de la UNIFICACIÓN): GATING EXPLÍCITO — el agente DECIDE cuándo confiar en su
auto-consistencia usando su PROPIA calibración estimada (probe chico), cayendo al verificador externo donde no
es confiable. Convierte la MIXTA del CYCLE 60 en "el agente que SABE cuándo confiar en sí mismo" (nunca colapsa).

CONTEXTO: exp046 (CYCLE 60, H-V4-2i, MIXTA) mostró que la auto-consistencia es un verificador PARCIAL gateado
por calibración: usable con base calibrada, COLAPSA con base mal-calibrada (consistente-pero-equivocado). El
peligro: usarla cuando NO está calibrada. SOLUCIÓN: que el agente ESTIME su calibración con un probe barato y
DECIDA — usar el filtro endógeno donde es confiable, el externo donde no.

MECANISMO del probe (honesto): en esta tarea de juguete el TARGET está en el prompt ("N="), así que estimar
"¿el valor consistente es correcto?" en una fracción chica de prompts es barato. En tareas con oráculo CARO, ese
probe son unas pocas llamadas al verificador para CALIBRAR, y luego se usa el filtro endógeno (sin oráculo) en el
grueso. Aquí el valor demostrado es la SEGURIDAD (evitar el colapso del CYCLE 60) y el MECANISMO de decisión.

DISEÑO (reusa exp046). DOS regímenes de base: FUERTE (calibrado) y DÉBIL (mal calibrado). 4 brazos:
  - verified (EXTERNO en todo), self_consistency (ENDÓGENO en todo, sin gate), naive (sin filtro),
  - GATED: cada ronda, en un probe_frac de prompts estima calib_est (frac de consistentes cuyo valor==target);
    si calib_est >= umbral usa self_consistency (ENDÓGENO) en todo; si no, cae a verified (EXTERNO) en todo.
Métrica: real_acc media-rondas por brazo; del GATED, fracción de rondas que eligió ENDÓGENO y oracle_frac (cuánto
verificador usó). 3 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el GATED es ROBUSTO en AMBOS regímenes: en FUERTE elige ENDÓGENO y NO pierde vs self_consistency
    (real >= self_consistency - margen) usando POCO verificador; en DÉBIL elige EXTERNO y EVITA el colapso de
    self_consistency (real >> self_consistency) igualando a verified (real >= verified - margen). => el agente
    que estima su propia calibración nunca colapsa: endógeno barato cuando es confiable, externo seguro cuando no.
  - REFUTADA si el GATED elige mal (endógeno en débil -> colapsa, o externo en fuerte -> no ahorra) o no mejora
    sobre el peor de los dos filtros fijos.
  - MIXTA si decide bien en un régimen pero no en el otro.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp047_gated_self_verifier.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp047_gated_self_verifier.run            # FULL
"""
import argparse
import copy
import json
import math
import os
import platform
import sys

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm
from cognia_x.experiments.exp037_iterated_real_verifier.run import LO, HI
from cognia_x.experiments.exp046_self_consistency_verifier.run import filter_self_consistency, _target

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["verified", "self_consistency", "gated", "naive"]
REGIMES = {"strong": 250, "weak": 150}        # fuerte ~0.63 (calib ~0.76) / débil ~0.18 (calib ~0.3-0.54, recuperable por el externo)


def _filter_verified(pool):
    return [(p, e) for (p, e, w, s) in pool if s]


def _estimate_calibration(pool, prompts_probe, tau):
    """Estima la calibración de la auto-consistencia SÓLO en los prompts del probe (frac de consistentes cuyo
    valor mayoritario == target). Devuelve calib_est."""
    from collections import Counter, defaultdict
    by_prompt = defaultdict(list)
    probe_set = set(prompts_probe)
    for (p, e, w, s) in pool:
        if bytes(p) in probe_set:
            by_prompt[bytes(p)].append(bytes(e))
    n_cons = n_corr = 0
    for p, exprs in by_prompt.items():
        vals = []
        for e in exprs:
            v, has_op, ok = E.interpret(E.emitted_expr(e + b"\n"))
            if ok and has_op:
                vals.append(v)
        if not vals:
            continue
        maj_val, maj_cnt = Counter(vals).most_common(1)[0]
        if maj_cnt / len(exprs) >= tau:
            n_cons += 1
            if maj_val == _target(p):
                n_corr += 1
    return n_corr / max(1, n_cons)


def filter_gated(pool, tau, calib_threshold, probe_frac, probe_rng):
    """El agente DECIDE: estima su calibración en un probe; si es alta usa endógeno (self_consistency), si no cae
    al externo (verified). Devuelve (kept, info)."""
    prompts = list({bytes(p) for (p, e, w, s) in pool})
    n_probe = max(1, int(probe_frac * len(prompts)))
    idx = probe_rng.choice(len(prompts), size=min(n_probe, len(prompts)), replace=False)
    probe_prompts = [prompts[i] for i in idx]
    calib_est = _estimate_calibration(pool, probe_prompts, tau)
    if calib_est >= calib_threshold:
        kept, _ = filter_self_consistency(pool, tau)
        return kept, {"calib_est": round(calib_est, 4), "mode": "endogenous", "oracle_frac": probe_frac}
    else:
        return _filter_verified(pool), {"calib_est": round(calib_est, 4), "mode": "external", "oracle_frac": 1.0}


def run_seed(seed, base_steps, args, train_targets, test_targets, log, tag):
    base, npar = build_base(seed, args.n_seed, base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    rng = np.random.default_rng(seed + 7)
    sel = rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    probe_rng = np.random.default_rng(seed + 4242)

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: [round(bm["real_acc"], 4)] for a in ARMS}
    gated_modes = []
    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temperature, args.top_k, "cpu")
            if a == "verified":
                ex = _filter_verified(pool)
            elif a == "self_consistency":
                ex, _ = filter_self_consistency(pool, args.tau)
            elif a == "gated":
                ex, info = filter_gated(pool, args.tau, args.calib_threshold, args.probe_frac, probe_rng)
                gated_modes.append(info)
            else:
                ex = [(p, e) for (p, e, w, s) in pool]
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", np.random.default_rng(98000 + r))
            hist[a].append(round(E.eval_metrics(arms[a], test_targets, "cpu")["real_acc"], 4))
    frac_endo = float(np.mean([1.0 if g["mode"] == "endogenous" else 0.0 for g in gated_modes]))
    oracle_frac = float(np.mean([g["oracle_frac"] for g in gated_modes]))
    log(f"[exp047] {tag} seed={seed} base={bm['real_acc']:.3f} -> verified={hist['verified'][-1]:.3f} "
        f"self_cons={hist['self_consistency'][-1]:.3f} gated={hist['gated'][-1]:.3f} naive={hist['naive'][-1]:.3f} "
        f"| gated_endo={frac_endo:.2f} oracle_frac={oracle_frac:.2f} calib_est={np.mean([g['calib_est'] for g in gated_modes]):.2f}")
    return {"seed": seed, "base": round(bm["real_acc"], 4), "hist": hist, "frac_endo": round(frac_endo, 4),
            "oracle_frac": round(oracle_frac, 4)}


def regime_stats(per_seed):
    def fmean(a):
        return round(float(np.mean([np.mean(s["hist"][a][1:]) for s in per_seed])), 4)
    return {"base": round(float(np.mean([s["base"] for s in per_seed])), 4),
            "verified": fmean("verified"), "self_consistency": fmean("self_consistency"),
            "gated": fmean("gated"), "naive": fmean("naive"),
            "frac_endo": round(float(np.mean([s["frac_endo"] for s in per_seed])), 4),
            "oracle_frac": round(float(np.mean([s["oracle_frac"] for s in per_seed])), 4)}


def build_summary(strong, weak, m):
    margin = round(2 * math.sqrt(0.25 / max(1, m)), 4)
    S, W = regime_stats(strong), regime_stats(weak)
    # FUERTE: el gated elige ENDÓGENO y no pierde vs self_consistency, usando poco verificador.
    strong_chooses_endo = S["frac_endo"] >= 0.6 and S["oracle_frac"] <= 0.5
    strong_no_loss = S["gated"] >= S["self_consistency"] - margin
    # DÉBIL: el gated elige EXTERNO, evita el colapso de self_consistency y matchea a verified.
    weak_chooses_ext = W["frac_endo"] <= 0.4
    weak_avoids_collapse = (W["gated"] - W["self_consistency"]) > margin
    weak_matches_verified = W["gated"] >= W["verified"] - margin

    if strong_chooses_endo and strong_no_loss and weak_chooses_ext and weak_avoids_collapse and weak_matches_verified:
        status = "apoyada"
        verdict = ("H-V4-2j APOYADA: el GATING EXPLÍCITO cierra la unificación — el agente DECIDE cuándo confiar "
                   "en su auto-consistencia por su propia calibración estimada y es ROBUSTO en AMBOS regímenes. "
                   "FUERTE (calib alta): elige ENDÓGENO {se:.0f}% de las rondas (oracle_frac {sof:.2f}) y NO "
                   "pierde (gated {sg:.3f} vs self_cons {ssc:.3f}, verified {sv:.3f}) -> verificación barata sin "
                   "oráculo. DÉBIL (mal calib): elige EXTERNO {we:.0f}% (oracle_frac {wof:.2f}), EVITA el colapso "
                   "de self_consistency (gated {wg:.3f} >> self_cons {wsc:.3f}) e iguala a verified {wv:.3f}. => "
                   "el agente que estima su calibración NUNCA colapsa: endógeno cuando es confiable, externo "
                   "cuando no.").format(se=S["frac_endo"] * 100, sof=S["oracle_frac"], sg=S["gated"],
                                        ssc=S["self_consistency"], sv=S["verified"], we=(1 - W["frac_endo"]) * 100,
                                        wof=W["oracle_frac"], wg=W["gated"], wsc=W["self_consistency"], wv=W["verified"])
    elif (S["gated"] >= S["self_consistency"] - margin) and (W["gated"] - W["self_consistency"] > margin):
        status = "mixta"
        verdict = ("H-V4-2j MIXTA: el gated evita el colapso en débil (gated {wg:.3f} vs self_cons {wsc:.3f}) y no "
                   "pierde en fuerte (gated {sg:.3f} vs self_cons {ssc:.3f}), pero la decisión por régimen no es "
                   "del todo limpia (fuerte endo {se:.0f}%, débil endo {we:.0f}%).").format(
                       wg=W["gated"], wsc=W["self_consistency"], sg=S["gated"], ssc=S["self_consistency"],
                       se=S["frac_endo"] * 100, we=W["frac_endo"] * 100)
    else:
        status = "refutada"
        verdict = ("H-V4-2j REFUTADA: el gated no es robusto -- no evita el colapso en débil (gated {wg:.3f} vs "
                   "self_cons {wsc:.3f}) o pierde en fuerte (gated {sg:.3f} vs self_cons {ssc:.3f}).").format(
                       wg=W["gated"], wsc=W["self_consistency"], sg=S["gated"], ssc=S["self_consistency"])

    return {"margin": margin, "strong": S, "weak": W, "strong_chooses_endo": bool(strong_chooses_endo),
            "strong_no_loss": bool(strong_no_loss), "weak_chooses_ext": bool(weak_chooses_ext),
            "weak_avoids_collapse": bool(weak_avoids_collapse), "weak_matches_verified": bool(weak_matches_verified),
            "n_seeds": len(strong), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--K", type=int, default=6)
    ap.add_argument("--pool", type=int, default=256)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--top_k", type=int, default=20)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--tau", type=float, default=0.5)
    ap.add_argument("--calib_threshold", type=float, default=0.65)   # confiar en self-consistency sólo si >=65% de consistentes son correctos
    ap.add_argument("--probe_frac", type=float, default=0.15)
    ap.add_argument("--n_seed", type=int, default=256)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps = "0,1", 3, 128, 80

    torch.set_num_threads(3)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")
    logs = []

    def log(m):
        print(m, flush=True); logs.append(m); logf.write(m + "\n"); logf.flush()

    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    log(f"[exp047] CYCLE 62 / H-V4-2j — GATING EXPLÍCITO: el agente decide cuándo confiar en su auto-consistencia")
    log(f"[exp047] regímenes={REGIMES} rounds={args.rounds} tau={args.tau} calib_thr={args.calib_threshold} "
        f"probe_frac={args.probe_frac} seeds={seeds}")

    results = {}
    for name, bs in REGIMES.items():
        results[name] = [run_seed(s, bs, args, train_targets, test_targets, log, name.upper()) for s in seeds]

    sm = build_summary(results["strong"], results["weak"], len(test_targets))
    log(f"[exp047] FUERTE: {sm['strong']}")
    log(f"[exp047] DÉBIL : {sm['weak']}")
    log(f"[exp047] VEREDICTO H-V4-2j: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp047_gated_self_verifier", "cycle": 62, "hypothesis": "H-V4-2j",
           "claim": "el agente que estima su propia calibración decide cuándo confiar en su auto-consistencia y es "
                    "robusto en ambos regímenes (endógeno barato calibrado, externo seguro mal-calibrado)",
           "verdict": sm["status"], "summary": sm, "args": vars(args), "regimes": results,
           "task_range": [LO, HI],
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp047] escrito {os.path.join(RESULTS, 'results.json')}")
    logf.close()


if __name__ == "__main__":
    main()
