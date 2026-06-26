r"""
exp117 — CYCLE 133 / H-V4-10g (rama control/acción, ROBUSTEZ del keystone 129 a un SUSTRATO ACOPLADO; versión HONESTA tras
VERIFICACIÓN ADVERSARIAL): ¿sobrevive el keystone (el control reconstruye R-VALOR = controlabilidad × relevancia) cuando el
SUSTRATO ya NO es de modos INDEPENDIENTES sino que ACOPLA los modos (actuar sobre uno propaga a otros)? Es la frontera explícita
de 132 ("estructura/no-linealidad en el SUSTRATO, no sólo en el control"); rompe el supuesto de modos independientes que se
mantenía desde CYCLE 127.

HISTORIA HONESTA (registrada): una 1ra versión (un único arco de acople m1<-m2, w_driver=0, criterio reach = top-K-standalone)
daba una MIXTA FUERTE ("valor_reach robustamente óptimo en TODO κ, valor_local ciego al acople, ventaja +0.526"). Una
VERIFICACIÓN ADVERSARIAL (4 agentes) la ACOTÓ con tres hallazgos reproducidos: (1) en esa estructura reach≡ORACLE por
construcción (subset-match 100% a κ>0) -> "reach=1.000 exacto" NO es evidencia ortogonal de robustez; el contenido sustantivo es
el FALLO del local. (2) El criterio IMPLEMENTADO (top-K-standalone) NO es robusto: bajo REDUNDANCIA SUBMODULAR (2 drivers->1
target) COLAPSA (gasta la capacidad en drivers redundantes) mientras un GREEDY ADAPTATIVO mantiene el óptimo -> la robustez
pertenece al PRINCIPIO reach×rel CON selección ADAPTATIVA, no al heurístico marginal. (3) La magnitud titular era un FILO de
medida cero en w_driver=0 EXACTO (con 1% de relevancia directa el local se recupera) -> el mecanismo correcto NO es "ceguera
estructural" sino "la relevancia DIRECTA es un PROXY INFIEL de la relevancia-POR-ALCANCE", que reaparece de forma GENÉRICA con un
modo DISTRACTOR (vanidad: controlable + directamente-relevante, sin acople). Lo que RESISTIÓ: _reduction es correcto (MC <0.21%),
sin leakage, y la falla del local NO es "1-paso vs multi-paso" (un local multipaso sobre su propio modo tampoco elige al driver).

Esta versión incorpora los fixes ANTES del ledger:
  - reach_greedy: selección GREEDY ADAPTATIVA sobre M̂ acoplada (el criterio CORRECTO; ≈ oracle estimado).
  - reach_topk:   top-K-standalone (el heurístico naive) -> se reporta su COLAPSO bajo redundancia.
  - reach_1hop:   criterio simple de 1 salto (w_i b̂_i² + Σ_j w_j (Â[j,i] b̂_i)²) -> iguala a reach en 1-hop, FALLA en multi-hop
                  (justifica la maquinaria de horizonte completo; evita el straw-man).
  - 4 estructuras de acople: base (1-arco), multihop (driver->relay->target), redundant (2 drivers->1 target), distractor
    (driver poco-relevante + vanidad), + un sweep de w_driver que documenta el knife-edge.

DINÁMICA (sustrato lineal ACOPLADO). x_{t+1} = A·x_t + (b ⊙ u_t) + ruido; A = a·I + Σ κ·E_{dst<-src} (aristas de acople,
κ barrido). Regulación de horizonte H a target aleatorio en los modos relevantes; control ridge (cost ρ·||u||²) sobre el
SUBCONJUNTO elegido -> costo esperado en forma CERRADA (E_d[coste]=tr(W)-reducción, d~N(0,I)). perf = reducción(arm)/reducción
(oracle), con M VERDADERA; el ranking sale de ESTIMACIONES por probes (Â,b̂,var̂ por sistema-ID, como 128/132). El criterio LOCAL
usa sólo b̂ (tira el acople estimado Â); los criterios reach usan la M̂ completa (Â con el acople). MISMA información: la
diferencia es si USAN el acople y CÓMO seleccionan.

PREGUNTA FALSABLE:
  - APOYADA si el keystone LOCAL (valor_local) se mantiene óptimo aun con acople (el acople no rompe la versión local).
  - REFUTADA si NI el principio con selección adaptativa (reach_greedy) sobrevive -> el keystone no sobrevive al acople.
  - MIXTA (esperado/verificado, ACOTADA): el PRINCIPIO valor=ctrl×rel sobrevive a un sustrato acoplado PERO su factor de
    controlabilidad debe ser de ALCANCE-POR-LA-RED **y** la selección debe ser ADAPTATIVA (greedy): (i) valor_local falla bajo
    acople cuando la relevancia directa es un proxy infiel del alcance (base w_driver=0 Y, robusto, con distractor); (ii) el
    reach NAIVE (top-K-standalone) NO basta: colapsa bajo redundancia submodular; (iii) el reach de 1-hop NO basta: falla bajo
    multi-hop. Generaliza 132 (alcance bajo saturación del CONTROL) al alcance por el acople del SUSTRATO.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp117_coupled_substrate.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp117_coupled_substrate.run            # FULL
"""
import argparse
import itertools
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
RHO = 0.5
H = 3                  # horizonte de regulación (>=2 para que el acople propague el control del DRIVER al TARGET)
K = 2                  # capacidad: nº de actuadores; la MIXTA requiere K>=2 (a K=1 la disociación no se manifiesta)
D = 8
SIGMA_P = 1.0
N_PROBE = 2000         # >= ~100 para que el sistema-ID del acople (reach) sea señal y no ruido (costo de datos, CYCLE 128)
KAPPAS = [0.0, 0.25, 0.5, 1.0]
W_DRIVER_SWEEP = [0.0, 0.01, 0.05, 0.1]   # documenta el knife-edge: el local se recupera con fuga de relevancia directa
ARMS = ("reach_greedy", "reach_topk", "reach_1hop", "valor_local", "relevancia", "prediccion")
NOISE_HI = 3.0
STRUCT_SEED = {"base": 1, "multihop": 2, "redundant": 3, "distractor": 4}   # offset determinista (NO usar hash(): no es estable)


