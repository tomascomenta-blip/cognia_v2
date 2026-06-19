"""
CYCLE 13 — razonar en el régimen REALISTA: el examinador no siempre dice la verdad, y a veces te
toca un problema que nunca viste. Dos robusteces cotidianas, construidas SOBRE el router de CYCLE 12
(mismas cadenas, mismo verificador de verdad-base, misma idea de "preguntarle al usuario"):

  PROBLEMA A — el usuario a veces te contesta MAL (oráculo RUIDOSO).
    "Le preguntás a alguien y te contesta mal con prob p_noise." Un router que pregunta UNA vez y
    confía ciego aprende un mapa tipo->cadena CORROMPIDO a medida que sube p_noise. El arreglo
    (innovador y de todos los días): "preguntá a VARIOS y quedate con lo que más se repite" =
    voto MAYORÍA sobre K respuestas + acumular la señal ruidosa sobre muchos intentos. La ley de
    los grandes números protege la política aunque cada respuesta sea ruidosa.
    -> barremos p_noise (0.0, 0.2, 0.4) y comparamos held-out: blind-single vs robust-aggregate.

  PROBLEMA B — un TIPO nunca visto en entrenamiento (fuera-de-distribución: saber lo que no sabés).
    Agregamos un 5º tipo NUEVO ("discount_better": X% off vs $Y off sobre un precio) que aparece
    SOLO en el test. Un router naive rutea confiado a alguna cadena y falla seguido. El arreglo:
    una señal de INCERTIDUMBRE por falta de evidencia -> cuando casi no vio un tipo, ESCALA
    (pregunta) en vez de adivinar. Medimos: pregunta MUCHO más en el tipo nuevo que en los
    familiares (calibrado), y tras unas escaladas APRENDE también el tipo nuevo.

torch NO hace falta (loop meta-razonador sobre solvers deterministas; solo stdlib).
Uso: python -m cognia_x.reason.run_cycle13 [--smoke]
"""
import argparse
import json
import os
import sys
from random import Random

from cognia_x.reason.problems import gen_problems, is_correct, TYPES, OOD_TYPE
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.router import Router

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle13")


def eval_router(router, problems):
    """Accuracy del router con exploración congelada (despliega la mejor cadena aprendida por tipo)."""
    router.explore = False
    ok = sum(1 for p in problems if is_correct(p, CHAINS[router.deploy_chain(p["type"])](p)[0]))
    router.explore = True
    return ok / len(problems)


def train_noisy(mode, train, test, p_noise, k, eps, seed):
    """Entrena un router con oráculo ruidoso (blind o aggregate) y devuelve (acc_held_out, mapa)."""
    r = Router(list(CHAINS), mode="verifier", eps=eps, seed=seed)
    rng = Random(seed + 7)
    for p in train:
        r.solve_noisy(p, mode=mode, p_noise=p_noise, k=k, rng=rng)
    deployed = {t: r.deploy_chain(t) for t in r.stats} if mode != "blind" else dict(r.locked_map)
    return eval_router(r, test), deployed


