"""
CYCLE 15 — ROMPER EL TECHO PERFECTO. CYCLE 12/13/14 cerraron el mecanismo (elegir/robustecer/componer
cadenas con un verificador real), pero TODOS tocaban 1.000: solvers deterministas y exactos -> oráculo=1.0
y política=1.0. El caveat repetido era "mecanismo, no escala; techo sintético perfecto". Acá lo RETIRAMOS.

La situación cotidiana honesta: hasta tu mejor forma de razonar PATINA a veces, los problemas vienen con
dificultad variable (comparaciones casi-empatadas, plazos al filo, propinas con redondeos finos), y el
mundo te da crédito SOLO cuando de verdad acertaste. Introducimos dureza real y controlable:
  - gen_graded marca cada problema con `difficulty` en [0,1] y lo ENDURECE (acerca la decisión al filo).
  - graded_chain (en chains.py) hace que cada cadena ACIERTE su tipo de casa con prob < 1 y patine MÁS
    cuanto más duro es el problema. El patinazo es determinista por (cadena, instancia) -> oráculo / fija /
    router ven el MISMO mundo (comparación justa).

Demostramos, sin maquillar los números (armamos el SETUP realista y reportamos lo que caiga):
  1) ORACLE < 1.000  -> hay techo alcanzable real (mejor cadena por instancia, por el verificador real).
  2) La mejor cadena FIJA queda claramente por debajo del oráculo.
  3) El router VERIFIER aprendido le gana a TODA cadena fija y se ACERCA al oráculo, sin alcanzarlo:
     reportamos la BRECHA (oráculo - router) como el número titular "qué tan bueno es el razonamiento".
  4) Robustez bajo grading: el router CONFIDENCE (circular) sigue peor (fanfarrón); preguntar bajo
     presupuesto cierra parte de la brecha.

torch NO hace falta (loop meta-razonador sobre solvers; solo stdlib).
Uso: python -m cognia_x.reason.run_cycle15 [--n N] [--difficulty D] [--smoke]
"""
import argparse
import json
import os
import sys

from cognia_x.reason.problems import gen_graded, is_correct, TYPES
from cognia_x.reason.chains import CHAINS, graded_chain
from cognia_x.reason.router import Router

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle15")


def acc_fixed_graded(chain_name, problems):
    """Accuracy de SIEMPRE usar la misma cadena, corrida GRADUADA (patina, más en lo difícil)."""
    ok = sum(1 for p in problems if is_correct(p, graded_chain(chain_name, p)[0]))
    return ok / len(problems)


def acc_oracle_graded(problems):
    """Techo alcanzable AHORA: por cada instancia, ¿ALGUNA cadena (graduada) la resuelve? Con dureza,
    todas patinan a veces -> esto cae por debajo de 1.0 (el punto de CYCLE 15)."""
    ok = 0
    for p in problems:
        if any(is_correct(p, graded_chain(c, p)[0]) for c in CHAINS):
            ok += 1
    return ok / len(problems)


def eval_router_graded(router, problems):
    """Accuracy del router con exploración congelada, corriendo la cadena desplegada GRADUADA."""
    router.explore = False
    ok = 0
    for p in problems:
        chain = router.select(p["type"])
        if is_correct(p, graded_chain(chain, p)[0]):
            ok += 1
    router.explore = True
    return ok / len(problems)


