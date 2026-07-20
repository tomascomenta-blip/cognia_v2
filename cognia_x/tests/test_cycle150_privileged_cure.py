r"""
CYCLE 150 / H-V4-9j — regresión: ¿la cura 119 (unlikelihood LABEL-AWARE) es PRIVILEGIADA, o cualquier regularizador de
calibración GENÉRICO (entropy penalty / label smoothing) iguala su ventaja AUROC en el lazo torch real del 149?

El lazo torch es LENTO (6 brazos) -> el test NO re-corre N=16; valida la LÓGICA de privilegio de build_summary sobre datos
sintéticos (APOYADA si el durable bate al MEJOR genérico con CI que excluye 0; REFUTADA si el genérico recupera la ventaja con CI
que cruza 0) + verifica la consistencia interna del results.json commiteado.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle150_privileged_cure.py -q
"""
import json
import os

import numpy as np

from cognia_x.experiments.exp132_privileged_cure import run as X

RESULTS = os.path.join(os.path.dirname(X.__file__), "results", "results.json")


def _mk(seed, dur, gen, nai, rng, jit=0.01):
    """per_seed sintético: AUROC medio dur/gen/nai por brazo (gen se reparte entre los 4 genéricos; el mejor ~= gen)."""
    def series(mu):
        return [mu + jit * rng.standard_normal() for _ in range(8)]
    h = {
        "naive":   {"auroc": series(nai), "ncorrect": [110] * 8, "npool": [512] * 8},
        "durable": {"auroc": series(dur), "ncorrect": [15] * 8, "npool": [512] * 8},
        "ent_lo":  {"auroc": series(gen - 0.01), "ncorrect": [80] * 8, "npool": [512] * 8},
        "ent_hi":  {"auroc": series(gen - 0.03), "ncorrect": [6] * 8, "npool": [512] * 8},
        "ls_lo":   {"auroc": series(gen - 0.005), "ncorrect": [40] * 8, "npool": [512] * 8},
        "ls_hi":   {"auroc": series(gen), "ncorrect": [10] * 8, "npool": [512] * 8},
    }
    real = {a: 0.2 for a in X.ARMS}
    return {"seed": seed, "base": {}, "hist": h, "real_final": real}


def test_logica_apoyada_cuando_durable_bate_al_mejor_generico():
    # durable claramente arriba del mejor genérico Y del naive -> privilegio: CI excluye 0 -> APOYADA
    rng = np.random.default_rng(1)
    ps = [_mk(i, dur=0.93, gen=0.885, nai=0.86, rng=rng) for i in range(16)]
    sm = X.build_summary(ps, n_boot=3000)
    assert sm["status"] == "apoyada", (sm["mean_priv_gap"], sm["ci95"], sm["mean_durable_vs_naive"])
    assert sm["ci_excludes_zero"], sm["ci95"]
    assert sm["mean_durable_vs_naive"] > 0, sm["mean_durable_vs_naive"]   # sanity 149


def test_logica_refutada_cuando_generico_recupera_la_ventaja():
    # durable ~= mejor genérico, ambos > naive -> el genérico recupera -> CI cruza 0 -> REFUTADA
    rng = np.random.default_rng(2)
    ps = [_mk(i, dur=0.90, gen=0.90, nai=0.85, rng=rng, jit=0.02) for i in range(16)]
    sm = X.build_summary(ps, n_boot=3000)
    assert sm["status"] in ("refutada", "mixta"), (sm["status"], sm["mean_priv_gap"], sm["ci95"])
    if sm["status"] == "refutada":
        assert not sm["ci_excludes_zero"], sm["ci95"]
        assert sm["generic_recovers"], (sm["mean_recovery_gap"], sm["recovery_frac"])


def test_results_committeado_consistente():
    if not os.path.exists(RESULTS):
        import pytest
        pytest.skip("results.json aún no generado (corre exp132 primero)")
    with open(RESULTS, encoding="utf-8") as f:
        d = json.load(f)
    s = d["summary"]
    assert d["verdict"] in ("apoyada", "refutada", "mixta"), d["verdict"]
    assert d["verdict"] == s["status"], (d["verdict"], s["status"])
    # consistencia interna de la compuerta de privilegio
    if s["status"] == "apoyada":
        assert s["ci_excludes_zero"] and s["ci95"][0] > 0, s["ci95"]
        assert s["sane_149"], s["mean_durable_vs_naive"]
    if s["status"] == "refutada":
        assert not s["ci_excludes_zero"], s["ci95"]
        assert s["generic_recovers"], (s["mean_recovery_gap"], s["recovery_frac"])
    # sanity 149 SIEMPRE: el durable debe batir al naive (reproduce el hallazgo del 149) en cualquier veredicto
    assert s["mean_durable_vs_naive"] > 0, s["mean_durable_vs_naive"]
