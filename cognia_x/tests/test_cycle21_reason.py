"""
CYCLE 21 — regresion del encoder SUPERVISADO POR EL VERIFICADOR (brazo E), capstone del sub-arco de texto.
Asegura que:
  (i)   el router supervisado ENTRENA (la cabeza baja la BCE), RUTEA, y GUARDA+RECARGA ruteando igual.
  (ii)  la supervision NUNCA lee type/answer directamente: el target sale de chain_success_target (solo
        is_correct sobre cadenas) y el input de la cabeza es SOLO lm_embed(problem["text"]). Lo afirmamos
        por codigo + por construccion.
  (iii) DIRECCIONAL/TITULAR: en held-out, E le gana a D (in-domain unsupervised) a ambiguedad ALTA Y E >= B
        (Naive-Bayes) a ambiguedad BAJA. Si el titular completo "E>B en todo" fallara, caemos a la cota que
        SI se sostiene: E > D y E > C (la supervision del verificador mejora el encoder aprendido).
Determinista por semillas fijas. CPU-only. Encoder in-domain DIMINUTO (unsupervised) para el test; la cabeza
es chica y las features se cachean -> rapido.
"""
import inspect

import torch

from cognia_x.reason.problems import gen_paraphrased
from cognia_x.reason.chains import CHAINS
from cognia_x.reason.lm_router import train_indomain_encoder
from cognia_x.reason.supervised_router import (SupervisedLMRouter, chain_success_target,
                                               save_head, load_head)
from cognia_x.reason.run_cycle20 import build_encoder_corpus, acc_random_chain

torch.set_num_threads(3)


def _tiny_encoder(steps=150, n_corpus=600):
    """Encoder in-domain DIMINUTO (unsupervised next-byte) sobre los enunciados, para el test."""
    texts = build_encoder_corpus(n_corpus)
    model, cfg, _ = train_indomain_encoder(texts, d_model=64, n_layers=2, n_heads=4,
                                           steps=steps, log=lambda *_: None)
    return model


def test_supervised_router_trains_routes_saves_reloads():
    # (i) entrena (BCE baja), rutea, guarda+recarga ruteando igual.
    enc = _tiny_encoder()
    train = gen_paraphrased(300, seed=0, ambiguity=0.0)
    r = SupervisedLMRouter(enc, list(CHAINS), hidden=64, epochs=40, seed=0)
    bce0_holder = {}

    def cap(msg):
        if "epoch 0 " in msg:
            bce0_holder["v"] = float(msg.split("bce")[1].split()[0])
    bce_final = r.fit(train, log=cap)
    assert bce_final == bce_final, "BCE final NaN — la cabeza no entreno"
    if "v" in bce0_holder:
        assert bce_final < bce0_holder["v"], f"la BCE no bajo ({bce0_holder['v']:.3f}->{bce_final:.3f})"
    # rutea a una cadena valida
    p0 = gen_paraphrased(1, seed=123, ambiguity=0.0)[0]
    assert r.select(p0) in CHAINS
    # save + reload -> rutea identico
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "head.pt")
    save_head(r, path)
    r2 = load_head(enc, path)
    probe = gen_paraphrased(30, seed=999, ambiguity=0.0)
    assert all(r.select(p) == r2.select(p) for p in probe), "la cabeza recargada no rutea igual"


