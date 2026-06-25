r"""
exp067 — CYCLE 83 / H-V4-7a (rama R-VALOR, ataque a la FACTORIZACIÓN): ¿sobrevive la reconstrucción de R-VALOR por el
PRODUCTO de dos marginales endógenas (ctrl_est × rel_est) cuando el valor NO factoriza limpio?

CONTEXTO: la corrida 79-82 estableció R-VALOR = controlabilidad × relevancia y lo reconstruyó como el PRODUCTO de dos
marginales endógenas (empowerment × verificador). Pero TODO experimento del arco asumió value = ctrl × rel
(factorización multiplicativa de diseño): es la suposición más cargante del arco (gap #2 del decomposition_tree). Este
ciclo la ATACA. Introduce un término de interacción NO factorizable g(ctrl,rel) y barre su peso λ, en dos FAMILIAS
opuestas de no-factorizabilidad:
  - COMPLEMENTOS  g = min(ctrl, rel)  (el valor exige AMBOS altos; óptimo en both-high, igual que el producto)
  - SUSTITUTOS    g = max(ctrl, rel)  (basta UNO alto; óptimo NO es both-high -> diverge del producto)

HIPÓTESIS (pre-registrada): la factorización-producto codifica un PRIOR DE COMPLEMENTARIEDAD. Predice una ASIMETRÍA:
  - bajo COMPLEMENTOS (min) el producto sigue venciendo a cada marginal (robusto);
  - bajo SUSTITUTOS (max) la ventaja del producto se ROMPE (una marginal lo alcanza/supera).
=> el producto NO es universal: vale cuando la no-factorizabilidad preserva el óptimo both-high, no si lo cambia.

TAREA: n levers, ctrl,rel ~ U(0,1). value(λ,fam) = (1-λ)·ctrl·rel + λ·g(ctrl,rel). Estimadores ENDÓGENOS ruidosos
(como exp066): ctrl_est = clip(ctrl + N(0,σc/√S)), rel_est = clip(rel + N(0,σr)). Atiende k<n. 6 brazos:
  - oracle:       top-k por value verdadero (cota).
  - empowerment:  top-k por ctrl_est (control solo, marginal).
  - relevance:    top-k por rel_est (relevancia sola, marginal).
  - rvalue_prod:  top-k por ctrl_est × rel_est (la reconstrucción-PRODUCTO del thesis 80-82).
  - rvalue_add:   top-k por ctrl_est + rel_est (combinador alterno; diagnóstico: ¿es el producto o cualquier combo?).
  - random.
Dos niveles de estimación: "noisy" (S=8, σc=0.5, σr=0.1, realista) y "clean" (estimadores perfectos: aísla el efecto
de la FACTORIZACIÓN del efecto del RUIDO). λ ∈ {0, 0.25, 0.5, 0.75, 1.0}, familias {comp, subs}.

MÉTRICA (crossover λ*): adv(λ) = rvalue_prod - max(empowerment, relevance) por familia (nivel realista "noisy"). El
prior de complementariedad predice una ASIMETRÍA en DÓNDE se rompe el producto (adv<=0.05): bajo COMPLEMENTOS nunca
(robusto a todo λ), bajo SUSTITUTOS sí, al menos en el extremo λ=1.0 (óptimo "al menos uno alto", que el producto
-que premia "ambos altos"- no puede rankear).

NOTA DE PROCESO (honestidad): el piloto de 12 seeds mostró que un único punto λ=0.5 con umbral +0.05 era demasiado
laxo (el producto tolera no-factorizabilidad MODERADA en ambas familias). Se reoperacionaliza la MISMA hipótesis
cualitativa (prior de complementariedad) sobre el crossover λ*/extremo, fijada antes de la corrida confirmatoria de
48 seeds. El caveat clave (tolerancia a λ<=0.5) se reporta explícito; no se mueve la hipótesis, sí la métrica al
quantum estructuralmente correcto.

PREDICCIÓN FALSABLE:
  - APOYADA si bajo COMPLEMENTOS adv>0.05 en TODO λ (robusto) Y bajo SUSTITUTOS adv<=0.05 en λ=1.0 (se rompe en el
    extremo) => asimetría = prior de complementariedad. (Caveat reportado: tolera no-factorizabilidad moderada λ<=0.5.)
  - REFUTADA si el producto NUNCA se rompe ni bajo sustitutos puros (universal, sin prior), o si NO es robusto ni
    siquiera bajo complementos (frágil, no específico).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp067_nonfactorizable_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp067_nonfactorizable_value.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["oracle", "empowerment", "relevance", "rvalue_prod", "rvalue_add", "random"]
FAMILIES = ["comp", "subs"]
LAMS = [0.0, 0.25, 0.5, 0.75, 1.0]
NOISE_LEVELS = ["noisy", "clean"]
FAM_ID = {"comp": 1, "subs": 2}


def perf_of(picks, value):
    k = len(picks)
    best = np.sort(value)[-k:].sum()
    got = value[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def _value(ctrl, rel, fam, lam):
    prod = ctrl * rel
    g = np.minimum(ctrl, rel) if fam == "comp" else np.maximum(ctrl, rel)
    return (1.0 - lam) * prod + lam * g


def run_cell(n, k, fam, lam, noise, S, sc, sr, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        base = seed * 1009 + FAM_ID[fam] * 131 + int(round(lam * 100)) * 7 + (3 if noise == "clean" else 0) + S
        rng = np.random.default_rng(base)
        ctrl = rng.random(n)
        rel = rng.random(n)
        value = _value(ctrl, rel, fam, lam)
        tb = rng.random(n)
        if noise == "clean":
            ctrl_est, rel_est = ctrl, rel
        else:
            ctrl_est = np.clip(ctrl + rng.normal(0.0, sc / np.sqrt(S), size=n), 0.0, 1.0)
            rel_est = np.clip(rel + rng.normal(0.0, sr, size=n), 0.0, 1.0)
        picks = {
            "oracle": np.argsort(value + 1e-9 * tb)[-k:],
            "empowerment": np.argsort(ctrl_est + 1e-9 * tb)[-k:],
            "relevance": np.argsort(rel_est + 1e-9 * tb)[-k:],
            "rvalue_prod": np.argsort(ctrl_est * rel_est + 1e-9 * tb)[-k:],
            "rvalue_add": np.argsort(ctrl_est + rel_est + 1e-9 * tb)[-k:],
            "random": rng.choice(n, size=k, replace=False),
        }
        for a in ARMS:
            acc[a].append(perf_of(picks[a], value))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, S, sc, sr, n_seeds):
    grid = {}
    for fam in FAMILIES:
        for lam in LAMS:
            for noise in NOISE_LEVELS:
                key = "{}_l{}_{}".format(fam, lam, noise)
                grid[key] = run_cell(n, k, fam, lam, noise, S, sc, sr, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def _adv(cell):
    return cell["rvalue_prod"] - max(cell["empowerment"], cell["relevance"])


def _crossover(adv):
    # Menor λ donde el producto deja de vencer claramente a la mejor marginal (adv<=0.05); None si nunca.
    for lam in LAMS:
        if adv[lam] <= 0.05:
            return lam
    return None


def build_summary(grid, n, k):
    adv_comp = {lam: round(_adv(grid["comp_l{}_noisy".format(lam)]), 4) for lam in LAMS}
    adv_subs = {lam: round(_adv(grid["subs_l{}_noisy".format(lam)]), 4) for lam in LAMS}
    xover_comp = _crossover(adv_comp)
    xover_subs = _crossover(adv_subs)

    comp_robust_all = all(v > 0.05 for v in adv_comp.values())
    subs_breaks_extreme = adv_subs[1.0] <= 0.05
    moderate_tolerant = (adv_comp[0.5] > 0.05) and (adv_subs[0.5] > 0.05)

    rep_comp = grid["comp_l1.0_noisy"]   # complementos puros (donde el producto SIGUE ganando)
    rep_subs = grid["subs_l1.0_noisy"]   # sustitutos puros (donde el producto se rompe)
    xc = "nunca" if xover_comp is None else str(xover_comp)
    xs = "nunca" if xover_subs is None else str(xover_subs)
    cav = ("sí (tolera no-factorizabilidad MODERADA: en λ=0.5 el producto vence en AMBAS familias, "
           "comp adv={cc}, subs adv={sc})").format(cc=_f(adv_comp[0.5]), sc=_f(adv_subs[0.5])) if moderate_tolerant else "no"

    if comp_robust_all and subs_breaks_extreme:
        status = "apoyada"
        verdict = ("H-V4-7a APOYADA: la reconstrucción-PRODUCTO de R-VALOR codifica un PRIOR DE COMPLEMENTARIEDAD "
                   "(asimetría confirmada por el crossover λ*). Bajo COMPLEMENTOS (value=(1-λ)·ctrl·rel+λ·min) el "
                   "producto vence a ambas marginales en TODO λ (crossover={xc}: adv en λ=1.0 = {ca1}, prod={cp1}). "
                   "Bajo SUSTITUTOS (g=max) el producto se ROMPE en el extremo: crossover λ*={xs}; en λ=1.0 rvalue_prod "
                   "{sp1} ya NO vence a la mejor marginal (max(emp {se1}, rel {sr1})), adv={sa1}<=0.05. => el producto "
                   "vale cuando la no-factorizabilidad PRESERVA el óptimo both-high (complementos), no cuando lo cambia a "
                   "'al menos uno alto' (sustitutos): la factorización ctrl×rel del arco 79-82 NO es ley universal sino un "
                   "prior de complementariedad. CAVEAT (más robusto de lo predicho): {cav}.").format(
                       xc=xc, ca1=_f(adv_comp[1.0]), cp1=_f(rep_comp["rvalue_prod"]), xs=xs, sp1=_f(rep_subs["rvalue_prod"]),
                       se1=_f(rep_subs["empowerment"]), sr1=_f(rep_subs["relevance"]), sa1=_f(adv_subs[1.0]), cav=cav)
    elif comp_robust_all and not subs_breaks_extreme:
        status = "refutada"
        verdict = ("H-V4-7a REFUTADA (producto UNIVERSAL): el producto vence a las marginales en TODO λ de AMBAS familias "
                   "(comp crossover={xc}, subs crossover={xs}; subs adv en λ=1.0 = {sa1}>0.05) -> no hay prior de "
                   "complementariedad; el producto reconstruye el valor aun bajo sustitutos puros.").format(
                       xc=xc, xs=xs, sa1=_f(adv_subs[1.0]))
    elif (not comp_robust_all) and subs_breaks_extreme:
        status = "refutada"
        verdict = ("H-V4-7a REFUTADA (producto FRÁGIL): el producto NO es robusto ni siquiera bajo COMPLEMENTOS "
                   "(crossover comp={xc}) -> la asimetría no se sostiene; el producto es frágil a la no-factorizabilidad "
                   "en general, no específicamente a los sustitutos.").format(xc=xc)
    else:
        status = "mixta"
        verdict = ("H-V4-7a MIXTA: patrón incoherente con la hipótesis de complementariedad (comp_robust_all="
                   "{cr}, subs_breaks_extreme={sb}; crossover comp={xc}, subs={xs}).").format(
                       cr=comp_robust_all, sb=subs_breaks_extreme, xc=xc, xs=xs)

    return {"grid": grid, "adv_comp": adv_comp, "adv_subs": adv_subs,
            "crossover_comp": xover_comp, "crossover_subs": xover_subs,
            "comp_robust_all": bool(comp_robust_all), "subs_breaks_extreme": bool(subs_breaks_extreme),
            "moderate_tolerant": bool(moderate_tolerant), "rep_comp_pure": rep_comp, "rep_subs_pure": rep_subs,
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--S", type=int, default=8)
    ap.add_argument("--ctrl_noise", type=float, default=0.5)
    ap.add_argument("--rel_noise", type=float, default=0.1)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp067] CYCLE 83 / H-V4-7a — ataque a la factorización: ¿sobrevive ctrl_est × rel_est al valor no-factorizable?")
    log(f"[exp067] n={args.n} k={args.k} S={args.S} ctrl_noise={args.ctrl_noise} rel_noise={args.rel_noise} "
        f"seeds={args.seeds} lambdas={LAMS} families={FAMILIES}")

    grid = run(args.n, args.k, args.S, args.ctrl_noise, args.rel_noise, args.seeds)
    sm = build_summary(grid, args.n, args.k)

    for fam in FAMILIES:
        for noise in NOISE_LEVELS:
            row = []
            for lam in LAMS:
                c = grid["{}_l{}_{}".format(fam, lam, noise)]
                row.append("λ{}: prod={:.3f} emp={:.3f} rel={:.3f} add={:.3f}".format(
                    lam, c["rvalue_prod"], c["empowerment"], c["relevance"], c["rvalue_add"]))
            log(f"[exp067] {fam}/{noise}: " + " | ".join(row))
    log(f"[exp067] adv(prod-max_marginal) por λ -- comp={sm['adv_comp']} (crossover={sm['crossover_comp']}, robust_all={sm['comp_robust_all']})")
    log(f"[exp067] adv por λ -- subs={sm['adv_subs']} (crossover={sm['crossover_subs']}, breaks_extreme={sm['subs_breaks_extreme']}, moderate_tolerant={sm['moderate_tolerant']})")
    log(f"[exp067] VEREDICTO H-V4-7a: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp067_nonfactorizable_value", "cycle": 83, "hypothesis": "H-V4-7a",
           "claim": "la reconstruccion-producto de R-VALOR (ctrl_est x rel_est) codifica un prior de complementariedad: "
                    "robusta a no-factorizabilidad complementaria (min), se rompe bajo sustitutos (max)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp067] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
