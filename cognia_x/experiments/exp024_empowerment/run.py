r"""
exp024 — CYCLE 38 / H-V4-1c: ¿un valor AUTO-generado (EMPOWERMENT) captura "lo que puedo afectar"
que la predicción pasiva NO puede?

Contexto (deriva de CYCLE 36/37): H-V4-1b mostró que el info-gain NO es el lever (≈ azar-activo). Pero el
barrido de literatura (literature_v4.md) dice que el EMPOWERMENT — un valor AUTO-generado, sin reward ni
verificador externo — sí talla estructura causal/controlable (arXiv:2606.20104, EELMA arXiv:2509.22504,
Blahut-Arimoto arXiv:2510.05996). Esta es la forma FUERTE de R-VALOR. Si tampoco funciona, el reset pivota
del todo a R-INTERVENCIÓN/act-and-verify.

IDEA RAÍZ (analogía cotidiana): un bebé descubre que SU mano se mueve cuando él quiere (controlable) y la
distingue de un reloj de pared que también se mueve solo (predecible pero NO suyo) y de las motas de polvo
(aleatorias). Lo que le importa a un AGENTE no es lo PREDECIBLE, es lo que PUEDE AFECTAR.

DISEÑO (numpy puro, CPU). Mundo con 3 tipos de factor (cada uno toma K valores):
  - CONTROLABLE: f' = acción del agente (con ruido η). El agente lo fija.
  - RELOJ: f' = (f+1) mod K (con ruido η). Perfectamente PREDECIBLE pero IGNORA la acción.
  - ALEATORIO: f' = uniforme. Ni predecible ni controlable.
Dos medidas POR FACTOR, ambas estimadas por muestreo (acciones uniformes):
  - EMPOWERMENT E_i = capacidad de canal a -> f_i' (Blahut-Arimoto, bits). Mide CONTROLABILIDAD.
  - PREDICTIBILIDAD pasiva P_i = I(f_i,t ; f_i,t+1) (bits). Mide qué tan predecible es desde el estado, SIN
    usar la acción como lever (lo que ve un predictor pasivo).

PREDICCIÓN FALSABLE (pre-registrada):
  (a) APOYADA si se da la INVERSIÓN: el EMPOWERMENT se queda con el CONTROLABLE (E_ctrl >> E_reloj, E_rand)
      Y la PREDICCIÓN pasiva se queda con el RELOJ y PIERDE el controlable (P_reloj >> P_ctrl). Margen >0.8 bits.
      => un valor auto-generado (empowerment) captura "lo que puedo afectar" que la predicción pasiva no.
  (b) REFUTADA si E_ctrl no supera a E_reloj por >0.8 bits (el empowerment no distingue controlable de reloj).
  (c) MIXTA si parcial (p.ej. empowerment acierta pero no hay inversión clara en predicción).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp024_empowerment.run
  (opcional) --K 4 --eta 0.05 --n_factors 2 --samples 20000 --seeds 12
"""
import argparse
import json
import os
import platform
import sys
import time

import numpy as np


HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def blahut_arimoto(p_y_given_x, n_iter=300, tol=1e-10):
    """Capacidad de canal C = max_{p(x)} I(X;Y) en BITS, dado p(y|x) (matriz X×Y). Algoritmo estándar."""
    X = p_y_given_x.shape[0]
    r = np.ones(X) / X
    for _ in range(n_iter):
        q = r[:, None] * p_y_given_x                      # (X,Y) no normalizado
        q = q / (q.sum(axis=0, keepdims=True) + 1e-12)    # q(x|y)
        logr = np.sum(p_y_given_x * np.log(q + 1e-12), axis=1)
        r_new = np.exp(logr - logr.max())
        r_new = r_new / r_new.sum()
        if np.max(np.abs(r_new - r)) < tol:
            r = r_new
            break
        r = r_new
    q = r[:, None] * p_y_given_x
    q = q / (q.sum(axis=0, keepdims=True) + 1e-12)
    C = np.sum(r[:, None] * p_y_given_x * np.log((q + 1e-12) / (r[:, None] + 1e-12)))
    return float(C / np.log(2))


