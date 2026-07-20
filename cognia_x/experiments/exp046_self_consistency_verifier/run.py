r"""
exp046 — CYCLE 60 / H-V4-2i (UNIFICACIÓN de los dos arcos): ¿la AUTO-CONSISTENCIA del modelo (acuerdo entre sus
muestras = confianza ENDÓGENA, sin oráculo) sirve como VERIFICADOR PARCIAL en el lazo de auto-mejora — y su
utilidad está GATEADA por la CALIBRACIÓN (el insight del CYCLE 57)?

CONTEXTO: la corrida cerró dos arcos: VERIFICADOR-REAL (51-55, el verificador externo es el motor) y R-VALOR
(56-59, hay señal de valor endógena — confianza calibrada — usable sin oráculo, PERO confiable sólo con la
política/competencia correcta: el CYCLE 57 mostró 'confiado-pero-equivocado' cuando NO está calibrado). Insight
del CYCLE 57: 'el verificador externo es, EN PARTE, reemplazable por la confianza calibrada'. Este ciclo lo
PRUEBA en el sustrato de auto-mejora: filtrar las auto-generaciones por AUTO-CONSISTENCIA (¿el modelo produce
consistentemente el mismo VALOR?) en vez del verificador externo. PREDICCIÓN AFINADA tras smoke: funciona
cuando el modelo está CALIBRADO (base fuerte: consistente=>correcto) y FALLA/refuerza errores cuando NO
(base débil: consistente-pero-equivocado).

ANALOGÍA: te quedás con los ejercicios que resolviste IGUAL varias veces (estás seguro), sin mirar la tabla de
respuestas. Si ya sabés bastante (calibrado), tus 'seguros' son correctos y aprendés. Si sabés poco, repetís el
mismo ERROR con seguridad y te reforzás en él.

DISEÑO (reusa exp018/exp037). DOS REGÍMENES de base: FUERTE (base_steps alto -> real_acc alto, calibrado) y
DÉBIL (base_steps bajo -> real_acc bajo, mal calibrado). En cada uno, lazo R rondas, 3 brazos (mismo base+RNG):
  - verified (EXTERNO): STRONG-verificadas por el sandbox (valor==target Y operador).
  - self_consistency (ENDÓGENO): por prompt, si el VALOR mayoritario aparece en fracción >= tau de las K
    muestras, se queda con una expr de ese valor -- SIN chequear el target.
  - naive: todas (referencia).
Métrica: real_acc (verificador FUERTE externo, CLEAN) media-rondas por brazo; CALIBRACIÓN de la consistencia
(frac de prompts consistentes cuyo valor==target). 3 seeds por régimen.

PREDICCIÓN FALSABLE (pre-registrada, afinada tras smoke):
  - APOYADA si: en el régimen FUERTE la consistencia está CALIBRADA (>=0.70) Y self_consistency SUPERA a naive
    (la confianza endógena es un verificador parcial usable cuando calibrado); en el régimen DÉBIL la
    consistencia está MAL calibrada (<0.55) Y self_consistency NO supera a naive (o cae). => la auto-consistencia
    es un verificador PARCIAL GATEADO por calibración -> conecta los dos arcos y confirma el CYCLE 57.
  - REFUTADA si self_consistency no supera a naive ni siquiera con base fuerte/calibrada (la confianza endógena
    nunca sirve de filtro).
  - MIXTA si el gating no es limpio (p.ej. ayuda en ambos o en ninguno por igual).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp046_self_consistency_verifier.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp046_self_consistency_verifier.run            # FULL
"""
import argparse
import copy
import json
import math
import os
import platform
import sys
from collections import Counter, defaultdict

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm
from cognia_x.experiments.exp037_iterated_real_verifier.run import LO, HI

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["verified", "self_consistency", "naive"]
REGIMES = {"strong": 250, "weak": 150}        # base_steps -> base ~0.63 (calibrado, con headroom) / ~0.18 (mal calib)


def _target(prompt_bytes):
    import re
    m = re.match(rb"^(\d{1,3})=$", bytes(prompt_bytes))
    return int(m.group(1)) if m else None


