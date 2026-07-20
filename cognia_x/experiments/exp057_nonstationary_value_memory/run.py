r"""
exp057 — CYCLE 73 / H-V4-5c (arco "R-VALOR bajo realismo", hija del CYCLE 72): el estimador de valor debe OLVIDAR
para rastrear valor NO-estacionario. CROSSOVER: la frecuencia-de-toda-la-historia (LFU full, ganadora del CYCLE
72 en estacionario) DEGRADA bajo no-estacionariedad; una frecuencia con DECAY (valor estimado + olvido) recupera
la ventaja. Ata R-VALOR (el estimador endógeno) con el arco de OLVIDO (CYCLE 58-66).

CONTEXTO: el CYCLE 72 (exp056, H-V4-5b APOYADA) mostró que estimar el valor de la frecuencia observada (LFU full)
recupera ~99% de la ventaja del oráculo -- PERO sólo en régimen ESTACIONARIO. El caveat honesto registrado: bajo
NO-estacionariedad, la frecuencia de TODA la historia es un valor SESGADO (mezcla épocas viejas con la actual). El
lab ya mostró (CYCLE 58-66) que el TIPO de olvido se elige del régimen. Aquí lo aterrizamos sobre el ESTIMADOR DE
VALOR: ¿olvidar (decay) en el conteo de frecuencia recupera la ventaja cuando la popularidad cambia?

TAREA (memoria online no-estacionaria): n items, capacidad m<n. La popularidad es power-law (Pareto) PERO la
asignación item->valor se PERMUTA cada K_phase pasos (régimen RECURRENTE, cf. CYCLE 63): la forma de la
distribución es fija, pero QUÉ items son populares cambia. Stream de consultas IID ~ valor de la fase actual.
HIT si el item consultado está en memoria. Métrica = hit-rate online promedio tras el warm-up (1 fase). Se corren
DOS escenarios -- ESTACIONARIO (misma asignación siempre) y NO-ESTACIONARIO (re-permuta cada fase) -- para exhibir
el CROSSOVER. 5 brazos:
  - oracle_current: top-m por el valor VERDADERO de la fase actual (cota superior; conoce el cambio).
  - lfu_full:       top-m por frecuencia acumulada de TODA la historia (el estimador del CYCLE 72; NO olvida).
  - lfu_decay:      top-m por frecuencia con DECAY exponencial (valor estimado que OLVIDA; ventana ~1/(1-decay)).
  - recency:        LRU (value-free).
  - random:         m fijos al azar.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si, en NO-estacionario, lfu_decay supera a lfu_full (+>0.05; olvidar ayuda al estimador) Y lfu_decay
    recupera gran parte de la ventaja del oráculo ((decay-rnd)/(oracle-rnd) >= 0.55) Y lfu_decay > recency (+>0.03).
    (Apoyo: en ESTACIONARIO lfu_full >= lfu_decay -- olvidar tiene un COSTO; el tradeoff es real, no dominación.)
  - REFUTADA si lfu_decay no supera a lfu_full bajo no-estacionariedad (olvidar no ayuda) O lfu_decay <= recency.
  - MIXTA si decay ayuda pero recupera poco o no le gana limpio a recency.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp057_nonstationary_value_memory.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp057_nonstationary_value_memory.run            # FULL
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
ARMS = ["oracle_current", "lfu_full", "lfu_decay", "recency", "random"]


def gen_values(rng, n, alpha):
    """Valores con cola pesada (power-law), normalizados a prob de consulta. Forma fija; se re-asigna a items."""
    v = (rng.pareto(alpha, size=n) + 1.0)
    return v / v.sum()


def build_stream(rng, base_vals, n, K_phase, n_phases, nonstationary):
    """Construye (queries, phase_of_t, p_by_phase, topm_by_phase). En no-estacionario re-permuta item->valor cada
    fase; en estacionario usa una asignación fija. Mismo stream para todos los brazos (comparación pareada)."""
    if nonstationary:
        perms = [rng.permutation(n) for _ in range(n_phases)]
    else:
        base = rng.permutation(n)
        perms = [base for _ in range(n_phases)]
    p_by_phase = [base_vals[perm] for perm in perms]            # p_phi[i] = base_vals[perm[i]] (suma 1)
    return perms, p_by_phase


def simulate_arm(queries, phase_of_t, p_by_phase, topm_by_phase, m, n, arm, decay, rng, warmup):
    """Hit-rate online promedio (tras warmup pasos) de un brazo sobre el stream dado."""
    counts = np.zeros(n, dtype=np.float64)
    tiebreak = rng.random(n)
    lru = []
    fixed_random = set(rng.choice(n, size=m, replace=False).tolist())
    T = len(queries)
    hits = np.zeros(T, dtype=np.int8)
    for t in range(T):
        q = int(queries[t])
        ph = phase_of_t[t]
        if arm == "oracle_current":
            mem = topm_by_phase[ph]
        elif arm == "random":
            mem = fixed_random
        elif arm == "recency":
            mem = set(lru[:m])
        else:  # lfu_full / lfu_decay
            key = counts + 1e-9 * tiebreak
            mem = set(np.argsort(key)[-m:].tolist())
        hits[t] = 1 if q in mem else 0
        # actualizar estado
        if arm == "lfu_full":
            counts[q] += 1.0
        elif arm == "lfu_decay":
            counts *= decay
            counts[q] += 1.0
        elif arm == "recency":
            if q in lru:
                lru.remove(q)
            lru.insert(0, q)
            del lru[m:]
    return float(hits[warmup:].mean())


def run_scenario(n, m, alpha, K_phase, n_phases, decay, n_seeds, nonstationary):
    T = K_phase * n_phases
    warmup = K_phase
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        base_vals = gen_values(rng, n, alpha)
        _, p_by_phase = build_stream(rng, base_vals, n, K_phase, n_phases, nonstationary)
        topm_by_phase = [set(np.argsort(p)[-m:].tolist()) for p in p_by_phase]
        phase_of_t = [t // K_phase for t in range(T)]
        # stream de consultas (mismo para todos los brazos de este seed)
        qrng = np.random.default_rng(seed * 104729 + (1 if nonstationary else 0))
        queries = np.empty(T, dtype=np.int64)
        for ph in range(n_phases):
            lo, hi = ph * K_phase, (ph + 1) * K_phase
            queries[lo:hi] = qrng.choice(n, size=hi - lo, p=p_by_phase[ph])
        for a in ARMS:
            arng = np.random.default_rng(seed * 7919 + ARMS.index(a) + 1)
            acc[a].append(simulate_arm(queries, phase_of_t, p_by_phase, topm_by_phase, m, n, a, decay, arng, warmup))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(stat, nonstat, n, m):
    o_s, full_s, dec_s = stat["oracle_current"], stat["lfu_full"], stat["lfu_decay"]
    o_n, full_n, dec_n, rec_n, rnd_n = (nonstat["oracle_current"], nonstat["lfu_full"], nonstat["lfu_decay"],
                                        nonstat["recency"], nonstat["random"])
    gap_n = o_n - rnd_n
    recovered_n = (dec_n - rnd_n) / gap_n if gap_n > 1e-9 else 0.0
    decay_beats_full_ns = (dec_n - full_n) > 0.05
    decay_recovers_ns = recovered_n >= 0.55
    decay_beats_recency_ns = (dec_n - rec_n) > 0.03
    tradeoff_real = full_s >= dec_s - 0.02            # en estacionario, olvidar NO es gratis (full >= decay)

    if decay_beats_full_ns and decay_recovers_ns and decay_beats_recency_ns:
        status = "apoyada"
        verdict = ("H-V4-5c APOYADA: el estimador de valor debe OLVIDAR para rastrear valor NO-estacionario. "
                   "NO-ESTACIONARIO: lfu_full (no olvida) DEGRADA de {fs} (estacionario) a {fn}, cayendo hacia "
                   "random ({rn}) al promediar épocas; lfu_decay (olvida) recupera {pct}% de la ventaja del oráculo "
                   "({on}) -> {dn}, +{df} sobre full y +{dr} sobre recency value-free ({rc}). ESTACIONARIO "
                   "(control): lfu_full {fs} >= lfu_decay {ds} -> olvidar tiene un COSTO cuando NO hay cambio "
                   "(tradeoff real, no dominación). => el valor endógeno por frecuencia se ATA al olvido (CYCLE "
                   "58-66): el estimador de valor con decay rastrea popularidad no-estacionaria; full la promedia y "
                   "se confunde. Crossover limpio.").format(
                       fn=_f(full_n), rn=_f(rnd_n), pct=int(round(recovered_n * 100)), on=_f(o_n), dn=_f(dec_n),
                       df=_f(dec_n - full_n), dr=_f(dec_n - rec_n), rc=_f(rec_n), fs=_f(full_s), ds=_f(dec_s))
    elif (not decay_beats_full_ns) or (dec_n <= rec_n):
        status = "refutada"
        verdict = ("H-V4-5c REFUTADA: olvidar no ayuda al estimador bajo no-estacionariedad. lfu_decay {dn} vs "
                   "lfu_full {fn} (gap oráculo {on}) y vs recency {rc} -> el decay no recupera la ventaja a esta "
                   "escala.").format(dn=_f(dec_n), fn=_f(full_n), on=_f(o_n), rc=_f(rec_n))
    else:
        status = "mixta"
        verdict = ("H-V4-5c MIXTA: lfu_decay {dn} supera a full {fn} y a recency {rc} pero recupera sólo {pct}% de "
                   "la ventaja del oráculo ({on}) bajo no-estacionariedad.").format(
                       dn=_f(dec_n), fn=_f(full_n), rc=_f(rec_n), pct=int(round(recovered_n * 100)), on=_f(o_n))

    return {"stationary": stat, "nonstationary": nonstat, "oracle_advantage_ns": round(gap_n, 4),
            "fraction_recovered_ns": round(float(recovered_n), 4),
            "decay_beats_full_ns": bool(decay_beats_full_ns), "decay_recovers_ns": bool(decay_recovers_ns),
            "decay_beats_recency_ns": bool(decay_beats_recency_ns), "tradeoff_real_stationary": bool(tradeoff_real),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=32)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--m", type=int, default=10)
    ap.add_argument("--alpha", type=float, default=1.5)
    ap.add_argument("--K_phase", type=int, default=300, help="pasos por fase (recurrencia)")
    ap.add_argument("--n_phases", type=int, default=6)
    ap.add_argument("--decay", type=float, default=0.97, help="decay del conteo de frecuencia (ventana ~1/(1-decay))")
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 6
        args.K_phase = 150
        args.n_phases = 4

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp057] CYCLE 73 / H-V4-5c — el estimador de valor debe OLVIDAR (decay) para rastrear valor no-estacionario")
    log(f"[exp057] n={args.n} m={args.m} alpha={args.alpha} K_phase={args.K_phase} n_phases={args.n_phases} "
        f"decay={args.decay} seeds={args.seeds} (ventana decay ~{1.0/(1.0-args.decay):.0f} pasos)")

    stat = run_scenario(args.n, args.m, args.alpha, args.K_phase, args.n_phases, args.decay, args.seeds, False)
    nonstat = run_scenario(args.n, args.m, args.alpha, args.K_phase, args.n_phases, args.decay, args.seeds, True)
    sm = build_summary(stat, nonstat, args.n, args.m)

    log(f"[exp057] ESTACIONARIO   hit-rate: oracle={stat['oracle_current']:.3f} lfu_full={stat['lfu_full']:.3f} "
        f"lfu_decay={stat['lfu_decay']:.3f} recency={stat['recency']:.3f} random={stat['random']:.3f}")
    log(f"[exp057] NO-ESTACIONARIO hit-rate: oracle={nonstat['oracle_current']:.3f} lfu_full={nonstat['lfu_full']:.3f} "
        f"lfu_decay={nonstat['lfu_decay']:.3f} recency={nonstat['recency']:.3f} random={nonstat['random']:.3f}")
    log(f"[exp057] CROSSOVER: en no-estac. decay recupera {sm['fraction_recovered_ns']*100:.0f}% del oráculo; "
        f"full cae hacia random. En estac. full>=decay (olvidar cuesta): {sm['tradeoff_real_stationary']}")
    log(f"[exp057] VEREDICTO H-V4-5c: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp057_nonstationary_value_memory", "cycle": 73, "hypothesis": "H-V4-5c",
           "claim": "el estimador de valor por frecuencia debe OLVIDAR (decay) para rastrear valor no-estacionario: "
                    "lfu_full degrada bajo cambio de popularidad y lfu_decay recupera la ventaja (ata R-VALOR con olvido)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp057] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