def mutual_info_bits(x, y, K):
    """I(X;Y) en bits desde muestras de enteros en [0,K)."""
    joint = np.zeros((K, K))
    np.add.at(joint, (x, y), 1.0)
    joint /= joint.sum()
    px = joint.sum(1)
    py = joint.sum(0)
    mi = 0.0
    nz = joint > 0
    mi = np.sum(joint[nz] * np.log2(joint[nz] / (np.outer(px, py)[nz] + 1e-12) + 1e-12))
    return float(mi)


def factor_step(rng, kind, f_prev, a, K, eta):
    """Transición de UN factor dado su tipo, su valor previo y la acción."""
    n = len(a)
    noise = rng.random(n) < eta
    rand_vals = rng.integers(0, K, size=n)
    if kind == "ctrl":
        base = a.copy()
    elif kind == "clock":
        base = (f_prev + 1) % K
    elif kind == "rand":
        base = rng.integers(0, K, size=n)
    else:
        raise ValueError(kind)
    out = np.where(noise, rand_vals, base)
    return out


def measure_factor(rng, kind, K, eta, samples):
    """Devuelve (empowerment_bits, predictibilidad_bits) de un factor de un tipo dado."""
    a = rng.integers(0, K, size=samples)            # política uniforme sobre acciones
    f_prev = rng.integers(0, K, size=samples)       # valor previo del factor (uniforme)
    f_next = factor_step(rng, kind, f_prev, a, K, eta)

    # EMPOWERMENT: capacidad de canal a -> f_next. Estimar p(f_next | a) por conteo.
    p_y_given_x = np.zeros((K, K))                   # filas=acción, cols=f_next
    np.add.at(p_y_given_x, (a, f_next), 1.0)
    p_y_given_x = p_y_given_x / (p_y_given_x.sum(axis=1, keepdims=True) + 1e-12)
    emp = blahut_arimoto(p_y_given_x)

    # PREDICTIBILIDAD pasiva: I(f_prev ; f_next) — sin usar la acción como lever.
    pred = mutual_info_bits(f_prev, f_next, K)
    return emp, pred


