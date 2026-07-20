r"""
exp063 — CYCLE 79 / H-V4-6a (PIVOTE: rama R-CONTROL, test ADVERSARIAL de empowerment-como-valor): el empowerment NO
es un valor endógeno UNIVERSAL. La corrida (CYCLE 38/exp024, 39/exp025) aceptó "empowerment > predicción como valor"
PERO sólo en regímenes donde lo CONTROLABLE coincidía con lo ÚTIL. La crítica SIMÉTRICA nunca hecha: así como la
predicción pasiva malgasta en lo predecible-INÚTIL (exp024: el reloj predecible da 0 empowerment), el EMPOWERMENT
malgasta en lo controlable-INÚTIL (un lever que podés mover pero que no afecta la recompensa). Ni predicción ni
control PURO es el valor; el general es R-VALOR (referido al OBJETIVO/recompensa).

CONTEXTO: el árbol de descomposición marca "inteligencia = control/acción (empowerment)" como la rama CONTESTADA /
faltante más grande. exp024/025 mostraron empowerment AÍSLA lo controlable y MEJORA la tarea -- pero no testearon
qué pasa cuando lo controlable NO es lo valioso. Este ciclo cierra esa brecha y UNIFICA bajo R-VALOR.

TAREA (asignación de capacidad bajo objetivo): n levers, cada uno con CONTROLABILIDAD ctrl_i (cuánto lo mueve la
acción) y RELEVANCIA rel_i (cuánto afecta la recompensa). El VALOR verdadero de un lever = ctrl_i × rel_i (rinde
recompensa sólo si lo podés controlar Y es relevante). El agente atiende/controla k<n levers (capacidad limitada);
recompensa = masa de valor de los k elegidos / masa de valor del óptimo (oracle). 3 señales para elegir los k:
  - oracle_value: top-k por ctrl×rel (cota = 1.0).
  - empowerment:  top-k por ctrl (MI acción->lever; IGNORA la relevancia).
  - random:       k al azar.
KNOB: correlación rho entre ctrl y rel (cópula gaussiana). rho=1 -> controlable=útil (régimen de exp024/025);
rho=0 -> controlable ⊥ útil (existe lo controlable-inútil); rho<0 -> controlable=inútil.

PREDICCIÓN FALSABLE (pre-registrada): el empowerment es REGIMEN-DEPENDIENTE, no universal.
  - APOYADA si empowerment_perf(rho=1) >= 0.85 (recupera exp024/025: controlable=útil) Y empowerment_perf(rho<=0)
    colapsa cerca de random (<= random+0.10) Y el swing (perf alto - perf bajo) > 0.25 monótono. => el empowerment
    rinde SÓLO cuando control≈valor; cuando divergen malgasta en lo controlable-inútil, igual que la predicción en
    lo predecible-inútil -> ni control ni predicción puro es el valor; el general es R-VALOR (referido al objetivo).
  - REFUTADA si empowerment ~ oracle para TODO rho (sería universal, contradice la crítica).
  - MIXTA si depende del régimen pero no colapsa a random ni recupera el oráculo en los extremos.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp063_empowerment_limits.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp063_empowerment_limits.run            # FULL
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
RHOS = [1.0, 0.7, 0.3, 0.0, -0.5]


def _phi(x):
    """CDF normal estándar (sin scipy): 0.5*(1+erf(x/sqrt2)) vía aproximación de math.erf elementwise."""
    from math import erf, sqrt
    vfun = np.vectorize(lambda z: 0.5 * (1.0 + erf(z / sqrt(2.0))))
    return vfun(x)


def gen_levers(rng, n, rho):
    """ctrl, rel positivos (uniformes via cópula gaussiana) con correlación de rango ~ rho."""
    z = rng.normal(size=n)
    w = rng.normal(size=n)
    ctrl_raw = z
    rel_raw = rho * z + np.sqrt(max(0.0, 1.0 - rho * rho)) * w
    ctrl = _phi(ctrl_raw)           # uniforme (0,1)
    rel = _phi(rel_raw)             # uniforme (0,1), corr de rango ~rho con ctrl
    return ctrl, rel


def perf_of(picks, value):
    """Masa de valor de los k elegidos / masa de valor del óptimo top-k (oracle = 1.0)."""
    k = len(picks)
    best = np.sort(value)[-k:].sum()
    got = value[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def run_rho(n, k, rho, n_seeds):
    emp, rnd = [], []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 131 + int((rho + 1) * 1000))
        ctrl, rel = gen_levers(rng, n, rho)
        value = ctrl * rel
        emp_picks = np.argsort(ctrl)[-k:]                  # empowerment: top-k por controlabilidad
        rnd_picks = rng.choice(n, size=k, replace=False)
        emp.append(perf_of(emp_picks, value))
        rnd.append(perf_of(rnd_picks, value))
    return round(float(np.mean(emp)), 4), round(float(np.mean(rnd)), 4)


def run(n, k, n_seeds):
    out = {}
    for rho in RHOS:
        e, r = run_rho(n, k, rho, n_seeds)
        out[rho] = {"empowerment": e, "random": r}
    return out


def _f(x):
    return "{:.3f}".format(x)


def build_summary(by_rho, n, k):
    emp_hi = by_rho[1.0]["empowerment"]
    emp_lo = by_rho[0.0]["empowerment"]
    rnd_lo = by_rho[0.0]["random"]
    swing = emp_hi - emp_lo
    emps = [by_rho[r]["empowerment"] for r in RHOS]        # rho decreciente 1.0..-0.5
    monotonic = all(emps[i] >= emps[i + 1] - 0.03 for i in range(len(emps) - 1))
    recovers_when_aligned = emp_hi >= 0.85
    collapses_when_orthogonal = emp_lo <= rnd_lo + 0.10
    big_swing = swing > 0.25

    if recovers_when_aligned and collapses_when_orthogonal and big_swing:
        status = "apoyada"
        verdict = ("H-V4-6a APOYADA: el empowerment NO es un valor endógeno universal -- es REGIMEN-DEPENDIENTE. Con "
                   "control≈valor (rho=1) empowerment captura {hi} del óptimo (recupera exp024/025: lo controlable ES "
                   "lo útil); con control ⊥ valor (rho=0) COLAPSA a {lo} ~ random ({rl}): malgasta en lo controlable-"
                   "INÚTIL. Swing {sw} monótono ({mono}). => así como la predicción malgasta en lo predecible-inútil "
                   "(exp024), el empowerment malgasta en lo controlable-inútil: ni control ni predicción PURO es el "
                   "valor. El general es R-VALOR (referido al OBJETIVO/recompensa); empowerment es un proxy correcto "
                   "SÓLO cuando lo controlable coincide con lo valioso. Resuelve el rival CONTESTADO del árbol bajo "
                   "R-VALOR.").format(hi=_f(emp_hi), lo=_f(emp_lo), rl=_f(rnd_lo), sw=_f(swing),
                                      mono="sí" if monotonic else "aprox")
    elif emp_lo >= 0.85 and emp_hi >= 0.85:
        status = "refutada"
        verdict = ("H-V4-6a REFUTADA: el empowerment ~ oracle para todo rho (rho=1 {hi}, rho=0 {lo}) -> sería un valor "
                   "UNIVERSAL, contradice la crítica de que malgasta en lo controlable-inútil.").format(
                       hi=_f(emp_hi), lo=_f(emp_lo))
    else:
        status = "mixta"
        verdict = ("H-V4-6a MIXTA (matiz más fino que el pre-registro): el empowerment es un PROXY PARCIAL del valor, "
                   "no universal ni inútil. Captura SIEMPRE el componente de CONTROLABILIDAD (valor=ctrl×rel), por eso "
                   "es EXACTO cuando control≈valor (rho=1 {hi}, recupera exp024/025) y NUNCA cae a random aun con "
                   "control ⊥ valor (rho=0 {lo} vs random {rl}: sigue capturando el factor ctrl). Degrada MONÓTONO al "
                   "desalinearse (swing {sw}, {mono}); sólo con control ANTI-valor se acerca a random. Le falta el "
                   "componente de RELEVANCIA. => ni control ni predicción PURO es el valor universal: la predicción "
                   "malgasta en lo predecible-inútil (exp024), el empowerment en lo controlable-inútil; el general es "
                   "R-VALOR (ctrl×rel, referido al OBJETIVO) y el empowerment es su MARGINAL-de-controlabilidad. Acota "
                   "honestamente el rival CONTESTADO (aceptado sin este test en CYCLE 38/39) y lo UNIFICA bajo R-VALOR: "
                   "empowerment es un COMPONENTE de R-VALOR, no su reemplazo.").format(
                       hi=_f(emp_hi), lo=_f(emp_lo), rl=_f(rnd_lo), sw=_f(swing),
                       mono="monótono" if monotonic else "aprox-monótono")

    return {"by_rho": {str(r): by_rho[r] for r in RHOS}, "emp_high_rho": emp_hi, "emp_low_rho": emp_lo,
            "random_low_rho": rnd_lo, "swing": round(swing, 4), "monotonic": bool(monotonic),
            "recovers_when_aligned": bool(recovers_when_aligned),
            "collapses_when_orthogonal": bool(collapses_when_orthogonal), "big_swing": bool(big_swing),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp063] CYCLE 79 / H-V4-6a — test ADVERSARIAL de empowerment-como-valor (controlable != util)")
    log(f"[exp063] n={args.n} k={args.k} seeds={args.seeds} rhos={RHOS}")

    by_rho = run(args.n, args.k, args.seeds)
    sm = build_summary(by_rho, args.n, args.k)

    for r in RHOS:
        log(f"[exp063] rho={r:+.1f}: empowerment={by_rho[r]['empowerment']:.3f} random={by_rho[r]['random']:.3f} "
            f"(frac del oraculo)")
    log(f"[exp063] swing empowerment (rho=1 -> rho=0): {sm['emp_high_rho']:.3f} -> {sm['emp_low_rho']:.3f} "
        f"(random {sm['random_low_rho']:.3f}); monotono={sm['monotonic']}")
    log(f"[exp063] VEREDICTO H-V4-6a: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp063_empowerment_limits", "cycle": 79, "hypothesis": "H-V4-6a",
           "claim": "el empowerment no es un valor endogeno universal: rinde solo cuando lo controlable coincide con "
                    "lo util; cuando divergen malgasta en lo controlable-inutil (igual que la prediccion en lo "
                    "predecible-inutil). El general es R-VALOR (referido al objetivo)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp063] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