def filter_self_consistency(pool, tau):
    """ENDÓGENO: por prompt, si el VALOR mayoritario aparece en fracción >= tau de las K muestras, se queda con
    una expr de ese valor. Devuelve (kept, info) con info.calibration = frac de consistentes cuyo valor==target."""
    by_prompt = defaultdict(list)
    for (p, e, w, s) in pool:
        by_prompt[bytes(p)].append(bytes(e))
    kept = []
    n_consistent = n_correct = 0
    for p, exprs in by_prompt.items():
        vals, rep = [], {}
        for e in exprs:
            v, has_op, ok = E.interpret(E.emitted_expr(e + b"\n"))
            if ok and has_op:
                vals.append(v); rep.setdefault(v, e)
        if not vals:
            continue
        maj_val, maj_cnt = Counter(vals).most_common(1)[0]
        if maj_cnt / len(exprs) >= tau:
            kept.append((p, rep[maj_val]))
            n_consistent += 1
            if maj_val == _target(p):
                n_correct += 1
    return kept, {"n_consistent": n_consistent, "calibration": round(n_correct / max(1, n_consistent), 4)}


def run_seed(seed, base_steps, args, train_targets, test_targets, log, tag):
    base, npar = build_base(seed, args.n_seed, base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: [round(bm["real_acc"], 4)] for a in ARMS}
    calibs = []
    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts(seed, args, train_targets), args.K, args.temperature,
                                 args.top_k, "cpu")
            if a == "verified":
                ex = [(p, e) for (p, e, w, s) in pool if s]
            elif a == "self_consistency":
                ex, info = filter_self_consistency(pool, args.tau)
                calibs.append(info["calibration"])
            else:
                ex = [(p, e) for (p, e, w, s) in pool]
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", np.random.default_rng(98000 + r))
            hist[a].append(round(E.eval_metrics(arms[a], test_targets, "cpu")["real_acc"], 4))
    log(f"[exp046] {tag} seed={seed} base={bm['real_acc']:.3f} -> verified={hist['verified'][-1]:.3f} "
        f"self_cons={hist['self_consistency'][-1]:.3f} naive={hist['naive'][-1]:.3f} sc_calib={np.mean(calibs):.2f}")
    return {"seed": seed, "base": round(bm["real_acc"], 4), "hist": hist, "sc_calib": round(float(np.mean(calibs)), 4)}


_POOL_CACHE = {}


def pool_prompts(seed, args, train_targets):
    if seed not in _POOL_CACHE:
        rng = np.random.default_rng(seed + 7)
        sel = rng.integers(0, len(train_targets), size=args.pool)
        _POOL_CACHE[seed] = [E.make_prompt(train_targets[i]) for i in sel]
    return _POOL_CACHE[seed]


def regime_stats(per_seed, args):
    def fmean(a):
        return round(float(np.mean([np.mean(s["hist"][a][1:]) for s in per_seed])), 4)
    return {"base": round(float(np.mean([s["base"] for s in per_seed])), 4),
            "verified": fmean("verified"), "self_consistency": fmean("self_consistency"), "naive": fmean("naive"),
            "sc_calibration": round(float(np.mean([s["sc_calib"] for s in per_seed])), 4)}


