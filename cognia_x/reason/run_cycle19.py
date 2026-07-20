"""
CYCLE 19 — el char-LM ENTRENADO de verdad como ENCODER del router (primera vez que el pilar toca el modelo).

CYCLE 16 ruteo desde texto con una firma de KEYWORDS (almuerzo gratis: cada tipo sintetico tenia vocabulario
unico). CYCLE 17 mostro que bajo PARAFRASIS + ambiguedad las keywords CONFUNDEN tipos, y un router Naive-Bayes
de bag-of-words degrada mas suave. Caveat de pie de pagina de TODO el pilar: features hechas a mano / sinteticas.
La frontera: usar un ENCODER APRENDIDO real. CYCLE 19 lo ataca: usa el char-LM de CYCLE 7 (6.3M params,
entrenado sobre LIBROS en/es — dominio AJENO a estos problemas de cuentas) como encoder del enunciado.

Sobre HELD-OUT parafraseado (semillas disjuntas), a un par de niveles de ambiguedad, tabulamos accuracy +
pureza clase->tipo de 5 brazos:
  FIJA.       mejor cadena fija (baseline naive, no rutea).
  A. keyword  router de keywords FRAGIL (CYCLE 16/17).
  B. NB       router Naive-Bayes bag-of-words (CYCLE 17).
  C. LM       router de embeddings del char-LM REAL (CYCLE 19) — nearest-class-mean sobre lm_embed.
  CEILING.    router de TIPO (le dan la etiqueta verdadera).

Titular: ¿la representacion del char-LM REAL separa los tipos mejor que keywords bajo parafrasis — C es
competitivo o mejor que B, y mas cerca del ceiling? HONESTO: el modelo es chico y fuera-de-dominio; si sus
features NO separan bien, lo reportamos con numeros (es en si un hallazgo sobre un LM diminuto off-domain).

Usa torch (carga el char-LM). CPU-only, threads=3. Cada problema necesita un FORWARD del LM -> mas lento que
CYCLE 17; por eso los conteos son menores y --smoke usa muy pocos.
Uso: python -m cognia_x.reason.run_cycle19 [--n N] [--n_test M] [--smoke]
"""
import argparse
import json
import os
import sys

import torch

from cognia_x.reason.problems import gen_paraphrased, is_correct
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.router import Router
from cognia_x.reason.text_router import TextRouter, RobustTextRouter, signature_keywords
from cognia_x.reason.lm_router import LMRouter, load_charlm, train_tiny_charlm_fallback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle19")

# un par de niveles de ambiguedad (el LM forward es lento -> menos niveles que CYCLE 17).
AMBIGUITY_LEVELS = [0.0, 0.5, 1.0]


def acc_fixed(chain_name, problems):
    """Accuracy de SIEMPRE usar la misma cadena (no rutea)."""
    return sum(1 for p in problems if is_correct(p, CHAINS[chain_name](p)[0])) / len(problems)


def eval_type_router(router, problems):
    """Accuracy del router de TIPO (le pasamos problem['type'], el CEILING)."""
    router.explore = False
    ok = sum(1 for p in problems if is_correct(p, CHAINS[router.select(p["type"])](p)[0]))
    router.explore = True
    return ok / len(problems)


def acc_random_chain(problems, seed=0):
    """BASELINE de control: elige una cadena AL AZAR por problema (no aprende nada). Piso honesto contra
    el que comparamos el router-LM si sus features fueran demasiado debiles."""
    from random import Random
    rng = Random(seed)
    names = list(CHAINS)
    return sum(1 for p in problems if is_correct(p, CHAINS[rng.choice(names)](p)[0])) / len(problems)