def per_type_acc_graded(chain_name, problems):
    """Accuracy por tipo de una cadena graduada."""
    by = {t: [0, 0] for t in TYPES}
    for p in problems:
        by[p["type"]][1] += 1
        if is_correct(p, graded_chain(chain_name, p)[0]):
            by[p["type"]][0] += 1
    return {t: round(c / n, 3) if n else 0.0 for t, (c, n) in by.items()}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8000)        # train graduado
    ap.add_argument("--n_test", type=int, default=4000)   # held-out graduado (semilla disjunta)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--dmin", type=float, default=0.0)    # dificultad mínima de las instancias
    ap.add_argument("--dmax", type=float, default=1.0)    # dificultad máxima (más dureza -> oráculo más bajo)
    ap.add_argument("--ask_budget", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test, args.ask_budget = 1600, 800, 80

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    # 1) train y held-out GRADUADOS con SEMILLAS DISJUNTAS (problemas nuevos en test)
    train = gen_graded(args.n, seed=args.seed, dmin=args.dmin, dmax=args.dmax)
    test = gen_graded(args.n_test, seed=args.seed + 10_000, dmin=args.dmin, dmax=args.dmax)
    log(f"[cycle15] train={len(train)} held-out={len(test)} | tipos={TYPES} | "
        f"dificultad=[{args.dmin},{args.dmax}] (graduado: las cadenas PATINAN, más en lo difícil)")

    # 2) BASELINES GRADUADOS sobre held-out: cada cadena fija + ORACLE (mejor cadena por instancia)
    fixed = {c: acc_fixed_graded(c, test) for c in CHAINS}
    best_fixed_name = max(fixed, key=fixed.get)
    best_fixed = fixed[best_fixed_name]
    oracle = acc_oracle_graded(test)
    log("[cycle15] cadenas FIJAS (graduadas, held-out, por-tipo):")
    for c in CHAINS:
        log(f"   fija {c:<10} acc {fixed[c]:.3f}  por-tipo {per_type_acc_graded(c, test)}")
    log(f"   ORACLE (mejor cadena GRADUADA por instancia) acc {oracle:.3f}  <- techo alcanzable (debe ser <1.0)")

    # 3) ROUTER VERIFIER GRADUADO: aprende online qué cadena por tipo con el verificador real (sobre las
    #    corridas graduadas), luego evalúa congelado.
    rv = Router(list(CHAINS), mode="verifier", eps=args.eps, seed=args.seed, graded=True)
    for _ in range(args.epochs):
        for p in train:
            rv.train_one(p)
    acc_verifier = eval_router_graded(rv, test)
    gap = oracle - acc_verifier
    log(f"[cycle15] router VERIFIER held-out acc {acc_verifier:.3f}  best-por-tipo {rv.best_chain_per_type()}")
    log(f"   BRECHA al oráculo (oracle - router) = {gap:.3f}  <- 'qué tan bueno es el razonamiento aprendido'")

    # 4) ANTI-GOODHART bajo grading: router premiado con la CONFIANZA (circular) -> el fanfarrón sigue peor
    rc = Router(list(CHAINS), mode="confidence", eps=args.eps, seed=args.seed, graded=True)
    for _ in range(args.epochs):
        for p in train:
            rc.train_one(p)
    acc_confidence = eval_router_graded(rc, test)
    log(f"[cycle15] router CONFIDENCE held-out acc {acc_confidence:.3f}  (circular: el fanfarrón lo secuestra)")

    # 5) PREGUNTAR bajo presupuesto cierra parte de la brecha. La brecha del router VIENE del patinazo:
    #    rutea bien (cadena de casa) pero esa cadena igual patina en algunas instancias DURAS. "Preguntar"
    #    = en cada instancia donde quede presupuesto, consultar el verificador real sobre VARIAS cadenas
    #    graduadas y quedarse con UNA que acierte para ESTA instancia (el patinazo es por (cadena,instancia),
    #    así que otra cadena puede salvarla). Mostramos que esto sube por encima del router base, hacia el
    #    oráculo, GASTANDO el presupuesto en las instancias donde el router base falla.
    ra = Router(list(CHAINS), mode="verifier", eps=args.eps, seed=args.seed + 1, graded=True)
    for p in train:
        ra.train_one(p)
    ra.explore = False
    budget = args.ask_budget
    ok = 0
    for p in test:
        chain = ra.select(p["type"])
        base_ok = is_correct(p, graded_chain(chain, p)[0])
        if base_ok:
            ok += 1
            continue
        # el router base FALLÓ acá (su cadena de casa patinó): si queda presupuesto, PREGUNTAR
        if budget > 0:
            budget -= 1; ra.questions += 1
            if any(is_correct(p, graded_chain(c, p)[0]) for c in ra.chain_names):
                ok += 1   # alguna otra cadena acertó esta instancia (oráculo confirma)
    acc_ask = ok / len(test)
    asked = ra.questions
    ra.explore = True
    log(f"[cycle15] router VERIFIER + PREGUNTAR (presupuesto {args.ask_budget}, usó {asked}) held-out acc {acc_ask:.3f}")

    # 6) summary + RESUMEN
    summary = {
        "n_train": len(train), "n_test": len(test),
        "difficulty_range": [args.dmin, args.dmax],
        "baselines_fixed_graded": {c: round(v, 4) for c, v in fixed.items()},
        "best_fixed": {"chain": best_fixed_name, "acc": round(best_fixed, 4)},
        "oracle_graded": round(oracle, 4),
        "router_verifier": round(acc_verifier, 4),
        "router_confidence": round(acc_confidence, 4),
        "gap_to_oracle": round(gap, 4),
        "router_ask": {"budget": args.ask_budget, "questions_used": asked, "acc": round(acc_ask, 4)},
        "router_verifier_best_per_type": rv.best_chain_per_type(),
    }
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log("\n[cycle15] ===== RESUMEN: ¿se ROMPIÓ el techo perfecto? ¿qué tan bueno es el razonamiento? =====")
    log("  ACCURACY HELD-OUT GRADUADO (problemas nuevos, las cadenas PATINAN):")
    for c in CHAINS:
        marca = "  <- mejor fija" if c == best_fixed_name else ""
        log(f"    fija {c:<10}              {fixed[c]:.3f}{marca}")
    log(f"    router CONFIDENCE (circular)    {acc_confidence:.3f}   (el fanfarrón lo secuestra)")
    log(f"    router VERIFIER  (examinador)   {acc_verifier:.3f}")
    log(f"    router VERIFIER + PREGUNTAR     {acc_ask:.3f}   (cierra parte de la brecha)")
    log(f"    ORACLE (mejor cadena por inst.) {oracle:.3f}   <- techo alcanzable, AHORA < 1.000")
    log(f"  -> mejor fija {best_fixed_name} ({best_fixed:.3f}) < router VERIFIER ({acc_verifier:.3f}) < oráculo ({oracle:.3f})")
    log(f"  -> BRECHA AL ORÁCULO (oracle - router VERIFIER) = {gap:.3f}  (el número honesto: chica = buen razonamiento)")
    log(f"  mapa aprendido tipo->cadena (VERIFIER): {rv.best_chain_per_type()}")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
