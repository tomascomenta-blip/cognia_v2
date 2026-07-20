r"""
exp077 — CYCLE 93 / H-V4-7i (rama R-VALOR, EL CAPSTONE del salto grande, gaps #1/#3): en un LAZO CERRADO de auto-mejora
con el GENERADOR de MODELO REAL (HybridLM de exp018) y un VERIFICADOR chequeable REAL (sandbox), cuando la verificación
es el CUELLO (presupuesto B ≪ pool), ¿asignar el presupuesto por la CONFIANZA ENDÓGENA del propio modelo (logprob de su
generación — la señal R-VALOR de CYCLE 57/60) rinde MÁS datos verificado-correctos por verificación y mejor auto-mejora
que asignar al azar?

CONTEXTO. El arco 83-92 desarrolló la política R-VALOR (combinador + asignación del feedback escaso) y la aterrizó en un
verificador REAL pero con candidatos SINTÉTICOS y feedback sin lazo secuencial cerrado. El verdadero SALTO GRANDE
(frontera tras 88-92): cerrar el lazo con el GENERADOR de MODELO REAL — el modelo GENERA candidatos, el sandbox los
VERIFICA, las verificado-correctas lo ENTRENAN, el modelo cambia (dinámica secuencial REAL). La señal R-VALOR para
asignar la verificación escasa es la CONFIANZA ENDÓGENA del modelo (su propia probabilidad sobre lo que generó), que el
lab ya mostró informativa cuando el modelo está calibrado (CYCLE 57/60).

DISEÑO (PyTorch CPU; reusa exp018: build_base, generate_pool, train_arm, eval_metrics, sandbox). Base DÉBIL + temp ALTA
→ el pool es un MIX (correctas / malformadas / echo / valor-mal), para que la asignación IMPORTE. Por ronda: el modelo
genera M candidatos; se computa la CONFIANZA (mean logprob de la expr emitida bajo el modelo, sin ejecutar). Presupuesto
B = budget_frac·M. Brazos (mismo base+RNG por seed; mismo B):
  - conf_alloc:   verifica el top-B por CONFIANZA del modelo, entrena con las strong-correctas.
  - random_alloc: verifica B al azar, entrena con las strong-correctas.
  - verify_all:   verifica TODAS (B=M) = techo de referencia (presupuesto infinito).
MÉTRICA PRIMARIA: YIELD = #strong-correctas halladas por ronda con B verificaciones (eficiencia de la asignación).
SECUNDARIA: real_acc held-out (efecto downstream en el lazo cerrado). Se reporta también corr(confianza, strong).

PREGUNTA FALSABLE:
  - APOYADA si conf_alloc YIELD > random_alloc por > margen en TODOS los seeds (la confianza endógena asigna mejor la
    verificación) Y su real_acc no regresiona — la confianza endógena (R-VALOR) mejora un lazo cerrado REAL.
  - REFUTADA si conf_alloc YIELD ≈ random_alloc (la confianza no discrimina correcto/incorrecto en este lazo).
  - MIXTA si mejora el yield pero no el downstream (o viceversa).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp077_closed_loop_budget.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp077_closed_loop_budget.run            # FULL
"""
import argparse
import copy
import json
import os
import platform
import sys

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm, LO, HI

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["conf_alloc", "random_alloc", "verify_all"]


@torch.no_grad()
def _confidence(model, pairs, device):
    """Confianza endógena por candidato = mean logprob de la expr emitida (+\\n) bajo el modelo, dado el prompt. NO
    ejecuta ni mira el target -> señal R-VALOR barata y endógena (cf. CYCLE 57/60)."""
    if not pairs:
        return np.zeros(0)
    model.eval()
    x, y = E.batch_from_examples(pairs, device)            # y = tokens supervisados (expr+\n), -100 en el resto
    logits, _ = model(x)
    logp = torch.log_softmax(logits, dim=-1)
    mask = (y != -100).float()
    tok_logp = logp.gather(-1, y.clamp(min=0).unsqueeze(-1)).squeeze(-1) * mask
    seq = tok_logp.sum(dim=1) / mask.sum(dim=1).clamp(min=1.0)
    model.train()
    return seq.cpu().numpy()


