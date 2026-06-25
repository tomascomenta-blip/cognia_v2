r"""
exp056 — CYCLE 72 / H-V4-5b (R-VALOR bajo realismo, abre el arco): la ventaja de la memoria dirigida por valor
SOBREVIVE con valor ESTIMADO ONLINE (sin oráculo), y supera a una heurística value-free (recencia/LRU).

CONTEXTO: el CYCLE 70 (exp055, H-V4-5 APOYADA) cerró "la ventaja de una memoria finita ES el valor" PERO con
valor PERFECTO (la prob de consulta se daba de antemano) y selección ESTÁTICA. Caveat honesto registrado en el
techo de CYCLE 70: "falta valor ESTIMADO ruidoso" + "falta memoria dinámica con escritura/olvido online". Este
ciclo ataca ESE caveat -> abre el arco "R-VALOR bajo realismo" (quitar las muletas de juguete una por una).

TAREA (memoria de capacidad finita ONLINE): n items, cada uno con VALOR v_i (prob de consulta, power-law). Llega
un STREAM de T consultas IID ~ v. La memoria guarda sólo m < n items; en cada consulta, si el item está en
memoria = HIT, si no = MISS. El agente NO conoce v: debe ESTIMARLO de lo que observa. Desempeño = HIT-RATE online
(fracción de consultas acertadas) en la ventana FINAL (estado estacionario) -- un downstream más rico que la masa
exacta de exp055. 5 políticas de escritura/evicción:
  - oracle:    memoria fija = top-m por v VERDADERO (cota superior; = value_directed de exp055).
  - estimated: memoria = top-m por FRECUENCIA observada (LFU) -> el VALOR ENDÓGENO estimado online, sin oráculo.
  - recency:   memoria = los m consultados MÁS RECIENTES (LRU) -> heurística value-FREE (control: ¿estimar el
               VALOR por frecuencia vence a una memoria sin valor?).
  - random:    memoria fija al azar (referencia: cubre ~m/n del valor).
  - anti_value: memoria = top-m por frecuencia MÁS BAJA (estimada) -> control de DIRECCIÓN (< random).
Valores con cola pesada (Pareto alpha) -> pocos items concentran el valor. seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si estimated recupera GRAN parte de la ventaja del oráculo ((est-rnd)/(oracle-rnd) >= 0.70) Y
    estimated >> random (+>0.15) Y estimated > recency (+>0.03). => la ventaja por valor SOBREVIVE a estimarlo
    online de la propia experiencia (frecuencia = valor endógeno), sin oráculo, y vence a una memoria value-free.
  - REFUTADA si estimated no supera a random (estimar el valor destruye la ventaja) O estimated <= recency
    (estimar por frecuencia no le gana a una heurística sin valor).
  - MIXTA si estimated ayuda pero recupera poco del oráculo o no le gana limpio a recency.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp056_estimated_value_memory.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp056_estimated_value_memory.run            # FULL
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
ARMS = ["oracle", "estimated", "recency", "random", "anti_value"]


def gen_values(rng, n, alpha):
    """Valores con cola pesada (power-law): pocos items concentran la utilidad. Normalizados a prob de consulta."""
    v = (rng.pareto(alpha, size=n) + 1.0)
    return v / v.sum()


def simulate(rng, p, m, T, arm, n_checkpoints=4):
    """Procesa un stream de T consultas IID ~ p y devuelve (hit-rate ventana final 20%, curva por checkpoint).

    La memoria refleja el estado ANTES de ver la consulta t (un HIT cuenta sólo si el item ya estaba guardado);
    luego la política actualiza su estado. Cada arm = una regla de escritura/evicción distinta.
    """
    n = len(p)
    queries = rng.choice(n, size=T, p=p)
    # tiebreak fijo por item (cold-start determinista pero no sesgado al índice 0..m).
    tiebreak = rng.random(n)

    top_true = set(np.argsort(p)[-m:].tolist())              # oracle: top-m por valor verdadero (fijo)
    fixed_random = set(rng.choice(n, size=m, replace=False).tolist())  # random: m fijos al azar

    counts = np.zeros(n, dtype=np.int64)                     # estimated/anti: frecuencia observada
    lru = []                                                 # recency: lista ordenada (frente = más reciente)

    def current_mem(t_seen):
        if arm == "oracle":
            return top_true
        if arm == "random":
            return fixed_random
        if arm == "recency":
            return set(lru[:m])
        # estimated / anti_value: ranking por (frecuencia, tiebreak)
        key = counts.astype(np.float64) + 1e-6 * tiebreak
        order = np.argsort(key)
        return set((order[-m:] if arm == "estimated" else order[:m]).tolist())

    hits = np.zeros(T, dtype=np.int8)
    for t in range(T):
        q = int(queries[t])
        mem = current_mem(t)
        hits[t] = 1 if q in mem else 0
        # actualización de estado de la política (después de contar el hit)
        if arm in ("estimated", "anti_value"):
            counts[q] += 1
        elif arm == "recency":
            if q in lru:
                lru.remove(q)
            lru.insert(0, q)
            del lru[m:]                                       # mantener sólo m

    fw = max(1, T // 5)                                       # ventana final = último 20%
    final_window = float(hits[-fw:].mean())
    step = max(1, T // n_checkpoints)
    curve = [round(float(hits[: step * (k + 1)].mean()), 4) for k in range(n_checkpoints)]
    return final_window, curve


def run(n, m, alpha, T, n_seeds):
    fw = {a: [] for a in ARMS}
    curves = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        p = gen_values(rng, n, alpha)
        for a in ARMS:
            srng = np.random.default_rng(seed * 7919 + ARMS.index(a) + 1)
            f, c = simulate(srng, p, m, T, a)
            fw[a].append(f)
            curves[a].append(c)
    by_arm = {a: round(float(np.mean(fw[a])), 4) for a in ARMS}
    curve_mean = {a: [round(float(x), 4) for x in np.mean(curves[a], axis=0)] for a in ARMS}
    return by_arm, curve_mean


def _f(x):
    return "{:.3f}".format(x)


def build_summary(by_arm, n, m, T):
    oracle, est, rec, rnd, anti = (by_arm["oracle"], by_arm["estimated"], by_arm["recency"],
                                   by_arm["random"], by_arm["anti_value"])
    gap = oracle - rnd
    recovered = (est - rnd) / gap if gap > 1e-9 else 0.0
    est_beats_random = (est - rnd) > 0.15
    recovers_most = recovered >= 0.70
    beats_recency = (est - rec) > 0.03
    anti_below_random = anti < rnd - 0.05
    chance = round(m / n, 4)

    if est_beats_random and recovers_most and beats_recency:
        status = "apoyada"
        verdict = ("H-V4-5b APOYADA: la ventaja por valor SOBREVIVE a estimarlo ONLINE sin oráculo. estimated "
                   "(LFU = valor endógeno por frecuencia) llega a hit-rate {est} en estado estacionario, "
                   "recuperando {pct}% de la ventaja del oráculo ({oracle}) sobre random ({rnd}); +{adv} sobre "
                   "aleatoria. Vence a recency ({rec}, LRU value-free) por +{vrec}: estimar el VALOR por "
                   "frecuencia > una memoria sin valor. anti_value {anti} ({below} random): la DIRECCIÓN del valor "
                   "estimado importa. => R-VALOR no necesita oráculo: la frecuencia observada es un valor endógeno "
                   "que aterriza la memoria online (conecta con info-gain/confianza de CYCLE 56-57).").format(
                       est=_f(est), pct=int(round(recovered * 100)), oracle=_f(oracle), rnd=_f(rnd),
                       adv=_f(est - rnd), rec=_f(rec), vrec=_f(est - rec), anti=_f(anti),
                       below="<" if anti_below_random else "~")
    elif (not est_beats_random) or (est <= rec):
        status = "refutada"
        verdict = ("H-V4-5b REFUTADA: estimar el valor online no recupera la ventaja. estimated {est} vs random "
                   "{rnd} (gap oráculo {oracle}) y vs recency {rec} -> a esta escala el valor estimado no le gana "
                   "ni a una memoria value-free.").format(est=_f(est), rnd=_f(rnd), oracle=_f(oracle), rec=_f(rec))
    else:
        status = "mixta"
        verdict = ("H-V4-5b MIXTA: estimated {est} supera a random {rnd} y a recency {rec} pero recupera sólo "
                   "{pct}% de la ventaja del oráculo ({oracle}) -> la estimación ayuda pero no recobra el valor "
                   "perfecto a esta escala.").format(est=_f(est), rnd=_f(rnd), rec=_f(rec),
                                                     pct=int(round(recovered * 100)), oracle=_f(oracle))

    return {"by_arm": by_arm, "chance_m_over_n": chance, "oracle_advantage": round(gap, 4),
            "fraction_recovered": round(float(recovered), 4), "est_beats_random": bool(est_beats_random),
            "recovers_most": bool(recovers_most), "beats_recency": bool(beats_recency),
            "anti_below_random": bool(anti_below_random), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--m", type=int, default=10)
    ap.add_argument("--alpha", type=float, default=1.5, help="exponente Pareto (más chico = cola más pesada)")
    ap.add_argument("--T", type=int, default=3000, help="largo del stream de consultas")
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 8
        args.T = 1000

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp056] CYCLE 72 / H-V4-5b — memoria por valor ESTIMADO online (LFU) vs oráculo / recency / random")
    log(f"[exp056] n={args.n} m={args.m} (capacidad {args.m}/{args.n}) alpha={args.alpha} T={args.T} seeds={args.seeds}")

    by_arm, curves = run(args.n, args.m, args.alpha, args.T, args.seeds)
    sm = build_summary(by_arm, args.n, args.m, args.T)

    log(f"[exp056] hit-rate online (ventana final 20%): oracle={by_arm['oracle']:.3f} "
        f"estimated={by_arm['estimated']:.3f} recency={by_arm['recency']:.3f} random={by_arm['random']:.3f} "
        f"anti_value={by_arm['anti_value']:.3f} (azar m/n={sm['chance_m_over_n']:.3f})")
    log(f"[exp056] curva estimated (cumulativa por checkpoint): {curves['estimated']} "
        f"(converge hacia oracle {by_arm['oracle']:.3f})")
    log(f"[exp056] fracción de la ventaja del oráculo recuperada por estimated: {sm['fraction_recovered']:.3f}")
    log(f"[exp056] VEREDICTO H-V4-5b: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp056_estimated_value_memory", "cycle": 72, "hypothesis": "H-V4-5b",
           "claim": "la ventaja de la memoria dirigida por valor sobrevive con valor ESTIMADO online (frecuencia "
                    "observada = valor endógeno) y supera a una heuristica value-free (recencia/LRU)",
           "verdict": sm["status"], "summary": sm, "curves": curves, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp056] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