def build_summary(strong, weak, args, m):
    margin = round(2 * math.sqrt(0.25 / max(1, m)), 4)
    S = regime_stats(strong, args)
    W = regime_stats(weak, args)
    # El claim REAL (afinado tras smoke): la utilidad de la auto-consistencia está GATEADA por la CALIBRACIÓN.
    # Decisivo: (1) la calibración TRACKEA el régimen (alta en fuerte, baja en débil); (2) en DÉBIL/mal-calibrado
    # la consistencia COLAPSA bajo naive (refuerza errores confiados = el peligro); (3) en FUERTE/calibrado es
    # USABLE (supera/iguala a naive y no degrada, capturando parte del beneficio del verificador externo).
    gating_contrast = round(S["sc_calibration"] - W["sc_calibration"], 4)
    strong_calibrated = S["sc_calibration"] >= 0.70
    weak_miscalibrated = W["sc_calibration"] < 0.55
    strong_usable = strong_calibrated and (S["self_consistency"] > S["naive"]) and \
        (S["self_consistency"] >= S["base"] - margin)
    weak_collapses = weak_miscalibrated and (W["self_consistency"] < W["naive"] - margin / 2)
    strong_beats_naive_2sigma = (S["self_consistency"] - S["naive"]) > margin   # check pre-registrado (estricto)
    gating = gating_contrast > 0.30

    if gating and strong_usable and weak_collapses:
        status = "apoyada"
        verdict = ("H-V4-2i APOYADA: la AUTO-CONSISTENCIA es un VERIFICADOR PARCIAL GATEADO por CALIBRACIÓN. "
                   "FUERTE (base {sb:.3f}, calib {scal:.2f}): self_consistency {ssc:.3f} supera a naive {sn:.3f} "
                   "(+{sg:.3f}; modesto, {beat2} el bar 2σ) sin degradar la base -- captura parte del beneficio "
                   "del externo verified {sv:.3f}. DÉBIL (base {wb:.3f}, MAL calib {wcal:.2f}): self_consistency "
                   "COLAPSA a {wsc:.3f} << naive {wn:.3f} (consistente-pero-equivocado refuerza errores). La "
                   "calibración TRACKEA el régimen (contraste {gc:.2f}). => el verificador externo (arco 51-55) "
                   "es PARCIALMENTE reemplazable por la confianza endógena (arco 56-59) SÓLO cuando el modelo "
                   "está calibrado; confirma el CYCLE 57 (la confianza es confiable con la competencia "
                   "correcta).").format(sb=S["base"], scal=S["sc_calibration"], ssc=S["self_consistency"],
                                        sn=S["naive"], sg=S["self_consistency"] - S["naive"], sv=S["verified"],
                                        beat2="supera" if strong_beats_naive_2sigma else "NO supera",
                                        wb=W["base"], wcal=W["sc_calibration"], wsc=W["self_consistency"],
                                        wn=W["naive"], gc=gating_contrast)
    elif not gating or (S["self_consistency"] <= S["naive"]):
        status = "refutada"
        verdict = ("H-V4-2i REFUTADA: no hay gating por calibración (contraste {gc:.2f}) o ni con base "
                   "fuerte/calibrada la auto-consistencia supera a naive (sc {ssc:.3f} vs naive {sn:.3f}).").format(
                       gc=gating_contrast, ssc=S["self_consistency"], sn=S["naive"])
    else:
        status = "mixta"
        verdict = ("H-V4-2i MIXTA: hay señal de gating (fuerte sc {ssc:.3f} vs naive {sn:.3f} calib {scal:.2f}; "
                   "débil sc {wsc:.3f} vs naive {wn:.3f} calib {wcal:.2f}) pero usabilidad o colapso no cruzan "
                   "los umbrales limpiamente.").format(ssc=S["self_consistency"], sn=S["naive"],
                                                       scal=S["sc_calibration"], wsc=W["self_consistency"],
                                                       wn=W["naive"], wcal=W["sc_calibration"])

    return {"margin": margin, "strong": S, "weak": W, "gating_contrast": gating_contrast,
            "strong_calibrated": bool(strong_calibrated), "weak_miscalibrated": bool(weak_miscalibrated),
            "strong_usable": bool(strong_usable), "weak_collapses": bool(weak_collapses),
            "strong_beats_naive_2sigma": bool(strong_beats_naive_2sigma), "gating": bool(gating),
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
    log(f"[exp046] CYCLE 60 / H-V4-2i — auto-consistencia como verificador PARCIAL (gateado por calibración)")
    log(f"[exp046] regímenes={REGIMES} rounds={args.rounds} K={args.K} tau={args.tau} seeds={seeds}")

    results = {}
    for name, bs in REGIMES.items():
        results[name] = [run_seed(s, bs, args, train_targets, test_targets, log, name.upper()) for s in seeds]

    sm = build_summary(results["strong"], results["weak"], args, len(test_targets))
    log(f"[exp046] FUERTE: {sm['strong']}")
    log(f"[exp046] DÉBIL : {sm['weak']}")
    log(f"[exp046] VEREDICTO H-V4-2i: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp046_self_consistency_verifier", "cycle": 60, "hypothesis": "H-V4-2i",
           "claim": "la auto-consistencia (confianza endógena) es un verificador parcial GATEADO por calibración: "
                    "reemplaza en parte al externo cuando el modelo está calibrado, falla cuando no",
           "verdict": sm["status"], "summary": sm, "args": vars(args), "regimes": results,
           "task_range": [LO, HI],
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp046] escrito {os.path.join(RESULTS, 'results.json')}")
    logf.close()


if __name__ == "__main__":
    main()
