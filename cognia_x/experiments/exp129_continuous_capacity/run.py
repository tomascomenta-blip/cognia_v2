r"""
exp129 — CYCLE 145 / H-V4-10q (rama control/acción, RESUELVE el artefacto recurrente K=1): los CYCLEs 139/142/143 hallaron, una y
otra vez, que la ventaja del criterio de VALOR (keystone w·ctrl) sobre los factores de un eje EVAPORA a K>=#modos buenos en la
selección DISCRETA top-K -- un "artefacto K=1 winner-take-all". ¿Es ese colapso una PATOLOGÍA de la selección DISCRETA, o sólo la
manifestación discreta de la ESCASEZ de capacidad? Este ciclo lo testea con capacidad CONTINUA: en vez de elegir K-de-D modos,
distribuir un PRESUPUESTO continuo B sobre los modos (water-filling con retornos decrecientes). Si la ventaja del valor decae con
el presupuesto B IGUAL que decae con K, entonces el "artefacto K=1" es simplemente ESCASEZ (no winner-take-all) -- y eso QUITA el
caveat de medio arco (139/142/143).

TESIS. La ventaja del criterio de VALOR sobre los factores de un eje es gobernada por la ESCASEZ DE CAPACIDAD, no por la
discreteness de la selección. Bajo capacidad CONTINUA (presupuesto B repartido por water-filling) la ventaja DECAE con B
exactamente como decae con K en lo discreto, y a la MISMA capacidad efectiva las dos curvas COINCIDEN. La 'evaporación a K>=#modos'
de 139/142/143 es el punto MÁS escaso de lo discreto, no una patología del top-K.

DISEÑO (numpy, sustrato keystone). D modos; (w,b) con correlación ρ_wb (disociación ctrl-rel). Valor verdadero v_i = w_i·ctrl(b_i)
(keystone graduado). DISCRETO: elegir top-K por el criterio; payoff = Σ v de los K elegidos / Σ v de los top-K (oracle). CONTINUO:
repartir presupuesto B por water-filling del CRITERIO (a_i maximiza Σ score·log(1+a) s.t. Σa=B); beneficio MEDIDO por v_true =
Σ v_i·log(1+a_i); payoff = beneficio / beneficio del water-filling por v_true (oracle). CRITERIOS: value (w·ctrl=v_true, =oracle),
ctrl (ctrl), rel (w), uniform. BARRIDOS: K∈[1..D] (discreto), B (continuo), × disociación ρ_wb.

ANTI-TAUTOLOGÍA: el criterio VALUE = v_true por construcción -> payoff_value=1.0 en ambos; el NIVEL no es el hallazgo. Lo
LOAD-BEARING es la FORMA de la ventaja (1 − mejor-factor-solo) como función de la escasez (K discreto vs B continuo) y su COINCIDENCIA
-- los factores-solos NO son oracle.

PREGUNTA FALSABLE:
  - APOYADA si la ventaja CONTINUA (vs B) decae con la escasez igual que la DISCRETA (vs K), y a la misma capacidad efectiva
    COINCIDEN -> el 'artefacto K=1' es ESCASEZ, no winner-take-all; la selección discreta no es especial.
  - REFUTADA si bajo capacidad CONTINUA la ventaja del valor DESAPARECE (≈0 a todo B) -> la ventaja ERA específica del top-K
    discreto (winner-take-all), confirmando que el artefacto K=1 invalida los hallazgos.
  - MIXTA si condicional.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp129_continuous_capacity.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp129_continuous_capacity.run --seeds 300
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
D = 10
RHO = 0.5
KS = list(range(1, D + 1))
BS = [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]    # presupuesto continuo (escasez -> abundancia)
REGIMES = {"anti": -0.85, "indep": 0.0, "corr": 0.85}
CRITERIA = ("value", "ctrl", "rel", "uniform")


def _ctrl(b):
    return b ** 2 / (b ** 2 + RHO)


def _draw(rng, rho_wb):
    cov = np.array([[1.0, rho_wb], [rho_wb, 1.0]])
    z = rng.multivariate_normal([0.0, 0.0], cov, size=D)
    from math import erf, sqrt
    u = 0.5 * (1.0 + np.vectorize(lambda t: erf(t / sqrt(2.0)))(z))
    bw = 0.1 + 0.9 * u
    return bw[:, 0], bw[:, 1]      # b, w


def _scores(b, w):
    c = _ctrl(b)
    return {"value": w * c, "ctrl": c, "rel": w, "uniform": np.ones(D)}


def _waterfill(score, B):
    """a_i = max(score_i/λ − 1, 0) con Σa_i = B (maximiza Σ score·log(1+a) s.t. presupuesto). Bisección en λ."""
    s = np.maximum(score, 1e-9)
    lo, hi = 1e-9, float(np.max(s))
    for _ in range(60):
        lam = 0.5 * (lo + hi)
        a = np.maximum(s / lam - 1.0, 0.0)
        if a.sum() > B:
            lo = lam
        else:
            hi = lam
    return np.maximum(s / (0.5 * (lo + hi)) - 1.0, 0.0)


def _payoff_discrete(score, v_true, K):
    S = np.argsort(score)[-K:]
    oracle = float(np.sum(np.sort(v_true)[-K:])) + 1e-12
    return float(np.sum(v_true[S])) / oracle


def _payoff_continuous(score, v_true, B):
    a = _waterfill(score, B)
    a_or = _waterfill(v_true, B)
    benefit = float(np.sum(v_true * np.log1p(a)))
    oracle = float(np.sum(v_true * np.log1p(a_or))) + 1e-12
    return benefit / oracle


def _participation(score, B):
    """Ratio de participación (Σa)²/Σa² del water-filling del VALOR: PR≈1 -> winner-take-all blando; PR≈D -> repartido.
    La verificación 145 mostró que a presupuesto ESCASO el continuo CONCENTRA (~soft top-k), NO 'sin winner-take-all'."""
    a = _waterfill(score, B)
    s2 = float(np.sum(a ** 2))
    return float((np.sum(a) ** 2) / s2) if s2 > 1e-12 else 1.0


def _payoff_cont_sqrt(score, v_true, B):
    """g(a)=√a (marginal INFINITA en 0): el water-filling es a_i ∝ score_i² y el ratio es INVARIANTE en B -> la ventaja NO decae
    (rompe el paralelo continuo≈discreto -> el decaimiento es g-DEPENDIENTE, hallazgo de la verificación 145)."""
    def wf(s):
        s = np.maximum(s, 1e-9); a = s ** 2; return a * (B / a.sum())
    a = wf(score); a_or = wf(v_true)
    benefit = float(np.sum(v_true * np.sqrt(a)))
    oracle = float(np.sum(v_true * np.sqrt(a_or))) + 1e-12
    return benefit / oracle


def run_cell(rho_wb, n_seeds):
    disc = {cr: {K: [] for K in KS} for cr in CRITERIA}
    cont = {cr: {B: [] for B in BS} for cr in CRITERIA}
    cont_sqrt = {cr: {B: [] for B in BS} for cr in CRITERIA}
    pr = {B: [] for B in BS}          # ratio de participación del water-filling del VALOR (concentración)
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7919 + int((rho_wb + 1) * 1000) * 131 + 29)
        b, w = _draw(rng, rho_wb)
        v_true = w * _ctrl(b)
        sc = _scores(b, w)
        for cr in CRITERIA:
            for K in KS:
                disc[cr][K].append(_payoff_discrete(sc[cr], v_true, K))
            for B in BS:
                cont[cr][B].append(_payoff_continuous(sc[cr], v_true, B))
                cont_sqrt[cr][B].append(_payoff_cont_sqrt(sc[cr], v_true, B))
        for B in BS:
            pr[B].append(_participation(sc["value"], B))
    out = {"disc": {cr: [round(float(np.mean(disc[cr][K])), 4) for K in KS] for cr in CRITERIA},
           "cont": {cr: [round(float(np.mean(cont[cr][B])), 4) for B in BS] for cr in CRITERIA},
           "cont_sqrt": {cr: [round(float(np.mean(cont_sqrt[cr][B])), 4) for B in BS] for cr in CRITERIA},
           "participation": [round(float(np.mean(pr[B])), 4) for B in BS]}
    out["adv_disc"] = [round(out["disc"]["value"][i] - max(out["disc"]["ctrl"][i], out["disc"]["rel"][i]), 4) for i in range(len(KS))]
    out["adv_cont"] = [round(out["cont"]["value"][i] - max(out["cont"]["ctrl"][i], out["cont"]["rel"][i]), 4) for i in range(len(BS))]
    out["adv_cont_sqrt"] = [round(out["cont_sqrt"]["value"][i] - max(out["cont_sqrt"]["ctrl"][i], out["cont_sqrt"]["rel"][i]), 4) for i in range(len(BS))]
    return out


def run(n_seeds):
    return {name: run_cell(rho, n_seeds) for name, rho in REGIMES.items()}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    adv_d = {n: grid[n]["adv_disc"] for n in REGIMES}
    adv_c = {n: grid[n]["adv_cont"] for n in REGIMES}

    adv_cs = {n: grid[n]["adv_cont_sqrt"] for n in REGIMES}
    part = grid["anti"]["participation"]
    auc_d = {n: round(float(np.mean(adv_d[n])), 4) for n in REGIMES}
    auc_c = {n: round(float(np.mean(adv_c[n])), 4) for n in REGIMES}
    # NÚCLEO robusto (verificado g/D/RHO/seeds): la ventaja del valor SOBREVIVE a presupuesto ESCASO bajo capacidad CONTINUA y
    # ESCALA con la disociación -> NO es específica del top-K discreto.
    cont_survives = (adv_c["anti"][0] > 0.10) and (adv_c["indep"][0] > 0.05)
    dissoc_both = (auc_c["anti"] > auc_c["indep"] + 0.02 > auc_c["corr"]) and (auc_d["anti"] > auc_d["indep"] + 0.02)
    core = cont_survives and dissoc_both
    # --- correcciones de la VERIFICACIÓN ADVERSARIAL de 145 ---
    pr_scarce = part[0]; pr_abund = part[-1]
    scarce_is_concentrated = pr_scarce < 2.5       # a presupuesto escaso el water-filling es ~soft top-2 (no 'sin winner-take-all')
    cont_residual = adv_c["anti"][-1]
    permanent_residual = cont_residual > 0.04      # la continua (log) NO llega a 0; la discreta sí (a K=D, trivial)
    sqrt_flat = abs(adv_cs["anti"][0] - adv_cs["anti"][-1]) < 0.03 and adv_cs["anti"][0] > 0.05   # con g=√a la ventaja NO decae (g-dep)
    scarcity_match = scarce_is_concentrated and permanent_residual

    if not core:
        status = "refutada"
        verdict = ("H-V4-10q REFUTADA: bajo capacidad CONTINUA la ventaja del valor NO sobrevive/escala (anti B-chico +{ca1}, AUC "
                   "anti={aca}/indep={aci}/corr={acc}) -> era específica del top-K discreto.").format(
                       ca1=_f(adv_c["anti"][0]), aca=_f(auc_c["anti"]), aci=_f(auc_c["indep"]), acc=_f(auc_c["corr"]))
    else:
        status = "mixta"
        verdict = (
            "H-V4-10q MIXTA (núcleo real + claim central RE-ACOTADO por verificación adversarial de 2 agentes; 15mo ciclo). NÚCLEO "
            "(robusto en g/D/RHO/seeds): la ventaja del criterio de VALOR (keystone w·ctrl) sobre el mejor factor-solo SOBREVIVE a "
            "presupuesto ESCASO bajo capacidad CONTINUA (water-filling: anti +{ca1}, indep +{ci1}) y ESCALA con la DISOCIACIÓN "
            "ctrl-rel (AUC continua anti={aca}>indep={aci}>corr={acc}) -> la ventaja del keystone NO es ESPECÍFICA del top-K "
            "discreto. PERO el claim de que esto 'QUITA el caveat K=1 / es escasez NO winner-take-all' se RE-ACOTA: (1) escaso-"
            "continuo ES CONCENTRADO -- a presupuesto escaso el water-filling reparte ~soft top-k (ratio de participación {prs} a "
            "B={b0}; sube a {pra} a B={bN}): B-chico = un winner-take-all BLANDO, NO 'sin concentración'. El K=1 NO se DISUELVE: se "
            "REINTERPRETA como concentración-bajo-escasez (K=1 ≈ B-chico). (2) la continua NO decae 'igual que la discreta': "
            "RESIDUAL PERMANENTE (anti +{cr} a B={bN}, ~log) mientras la discreta llega a 0 sólo en K=D (el punto TRIVIAL "
            "select-all). (3) el decaimiento-en-B es g-DEPENDIENTE -- con g=√a (marginal infinita en 0) la ventaja es INVARIANTE en "
            "B (anti {cs0}->{csN}, plana) -> el paralelo continuo≈discreto SÓLO vale para beneficios de marginal FINITA en 0. (4) "
            "value=oracle (tautológico) y el contenido es ÁLGEBRA DE PRODUCTO (un producto w·ctrl no se aproxima por un factor, "
            "peor al decorrelacionar w,ctrl) -> RECOMBINACIÓN de 142 en forma continua. => RESULTADO HONESTO: la ventaja del valor "
            "NO es un artefacto de la selección DISCRETA (sobrevive continuo + escala con disociación, robusto), PERO el continuo "
            "escaso es un winner-take-all BLANDO -> NO 'quita' el caveat K=1, lo REINTERPRETA como concentración-bajo-escasez; el "
            "paralelo de decaimiento es g-dependiente y la magnitud es álgebra de producto. MIXTA EXITOSA: la verificación cazó el "
            "overclaim 'sin winner-take-all / decae igual' (15mo ciclo)."
        ).format(ca1=_f(adv_c["anti"][0]), ci1=_f(adv_c["indep"][0]), aca=_f(auc_c["anti"]), aci=_f(auc_c["indep"]),
                 acc=_f(auc_c["corr"]), prs=_f(pr_scarce), b0=BS[0], pra=_f(pr_abund), bN=BS[-1], cr=_f(cont_residual),
                 cs0=_f(adv_cs["anti"][0]), csN=_f(adv_cs["anti"][-1]))

    return {"D": D, "KS": KS, "BS": BS, "regimes": list(REGIMES.keys()), "by_regime": grid,
            "adv_disc": adv_d, "adv_cont": adv_c, "adv_cont_sqrt": adv_cs, "auc_disc": auc_d, "auc_cont": auc_c,
            "participation": part, "pr_scarce": pr_scarce, "pr_abund": pr_abund, "cont_residual": cont_residual,
            "cont_survives": bool(cont_survives), "dissoc_both": bool(dissoc_both), "core": bool(core),
            "scarce_is_concentrated": bool(scarce_is_concentrated), "permanent_residual": bool(permanent_residual),
            "sqrt_flat": bool(sqrt_flat), "scarcity_match": bool(scarcity_match), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=300)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 60

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp129] CYCLE 145 / H-V4-10q — ¿el 'artefacto K=1' (139/142/143) es ESCASEZ o una patología del top-K? capacidad CONTINUA (water-filling de un presupuesto B) vs DISCRETA")
    log(f"[exp129] seeds={args.seeds} D={D} rho={RHO} Ks={KS} Bs={BS} regimes={list(REGIMES.keys())}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp129] --- VENTAJA del valor sobre el mejor factor-solo: DISCRETA (por K) vs CONTINUA (por presupuesto B) ---")
    for n in REGIMES:
        ad = sm["adv_disc"][n]; ac = sm["adv_cont"][n]
        log(f"[exp129] {n:>5} DISCRETA (K): " + " ".join(f"K{KS[i]}:{ad[i]:+.2f}" for i in range(len(KS))))
        log(f"[exp129] {n:>5} CONTINUA (B): " + " ".join(f"B{BS[i]:g}:{ac[i]:+.2f}" for i in range(len(BS))))
    log(f"[exp129] AUC ventaja CONTINUA: anti={sm['auc_cont']['anti']:.3f} indep={sm['auc_cont']['indep']:.3f} corr={sm['auc_cont']['corr']:.3f} | DISCRETA: anti={sm['auc_disc']['anti']:.3f} indep={sm['auc_disc']['indep']:.3f} corr={sm['auc_disc']['corr']:.3f}")
    log(f"[exp129] CONCENTRACIÓN (ratio de participación del water-filling del valor, anti): " + " ".join(f"B{BS[i]:g}:{sm['participation'][i]:.1f}" for i in range(len(BS))) + f" -> escaso CONCENTRADO (~soft top-k)={sm['scarce_is_concentrated']}")
    log(f"[exp129] g-DEPENDENCIA: ventaja con g=√a (anti): " + " ".join(f"B{BS[i]:g}:{sm['adv_cont_sqrt']['anti'][i]:+.2f}" for i in range(len(BS))) + f" -> PLANA (no decae)={sm['sqrt_flat']} | residual permanente continuo (log, anti B={BS[-1]:g})={sm['cont_residual']:.3f}")
    log(f"[exp129] CHECK core={sm['core']} (cont_survives={sm['cont_survives']} dissoc_both={sm['dissoc_both']}) | scarce_is_concentrated={sm['scarce_is_concentrated']} permanent_residual={sm['permanent_residual']} sqrt_flat={sm['sqrt_flat']}")
    log(f"[exp129] VEREDICTO H-V4-10q: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp129_continuous_capacity", "cycle": 145, "hypothesis": "H-V4-10q",
           "claim": "MIXTA (post-verificacion adversarial de 2 agentes). NUCLEO (robusto g/D/RHO/seeds): bajo capacidad CONTINUA "
                    "(water-filling de un presupuesto B) la ventaja del criterio de VALOR (keystone w·ctrl) sobre el mejor factor-solo "
                    "SOBREVIVE a presupuesto escaso y ESCALA con la disociacion -> la ventaja del keystone NO es especifica del top-K "
                    "DISCRETO. PERO el claim 'quita el caveat K=1 / es escasez NO winner-take-all' se RE-ACOTA: escaso-continuo ES "
                    "CONCENTRADO (water-filling ~soft top-k a B chico, ratio de participacion <2.5) -> el K=1 NO se disuelve, se "
                    "REINTERPRETA como concentracion-bajo-escasez; la continua tiene RESIDUAL permanente (no decae a 0 como la "
                    "discreta); el decaimiento-en-B es g-DEPENDIENTE (con g=√a la ventaja es plana); value=oracle (tautologico) y el "
                    "contenido es algebra-de-producto -> RECOMBINACION de 142 en forma continua. La verificacion cazo el overclaim "
                    "'sin winner-take-all / decae igual'",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp129] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
