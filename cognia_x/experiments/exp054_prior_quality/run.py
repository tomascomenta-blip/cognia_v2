r"""
exp054 — CYCLE 69 / H-V4-3 (raíz FRESCA del thesis v4): la CALIDAD del prior > su forma. Un prior con la
ESTRUCTURA/EQUIVARIANZA correcta alcanza alta eficiencia muestral a fracción del costo; un prior EQUIVOCADO es
PEOR que no asumir nada (general) -- prueba que lo que importa es la CORRECCIÓN del prior, no tenerlo.

CONTEXTO: el thesis v4 lista R-PRIOR como raíz convergente ("la inducción desde k ejemplos es sub-determinada
(no-free-lunch): un prior fuerte es necesario; su CALIDAD, no su forma, fija la eficiencia muestral"). 'Programa
más corto / MDL / búsqueda de programas' es UNA apuesta de diseño, no la raíz. H-V4-3: un prior barato con la
SIMETRÍA correcta iguala/supera la eficiencia muestral, y un prior equivocado HUNDE.

TAREA (inducción con SIMETRÍA permutación-invariante): x in {0,1}^D; etiqueta y = 1 si sum(x) >= D/2 (depende
SÓLO del CONTEO de unos, no de QUÉ posiciones -> invariante a permutaciones). 3 priors = 3 feature maps para
una regresión logística (numpy):
  - correcto (perm-invariante): phi(x) = [sum(x)] -> 1 feature; el modelo aprende el umbral en 1-D -> muy
    eficiente muestralmente.
  - general (sin asumir simetría): phi(x) = [x_1..x_D] -> D features; debe APRENDER que todas las posiciones son
    equivalentes -> necesita más ejemplos.
  - equivocado (asume que sólo importan las primeras k posiciones): phi(x) = [x_1..x_k] -> k features; es un
    prior FUERTE pero FALSO -> sesgado, no puede representar la verdad -> peor que el general aun con muchos datos.
Métrica: test acc vs nº de ejemplos de entrenamiento (eficiencia muestral). seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el prior CORRECTO alcanza alta acc (>=0.90) con MUCHOS menos ejemplos que el general (eficiencia
    muestral) Y el prior EQUIVOCADO se queda por DEBAJO del general a n grande (un prior falso hunde). => la
    CALIDAD/corrección del prior es el lever, no su forma ni tenerlo.
  - REFUTADA si el correcto no es más eficiente que el general (el prior no ayuda) O el equivocado no es peor que
    el general (un prior falso no hunde).
  - MIXTA si una de las dos mitades se cumple y la otra no.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp054_prior_quality.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp054_prior_quality.run            # FULL
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
PRIORS = ["correcto", "general", "equivocado"]


def gen(rng, n, D):
    X = rng.integers(0, 2, size=(n, D))
    y = (X.sum(1) >= (D / 2.0)).astype(np.float64)      # permutación-invariante: depende sólo del conteo
    return X, y


def featurize(X, prior, D, k):
    if prior == "correcto":
        f = X.sum(1, keepdims=True).astype(np.float64) / D     # 1 feature: el conteo normalizado
    elif prior == "general":
        f = X.astype(np.float64)                                # D features crudas
    else:                                                       # equivocado: sólo las primeras k posiciones
        f = X[:, :k].astype(np.float64)
    return np.concatenate([f, np.ones((len(X), 1))], axis=1)    # + bias


def train_logreg(F, y, steps=1200, lr=0.8, l2=1e-4):
    w = np.zeros(F.shape[1])
    for _ in range(steps):
        z = F @ w
        p = 1.0 / (1.0 + np.exp(-z))
        grad = F.T @ (p - y) / len(y) + l2 * w
        w -= lr * grad
    return w


def acc(w, F, y):
    p = 1.0 / (1.0 + np.exp(-(F @ w)))
    return float(((p >= 0.5).astype(np.float64) == y).mean())


def run(D, k, n_trains, n_test, n_seeds):
    by_prior = {p: {str(nt): [] for nt in n_trains} for p in PRIORS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        Xte, yte = gen(rng, n_test, D)
        for nt in n_trains:
            Xtr, ytr = gen(rng, nt, D)
            for prior in PRIORS:
                Ftr = featurize(Xtr, prior, D, k)
                w = train_logreg(Ftr, ytr)
                a = acc(w, featurize(Xte, prior, D, k), yte)
                by_prior[prior][str(nt)].append(a)
    return {p: {nt: round(float(np.mean(by_prior[p][nt])), 4) for nt in by_prior[p]} for p in PRIORS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(curves, n_trains):
    nt_small = str(n_trains[1])           # pocos ejemplos
    nt_big = str(n_trains[-1])            # muchos ejemplos
    cor, gen_, wrong = curves["correcto"], curves["general"], curves["equivocado"]
    # eficiencia muestral: el correcto llega alto con POCOS ejemplos, muy por encima del general ahí.
    correct_efficient = cor[nt_small] >= 0.90 and (cor[nt_small] - gen_[nt_small]) > 0.10
    # un prior FALSO hunde: el equivocado queda por debajo del general a MUCHOS ejemplos.
    wrong_hurts = (gen_[nt_big] - wrong[nt_big]) > 0.05

    if correct_efficient and wrong_hurts:
        status = "apoyada"
        verdict = ("H-V4-3 APOYADA: la CALIDAD/corrección del prior es el lever, no su forma ni tenerlo. El prior "
                   "CORRECTO (perm-invariante, 1 feature) alcanza {cs} con sólo {ns} ejemplos (general {gs} ahí: "
                   "+{ds} de eficiencia muestral). El prior EQUIVOCADO (asume k posiciones) se queda en {wb} a "
                   "{nb} ejemplos, por DEBAJO del general {gb} -- un prior FALSO HUNDE (sesgo irreducible). => un "
                   "prior barato con la SIMETRÍA correcta iguala/supera la eficiencia, y uno falso es peor que no "
                   "asumir nada.").format(cs=_f(cor[nt_small]), ns=nt_small, gs=_f(gen_[nt_small]),
                                          ds=_f(cor[nt_small] - gen_[nt_small]), wb=_f(wrong[nt_big]), nb=nt_big,
                                          gb=_f(gen_[nt_big]))
    elif not correct_efficient:
        status = "refutada"
        verdict = ("H-V4-3 REFUTADA: el prior correcto no es más eficiente que el general a pocos ejemplos "
                   "(correcto {cs} vs general {gs} a {ns}).").format(cs=_f(cor[nt_small]), gs=_f(gen_[nt_small]),
                                                                    ns=nt_small)
    else:
        status = "mixta"
        verdict = ("H-V4-3 MIXTA: el prior correcto es eficiente (correcto {cs} vs general {gs} a {ns}) pero el "
                   "equivocado NO hunde claramente (equivocado {wb} vs general {gb} a {nb}).").format(
                       cs=_f(cor[nt_small]), gs=_f(gen_[nt_small]), ns=nt_small, wb=_f(wrong[nt_big]),
                       gb=_f(gen_[nt_big]), nb=nt_big)

    return {"n_trains": n_trains, "curves": curves, "nt_small": nt_small, "nt_big": nt_big,
            "correct_efficient": bool(correct_efficient), "wrong_hurts": bool(wrong_hurts),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--D", type=int, default=20)
    ap.add_argument("--k", type=int, default=3, help="prior equivocado: asume que sólo importan las primeras k posiciones")
    ap.add_argument("--n_trains", type=str, default="4,8,16,32,64,128")
    ap.add_argument("--n_test", type=int, default=3000)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.n_test = 8, 1500

    n_trains = [int(x) for x in args.n_trains.split(",")]
    logs = []

    def log(m):
        print(m, flush=True); logs.append(m)

    log(f"[exp054] CYCLE 69 / H-V4-3 — calidad del prior > forma (perm-invariante: y = sum(x)>=D/2)")
    log(f"[exp054] D={args.D} k_equivocado={args.k} n_trains={n_trains} seeds={args.seeds}")

    curves = run(args.D, args.k, n_trains, args.n_test, args.seeds)
    sm = build_summary(curves, n_trains)

    for prior in PRIORS:
        log(f"[exp054] {prior:>11} acc vs n: " + " ".join(f"n{nt}={curves[prior][str(nt)]:.3f}" for nt in n_trains))
    log(f"[exp054] VEREDICTO H-V4-3: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp054_prior_quality", "cycle": 69, "hypothesis": "H-V4-3",
           "claim": "la calidad/corrección del prior es el lever: un prior con la simetría correcta es eficiente "
                    "muestralmente y un prior falso hunde (peor que no asumir nada)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp054] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
