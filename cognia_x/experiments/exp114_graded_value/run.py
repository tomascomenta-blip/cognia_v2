r"""
exp114 — CYCLE 130 / H-V4-10d (rama control/acción, GENERALIZA el keystone 129 a GRADOS + COSTO y halla CUÁNDO importa el
producto): 129 mostró que el objetivo de control reconstruye R-VALOR = controlabilidad × relevancia, pero con
controlabilidad/relevancia BINARIAS y DISOCIADAS (los 4 cuadrantes). Este ciclo lo generaliza a GRADOS continuos (b,w∈(0,1)) +
COSTO cuadrático de acción ρ·u² (que es lo que hace que la controlabilidad GRADUADA importe), y pregunta CUÁNDO el producto
gana: barre la CORRELACIÓN entre controlabilidad y relevancia.

DERIVACIÓN (control de 1 paso con costo). Minimizar E[(x'−target)²+ρu²] con x'=a·x+b·u+ruido -> u*=b(target−a·x)/(b²+ρ), y el
BENEFICIO de modelar/regular el modo i = obj_pasivo−obj_modelado = E[(target−a·x)²]·b²/(b²+ρ). => valor de modelar i =
w_i·b_i²/(b_i²+ρ) = RELEVANCIA × CONTROLABILIDAD-descontada-por-costo (saturante en b). Es el producto graduado.

HALLAZGO PRECURSOR (smoke con factores independientes): si controlabilidad y relevancia son INDEPENDIENTES y graduadas, cada
factor por separado ya es informativo del producto -> la separación tajante del keystone binario NO aparece. La pregunta
correcta es CUÁNDO importa el producto: cuando los dos factores están DISOCIADOS (lo fácil de controlar ≠ lo que importa).

DISEÑO (numpy). D=10 modos; (b,w) graduados en (0,1) con CORRELACIÓN c barrida (anti / indep / corr). Acción vectorial; costo
ρ. Capacidad K=3. TODOS los criterios se evalúan PAREADOS sobre las MISMAS instancias por seed. 5 criterios: VALOR_COST
(w·b̂²/(b̂²+ρ)), VALOR_SIMPLE (w·b̂²), PREDICCION (varianza), CONTROLABILIDAD (b̂²/(b̂²+ρ)), RELEVANCIA (w). perf = fracción del
beneficio de control ALCANZABLE (vs oracle = asignar por el valor verdadero, control con params verdaderos).

PREGUNTA FALSABLE:
  - APOYADA si VALOR_COST es el criterio DOMINANTE (>= cada base de un solo factor en toda c) Y su MARGEN sobre la mejor base
    de un solo factor es GRANDE bajo DISOCIACIÓN (c<=0: anti/indep) y CHICO bajo correlación (c>0). => el producto R-VALOR
    generaliza a grados+costo, y su ventaja sobre asignar por un solo factor ESCALA con la disociación controlabilidad-
    relevancia (lo fácil de controlar ≠ lo importante). Une control/acción con la asignación cost-aware (101) y la
    complementariedad (83-86).
  - REFUTADA si el margen NO depende de la correlación o es uniformemente despreciable (el producto nunca aporta) -> la
    estructura producto no agrega en el régimen graduado.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp114_graded_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp114_graded_value.run            # FULL
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
RHO = 0.5
D = 10
K = 3
T = 400
EVAL = 400
CORRS = {"anti": -0.8, "indep": 0.0, "corr": 0.8}     # correlación controlabilidad-relevancia
ARMS = ("valor_cost", "valor_simple", "prediccion", "controlabilidad", "relevancia")


def _sig(z):
    return 1.0 / (1.0 + np.exp(-1.7 * z))


def _draw_modes(rng, c):
    g1 = rng.normal(0, 1, size=D)
    g2 = c * g1 + np.sqrt(max(0.0, 1.0 - c ** 2)) * rng.normal(0, 1, size=D)
    b = _sig(g1)                                   # controlabilidad ∈ (0,1)
    w = _sig(g2)                                   # relevancia ∈ (0,1), corr≈c con b
    s = rng.uniform(0.5, 1.5, size=D)              # ruido de proceso (independiente -> predicción es señal débil)
    return b, w, s


def _rollout(rng, n, b, s):
    u = rng.normal(0, 1, size=(n, D))
    x = np.zeros((n, D)); xn = np.zeros((n, D)); cc = np.zeros(D)
    for t in range(n):
        x[t] = cc
        cn = AA * cc + b * u[t] + rng.normal(0, 1, size=D) * s
        xn[t] = cn
        cc = cn
    return x, xn, u


def _fit(xc, xn, u):
    coef, *_ = np.linalg.lstsq(np.stack([xc, u], axis=1), xn, rcond=None)
    return float(coef[0]), float(coef[1])


def _obj_on(modeled, ahat, bhat, b, target, x, noise):
    """objetivo de control por modo (x'−target)²+ρu² con u* cost-aware en los modelados. Eval PAREADO (target,x,noise dados)."""
    obj = np.zeros(D)
    for i in range(D):
        if i in modeled:
            bh = bhat[i] if abs(bhat[i]) > 1e-9 else 1e-9
            u_i = bh * (target[:, i] - ahat[i] * x[:, i]) / (bh ** 2 + RHO)
        else:
            u_i = np.zeros(target.shape[0])
        xn_i = AA * x[:, i] + b[i] * u_i + noise[:, i]
        obj[i] = float(np.mean((xn_i - target[:, i]) ** 2 + RHO * u_i ** 2))
    return obj


def run_corr(c, n_seeds):
    perf = {arm: [] for arm in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 4639 + int((c + 1) * 1000) * 17 + 13)
        b, w, s = _draw_modes(rng, c)
        x, xn, u = _rollout(rng, T, b, s)
        ahat = np.zeros(D); bhat = np.zeros(D); var = np.zeros(D)
        for i in range(D):
            ahat[i], bhat[i] = _fit(x[:, i], xn[:, i], u[:, i])
            var[i] = np.var(xn[:, i])
        bh2 = bhat ** 2
        scores = {
            "valor_cost": w * bh2 / (bh2 + RHO),
            "valor_simple": w * bh2,
            "prediccion": var,
            "controlabilidad": bh2 / (bh2 + RHO),
            "relevancia": w + rng.normal(0, 1e-9, size=D),
        }
        # eval PAREADO: mismas instancias para todos los arms y el oracle
        target = rng.normal(0, 1, size=(EVAL, D)); xe = rng.normal(0, 1, size=(EVAL, D)); noise = rng.normal(0, 1, size=(EVAL, D)) * s
        obj_pass = _obj_on(set(), ahat, bhat, b, target, xe, noise)
        true_val = w * b ** 2 / (b ** 2 + RHO)
        oracle_set = set(np.argsort(true_val)[-K:].tolist())
        obj_oracle = _obj_on(oracle_set, np.full(D, AA), b, b, target, xe, noise)   # oracle: params verdaderos
        den = float(np.sum(w * (obj_pass - obj_oracle))) + 1e-9
        for arm in ARMS:
            modeled = set(np.argsort(scores[arm])[-K:].tolist())
            obj_m = _obj_on(modeled, ahat, bhat, b, target, xe, noise)
            num = float(np.sum(w * (obj_pass - obj_m)))
            perf[arm].append(max(0.0, num / den))
    return {arm: round(float(np.mean(perf[arm])), 4) for arm in ARMS}


def run(n_seeds):
    return {cn: run_corr(c, n_seeds) for cn, c in CORRS.items()}


def _f(x):
    return "{:.3f}".format(x)


def _best_base(row):
    bases = {k: row[k] for k in ("prediccion", "controlabilidad", "relevancia")}
    bn = max(bases, key=lambda a: bases[a])
    return bn, bases[bn]


def build_summary(grid):
    margins = {}
    dominant = True
    for cn in CORRS:
        row = grid[cn]
        bn, bb = _best_base(row)
        margins[cn] = round(row["valor_cost"] - bb, 4)
        if row["valor_cost"] < max(row[k] for k in ("valor_simple", "prediccion", "controlabilidad", "relevancia")) - 1e-6:
            dominant = False

    m_anti, m_corr = margins["anti"], margins["corr"]
    scales_with_dissociation = (m_anti > m_corr + 0.10) and (m_anti > 0.15)

    if dominant and scales_with_dissociation:
        status = "apoyada"
        verdict = ("H-V4-10d APOYADA (el producto generaliza a GRADOS+COSTO y su ventaja escala con la DISOCIACIÓN): "
                   "VALOR_COST (w·b̂²/(b̂²+ρ)) es el criterio DOMINANTE en toda la correlación, y su MARGEN sobre la mejor "
                   "base de un solo factor ESCALA con la disociación controlabilidad-relevancia: ANTI-correlacionados +{ma} "
                   "(lo fácil de controlar ≠ lo importante -> elegir por un solo factor falla), INDEP +{mi}, CORRELACIONADOS "
                   "+{mc} (cuando controlar e importar coinciden, un solo factor casi basta). => el producto R-VALOR que el "
                   "control reconstruye (129) NO era artefacto de lo binario: generaliza a grados + costo de acción, y MÁS "
                   "importa cuanto más DISOCIADAS están controlabilidad y relevancia. Une control/acción con la asignación "
                   "cost-aware (101) y la complementariedad (83-86).").format(
                       ma=_f(m_anti), mi=_f(margins["indep"]), mc=_f(m_corr))
    elif not scales_with_dissociation and not dominant:
        status = "refutada"
        verdict = ("H-V4-10d REFUTADA: el producto no domina o su margen no depende de la disociación (anti +{ma} vs corr "
                   "+{mc}). La estructura producto no agrega en el régimen graduado.").format(ma=_f(m_anti), mc=_f(m_corr))
    else:
        status = "mixta"
        verdict = ("H-V4-10d MIXTA: VALOR_COST dominante={dom} pero el escalado con la disociación no es limpio (anti +{ma}, "
                   "indep +{mi}, corr +{mc}).").format(dom=dominant, ma=_f(m_anti), mi=_f(margins["indep"]), mc=_f(m_corr))

    return {"grid": grid, "margins": margins, "dominant": bool(dominant),
            "scales_with_dissociation": bool(scales_with_dissociation), "status": status, "verdict": verdict}


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

    log("[exp114] CYCLE 130 / H-V4-10d — el producto ctrl×rel a GRADOS+COSTO: ¿domina y su ventaja escala con la DISOCIACIÓN controlabilidad-relevancia?")
    log(f"[exp114] seeds={args.seeds} D={D} K={K} rho={RHO} a={AA} T={T} eval={EVAL} corrs={CORRS}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    for cn in CORRS:
        row = grid[cn]
        bn, bb = _best_base(row)
        log(f"[exp114] corr={cn:>6}({CORRS[cn]:+.1f}): valor_cost={row['valor_cost']:.3f} valor_simple={row['valor_simple']:.3f} pred={row['prediccion']:.3f} ctrl={row['controlabilidad']:.3f} relev={row['relevancia']:.3f} | margen(vs {bn})=+{sm['margins'][cn]:.3f}")
    log(f"[exp114] dominante={sm['dominant']} escala_con_disociacion={sm['scales_with_dissociation']} (anti +{sm['margins']['anti']:.3f} vs corr +{sm['margins']['corr']:.3f})")
    log(f"[exp114] VEREDICTO H-V4-10d: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp114_graded_value", "cycle": 130, "hypothesis": "H-V4-10d",
           "claim": "el producto R-VALOR = relevancia x controlabilidad(-descontada-por-costo) que el control reconstruye "
                    "(129) generaliza del regimen BINARIO al GRADUADO continuo + COSTO de accion; es el criterio dominante y "
                    "su ventaja sobre asignar por un solo factor ESCALA con la DISOCIACION entre controlabilidad y relevancia "
                    "(grande cuando lo facil de controlar != lo importante, chica cuando coinciden) -> une control/accion con "
                    "la asignacion cost-aware (101) y la complementariedad (83-86)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp114] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