def train_noisy_avg(mode, train, test, p_noise, k, eps, base_seed, seeds):
    """
    Promedia el accuracy held-out sobre varias semillas. WHY: 'confiar ciego en una respuesta' es
    estocástico (una sola respuesta puede ser buena o mala por suerte). Promediar sobre semillas
    muestra el comportamiento ESPERADO honesto, no una corrida con suerte. Devuelve (media, mapa_ej).
    """
    accs, last_map = [], {}
    for i in range(seeds):
        a, m = train_noisy(mode, train, test, p_noise, k, eps, base_seed + i * 101)
        accs.append(a); last_map = m
    return sum(accs) / len(accs), last_map


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)         # train (tipos familiares)
    ap.add_argument("--n_test", type=int, default=2000)    # held-out (tipos familiares)
    ap.add_argument("--n_ood", type=int, default=800)      # problemas del tipo NUEVO (solo test)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--k", type=int, default=5)            # votos por pregunta (robust-aggregate)
    ap.add_argument("--min_obs", type=int, default=8)      # umbral OOD: menos obs -> escala
    ap.add_argument("--ask_budget", type=int, default=400)
    ap.add_argument("--noise_grid", type=str, default="0.0,0.2,0.4")
    ap.add_argument("--seeds", type=int, default=15)       # semillas para promediar blind/aggregate
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test, args.n_ood, args.ask_budget, args.seeds = 1200, 600, 300, 150, 8

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    # datos: train/test de los 4 tipos FAMILIARES (semillas disjuntas) -> held-out de verdad
    train = gen_problems(args.n, seed=args.seed)
    test = gen_problems(args.n_test, seed=args.seed + 10_000)
    # tipo NUEVO: SOLO en test (nunca entrenado) -> fuera-de-distribución
    ood = gen_problems(args.n_ood, seed=args.seed + 20_000, types=[OOD_TYPE])
    log(f"[cycle13] train={len(train)} held-out={len(test)} OOD({OOD_TYPE})={len(ood)} | familiares={TYPES}")

    noise_grid = [float(x) for x in args.noise_grid.split(",")]

    # =========================================================================
    # PROBLEMA A — oráculo RUIDOSO: blind-single (confía ciego) vs robust-aggregate (vota K)
    # =========================================================================
    log("\n[cycle13] PROBLEMA A — el usuario a veces contesta MAL (barrido de p_noise):")
    sweep = []
    for pn in noise_grid:
        acc_blind, map_blind = train_noisy_avg("blind", train, test, pn, args.k, args.eps, args.seed, args.seeds)
        acc_aggr, map_aggr = train_noisy_avg("aggregate", train, test, pn, args.k, args.eps, args.seed, args.seeds)
        sweep.append({"p_noise": pn,
                      "blind_single": round(acc_blind, 4),
                      "robust_aggregate": round(acc_aggr, 4),
                      "map_blind_example": map_blind, "map_aggregate_example": map_aggr})
        log(f"   p_noise={pn:.2f} | blind-single(media {args.seeds} seeds)={acc_blind:.3f}  "
            f"robust-aggregate(K={args.k})={acc_aggr:.3f}")

    # =========================================================================
    # PROBLEMA B — tipo NUEVO (OOD): naive (rutea confiado) vs escalación (sabe que no sabe)
    # =========================================================================
    log("\n[cycle13] PROBLEMA B — tipo NUEVO nunca visto (fuera-de-distribución):")

    # B0) NAIVE: router ya entrenado en los familiares, enfrenta el tipo nuevo SIN escalar (adivina).
    rn = Router(list(CHAINS), mode="verifier", eps=args.eps, seed=args.seed)
    for p in train:
        rn.train_one(p)
    acc_ood_naive = eval_router(rn, ood)   # nunca vio discount_better -> elige por stats vacías
    log(f"   NAIVE (sin escalar): acc en tipo NUEVO = {acc_ood_naive:.3f}  (adivina; no sabe que no sabe)")

    # B1) ESCALACIÓN: mismo router, pero al ver tipos con poca evidencia ESCALA (pregunta) y aprende.
    #     Mezclamos familiares + el tipo nuevo en un stream de test online para medir ASK-RATE por tipo.
    re = Router(list(CHAINS), mode="verifier", eps=args.eps, seed=args.seed)
    for p in train:
        re.train_one(p)        # llega ya competente en los familiares (mucha evidencia)
    rng_ood = Random(args.seed + 33)
    stream = list(test[:len(ood)]) + list(ood)   # familiares (conocidos) + nuevos (OOD)
    rng_ood.shuffle(stream)
    budget = args.ask_budget
    asks_by_type = {t: [0, 0] for t in (list(TYPES) + [OOD_TYPE])}   # [asked, total]
    ood_correct_first, ood_seen = 0, 0
    for p in stream:
        t = p["type"]
        _, correct, asked, budget = re.solve_ood(
            p, ask_budget=budget, min_obs=args.min_obs, p_noise=0.0, k=args.k, rng=rng_ood)
        asks_by_type[t][1] += 1
        if asked:
            asks_by_type[t][0] += 1
        if t == OOD_TYPE:
            ood_seen += 1
            ood_correct_first += 1 if correct else 0
    ask_rate = {t: (a / n if n else 0.0) for t, (a, n) in asks_by_type.items()}
    acc_ood_escalated = eval_router(re, ood)   # tras escalar/aprender, ¿resuelve el tipo nuevo?
    fam_ask = max(ask_rate[t] for t in TYPES)   # peor (mayor) ask-rate entre familiares
    log(f"   ask-rate por tipo (escalación): {{ {', '.join(f'{t}={ask_rate[t]:.3f}' for t in (list(TYPES)+[OOD_TYPE]))} }}")
    log(f"   -> familiares ask-rate <= {fam_ask:.3f} | tipo NUEVO ask-rate = {ask_rate[OOD_TYPE]:.3f}")
    log(f"   acc en tipo NUEVO: naive={acc_ood_naive:.3f}  con-escalación={acc_ood_escalated:.3f}")

    # =========================================================================
    # summary + RESUMEN
    # =========================================================================
    summary = {
        "n_train": len(train), "n_test": len(test), "n_ood": len(ood),
        "ood_type": OOD_TYPE, "k": args.k, "min_obs": args.min_obs,
        "problem_A_noisy_oracle": {"noise_grid": noise_grid, "sweep": sweep},
        "problem_B_ood": {
            "ask_rate_by_type": {t: round(ask_rate[t], 4) for t in (list(TYPES) + [OOD_TYPE])},
            "familiar_max_ask_rate": round(fam_ask, 4),
            "ood_ask_rate": round(ask_rate[OOD_TYPE], 4),
            "acc_ood_naive": round(acc_ood_naive, 4),
            "acc_ood_escalated": round(acc_ood_escalated, 4),
        },
    }
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log("\n[cycle13] ===== RESUMEN A: oráculo RUIDOSO (held-out) =====")
    log("  p_noise | blind-single | robust-aggregate")
    for s in sweep:
        log(f"    {s['p_noise']:.2f}   |    {s['blind_single']:.3f}    |    {s['robust_aggregate']:.3f}")
    base = sweep[0]["robust_aggregate"]
    worst_blind = min(s["blind_single"] for s in sweep)
    log(f"  -> blind-single CAE hasta {worst_blind:.3f} con ruido; robust-aggregate se mantiene ~{base:.3f}")

    log("\n[cycle13] ===== RESUMEN B: tipo NUEVO fuera-de-distribución =====")
    log("  ASK-RATE (cuánto PREGUNTA por tipo):")
    for t in TYPES:
        log(f"    familiar {t:<20} {ask_rate[t]:.3f}")
    log(f"    NUEVO    {OOD_TYPE:<20} {ask_rate[OOD_TYPE]:.3f}  <- pregunta MUCHO más (sabe que no sabe)")
    log(f"  ACC en el tipo NUEVO:  naive {acc_ood_naive:.3f}  ->  con-escalación {acc_ood_escalated:.3f}")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
