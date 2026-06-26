r"""
CYCLE 96 / H-V4-8b — regresión: la selección MARGINAL (cobertura de targets) subsume el downstream de la guardia
dedup+replay SIN el crutch del replay clean (a costo de yield). El lazo usa torch y es lento -> se protege la LÓGICA del
veredicto (build_summary) y el helper de cobertura; el run real se verifica al correr el experimento/ciclo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle96_marginal_loop.py -q
"""
from cognia_x.experiments.exp080_marginal_loop import run as X


def test_marginal_alloc_covers_targets():
    # 3 candidatos del target A (alta confianza) + 1 de B: top-2 absoluto toma 2 de A; marginal cubre A y B
    conf = [0.9, 0.85, 0.8, 0.5]
    prompts = [b"7=", b"7=", b"7=", b"9="]
    picks = X._marginal_alloc(conf, prompts, B=2)
    covered = {prompts[i] for i in picks}
    assert covered == {b"7=", b"9="}              # cobertura: ambos targets, no 2 del mismo


def _seed(yc, ym, yg, yva, rc, rm, rg, rva, corr=0.45, B=20, M=100):
    return {"hist": {"conf_alloc": {"yield": yc, "real": [0.5] + rc},
                     "marginal_alloc": {"yield": ym, "real": [0.5] + rm},
                     "conf_alloc_guard": {"yield": yg, "real": [0.5] + rg},
                     "verify_all": {"yield": yva, "real": [0.5] + rva}},
            "conf_strong_corr": corr, "B": B, "M": M, "base": {"real_acc": 0.5}}


def test_verdict_mixta_subsumes_at_yield_cost():
    # marginal rescata (real > conf) y ≈ guard (subsume) PERO yield < conf -> mixta
    per = [_seed([56, 47], [46, 36], [61, 46], [99, 67], [0.29, 0.28], [0.47, 0.39], [0.52, 0.39], [0.53, 0.37]),
           _seed([55, 48], [45, 37], [60, 47], [98, 66], [0.30, 0.29], [0.46, 0.40], [0.51, 0.40], [0.52, 0.38])]
    sm = X.build_summary(per)
    assert sm["rescues"] and sm["subsumes_guard"] and not sm["yield_ok"]
    assert sm["status"] == "mixta"


def test_verdict_apoyada_subsumes_keeps_yield():
    # marginal rescata, ≈ guard Y mantiene el yield -> apoyada
    per = [_seed([56, 55], [46, 50], [61, 47], [99, 67], [0.29, 0.28], [0.50, 0.49], [0.52, 0.50], [0.53, 0.37]),
           _seed([55, 54], [45, 51], [60, 47], [98, 66], [0.30, 0.29], [0.51, 0.50], [0.51, 0.49], [0.52, 0.38])]
    sm = X.build_summary(per)
    assert sm["rescues"] and sm["subsumes_guard"] and sm["yield_ok"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_no_rescue():
    # marginal ≈ conf -> la cobertura no rescata
    per = [_seed([56, 47], [46, 36], [61, 46], [99, 67], [0.29, 0.28], [0.30, 0.29], [0.52, 0.39], [0.53, 0.37]),
           _seed([55, 48], [45, 37], [60, 47], [98, 66], [0.30, 0.29], [0.29, 0.30], [0.51, 0.40], [0.52, 0.38])]
    sm = X.build_summary(per)
    assert not sm["rescues"]
    assert sm["status"] == "refutada"