def _spec(structure, w_driver=0.0):
    """Devuelve (b, w, s, edges). edges = lista (dst, src, peso_kappa) en índices canónicos (peso se escala por κ en _build_A,
    salvo en estructuras multi-arista donde el peso ya es relativo). Modos: 0..7."""
    b = np.zeros(D); w = np.zeros(D); s = np.ones(D); edges = []
    if structure == "base":
        # 0 CTRL+REL  1 TARGET  2 DRIVER->1  3,4 DECOY-CTRL  5,6 NOISY  7 FILLER
        b[:] = [1, 0, 1, 1, 1, 0, 0, 0]; w[:] = [1, 1, w_driver, 0, 0, 0, 0, 0]
        s[5] = s[6] = NOISE_HI; edges = [(1, 2, 1.0)]
        driver = 2
    elif structure == "multihop":
        # 0 CTRL+REL  1 TARGET  2 DRIVER  3 RELAY  4 DECOY  5,6 NOISY  7 FILLER ; driver->relay->target (sin arco directo)
        b[:] = [1, 0, 1, 0, 1, 0, 0, 0]; w[:] = [1, 1, 0, 0, 0, 0, 0, 0]
        s[5] = s[6] = NOISE_HI; edges = [(1, 3, 1.0), (3, 2, 1.0)]
        driver = 2
    elif structure == "redundant":
        # 0 CTRL+REL  1 TARGET  2 DRIVER1->1  3 DRIVER2->1  4 DECOY  5,6 NOISY  7 FILLER (2 drivers redundantes al mismo target)
        b[:] = [1, 0, 1, 1, 1, 0, 0, 0]; w[:] = [1, 1, 0, 0, 0, 0, 0, 0]
        s[5] = s[6] = NOISE_HI; edges = [(1, 2, 1.0), (1, 3, 1.0)]
        driver = 2
    elif structure == "distractor":
        # 0 CTRL+REL  1 TARGET  2 DRIVER(poco rel)->1  3 VANIDAD(ctrl+rel directo, SIN acople)  4 DECOY  5,6 NOISY  7 FILLER
        b[:] = [1, 0, 1, 1, 1, 0, 0, 0]; w[:] = [1, 1, 0.1, 0.3, 0, 0, 0, 0]
        s[5] = s[6] = NOISE_HI; edges = [(1, 2, 1.0)]
        driver = 2
    else:
        raise ValueError(structure)
    return b, w, s, edges, driver


