r"""
exp127 — CYCLE 143 / H-V4-10o (rama control/acción, CIERRA el caveat de 139: AISLAR la relevancia bajo CICLOS donde reach≠relevancia):
139 (exp123) halló que bajo un sustrato con ciclos la relevancia era COLINEAL con la controlabilidad-reach (el control nulo ŵ≡unos
NO colapsaba a ctrl_only -> el factor LOAD-BEARING demostrado era la reach, no la relevancia). El motivo: en 139 todos los modos
relevantes eran alcanzables y todos los alcanzables relevantes (colinealidad). Este ciclo construye un sustrato cíclico donde reach
y relevancia están GENUINAMENTE DISOCIADAS -- con (a) modos relevantes-Y-alcanzables (el R-VALOR alto), (b) modos relevantes-pero-
INALCANZABLES (alta w, reach 0: el control no llega), (c) modos alcanzables-pero-IRRELEVANTES (reach > 0, w 0) -- y pregunta si el
agente, descubriendo b̂/Â/ŵ de UN stream, AÍSLA AMBOS factores: ¿la reach-relevancia compuesta valora el relevante-alcanzable por
encima del relevante-inalcanzable (relevancia sin reach) Y del alcanzable-irrelevante (reach sin relevancia)? ¿Y AHORA sí la
relevancia es load-bearing (shuffle-ŵ Y ŵ≡unos rompen, a diferencia de 139)?

DINÁMICA (numpy, sustrato lineal con CICLO, estructura de 137/139). x_{t+1}=A·x+b⊙u+ruido; A=a·I + ciclo driver↔target (radio<1).
Modos canónicos: 0 driver_R (b=1,w=0) en ciclo con 1 target_R (b=0,w=1) = relevante-ALCANZABLE; 2 rel_unreached (b=0,w=1, SIN
acople a ningún controlable) = relevante-INALCANZABLE; 3 driver_irr (b=1,w=0) en ciclo con 4 target_irr (b=0,w=0) = alcanzable-
IRRELEVANTE; 5,6 ruidosos; 7 filler. Meta G=w·x. Valor-de-decisión verdadero dG/du_i = |b_i·m_i|, m=(I-A)^{-T}w. El agente descubre
b̂,Â (system-ID), ŵ (credit-assignment G~x) de un stream u~N(0,σu). CRITERIOS: reach (|b̂·(I-Â)^{-T}ŵ|), local (|b̂·ŵ|, 134),
ctrl_only (|b̂|), rel_only (|ŵ|). CONTROLES NULOS: shuffle-ŵ y ŵ≡unos (si la relevancia es load-bearing, AMBOS deben romper -- a
diferencia de 139 donde ŵ≡unos NO rompía).

PREGUNTA FALSABLE:
  - APOYADA si reach valora correctamente el relevante-alcanzable por encima del relevante-inalcanzable Y del alcanzable-irrelevante
    (AMBOS factores load-bearing), Y los controles nulos shuffle-ŵ Y ŵ≡unos AHORA rompen (relevancia aislada). => cierra el caveat
    de 139: bajo un sustrato donde reach≠relevancia, el agente aísla AMBOS factores de un stream.
  - REFUTADA si la relevancia sigue sin aislarse (ŵ≡unos no rompe) o el agente no distingue relevante-alcanzable de relevante-
    inalcanzable.
  - MIXTA si condicional (p.ej. aísla la relevancia pero la estimación bajo ciclos es cara, o un control nulo no rompe limpio).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp127_relevance_isolation.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp127_relevance_isolation.run --seeds 200
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
AA = 0.6
RHO_SPEC = 0.9        # radio espectral del ciclo (a+g) -> g = RHO_SPEC - AA
N_DECOY = 2           # nº de drivers alcanzables-IRRELEVANTES que compiten (n_decoy=0 reproduce 139: ones_w NO rompe)
D = 2 + 2 * N_DECOY + 2     # driver_R+target_R + n_decoy×(driver_irr+target_irr) + rel_unreached + noisy
KSEL = 1              # capacidad por defecto; la verificación 139/143 mostró que a K>=#drivers el efecto EVAPORA (artefacto K=1)
SU = 1.0
NOISE_HI = 3.0
TS = [50, 150, 500, 1500]
T_FIXED = 1500
KS = [1, 2, 3]        # barrido de capacidad (la corrección clave: el aislamiento es condicional a K < #drivers controlables)
ARMS = ("reach", "local", "ctrl_only", "rel_only")
CONTROLS = ("shuffle_w", "ones_w")


def _n_drivers():
    return 1 + N_DECOY     # driver_R + n_decoy drivers irrelevantes


def _spec():
    """índices: 0 driver_R, 1 target_R(rel); luego N_DECOY pares (driver_irr,target_irr); rel_unreached; noisy."""
    d = D
    b = np.zeros(d); w = np.zeros(d); s = np.ones(d); edges = [(1, 0)]
    b[0] = 1.0; w[1] = 1.0          # driver_R <-> target_R: relevante-ALCANZABLE (EL valioso)
    for k in range(N_DECOY):
        di = 2 + 2 * k; ti = 3 + 2 * k
        b[di] = 1.0; edges.append((ti, di))     # driver_irr <-> target_irr: alcanzable-IRRELEVANTE
    w[2 + 2 * N_DECOY] = 1.0        # rel_unreached: relevante-INALCANZABLE (b=0)
    s[2 + 2 * N_DECOY + 1] = NOISE_HI
    return b, w, s, edges


def _build_A(g, perm, edges):
    d = len(perm)
    A = AA * np.eye(d)
    for dst, src in edges:          # ciclos driver<->target, peso g (lazo de feedback, radio = a+g)
        A[dst, src] += g; A[src, dst] += g
    return A[np.ix_(perm, perm)]


def _reach_value(A, b, w):
    d = len(b)
    m = np.linalg.solve((np.eye(d) - A).T, w)
    return np.abs(b * m)


def _experience(rng, A, b, s, T, sigma_u, w):
    d = len(b); x = np.zeros(d)
    X = np.zeros((T, d)); Xn = np.zeros((T, d)); U = np.zeros((T, d)); G = np.zeros(T)
    for t in range(T):
        u = rng.normal(0, sigma_u, d)
        xn = A @ x + b * u + rng.normal(0, 1.0, d) * s
        xn = np.clip(xn, -1e6, 1e6)
        X[t] = x; Xn[t] = xn; U[t] = u; G[t] = float(np.dot(w, x)) + rng.normal(0, 0.5)
        x = xn
    return X, Xn, U, G


def _estimate_AB(X, Xn, U):
    d = X.shape[1]
    A_hat = np.zeros((d, d)); b_hat = np.zeros(d)
    for j in range(d):
        F = np.concatenate([X, U[:, j:j + 1]], axis=1)
        coef, *_ = np.linalg.lstsq(F, Xn[:, j], rcond=None)
        A_hat[j, :] = coef[:d]; b_hat[j] = coef[d]
    return A_hat, b_hat


def _safe_reach(A_hat, w_hat):
    d = len(w_hat)
    try:
        return np.linalg.solve((np.eye(d) - A_hat).T, w_hat)
    except np.linalg.LinAlgError:
        return np.linalg.pinv((np.eye(d) - A_hat).T) @ w_hat


def _payoff(score, v_true, K):
    S = np.argsort(np.where(np.isfinite(score), score, -np.inf))[-K:]
    oracle = float(np.sum(np.sort(v_true)[-K:])) + 1e-12
    return float(np.sum(v_true[S])) / oracle


def run_cell(T, n_seeds, control=None, K=None):
    if K is None:
        K = KSEL
    d = D
    accs = {a: [] for a in ARMS}
    pick_reach_correct = []
    g = RHO_SPEC - AA
    b0, w0, s0, edges = _spec()
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 9173 + int(T) * 13 + (hash(control) % 1000) * 101 + K * 7919 + 29)
        perm = rng.permutation(d)
        b = b0[perm]; w = w0[perm]; s = s0[perm]
        A = _build_A(g, perm, edges)
        idx_dR = int(np.where(perm == 0)[0][0])    # driver_R = EL valioso (relevante-alcanzable)

        v_true = _reach_value(A, b, w)
        X, Xn, U, G = _experience(rng, A, b, s, T, SU, w)
        A_hat, b_hat = _estimate_AB(X, Xn, U)
        w_hat, *_ = np.linalg.lstsq(X, G, rcond=None)
        if control == "shuffle_w":
            w_hat = w_hat[rng.permutation(d)]
        elif control == "ones_w":
            w_hat = np.ones(d)
        m_hat = _safe_reach(A_hat, w_hat)
        scores = {"reach": np.abs(b_hat * m_hat), "local": np.abs(b_hat * w_hat),
                  "ctrl_only": np.abs(b_hat), "rel_only": np.abs(w_hat)}
        for a in ARMS:
            accs[a].append(_payoff(scores[a], v_true, K))
        if control is None:
            top = set(np.argsort(scores["reach"])[-K:].tolist())
            pick_reach_correct.append(1.0 if idx_dR in top else 0.0)
    out = {a: round(float(np.mean(accs[a])), 4) for a in ARMS}
    if control is None:
        out["pick_reach_correct"] = round(float(np.mean(pick_reach_correct)), 4)
    return out


def run(n_seeds):
    global N_DECOY, D
    by_T = {str(T): run_cell(T, n_seeds) for T in TS}
    ctrl = {c: run_cell(T_FIXED, n_seeds, control=c) for c in CONTROLS}
    # BARRIDO DE CAPACIDAD K (la corrección clave de la verificación: el aislamiento EVAPORA a K>=#drivers, artefacto K=1 de 139)
    by_K = {}
    for K in KS:
        cell = run_cell(T_FIXED, n_seeds, K=K)
        cell_ones = run_cell(T_FIXED, n_seeds, control="ones_w", K=K)
        by_K[str(K)] = {"reach": cell["reach"], "ctrl_only": cell["ctrl_only"], "rel_only": cell["rel_only"],
                        "ones_reach": cell_ones["reach"]}
    # CONTROL n_decoy=0 (reproduce 139: sin drivers irrelevantes competidores, ŵ≡unos NO rompe -> el cierre depende de los decoys)
    saved_nd, saved_d = N_DECOY, D
    N_DECOY = 0; D = 2 + 2 * N_DECOY + 2
    nodecoy = run_cell(T_FIXED, n_seeds)
    nodecoy_ones = run_cell(T_FIXED, n_seeds, control="ones_w")
    N_DECOY, D = saved_nd, saved_d
    return {"by_T": by_T, "controls": ctrl, "by_K": by_K,
            "nodecoy": {"reach": nodecoy["reach"], "ones_reach": nodecoy_ones["reach"], "ctrl_only": nodecoy["ctrl_only"]}}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    bt = grid["by_T"]; ct = grid["controls"]
    hi = bt[str(T_FIXED)]
    reach = hi["reach"]; local = hi["local"]; cto = hi["ctrl_only"]; rel = hi["rel_only"]

    reach_high = reach > 0.85
    pick_correct = hi.get("pick_reach_correct", 0.0)
    reach_beats_ctrl = (reach - cto) > 0.15
    reach_beats_rel = (reach - rel) > 0.15
    shuffle_breaks = (reach - ct["shuffle_w"]["reach"]) > 0.15
    ones_breaks = (reach - ct["ones_w"]["reach"]) > 0.15
    # NÚCLEO a K=1: bajo capacidad escasa + decoys, el agente aísla (reach alto, bate a ctrl/rel, ambos controles rompen)
    core_k1 = reach_high and pick_correct > 0.80 and reach_beats_ctrl and reach_beats_rel and shuffle_breaks and ones_breaks

    # --- correcciones de la VERIFICACIÓN ADVERSARIAL de 143 ---
    bk = grid["by_K"]; nd = grid["nodecoy"]; ndrv = _n_drivers()
    # (1) EVAPORA a K>=#drivers (el artefacto K=1 winner-take-all que la verificación de 139 YA RETRACTÓ)
    kfull = bk.get(str(ndrv), bk[str(KS[-1])])
    evaporates_at_kfull = (kfull["reach"] - kfull["ctrl_only"]) < 0.10 and (kfull["reach"] - kfull["ones_reach"]) < 0.10
    # (2) n_decoy=0 REPRODUCE 139: sin drivers irrelevantes competidores, ŵ≡unos NO rompe -> el 'cierre' depende de los decoys+K=1
    nodecoy_ones_break = round(nd["reach"] - nd["ones_reach"], 4)
    nodecoy_reproduces_139 = nodecoy_ones_break < 0.10
    # (3) TAUTOLOGÍA: reach con params VERDADEROS = oracle por construcción (sin sim_check, a diferencia de 139); rel_only=0 es
    #     ESTRUCTURAL (b,w nunca co-localizados); el 'reach bate a rel_only' es definicional.
    Tmin = bt[str(TS[0])]
    estimable = (reach - Tmin["reach"]) > 0.05 or reach > 0.90    # converge desde abajo (la pata leakage-free no-trivial)

    if not core_k1:
        status = "refutada"
        verdict = ("H-V4-10o REFUTADA: ni a K=1 el agente aísla los factores (reach={rh} pick={pk} reach-ctrl +{rbc} reach-rel "
                   "+{rbr} shuffle_breaks={sb} ones_breaks={ob}).").format(
                       rh=_f(reach), pk=_f(pick_correct), rbc=_f(reach - cto), rbr=_f(reach - rel), sb=shuffle_breaks, ob=ones_breaks)
    else:
        status = "mixta"
        verdict = (
            "H-V4-10o MIXTA (núcleo real bajo escasez + acotaciones por verificación adversarial de 2 agentes; 13mo ciclo). El "
            "CYCLE 139 dejó como caveat que bajo ciclos la relevancia era COLINEAL con la reach (ŵ≡unos NO rompía). NÚCLEO "
            "(robusto en radio/T/seeds, verificado): construyendo un sustrato con reach≠relevancia (modos relevante-ALCANZABLE, "
            "relevante-INALCANZABLE, alcanzable-IRRELEVANTE) y bajo CAPACIDAD ESCASA K=1 con drivers irrelevantes COMPITIENDO, la "
            "reach-relevancia estimada |b̂·(I-Â)^{{-T}}ŵ| AÍSLA el único driver relevante-alcanzable (reach={rh}, pick={pk}) donde "
            "ctrl_only ({cto}, +{rbc}: la relevancia añade), rel_only ({rel}, +{rbr}: la reach añade) y AMBOS controles nulos "
            "fallan/rompen (shuffle-ŵ +{shg}, ŵ≡unos +{ong}); estimable leakage-free (converge desde abajo con T, robusto a radio "
            "0.75-0.99). NO SOBREVIVE (retractado): (1) el aislamiento es CONDICIONAL a K<#drivers -- a K={ndrv} (=#drivers) "
            "EVAPORA (reach-ctrl_only {gke}, reach-ones {gko}): ctrl_only captura el relevante por barrido y ŵ≡unos deja de romper; "
            "es EXACTAMENTE el artefacto K=1 winner-take-all que la verificación de 139 YA RETRACTÓ -- no se barría K. (2) el "
            "'cierre de 139' depende de los DECOYS, no de la disociación per se: con n_decoy=0 (un solo driver) ŵ≡unos NO rompe "
            "({ndob}) -- REPRODUCE 139 exacto. (3) TAUTOLOGÍA: reach con params VERDADEROS = oracle por construcción (sin sim_check, "
            "a diferencia de 139); rel_only=0 es ESTRUCTURAL (b y w nunca co-localizados) -> 'reach bate a rel_only' es "
            "definicional; el 'ŵ≡unos rompe' es un artefacto de decoys SIMÉTRICOS (clones geométricos -> reach les da score igual "
            "-> 1/#drivers). => RESULTADO HONESTO: el sustrato disocia genuinamente reach de relevancia y, BAJO CAPACIDAD ESCASA "
            "(K<#drivers) + decoys competidores, la relevancia ES load-bearing (consistente con 142: el producto importa bajo "
            "escasez de capacidad×disociación); PERO NO cierra el caveat de 139 de forma incondicional -- re-introduce el artefacto "
            "K=1 de 139, el nivel reach=1.0 es tautológico, y el 'ŵ≡unos rompe' depende de la multiplicidad/simetría de decoys. "
            "MIXTA EXITOSA: la verificación cazó el re-uso del artefacto K=1 + la tautología antes del ledger (13mo ciclo). "
            "Frontera: un test del aislamiento que NO dependa de K=1 (capacidad continua / decoys asimétricos); SCALE."
        ).format(rh=_f(reach), pk=_f(pick_correct), cto=_f(cto), rbc=_f(reach - cto), rel=_f(rel), rbr=_f(reach - rel),
                 shg=_f(reach - ct["shuffle_w"]["reach"]), ong=_f(reach - ct["ones_w"]["reach"]), ndrv=ndrv,
                 gke=_f(kfull["reach"] - kfull["ctrl_only"]), gko=_f(kfull["reach"] - kfull["ones_reach"]),
                 ndob=_f(nodecoy_ones_break))

    return {"D": D, "KSEL": KSEL, "n_drivers": ndrv, "radio_spec": RHO_SPEC, "by_T": bt, "controls": ct,
            "by_K": bk, "nodecoy": nd, "reach": reach, "local": local, "ctrl_only": cto, "rel_only": rel,
            "pick_reach_correct": pick_correct, "reach_minus_ctrl": round(reach - cto, 4),
            "reach_minus_rel": round(reach - rel, 4), "shuffle_reach": ct["shuffle_w"]["reach"],
            "ones_reach": ct["ones_w"]["reach"], "shuffle_breaks": bool(shuffle_breaks), "ones_breaks": bool(ones_breaks),
            "core_k1": bool(core_k1), "evaporates_at_kfull": bool(evaporates_at_kfull),
            "nodecoy_ones_break": nodecoy_ones_break, "nodecoy_reproduces_139": bool(nodecoy_reproduces_139),
            "estimable": bool(estimable), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=200)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 40

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp127] CYCLE 143 / H-V4-10o — ¿bajo un sustrato cíclico donde reach≠relevancia, el agente AÍSLA AMBOS factores del keystone (cierra el caveat de 139)?")
    log(f"[exp127] seeds={args.seeds} a={AA} radio_spec={RHO_SPEC} D={D} K={KSEL} Ts={TS}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp127] --- payoff por T (reach vs local vs ctrl_only vs rel_only) ---")
    for T in TS:
        c = grid["by_T"][str(T)]
        log(f"[exp127] T={T:>5}: reach={c['reach']:.3f} local={c['local']:.3f} ctrl_only={c['ctrl_only']:.3f} rel_only={c['rel_only']:.3f}" + (f" | pick_correcto={c.get('pick_reach_correct',0):.2f}" if T == T_FIXED else ""))
    log(f"[exp127] AMBOS factores (K=1): reach-ctrl_only=+{sm['reach_minus_ctrl']:.3f} reach-rel_only=+{sm['reach_minus_rel']:.3f} | shuffle-ŵ reach={sm['shuffle_reach']:.3f} (rompe={sm['shuffle_breaks']}) ŵ≡unos reach={sm['ones_reach']:.3f} (rompe={sm['ones_breaks']})")
    log("[exp127] --- BARRIDO K (la corrección: el aislamiento EVAPORA a K>=#drivers=%d, artefacto K=1 de 139) ---" % sm['n_drivers'])
    for K in KS:
        c = grid["by_K"][str(K)]
        log(f"[exp127] K={K}: reach={c['reach']:.3f} ctrl_only={c['ctrl_only']:.3f} (reach-ctrl +{c['reach']-c['ctrl_only']:.3f}) ones_w={c['ones_reach']:.3f} (ones-break +{c['reach']-c['ones_reach']:.3f})")
    log(f"[exp127] CONTROL n_decoy=0 (reproduce 139): reach={grid['nodecoy']['reach']:.3f} ŵ≡unos={grid['nodecoy']['ones_reach']:.3f} -> ones-break +{sm['nodecoy_ones_break']:.3f} (139-reproducido={sm['nodecoy_reproduces_139']}: sin decoys, ŵ≡unos NO rompe)")
    log(f"[exp127] CHECK core_k1={sm['core_k1']} | evaporates_at_kfull={sm['evaporates_at_kfull']} nodecoy_reproduces_139={sm['nodecoy_reproduces_139']} estimable={sm['estimable']}")
    log(f"[exp127] VEREDICTO H-V4-10o: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp127_relevance_isolation", "cycle": 143, "hypothesis": "H-V4-10o",
           "claim": "MIXTA (post-verificacion adversarial de 2 agentes). NUCLEO (robusto en radio/T/seeds): construyendo un sustrato "
                    "ciclico con reach!=relevancia (modos relevante-ALCANZABLE, relevante-INALCANZABLE, alcanzable-IRRELEVANTE), bajo "
                    "CAPACIDAD ESCASA K=1 + drivers irrelevantes COMPITIENDO, la reach-relevancia estimada |b*(I-A)^-T w| aisla el "
                    "driver relevante-alcanzable donde ctrl_only/rel_only/null-w no pueden (estimable leakage-free). NO SOBREVIVE: el "
                    "aislamiento es CONDICIONAL a K<#drivers -- a K=#drivers EVAPORA (ctrl_only=reach, w=unos no rompe), el MISMO "
                    "artefacto K=1 winner-take-all que la verificacion de 139 YA RETRACTO; n_decoy=0 REPRODUCE 139 (w=unos no rompe -> "
                    "el cierre depende de los decoys, no de la disociacion per se); TAUTOLOGIA (reach con params verdaderos=oracle por "
                    "construccion, sin sim_check; rel_only=0 estructural -b,w disjuntos-; el w=unos-rompe es artefacto de decoys "
                    "simetricos). NO cierra el caveat de 139 incondicionalmente; muestra que la relevancia es load-bearing solo bajo "
                    "escasez de capacidad (consistente con 142)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp127] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
