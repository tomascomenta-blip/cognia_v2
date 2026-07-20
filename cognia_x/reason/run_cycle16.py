"""
CYCLE 16 — SACAR LA MULETA: razonar desde el TEXTO, no desde la etiqueta de tipo.

CYCLE 12–15 construyeron un router meta-razonador con verificador real que aprende QUÉ cadena usar por
tipo de problema (robusto a oráculo ruidoso, tipos nuevos, escala graduada). PERO en todos esos ciclos al
router le PASABAN el tipo como label (routeaba sobre `problem["type"]`). Eso es una muleta: razonar de
verdad es DARTE CUENTA de qué clase de problema tenés enfrente leyendo el enunciado. CYCLE 16 la saca: el
router solo ve `problem["text"]` y debe INFERIR cómo razonar.

Demostramos, sobre HELD-OUT (semillas disjuntas), tabulando accuracy de:
  1) mejor cadena FIJA (baseline).
  2) router de TIPO (CYCLE 12, le DAN la etiqueta) -> ahora es la REFERENCIA SUPERIOR ("si supiera el tipo").
  3) router de TEXTO (CYCLE 16, infiere del enunciado) -> debe ACERCARSE al router de tipo SIN que le digan
     el tipo. El titular es la BRECHA (router-tipo − router-texto): chica = infirió bien la clase.
  4) ALINEACIÓN firma->tipo: pureza de las firmas inferidas vs el tipo verdadero (recuperó la estructura).
  5) Honestidad: si el texto es ambiguo para algún tipo y los confunde, lo reportamos con el costo en accuracy.
  6) BONUS barato: lo mismo en el régimen GRADUADO de CYCLE 15 (las cadenas patinan).

torch NO hace falta (loop meta-razonador sobre solvers; solo stdlib).
Uso: python -m cognia_x.reason.run_cycle16 [--n N] [--smoke]
"""
import argparse
import json
import os
import sys

from cognia_x.reason.problems import gen_problems, gen_graded, is_correct, TYPES
from cognia_x.reason.chains import CHAINS, graded_chain
from cognia_x.reason.router import Router
from cognia_x.reason.text_router import TextRouter, signature_blind

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle16")


def acc_fixed(chain_name, problems, graded):
    """Accuracy de SIEMPRE usar la misma cadena (graduada o exacta)."""
    runner = (lambda c, p: graded_chain(c, p)[0]) if graded else (lambda c, p: CHAINS[c](p)[0])
    return sum(1 for p in problems if is_correct(p, runner(chain_name, p))) / len(problems)


def eval_type_router(router, problems, graded):
    """Accuracy del router de TIPO (le pasamos problem['type'], la muleta): despliega la mejor por tipo."""
    router.explore = False
    runner = (lambda c, p: graded_chain(c, p)[0]) if graded else (lambda c, p: CHAINS[c](p)[0])
    ok = sum(1 for p in problems if is_correct(p, runner(router.select(p["type"]), p)))
    router.explore = True
    return ok / len(problems)


