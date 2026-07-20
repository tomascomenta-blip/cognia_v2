r"""
exp112 — CYCLE 128 / H-V4-10b (rama control/acción, CIERRA el caveat principal de 127): 127 mostró que un objetivo de CONTROL
enfoca la capacidad en el modo CONTROLABLE-relevante y no en el distractor ruidoso -- PERO le DABA al agente la partición
(sabía cuál modo era accionable). Este ciclo cierra ese caveat: ¿el agente DESCUBRE qué es controlable de sus PROPIOS datos
acción-resultado, sin que se le diga? Si sí, "el control es la fuente de la relevancia" (127) se fortalece a "el control
DESCUBRE la relevancia ACTUANDO" -- el claim fuerte del good-regulator, anclado en R-INTERVENCIÓN (aprendés qué controlás
interviniendo).

DISEÑO (numpy, extiende exp111). Mismo sistema 2D: x1 CONTROLABLE (x1'=a·x1+b·u+N(0,s1)), x2 distractor INCONTROLABLE
(x2'=a·x2+N(0,s2)), s2 barrido. Tres arms con cuello de botella capacidad-1:
  - PREDICCION: asigna al modo de mayor VARIANZA (minimiza MSE de predicción). [colapsa, como 127]
  - CONTROL-ORACLE: asigna al modo controlable CONOCIDO (x1). [robusto, referencia de 127]
  - CONTROL-DISCOVERY: NO sabe la partición. Estima la CONTROLABILIDAD de cada modo regresando x_i' sobre [x_i, u] y tomando
    |b̂_i|; asigna al modo de mayor |b̂_i| ESTIMADO. (Descubre lo accionable de sus propios datos de acción.)
Métrica de control: idéntica a exp111 (fracción del beneficio de control ALCANZABLE, normalizada por el oráculo, indep. del
ruido). Se barre además el presupuesto de datos T (poco/mucho) para ver si descubrir necesita suficiente data interventiva.

PREGUNTA FALSABLE:
  - APOYADA si CONTROL-DISCOVERY ≈ CONTROL-ORACLE en todo el barrido del distractor (ambos robustos, ambos >> PREDICCION a
    distractor fuerte) Y DISCOVERY elige el modo controlable correcto con alta frecuencia -- SIN que se le diga la partición.
    => la partición de relevancia (qué es controlable) es DESCUBRIBLE de los datos acción-resultado actuando; cierra el
    caveat de 127 y ancla "control = fuente de relevancia" en R-INTERVENCIÓN.
  - REFUTADA si DISCOVERY NO recupera el modo controlable (colapsa como PREDICCION) -> la partición no se descubre actuando,
    el control-relevancia de 127 dependía de saberla.
  - MIXTA en otro caso (p.ej. descubre sólo con mucha data).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp112_control_discovery.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp112_control_discovery.run            # FULL
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
A = 0.6
B = 1.0
S1 = 1.0
S2_SWEEP = [0.5, 1.0, 2.0, 4.0]
T_SWEEP = [12, 200]          # presupuesto de datos acción-resultado: POCO (descubrir es difícil) vs MUCHO
EVAL = 200
ARMS = ("prediccion", "control_oracle", "control_discovery")


def _fit_mode(x_cur, x_nxt, u):
    if u is None:
        w, *_ = np.linalg.lstsq(x_cur.reshape(-1, 1), x_nxt, rcond=None)
        return float(w[0]), 0.0
    w, *_ = np.linalg.lstsq(np.stack([x_cur, u], axis=1), x_nxt, rcond=None)
    return float(w[0]), float(w[1])


def _ctrlability(x_cur, x_nxt, u):
    """|b̂| estimado = cuánto influye u sobre el next-state del modo (regresión x_nxt ~ [x_cur, u])."""
    _, b = _fit_mode(x_cur, x_nxt, u)
    return abs(b)


def _rollout(rng, n, s2):
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
    if abs(b_hat) < 1e-6:
        b_hat = 1e-6 * (1.0 if b_hat >= 0 else -1.0)
    x1 = rng.normal(0, 1, size=n); target = rng.normal(0, 1, size=n); noise = rng.normal(0, S1, size=n)
    u_model = (target - a_hat * x1) / b_hat
    err_model = np.abs(A * x1 + B * u_model + noise - target)
    err_oracle = np.abs(noise)
    err_pass = np.abs(A * x1 + noise - target)
    benefit = float(np.mean(err_pass) - np.mean(err_oracle)) + 1e-9
    return round(max(0.0, float(np.mean(err_pass) - np.mean(err_model)) / benefit), 4)


def run_arm(arm, s2, T, n_seeds):
    perfs = []
    picks_correct = 0
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 6271 + int(s2 * 100) * 19 + T * 131 + ARMS.index(arm) * 40009 + 5)
        x1, x2, x1n, x2n, u = _rollout(rng, T, s2)
        if arm == "prediccion":
            pick1 = np.var(x1n) >= np.var(x2n)                 # mayor varianza
        elif arm == "control_oracle":
            pick1 = True                                       # sabe que x1 es el controlable
        else:  # control_discovery: estima la controlabilidad de cada modo de sus propios datos
            pick1 = _ctrlability(x1, x1n, u) >= _ctrlability(x2, x2n, u)
        if pick1:
            a_hat, b_hat = _fit_mode(x1, x1n, u)
            picks_correct += 1
        else:
            a_hat, b_hat = _fit_mode(x2, x2n, None)
        perfs.append(_control_perf(rng, a_hat, b_hat, EVAL))
    return round(float(np.mean(perfs)), 4), round(picks_correct / n_seeds, 4)


def run(n_seeds):
    # grid[T][arm][s2] = {perf, pick1}
    grid = {}
    for T in T_SWEEP:
        grid[str(T)] = {}
        for arm in ARMS:
            grid[str(T)][arm] = {}
            for s2 in S2_SWEEP:
                p, pc = run_arm(arm, s2, T, n_seeds)
                grid[str(T)][arm][str(s2)] = {"perf": p, "pick1": pc}
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    hiT = str(T_SWEEP[-1])           # mucha data: descubrir debería funcionar
    loT = str(T_SWEEP[0])            # poca data
    hs2 = str(S2_SWEEP[-1])          # distractor fuerte (donde predicción colapsa)
    ls2 = str(S2_SWEEP[0])

    disc_hi = grid[hiT]["control_discovery"][hs2]["perf"]      # discovery, mucha data, distractor fuerte
    orac_hi = grid[hiT]["control_oracle"][hs2]["perf"]         # oracle, idem
    pred_hi = grid[hiT]["prediccion"][hs2]["perf"]             # predicción, idem (colapsa)
    disc_pick_hi = grid[hiT]["control_discovery"][hs2]["pick1"]   # frecuencia de elegir el modo controlable
    disc_lo = grid[loT]["control_discovery"][hs2]["perf"]      # discovery con POCA data (distractor fuerte)

    GAP = 0.30
    discovery_matches_oracle = abs(disc_hi - orac_hi) < 0.15 and disc_hi > pred_hi + GAP
    discovery_picks_right = disc_pick_hi > 0.8
    data_dependence = disc_hi - disc_lo                        # cuánto ayuda tener más data interventiva

    if discovery_matches_oracle and discovery_picks_right:
        status = "apoyada"
        verdict = ("H-V4-10b APOYADA (la relevancia es DESCUBRIBLE actuando): con datos acción-resultado suficientes (T={ht}) "
                   "y distractor FUERTE (s2={hs}), CONTROL-DISCOVERY -- que NO sabe la partición y estima la controlabilidad "
                   "|b̂| de cada modo de sus propios datos -- iguala al CONTROL-ORACLE ({dh}≈{oh}) y supera a la PREDICCIÓN "
                   "que colapsa ({ph}); elige el modo controlable correcto el {pk} de las veces. => la PARTICIÓN de relevancia "
                   "(qué es controlable) es DESCUBRIBLE de los datos acción-resultado ACTUANDO -- cierra el caveat de 127 (no "
                   "hace falta darle la partición) y ancla 'control = fuente de relevancia' en R-INTERVENCIÓN: aprendés qué "
                   "controlás interviniendo. Dependencia de datos: con poca data (T={lt}) discovery rinde {dl} (Δ{dd} vs mucha "
                   "data) -- descubrir necesita suficiente acción.").format(
                       ht=T_SWEEP[-1], hs=S2_SWEEP[-1], dh=_f(disc_hi), oh=_f(orac_hi), ph=_f(pred_hi), pk=_f(disc_pick_hi),
                       lt=T_SWEEP[0], dl=_f(disc_lo), dd=_f(data_dependence))
    elif not discovery_matches_oracle:
        status = "refutada"
        verdict = ("H-V4-10b REFUTADA: CONTROL-DISCOVERY no recupera el modo controlable (perf {dh} vs oracle {oh}, pred {ph}, "
                   "pick {pk}). La partición no se descubre actuando -> el control-relevancia de 127 dependía de saberla.").format(
                       dh=_f(disc_hi), oh=_f(orac_hi), ph=_f(pred_hi), pk=_f(disc_pick_hi))
    else:
        status = "mixta"
        verdict = ("H-V4-10b MIXTA: discovery iguala al oracle ({dh}≈{oh}) pero el pick del modo correcto no es robusto "
                   "({pk}) o la dependencia de datos domina (Δ{dd}).").format(
                       dh=_f(disc_hi), oh=_f(orac_hi), pk=_f(disc_pick_hi), dd=_f(data_dependence))

    return {"grid": grid, "disc_hi": disc_hi, "orac_hi": orac_hi, "pred_hi": pred_hi, "disc_pick_hi": disc_pick_hi,
            "disc_lo": disc_lo, "data_dependence": round(data_dependence, 4),
            "discovery_matches_oracle": bool(discovery_matches_oracle), "discovery_picks_right": bool(discovery_picks_right),
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

    log("[exp112] CYCLE 128 / H-V4-10b — ¿el CONTROL DESCUBRE qué es controlable (la partición de relevancia) de sus datos acción-resultado, sin que se le diga?")
    log(f"[exp112] seeds={args.seeds} a={A} b={B} s1={S1} s2_sweep={S2_SWEEP} T_sweep={T_SWEEP} eval={EVAL}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    for T in T_SWEEP:
        for arm in ARMS:
            row = " ".join(f"s2={s2}:{grid[str(T)][arm][str(s2)]['perf']:.3f}" for s2 in S2_SWEEP)
            extra = ""
            if arm == "control_discovery":
                extra = "  pick1=[" + ",".join(f"{grid[str(T)][arm][str(s2)]['pick1']:.2f}" for s2 in S2_SWEEP) + "]"
            log(f"[exp112] T={T:>3} {arm:>17}: {row}{extra}")
    log(f"[exp112] (T={T_SWEEP[-1]}, distractor fuerte s2={S2_SWEEP[-1]}): discovery={sm['disc_hi']:.3f} oracle={sm['orac_hi']:.3f} predicción={sm['pred_hi']:.3f} | pick_correcto={sm['disc_pick_hi']:.2f}")
    log(f"[exp112] dependencia de datos (discovery T{T_SWEEP[-1]} - T{T_SWEEP[0]})={sm['data_dependence']:+.3f}")
    log(f"[exp112] discovery_matches_oracle={sm['discovery_matches_oracle']} discovery_picks_right={sm['discovery_picks_right']}")
    log(f"[exp112] VEREDICTO H-V4-10b: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp112_control_discovery", "cycle": 128, "hypothesis": "H-V4-10b",
           "claim": "un objetivo de control DESCUBRE que dimensiones son controlables (la particion de relevancia) de sus "
                    "propios datos accion-resultado -estimando |b| de cada modo- sin que se le diga: control-discovery iguala "
                    "al control-oracle y supera a la prediccion que colapsa, eligiendo el modo controlable correcto -> la "
                    "relevancia es DESCUBRIBLE actuando (R-INTERVENCION); cierra el caveat de 127",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp112] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
