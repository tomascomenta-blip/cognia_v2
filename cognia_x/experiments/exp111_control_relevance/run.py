r"""
exp111 — CYCLE 127 / H-V4-10a (ABRE la rama NEGLECTADA del árbol: inteligencia = CONTROL/ACCIÓN como rival/raíz de R-VALOR):
la directiva v4 marca "inteligencia = control/acción (active inference / empowerment / good-regulator)" como la mayor
pendiente del árbol de descomposición -- tocada (38/39/79) pero nunca entretenida como la RAÍZ de la relevancia. Este ciclo
la ataca con una pregunta que además la UNIFICA con R-VALOR: ¿un objetivo de CONTROL provee el criterio endógeno de
RELEVANCIA (qué vale la pena modelar) que la PREDICCIÓN pura no tiene?

CONTEXTO (good-regulator, Conant&Ashby): un buen regulador de un sistema debe ser un modelo de ese sistema -- PERO sólo de la
parte CONTROL-RELEVANTE. Bajo capacidad limitada, predecir gasta el presupuesto en lo que tiene más VARIANZA (aunque sea
irrelevante e incontrolable); controlar lo gasta en lo ACCIONABLE. Echo de CYCLE 40 (control > predicción-pasiva bajo
escasez) pero en el dominio del MODELO (qué estructura se aprende), no del cómputo test-time.

DISEÑO (numpy). Estado 2D x=(x1,x2). x1 CONTROLABLE+RELEVANTE: x1' = a·x1 + b·u + N(0,s1). x2 INCONTROLABLE+IRRELEVANTE
(distractor): x2' = a·x2 + N(0,s2), con s2 barrido de < s1 a >> s1. El agente tiene un CUELLO DE BOTELLA: su modelo-del-mundo
captura UN solo modo (una de las dos coordenadas; capacidad-1). PREDICCIÓN elige el modo de mayor varianza de next-state (lo
que más reduce el MSE de predicción). CONTROL elige el modo CONTROLABLE (el único que u afecta). Ambos estiman (â,b̂) de ese
modo de los MISMOS T datos excitados. TAREA: regulación de 1 paso de x1 a un target -> u* = (target − â·x1)/b̂ (necesita el
modelo de x1). performance = 1 − |x1' − target| normalizada (reducción de error vs no-control).

PREGUNTA FALSABLE:
  - APOYADA si: al crecer la varianza del distractor s2 por encima de la del modo relevante, la performance de CONTROL del
    agente PREDICCIÓN COLAPSA (modela el distractor ruidoso, pierde el modo accionable) mientras la de CONTROL se MANTIENE
    alta; y a s2 baja ambos son comparables (ambos modelan x1). El CROSSOVER al crecer s2 es la firma. => un objetivo de
    CONTROL provee el criterio endógeno de RELEVANCIA (qué modelar) que la predicción pura no tiene; un buen regulador modela
    lo control-relevante, no lo más ruidoso. Une la rama control/acción con R-VALOR (control = fuente de la relevancia).
  - REFUTADA si PREDICCIÓN controla tan bien como CONTROL aun con distractor fuerte (predecir basta para hallar lo relevante)
    -> el control no es una fuente distinta de relevancia.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp111_control_relevance.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp111_control_relevance.run            # FULL
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
A = 0.6            # decay compartido de ambos modos
B = 1.0           # ganancia de acción sobre x1
S1 = 1.0          # ruido de proceso del modo relevante (controlable)
S2_SWEEP = [0.5, 1.0, 2.0, 4.0]   # ruido de proceso del distractor (irrelevante), barrido de < a >> s1
T = 200           # presupuesto de datos para identificar el modo elegido
EVAL = 200        # pasos de evaluación de la tarea de control


def _fit_mode(x_cur, x_nxt, u):
    """LSQ de x_nxt ≈ â·x_cur + b̂·u (si u dado) o x_nxt ≈ â·x_cur (si u None). Devuelve (â, b̂)."""
    if u is None:
        A_mat = x_cur.reshape(-1, 1)
        w, *_ = np.linalg.lstsq(A_mat, x_nxt, rcond=None)
        return float(w[0]), 0.0
    A_mat = np.stack([x_cur, u], axis=1)
    w, *_ = np.linalg.lstsq(A_mat, x_nxt, rcond=None)
    return float(w[0]), float(w[1])


def _rollout(rng, n, s2):
    """rollout excitado (u ~ N(0,1)) del sistema 2D. Devuelve x1,x2 (cur), x1n,x2n (next), u."""
    x1 = np.zeros(n); x2 = np.zeros(n); u = rng.normal(0, 1, size=n)
    x1n = np.zeros(n); x2n = np.zeros(n)
    c1, c2 = 0.0, 0.0
    for t in range(n):
        x1[t], x2[t] = c1, c2
        c1n = A * c1 + B * u[t] + rng.normal(0, S1)
        c2n = A * c2 + rng.normal(0, s2)
        x1n[t], x2n[t] = c1n, c2n
        c1, c2 = c1n, c2n
    return x1, x2, x1n, x2n, u


def _control_perf(rng, a_hat, b_hat, n):
    """Regulación de 1 paso de x1 a un target, evaluada per-step en estados iid x1~N(0,1) con targets y ruido COMPARTIDOS
    entre {modelo, oráculo, pasivo} (comparación pareada). perf = fracción del BENEFICIO de control ALCANZABLE capturado =
    (err_pasivo − err_modelo) / (err_pasivo − err_oráculo). Independiente de la escala del ruido S1: modelo perfecto -> 1,
    modelo inútil (b̂≈0) -> ~0. El oráculo usa (A,B) verdaderos = piso de ruido irreducible."""
    if abs(b_hat) < 1e-6:
        b_hat = 1e-6 * (1.0 if b_hat >= 0 else -1.0)
    x1 = rng.normal(0, 1, size=n)
    target = rng.normal(0, 1, size=n)
    noise = rng.normal(0, S1, size=n)
    u_model = (target - a_hat * x1) / b_hat
    u_oracle = (target - A * x1) / B
    err_model = np.abs(A * x1 + B * u_model + noise - target)
    err_oracle = np.abs(A * x1 + B * u_oracle + noise - target)     # = |noise| (piso irreducible)
    err_pass = np.abs(A * x1 + noise - target)                      # sin control (u=0)
    benefit = float(np.mean(err_pass) - np.mean(err_oracle)) + 1e-9
    captured = float(np.mean(err_pass) - np.mean(err_model))
    return round(max(0.0, captured / benefit), 4)


def run_arm(arm, s2, n_seeds):
    perfs = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 6271 + int(s2 * 100) * 19 + (1 if arm == "control" else 0) * 40009 + 5)
        x1, x2, x1n, x2n, u = _rollout(rng, T, s2)
        var1 = np.var(x1n); var2 = np.var(x2n)
        if arm == "prediccion":
            # elige el modo de MAYOR varianza de next-state (lo que más reduce el MSE de predicción)
            pick_relevant = var1 >= var2
        else:  # control
            # elige el modo CONTROLABLE (el único que u afecta) -> siempre x1
            pick_relevant = True
        if pick_relevant:
            a_hat, b_hat = _fit_mode(x1, x1n, u)          # modela el modo relevante x1 (con acción)
        else:
            a_hat, b_hat = _fit_mode(x2, x2n, None)       # modela el distractor x2 (sin acción util) -> b̂=0
        perfs.append(_control_perf(rng, a_hat, b_hat, EVAL))
    return round(float(np.mean(perfs)), 4)


def run(n_seeds):
    grid = {"prediccion": {}, "control": {}}
    for arm in ("prediccion", "control"):
        for s2 in S2_SWEEP:
            grid[arm][str(s2)] = run_arm(arm, s2, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    lo, hi = str(S2_SWEEP[0]), str(S2_SWEEP[-1])
    pred_lo, pred_hi = grid["prediccion"][lo], grid["prediccion"][hi]
    ctrl_lo, ctrl_hi = grid["control"][lo], grid["control"][hi]

    gap_hi = round(ctrl_hi - pred_hi, 4)             # con distractor FUERTE: ventaja de control
    gap_lo = round(ctrl_lo - pred_lo, 4)             # con distractor débil: deberían ser comparables
    pred_collapse = round(pred_lo - pred_hi, 4)      # cuánto COLAPSA la predicción al crecer el distractor
    ctrl_stable = round(ctrl_lo - ctrl_hi, 4)        # cuánto cae control (debería ser chico)

    GAP, SMALL = 0.30, 0.15
    crossover = (gap_hi > GAP) and (gap_lo < SMALL) and (pred_collapse > GAP) and (abs(ctrl_stable) < SMALL + 0.10)
    pred_collapses = pred_collapse > GAP
    ctrl_holds = ctrl_hi > pred_hi + GAP

    if crossover:
        status = "apoyada"
        verdict = ("H-V4-10a APOYADA (control = fuente de RELEVANCIA): CROSSOVER al crecer el distractor irrelevante. A "
                   "distractor DÉBIL (s2={lo}) PREDICCIÓN y CONTROL son comparables ({pl} vs {cl}, gap {gl}: ambos modelan el "
                   "modo accionable). A distractor FUERTE (s2={hi}) la PREDICCIÓN COLAPSA ({ph}, cae {pc}: gasta su capacidad "
                   "en el distractor ruidoso pero irrelevante e incontrolable) mientras CONTROL se MANTIENE ({ch}, gap "
                   "{gh}). => un objetivo de CONTROL provee el criterio endógeno de RELEVANCIA -- modela lo CONTROL-relevante, "
                   "no lo más RUIDOSO; la predicción pura carece de ese criterio. Un buen regulador modela sólo la parte "
                   "control-relevante (good-regulator). UNE la rama control/acción con R-VALOR: el CONTROL es la fuente de la "
                   "relevancia (qué vale la pena modelar).").format(
                       lo=S2_SWEEP[0], pl=_f(pred_lo), cl=_f(ctrl_lo), gl=_f(gap_lo), hi=S2_SWEEP[-1], ph=_f(pred_hi),
                       pc=_f(pred_collapse), ch=_f(ctrl_hi), gh=_f(gap_hi))
    elif not pred_collapses or not ctrl_holds:
        status = "refutada"
        verdict = ("H-V4-10a REFUTADA: el control no es una fuente distinta de relevancia. predicción a distractor fuerte "
                   "{ph} (¿colapsa? {pcb}); control {ch} (¿gap>{g}? {chb}). Si la predicción no colapsa o el control no la "
                   "supera, predecir basta para hallar lo relevante.").format(
                       ph=_f(pred_hi), pcb=pred_collapses, ch=_f(ctrl_hi), g=GAP, chb=ctrl_holds)
    else:
        status = "mixta"
        verdict = ("H-V4-10a MIXTA: hay ventaja de control a distractor fuerte (gap {gh}, colapso predicción {pc}) pero el "
                   "crossover no es limpio (gap a distractor débil {gl}, caída de control {cs}).").format(
                       gh=_f(gap_hi), pc=_f(pred_collapse), gl=_f(gap_lo), cs=_f(ctrl_stable))

    return {"grid": grid, "gap_hi": gap_hi, "gap_lo": gap_lo, "pred_collapse": pred_collapse, "ctrl_stable": ctrl_stable,
            "crossover": bool(crossover), "pred_collapses": bool(pred_collapses), "ctrl_holds": bool(ctrl_holds),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=200)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 50

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp111] CYCLE 127 / H-V4-10a — ¿el CONTROL provee el criterio de RELEVANCIA (qué modelar) que la predicción no tiene? (abre rama control/acción)")
    log(f"[exp111] seeds={args.seeds} a={A} b={B} s1={S1} s2_sweep={S2_SWEEP} T={T} eval={EVAL}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    for arm in ("prediccion", "control"):
        row = " ".join(f"s2={s2}:{grid[arm][str(s2)]:.3f}" for s2 in S2_SWEEP)
        log(f"[exp111] {arm:>10} (control-perf de x1): {row}")
    log(f"[exp111] distractor DÉBIL (s2={S2_SWEEP[0]}): gap control-pred={sm['gap_lo']:+.3f} | distractor FUERTE (s2={S2_SWEEP[-1]}): gap={sm['gap_hi']:+.3f}")
    log(f"[exp111] colapso de PREDICCIÓN al crecer distractor={sm['pred_collapse']:+.3f} | caída de CONTROL={sm['ctrl_stable']:+.3f}")
    log(f"[exp111] crossover={sm['crossover']} pred_collapses={sm['pred_collapses']} ctrl_holds={sm['ctrl_holds']}")
    log(f"[exp111] VEREDICTO H-V4-10a: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp111_control_relevance", "cycle": 127, "hypothesis": "H-V4-10a",
           "claim": "un objetivo de CONTROL provee el criterio endogeno de RELEVANCIA (que vale la pena modelar) que la "
                    "prediccion pura no tiene: bajo capacidad limitada + distractor irrelevante de alta varianza, predecir "
                    "gasta la capacidad en el distractor ruidoso y colapsa el control, mientras controlar enfoca el modo "
                    "accionable y se mantiene (good-regulator) -> el control es la fuente de la relevancia; une la rama "
                    "control/accion con R-VALOR",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp111] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