def _corr(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp077] seed={seed} base real_acc={bm['real_acc']:.3f} weak={bm['weak_acc']:.3f} deg={bm['degenerate']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    M = args.pool * args.K
    B = max(1, int(round(args.budget_frac * M)))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"real": [round(bm["real_acc"], 4)], "yield": [], "verified": []} for a in ARMS}
    corrs = []
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            n = len(pool)
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            if a == "verify_all":
                sel_idx = np.arange(n)
            elif a == "random_alloc":
                sel_idx = rng_a.choice(n, size=min(B, n), replace=False)
            else:  # conf_alloc: rankea por la CONFIANZA endógena del modelo
                conf = _confidence(arms[a], pairs, "cpu")
                if a == "conf_alloc" and r == 1:
                    corrs.append(round(_corr(conf, strong), 4))      # diagnóstico: ¿confianza predice strong?
                sel_idx = np.argsort(conf + 1e-9 * rng_a.random(n))[-min(B, n):]
            ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
            hist[a]["yield"].append(len(ex))
            hist[a]["verified"].append(int(len(sel_idx)))
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp077] seed={seed} ronda {r} (B={B}/{M}): "
            + " | ".join(f"{a}: yield={hist[a]['yield'][-1]}/{hist[a]['verified'][-1]} real={hist[a]['real'][-1]:.3f}" for a in ARMS))

    return {"seed": seed, "base": bm, "params": npar, "hist": hist, "B": B, "M": M,
            "conf_strong_corr": (corrs[0] if corrs else 0.0)}


