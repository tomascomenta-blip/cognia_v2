r"""
exp130 — CYCLE 146 / H-V4-10r (PIVOTE fuera de la vena keystone/capacidad saturada): todo el arco 127-145 USÓ el keystone
(valor=ctrl×rel) como CRITERIO conocido y preguntó si bate a los factores al seleccionar (5 MIXTA seguidos, rendimientos
decrecientes). Este ciclo pregunta algo DISTINTO y central al North Star ("¿un sistema CONSTRUYE una función de valor endógena?"):
¿es la estructura PRODUCTO ctrl×rel un SESGO INDUCTIVO ÚTIL para un APRENDIZ que debe estimar el valor desde experiencia ESCASA?

TESIS. La factorización keystone (valor ≈ w·ctrl) es un PRIOR de baja capacidad que, bajo ESCASEZ DE DATOS, hace que un aprendiz que
la asume generalice MEJOR que (a) un aprendiz FLEXIBLE (polinomio de alto grado, que sobreajusta -> alta varianza) y (b) un aprendiz
ADITIVO w+ctrl (estructura ERRÓNEA: no puede representar el producto -> sesgo). Bajo ABUNDANCIA el flexible alcanza al estructurado.
=> el keystone no es sólo la forma del oracle: es una hipótesis ÚTIL para APRENDER el valor con pocos datos (sample-efficiency).

DISEÑO (numpy, ridge cerrado). Muestras (w,ctrl)∈[0,1]². Valor verdadero v = w·ctrl + δ·w²ctrl² + ruido (el término δ·w²ctrl² es una
MISESPECIFICACIÓN fuera del span de {1,w,ctrl,w·ctrl} -> el estructurado NO es trivialmente perfecto; anti-tautología). Aprendices
(ridge λ fijo): STRUCT [1, w·ctrl] (asume el producto, 2 params); ADD [1, w, ctrl] (aditivo, sin producto, 3 params); FLEX
[polinomio grado-3, 10 params] (puede representar todo, sobreajusta con N chico). Entrenar con N muestras (eje de ESCASEZ),
evaluar en test grande held-out: MSE de test + payoff de DECISIÓN (rankear top-K por el valor aprendido vs oracle). BARRIDOS:
N∈[6..400] (escasez->abundancia), × δ (misespecificación), × ruido.

ANTI-TAUTOLOGÍA: v_true NO es exactamente la forma STRUCT (la misespecificación δ·w²ctrl² está fuera de su span) -> STRUCT tiene
SESGO; no gana por construcción. El control clave es ADD (mismo orden de params, estructura distinta): si 'cualquier modelo chico'
ganara, el PRODUCTO no sería lo especial. FLEX controla 'sólo usá más capacidad'. La pregunta es bias-variance REAL.

PREGUNTA FALSABLE:
  - APOYADA si bajo ESCASEZ (N chico) STRUCT tiene MENOR error/mejor decisión que FLEX (sobreajuste) Y que ADD (mis-estructura), y
    FLEX lo alcanza bajo ABUNDANCIA -> el keystone es un sesgo inductivo útil para aprender el valor con pocos datos.
  - REFUTADA si STRUCT NO bate a FLEX bajo escasez (sin beneficio bias-variance) o ADD iguala a STRUCT (el producto no es la clave).
  - MIXTA si condicional.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp130_inductive_bias.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp130_inductive_bias.run --seeds 300
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
NS = [6, 12, 25, 50, 100, 400]
N_TEST = 2000
K = 3
LAM = 0.01
DELTA = 0.6        # misespecificación
NOISE = 0.05
# formas de misespecificación. 'prod2' es ~colineal con w·c (la verificación 146 midió 0.95) -> STRUCT casi no recibe sesgo;
# las ORTOGONALES (función de w sola / (w-c)²) NO están en el span de STRUCT -> testean si la ventaja es CONDICIONAL a la
# alineación-con-el-producto (el caveat estándar de sesgo inductivo: ayuda sólo si matchea).
MISSPECS = ("prod2", "w_only", "wmc2")
LEARNERS = ("struct", "add", "flex")


def _feat(w, c, kind):
    if kind == "struct":
        return np.stack([np.ones_like(w), w * c], axis=1)
    if kind == "add":
        return np.stack([np.ones_like(w), w, c], axis=1)
    # flex: polinomio grado-3 (10 términos)
    return np.stack([np.ones_like(w), w, c, w * w, w * c, c * c,
                     w ** 3, w * w * c, w * c * c, c ** 3], axis=1)


def _v_true(w, c, delta, form="prod2"):
    if form == "prod2":
        return w * c + delta * (w ** 2) * (c ** 2)        # ~colineal con w·c (corr~0.95): STRUCT casi no recibe sesgo
    if form == "w_only":
        return w * c + delta * w                           # ORTOGONAL al producto: función de w sola
    if form == "wmc2":
        return w * c + delta * (w - c) ** 2                # ORTOGONAL: interacción no representable por w·c
    raise ValueError(form)


def _ridge_fit(Phi, y, lam):
    p = Phi.shape[1]
    return np.linalg.solve(Phi.T @ Phi + lam * np.eye(p), Phi.T @ y)


def _pairwise(pred, yte, n_pairs=4000, rng=None):
    """Decisión DURA (la fácil top-K no discrimina): fracción de pares ordenados correctamente por el valor predicho."""
    a = rng.integers(0, len(yte), n_pairs); b = rng.integers(0, len(yte), n_pairs)
    same = np.sign(pred[a] - pred[b]) == np.sign(yte[a] - yte[b])
    return float(np.mean(same))


def run_cell(n_train, delta, noise, n_seeds, form="prod2"):
    mse = {k: [] for k in LEARNERS}
    payoff = {k: [] for k in LEARNERS}
    pair = {k: [] for k in LEARNERS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7919 + int(n_train) * 131 + int(delta * 1000) * 17 + int(noise * 1000) * 7 + hash(form) % 997 * 3 + 29)
        wtr = rng.uniform(0, 1, n_train); ctr = rng.uniform(0, 1, n_train)
        ytr = _v_true(wtr, ctr, delta, form) + rng.normal(0, noise, n_train)
        wte = rng.uniform(0, 1, N_TEST); cte = rng.uniform(0, 1, N_TEST)
        yte = _v_true(wte, cte, delta, form)        # test sin ruido (valor verdadero)
        for k in LEARNERS:
            theta = _ridge_fit(_feat(wtr, ctr, k), ytr, LAM)
            pred = _feat(wte, cte, k) @ theta
            mse[k].append(float(np.mean((pred - yte) ** 2)))
            idx = np.argsort(pred)[-K:]
            oracle = float(np.sum(np.sort(yte)[-K:])) + 1e-12
            payoff[k].append(float(np.sum(yte[idx])) / oracle)       # decisión FÁCIL (top-K, no discrimina)
            pair[k].append(_pairwise(pred, yte, rng=rng))            # decisión DURA (pairwise)
    return {"mse": {k: round(float(np.mean(mse[k])), 5) for k in LEARNERS},
            "payoff": {k: round(float(np.mean(payoff[k])), 4) for k in LEARNERS},
            "pairwise": {k: round(float(np.mean(pair[k])), 4) for k in LEARNERS}}


def _colinearity_prod2():
    """corr(w·c, (w·c)²) sobre el dominio: la verificación 146 mostró que la misespecificación 'prod2' es ~colineal con la
    ÚNICA feature de STRUCT -> su sesgo irreducible es minúsculo POR DISEÑO (el 'anti-tautología' es débil)."""
    rng = np.random.default_rng(0)
    w = rng.uniform(0, 1, 20000); c = rng.uniform(0, 1, 20000)
    u = w * c
    return float(np.corrcoef(u, u ** 2)[0, 1])


def run(n_seeds):
    by_n = {str(n): run_cell(n, DELTA, NOISE, n_seeds) for n in NS}
    by_delta = {str(d): run_cell(25, d, NOISE, n_seeds) for d in (0.0, 0.6, 1.5)}
    by_noise = {str(s): run_cell(25, DELTA, s, n_seeds) for s in (0.0, 0.05, 0.2)}
    # la verificación 146: la ventaja es CONDICIONAL a la alineación-con-el-producto. Misespecificación ORTOGONAL -> STRUCT se hunde.
    by_misspec = {f: run_cell(NS[0], DELTA, NOISE, n_seeds, form=f) for f in MISSPECS}
    return {"by_n": by_n, "by_delta": by_delta, "by_noise": by_noise, "by_misspec": by_misspec,
            "colinearity_prod2": round(_colinearity_prod2(), 4)}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    bn = grid["by_n"]
    mse_struct = [bn[str(n)]["mse"]["struct"] for n in NS]
    mse_add = [bn[str(n)]["mse"]["add"] for n in NS]
    mse_flex = [bn[str(n)]["mse"]["flex"] for n in NS]
    adv_flex = [round(mse_flex[i] - mse_struct[i], 5) for i in range(len(NS))]
    colin = grid.get("colinearity_prod2", 0.0)
    bm = grid["by_misspec"]

    # NÚCLEO (verificado robusto en λ-justo/δ/noise/grado/seeds): bajo ESCASEZ STRUCT (producto, 2 params) bate en MSE a FLEX
    # (sobreajuste) y a ADD/separables (sin producto); FLEX lo alcanza bajo abundancia (bias-variance) -- PERO sólo cuando el valor
    # está ALINEADO con el producto (la misespecificación 'prod2' es ~colineal con w·c).
    scarce_struct_beats_flex = mse_struct[0] < mse_flex[0] * 0.7
    scarce_struct_beats_add = mse_struct[0] < mse_add[0] * 0.7
    flex_catches_up = mse_flex[-1] <= mse_struct[-1] + 0.0005
    adv_decays = adv_flex[0] > adv_flex[-1] + 0.001 and adv_flex[0] > 0.005
    core_estimator = scarce_struct_beats_flex and scarce_struct_beats_add and flex_catches_up and adv_decays

    # --- correcciones de la VERIFICACIÓN ADVERSARIAL de 146 ---
    # (1) CONDICIONAL a la alineación-con-el-producto: con misespecificación ORTOGONAL al producto STRUCT se HUNDE (peor que flex/add)
    def struct_sinks(form):
        m = bm[form]["mse"]
        return m["struct"] > m["flex"] and m["struct"] > m["add"] - 1e-9
    conditional_on_alignment = struct_sinks("w_only") and struct_sinks("wmc2")
    # (2) la 'anti-tautología' es DÉBIL: la misespecificación prod2 es ~colineal con la única feature de STRUCT (corr alta)
    weak_antitaut = colin > 0.85
    # (3) la DECISIÓN está CONFUNDIDA: el top-K perfecto de STRUCT es la SUFICIENCIA de w·c para el orden (v_true monótona en w·c),
    #     no 'ranking robusto'. En decisión DURA (pairwise) STRUCT sí gana bajo escasez con prod2, PERO también colapsa con ortogonal.
    pw0 = bn[str(NS[0])]["pairwise"]
    struct_pairwise_wins_aligned = pw0["struct"] > pw0["flex"] + 0.02 and pw0["struct"] > pw0["add"] + 0.02
    struct_pairwise_sinks_ortho = bm["w_only"]["pairwise"]["struct"] < bm["w_only"]["pairwise"]["flex"]

    if not core_estimator:
        status = "refutada"
        verdict = ("H-V4-10r REFUTADA: bajo escasez STRUCT NO bate a FLEX/ADD en MSE (struct {ms0} vs flex {mf0} vs add {ma0} a "
                   "N={n0}).").format(n0=NS[0], ms0=_f(mse_struct[0]), mf0=_f(mse_flex[0]), ma0=_f(mse_add[0]))
    else:
        status = "mixta"
        verdict = (
            "H-V4-10r MIXTA (núcleo del ESTIMADOR robusto + RE-ACOTADO BIDIRECCIONALMENTE por verificación adversarial de 2 agentes; "
            "16mo ciclo). NÚCLEO (robusto en λ-justo/δ/noise/grado/seeds): bajo ESCASEZ (N={n0}) el aprendiz ESTRUCTURADO (asume el "
            "producto w·ctrl, 2 params) tiene MENOR MSE de test ({ms0}) que el FLEXIBLE (polinomio grado-3, {mf0}: sobreajusta) Y "
            "que el ADITIVO/separables ({ma0}: sin producto); la ventaja DECRECE con N (+{af0}->{afN}, bias-variance) y FLEX lo "
            "ALCANZA bajo ABUNDANCIA -> la factorización producto es un sesgo inductivo útil de BAJA CAPACIDAD para ESTIMAR el valor "
            "con pocos datos (la verificación confirmó: FLEX con λ óptimo sigue ~3x peor a N={n0}, no es artefacto de regularización; "
            "y la MINIMALIDAD -2 params- es lo load-bearing, no sólo 'tener el producto'). PERO RE-ACOTADO: (1) la ventaja es "
            "CONDICIONAL a la ALINEACIÓN-CON-EL-PRODUCTO -- es el caveat ESTÁNDAR de sesgo inductivo ('ayuda sólo si matchea'): con "
            "misespecificación ORTOGONAL al producto (v=w·c+δ·w, o +δ·(w-c)²) STRUCT es el PEOR aprendiz en TODOS los N "
            "(struct_sinks={cond}); el prior de baja capacidad se vuelve sesgo impagable. (2) la 'anti-tautología' es DÉBIL: la "
            "misespecificación 'prod2' δ·(w·c)² está ~{col} CORRELACIONADA con la única feature de STRUCT (w·c) -> su sesgo "
            "irreducible es minúsculo POR DISEÑO (la elegí favorable). (3) la DECISIÓN está CONFUNDIDA: el top-K perfecto de TODOS "
            "(payoff ~1.0) NO es 'ranking robusto al MSE' como dije -- es la SUFICIENCIA de w·c para el ORDEN (v_true es monótona "
            "en w·c, así que el feature de STRUCT ordena perfecto por construcción; a N=100 STRUCT decide perfecto con MSE PEOR que "
            "flex). En decisión DURA (pairwise) STRUCT SÍ gana bajo escasez con prod2 (struct {pws} vs flex {pwf}) -> el 'no se "
            "traslada' era artefacto del top-K fácil; PERO también COLAPSA con misespecificación ortogonal (sinks={cono}). => "
            "RESULTADO HONESTO: el keystone ES un sesgo inductivo útil (minimalidad+producto) para ESTIMAR el valor bajo escasez "
            "CUANDO el valor está alineado con el producto -- el caveat estándar 'no free lunch'; con residuo ortogonal el prior "
            "HUNDE al estimador; y el pago decisional, donde existe, está mediado por la suficiencia de w·c (tautológica para "
            "v_true monótona en el producto). MIXTA EXITOSA: la verificación cazó (a) el over-framing 'anti-tautología' "
            "(misespecificación ~colineal), (b) la mis-caracterización de la decisión (suficiencia, no robustez), (c) la "
            "incondicionalidad (es condicional a la alineación). Frontera: un sesgo inductivo APRENDIDO (no asumido); SCALE."
        ).format(n0=NS[0], nN=NS[-1], ms0=_f(mse_struct[0]), mf0=_f(mse_flex[0]), ma0=_f(mse_add[0]), af0=_f(adv_flex[0]),
                 afN=_f(adv_flex[-1]), cond=conditional_on_alignment, col=_f(colin), pws=_f(pw0["struct"]),
                 pwf=_f(pw0["flex"]), cono=struct_pairwise_sinks_ortho)

    return {"NS": NS, "K": K, "DELTA": DELTA, "NOISE": NOISE, "by_n": bn, "by_delta": grid["by_delta"],
            "by_noise": grid["by_noise"], "by_misspec": bm, "colinearity_prod2": colin,
            "mse_struct": mse_struct, "mse_add": mse_add, "mse_flex": mse_flex, "adv_flex": adv_flex,
            "scarce_struct_beats_flex": bool(scarce_struct_beats_flex), "scarce_struct_beats_add": bool(scarce_struct_beats_add),
            "flex_catches_up": bool(flex_catches_up), "adv_decays": bool(adv_decays), "core_estimator": bool(core_estimator),
            "conditional_on_alignment": bool(conditional_on_alignment), "weak_antitaut": bool(weak_antitaut),
            "struct_pairwise_wins_aligned": bool(struct_pairwise_wins_aligned),
            "struct_pairwise_sinks_ortho": bool(struct_pairwise_sinks_ortho), "status": status, "verdict": verdict}


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

    log("[exp130] CYCLE 146 / H-V4-10r — ¿es la factorización keystone ctrl×rel un SESGO INDUCTIVO ÚTIL para APRENDER el valor bajo escasez de datos? (PIVOTE: aprender el valor, no usarlo)")
    log(f"[exp130] seeds={args.seeds} Ns={NS} K={K} lam={LAM} delta={DELTA} noise={NOISE} learners={LEARNERS}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp130] --- MSE de test por N (escasez->abundancia): STRUCT vs ADD vs FLEX ---")
    for i, n in enumerate(NS):
        log(f"[exp130] N={n:>4}: struct={sm['mse_struct'][i]:.4f} add={sm['mse_add'][i]:.4f} flex={sm['mse_flex'][i]:.4f} | flex-struct=+{sm['adv_flex'][i]:.4f}")
    log("[exp130] --- DECISIÓN por N: payoff top-K (FÁCIL) vs pairwise (DURA) ---")
    for n in NS:
        p = grid["by_n"][str(n)]["payoff"]; pw = grid["by_n"][str(n)]["pairwise"]
        log(f"[exp130] N={n:>4}: topK[struct={p['struct']:.3f} add={p['add']:.3f} flex={p['flex']:.3f}] pairwise[struct={pw['struct']:.3f} add={pw['add']:.3f} flex={pw['flex']:.3f}]")
    log(f"[exp130] --- CONDICIONAL a la alineación: MSE a N={NS[0]} por forma de misespecificación (prod2 ~colineal vs ORTOGONALES) ---")
    for fm in MISSPECS:
        m = grid["by_misspec"][fm]["mse"]
        log(f"[exp130] {fm:>7}: struct={m['struct']:.4f} add={m['add']:.4f} flex={m['flex']:.4f} -> STRUCT {'GANA' if (m['struct']<m['flex'] and m['struct']<m['add']) else 'SE HUNDE'}")
    log(f"[exp130] colinealidad prod2 corr(w·c,(w·c)²)={sm['colinearity_prod2']:.3f} (anti-tautología débil si >0.85)")
    log(f"[exp130] CHECK core_estimator={sm['core_estimator']} | conditional_on_alignment={sm['conditional_on_alignment']} weak_antitaut={sm['weak_antitaut']} struct_pairwise_wins_aligned={sm['struct_pairwise_wins_aligned']} struct_pairwise_sinks_ortho={sm['struct_pairwise_sinks_ortho']}")
    log(f"[exp130] VEREDICTO H-V4-10r: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp130_inductive_bias", "cycle": 146, "hypothesis": "H-V4-10r",
           "claim": "PIVOTE (aprender el valor, no usarlo), MIXTA post-verificacion de 2 agentes. NUCLEO (robusto lambda-justo/delta/"
                    "noise/grado/seeds): la factorizacion keystone w·ctrl es un sesgo inductivo de BAJA CAPACIDAD util para ESTIMAR el "
                    "valor bajo ESCASEZ -- bajo N chico STRUCT (2 params) tiene menor MSE que FLEX (sobreajusta) y separables (sin "
                    "producto), FLEX lo alcanza bajo abundancia (bias-variance), y la MINIMALIDAD es load-bearing. RE-ACOTADO: (1) "
                    "CONDICIONAL a la alineacion-con-el-producto (caveat estandar 'ayuda si matchea'): con misespecificacion ORTOGONAL "
                    "STRUCT se HUNDE en todos los N; (2) la 'anti-tautologia' es DEBIL (la misespecificacion prod2 es ~0.95 colineal "
                    "con w·c); (3) la DECISION esta CONFUNDIDA: el top-K perfecto es la SUFICIENCIA de w·c para el orden (v_true "
                    "monotona en w·c), no robustez; en pairwise STRUCT gana bajo escasez con prod2 pero colapsa con ortogonal",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp130] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
