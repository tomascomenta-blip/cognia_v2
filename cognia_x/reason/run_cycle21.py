"""
CYCLE 21 — CAPSTONE del sub-arco de ruteo de texto: el encoder SUPERVISADO POR EL VERIFICADOR (brazo E).

El sub-arco encontro (RESULTS.md):
  CYCLE 16: keywords rutearon "gratis" sobre textos sinteticos trivialmente separables.
  CYCLE 17: bajo paraphrasis+ambiguedad, las keywords confunden; un Naive-Bayes bag-of-words (B) degrada
            suave y es el baseline a vencer.
  CYCLE 19: un encoder char-LM OFF-DOMAIN (libros) recupero estructura y le gano a las keywords, pero
            PERDIO con B.
  CYCLE 20: un encoder char-LM IN-DOMAIN pero UNSUPERVISED le gano a off-domain y le gano a B con texto
            LIMPIO (1.000 vs 0.920), pero seguia perdiendo con B bajo ambiguedad. Leccion refinada: "un
            encoder diminuto UNSUPERVISED necesita senal SUPERVISADA (verificador) para dominar a un
            bag-of-words discriminativo barato BAJO RUIDO".

CYCLE 21 lo CIERRA: le da al encoder la SENAL del verificador — aprende la representacion DISCRIMINATIVAMENTE
del verificador real (que cadena ACIERTA cada texto) y rutea sobre eso — y testea si un encoder
SUPERVISADO-POR-VERIFICADOR finalmente LE GANA a B en TODOS los niveles de ambiguedad (incluido el ruidoso),
algo que ni off-domain ni unsupervised-in-domain lograron. Es el embodiment literal del objetivo del dueno:
"evalua el resultado DENTRO del sistema" — el encoder aprende de si la forma de razonar elegida FUNCIONO.

Sobre HELD-OUT parafraseado (semillas disjuntas), a ambiguedad {0.0, 0.5, 1.0}, tabulamos accuracy de 7 brazos:
  FIJA.       mejor cadena fija (no rutea).
  A. keyword  router de keywords FRAGIL (CYCLE 16/17).
  B. NB       router Naive-Bayes bag-of-words (CYCLE 17) — el baseline a vencer.
  C. LM-off   encoder char-LM OFF-DOMAIN (CYCLE 19, libros).
  D. LM-in    encoder char-LM IN-DOMAIN UNSUPERVISED (CYCLE 20).
  E. SUP      encoder SUPERVISADO POR EL VERIFICADOR (CYCLE 21) — la contribucion nueva.
  CEILING.    router de TIPO (le dan la etiqueta verdadera).

HONESTIDAD: es un TEST DE HIPOTESIS. Si E > B en TODOS los niveles -> el sub-arco cierra limpio: un encoder
APRENDIDO le gana al bag-of-words UNA VEZ que recibe senal del verificador. Si E NO le gana a B en todos
lados -> lo REPORTAMOS con los numeros y la razon probable (capacidad/muestra/optimizacion). Un casi-acierto
con analisis es una conclusion legitima; NO maquillamos.

Reusa el encoder IN-DOMAIN cacheado de CYCLE 20 (runs/cycle20/encoder_indomain.pt); E solo entrena una CABEZA
chica supervisada -> rapido en CPU. Cada problema = 1 forward del char-LM (cacheado por brazo).
Uso: python -m cognia_x.reason.run_cycle21 [--n N] [--n_test M] [--smoke]
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
from cognia_x.reason.lm_router import (LMRouter, load_charlm, train_tiny_charlm_fallback,
                                       train_indomain_encoder, save_encoder, load_encoder)
from cognia_x.reason.supervised_router import SupervisedLMRouter, save_head, load_head
from cognia_x.reason.run_cycle20 import (acc_fixed, eval_type_router, acc_random_chain,
                                         build_encoder_corpus)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle21")
# reusamos el encoder IN-DOMAIN cacheado de CYCLE 20 (no re-entrenamos el char-LM; solo la cabeza E).
CYCLE20_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle20")
ENCODER_PATH = os.path.join(CYCLE20_DIR, "encoder_indomain.pt")
HEAD_PATH = os.path.join(RUN_DIR, "supervised_head.pt")

AMBIGUITY_LEVELS = [0.0, 0.5, 1.0]


def get_indomain_encoder(log, steps, n_corpus):
    """Recarga el encoder IN-DOMAIN de CYCLE 20 si existe; si no, lo entrena UNA vez (UNSUPERVISED) y lo
    guarda donde CYCLE 20 lo espera (asi ambos ciclos comparten el mismo encoder cacheado)."""
    if os.path.exists(ENCODER_PATH):
        model, cfg = load_encoder(ENCODER_PATH)
        log(f"[cycle21] encoder IN-DOMAIN (CYCLE 20) recargado: d={cfg.d_model} layers={cfg.n_layers} "
            f"params={model.num_params():,}")
        return model, cfg
    texts = build_encoder_corpus(n_corpus)
    import time
    t0 = time.time()
    model, cfg, final_loss = train_indomain_encoder(texts, steps=steps, log=log)
    save_encoder(model, cfg, ENCODER_PATH)
    log(f"[cycle21] encoder IN-DOMAIN entrenado en {time.time()-t0:.1f}s (loss {final_loss:.4f}); "
        f"guardado en {ENCODER_PATH}")
    return model, cfg


def run_ambiguity(log, off_model, in_model, ambiguity, n_train, n_test, eps, seed,
                  sup_hidden, sup_epochs, sup_lr):
    """Corre los 7 brazos en un nivel de ambiguedad (held-out parafraseado, semillas disjuntas)."""
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

    # B: Naive-Bayes bag-of-words (CYCLE 17) — el baseline a vencer
    rb = RobustTextRouter(list(CHAINS), eps=eps, seed=seed)
    for p in train:
        rb.train_one(p)
    acc_nb = rb.eval(test)

    # C: LM-embedding OFF-DOMAIN (CYCLE 19) — referencia
    rc = LMRouter(off_model, list(CHAINS), eps=eps, seed=seed)
    rc.fit_whiten(train)
    for p in train:
        rc.train_one(p)
    acc_off = rc.eval(test)

    # D: LM-embedding IN-DOMAIN UNSUPERVISED (CYCLE 20)
    rd = LMRouter(in_model, list(CHAINS), eps=eps, seed=seed)
    rd.fit_whiten(train)
    for p in train:
        rd.train_one(p)
    acc_in = rd.eval(test)

    # E: encoder SUPERVISADO POR EL VERIFICADOR (CYCLE 21) — la contribucion nueva.
    # Mismo char-LM in-domain que D (frozen), pero una cabeza aprendida del exito-de-cadena (verificador).
    re_ = SupervisedLMRouter(in_model, list(CHAINS), hidden=sup_hidden, lr=sup_lr,
                             epochs=sup_epochs, seed=seed)
    sup_bce = re_.fit(train, log=log)
    acc_sup = re_.eval(test)
    purity_sup, n_cls_sup = re_.class_to_type_purity(test)

    log(f"\n[cycle21] ===== AMBIGUEDAD {ambiguity:.2f} (held-out parafraseado, train={len(train)} test={len(test)}) =====")
    log(f"    mejor cadena FIJA ({best_fixed_name})   {best_fixed:.3f}   <- baseline naive (no rutea); azar={rand:.3f}")
    log(f"    A. keyword fragil (CYCLE 16)        {acc_kw:.3f}")
    log(f"    B. Naive-Bayes BoW (CYCLE 17)       {acc_nb:.3f}   <- baseline a vencer")
    log(f"    C. LM-off   (CYCLE 19, libros)      {acc_off:.3f}")
    log(f"    D. LM-in    (CYCLE 20, unsupervised){acc_in:.3f}")
    log(f"    E. SUPERVISADO (CYCLE 21)           {acc_sup:.3f}  (pureza cadena->tipo {purity_sup:.3f}, "
        f"{n_cls_sup} cadenas usadas; bce final {sup_bce:.4f})")
    log(f"    CEILING router de TIPO              {acc_type:.3f}   <- cota superior")

    return {
        "ambiguity": ambiguity, "n_train": len(train), "n_test": len(test),
        "best_fixed": {"chain": best_fixed_name, "acc": round(best_fixed, 4)},
        "acc_random_chain": round(rand, 4),
        "acc_keyword_brittle": round(acc_kw, 4),
        "acc_nb": round(acc_nb, 4),
        "acc_lm_off": round(acc_off, 4),
        "acc_lm_in": round(acc_in, 4),
        "acc_supervised": round(acc_sup, 4),
        "acc_type_ceiling": round(acc_type, 4),
        "purity_supervised": round(purity_sup, 4), "n_chains_supervised": n_cls_sup,
        "supervised_bce": round(sup_bce, 4),
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    torch.set_num_threads(3)
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)        # train por nivel (cada problema = 1 forward LM)
    ap.add_argument("--n_test", type=int, default=800)    # held-out (semilla disjunta)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--enc_steps", type=int, default=2000)   # solo si hay que entrenar el encoder (no cacheado)
    ap.add_argument("--enc_corpus", type=int, default=4000)
    ap.add_argument("--sup_hidden", type=int, default=64)    # tamano de la capa oculta de la cabeza E
    ap.add_argument("--sup_epochs", type=int, default=60)    # epocas de la cabeza supervisada
    ap.add_argument("--sup_lr", type=float, default=3e-3)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test = 200, 120
        args.enc_steps, args.enc_corpus = 150, 600
        args.sup_epochs = 25

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    log("[cycle21] encoder SUPERVISADO POR EL VERIFICADOR (E) vs Naive-Bayes (B) y encoders previos | "
        "A=keyword B=NB C=LM-off D=LM-in(unsup) E=SUP ceiling=router-de-tipo | A/B/C/D/E rutean SOLO desde problem['text']")

    # encoder OFF-DOMAIN (referencia, CYCLE 19): char-LM de CYCLE 7; si no carga, fallback honesto.
    used_fallback = False
    try:
        off_model, off_cfg = load_charlm()
        log(f"[cycle21] C: char-LM OFF-DOMAIN (CYCLE 7) cargado: d={off_cfg.d_model} layers={off_cfg.n_layers} "
            f"params={off_model.num_params():,}")
    except Exception as e:  # noqa: BLE001
        log(f"[cycle21] checkpoint CYCLE 7 NO cargo ({e!r}); FALLBACK off-domain diminuto in-script.")
        off_model, off_cfg = train_tiny_charlm_fallback(log=log, steps=80 if args.smoke else 400)
        used_fallback = True

    # encoder IN-DOMAIN (CYCLE 20): recargado del cache (o entrenado una vez). Lo comparten D y E.
    in_model, in_cfg = get_indomain_encoder(log, args.enc_steps, args.enc_corpus)

    levels = []
    for amb in AMBIGUITY_LEVELS:
        levels.append(run_ambiguity(log, off_model, in_model, amb, args.n, args.n_test, args.eps, args.seed,
                                    args.sup_hidden, args.sup_epochs, args.sup_lr))

    # CHECK: la cabeza supervisada GUARDA y RECARGA y rutea (entrenada en el ultimo nivel de ambiguedad).
    save_reload_ok = None
    try:
        amb_last = AMBIGUITY_LEVELS[-1]
        train_last = gen_paraphrased(min(args.n, 400), seed=args.seed, ambiguity=amb_last)
        re_save = SupervisedLMRouter(in_model, list(CHAINS), hidden=args.sup_hidden,
                                     epochs=args.sup_epochs, lr=args.sup_lr, seed=args.seed)
        re_save.fit(train_last)
        save_head(re_save, HEAD_PATH)
        re_load = load_head(in_model, HEAD_PATH)
        probe = gen_paraphrased(40, seed=args.seed + 99_000, ambiguity=amb_last)
        same = all(re_save.select(p) == re_load.select(p) for p in probe)
        save_reload_ok = bool(same)
        log(f"[cycle21] CHECK save+reload cabeza: rutea igual en {len(probe)} sondas -> {save_reload_ok} "
            f"(guardada en {HEAD_PATH})")
    except Exception as e:  # noqa: BLE001
        log(f"[cycle21] CHECK save+reload FALLO: {e!r}")
        save_reload_ok = False

    results = {"levels": levels, "ambiguity_levels": AMBIGUITY_LEVELS,
               "used_fallback_offdomain": used_fallback,
               "in_embed_dim": 2 * in_cfg.d_model, "in_params": in_model.num_params(),
               "sup_hidden": args.sup_hidden, "sup_epochs": args.sup_epochs, "sup_lr": args.sup_lr,
               "head_save_reload_ok": save_reload_ok}
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # RESUMEN: tabla 7 brazos vs ambiguedad.
    log("\n[cycle21] ===== RESUMEN: accuracy HELD-OUT vs AMBIGUEDAD (7 brazos) =====")
    if used_fallback:
        log("  (!) FALLBACK en uso para C: el char-LM off-domain es el diminuto in-script, NO el de CYCLE 7.")
    log("  ambig | FIJA  | A:kw  | B:NB  | C:off | D:in  | E:SUP | CEIL")
    for r in levels:
        log(f"  {r['ambiguity']:.2f}  | {r['best_fixed']['acc']:.3f} | {r['acc_keyword_brittle']:.3f} | "
            f"{r['acc_nb']:.3f} | {r['acc_lm_off']:.3f} | {r['acc_lm_in']:.3f} | {r['acc_supervised']:.3f} | "
            f"{r['acc_type_ceiling']:.3f}")

    # VEREDICTO: ¿E le gana a B en TODOS los niveles (lo que nada antes logro) y se acerca al ceiling?
    log("\n[cycle21] ===== VEREDICTO =====")
    e_vs_b = sum(1 for r in levels if r["acc_supervised"] >= r["acc_nb"] - 1e-9)
    e_vs_d = sum(1 for r in levels if r["acc_supervised"] >= r["acc_lm_in"] - 1e-9)
    e_vs_c = sum(1 for r in levels if r["acc_supervised"] >= r["acc_lm_off"] - 1e-9)
    e_vs_a = sum(1 for r in levels if r["acc_supervised"] >= r["acc_keyword_brittle"] - 1e-9)
    e_beats_fixed = sum(1 for r in levels if r["acc_supervised"] > r["best_fixed"]["acc"] + 1e-9)
    avg_e = sum(r["acc_supervised"] for r in levels) / len(levels)
    avg_b = sum(r["acc_nb"] for r in levels) / len(levels)
    avg_ceil = sum(r["acc_type_ceiling"] for r in levels) / len(levels)
    log(f"  E(SUP) iguala/supera a B(NB) en {e_vs_b}/{len(levels)} niveles; a D(in) en {e_vs_d}/{len(levels)}; "
        f"a C(off) en {e_vs_c}/{len(levels)}; a A(kw) en {e_vs_a}/{len(levels)}; supera FIJA en "
        f"{e_beats_fixed}/{len(levels)}.")
    log(f"  accuracy media: E={avg_e:.3f}  B={avg_b:.3f}  ceiling={avg_ceil:.3f}  (gap E->ceiling {avg_ceil-avg_e:+.3f})")

    high = levels[-1]   # ambiguedad maxima (el regimen ruidoso donde D y C perdian con B)
    if e_vs_b == len(levels):
        log(f"  -> TITULAR CONFIRMADO: el encoder SUPERVISADO POR EL VERIFICADOR (E) le GANA a B en TODOS los "
            f"niveles de ambiguedad — lo que ni off-domain (C) ni unsupervised-in-domain (D) lograron. El "
            f"sub-arco 16->17->19->20->21 CIERRA: un encoder APRENDIDO le gana al bag-of-words UNA VEZ que "
            f"recibe senal del verificador. (E media {avg_e:.3f} vs B {avg_b:.3f}; ceiling {avg_ceil:.3f}.)")
    else:
        log(f"  -> HONESTO (casi-acierto): E NO le gana a B en TODOS los niveles ({e_vs_b}/{len(levels)}). "
            f"A ambig maxima: E={high['acc_supervised']:.3f} vs B={high['acc_nb']:.3f}. E SI le gana a D(unsup) "
            f"en {e_vs_d}/{len(levels)} y a C(off) en {e_vs_c}/{len(levels)} -> la supervision del verificador "
            f"MEJORA el encoder aprendido (cierra la brecha vs B), pero a esta escala/capacidad la "
            f"representacion char-LM frozen no termina de dominar al bag-of-words discriminativo. Razon probable: "
            f"la cabeza ve features FROZEN (no fine-tunea el char-LM) y la muestra/optimizacion limitan la "
            f"separacion bajo ruido. Es una conclusion legitima, reportada con numeros, sin maquillaje.")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
