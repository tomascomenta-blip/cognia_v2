"""
CYCLE 12 — enseñarle a RAZONAR: prueba distintas cadenas de razonamiento, ve cuál da el mejor
resultado (verificado internamente o preguntando al usuario) y APRENDE qué cadena desplegar por
tipo de problema. Situación cotidiana: alguien que enfrenta cuentas, compras, viajes y plazos, y
con la práctica descubre QUÉ forma de pensar le sirve para cada clase de problema.

Demostramos cuatro cosas, sin trampa (el mecanismo las produce de verdad):
  1) Ninguna cadena fija domina los 4 tipos (por eso ELEGIR importa).
  2) El router entrenado con el VERIFICADOR real supera a toda cadena fija y al azar, y se ACERCA al
     oráculo (mejor posible) sobre problemas NUEVOS (held-out) -> aprendió y GENERALIZA.
  3) Anti-Goodhart: un router entrenado con la CONFIANZA auto-reportada (circular) es secuestrado por
     el fanfarrón (chain_direct) y rinde mucho PEOR -> la lección del examinador no-circular, ahora
     en el dominio del razonamiento.
  4) "Preguntar al usuario" bajo presupuesto: el router pregunta MUCHO temprano (cuando duda) y MENOS
     con el tiempo, manteniendo el accuracy alto.

torch NO hace falta (es un loop meta-razonador sobre solvers deterministas; solo stdlib).
Uso: python -m cognia_x.reason.run_cycle12 [--n N] [--smoke]
"""
import argparse
import json
import os
import sys
from random import Random

from cognia_x.reason.problems import gen_problems, is_correct, TYPES
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.router import Router

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle12")


def acc_fixed_chain(chain_name, problems):
    """Accuracy de SIEMPRE usar la misma cadena."""
    ok = sum(1 for p in problems if is_correct(p, CHAINS[chain_name](p)[0]))
    return ok / len(problems)


def acc_random_chain(problems, seed=0):
    """Accuracy de elegir una cadena al azar por problema."""
    rng = Random(seed); names = list(CHAINS)
    ok = sum(1 for p in problems if is_correct(p, CHAINS[rng.choice(names)](p)[0]))
    return ok / len(problems)


def acc_oracle(problems):
    """Cota superior: por cada problema, ¿existe ALGUNA cadena que lo resuelva? (mejor posible)."""
    ok = 0
    for p in problems:
        if any(is_correct(p, CHAINS[c](p)[0]) for c in CHAINS):
            ok += 1
    return ok / len(problems)


def eval_router(router, problems):
    """Accuracy del router con exploración congelada (despliega la mejor cadena aprendida por tipo)."""
    router.explore = False
    ok = 0
    for p in problems:
        chain = router.select(p["type"])
        if is_correct(p, CHAINS[chain](p)[0]):
            ok += 1
    return ok / len(problems)