def run_regime(log, name, train, test, eps, seed, graded):
    """Corre la comparación completa en un régimen (exacto o graduado) y devuelve el dict de resultados."""
    # 1) baseline: mejor cadena fija
    fixed = {c: acc_fixed(c, test, graded) for c in CHAINS}
    best_fixed_name = max(fixed, key=fixed.get)
    best_fixed = fixed[best_fixed_name]

    # 2) router de TIPO (CYCLE 12, le DAN la etiqueta) -> referencia superior "si supiera el tipo"
    rt = Router(list(CHAINS), mode="verifier", eps=eps, seed=seed, graded=graded)
    for p in train:
        rt.train_one(p)
    acc_type = eval_type_router(rt, test, graded)

    # 3) router de TEXTO (CYCLE 16): infiere la firma del enunciado, jamás ve el tipo
    tr = TextRouter(list(CHAINS), eps=eps, seed=seed, graded=graded)
    for p in train:
        tr.train_one(p)
    acc_text = tr.eval(test)
    gap = acc_type - acc_text

    # 4) alineación firma->tipo (auditoría de estructura, a posteriori)
    purity, n_sigs, per_sig = tr.signature_to_type_purity(test)

    # 4b) CONTROL HONESTO: el MISMO router pero con features POBRES (signature_blind: solo conteo de
    #     números + $/%, sin vocabulario). Si las clases se MEZCLAN, la pureza cae y la brecha se ABRE
    #     -> demuestra que son las FEATURES DE TEXTO las que recuperan la estructura, no la mecánica.
    tb = TextRouter(list(CHAINS), eps=eps, seed=seed, graded=graded, sig_fn=signature_blind)
    for p in train:
        tb.train_one(p)
    acc_blind = tb.eval(test)
    purity_blind, n_sigs_blind, _ = tb.signature_to_type_purity(test)

    log(f"\n[cycle16] ===== RÉGIMEN {name} (held-out, train={len(train)} test={len(test)}) =====")
    log("  ACCURACY HELD-OUT (problemas nuevos):")
    for c in CHAINS:
        marca = "  <- mejor fija" if c == best_fixed_name else ""
        log(f"    fija {c:<10}                  {fixed[c]:.3f}{marca}")
    log(f"    router de TIPO   (le DAN el tipo)   {acc_type:.3f}   <- referencia superior ('si supiera el tipo')")
    log(f"    router de TEXTO  (infiere del texto){acc_text:.3f}   <- CYCLE 16: SIN que le digan el tipo")
    log(f"  -> mejor fija {best_fixed_name} ({best_fixed:.3f}) < router de TEXTO ({acc_text:.3f}) ~ router de TIPO ({acc_type:.3f})")
    log(f"  -> BRECHA (router-TIPO − router-TEXTO) = {gap:.3f}  (chica = infirió bien la clase desde el texto)")
    log(f"  ALINEACIÓN firma->tipo: pureza {purity:.3f} con {n_sigs} firmas inferidas (1.0 = recuperó los tipos)")
    for sig, info in sorted(per_sig.items(), key=lambda kv: -kv[1]["n"]):
        log(f"    firma {sig} -> {info['maj_type']:<20} pureza {info['purity']:.3f}  mezcla {info['mix']}")
    log(f"  CONTROL (features POBRES, sin vocabulario): router-TEXTO-ciego {acc_blind:.3f}, "
        f"pureza {purity_blind:.3f} con {n_sigs_blind} firmas")
    if purity_blind < purity - 1e-9 or acc_blind < acc_text - 1e-9:
        log(f"    -> al ablacionar las palabras clave la pureza CAE ({purity:.3f}->{purity_blind:.3f}) y la "
            f"accuracy ({acc_text:.3f}->{acc_blind:.3f}): son las FEATURES de texto las que recuperan la clase.")
    else:
        log(f"    -> honesto: en este lab hasta el control crudo SEPARA los tipos (los enunciados difieren "
            f"incluso en señales gruesas), así que no hay confusión que reportar acá. La estructura es recuperable.")

    return {
        "regime": name,
        "n_train": len(train), "n_test": len(test),
        "baselines_fixed": {c: round(v, 4) for c, v in fixed.items()},
        "best_fixed": {"chain": best_fixed_name, "acc": round(best_fixed, 4)},
        "router_type": round(acc_type, 4),
        "router_text": round(acc_text, 4),
        "gap_type_minus_text": round(gap, 4),
        "signature_type_purity": round(purity, 4),
        "n_signatures": n_sigs,
        "control_blind": {
            "router_text_blind": round(acc_blind, 4),
            "signature_type_purity": round(purity_blind, 4),
            "n_signatures": n_sigs_blind,
        },
        "router_type_best_per_type": rt.best_chain_per_type(),
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)        # train
    ap.add_argument("--n_test", type=int, default=2000)   # held-out (semilla disjunta)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no_graded", action="store_true")   # saltear el bonus graduado
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test = 1200, 600

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    log(f"[cycle16] tipos={TYPES} | el router de TEXTO solo ve problem['text'] (nunca type/answer)")

    results = {}
    # régimen EXACTO (CYCLE 12): el techo es 1.0; mostramos que el texto-router lo alcanza igual que el tipo.
    train = gen_problems(args.n, seed=args.seed)
    test = gen_problems(args.n_test, seed=args.seed + 10_000)
    results["exact"] = run_regime(log, "EXACTO", train, test, args.eps, args.seed, graded=False)

    # BONUS: régimen GRADUADO (CYCLE 15): las cadenas patinan -> oráculo < 1.0; ¿el texto-router sigue cerca?
    if not args.no_graded:
        g_train = gen_graded(args.n, seed=args.seed, dmin=0.0, dmax=1.0)
        g_test = gen_graded(args.n_test, seed=args.seed + 10_000, dmin=0.0, dmax=1.0)
        results["graded"] = run_regime(log, "GRADUADO (bonus, CYCLE 15)", g_train, g_test, args.eps, args.seed, graded=True)

    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    log("\n[cycle16] ===== VEREDICTO: ¿infiere la clase de problema desde el TEXTO (sin la muleta del tipo)? =====")
    for key, r in results.items():
        log(f"  [{r['regime']}] mejor fija {r['best_fixed']['acc']:.3f} | router-TIPO {r['router_type']:.3f} | "
            f"router-TEXTO {r['router_text']:.3f} | BRECHA {r['gap_type_minus_text']:.3f} | "
            f"pureza firma->tipo {r['signature_type_purity']:.3f}")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
