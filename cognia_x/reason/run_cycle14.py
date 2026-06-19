"""
CYCLE 14 — cerrar el sentido literal de "cadenas de razonamiento": COMPONER cadenas. Hasta acá todo
problema se resolvía con UNA cadena (esa era la brecha honesta de CYCLE 12/13). Los problemas reales
piden MÁS DE UN MOVIMIENTO: la respuesta necesita el resultado del paso 1 como entrada del paso 2.
Situación cotidiana: "¿qué paquete conviene por kg Y cuántos entran en mi presupuesto con el envío?",
"divido la cuenta con propina Y veo si la cuota pasa mi límite", "calculo el consumo diario Y veo
cuántos días me alcanza el stock". Ninguna forma SOLA de pensar lo resuelve; hay que ENCADENAR.

Demostramos, sin trampa (el mecanismo las produce de verdad):
  1) NINGUNA cadena fija de un paso resuelve los tipos compuestos (todas muy por debajo de 1.0) ->
     la composición es NECESARIA.
  2) El COMPOSER aprendido (bandit sobre SECUENCIAS, premiado por el verificador real) DESCUBRE el
     programa correcto por tipo, supera a toda cadena fija y se ACERCA al oráculo (mejor programa por
     instancia) sobre problemas NUEVOS (held-out) -> aprendió a componer y GENERALIZA.
  3) Anti-Goodhart en PROGRAMAS: un composer premiado con la CONFIANZA auto-reportada (circular) es
     secuestrado por programas con el paso fanfarrón (step_direct, conf ~0.95) y rinde PEOR -> la misma
     lección no-circular del lab, ahora en el espacio de secuencias.

torch NO hace falta (loop meta-razonador sobre solvers deterministas; solo stdlib).
Uso: python -m cognia_x.reason.run_cycle14 [--n N] [--smoke]
"""
import argparse
import json
import os
import sys

from cognia_x.reason.problems import gen_composed, is_correct, COMPOSED_TYPES
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.composer import Composer, run_program, enumerate_programs

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle14")


def acc_fixed_single(chain_name, problems):
    """Accuracy de SIEMPRE usar la misma cadena de UN paso (de CHAINS, las de cycle12)."""
    ok = sum(1 for p in problems if is_correct(p, CHAINS[chain_name](p)[0]))
    return ok / len(problems)


def acc_program_oracle(problems, max_len=2):
    """Cota superior: por cada problema, ¿existe ALGÚN programa (long<=max_len) que lo resuelva?"""
    progs = enumerate_programs(max_len)
    ok = 0
    for p in problems:
        if any(is_correct(p, run_program(p, prog)[0]) for prog in progs):
            ok += 1
    return ok / len(problems)


def eval_composer(comp, problems):
    """Accuracy del composer con exploración congelada (despliega el mejor programa aprendido por tipo)."""
    comp.explore = False
    ok = sum(1 for p in problems if is_correct(p, run_program(p, comp.deploy(p["type"]))[0]))
    comp.explore = True
    return ok / len(problems)


def per_type_acc_single(chain_name, problems):
    """Accuracy por tipo compuesto de una cadena de un paso."""
    by = {t: [0, 0] for t in COMPOSED_TYPES}
    for p in problems:
        by[p["type"]][1] += 1
        if is_correct(p, CHAINS[chain_name](p)[0]):
            by[p["type"]][0] += 1
    return {t: (c / n if n else 0.0) for t, (c, n) in by.items()}


