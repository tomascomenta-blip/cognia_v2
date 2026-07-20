r"""
exp058 — CYCLE 74 / H-V4-5d (arco "R-VALOR bajo realismo", cierra la muleta del 73): el estimador de valor elige
su PROPIA tasa de olvido. Un meta-SELECTOR sobre dos expertos (frecuencia full = no-olvida, frecuencia decay =
olvida) que sigue al RECIENTEMENTE-MEJOR -- juzgado por sus PROPIOS aciertos (sin oráculo ni aviso de régimen) --
logra NO-REGRET: iguala al mejor experto en CADA régimen, lo que ningún experto FIJO logra en ambos.

CONTEXTO: CYCLE 73 (exp057, H-V4-5c APOYADA) mostró el CROSSOVER -- full gana en estacionario, decay gana en
no-estacionario -- pero con decay FIJO (su caveat #1: el óptimo depende de la tasa de cambio). El lab ya mostró
(CYCLE 64 meta-olvido MIXTA; CYCLE 66 selector de estrategia alcanza el óptimo donde la modulación de TASA no pudo)
que ELEGIR la estrategia (decisión discreta) vence a modular la intensidad. Aquí lo aterrizamos sobre el ESTIMADOR
DE VALOR: ¿un selector discreto full<->decay, gateado por la sorpresa endógena, logra no-regret en ambos regímenes?

TAREA (idéntica a exp057): memoria online m<n, popularidad power-law que RE-PERMUTA item->valor cada K_phase
(no-estacionario) o fija (estacionario). HIT si el item consultado está en memoria. 6 brazos:
  - oracle_current: top-m por valor verdadero de la fase (cota superior).
  - lfu_full:       frecuencia acumulada (no olvida) -- mejor en ESTACIONARIO, degrada con cambio.
  - lfu_decay:      frecuencia con decay (olvida) -- mejor en NO-ESTACIONARIO, paga costo sin cambio.
  - selector:       corre AMBOS expertos en sombra y, en cada paso, USA la memoria del experto con mayor hit-rate
                    RECIENTE (EMA de sus propios aciertos). Decisión DISCRETA y ENDÓGENA. Sin saber el régimen.
  - recency:        LRU (value-free).
  - random:         m fijos al azar.

PREDICCIÓN FALSABLE (pre-registrada): el selector es NO-REGRET si IGUALA al mejor experto en CADA régimen:
  - APOYADA si selector >= full-0.03 en estacionario (iguala al mejor=full) Y selector >= decay-0.03 en
    no-estacionario (iguala al mejor=decay) Y en cada régimen SUPERA al experto FIJO equivocado (selector > decay
    en estac. y selector > full en no-estac., +>0.02). => el estimador de valor ELIGE su tasa de olvido de su
    propia sorpresa, logrando lo que ningún decay fijo logra en ambos regímenes.
  - REFUTADA si el selector elige MAL (peor que el experto fijo equivocado en algún régimen, -0.02).
  - MIXTA si adapta en la dirección correcta pero con REGRET (iguala en un régimen y queda corto en el otro).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp058_adaptive_value_memory.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp058_adaptive_value_memory.run            # FULL
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
ARMS = ["oracle_current", "lfu_full", "lfu_decay", "selector", "recency", "random"]


def gen_values(rng, n, alpha):
    v = (rng.pareto(alpha, size=n) + 1.0)
    return v / v.sum()


def _topm(counts, tiebreak, m):
    return set(np.argsort(counts + 1e-9 * tiebreak)[-m:].tolist())


def simulate_arm(queries, phase_of_t, topm_by_phase, m, n, arm, decay, beta, rng, warmup):
    """Hit-rate online promedio (tras warmup) de un brazo. El selector corre full+decay en sombra y usa el experto
    con mayor EMA de aciertos recientes (decisión hecha ANTES de ver la consulta del paso)."""
    counts_full = np.zeros(n, dtype=np.float64)
    counts_decay = np.zeros(n, dtype=np.float64)
    tb = rng.random(n)
    lru = []
    fixed_random = set(rng.choice(n, size=m, replace=False).tolist())
    ema_full, ema_decay = 0.0, 0.0          # hit-rate reciente de cada experto (para el selector)
    T = len(queries)
    hits = np.zeros(T, dtype=np.int8)
    use_decay_steps = 0                     # diagnóstico: cuántos pasos el selector eligió decay
    for t in range(T):
        q = int(queries[t])
        ph = phase_of_t[t]
        if arm == "oracle_current":
            mem = topm_by_phase[ph]
        elif arm == "random":
            mem = fixed_random
        elif arm == "recency":
            mem = set(lru[:m])
        elif arm == "lfu_full":
            mem = _topm(counts_full, tb, m)
        elif arm == "lfu_decay":
            mem = _topm(counts_decay, tb, m)
        else:  # selector: elige experto por EMA de aciertos reciente
            mem_full = _topm(counts_full, tb, m)
            mem_decay = _topm(counts_decay, tb, m)
            pick_decay = ema_decay > ema_full
            mem = mem_decay if pick_decay else mem_full
            if t >= warmup and pick_decay:
                use_decay_steps += 1
        hits[t] = 1 if q in mem else 0
        # actualizar estado
        if arm == "lfu_full":
            counts_full[q] += 1.0
        elif arm == "lfu_decay":
            counts_decay *= decay
            counts_decay[q] += 1.0
        elif arm == "recency":
            if q in lru:
                lru.remove(q)
            lru.insert(0, q)
            del lru[m:]
        elif arm == "selector":
            hf = 1.0 if q in mem_full else 0.0
            hd = 1.0 if q in mem_decay else 0.0
            ema_full = beta * ema_full + (1.0 - beta) * hf
            ema_decay = beta * ema_decay + (1.0 - beta) * hd
            counts_full[q] += 1.0
            counts_decay *= decay
            counts_decay[q] += 1.0
    hr = float(hits[warmup:].mean())
    if arm == "selector":
        frac_decay = use_decay_steps / max(1, T - warmup)
        return hr, round(frac_decay, 3)
    return hr, None


def run_scenario(n, m, alpha, K_phase, n_phases, decay, beta, n_seeds, nonstationary):
    T = K_phase * n_phases
    warmup = K_phase
    acc = {a: [] for a in ARMS}
    sel_fracs = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        base_vals = gen_values(rng, n, alpha)
        if nonstationary:
            perms = [rng.permutation(n) for _ in range(n_phases)]
        else:
            base = rng.permutation(n)
            perms = [base for _ in range(n_phases)]
        p_by_phase = [base_vals[perm] for perm in perms]
        topm_by_phase = [set(np.argsort(p)[-m:].tolist()) for p in p_by_phase]
        phase_of_t = [t // K_phase for t in range(T)]
        qrng = np.random.default_rng(seed * 104729 + (1 if nonstationary else 0))
        queries = np.empty(T, dtype=np.int64)
        for ph in range(n_phases):
            lo, hi = ph * K_phase, (ph + 1) * K_phase
            queries[lo:hi] = qrng.choice(n, size=hi - lo, p=p_by_phase[ph])
        for a in ARMS:
            arng = np.random.default_rng(seed * 7919 + ARMS.index(a) + 1)
            hr, frac = simulate_arm(queries, phase_of_t, topm_by_phase, m, n, a, decay, beta, arng, warmup)
            acc[a].append(hr)
            if a == "selector":
                sel_fracs.append(frac)
    out = {a: round(float(np.mean(acc[a])), 4) for a in ARMS}
    out["_selector_frac_decay"] = round(float(np.mean(sel_fracs)), 3)
    return out


def _f(x):
    return "{:.3f}".format(x)


def build_summary(stat, nonstat, n, m):
    full_s, dec_s, sel_s = stat["lfu_full"], stat["lfu_decay"], stat["selector"]
    full_n, dec_n, sel_n = nonstat["lfu_full"], nonstat["lfu_decay"], nonstat["selector"]
    # no-regret = iguala al mejor experto de cada régimen (full en estac., decay en no-estac.)
    matches_best_stat = sel_s >= full_s - 0.03
    matches_best_ns = sel_n >= dec_n - 0.03
    beats_wrong_stat = sel_s > dec_s + 0.02          # en estac. supera a decay (el fijo equivocado)
    beats_wrong_ns = sel_n > full_n + 0.02           # en no-estac. supera a full (el fijo equivocado)
    picks_wrong = (sel_s < dec_s - 0.02) or (sel_n < full_n - 0.02)

    no_regret = matches_best_stat and matches_best_ns and beats_wrong_stat and beats_wrong_ns
    if no_regret:
        status = "apoyada"
        verdict = ("H-V4-5d APOYADA: el estimador de valor ELIGE su tasa de olvido de su propia sorpresa (no-regret). "
                   "ESTACIONARIO: selector {ss} iguala al mejor (full {fs}; supera a decay {ds}). NO-ESTACIONARIO: "
                   "selector {sn} iguala al mejor (decay {dn}; supera a full {fn}). Ningún experto FIJO logra ser el "
                   "mejor en AMBOS regímenes (full pierde con cambio, decay paga sin cambio), pero el SELECTOR "
                   "discreto -- gateado por el hit-rate reciente de cada experto, ENDÓGENO -- sí. El selector usó "
                   "decay {fdn}% del tiempo en no-estac. y {fds}% en estac.: detecta el régimen de su sorpresa. => "
                   "cierra la muleta 'decay fijo' del CYCLE 73; replica el selector de estrategia (CYCLE 66) sobre el "
                   "estimador de valor. R-VALOR elige QUÉ vale, CUÁNDO dejó de valer Y a qué RITMO olvidar.").format(
                       ss=_f(sel_s), fs=_f(full_s), ds=_f(dec_s), sn=_f(sel_n), dn=_f(dec_n), fn=_f(full_n),
                       fdn=int(round(nonstat["_selector_frac_decay"] * 100)),
                       fds=int(round(stat["_selector_frac_decay"] * 100)))
    elif picks_wrong:
        status = "refutada"
        verdict = ("H-V4-5d REFUTADA: el selector elige MAL. estac. selector {ss} vs decay {ds} / no-estac. selector "
                   "{sn} vs full {fn} -> queda por debajo del experto fijo en algún régimen (el gating por sorpresa "
                   "no separa los regímenes a esta escala).").format(ss=_f(sel_s), ds=_f(dec_s), sn=_f(sel_n), fn=_f(full_n))
    else:
        status = "mixta"
        verdict = ("H-V4-5d MIXTA: el selector adapta en la dirección correcta pero con REGRET. estac. selector {ss} "
                   "(mejor full {fs}) / no-estac. selector {sn} (mejor decay {dn}); iguala en un régimen y queda corto "
                   "en el otro -- la conmutación tiene un costo de transitorio (cf. CYCLE 64 meta-olvido MIXTA).").format(
                       ss=_f(sel_s), fs=_f(full_s), sn=_f(sel_n), dn=_f(dec_n))

    return {"stationary": stat, "nonstationary": nonstat,
            "matches_best_stat": bool(matches_best_stat), "matches_best_ns": bool(matches_best_ns),
            "beats_wrong_stat": bool(beats_wrong_stat), "beats_wrong_ns": bool(beats_wrong_ns),
            "no_regret": bool(no_regret), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=32)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--m", type=int, default=10)
    ap.add_argument("--alpha", type=float, default=1.5)
    ap.add_argument("--K_phase", type=int, default=300)
    ap.add_argument("--n_phases", type=int, default=6)
    ap.add_argument("--decay", type=float, default=0.97)
    ap.add_argument("--beta", type=float, default=0.98, help="EMA del hit-rate por experto (ventana ~1/(1-beta))")
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 6
        args.K_phase = 150
        args.n_phases = 4

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp058] CYCLE 74 / H-V4-5d — el estimador de valor ELIGE su tasa de olvido (selector full<->decay endógeno)")
    log(f"[exp058] n={args.n} m={args.m} K_phase={args.K_phase} n_phases={args.n_phases} decay={args.decay} "
        f"beta={args.beta} seeds={args.seeds}")

    stat = run_scenario(args.n, args.m, args.alpha, args.K_phase, args.n_phases, args.decay, args.beta, args.seeds, False)
    nonstat = run_scenario(args.n, args.m, args.alpha, args.K_phase, args.n_phases, args.decay, args.beta, args.seeds, True)
    sm = build_summary(stat, nonstat, args.n, args.m)

    log(f"[exp058] ESTACIONARIO   oracle={stat['oracle_current']:.3f} full={stat['lfu_full']:.3f} "
        f"decay={stat['lfu_decay']:.3f} selector={stat['selector']:.3f} (usa decay {stat['_selector_frac_decay']*100:.0f}%) "
        f"recency={stat['recency']:.3f} random={stat['random']:.3f}")
    log(f"[exp058] NO-ESTACIONARIO oracle={nonstat['oracle_current']:.3f} full={nonstat['lfu_full']:.3f} "
        f"decay={nonstat['lfu_decay']:.3f} selector={nonstat['selector']:.3f} (usa decay {nonstat['_selector_frac_decay']*100:.0f}%) "
        f"recency={nonstat['recency']:.3f} random={nonstat['random']:.3f}")
    log(f"[exp058] VEREDICTO H-V4-5d: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp058_adaptive_value_memory", "cycle": 74, "hypothesis": "H-V4-5d",
           "claim": "un meta-selector full<->decay gateado por el hit-rate reciente de cada experto (endógeno) logra "
                    "no-regret en ambos regímenes: el estimador de valor elige su propia tasa de olvido",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp058] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
