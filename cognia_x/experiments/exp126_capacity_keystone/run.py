r"""
exp126 — CYCLE 142 / H-V4-10n (rama control/acción, EJE DE CAPACIDAD del keystone): ¿cómo escala la ventaja del PRODUCTO R-VALOR
(valor=ctrl×rel, keystone 129) sobre los factores de un solo eje con la CAPACIDAD K del agente? CYCLE 139 reveló (de pasada) que
K=1 era load-bearing -- el gap del keystone evaporaba a K≥2 en el sustrato cíclico. Este ciclo lo ESTUDIA sistemáticamente sobre el
sustrato canónico del keystone (129/130): barre K de 1 a D y mide la ventaja del producto sobre el mejor factor-solo, × la
correlación ctrl-rel (la 'disociación' de 130).

TESIS. El R-VALOR (el producto ctrl×rel) importa bajo ESCASEZ -- aquí, escasez de CAPACIDAD. A K=1 (modelar/regular UN solo modo)
hay que elegir EL mejor, y ambos factores son esenciales -> el producto bate fuerte a cada factor solo. A K→D (capacidad para
todo) cualquier criterio captura los modos buenos -> la ventaja del producto se DESVANECE (no hay que priorizar). La ventaja
DECAE con K, y su tasa de decaimiento depende de la DISOCIACIÓN ctrl-rel: bajo ANTI-correlación (lo controlable ≠ lo relevante) un
factor solo falla feo y la ventaja persiste a K más alto; bajo correlación los factores casi bastan y la ventaja es chica ya a K=1.

DISEÑO (numpy, sustrato keystone de 129/130). D modos; (b,w) graduados con correlación ρ_bw controlada (anti/indep/corr). Costo de
control cuadrático ρ. Valor-de-decisión verdadero de regular el modo i = w_i·b_i²/(b_i²+ρ) (cost-aware, 130). CRITERIOS de
selección de los K modos:
  - product (= keystone/oracle por construcción): w·b²/(b²+ρ).
  - ctrl_only: b²/(b²+ρ).      - rel_only: w.      - random.
Payoff(K, criterio) = Σ valor-verdadero de los K elegidos / Σ valor-verdadero de los top-K (oracle). VENTAJA(K) = payoff_product
(=1.0) − max(payoff_ctrl, payoff_rel). Barridos: K∈[1..D] × ρ_bw∈{anti,indep,corr}.

ANTI-TAUTOLOGÍA: el producto = oracle por construcción (payoff_product=1.0), así que el NIVEL no es el hallazgo. Lo LOAD-BEARING es
la FORMA de la VENTAJA sobre los factores-solos como función de K (¿decae? ¿hasta qué K persiste?) y su dependencia de la
disociación -- los factores-solos NO son oracle y su payoff(K) es lo que se mide.

PREGUNTA FALSABLE:
  - APOYADA si la ventaja del producto DECAE monótona con K y se DESVANECE cerca de K=D, Y la tasa de decaimiento escala con la
    disociación (anti persiste a K más alto que corr). => el R-VALOR (producto) importa bajo escasez de CAPACIDAD; con capacidad
    holgada cualquier factor basta.
  - REFUTADA si la ventaja es K-INDEPENDIENTE (el producto bate por el mismo margen a todo K) -> la capacidad no modula el valor.
  - MIXTA si condicional (decae pero no se desvanece, o no depende de la disociación).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp126_capacity_keystone.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp126_capacity_keystone.run --seeds 300
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
D = 12
RHO = 0.5
KS = list(range(1, D + 1))
REGIMES = {"anti": -0.85, "indep": 0.0, "corr": 0.85}    # correlación objetivo entre b y w (disociación ctrl-rel)
CRITERIA = ("product", "ctrl_only", "rel_only", "random")
BINARY = False                                            # validity-probe: (b,w) binarios INVIERTEN el orden (frágil a la marginal)


def _ctrl(b):
    return b ** 2 / (b ** 2 + RHO)


def _draw_bw(rng, rho_bw):
    """Dibuja (b, w) con correlación objetivo rho_bw vía una cópula gaussiana. GRADUADO (uniforme en (0.05,1.0)) por defecto;
    si BINARY, b,w ∈ {0.05,1.0} -> la verificación adversarial mostró que esto INVIERTE el orden anti<indep (validity-limit:
    el resultado vale para marginales GRADUADAS, el régimen canónico del keystone 130, no para binarias 129)."""
    cov = np.array([[1.0, rho_bw], [rho_bw, 1.0]])
    z = rng.multivariate_normal([0.0, 0.0], cov, size=D)
    from math import erf, sqrt
    u = 0.5 * (1.0 + np.vectorize(lambda t: erf(t / sqrt(2.0)))(z))
    if BINARY:
        return np.where(u[:, 0] > 0.5, 1.0, 0.05), np.where(u[:, 1] > 0.5, 1.0, 0.05)
    bw = 0.05 + 0.95 * u
    return bw[:, 0], bw[:, 1]


def _scores(b, w):
    c = _ctrl(b)
    return {"product": w * c, "ctrl_only": c, "rel_only": w}


def _payoff_at_K(score, v_true, K):
    order = np.argsort(score)[-K:]
    oracle = float(np.sum(np.sort(v_true)[-K:])) + 1e-12
    return float(np.sum(v_true[order])) / oracle


def run_cell(rho_bw, n_seeds):
    # payoff[criterio][K-1] promediado sobre seeds
    acc = {cr: {K: [] for K in KS} for cr in CRITERIA}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7919 + int((rho_bw + 1) * 1000) * 131 + 17)
        b, w = _draw_bw(rng, rho_bw)
        v_true = w * _ctrl(b)
        sc = _scores(b, w)
        for K in KS:
            for cr in ("product", "ctrl_only", "rel_only"):
                acc[cr][K].append(_payoff_at_K(sc[cr], v_true, K))
            # random: media sobre varias selecciones aleatorias
            rs = [float(np.sum(v_true[rng.choice(D, K, replace=False)])) / (float(np.sum(np.sort(v_true)[-K:])) + 1e-12)
                  for _ in range(8)]
            acc["random"][K].append(float(np.mean(rs)))
    out = {cr: [round(float(np.mean(acc[cr][K])), 4) for K in KS] for cr in CRITERIA}
    # ventaja del producto sobre el MEJOR factor-solo, por K
    out["advantage"] = [round(out["product"][i] - max(out["ctrl_only"][i], out["rel_only"][i]), 4) for i in range(len(KS))]
    return out


def run(n_seeds):
    grid = {name: run_cell(rho, n_seeds) for name, rho in REGIMES.items()}
    # VALIDITY-PROBE (verificación adversarial): con (b,w) BINARIO el orden anti>indep se INVIERTE -> el resultado vale sólo para
    # marginales GRADUADAS. Se computa toggleando el global BINARY.
    global BINARY
    BINARY = True
    grid["_binary_anti"] = run_cell(REGIMES["anti"], n_seeds)
    grid["_binary_indep"] = run_cell(REGIMES["indep"], n_seeds)
    BINARY = False
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    adv = {name: grid[name]["advantage"] for name in REGIMES}
    PRESENT = 0.10        # umbral para considerar que HAY ventaja a K=1 (regímenes disociados)

    def decays(a):
        # monótona no-creciente con tolerancia de ruido, y termina ~0, desde un valor inicial NO-trivial
        viol = sum(1 for i in range(1, len(a)) if a[i] > a[i - 1] + 0.04)
        return viol <= 1 and a[-1] < 0.04 and a[0] > a[-1] + 0.15

    dissoc_regs = [n for n in REGIMES if adv[n][0] >= PRESENT]
    decays_where_present = len(dissoc_regs) >= 2 and all(decays(adv[n]) for n in dissoc_regs)
    auc = {name: round(float(np.mean(adv[name])), 4) for name in REGIMES}
    dissoc_scales = auc["anti"] > auc["indep"] + 0.03 and auc["indep"] > auc["corr"] + 0.03

    def kstar(a):
        for i, v in enumerate(a):
            if v < 0.05:
                return KS[i]
        return D
    kst = {name: kstar(adv[name]) for name in REGIMES}
    kst_rel = {name: round(kst[name] / float(D), 3) for name in REGIMES}   # K* RELATIVO a D (verificación: K*≈0.7·D, no absoluto)

    # --- correcciones de la VERIFICACIÓN ADVERSARIAL de 142 ---
    # (1) TRIVIALIDAD: la (1−payoff) de RANDOM también decae a ~0 en K=D -> 'decae con K / vanishes@D' es genérico de la métrica
    #     top-K, NO keystone-específico. El contenido NO-trivial es adv(K=1) (el mis-ranking de un-factor) y la pendiente interior.
    rand_decay = {name: round((1.0 - grid[name]["random"][0]) - (1.0 - grid[name]["random"][-1]), 4) for name in REGIMES}
    random_also_decays = all((1.0 - grid[name]["random"][-1]) < 0.04 for name in REGIMES)
    # (2) FORMA UNIVERSAL: las curvas de ventaja anti/indep normalizadas por adv(K=1) son ~idénticas -> el eje-K aporta UNA forma
    #     universal; lo regime-específico es el NIVEL adv(K=1) = la disociación de 130 (RECOMBINACIÓN, no mecanismo nuevo).
    na = np.array(adv["anti"]) / (adv["anti"][0] + 1e-9); ni = np.array(adv["indep"]) / (adv["indep"][0] + 1e-9)
    universal_shape_maxdiff = round(float(np.max(np.abs(na - ni))), 4)
    is_recombination = universal_shape_maxdiff < 0.10
    # (3) VALIDITY-LIMIT: con (b,w) BINARIO el orden anti>indep se INVIERTE -> sólo vale para marginales GRADUADAS
    bauc_anti = round(float(np.mean(grid["_binary_anti"]["advantage"])), 4)
    bauc_indep = round(float(np.mean(grid["_binary_indep"]["advantage"])), 4)
    binary_inverts = bauc_anti <= bauc_indep + 0.01
    core_organizing = decays_where_present and dissoc_scales and (kst["anti"] >= kst["indep"] >= kst["corr"])

    if not core_organizing:
        status = "refutada"
        verdict = ("H-V4-10n REFUTADA: el núcleo organizador no se sostiene (decays={dc} dissoc_scales={ds} K* anti={ka}/indep={ki}/"
                   "corr={kc}).").format(dc=decays_where_present, ds=dissoc_scales, ka=kst["anti"], ki=kst["indep"], kc=kst["corr"])
    else:
        status = "mixta"
        verdict = (
            "H-V4-10n MIXTA (núcleo organizador real + novedad/especificidad acotada por verificación adversarial de 2 agentes). "
            "NÚCLEO (robusto en el régimen GRADUADO, verificado en D/RHO/seeds/correlación-fina): el R-VALOR (producto ctrl×rel, "
            "keystone 129) importa bajo DOS escaseces que INTERACTÚAN -- la ventaja del producto sobre el mejor factor-solo es "
            "grande sólo a CAPACIDAD escasa (K bajo) Y factores DISOCIADOS (ctrl≠rel); AUC anti={aa} > indep={ai} > corr={ac} "
            "(monótona y SUAVE en ρ_bw); K* (capacidad a la que un factor basta) anti={ka}/indep={ki}/corr={kc} = RELATIVO a D "
            "(K*≈{krela}·D, no absoluto); explica el K=1-load-bearing de 139. NO SOBREVIVE (retractado): (1) 'decae con K / se "
            "desvanece a K=D' es PARCIALMENTE TRIVIAL -- la (1−payoff) de la selección ALEATORIA también decae a ~0 en K=D "
            "(random_also_decays={rad}, decaimiento {rd}): a K=D se eligen TODOS los modos -> payoff=1 por construcción para "
            "cualquier criterio; el contenido NO-trivial es adv(K=1) y la pendiente interior, no el endpoint. (2) RECOMBINACIÓN, "
            "no mecanismo nuevo: las curvas de ventaja anti/indep NORMALIZADAS por adv(K=1) son ~idénticas (max-diff {usm}) -> el "
            "eje-K aporta UNA forma universal de decaimiento; lo regime-específico es sólo el NIVEL adv(K=1) = el mis-ranking de "
            "un-factor de la DISOCIACIÓN (130). El aporte es la SÍNTESIS (escasez 123-126 × disociación 130 interactúan + explica "
            "139), no un mecanismo nuevo. (3) VALIDITY-LIMIT: vale para (b,w) GRADUADOS (el régimen canónico del keystone 130) -- "
            "con (b,w) BINARIOS el orden anti>indep se INVIERTE (binario AUC anti={baa} <= indep={bai}). => MIXTA: la síntesis "
            "organizadora de los dos ejes de escasez es real y robusta en el régimen graduado, pero es una recombinación (no "
            "novel), el decaimiento-en-K es parcialmente trivial (lo comparte el azar), K* es relativo, y el orden se invierte "
            "bajo marginal binaria. Aporte: el cuadro unificado capacidad×disociación + la explicación del K=1-load-bearing de 139."
        ).format(aa=_f(auc["anti"]), ai=_f(auc["indep"]), ac=_f(auc["corr"]), ka=kst["anti"], ki=kst["indep"], kc=kst["corr"],
                 krela=_f(kst_rel["anti"]), rad=random_also_decays, rd=_f(rand_decay["anti"]), usm=_f(universal_shape_maxdiff),
                 baa=_f(bauc_anti), bai=_f(bauc_indep))

    return {"D": D, "KS": KS, "regimes": list(REGIMES.keys()), "by_regime": grid, "advantage": adv, "auc_advantage": auc,
            "kstar": kst, "kstar_rel": kst_rel, "dissoc_regimes": dissoc_regs,
            "decays_where_present": bool(decays_where_present), "dissoc_scales": bool(dissoc_scales),
            "rand_decay": rand_decay, "random_also_decays": bool(random_also_decays),
            "universal_shape_maxdiff": universal_shape_maxdiff, "is_recombination": bool(is_recombination),
            "binary_auc_anti": bauc_anti, "binary_auc_indep": bauc_indep, "binary_inverts": bool(binary_inverts),
            "core_organizing": bool(core_organizing), "status": status, "verdict": verdict}


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

    log("[exp126] CYCLE 142 / H-V4-10n — ¿la ventaja del PRODUCTO R-VALOR (ctrl×rel) sobre los factores-solos DECAE con la CAPACIDAD K (el valor importa bajo escasez de capacidad)?")
    log(f"[exp126] seeds={args.seeds} D={D} rho={RHO} Ks={KS} regimes={list(REGIMES.keys())}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp126] --- VENTAJA del producto sobre el mejor factor-solo, por capacidad K y disociación ---")
    for name in REGIMES:
        a = sm["advantage"][name]
        log(f"[exp126] {name:>5} (ρ_bw={REGIMES[name]:+.2f}): " + " ".join(f"K{KS[i]}:{a[i]:+.2f}" for i in range(len(KS))))
        log(f"[exp126]        product={' '.join(_f(x) for x in grid[name]['product'])}")
        log(f"[exp126]        ctrl   ={' '.join(_f(x) for x in grid[name]['ctrl_only'])}")
        log(f"[exp126]        rel    ={' '.join(_f(x) for x in grid[name]['rel_only'])}")
    log(f"[exp126] AUC ventaja: anti={sm['auc_advantage']['anti']:.3f} indep={sm['auc_advantage']['indep']:.3f} corr={sm['auc_advantage']['corr']:.3f} | K* (un factor basta) abs={sm['kstar']} rel(K*/D)={sm['kstar_rel']}")
    log(f"[exp126] TRIVIALIDAD: random (1-payoff) también decae a ~0 en K=D (random_also_decays={sm['random_also_decays']}, decaim anti={sm['rand_decay']['anti']:.3f}) -> 'decae/vanishes@D' es genérico de top-K, no keystone-específico")
    log(f"[exp126] FORMA UNIVERSAL: curvas anti/indep normalizadas por adv(K=1) max-diff={sm['universal_shape_maxdiff']:.3f} -> recombinación={sm['is_recombination']} (el eje-K aporta UNA forma; lo regime-específico es adv(K=1)=disociación de 130)")
    log(f"[exp126] VALIDITY-LIMIT: (b,w) BINARIO AUC anti={sm['binary_auc_anti']:.3f} indep={sm['binary_auc_indep']:.3f} -> orden INVIERTE={sm['binary_inverts']} (sólo vale para (b,w) GRADUADOS)")
    log(f"[exp126] CHECK core_organizing={sm['core_organizing']} decays_where_present={sm['decays_where_present']} (disociados={sm['dissoc_regimes']}) dissoc_scales={sm['dissoc_scales']} | random_also_decays={sm['random_also_decays']} is_recombination={sm['is_recombination']} binary_inverts={sm['binary_inverts']}")
    log(f"[exp126] VEREDICTO H-V4-10n: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp126_capacity_keystone", "cycle": 142, "hypothesis": "H-V4-10n",
           "claim": "MIXTA (post-verificacion adversarial de 2 agentes). NUCLEO (robusto en el regimen GRADUADO): el R-VALOR "
                    "(producto ctrl×rel, keystone 129) importa bajo DOS escaseces que INTERACTUAN -- la ventaja del producto sobre "
                    "el mejor factor-solo es grande solo a CAPACIDAD escasa (K bajo) Y factores DISOCIADOS (ctrl!=rel); AUC anti > "
                    "indep > corr (monotona y suave en rho_bw); K* relativo a D (~0.7D); explica el K=1-load-bearing de 139. NO "
                    "SOBREVIVE: 'decae/vanishes@D' es parcialmente TRIVIAL (la (1-payoff) de random tambien decae a 0 en K=D); es "
                    "una RECOMBINACION no un mecanismo nuevo (las curvas anti/indep normalizadas por adv(K=1) son ~identicas -> el "
                    "eje-K es una forma universal, lo regime-especifico es adv(K=1)=disociacion de 130); VALIDITY-LIMIT: vale para "
                    "(b,w) GRADUADOS, con binarios el orden anti>indep se INVIERTE. Aporte: la sintesis capacidad×disociacion + la "
                    "explicacion del K=1-load-bearing de 139, no un mecanismo novel",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp126] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