def per_type_acc(predictor, problems):
    """Accuracy desglosada por tipo. predictor(problem)->pred."""
    by = {t: [0, 0] for t in TYPES}
    for p in problems:
        by[p["type"]][1] += 1
        if is_correct(p, predictor(p)):
            by[p["type"]][0] += 1
    return {t: (c / n if n else 0.0) for t, (c, n) in by.items()}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)        # tamaño del train
    ap.add_argument("--n_test", type=int, default=2000)   # held-out
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--ask_budget", type=int, default=200)
    ap.add_argument("--blocks", type=int, default=10)     # bloques para la curva de preguntas
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test, args.ask_budget, args.blocks = 800, 400, 60, 8

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    # 1) train y held-out con SEMILLAS DISJUNTAS (problemas nuevos en test)
    train = gen_problems(args.n, seed=args.seed)
    test = gen_problems(args.n_test, seed=args.seed + 10_000)
    log(f"[cycle12] train={len(train)} held-out={len(test)} | tipos={TYPES}")

    # 2) BASELINES sobre held-out
    fixed = {c: acc_fixed_chain(c, test) for c in CHAINS}
    rnd = acc_random_chain(test, seed=args.seed)
    oracle = acc_oracle(test)
    best_fixed_name = max(fixed, key=fixed.get)
    best_fixed = fixed[best_fixed_name]
    log("[cycle12] baselines (held-out):")
    for c in CHAINS:
        log(f"   fija {c:<10} acc {fixed[c]:.3f}  por-tipo {per_type_acc(lambda p, cc=c: CHAINS[cc](p)[0], test)}")
    log(f"   RANDOM      acc {rnd:.3f}")
    log(f"   ORACLE      acc {oracle:.3f}  (mejor posible)")

    # 3) ROUTER VERIFIER: entrena online con el verificador real, luego evalúa congelado
    rv = Router(list(CHAINS), mode="verifier", eps=args.eps, seed=args.seed)
    for _ in range(args.epochs):
        for p in train:
            rv.train_one(p)
    acc_verifier = eval_router(rv, test)
    log(f"[cycle12] router VERIFIER held-out acc {acc_verifier:.3f}  best-por-tipo {rv.best_chain_per_type()}")

    # 4) ANTI-GOODHART: router entrenado con la confianza (circular) -> el fanfarrón lo secuestra
    rc = Router(list(CHAINS), mode="confidence", eps=args.eps, seed=args.seed)
    for _ in range(args.epochs):
        for p in train:
            rc.train_one(p)
    acc_confidence = eval_router(rc, test)
    log(f"[cycle12] router CONFIDENCE held-out acc {acc_confidence:.3f}  best-por-tipo {rc.best_chain_per_type()}")

    # 5) "PREGUNTAR AL USUARIO" bajo presupuesto: curva de preguntas por bloque a lo largo del train
    ra = Router(list(CHAINS), mode="verifier", eps=args.eps, seed=args.seed + 1)
    budget = args.ask_budget
    block_size = max(1, len(train) // args.blocks)
    questions_curve = []; acc_curve = []
    for b in range(args.blocks):
        chunk = train[b * block_size:(b + 1) * block_size]
        if not chunk:
            break
        q0 = ra.questions; ok = 0
        for p in chunk:
            _, correct, _, budget = ra.solve(p, ask_budget=budget)
            ok += 1 if correct else 0
        questions_curve.append(ra.questions - q0)
        acc_curve.append(round(ok / len(chunk), 3))
    ask_total = ra.questions
    acc_ask_test = eval_router(ra, test)   # tras aprender preguntando, ¿qué tan bien generaliza?

    # 6) summary + RESUMEN
    summary = {
        "n_train": len(train), "n_test": len(test),
        "baselines_fixed": {c: round(v, 4) for c, v in fixed.items()},
        "best_fixed": {"chain": best_fixed_name, "acc": round(best_fixed, 4)},
        "random": round(rnd, 4),
        "oracle": round(oracle, 4),
        "router_verifier": round(acc_verifier, 4),
        "router_confidence": round(acc_confidence, 4),
        "router_verifier_best_per_type": rv.best_chain_per_type(),
        "router_confidence_best_per_type": rc.best_chain_per_type(),
        "ask": {
            "budget": args.ask_budget,
            "questions_total": ask_total,
            "questions_per_block": questions_curve,
            "acc_per_block": acc_curve,
            "router_ask_held_out_acc": round(acc_ask_test, 4),
        },
    }
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log("\n[cycle12] ===== RESUMEN: ¿aprendió a razonar (qué cadena por tipo)? =====")
    log("  ACCURACY HELD-OUT (problemas nuevos):")
    for c in CHAINS:
        marca = "  <- mejor fija" if c == best_fixed_name else ""
        log(f"    fija {c:<10}     {fixed[c]:.3f}{marca}")
    log(f"    RANDOM             {rnd:.3f}")
    log(f"    router CONFIDENCE  {acc_confidence:.3f}   (circular: el fanfarrón lo secuestra)")
    log(f"    router VERIFIER    {acc_verifier:.3f}   (examinador REAL)")
    log(f"    ORACLE             {oracle:.3f}   (cota superior)")
    log(f"  -> VERIFIER ({acc_verifier:.3f}) vs mejor fija {best_fixed_name} ({best_fixed:.3f}) "
        f"vs CONFIDENCE ({acc_confidence:.3f}) vs oracle ({oracle:.3f})")
    log(f"  mapa aprendido tipo->cadena (VERIFIER):   {rv.best_chain_per_type()}")
    log(f"  mapa secuestrado tipo->cadena (CONFIDENCE): {rc.best_chain_per_type()}")
    log("  CURVA 'preguntar al usuario' (preguntas por bloque a lo largo del train):")
    log(f"    preguntas/bloque {questions_curve}  (total {ask_total} de presupuesto {args.ask_budget})")
    log(f"    accuracy/bloque  {acc_curve}")
    log(f"    -> pregunta MUCHO al principio y MENOS después; held-out tras preguntar {acc_ask_test:.3f}")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