def build_summary(per_seed):
    def mean_yield(a):
        return [sum(s["hist"][a]["yield"]) / len(s["hist"][a]["yield"]) for s in per_seed]

    def mean_real(a):
        return [sum(s["hist"][a]["real"][1:]) / len(s["hist"][a]["real"][1:]) for s in per_seed]

    cy, ny = mean_yield("conf_alloc"), mean_yield("random_alloc")
    cr, nr_ = mean_real("conf_alloc"), mean_real("random_alloc")
    va_y, va_r = mean_yield("verify_all"), mean_real("verify_all")
    nseed = len(per_seed)
    corrs = [s["conf_strong_corr"] for s in per_seed]

    yield_gain = round(float(np.mean(cy) - np.mean(ny)), 4)
    yield_all_pos = all(cy[i] > ny[i] for i in range(nseed))
    real_gain = round(float(np.mean(cr) - np.mean(nr_)), 4)
    real_not_worse = float(np.mean(cr)) >= float(np.mean(nr_)) - 0.02
    yield_margin = round(0.10 * max(1.0, float(np.mean(ny))), 4)
    mean_corr = round(float(np.mean(corrs)), 4)

    yield_better = (yield_gain > yield_margin) and yield_all_pos

    if yield_better and real_not_worse:
        status = "apoyada"
        verdict = ("H-V4-7i APOYADA: en el LAZO CERRADO con el GENERADOR de MODELO REAL + verificador real, asignar la "
                   "verificación por la CONFIANZA ENDÓGENA del modelo rinde MÁS datos correctos por verificación que al "
                   "azar: yield conf={cy:.2f} vs random={ny:.2f} (+{yg}, todos los {ns} seeds) a igual presupuesto "
                   "B={B}/{M}; corr(confianza,strong)={mc}. El downstream real_acc NO regresiona (conf={cr:.3f} vs "
                   "random={nr:.3f}, Δ={rg}; verify_all techo={var:.3f}). => la confianza endógena (R-VALOR, CYCLE "
                   "57/60) mejora un lazo de auto-mejora REAL cuando la verificación es el cuello.").format(
                       cy=float(np.mean(cy)), ny=float(np.mean(ny)), yg=yield_gain, ns=nseed, B=per_seed[0]["B"],
                       M=per_seed[0]["M"], mc=mean_corr, cr=float(np.mean(cr)), nr=float(np.mean(nr_)), rg=real_gain,
                       var=float(np.mean(va_r)))
    elif not yield_better:
        status = "refutada"
        verdict = ("H-V4-7i REFUTADA: asignar por confianza NO mejora el yield sobre al azar (conf={cy:.2f} vs "
                   "random={ny:.2f}, +{yg} <= margen {ym}, all_pos={ap}, corr={mc}) -> la confianza endógena no "
                   "discrimina correcto/incorrecto en este lazo.").format(
                       cy=float(np.mean(cy)), ny=float(np.mean(ny)), yg=yield_gain, ym=yield_margin,
                       ap=yield_all_pos, mc=mean_corr)
    else:
        status = "mixta"
        verdict = ("H-V4-7i MIXTA: yield_better={yb} (conf={cy:.2f} vs random={ny:.2f}, +{yg}, corr={mc}) pero "
                   "downstream real_acc {cr:.3f} vs {nr:.3f} (Δ={rg}) -> mejora la asignación pero no claramente el "
                   "downstream.").format(yb=yield_better, cy=float(np.mean(cy)), ny=float(np.mean(ny)), yg=yield_gain,
                                         mc=mean_corr, cr=float(np.mean(cr)), nr=float(np.mean(nr_)), rg=real_gain)

    return {"arms": ARMS, "n_seeds": nseed, "B": per_seed[0]["B"], "M": per_seed[0]["M"],
            "conf_strong_corr_by_seed": corrs, "mean_corr": mean_corr,
            "yield_conf_by_seed": [round(x, 3) for x in cy], "yield_random_by_seed": [round(x, 3) for x in ny],
            "yield_verify_all_by_seed": [round(x, 3) for x in va_y],
            "real_conf_by_seed": [round(x, 3) for x in cr], "real_random_by_seed": [round(x, 3) for x in nr_],
            "real_verify_all_by_seed": [round(x, 3) for x in va_r],
            "yield_gain": yield_gain, "yield_all_pos": bool(yield_all_pos), "yield_margin": yield_margin,
            "real_gain": real_gain, "real_not_worse": bool(real_not_worse), "yield_better": bool(yield_better),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.20)
    ap.add_argument("--temp", type=float, default=1.3)        # temp ALTA -> pool con MIX (la asignación importa)
    ap.add_argument("--top_k", type=int, default=0)           # 0 = sin top-k (más diversidad/errores)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--n_seed", type=int, default=200)
    ap.add_argument("--base_steps", type=int, default=250)    # base DÉBIL -> genera un MIX correcto/incorrecto
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()
    if args.top_k <= 0:
        args.top_k = None
    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 2, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log(f"[exp077] CYCLE 93 / H-V4-7i — LAZO CERRADO con MODELO REAL + asignación R-VALOR (confianza endógena) del presupuesto")
    log(f"[exp077] seeds={seeds} rango=[{LO},{HI}] train={len(train_targets)} test={len(test_targets)} rounds={args.rounds} "
        f"K={args.K} pool={args.pool} budget_frac={args.budget_frac} temp={args.temp} top_k={args.top_k} steps={args.steps} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp077] corr(confianza,strong) por seed={sm['conf_strong_corr_by_seed']} (media {sm['mean_corr']})")
    log(f"[exp077] YIELD/ronda (B={sm['B']}/{sm['M']}): conf={sm['yield_conf_by_seed']} random={sm['yield_random_by_seed']} verify_all={sm['yield_verify_all_by_seed']}")
    log(f"[exp077] real_acc media-rondas: conf={sm['real_conf_by_seed']} random={sm['real_random_by_seed']} verify_all={sm['real_verify_all_by_seed']}")
    log(f"[exp077] yield_gain=+{sm['yield_gain']:.3f} (all_pos={sm['yield_all_pos']}, margen {sm['yield_margin']}) | real_gain={sm['real_gain']:+.3f} (not_worse={sm['real_not_worse']})")
    log(f"[exp077] VEREDICTO H-V4-7i: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp077_closed_loop_budget", "cycle": 93, "hypothesis": "H-V4-7i",
           "claim": "en un lazo cerrado de auto-mejora con el generador de MODELO REAL + verificador real, asignar el "
                    "presupuesto de verificacion por la CONFIANZA ENDOGENA del modelo rinde mas datos verificado-"
                    "correctos por verificacion y no regresiona el downstream vs asignar al azar",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp077] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
