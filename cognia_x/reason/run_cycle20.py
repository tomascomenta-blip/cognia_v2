"""
CYCLE 20 — entrenar el char-LM ENCODER IN-DOMAIN (sobre los propios enunciados) y testear la leccion de CYCLE 19.

CYCLE 19 uso el char-LM de CYCLE 7 (6.3M, entrenado sobre LIBROS — dominio AJENO) como encoder del router.
Hallazgo: recupero estructura de tipo (pureza 0.61-0.75 >> 0.25 azar) y le GANO a las keywords fragiles,
pero PERDIO con un Naive-Bayes in-domain barato y solo EMPATO a la mejor cadena fija. Leccion honesta que
dejo: "un encoder generico off-domain NO domina features baratas in-domain salvo que este entrenado CERCA
de la tarea".

CYCLE 20 testea esa leccion DE FRENTE: entrena un char-LM CHICO IN-DOMAIN (UNSUPERVISED next-byte sobre el
corpus de enunciados parafraseados — nunca ve el type/answer) y usa SUS embeddings como encoder del MISMO
LMRouter (NCM/whitened, online, premiado por el verificador, lee SOLO problem["text"]). Pregunta: ahora que
el encoder esta entrenado SOBRE el dominio, ¿le gana a keywords (A) y a off-domain (C), y CIERRA o supera la
brecha con Naive-Bayes (B)?

Sobre HELD-OUT parafraseado (semillas disjuntas), a un par de niveles de ambiguedad, tabulamos accuracy +
pureza clase/firma->tipo de 6 brazos:
  FIJA.       mejor cadena fija (baseline naive, no rutea).
  A. keyword  router de keywords FRAGIL (CYCLE 16/17).
  B. NB       router Naive-Bayes bag-of-words (CYCLE 17).
  C. LM-off   embeddings del char-LM de CYCLE 7 (LIBROS, off-domain) — referencia de CYCLE 19.
  D. LM-in    embeddings del char-LM IN-DOMAIN (CYCLE 20) — la contribucion nueva.
  CEILING.    router de TIPO (le dan la etiqueta verdadera).

HONESTIDAD: esto es un TEST DE HIPOTESIS. Si D > B -> la leccion de CYCLE 19 queda CONFIRMADA (entrenar cerca
de la tarea). Si D igual pierde con B -> tambien es un hallazgo real: un char-LM diminuto unsupervised puede
seguir sin ganarle a un bag-of-words discriminativo en 4 tipos. NO maquillamos numeros: armamos un setup
JUSTO y reportamos lo que pase. La pureza C vs D muestra si el entrenamiento in-domain AFILO la estructura
de tipo en la representacion.

Usa torch. CPU-only, threads=3. El encoder in-domain se entrena UNA vez (UNSUPERVISED) y se guarda en
runs/cycle20/ (si ya existe, se recarga). Cada problema = 1 forward del LM -> conteos moderados.
Uso: python -m cognia_x.reason.run_cycle20 [--n N] [--n_test M] [--smoke]
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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle20")
ENCODER_PATH = os.path.join(RUN_DIR, "encoder_indomain.pt")

# un par de niveles de ambiguedad (el LM forward es lento -> pocos niveles).
AMBIGUITY_LEVELS = [0.0, 0.5, 1.0]

# corpus UNSUPERVISED para entrenar el encoder in-domain: enunciados parafraseados a ambiguedad MEDIA,
# semillas DISJUNTAS de train/test de evaluacion (asi el encoder no ve los problemas de evaluacion).
ENCODER_CORPUS_SEED = 77_000


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
    """BASELINE de control: elige una cadena AL AZAR por problema (no aprende nada). Piso honesto."""
    from random import Random
    rng = Random(seed)
    names = list(CHAINS)
    return sum(1 for p in problems if is_correct(p, CHAINS[rng.choice(names)](p)[0])) / len(problems)


def build_encoder_corpus(n_corpus, seed=ENCODER_CORPUS_SEED, ambiguity=0.5):
    """
    Genera el corpus UNSUPERVISED para el encoder in-domain: SOLO los strings de los enunciados.
    AUDITORIA: extrae problem["text"] y DESCARTA el resto del dict -> el encoder no puede ver type/answer.
    Semilla disjunta de train/test de evaluacion.
    """
    probs = gen_paraphrased(n_corpus, seed=seed, ambiguity=ambiguity)
    return [p["text"] for p in probs]          # <- SOLO el texto; type/answer quedan afuera


def get_indomain_encoder(log, steps, n_corpus, force_retrain=False):
    """Entrena (o recarga) el encoder in-domain. Lo guarda en RUN_DIR para reproducibilidad/reuso del test."""
    if os.path.exists(ENCODER_PATH) and not force_retrain:
        model, cfg = load_encoder(ENCODER_PATH)
        log(f"[cycle20] encoder IN-DOMAIN recargado de {ENCODER_PATH}: d={cfg.d_model} layers={cfg.n_layers} "
            f"params={model.num_params():,}")
        return model, cfg, None
    texts = build_encoder_corpus(n_corpus)
    import time
    t0 = time.time()
    model, cfg, final_loss = train_indomain_encoder(texts, steps=steps, log=log)
    dt = time.time() - t0
    save_encoder(model, cfg, ENCODER_PATH)
    log(f"[cycle20] encoder IN-DOMAIN entrenado en {dt:.1f}s (loss final {final_loss:.4f}); guardado en {ENCODER_PATH}")
    # CHECK de cordura: reload + embed + shape.
    rm, rcfg = load_encoder(ENCODER_PATH)
    from cognia_x.reason.lm_router import lm_embed
    emb = lm_embed(rm, texts[0])
    log(f"[cycle20] CHECK reload+embed: shape {tuple(emb.shape)} (esperado {(2*rcfg.d_model,)})")
    return model, cfg, {"final_loss": round(final_loss, 4), "train_seconds": round(dt, 1)}


def run_ambiguity(log, off_model, in_model, ambiguity, n_train, n_test, eps, seed):
    """Corre los 6 brazos en un nivel de ambiguedad (held-out parafraseado, semillas disjuntas)."""
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

    # C: LM-embedding OFF-DOMAIN (CYCLE 19 — char-LM de libros) — referencia
    rc = LMRouter(off_model, list(CHAINS), eps=eps, seed=seed)
    rc.fit_whiten(train)
    for p in train:
        rc.train_one(p)
    acc_off = rc.eval(test)
    purity_off, n_cls_off, _ = rc.class_to_type_purity(test)

    # D: LM-embedding IN-DOMAIN (CYCLE 20 — char-LM entrenado sobre estos textos) — contribucion nueva
    rd = LMRouter(in_model, list(CHAINS), eps=eps, seed=seed)
    rd.fit_whiten(train)
    for p in train:
        rd.train_one(p)
    acc_in = rd.eval(test)
    purity_in, n_cls_in, _ = rd.class_to_type_purity(test)

    log(f"\n[cycle20] ===== AMBIGUEDAD {ambiguity:.2f} (held-out parafraseado, train={len(train)} test={len(test)}) =====")
    log(f"    mejor cadena FIJA ({best_fixed_name})   {best_fixed:.3f}   <- baseline naive (no rutea); azar={rand:.3f}")
    log(f"    A. keyword fragil (CYCLE 16)   {acc_kw:.3f}  (pureza firma->tipo {purity_kw:.3f}, {n_sigs_kw} firmas)")
    log(f"    B. Naive-Bayes BoW (CYCLE 17)  {acc_nb:.3f}")
    log(f"    C. LM-off  (CYCLE 19, libros)  {acc_off:.3f}  (pureza clase->tipo {purity_off:.3f}, {n_cls_off} clases)")
    log(f"    D. LM-in   (CYCLE 20, dominio) {acc_in:.3f}  (pureza clase->tipo {purity_in:.3f}, {n_cls_in} clases)")
    log(f"    CEILING router de TIPO          {acc_type:.3f}   <- cota superior")

    return {
        "ambiguity": ambiguity, "n_train": len(train), "n_test": len(test),
        "best_fixed": {"chain": best_fixed_name, "acc": round(best_fixed, 4)},
        "acc_random_chain": round(rand, 4),
        "acc_keyword_brittle": round(acc_kw, 4),
        "acc_nb": round(acc_nb, 4),
        "acc_lm_off": round(acc_off, 4),
        "acc_lm_in": round(acc_in, 4),
        "acc_type_ceiling": round(acc_type, 4),
        "purity_keyword": round(purity_kw, 4), "n_signatures_keyword": n_sigs_kw,
        "purity_lm_off": round(purity_off, 4), "n_classes_lm_off": n_cls_off,
        "purity_lm_in": round(purity_in, 4), "n_classes_lm_in": n_cls_in,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    torch.set_num_threads(3)
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=800)         # train por nivel (cada problema = 1 forward LM)
    ap.add_argument("--n_test", type=int, default=600)    # held-out (semilla disjunta)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--enc_steps", type=int, default=2000)   # pasos de entrenamiento del encoder in-domain
    ap.add_argument("--enc_corpus", type=int, default=4000)  # nro de enunciados en el corpus del encoder
    ap.add_argument("--retrain_encoder", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.n, args.n_test = 120, 80
        args.enc_steps, args.enc_corpus = 150, 600

    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    log("[cycle20] encoder IN-DOMAIN (next-byte UNSUPERVISED sobre los enunciados) como encoder del router | "
        "A=keyword B=NaiveBayes C=LM-off(libros) D=LM-in(dominio) ceiling=router-de-tipo | A/B/C/D rutean SOLO desde problem['text']")

    # encoder OFF-DOMAIN (referencia, CYCLE 19): char-LM de CYCLE 7; si no carga, fallback honesto.
    used_fallback = False
    try:
        off_model, off_cfg = load_charlm()
        log(f"[cycle20] C: char-LM OFF-DOMAIN (CYCLE 7) cargado: d={off_cfg.d_model} layers={off_cfg.n_layers} "
            f"params={off_model.num_params():,}")
    except Exception as e:  # noqa: BLE001
        log(f"[cycle20] checkpoint CYCLE 7 NO cargo ({e!r}); FALLBACK off-domain diminuto in-script.")
        off_model, off_cfg = train_tiny_charlm_fallback(log=log, steps=80 if args.smoke else 400)
        used_fallback = True

    # encoder IN-DOMAIN (contribucion, CYCLE 20): entrenado/recargado UNA vez.
    in_model, in_cfg, enc_info = get_indomain_encoder(log, args.enc_steps, args.enc_corpus,
                                                      force_retrain=args.retrain_encoder)

    levels = []
    for amb in AMBIGUITY_LEVELS:
        levels.append(run_ambiguity(log, off_model, in_model, amb, args.n, args.n_test, args.eps, args.seed))

    results = {"levels": levels, "ambiguity_levels": AMBIGUITY_LEVELS,
               "used_fallback_offdomain": used_fallback,
               "off_embed_dim": 2 * off_cfg.d_model, "off_params": off_model.num_params(),
               "in_embed_dim": 2 * in_cfg.d_model, "in_params": in_model.num_params(),
               "in_cfg": {"d_model": in_cfg.d_model, "n_layers": in_cfg.n_layers},
               "encoder_training": enc_info, "encoder_corpus": args.enc_corpus}
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # RESUMEN: tabla 6 brazos vs ambiguedad + pureza C vs D.
    log("\n[cycle20] ===== RESUMEN: accuracy HELD-OUT vs AMBIGUEDAD (6 brazos) =====")
    if used_fallback:
        log("  (!) FALLBACK en uso para C: el char-LM off-domain es el diminuto in-script, NO el de CYCLE 7.")
    log("  ambig | FIJA  | A:kw  | B:NB  | C:off | D:in  | CEIL  | purC  | purD")
    for r in levels:
        log(f"  {r['ambiguity']:.2f}  | {r['best_fixed']['acc']:.3f} | {r['acc_keyword_brittle']:.3f} | "
            f"{r['acc_nb']:.3f} | {r['acc_lm_off']:.3f} | {r['acc_lm_in']:.3f} | {r['acc_type_ceiling']:.3f} | "
            f"{r['purity_lm_off']:.3f} | {r['purity_lm_in']:.3f}")

    # VEREDICTO honesto: ¿D le gana a C y a A, y cierra/supera la brecha con B?
    last = levels[-1]
    log("\n[cycle20] ===== VEREDICTO =====")
    log(f"  ambig max ({last['ambiguity']:.2f}): D(in)={last['acc_lm_in']:.3f} vs C(off)={last['acc_lm_off']:.3f} "
        f"vs B(NB)={last['acc_nb']:.3f} vs A(kw)={last['acc_keyword_brittle']:.3f} | "
        f"ceiling={last['acc_type_ceiling']:.3f} | FIJA={last['best_fixed']['acc']:.3f} | azar={last['acc_random_chain']:.3f}")

    d_vs_c = sum(1 for r in levels if r["acc_lm_in"] >= r["acc_lm_off"] - 1e-9)
    d_vs_a = sum(1 for r in levels if r["acc_lm_in"] >= r["acc_keyword_brittle"] - 1e-9)
    d_vs_b = sum(1 for r in levels if r["acc_lm_in"] >= r["acc_nb"] - 1e-9)
    d_beats_fixed = sum(1 for r in levels if r["acc_lm_in"] > r["best_fixed"]["acc"] + 1e-9)
    log(f"  D(in) iguala/supera a C(off) en {d_vs_c}/{len(levels)} niveles; a A(kw) en {d_vs_a}/{len(levels)}; "
        f"a B(NB) en {d_vs_b}/{len(levels)}; supera a la mejor FIJA en {d_beats_fixed}/{len(levels)}.")

    avg_pur_in = sum(r["purity_lm_in"] for r in levels) / len(levels)
    avg_pur_off = sum(r["purity_lm_off"] for r in levels) / len(levels)
    log(f"  pureza clase->tipo: C(off)={avg_pur_off:.3f}  D(in)={avg_pur_in:.3f} (media sobre niveles)")
    if avg_pur_in > avg_pur_off + 1e-6:
        log(f"  -> entrenar el encoder IN-DOMAIN AFILO la estructura de tipo en la representacion "
            f"(pureza media {avg_pur_in:.3f} > off-domain {avg_pur_off:.3f}).")
    else:
        log(f"  -> HONESTO: el encoder in-domain NO afilo la pureza por encima del off-domain "
            f"(media {avg_pur_in:.3f} vs {avg_pur_off:.3f}).")

    avg_in = sum(r["acc_lm_in"] for r in levels) / len(levels)
    avg_b = sum(r["acc_nb"] for r in levels) / len(levels)
    if d_vs_b == len(levels):
        log(f"  -> CONFIRMA la leccion de CYCLE 19: el encoder entrenado CERCA de la tarea (D, acc media "
            f"{avg_in:.3f}) IGUALA/SUPERA al Naive-Bayes in-domain (B, {avg_b:.3f}).")
    else:
        log(f"  -> HONESTO: aun entrenado in-domain, D (acc media {avg_in:.3f}) NO le gana al Naive-Bayes "
            f"(B, {avg_b:.3f}) en todos los niveles -> un char-LM diminuto unsupervised sigue sin dominar a "
            f"un bag-of-words discriminativo en 4 tipos. Es un hallazgo real sobre el aprendizaje de "
            f"representaciones a esta escala.")
    log(f"  summary.json escrito en {os.path.join(RUN_DIR, 'summary.json')}")
    logf.close()


if __name__ == "__main__":
    main()