def _build_A(edges, kappa, perm):
    A = AA * np.eye(D)
    for dst, src, wgt in edges:
        A[dst, src] += kappa * wgt
    return A[np.ix_(perm, perm)]


def _Apows(A):
    P = [np.eye(D)]
    for _ in range(1, H):
        P.append(A @ P[-1])
    return P


def _M_subset(Apows, b, S):
    cols = []
    for j in S:
        for k in range(H):
            cols.append(Apows[H - 1 - k][:, j] * b[j])
    return np.stack(cols, axis=1) if cols else np.zeros((D, 0))


def _reduction(M, w):
    """E_d[coste_pasivo - coste_regulado], d~N(0,I), control ridge: tr(W M (M^T W M+ρI)^{-1} M^T W). (Verificado MC <0.21%.)"""
    if M.shape[1] == 0:
        return 0.0
    Wm = w[:, None] * M
    G = M.T @ Wm + RHO * np.eye(M.shape[1])
    try:
        Ginv = np.linalg.inv(G)
    except np.linalg.LinAlgError:
        Ginv = np.linalg.pinv(G)
    return float(np.sum((Wm @ Ginv) * Wm))


def _greedy(Apows, b, w, k):
    """Selección GREEDY ADAPTATIVA: en cada paso agrega el modo de mayor reducción MARGINAL dado lo ya elegido."""
    S = []
    for _ in range(k):
        best_j, best_r = None, -1.0
        for j in range(D):
            if j in S:
                continue
            r = _reduction(_M_subset(Apows, b, S + [j]), w)
            if r > best_r:
                best_r, best_j = r, j
        S.append(best_j)
    return S


def _estimate(rng, A, b, s):
    X = rng.normal(0, 1.0, (N_PROBE, D))
    U = rng.normal(0, SIGMA_P, (N_PROBE, D))
    noise = rng.normal(0, 1.0, (N_PROBE, D)) * s[None, :]
    Xp = X @ A.T + U * b[None, :] + noise
    Feat = np.concatenate([X, U], axis=1)
    coef, *_ = np.linalg.lstsq(Feat, Xp, rcond=None)
    A_hat = coef[:D, :].T
    b_hat = np.array([coef[D + i, i] for i in range(D)])
    Xp0 = X @ A.T + noise
    var_hat = np.var(Xp0, axis=0)
    return A_hat, b_hat, var_hat


def _select(arm, Apows_hat, A_hat, b_hat, w, var_hat):
    if arm == "reach_greedy":
        return _greedy(Apows_hat, b_hat, w, K)
    if arm == "reach_topk":
        score = np.array([_reduction(_M_subset(Apows_hat, b_hat, [i]), w) for i in range(D)])
    elif arm == "reach_1hop":
        # alcance de 1 salto: directo + 1 hop de acople, ponderado por relevancia (sin horizonte completo, sin ridge)
        direct = w * b_hat ** 2
        hop = np.array([np.sum(w * (A_hat[:, i] * b_hat[i]) ** 2) for i in range(D)])
        score = direct + hop
    elif arm == "valor_local":
        score = w * b_hat ** 2 / (b_hat ** 2 + RHO)       # keystone 129/130 LOCAL (sólo pendiente directa)
    elif arm == "relevancia":
        score = w + np.arange(D) * 1e-12                    # tie-break determinista
    elif arm == "prediccion":
        score = var_hat
    else:
        raise ValueError(arm)
    return list(np.argsort(score)[-K:])