def run(K, eta, n_factors, samples, seeds):
    kinds = ["ctrl", "clock", "rand"]
    per_seed = []
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        row = {"seed": seed, "emp": {}, "pred": {}}
        for kind in kinds:
            emps, preds = [], []
            for _ in range(n_factors):
                e, p = measure_factor(rng, kind, K, eta, samples)
                emps.append(e)
                preds.append(p)
            row["emp"][kind] = float(np.mean(emps))
            row["pred"][kind] = float(np.mean(preds))
        per_seed.append(row)

    def agg(metric, kind):
        vals = [per_seed[s][metric][kind] for s in range(seeds)]
        return float(np.mean(vals)), float(np.std(vals))

    summary = {"K": K, "max_bits": float(np.log2(K)), "by_kind": {}}
    for kind in kinds:
        summary["by_kind"][kind] = {
            "emp_mean": agg("emp", kind)[0], "emp_std": agg("emp", kind)[1],
            "pred_mean": agg("pred", kind)[0], "pred_std": agg("pred", kind)[1],
        }

    e = {k: summary["by_kind"][k]["emp_mean"] for k in kinds}
    p = {k: summary["by_kind"][k]["pred_mean"] for k in kinds}
    # empowerment se queda con el CONTROLABLE
    emp_finds_control = (e["ctrl"] - max(e["clock"], e["rand"])) > 0.8
    # predicción pasiva se queda con el RELOJ y PIERDE el controlable (la INVERSIÓN)
    passive_locks_clock = (p["clock"] - p["ctrl"]) > 0.8
    # refutación: empowerment NO distingue controlable de reloj
    emp_fails = (e["ctrl"] - e["clock"]) <= 0.8

    if emp_fails:
        verdict = "refutada"
    elif emp_finds_control and passive_locks_clock:
        verdict = "apoyada"
    else:
        verdict = "mixta"

    summary["checks"] = {
        "emp_finds_control(E_ctrl-max(otros)>0.8)": emp_finds_control,
        "passive_locks_clock_inversion(P_clock-P_ctrl>0.8)": passive_locks_clock,
        "REFUTE_emp_fails(E_ctrl-E_clock<=0.8)": emp_fails,
        "E_ctrl_minus_E_clock": round(e["ctrl"] - e["clock"], 3),
        "P_clock_minus_P_ctrl": round(p["clock"] - p["ctrl"], 3),
    }
    summary["interpretation"] = (
        "Si APOYADA: el EMPOWERMENT (valor AUTO-generado, sin reward/verificador externo) identifica el factor "
        "CONTROLABLE y descarta el reloj predecible-pero-inútil; la PREDICCIÓN pasiva hace lo contrario "
        "(se queda con el reloj, pierde el controlable). => para un AGENTE, un valor endógeno captura 'lo que "
        "puedo afectar', que la predicción pasiva fundamentalmente no puede. Es la forma FUERTE de R-VALOR, "
        "y a diferencia del info-gain (exp023) SÍ se distingue de lo trivial. Límite honesto: muestra el "
        "MECANISMO (controlabilidad != predictibilidad), no aún que mejore una tarea downstream ni que escale "
        "a lenguaje."
    )
    summary["verdict"] = verdict
    return per_seed, summary


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="python -m cognia_x.experiments.exp024_empowerment.run")
    ap.add_argument("--K", type=int, default=4)
    ap.add_argument("--eta", type=float, default=0.05)
    ap.add_argument("--n_factors", type=int, default=2)
    ap.add_argument("--samples", type=int, default=20000)
    ap.add_argument("--seeds", type=int, default=12)
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    per_seed, summary = run(args.K, args.eta, args.n_factors, args.samples, args.seeds)
    wall = time.perf_counter() - t0

    out = {
        "experiment": "exp024_empowerment",
        "hypothesis": "H-V4-1c",
        "question": ("¿Un valor AUTO-generado (empowerment, sin reward/verificador externo) captura la "
                     "CONTROLABILIDAD ('lo que puedo afectar') que la predicción pasiva no puede?"),
        "env": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
        "params": {"K": args.K, "eta": args.eta, "n_factors": args.n_factors, "samples": args.samples,
                   "seeds": args.seeds},
        "wall_secs": round(wall, 3),
        "per_seed": per_seed,
        "summary": summary,
    }
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print("=" * 80)
    print("exp024 — H-V4-1c: empowerment (valor auto-generado) vs predicción pasiva")
    print("=" * 80)
    print("params: K={K} eta={eta} n_factors={n_factors} samples={samples} seeds={seeds} | max={mb:.2f} bits".format(
        mb=summary["max_bits"], **out["params"]))
    print("")
    print("  {:<10} | {:>16} | {:>16}".format("factor", "EMPOWERMENT(bits)", "PREDICTIBILIDAD(bits)"))
    for kind in ("ctrl", "clock", "rand"):
        d = summary["by_kind"][kind]
        print("  {:<10} | {:>16} | {:>16}".format(
            kind,
            "{:.3f}±{:.3f}".format(d["emp_mean"], d["emp_std"]),
            "{:.3f}±{:.3f}".format(d["pred_mean"], d["pred_std"])))
    print("")
    for k, v in summary["checks"].items():
        print("  CHECK  {:<42} = {}".format(k, v))
    print("")
    print("  costo: {:.3f}s CPU (numpy puro)".format(wall))
    print("  INTERPRETACIÓN:", summary["interpretation"])
    print("  VEREDICTO H-V4-1c :", summary["verdict"].upper())
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
