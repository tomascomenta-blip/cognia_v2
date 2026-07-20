r"""
CYCLE 42 / H-V4-1g — regresión: señal de control verifier-free (auto-consistencia) vs ruido del verificador.

Protege el MECANISMO: (a) la señal por auto-consistencia (p_top·(1−p_top)) es un sweet-spot — 0 cuando todos
coinciden y 0 cuando todos difieren, máximo en acuerdo PARCIAL; (b) CONSEC_FREE no usa el veredicto del
verificador → su asignación no se corrompe con el ruido; (c) reproducible por seed.

Config diminuta -> ~30s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle42_robust_control_signal.py -q
"""
from types import SimpleNamespace

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp028_robust_control_signal import run as E


def test_emerging_consensus_signal():
    # consenso EMERGENTE (parcial) > consenso total (ya resuelto/atascado) y > caos total (no controlable)
    same = [("5\n", True), ("5\n", True), ("5\n", True)]    # unánime -> ~0
    alld = [("5\n", True), ("6\n", False), ("7\n", False)]  # caos (p_top=1/3)
    part = [("5\n", True), ("5\n", True), ("7\n", False)]   # consenso emergente (p_top=2/3)
    w_same = E.signal_weight("consequence_free", same, False)
    w_alld = E.signal_weight("consequence_free", alld, False)
    w_part = E.signal_weight("consequence_free", part, False)
    assert w_part > w_same          # acuerdo parcial gana a consenso unánime (controlabilidad nula)
    assert w_part > w_alld          # acuerdo parcial gana al caos total (NO simétrica: distingue 2/3 de 1/3)


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           temperature=1.0, top_k=16, n_probe=3, avg=5)


def _setup(M=60):
    train_pairs, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:M]
    return _args(), test, train_pairs


def test_loop_beats_greedy_at_zero_noise():
    args, test, train_pairs = _setup()
    r = E.run_seed(0, args, test, train_pairs, noises=[0.0], log=lambda m: None)
    d = r["by_noise"][0.0]
    # con verificador perfecto, asignar por consenso-emergente (act-and-verify) supera al greedy de 1 muestra
    assert d["consequence_free"] >= d["greedy"]


def test_reproducible():
    args, test, train_pairs = _setup(M=40)
    a = E.run_seed(0, args, test, train_pairs, noises=[0.1], log=lambda m: None)
    b = E.run_seed(0, args, test, train_pairs, noises=[0.1], log=lambda m: None)
    assert a["by_noise"][0.1]["consequence_free"] == b["by_noise"][0.1]["consequence_free"]
    assert a["greedy_acc"] == b["greedy_acc"]