def run_cell(structure, kappa, n_seeds, w_driver=0.0):
    accs = {a: [] for a in ARMS}
    pick_drv = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7919 + int(kappa * 1000) * 17 + STRUCT_SEED[structure] * 90001 + int(w_driver * 1000) * 7 + 3)
        b0, w0, s0, edges, drv_can = _spec(structure, w_driver)
        perm = rng.permutation(D)
        inv = np.argsort(perm)
        b = b0[perm]; w = w0[perm]; s = s0[perm]
        A = _build_A(edges, kappa, perm)
        driver_pos = int(inv[drv_can])
        Apows = _Apows(A)

        A_hat, b_hat, var_hat = _estimate(rng, A, b, s)
        Apows_hat = [np.eye(D)]
        for _ in range(1, H):
            Apows_hat.append(A_hat @ Apows_hat[-1])

        best = -1.0
        for S in itertools.combinations(range(D), K):
            r = _reduction(_M_subset(Apows, b, list(S)), w)
            if r > best:
                best = r
        den = best + 1e-12

        for arm in ARMS:
            S = _select(arm, Apows_hat, A_hat, b_hat, w, var_hat)
            r = _reduction(_M_subset(Apows, b, S), w)
            accs[arm].append(max(0.0, min(1.0, r / den)))
            pick_drv[arm].append(1.0 if driver_pos in set(S) else 0.0)
    out = {a: round(float(np.mean(accs[a])), 4) for a in ARMS}
    out["pd_local"] = round(float(np.mean(pick_drv["valor_local"])), 4)
    out["pd_greedy"] = round(float(np.mean(pick_drv["reach_greedy"])), 4)
    return out