def per_type_acc_composer(comp, problems):
    """Accuracy por tipo compuesto del composer (programa desplegado por tipo)."""
    comp.explore = False
    by = {t: [0, 0] for t in COMPOSED_TYPES}
    for p in problems:
        by[p["type"]][1] += 1
        if is_correct(p, run_program(p, comp.deploy(p["type"]))[0]):
            by[p["type"]][0] += 1
    comp.explore = True
    return {t: (c / n if n else 0.0) for t, (c, n) in by.items()}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)        # train compuesto
    ap.add_argument("--n_test", type=int, default=2000)   # held-out compuesto (semilla disjunta)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--max_len", type=int, default=2)     # longitud máxima de programa a explorar
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test = 900, 450

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    # 1) train y held-out COMPUESTOS con SEMILLAS DISJUNTAS (problemas nuevos en test)
    train = gen_composed(args.n, seed=args.seed)
    test = gen_composed(args.n_test, seed=args.seed + 10_000)
    n_progs = len(enumerate_programs(args.max_len))
    log(f"[cycle14] train={len(train)} held-out={len(test)} | tipos compuestos={COMPOSED_TYPES} "
        f"| espacio de programas (long<= {args.max_len})={n_progs}")

    # 2) BASELINE: cada cadena FIJA de UN paso sobre los tipos compuestos (held-out) -> deben ser pobres
    fixed = {c: acc_fixed_single(c, test) for c in CHAINS}
    best_fixed_name = max(fixed, key=fixed.get)
    best_fixed = fixed[best_fixed_name]
    oracle = acc_program_oracle(test, max_len=args.max_len)
    log("[cycle14] cadenas FIJAS de un paso (held-out, por-tipo):")
    for c in CHAINS:
        log(f"   fija {c:<10} acc {fixed[c]:.3f}  por-tipo {per_type_acc_single(c, test)}")
    log(f"   ORACLE (mejor PROGRAMA por instancia, long<= {args.max_len}) acc {oracle:.3f}")

    # 3) COMPOSER VERIFIER: aprende online qué SECUENCIA por tipo con el verificador real, luego congela
    cv = Composer(max_len=args.max_len, mode="verifier", eps=args.eps, seed=args.seed)
    for _ in range(args.epochs):
        for p in train:
            cv.train_one(p)
    acc_verifier = eval_composer(cv, test)
    map_v = {t: list(prog) for t, prog in cv.best_program_per_type().items()}
    log(f"[cycle14] composer VERIFIER held-out acc {acc_verifier:.3f}")
    log(f"   programas descubiertos (VERIFIER): {map_v}")

    # 4) ANTI-GOODHART: composer premiado con la CONFIANZA (circular) -> el paso fanfarrón lo secuestra
    cc = Composer(max_len=args.max_len, mode="confidence", eps=args.eps, seed=args.seed)
    for _ in range(args.epochs):
        for p in train:
            cc.train_one(p)
    acc_confidence = eval_composer(cc, test)
    map_c = {t: list(prog) for t, prog in cc.best_program_per_type().items()}
    log(f"[cycle14] composer CONFIDENCE held-out acc {acc_confidence:.3f}")
    log(f"   programas 'elegidos' por confianza (circular): {map_c}")

    # 5) summary + RESUMEN
    summary = {
        "n_train": len(train), "n_test": len(test), "max_len": args.max_len,
        "n_programs": n_progs,
        "composed_types": COMPOSED_TYPES,
        "baselines_fixed_single": {c: round(v, 4) for c, v in fixed.items()},
        "best_fixed_single": {"chain": best_fixed_name, "acc": round(best_fixed, 4)},
        "oracle_best_program": round(oracle, 4),
        "composer_verifier": round(acc_verifier, 4),
        "composer_confidence": round(acc_confidence, 4),
        "composer_verifier_program_per_type": map_v,
        "composer_confidence_program_per_type": map_c,
        "composer_verifier_per_type": per_type_acc_composer(cv, test),
    }
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log("\n[cycle14] ===== RESUMEN: ¿aprendió a COMPONER (qué SECUENCIA por tipo)? =====")
    log("  ACCURACY HELD-OUT en tipos COMPUESTOS (problemas nuevos):")
    for c in CHAINS:
        marca = "  <- mejor fija (igual pobre)" if c == best_fixed_name else ""
        log(f"    cadena fija de UN paso {c:<10}  {fixed[c]:.3f}{marca}")
    log(f"    composer CONFIDENCE (circular)        {acc_confidence:.3f}   (el paso fanfarrón lo secuestra)")
    log(f"    composer VERIFIER  (examinador REAL)  {acc_verifier:.3f}")
    log(f"    ORACLE (mejor programa por instancia) {oracle:.3f}   (cota superior)")
    log(f"  -> ninguna cadena sola pasa de {best_fixed:.3f}; el composer VERIFIER llega a {acc_verifier:.3f} ~ oracle {oracle:.3f}")
    log("  PROGRAMAS DESCUBIERTOS (VERIFIER) tipo->secuencia:")
    for t in COMPOSED_TYPES:
        log(f"    {t:<18} -> {tuple(map_v.get(t, []))}")
    log("  programas 'elegidos' por CONFIDENCE (circular, secuestrado):")
    for t in COMPOSED_TYPES:
        log(f"    {t:<18} -> {tuple(map_c.get(t, []))}")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
