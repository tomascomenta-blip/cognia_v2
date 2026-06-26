r"""
exp113 — CYCLE 129 / H-V4-10c (rama control/acción, KEYSTONE: el objetivo de CONTROL reconstruye R-VALOR = CONTROLABILIDAD ×
RELEVANCIA): 127 mostró que el control es la fuente de la relevancia; 128 que la partición controlable es DESCUBRIBLE
actuando. Este ciclo cierra el lazo con la TESIS CENTRAL del lab (79-82: R-VALOR = controlabilidad × relevancia): con
capacidad de modelado MULTI-UNIDAD y modos que varían en controlabilidad Y relevancia, ¿un objetivo de CONTROL asigna su
capacidad por el PRODUCTO controlabilidad × relevancia -- batiendo a cada factor por separado? Si sí, el producto value=
ctrl×rel EMERGE del objetivo de control (no se postula); la tesis 79-82 tiene su RAÍZ en el control.

DISEÑO (numpy). D=8 modos, 2 en cada cuadrante de (CONTROLABLE b∈{1,0}) × (RELEVANTE w∈{1,0}); los uncont+irrel son RUIDOSOS
(alta varianza) para tentar a la predicción. Acción vectorial u∈R^D, u_i excita el modo i: x_i' = a·x_i + b_i·u_i + N(0,s_i).
El agente tiene capacidad k (modela k de D modos: estima â_i,b̂_i; el resto u_i=0, pasivo). Estima de T datos: b̂_i
(controlabilidad, regresión de x_i' sobre [x_i,u_i]) y la varianza. La relevancia w_i la da su PROPIO objetivo (las cosas que
le importan). 4 criterios de asignación de la capacidad k:
  - VALOR        rank por w_i·b̂_i²   (relevancia × controlabilidad estimada) -- el producto R-VALOR
  - PREDICCION   rank por varianza    (tentado por los distractores ruidosos)
  - CONTROLABIL. rank por b̂_i²        (ignora la relevancia)
  - RELEVANCIA   rank por w_i          (ignora la controlabilidad)
TAREA: regulación de 1 paso de cada modo a un target, ponderada por w_i. perf = fracción del beneficio de control ALCANZABLE
ponderado (vs oracle = modelar los k modos de mayor valor verdadero w_i·b_i). El orden de los modos se MEZCLA por seed (para
que los empates de los criterios de un solo factor promedien).

PREGUNTA FALSABLE:
  - APOYADA si VALOR (w·b̂²) supera a las TRES líneas base de un solo factor (predicción/controlabilidad/relevancia) por un
    margen: sólo el PRODUCTO captura los modos controlable-Y-relevante; controlabilidad-sola modela controlable-pero-
    irrelevante, relevancia-sola modela relevante-pero-incontrolable (no se puede regular), predicción modela el ruido. =>
    el objetivo de CONTROL reconstruye R-VALOR = controlabilidad × relevancia (la tesis 79-82 emerge de la raíz del control).
  - REFUTADA si VALOR no supera a la MEJOR línea base de un solo factor -> el producto no es necesario / no emerge del control.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp113_value_factorization.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp113_value_factorization.run            # FULL
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
K = 2                  # capacidad: modela K de D modos
T = 300                # datos acción-resultado para estimar b̂_i
EVAL = 300
# 8 modos, 2 por cuadrante: (b controlabilidad, w relevancia, s ruido de proceso)
MODES = [
    (1.0, 1.0, 1.0), (1.0, 1.0, 1.0),     # CONTROLABLE + RELEVANTE  -> los que valen (valor=1)
    (1.0, 0.0, 1.0), (1.0, 0.0, 1.0),     # controlable + irrelevante (tienta a controlabilidad-sola)
    (0.0, 1.0, 1.0), (0.0, 1.0, 1.0),     # incontrolable + relevante (tienta a relevancia-sola; no se puede regular)
    (0.0, 0.0, 3.0), (0.0, 0.0, 3.0),     # incontrolable + irrelevante, RUIDOSO (tienta a la predicción)
]
ARMS = ("valor", "prediccion", "controlabilidad", "relevancia")


def _rollout(rng, n, bb, ss):
    """rollout excitado con acción vectorial; bb,ss = vectores por modo. Devuelve x (cur), xn (next), u  (n×D)."""
    D = len(bb)
    u = rng.normal(0, 1, size=(n, D))
    x = np.zeros((n, D)); xn = np.zeros((n, D))
    c = np.zeros(D)
    for t in range(n):
        x[t] = c
        cn = AA * c + bb * u[t] + rng.normal(0, 1, size=D) * ss
        xn[t] = cn
        c = cn
    return x, xn, u


def _fit_mode(xc, xn, u):
    w, *_ = np.linalg.lstsq(np.stack([xc, u], axis=1), xn, rcond=None)
    return float(w[0]), float(w[1])     # â, b̂


def _weighted_perf(rng, modeled, ahat, bhat, bb, ww, n):
    """regulación de 1 paso por modo (modeled=set de índices modelados), ponderada por w. Fracción del beneficio ALCANZABLE
    (vs oracle = modelar los K modos de mayor w·b verdadero), pareada en targets/ruido."""
    D = len(bb)
    target = rng.normal(0, 1, size=(n, D))
    x = rng.normal(0, 1, size=(n, D))
    noise = rng.normal(0, 1, size=(n, D))     # ruido base; se escala por s en el paso real (cancelado en la fracción)
    # u por modo: si modelado -> u=(target-â x)/b̂ ; si no -> 0
    err_pass = np.abs(AA * x + noise - target)                      # sin control
    # oracle: modela los K de mayor w·b verdadero (los controlable+relevante)
    true_val = ww * bb
    oracle_set = set(np.argsort(true_val)[-K:].tolist())
    def err_for(mset, ah, bh):
        e = np.empty((n, D))
        for i in range(D):
            if i in mset:
                bh_i = bh[i] if abs(bh[i]) > 1e-6 else 1e-6
                u_i = (target[:, i] - ah[i] * x[:, i]) / bh_i
                xn_i = AA * x[:, i] + bb[i] * u_i + noise[:, i]     # dinámica REAL usa bb[i] (b=0 -> no se puede regular)
                e[:, i] = np.abs(xn_i - target[:, i])
            else:
                e[:, i] = err_pass[:, i]
        return e
    err_model = err_for(modeled, ahat, bhat)
    err_oracle = err_for(oracle_set, np.full(D, AA), bb)   # oracle usa el modelo verdadero (â=AA, b̂=b)
    num = float(np.sum(ww * (np.mean(err_pass, axis=0) - np.mean(err_model, axis=0))))
    den = float(np.sum(ww * (np.mean(err_pass, axis=0) - np.mean(err_oracle, axis=0)))) + 1e-9
    return max(0.0, num / den)


def run_arm(arm, n_seeds):
    perfs = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 5471 + ARMS.index(arm) * 70001 + 11)
        order = rng.permutation(len(MODES))                        # mezcla los modos (promedia empates)
        bb = np.array([MODES[i][0] for i in order])
        ww = np.array([MODES[i][1] for i in order])
        ss = np.array([MODES[i][2] for i in order])
        D = len(bb)
        x, xn, u = _rollout(rng, T, bb, ss)
        ahat = np.zeros(D); bhat = np.zeros(D); var = np.zeros(D)
        for i in range(D):
            ahat[i], bhat[i] = _fit_mode(x[:, i], xn[:, i], u[:, i])
            var[i] = np.var(xn[:, i])
        if arm == "valor":
            score = ww * bhat ** 2
        elif arm == "prediccion":
            score = var
        elif arm == "controlabilidad":
            score = bhat ** 2
        else:  # relevancia
            score = ww + rng.normal(0, 1e-6, size=D)               # romper empates al azar
        modeled = set(np.argsort(score)[-K:].tolist())
        perfs.append(_weighted_perf(rng, modeled, ahat, bhat, bb, ww, EVAL))
    return round(float(np.mean(perfs)), 4)


def run(n_seeds):
    return {arm: run_arm(arm, n_seeds) for arm in ARMS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    val = grid["valor"]
    best_base = max(grid["prediccion"], grid["controlabilidad"], grid["relevancia"])
    base_name = max(("prediccion", "controlabilidad", "relevancia"), key=lambda a: grid[a])
    margin = round(val - best_base, 4)

    MARG = 0.20
    value_wins = margin > MARG and val > 0.7

    if value_wins:
        status = "apoyada"
        verdict = ("H-V4-10c APOYADA (el control reconstruye R-VALOR = ctrl × rel): el criterio VALOR (relevancia × "
                   "controlabilidad estimada, w·b̂²) asigna la capacidad de modelado MEJOR que cualquier factor por separado "
                   "-- VALOR {v} vs mejor base ({bn}) {bb} (margen +{m}). Sólo el PRODUCTO captura los modos "
                   "controlable-Y-relevante: la PREDICCIÓN {p} modela el ruido, CONTROLABILIDAD-sola {c} modela "
                   "controlable-pero-irrelevante, RELEVANCIA-sola {r} modela relevante-pero-incontrolable (no se puede "
                   "regular). => el objetivo de CONTROL RECONSTRUYE R-VALOR = controlabilidad × relevancia: la tesis central "
                   "del lab (79-82) EMERGE de la raíz del control, no se postula.").format(
                       v=_f(val), bn=base_name, bb=_f(best_base), m=_f(margin), p=_f(grid["prediccion"]),
                       c=_f(grid["controlabilidad"]), r=_f(grid["relevancia"]))
    elif margin <= MARG:
        status = "refutada"
        verdict = ("H-V4-10c REFUTADA: VALOR {v} no supera a la mejor línea base de un solo factor ({bn} {bb}, margen +{m} "
                   "<= {mg}) -> el producto controlabilidad×relevancia no es necesario / no emerge del control.").format(
                       v=_f(val), bn=base_name, bb=_f(best_base), m=_f(margin), mg=MARG)
    else:
        status = "mixta"
        verdict = ("H-V4-10c MIXTA: VALOR supera a la mejor base (margen +{m}) pero VALOR {v} es bajo (<0.7) -> el producto "
                   "ayuda pero no captura limpio el óptimo.").format(m=_f(margin), v=_f(val))

    return {"grid": grid, "value": val, "best_base": best_base, "best_base_name": base_name, "margin": margin,
            "value_wins": bool(value_wins), "status": status, "verdict": verdict}


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

    log("[exp113] CYCLE 129 / H-V4-10c — ¿el objetivo de CONTROL reconstruye R-VALOR = controlabilidad × relevancia? (keystone: une la rama control con la tesis 79-82)")
    log(f"[exp113] seeds={args.seeds} D={len(MODES)} K={K} a={AA} T={T} eval={EVAL}")
    log(f"[exp113] modos (b,w,s): {MODES}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    for arm in ARMS:
        log(f"[exp113] {arm:>16} (perf de control ponderada): {grid[arm]:.3f}")
    log(f"[exp113] VALOR={sm['value']:.3f} vs mejor base ({sm['best_base_name']})={sm['best_base']:.3f} | margen +{sm['margin']:.3f}")
    log(f"[exp113] value_wins={sm['value_wins']}")
    log(f"[exp113] VEREDICTO H-V4-10c: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp113_value_factorization", "cycle": 129, "hypothesis": "H-V4-10c",
           "claim": "un objetivo de CONTROL con capacidad de modelado limitada asigna su capacidad por el PRODUCTO "
                    "controlabilidad x relevancia (w·b^2 estimado), batiendo a cada factor por separado (prediccion=varianza, "
                    "controlabilidad-sola, relevancia-sola) -> el objetivo de control RECONSTRUYE R-VALOR = controlabilidad x "
                    "relevancia; la tesis central 79-82 emerge de la raiz del control",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp113] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