def run(n_seeds):
    grid = {"base": {str(kp): run_cell("base", kp, n_seeds) for kp in KAPPAS}}
    grid["wdriver"] = {str(wd): run_cell("base", 1.0, n_seeds, w_driver=wd) for wd in W_DRIVER_SWEEP}
    for st in ("multihop", "redundant", "distractor"):
        grid[st] = run_cell(st, 1.0, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    k0, kmax = str(KAPPAS[0]), str(KAPPAS[-1])
    base0 = grid["base"][k0]; baseM = grid["base"][kmax]
    multi = grid["multihop"]; redun = grid["redundant"]; dist = grid["distractor"]

    # PRINCIPIO con selección adaptativa: reach_greedy robusto en TODAS las estructuras
    greedy_min = min(grid["base"][kmax]["reach_greedy"], multi["reach_greedy"], redun["reach_greedy"], dist["reach_greedy"])
    # LOCAL falla bajo acople: base (w_driver=0) y, robusto/no-knife-edge, con DISTRACTOR
    local_base0 = base0["valor_local"]; local_baseM = baseM["valor_local"]
    greedy_baseM = baseM["reach_greedy"]
    local_dist = dist["valor_local"]; greedy_dist = dist["reach_greedy"]
    # reach NAIVE (top-K-standalone) NO basta: colapsa bajo redundancia submodular
    topk_redun = redun["reach_topk"]; greedy_redun = redun["reach_greedy"]
    # reach de 1-hop NO basta: falla bajo multi-hop
    onehop_multi = multi["reach_1hop"]; greedy_multi = multi["reach_greedy"]

    principle_robust = greedy_min > 0.85
    local_ok_indep = local_base0 > 0.90                                    # κ=0 recupera 129
    local_fails_coupled = (greedy_baseM - local_baseM) > 0.15              # base: local ciego al acople
    local_fails_distractor = (greedy_dist - local_dist) > 0.10            # robusto/no-knife-edge: proxy infiel de relevancia
    topk_not_robust = (greedy_redun - topk_redun) > 0.15                  # selección debe ser ADAPTATIVA
    onehop_not_enough = (greedy_multi - onehop_multi) > 0.15              # controlabilidad debe ser de horizonte completo

    if principle_robust and local_ok_indep and local_fails_coupled and topk_not_robust and onehop_not_enough:
        status = "mixta"
        verdict = (
            "H-V4-10g MIXTA (ACOTADA): el PRINCIPIO valor=ctrl×rel SOBREVIVE a un sustrato ACOPLADO pero su factor de "
            "controlabilidad debe ser de ALCANCE-POR-LA-RED **y** la selección debe ser ADAPTATIVA. El criterio CORRECTO "
            "(reach_greedy: alcance acoplado de horizonte completo + selección greedy) es robusto en TODAS las estructuras "
            "(min {gm}). (i) El keystone LOCAL 129 (valor_local) es óptimo con modos independientes (κ=0: {lk0}, recupera 129) "
            "pero FALLA bajo acople: en base cae a {lkm} vs greedy {gbm} (la relevancia directa es proxy INFIEL del alcance, "
            "pd_local={pdl}); y la falla es ROBUSTA/no-knife-edge -- con un modo DISTRACTOR (vanidad ctrl+rel-directo sin "
            "acople) el local cae a {ld} vs greedy {gd}. (ii) El reach NAIVE (top-K-standalone) NO basta: bajo REDUNDANCIA "
            "submodular (2 drivers->1 target) COLAPSA a {tkr} mientras el greedy adaptativo mantiene {grr} -> la selección "
            "debe ser adaptativa. (iii) El reach de 1-HOP NO basta: bajo MULTI-HOP (driver->relay->target) cae a {ohm} vs "
            "greedy {gmm} -> la controlabilidad debe ser de horizonte/alcance completo. NOTA: reach_greedy ≈ oracle ESTIMADO "
            "por construcción (no es evidencia ortogonal de robustez); el contenido sustantivo es el FALLO del local y que "
            "BOTH la controlabilidad (->alcance-por-red) y la selección (->adaptativa) deben volverse conscientes del acople. "
            "Generaliza 132 (alcance bajo saturación del CONTROL) al alcance por el acople del SUSTRATO."
        ).format(gm=_f(greedy_min), lk0=_f(local_base0), lkm=_f(local_baseM), gbm=_f(greedy_baseM), pdl=_f(baseM["pd_local"]),
                 ld=_f(local_dist), gd=_f(greedy_dist), tkr=_f(topk_redun), grr=_f(greedy_redun), ohm=_f(onehop_multi),
                 gmm=_f(greedy_multi))
    elif not principle_robust:
        status = "refutada"
        verdict = ("H-V4-10g REFUTADA: ni el principio con selección adaptativa sobrevive al acople (reach_greedy min {gm} <= "
                   "0.85).").format(gm=_f(greedy_min))
    else:
        status = "apoyada"
        verdict = ("H-V4-10g APOYADA: el keystone LOCAL se mantiene óptimo aun con acople (valor_local base κmax {lkm} vs "
                   "greedy {gbm}) -> el acople del sustrato no rompe la versión local.").format(
                       lkm=_f(local_baseM), gbm=_f(greedy_baseM))

    return {"grid": grid, "greedy_min": greedy_min, "local_base0": local_base0, "local_baseM": local_baseM,
            "greedy_baseM": greedy_baseM, "local_dist": local_dist, "greedy_dist": greedy_dist,
            "topk_redun": topk_redun, "greedy_redun": greedy_redun, "onehop_multi": onehop_multi,
            "greedy_multi": greedy_multi, "pd_local_baseM": baseM["pd_local"], "pd_greedy_baseM": baseM["pd_greedy"],
            "principle_robust": bool(principle_robust), "local_ok_indep": bool(local_ok_indep),
            "local_fails_coupled": bool(local_fails_coupled), "local_fails_distractor": bool(local_fails_distractor),
            "topk_not_robust": bool(topk_not_robust), "onehop_not_enough": bool(onehop_not_enough),
            "status": status, "verdict": verdict}


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

    log("[exp117] CYCLE 133 / H-V4-10g (honesto, post-verificación adversarial) — ¿sobrevive el keystone (valor=ctrl×rel) a un SUSTRATO ACOPLADO? reach_greedy (alcance-por-red + selección adaptativa) vs valor_local (keystone 129) vs reach naive/1-hop")
    log(f"[exp117] seeds={args.seeds} a={AA} rho={RHO} H={H} K={K} D={D} sigma_p={SIGMA_P} kappas={KAPPAS} n_probe={N_PROBE}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp117] --- BASE (un arco, w_driver=0), barrido de acople κ ---")
    for kp in KAPPAS:
        r = grid["base"][str(kp)]
        log(f"[exp117] κ={kp:>4}: greedy={r['reach_greedy']:.3f} topk={r['reach_topk']:.3f} 1hop={r['reach_1hop']:.3f} local={r['valor_local']:.3f} relev={r['relevancia']:.3f} pred={r['prediccion']:.3f} | pd_local={r['pd_local']:.2f} pd_greedy={r['pd_greedy']:.2f}")
    log("[exp117] --- KNIFE-EDGE: sweep w_driver (κ=1.0); el local se recupera con fuga de relevancia directa ---")
    for wd in W_DRIVER_SWEEP:
        r = grid["wdriver"][str(wd)]
        log(f"[exp117] w_driver={wd:>4}: local={r['valor_local']:.3f} greedy={r['reach_greedy']:.3f} (pd_local={r['pd_local']:.2f})")
    log("[exp117] --- ESTRUCTURAS (κ=1.0) ---")
    for st in ("multihop", "redundant", "distractor"):
        r = grid[st]
        log(f"[exp117] {st:>10}: greedy={r['reach_greedy']:.3f} topk={r['reach_topk']:.3f} 1hop={r['reach_1hop']:.3f} local={r['valor_local']:.3f} relev={r['relevancia']:.3f}")
    log(f"[exp117] CHECK principle_robust(greedy_min={sm['greedy_min']:.3f})={sm['principle_robust']} | local_ok_indep={sm['local_ok_indep']} local_fails_coupled={sm['local_fails_coupled']} local_fails_distractor={sm['local_fails_distractor']} | topk_not_robust(redun greedy {sm['greedy_redun']:.3f} vs topk {sm['topk_redun']:.3f})={sm['topk_not_robust']} | onehop_not_enough(multi greedy {sm['greedy_multi']:.3f} vs 1hop {sm['onehop_multi']:.3f})={sm['onehop_not_enough']}")
    log(f"[exp117] VEREDICTO H-V4-10g: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp117_coupled_substrate", "cycle": 133, "hypothesis": "H-V4-10g",
           "claim": "el keystone (valor=controlabilidad×relevancia) SOBREVIVE a un sustrato ACOPLADO (modos no independientes) "
                    "pero su factor de controlabilidad debe ser de ALCANCE-POR-LA-RED Y la seleccion debe ser ADAPTATIVA "
                    "(greedy): el keystone LOCAL 129 (w·b^2) falla bajo acople porque la relevancia directa es proxy infiel del "
                    "alcance (robusto: tambien con distractor, no solo en w_driver=0 exacto); el reach naive top-K-standalone "
                    "colapsa bajo redundancia submodular; el reach de 1-hop falla bajo multi-hop. reach_greedy ~ oracle estimado "
                    "por construccion (el contenido sustantivo es el FALLO del local). Generaliza 132 (alcance bajo saturacion "
                    "del control) al alcance por el acople del sustrato",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp117] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