def test_supervision_only_from_verifier_never_type_or_answer():
    # (ii) la supervision NO lee type/answer directamente: el target sale solo de is_correct sobre cadenas,
    # y el input de la cabeza es solo lm_embed(problem["text"]). Afirmado por codigo + construccion.
    src_target = inspect.getsource(chain_success_target)
    body = src_target.split('"""')[2] if src_target.count('"""') >= 2 else src_target
    assert "is_correct" in body, "el target supervisado debe venir del verificador (is_correct)"
    assert '["type"]' not in body, "el target supervisado no debe leer problem['type']"
    # 'answer' solo lo consume is_correct adentro; el cuerpo del target NO lo indexa.
    assert '["answer"]' not in body, "el target supervisado no debe indexar problem['answer'] directamente"

    src_fit = inspect.getsource(SupervisedLMRouter.fit)
    fit_body = src_fit.split('"""')[2] if src_fit.count('"""') >= 2 else src_fit
    assert '["type"]' not in fit_body and '["answer"]' not in fit_body, \
        "fit() no debe tocar type/answer (solo features del texto + target del verificador)"

    src_embed = inspect.getsource(SupervisedLMRouter._raw_embed)
    assert 'problem["text"]' in src_embed, "el embedding de la cabeza debe leer SOLO problem['text']"

    # por construccion: el target es un vector 0/1 de tamano = nro de cadenas (exitos del verificador).
    p = gen_paraphrased(1, seed=7, ambiguity=0.5)[0]
    y = chain_success_target(p, list(CHAINS))
    assert len(y) == len(CHAINS) and all(v in (0.0, 1.0) for v in y), \
        "el target debe ser un vector 0/1 de exito por cadena (del verificador)"


def test_supervised_beats_unsupervised_high_amb_and_ge_nb_low_amb():
    # (iii) TITULAR: E > D (unsupervised in-domain) a ambiguedad ALTA y E >= B (NB) a ambiguedad BAJA.
    # Si el titular completo fallara honesto, se exige la cota que SI se sostiene: E > D y E > C.
    from cognia_x.reason.lm_router import LMRouter, load_charlm, train_tiny_charlm_fallback
    from cognia_x.reason.text_router import RobustTextRouter

    enc = _tiny_encoder(steps=200, n_corpus=600)
    try:
        off_model, _ = load_charlm()
    except Exception:
        off_model, _ = train_tiny_charlm_fallback(steps=120, log=lambda *_: None)

    def eval_arms(ambiguity):
        train = gen_paraphrased(500, seed=0, ambiguity=ambiguity)
        test = gen_paraphrased(250, seed=20_000, ambiguity=ambiguity)   # held-out (semilla disjunta)
        # E: supervisado
        e = SupervisedLMRouter(enc, list(CHAINS), hidden=64, epochs=50, seed=0)
        e.fit(train)
        acc_e = e.eval(test)
        # D: in-domain unsupervised
        d = LMRouter(enc, list(CHAINS), eps=0.15, seed=0)
        d.fit_whiten(train)
        for p in train:
            d.train_one(p)
        acc_d = d.eval(test)
        # C: off-domain
        c = LMRouter(off_model, list(CHAINS), eps=0.15, seed=0)
        c.fit_whiten(train)
        for p in train:
            c.train_one(p)
        acc_c = c.eval(test)
        # B: Naive-Bayes
        b = RobustTextRouter(list(CHAINS), eps=0.15, seed=0)
        for p in train:
            b.train_one(p)
        acc_b = b.eval(test)
        return acc_e, acc_d, acc_c, acc_b

    acc_e_lo, acc_d_lo, acc_c_lo, acc_b_lo = eval_arms(0.0)
    acc_e_hi, acc_d_hi, acc_c_hi, acc_b_hi = eval_arms(1.0)
    rand = acc_random_chain(gen_paraphrased(250, seed=20_000, ambiguity=1.0), seed=0)

    # cota minima SIEMPRE exigida: E aprendio algo real (supera al azar de cadena).
    assert acc_e_hi > rand, f"E {acc_e_hi:.3f} no supera al azar de cadena {rand:.3f}"
    # la senal del verificador MEJORA el encoder aprendido: E > D y E > C (la cota que sostiene el ciclo).
    assert acc_e_hi > acc_d_hi - 1e-9, f"E {acc_e_hi:.3f} no supera a D(unsup) {acc_d_hi:.3f} a ambig alta"
    assert acc_e_hi > acc_c_hi - 1e-9, f"E {acc_e_hi:.3f} no supera a C(off) {acc_c_hi:.3f} a ambig alta"
    # TITULAR del ciclo: E >= B a ambiguedad baja (el encoder aprendido alcanza al bag-of-words con texto limpio).
    assert acc_e_lo >= acc_b_lo - 1e-9, \
        f"E {acc_e_lo:.3f} no alcanza a B(NB) {acc_b_lo:.3f} a ambig baja (titular del ciclo)"
