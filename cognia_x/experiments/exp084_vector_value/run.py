r"""
exp084 — CYCLE 100 / H-V4-8e (rama R-VALOR, gap #4: objetivo VECTOR/multi-objetivo): todo el arco asumió un objetivo
ESCALAR. El valor real suele ser un VECTOR (varios objetivos) bajo una agregación que exige BALANCE (egalitaria: te juzga
por tu objetivo PEOR). ¿Seleccionar por UN objetivo o por la SUMA naive FALLA bajo un objetivo vector balance-requiriente,
y la selección R-VALOR MARGINAL (que balancea el objetivo rezagado) recupera? Generaliza CYCLE 95 (marginal) a vector y
conecta con CYCLE 83 (complementos g=min) a nivel de CONJUNTO.

CONTEXTO. CYCLE 95 mostró que bajo objetivo NO-aditivo (submodular escalar) el valor debe ser MARGINAL. Este ciclo lo
extiende a un objetivo VECTOR: el agente selecciona un conjunto y se lo juzga por min(ΣV1, ΣV2) (egalitario; el objetivo
PEOR del conjunto) -- requiere que el conjunto esté BALANCEADO entre los dos objetivos, no que maximice uno.

DISEÑO (numpy). n ítems con valor VECTOR (v1, v2) ANTI-correlacionados (v2 ≈ 1−v1+ruido: trade-off real). Selección de m.
Agregación del conjunto: 'min' = min(Σv1, Σv2) (egalitaria, balance-requiriente) vs 'sum' = Σv1+Σv2 (lineal, control).
El agente ve (v1,v2) RUIDOSOS. Brazos:
  - obj1_greedy:     top-m por v1 (un solo objetivo -> desbalancea: alto V1, bajo V2).
  - sum_greedy:      top-m por (v1+v2) (suma lineal -> ignora la estructura min; con anti-corr puede desbalancear).
  - marginal_greedy: greedy por GANANCIA MARGINAL en la agregación REAL (para 'min' añade al objetivo REZAGADO -> balancea).
  - oracle:          marginal_greedy sobre v REAL (techo).
  - random.
Perf = agregación_real(selección) / agregación_real(oracle).

Se BARRE la ASIMETRÍA de escala entre objetivos (v2_scale): bajo objetivos SIMÉTRICOS la suma naive ya balancea (max-suma
≈ balanceado por simetría); bajo objetivos ASIMÉTRICOS (v2 de escala menor) la max-suma CARGA el objetivo grande (ΣV1≫ΣV2
-> min bajo) y se necesita la selección MARGINAL que sube el objetivo rezagado.

PREGUNTA FALSABLE (cuándo el objetivo vector EXIGE marginal):
  - APOYADA si bajo 'min' ASIMÉTRICO marginal_greedy >> sum_greedy (+>0.05; la suma naive desbalancea, el marginal sube el
    rezagado) Y ≈ oracle; bajo 'min' SIMÉTRICO la suma ya balancea (marginal ≈ sum); bajo 'sum' (lineal) todos coinciden.
    => bajo objetivo VECTOR balance-requiriente Y ASIMÉTRICO, R-VALOR es la selección MARGINAL en la agregación real; la
    suma naive sólo basta bajo simetría. (obj1_greedy -un objetivo- falla en todos los casos.)
  - REFUTADA si ni bajo asimetría la suma naive falla (marginal ≈ sum siempre).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp084_vector_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp084_vector_value.run            # FULL
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
ARMS = ["obj1_greedy", "sum_greedy", "marginal_greedy", "oracle", "random"]
OBJECTIVES = ["min", "sum"]
OBJ_ID = {"min": 0, "sum": 1}


def _agg(picks, v1, v2, kind):
    if len(picks) == 0:
        return 0.0
    s1 = float(np.sum(v1[list(picks)])); s2 = float(np.sum(v2[list(picks)]))
    return min(s1, s2) if kind == "min" else (s1 + s2)


def _marginal_greedy(v1, v2, m, kind):
    n = len(v1)
    picks = []
    chosen = np.zeros(n, dtype=bool)
    s1 = s2 = 0.0
    cur = 0.0
    for _ in range(min(m, n)):
        if kind == "sum":
            gain = (v1 + v2)
        else:
            gain = np.minimum(s1 + v1, s2 + v2) - cur
        gain = np.where(chosen, -1e9, gain)
        j = int(np.argmax(gain))
        picks.append(j); chosen[j] = True
        s1 += v1[j]; s2 += v2[j]
        cur = min(s1, s2) if kind == "min" else (s1 + s2)
    return picks


def run_cell(n, m, kind, v2_scale, noise, anti_noise, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 821 + OBJ_ID[kind] * 37 + int(v2_scale * 100) * 3 + 5)
        v1 = rng.random(n)
        # anti-correlados (trade-off); v2_scale<1 -> objetivo 2 de ESCALA MENOR (asimetría)
        v2 = np.clip((1.0 - v1) * v2_scale + rng.normal(0.0, anti_noise, size=n), 0.0, 1.0)
        v1e = np.clip(v1 + rng.normal(0.0, noise, size=n), 0.0, 1.0)
        v2e = np.clip(v2 + rng.normal(0.0, noise, size=n), 0.0, 1.0)
        oracle_picks = _marginal_greedy(v1, v2, m, kind)
        denom = _agg(oracle_picks, v1, v2, kind)
        if denom < 1e-9:
            continue
        obj1 = list(np.argsort(v1e)[::-1][:m])
        summ = list(np.argsort(v1e + v2e)[::-1][:m])
        marg = _marginal_greedy(v1e, v2e, m, kind)
        rand = list(rng.choice(n, size=min(m, n), replace=False))
        acc["obj1_greedy"].append(_agg(obj1, v1, v2, kind) / denom)
        acc["sum_greedy"].append(_agg(summ, v1, v2, kind) / denom)
        acc["marginal_greedy"].append(_agg(marg, v1, v2, kind) / denom)
        acc["oracle"].append(1.0)
        acc["random"].append(_agg(rand, v1, v2, kind) / denom)
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


# celdas: min simétrico (v2_scale=1), min asimétrico (v2_scale=0.45), sum lineal (control, simétrico)
CELLS = {"min_sym": ("min", 1.0), "min_asym": ("min", 0.45), "sum_lin": ("sum", 1.0)}


def run(n, m, noise, anti_noise, n_seeds):
    return {key: run_cell(n, m, kind, sc, noise, anti_noise, n_seeds) for key, (kind, sc) in CELLS.items()}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    asym, sym, lin = grid["min_asym"], grid["min_sym"], grid["sum_lin"]
    asym_marg_vs_sum = round(asym["marginal_greedy"] - asym["sum_greedy"], 4)   # >0.05: bajo asimetría la suma falla
    asym_marg_vs_obj1 = round(asym["marginal_greedy"] - asym["obj1_greedy"], 4)
    asym_oracle_gap = round(asym["oracle"] - asym["marginal_greedy"], 4)
    sym_sum_ok = round(sym["marginal_greedy"] - sym["sum_greedy"], 4)           # ~0: bajo simetría la suma ya balancea
    lin_coincide = round(abs(lin["marginal_greedy"] - lin["sum_greedy"]), 4)    # ~0: bajo objetivo lineal coinciden

    GAP_THR = 0.05
    TOL = 0.03
    NEAR_ORACLE = 0.06

    asym_needs_marg = asym_marg_vs_sum > GAP_THR
    near_oracle = asym_oracle_gap <= NEAR_ORACLE
    sym_sum_suffices = sym_sum_ok <= GAP_THR
    lin_coincides = lin_coincide <= TOL

    if asym_needs_marg and near_oracle and sym_sum_suffices and lin_coincides:
        status = "apoyada"
        verdict = ("H-V4-8e APOYADA: bajo objetivo VECTOR balance-requiriente (min(ΣV1,ΣV2), egalitario) Y ASIMÉTRICO "
                   "(objetivo 2 de escala menor), la SUMA naive DESBALANCEA (carga el objetivo grande) y falla: "
                   "sum_greedy={asg} -- mientras la selección R-VALOR MARGINAL sube el objetivo REZAGADO y recupera: "
                   "marginal_greedy={amg} (vs sum +{avs}, vs obj1 +{avo}, ≈ oracle gap {aog}). Bajo objetivo SIMÉTRICO la "
                   "suma YA balancea (marginal ≈ sum, Δ {sso}: por simetría max-suma ≈ balanceado). Bajo objetivo LINEAL "
                   "('sum') todos coinciden (Δ {lc}). => R-VALOR bajo un objetivo VECTOR balance-requiriente Y ASIMÉTRICO "
                   "es la selección MARGINAL en la agregación real; la suma naive sólo basta bajo simetría; un solo "
                   "objetivo falla siempre. Generaliza CYCLE 95 (marginal) a vector y conecta con CYCLE 83 (complementos "
                   "g=min) a nivel de CONJUNTO -- el 'balance' es la forma vectorial de la cobertura/diversidad.").format(
                       asg=_f(asym["sum_greedy"]), amg=_f(asym["marginal_greedy"]), avs=_f(asym_marg_vs_sum),
                       avo=_f(asym_marg_vs_obj1), aog=_f(asym_oracle_gap), sso=_f(sym_sum_ok), lc=_f(lin_coincide))
    elif not asym_needs_marg:
        status = "refutada"
        verdict = ("H-V4-8e REFUTADA: ni bajo ASIMETRÍA la suma naive falla (marginal={amg} ≈ sum={asg}, Δ {avs} <= {thr}) "
                   "-> la suma lineal basta también bajo objetivo vector asimétrico.").format(
                       amg=_f(asym["marginal_greedy"]), asg=_f(asym["sum_greedy"]), avs=_f(asym_marg_vs_sum), thr=GAP_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-8e MIXTA: asym_needs_marg={an}(+{avs}) near_oracle={no}(gap {aog}) sym_sum_suffices={ss}(Δ {sso}) "
                   "lin_coincides={lc}(Δ {lcv}).").format(an=asym_needs_marg, avs=_f(asym_marg_vs_sum), no=near_oracle,
                                                          aog=_f(asym_oracle_gap), ss=sym_sum_suffices, sso=_f(sym_sum_ok),
                                                          lc=lin_coincides, lcv=_f(lin_coincide))

    return {"grid": grid, "asym_marg_vs_sum": asym_marg_vs_sum, "asym_marg_vs_obj1": asym_marg_vs_obj1,
            "asym_oracle_gap": asym_oracle_gap, "sym_sum_ok": sym_sum_ok, "lin_coincide": lin_coincide,
            "asym_needs_marg": bool(asym_needs_marg), "near_oracle": bool(near_oracle),
            "sym_sum_suffices": bool(sym_sum_suffices), "lin_coincides": bool(lin_coincides),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--m", type=int, default=10)
    ap.add_argument("--noise", type=float, default=0.05)
    ap.add_argument("--anti_noise", type=float, default=0.15)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp084] CYCLE 100 / H-V4-8e — gap #4 (objetivo VECTOR): R-VALOR marginal bajo agregación egalitaria min(ΣV1,ΣV2)")
    log(f"[exp084] n={args.n} m={args.m} noise={args.noise} anti_noise={args.anti_noise} seeds={args.seeds} objetivos={OBJECTIVES}")

    grid = run(args.n, args.m, args.noise, args.anti_noise, args.seeds)
    sm = build_summary(grid)

    for key in CELLS:
        c = grid[key]
        log(f"[exp084] {key:>8}: obj1={c['obj1_greedy']:.3f} sum={c['sum_greedy']:.3f} "
            f"marginal={c['marginal_greedy']:.3f} oracle={c['oracle']:.3f} random={c['random']:.3f}")
    log(f"[exp084] ASIM(min): marg_vs_sum=+{sm['asym_marg_vs_sum']:.3f} marg_vs_obj1=+{sm['asym_marg_vs_obj1']:.3f} "
        f"oracle_gap={sm['asym_oracle_gap']:.3f} | SIM(min): sum_ok Δ={sm['sym_sum_ok']:.3f} | LINEAL: coincide Δ={sm['lin_coincide']:.3f}")
    log(f"[exp084] asym_needs_marg={sm['asym_needs_marg']} near_oracle={sm['near_oracle']} sym_sum_suffices={sm['sym_sum_suffices']} lin_coincides={sm['lin_coincides']}")
    log(f"[exp084] VEREDICTO H-V4-8e: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp084_vector_value", "cycle": 100, "hypothesis": "H-V4-8e",
           "claim": "bajo un objetivo VECTOR balance-requiriente (min(SV1,SV2) egalitario, objetivos anti-correlacionados) "
                    "seleccionar por un objetivo o por la suma naive desbalancea y falla; la seleccion R-VALOR MARGINAL en "
                    "la agregacion real balancea y recupera -> R-VALOR bajo objetivo vector es marginal en la agregacion",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp084] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
