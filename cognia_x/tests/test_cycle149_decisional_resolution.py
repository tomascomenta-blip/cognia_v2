r"""
CYCLE 149 / H-V4-9i — regresión (APOYADA, confirmado out-of-sample + verificación adversarial). En el lazo torch REAL la confianza
endógena del brazo durable (unlikelihood = cura 119) es MÁS INFORMATIVA sobre la correctness real que la del naive: ventaja AUROC
base-rate-invariante robusta a la potencia (N=16 CI excluye 0) y replica out-of-sample (6/6 frescos -> N=22 t=5.87).

El lazo torch es LENTO (~2-3 min/seed) -> el test NO re-corre N=16; valida la LÓGICA de potencia (build_summary sobre datos
sintéticos: APOYADA si el CI excluye 0, REFUTADA si lo incluye) + verifica el results.json commiteado.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle149_decisional_resolution.py -q
"""
import json
import os

import numpy as np

from cognia_x.experiments.exp131_decisional_resolution import run as X

RESULTS = os.path.join(os.path.dirname(X.__file__), "results", "results.json")


def _mk(seed, dur_adv, rng, nc_dur=15, nc_nai=110):
    return {"seed": seed, "base": {}, "hist": {
        "durable": {"auroc": [0.90 + dur_adv + 0.01 * rng.standard_normal() for _ in range(8)], "ncorrect": [nc_dur] * 8},
        "naive": {"auroc": [0.90 + 0.01 * rng.standard_normal() for _ in range(8)], "ncorrect": [nc_nai] * 8}}}


def test_logica_apoyada_cuando_ci_excluye_cero():
    # ventaja real consistente +0.05 -> CI excluye 0 -> APOYADA
    rng = np.random.default_rng(1)
    ps = [_mk(i, 0.05, rng) for i in range(16)]
    sm = X.build_summary(ps, n_boot=3000)
    assert sm["status"] == "apoyada", (sm["mean_gap"], sm["ci95"])
    assert sm["ci_excludes_zero"], sm["ci95"]
    assert sm["mean_gap"] > 0.03, sm["mean_gap"]


def test_logica_refutada_cuando_ci_incluye_cero():
    # sin ventaja (durable=naive, gap ~0 simétrico) -> CI incluye 0 -> REFUTADA
    rng = np.random.default_rng(2)
    ps = []
    for i in range(16):
        s = _mk(i, 0.0, rng)
        # ruido simétrico grande para que el gap medio sea ~0 con CI cruzando 0
        s["hist"]["durable"]["auroc"] = [0.90 + 0.05 * rng.standard_normal() for _ in range(8)]
        ps.append(s)
    sm = X.build_summary(ps, n_boot=3000)
    assert sm["status"] in ("refutada", "mixta"), (sm["status"], sm["mean_gap"], sm["ci95"])
    # el punto clave: la lógica distingue ausencia-de-ventaja de ventaja-real
    if sm["status"] == "refutada":
        assert not sm["ci_excludes_zero"], sm["ci95"]


def test_results_committeado_es_apoyada_robusto():
    with open(RESULTS, encoding="utf-8") as f:
        d = json.load(f)
    s = d["summary"]
    assert d["verdict"] == "apoyada", d["verdict"]
    assert s["ci_excludes_zero"] and s["ci95"][0] > 0, s["ci95"]
    assert s["n_positive"] >= 13, (s["n_positive"], s["n"])      # 14/16
    assert s["tstat"] > 3.0, s["tstat"]
    assert s["auroc_durable"] > s["auroc_naive"], (s["auroc_durable"], s["auroc_naive"])


def test_results_committeado_replica_out_of_sample():
    with open(RESULTS, encoding="utf-8") as f:
        d = json.load(f)
    oos = d["out_of_sample"]
    assert oos["fresh_n_positive"] == 6, oos       # 6/6 seeds frescos positivos
    assert oos["combined_ci95"][0] > 0, oos["combined_ci95"]   # combinado N=22 excluye 0
    assert oos["combined_tstat"] > 4.0, oos["combined_tstat"]
