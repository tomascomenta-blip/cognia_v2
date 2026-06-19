"""
CYCLE 17 — rutear desde el TEXTO cuando el texto es DURO: paráfrasis + vocabulario ambiguo.

CYCLE 16 ruteaba desde el texto pero llegó a una brecha PERFECTA (pureza firma->tipo 1.000) porque cada
tipo sintético usaba su PROPIO vocabulario único: hasta un control crudo separaba los tipos. El caveat
honesto: demostró el MECANISMO, no la ROBUSTEZ a paráfrasis / redacción ambigua. CYCLE 17 retira ese
caveat haciendo el ruteo desde texto genuinamente DURO y mostrando QUÉ sobrevive.

Sobre HELD-OUT parafraseado (semillas disjuntas), bajo AMBIGÜEDAD creciente, comparamos 4 brazos que
rutean (cuando rutean) SOLO desde el TEXTO (jamás el tipo/answer):
  A. router de KEYWORDS FRÁGIL  = el TextRouter de CYCLE 16 (firma discreta de keywords). Debe CONFUNDIR
     tipos cuando sube la ambigüedad -> pureza firma->tipo CAE < 1.0 y la accuracy baja (prueba que
     CYCLE 16 tenía almuerzo gratis: vocabulario único por tipo).
  B. router de TEXTO ROBUSTO    = RobustTextRouter de CYCLE 17 (perceptrón promediado sobre bag-of-words,
     aprendido online con el verificador real). Debe DEGRADAR SUAVE y GANARLE a A al subir la ambigüedad.
  CEILING. router de TIPO       = le DAN la etiqueta verdadera (cota superior). Reportamos la brecha de A y B.
  FIJA.    mejor cadena fija     = baseline naïve (no rutea).

Titular: tabla accuracy vs ambigüedad para {mejor fija, keyword-frágil (A), texto-robusto (B), tipo (ceiling)}.
B debería SEGUIR al ceiling mucho mejor que A al subir la ambigüedad. Si bajo ambigüedad alta hasta B
sufre, se REPORTA honesto (degradación gradual con brecha honesta es exactamente el objetivo).

torch NO hace falta (loop meta-razonador sobre solvers; solo stdlib).
Uso: python -m cognia_x.reason.run_cycle17 [--n N] [--n_test M] [--smoke]
"""
import argparse
import json
import os
import sys

from cognia_x.reason.problems import gen_paraphrased, is_correct
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.router import Router
from cognia_x.reason.text_router import TextRouter, RobustTextRouter, signature_keywords

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle17")

# niveles de ambigüedad a barrer (0 = enunciados limpios; 1 = máximo solapamiento + distractores).
AMBIGUITY_LEVELS = [0.0, 0.25, 0.5, 0.75, 1.0]


def acc_fixed(chain_name, problems):
    """Accuracy de SIEMPRE usar la misma cadena (no rutea)."""
    return sum(1 for p in problems if is_correct(p, CHAINS[chain_name](p)[0])) / len(problems)


def eval_type_router(router, problems):
    """Accuracy del router de TIPO (le pasamos problem['type'], el CEILING): despliega la mejor por tipo."""
    router.explore = False
    ok = sum(1 for p in problems if is_correct(p, CHAINS[router.select(p["type"])](p)[0]))
    router.explore = True
    return ok / len(problems)