def run_ambiguity(log, model, ambiguity, n_train, n_test, eps, seed):
    """Corre los 5 brazos en un nivel de ambiguedad (held-out parafraseado, semillas disjuntas)."""
    train = gen_paraphrased(n_train, seed=seed, ambiguity=ambiguity)
    test = gen_paraphrased(n_test, seed=seed + 10_000, ambiguity=ambiguity)

    # FIJA: mejor cadena fija (baseline naive)
    fixed = {c: acc_fixed(c, test) for c in CHAINS}
    best_fixed_name = max(fixed, key=fixed.get)
    best_fixed = fixed[best_fixed_name]
    rand = acc_random_chain(test, seed=seed)

    # CEILING: router de TIPO
    rt = Router(list(CHAINS), mode="verifier", eps=eps, seed=seed)
    for p in train:
        rt.train_one(p)
    acc_type = eval_type_router(rt, test)

    # A: keyword FRAGIL (CYCLE 16/17)
    ra = TextRouter(list(CHAINS), eps=eps, seed=seed, sig_fn=signature_keywords)
    for p in train:
        ra.train_one(p)
    acc_kw = ra.eval(test)
    purity_kw, n_sigs_kw, _ = ra.signature_to_type_purity(test)

    # B: Naive-Bayes bag-of-words (CYCLE 17)
    rb = RobustTextRouter(list(CHAINS), eps=eps, seed=seed)
    for p in train:
        rb.train_one(p)
    acc_nb = rb.eval(test)

    # C: LM-embedding router (CYCLE 19) — el char-LM REAL como encoder
    rc = LMRouter(model, list(CHAINS), eps=eps, seed=seed)
    rc.fit_whiten(train)        # fija el espacio de whitening sobre el train antes de rutear
    for p in train:
        rc.train_one(p)
    acc_lm = rc.eval(test)
    purity_lm, n_cls_lm, _ = rc.class_to_type_purity(test)

    gap_kw = acc_type - acc_kw
    gap_nb = acc_type - acc_nb
    gap_lm = acc_type - acc_lm

    log(f"\n[cycle19] ===== AMBIGUEDAD {ambiguity:.2f} (held-out parafraseado, train={len(train)} test={len(test)}) =====")
    log(f"    mejor cadena FIJA ({best_fixed_name})   {best_fixed:.3f}   <- baseline naive (no rutea); azar={rand:.3f}")
    log(f"    A. keyword fragil (CYCLE 16)   {acc_kw:.3f}  (brecha ceiling {gap_kw:.3f}, pureza firma->tipo {purity_kw:.3f}, {n_sigs_kw} firmas)")
    log(f"    B. Naive-Bayes BoW (CYCLE 17)  {acc_nb:.3f}  (brecha ceiling {gap_nb:.3f})")
    log(f"    C. LM-embedding   (CYCLE 19)   {acc_lm:.3f}  (brecha ceiling {gap_lm:.3f}, pureza clase->tipo {purity_lm:.3f}, {n_cls_lm} clases)")
    log(f"    CEILING router de TIPO          {acc_type:.3f}   <- cota superior")

    return {
        "ambiguity": ambiguity, "n_train": len(train), "n_test": len(test),
        "best_fixed": {"chain": best_fixed_name, "acc": round(best_fixed, 4)},
        "acc_random_chain": round(rand, 4),
        "acc_keyword_brittle": round(acc_kw, 4),
        "acc_nb": round(acc_nb, 4),
        "acc_lm": round(acc_lm, 4),
        "acc_type_ceiling": round(acc_type, 4),
        "gap_keyword_to_ceiling": round(gap_kw, 4),
        "gap_nb_to_ceiling": round(gap_nb, 4),
        "gap_lm_to_ceiling": round(gap_lm, 4),
        "purity_keyword": round(purity_kw, 4), "n_signatures_keyword": n_sigs_kw,
        "purity_lm": round(purity_lm, 4), "n_classes_lm": n_cls_lm,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    torch.set_num_threads(3)
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200)        # train por nivel (cada problema = 1 forward LM)
    ap.add_argument("--n_test", type=int, default=600)    # held-out (semilla disjunta)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test = 120, 80

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    log("[cycle19] char-LM REAL (CYCLE 7) como ENCODER del router | A=keyword B=NaiveBayes C=LM-embedding "
        "ceiling=router-de-tipo | A/B/C rutean SOLO desde problem['text']")

    # cargar el char-LM de CYCLE 7; si falla, fallback honesto (LM diminuto in-script, declarado).
    used_fallback = False
    try:
        model, cfg = load_charlm()
        log(f"[cycle19] char-LM CYCLE 7 cargado: d={cfg.d_model} layers={cfg.n_layers} params={model.num_params():,}")
    except Exception as e:  # noqa: BLE001
        log(f"[cycle19] checkpoint NO cargo ({e!r}); FALLBACK: entreno char-LM diminuto in-script (NO es CYCLE 7).")
        model, cfg = train_tiny_charlm_fallback(log=log, steps=80 if args.smoke else 400)
        used_fallback = True

    levels = []
    for amb in AMBIGUITY_LEVELS:
        levels.append(run_ambiguity(log, model, amb, args.n, args.n_test, args.eps, args.seed))

    results = {"levels": levels, "ambiguity_levels": AMBIGUITY_LEVELS,
               "used_fallback": used_fallback, "embed_dim": 2 * cfg.d_model,
               "lm_params": model.num_params()}
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # RESUMEN: tabla 5 brazos vs ambiguedad.
    log("\n[cycle19] ===== RESUMEN: accuracy HELD-OUT vs AMBIGUEDAD (5 brazos) =====")
    if used_fallback:
        log("  (!) FALLBACK en uso: el char-LM es el diminuto in-script, NO el de CYCLE 7.")
    log("  ambig | FIJA  | A:kw  | B:NB  | C:LM  | CEIL  | purA  | purC  | C->ceil")
    for r in levels:
        log(f"  {r['ambiguity']:.2f}  | {r['best_fixed']['acc']:.3f} | {r['acc_keyword_brittle']:.3f} | "
            f"{r['acc_nb']:.3f} | {r['acc_lm']:.3f} | {r['acc_type_ceiling']:.3f} | "
            f"{r['purity_keyword']:.3f} | {r['purity_lm']:.3f} |  {r['gap_lm_to_ceiling']:.3f}")

    # VEREDICTO honesto: C vs B/A y vs ceiling al subir la ambiguedad.
    last = levels[-1]
    log("\n[cycle19] ===== VEREDICTO =====")
    log(f"  ambig max ({last['ambiguity']:.2f}): C(LM)={last['acc_lm']:.3f} vs B(NB)={last['acc_nb']:.3f} "
        f"vs A(kw)={last['acc_keyword_brittle']:.3f} | ceiling={last['acc_type_ceiling']:.3f} | "
        f"FIJA={last['best_fixed']['acc']:.3f} | azar={last['acc_random_chain']:.3f}")
    log(f"  pureza clase->tipo del LM: " +
        " -> ".join(f"{r['purity_lm']:.3f}(amb{r['ambiguity']:.2f})" for r in levels))
    c_vs_b = sum(1 for r in levels if r["acc_lm"] >= r["acc_nb"] - 1e-9)
    c_vs_kw = sum(1 for r in levels if r["acc_lm"] >= r["acc_keyword_brittle"] - 1e-9)
    c_beats_fixed = sum(1 for r in levels if r["acc_lm"] > r["best_fixed"]["acc"] + 1e-9)
    log(f"  C(LM) iguala/supera a B(NB) en {c_vs_b}/{len(levels)} niveles; a A(kw) en {c_vs_kw}/{len(levels)}; "
        f"supera a la mejor FIJA en {c_beats_fixed}/{len(levels)}.")
    avg_pur_lm = sum(r["purity_lm"] for r in levels) / len(levels)
    avg_pur_kw = sum(r["purity_keyword"] for r in levels) / len(levels)
    if avg_pur_lm >= avg_pur_kw:
        log(f"  -> la representacion del char-LM separa los tipos IGUAL O MEJOR que keywords "
            f"(pureza media LM {avg_pur_lm:.3f} >= keyword {avg_pur_kw:.3f}).")
    else:
        log(f"  -> HONESTO: la representacion del char-LM (off-domain, libros) separa los tipos PEOR que "
            f"keywords (pureza media LM {avg_pur_lm:.3f} < keyword {avg_pur_kw:.3f}). Hallazgo real sobre un LM chico ajeno.")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
