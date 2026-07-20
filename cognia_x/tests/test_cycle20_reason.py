"""
CYCLE 20 — regresion de entrenar el char-LM ENCODER IN-DOMAIN (sobre los propios enunciados) como encoder
del router, y testear la leccion de CYCLE 19 ("entrenar cerca de la tarea"). Asegura que:
  (i)   el encoder in-domain ENTRENA (next-byte unsupervised) y lm_embed devuelve un vector de tamano fijo
        (2*d_model); reload + embed reproduce el mismo shape.
  (ii)  el entrenamiento del encoder es UNSUPERVISED: NUNCA lee problem["type"] ni problem["answer"]. Lo
        afirmamos por codigo (train_indomain_encoder recibe una lista de strings; build_encoder_corpus
        descarta todo menos problem["text"]).
  (iii) DIRECCIONAL del ciclo: a ambiguedad BAJA (regimen estable), el router IN-DOMAIN (D) >= off-domain
        (C). Si esto fallara honestamente, caemos a la cota minima informativa: D > azar-de-cadena.
Determinista por semillas fijas. CPU-only. Conteos chicos (cada problema = 1 forward del LM); el encoder se
entrena diminuto/rapido para el test.
"""
import inspect

import torch

from cognia_x.reason.problems import gen_paraphrased
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.lm_router import (LMRouter, lm_embed, load_charlm, train_tiny_charlm_fallback,
                                       train_indomain_encoder, save_encoder, load_encoder)
from cognia_x.reason import run_cycle20
from cognia_x.reason.run_cycle20 import acc_random_chain, build_encoder_corpus

torch.set_num_threads(3)


def _train_tiny_indomain(steps=120, n_corpus=400):
    """Entrena un encoder in-domain DIMINUTO sobre los enunciados (unsupervised), para el test."""
    texts = build_encoder_corpus(n_corpus)
    model, cfg, loss = train_indomain_encoder(texts, d_model=64, n_layers=2, n_heads=4,
                                              steps=steps, log=lambda *_: None)
    return model, cfg, loss


def _off_model():
    """char-LM off-domain de CYCLE 7; si el checkpoint no esta, fallback diminuto."""
    try:
        model, _ = load_charlm()
        return model
    except Exception:
        model, _ = train_tiny_charlm_fallback(steps=120, log=lambda *_: None)
        return model


def test_indomain_encoder_trains_and_embeds_fixed_shape():
    # (i) el encoder in-domain entrena y lm_embed devuelve un vector fijo de 2*d_model; reload reproduce.
    model, cfg, loss = _train_tiny_indomain()
    assert loss == loss and loss < 5.0, f"loss final sospechoso ({loss}) — el encoder no entreno"
    txt = "La cuenta dio $80.00 con 10% de propina entre 5 amigos. ¿Cuanto cada uno?"
    emb = lm_embed(model, txt)
    assert emb.shape == (2 * cfg.d_model,), f"shape inesperado {tuple(emb.shape)}"
    # save + reload -> mismo shape, mismo embedding (encoder reproducible).
    import tempfile, os
    p = os.path.join(tempfile.mkdtemp(), "enc.pt")
    save_encoder(model, cfg, p)
    rm, rcfg = load_encoder(p)
    emb2 = lm_embed(rm, txt)
    assert emb2.shape == (2 * rcfg.d_model,)
    assert torch.allclose(emb, emb2), "el encoder recargado no reproduce el embedding"


def test_indomain_encoder_training_is_unsupervised():
    # (ii) el entrenamiento NO ve type/answer: train_indomain_encoder recibe `texts` (strings) y
    # build_encoder_corpus extrae SOLO problem["text"]. Lo afirmamos por codigo + por construccion.
    assert "texts" in inspect.signature(train_indomain_encoder).parameters, \
        "train_indomain_encoder debe recibir `texts` (no problems con label)"
    # cuerpo SIN docstring (el docstring si menciona type/answer al EXPLICAR que no los toca).
    src_train = inspect.getsource(train_indomain_encoder)
    body = src_train.split('"""')[2] if src_train.count('"""') >= 2 else src_train
    assert '["type"]' not in body and '["answer"]' not in body, \
        "el cuerpo del entrenamiento del encoder no debe tocar type/answer"
    src_corpus = inspect.getsource(build_encoder_corpus)
    assert 'p["text"]' in src_corpus, "el corpus del encoder debe extraer SOLO problem['text']"
    assert '["answer"]' not in src_corpus and '["type"]' not in src_corpus, \
        "el corpus del encoder no debe leer type/answer"
    # por construccion: lo que recibe el entrenador son strings puros (sin acceso al dict del problema).
    texts = build_encoder_corpus(20)
    assert all(isinstance(t, str) for t in texts), "el corpus deben ser strings (no dicts con label)"


def test_indomain_router_beats_offdomain_at_low_ambiguity():
    # (iii) DIRECCIONAL: a ambiguedad BAJA, el router IN-DOMAIN (D) >= off-domain (C). Si fallara honesto,
    # afirmamos la cota minima: D > azar-de-cadena (aprendio algo real de la representacion in-domain).
    in_model, _, _ = _train_tiny_indomain(steps=200, n_corpus=600)
    off_model = _off_model()

    train = gen_paraphrased(500, seed=0, ambiguity=0.0)
    test = gen_paraphrased(250, seed=20_000, ambiguity=0.0)   # held-out (semilla disjunta)

    def fit_eval(model):
        r = LMRouter(model, list(CHAINS), eps=0.15, seed=0)
        r.fit_whiten(train)
        for p in train:
            r.train_one(p)
        return r.eval(test), r.class_to_type_purity(test)[0]

    acc_in, pur_in = fit_eval(in_model)
    acc_off, pur_off = fit_eval(off_model)
    rand = acc_random_chain(test, seed=0)

    # cota minima SIEMPRE exigida: el router in-domain aprendio algo real (supera al azar de cadena).
    assert acc_in > rand, f"router IN-DOMAIN {acc_in:.3f} no supera al azar de cadena {rand:.3f}"
    # recupera estructura de tipo muy por encima del azar de etiqueta (4 tipos -> 0.25).
    assert pur_in > 0.25 + 1e-6, f"pureza clase->tipo in-domain {pur_in:.3f} no supera el azar 0.25"
    # DIRECCIONAL del ciclo: in-domain >= off-domain a ambiguedad baja (la claim de CYCLE 20).
    assert acc_in >= acc_off - 1e-9, \
        f"in-domain {acc_in:.3f} no alcanza al off-domain {acc_off:.3f} a ambig baja (claim direccional)"