def run_ambiguity(log, ambiguity, n_train, n_test, eps, seed):
    """Corre los 4 brazos en un nivel de ambigüedad y devuelve el dict de resultados (held-out parafraseado)."""
    # train y test con SEMILLAS DISJUNTAS (held-out de verdad), misma ambigüedad.
    train = gen_paraphrased(n_train, seed=seed, ambiguity=ambiguity)
    test = gen_paraphrased(n_test, seed=seed + 10_000, ambiguity=ambiguity)

    # FIJA: mejor cadena fija (baseline naïve)
    fixed = {c: acc_fixed(c, test) for c in CHAINS}
    best_fixed_name = max(fixed, key=fixed.get)
    best_fixed = fixed[best_fixed_name]

    # CEILING: router de TIPO (le DAN la etiqueta verdadera)
    rt = Router(list(CHAINS), mode="verifier", eps=eps, seed=seed)
    for p in train:
        rt.train_one(p)
    acc_type = eval_type_router(rt, test)

    # A: router de KEYWORDS FRÁGIL = el bandit-por-firma de CYCLE 16 indexado por la firma de KEYWORDS pura
    #    (signature_keywords: solo flags de palabras clave, sin los buckets numéricos que igual separan los
    #    tipos). Esta es la representación que la paráfrasis + vocabulario ambiguo ATACAN.
    ra = TextRouter(list(CHAINS), eps=eps, seed=seed, sig_fn=signature_keywords)
    for p in train:
        ra.train_one(p)
    acc_kw = ra.eval(test)
    purity_kw, n_sigs_kw, per_sig = ra.signature_to_type_purity(test)

    # B: router de TEXTO ROBUSTO (CYCLE 17, perceptrón promediado sobre bag-of-words)
    rb = RobustTextRouter(list(CHAINS), eps=eps, seed=seed)
    for p in train:
        rb.train_one(p)
    acc_rb = rb.eval(test)

    gap_kw = acc_type - acc_kw        # brecha de A al ceiling
    gap_rb = acc_type - acc_rb        # brecha de B al ceiling

    log(f"\n[cycle17] ===== AMBIGÜEDAD {ambiguity:.2f} (held-out parafraseado, train={len(train)} test={len(test)}) =====")
    log(f"    mejor cadena FIJA ({best_fixed_name})         {best_fixed:.3f}   <- baseline naïve (no rutea)")
    log(f"    A. router KEYWORDS frágil (CYCLE 16)   {acc_kw:.3f}   (brecha al ceiling {gap_kw:.3f})")
    log(f"    B. router TEXTO robusto  (CYCLE 17)    {acc_rb:.3f}   (brecha al ceiling {gap_rb:.3f})")
    log(f"    CEILING router de TIPO (le DAN el tipo){acc_type:.3f}   <- cota superior")
    log(f"    pureza firma->tipo de A (keywords): {purity_kw:.3f} con {n_sigs_kw} firmas inferidas "
        f"({'CONFUNDE tipos' if purity_kw < 0.999 else 'sin confusión'})")
    if acc_rb > acc_kw + 1e-9:
        log(f"    -> B le GANA a A por {acc_rb - acc_kw:.3f} en este nivel.")
    elif acc_rb < acc_kw - 1e-9:
        log(f"    -> honesto: A le gana a B por {acc_kw - acc_rb:.3f} acá.")
    else:
        log(f"    -> empate entre A y B acá.")

    return {
        "ambiguity": ambiguity,
        "n_train": len(train), "n_test": len(test),
        "best_fixed": {"chain": best_fixed_name, "acc": round(best_fixed, 4)},
        "acc_keyword_brittle": round(acc_kw, 4),
        "acc_text_robust": round(acc_rb, 4),
        "acc_type_ceiling": round(acc_type, 4),
        "gap_keyword_to_ceiling": round(gap_kw, 4),
        "gap_robust_to_ceiling": round(gap_rb, 4),
        "signature_type_purity_keyword": round(purity_kw, 4),
        "n_signatures_keyword": n_sigs_kw,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)        # train por nivel
    ap.add_argument("--n_test", type=int, default=2000)   # held-out (semilla disjunta)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test = 1200, 600

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    log("[cycle17] paráfrasis + vocabulario ambiguo | A=keyword-frágil(CYCLE16) B=texto-robusto(CYCLE17) "
        "ceiling=router-de-tipo | A y B rutean SOLO desde problem['text']")

    levels = []
    for amb in AMBIGUITY_LEVELS:
        levels.append(run_ambiguity(log, amb, args.n, args.n_test, args.eps, args.seed))

    results = {"levels": levels, "ambiguity_levels": AMBIGUITY_LEVELS}
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # RESUMEN: tabla accuracy vs ambigüedad para los 4 brazos.
    log("\n[cycle17] ===== RESUMEN: accuracy HELD-OUT vs AMBIGÜEDAD (4 brazos) =====")
    log("  ambig | FIJA  | A:keyword | B:robusto | CEILING(tipo) | pureza-A | A->ceil | B->ceil")
    for r in levels:
        log(f"  {r['ambiguity']:.2f}  | {r['best_fixed']['acc']:.3f} |   {r['acc_keyword_brittle']:.3f}   |"
            f"   {r['acc_text_robust']:.3f}   |     {r['acc_type_ceiling']:.3f}     |  {r['signature_type_purity_keyword']:.3f}   |"
            f"  {r['gap_keyword_to_ceiling']:.3f}  |  {r['gap_robust_to_ceiling']:.3f}")

    # VEREDICTO honesto: ¿degrada A y aguanta B mejor?
    a0, a1 = levels[0]["acc_keyword_brittle"], levels[-1]["acc_keyword_brittle"]
    b0, b1 = levels[0]["acc_text_robust"], levels[-1]["acc_text_robust"]
    pur0, pur1 = levels[0]["signature_type_purity_keyword"], levels[-1]["signature_type_purity_keyword"]
    log("\n[cycle17] ===== VEREDICTO =====")
    log(f"  A (keyword frágil): pureza firma->tipo {pur0:.3f} (amb 0) -> {pur1:.3f} (amb {AMBIGUITY_LEVELS[-1]:.2f}); "
        f"accuracy {a0:.3f} -> {a1:.3f}")
    log(f"  B (texto robusto):  accuracy {b0:.3f} (amb 0) -> {b1:.3f} (amb {AMBIGUITY_LEVELS[-1]:.2f})")
    if pur1 < 0.999:
        log(f"  -> CONFIRMADO: al subir la ambigüedad las KEYWORDS confunden tipos (pureza {pur0:.3f}->{pur1:.3f}); "
            f"el almuerzo gratis de CYCLE 16 desaparece.")
    else:
        log(f"  -> honesto: la firma de keywords NO se confundió ni con ambigüedad máxima en este lab.")
    wins = sum(1 for r in levels if r["acc_text_robust"] > r["acc_keyword_brittle"] + 1e-9)
    log(f"  -> B le gana (o iguala) a A en {wins}/{len(levels)} niveles; "
        f"brecha de B al ceiling en ambig máx = {levels[-1]['gap_robust_to_ceiling']:.3f} (menor = mejor).")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
