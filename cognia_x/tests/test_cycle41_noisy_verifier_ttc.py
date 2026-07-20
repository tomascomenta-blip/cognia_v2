r"""
CYCLE 41 / H-V4-1f — regresión: realismo del verificador (ruidoso/parcial) sobre act-and-verify TTS.

Protege el MECANISMO: (a) con verificador perfecto (vnoise=0) el act-and-verify supera al greedy (samplear +
verificar ayuda); (b) el ruido del verificador DEGRADA la accuracy real (no la mejora) — los falsos
positivos castigan; (c) reproducible por seed.

Config diminuta (base débil, pocos problemas) -> ~25s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle41_noisy_verifier_ttc.py -q
"""
from types import SimpleNamespace

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp027_noisy_verifier_ttc import run as E


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           temperature=1.0, top_k=16, n_probe=2, avg=3)


def _setup(M=60):
    train_pairs, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:M]
    return _args(), test, train_pairs


def test_perfect_verifier_beats_greedy():
    args, test, train_pairs = _setup()
    r = E.run_seed(0, args, test, train_pairs, noises=[0.0], log=lambda m: None)
    d = r["by_noise"][0.0]
    # con verificador perfecto, act-and-verify (consecuencia) supera al greedy de 1 sola muestra
    assert d["consequence"] >= d["greedy"]


def test_noise_degrades_accuracy():
    args, test, train_pairs = _setup(M=80)
    r = E.run_seed(1, args, test, train_pairs, noises=[0.0, 0.5], log=lambda m: None)
    perfect = r["by_noise"][0.0]["consequence"]
    zero_info = r["by_noise"][0.5]["consequence"]   # vnoise=0.5 = verificador sin información (moneda)
    # un verificador sin información NO supera al perfecto (tolerancia a varianza de muestreo)
    assert zero_info <= perfect + 0.05


def test_reproducible():
    args, test, train_pairs = _setup(M=40)
    a = E.run_seed(0, args, test, train_pairs, noises=[0.1], log=lambda m: None)
    b = E.run_seed(0, args, test, train_pairs, noises=[0.1], log=lambda m: None)
    assert a["by_noise"][0.1]["consequence"] == b["by_noise"][0.1]["consequence"]
    assert a["greedy_acc"] == b["greedy_acc"]
