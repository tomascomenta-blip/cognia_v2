r"""
CYCLE 40 / H-V4-1e (INTEGRADOR) — regresión: act-and-verify TTS sobre el modelo propio del lab.

Protege el hallazgo: bajo presupuesto ESCASO, asignar el cómputo de test-time por CONTROLABILIDAD/
CONSECUENCIA (empowerment) iguala o supera al AZAR (uniforme) y a la PREDICCIÓN-PASIVA (incertidumbre), a
igual presupuesto, sobre el HybridLM byte-level entrenado desde cero + oráculo de suma como verificador.

Config diminuta (base débil, pocos problemas) -> el test corre en ~20s. Verifica el MECANISMO (la
asignación por consecuencia no malgasta en lo ya resuelto/irresoluble), no la magnitud del FULL.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle40_ttc_allocation.py -q
"""
from types import SimpleNamespace

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp026_ttc_allocation import run as E


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           temperature=1.0, top_k=16, n_probe=2, margin=0.0)


def _setup(M=60):
    train_pairs, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:M]
    return _args(), test, train_pairs


def test_consequence_not_worse_than_uniform_when_scarce():
    args, test, train_pairs = _setup()
    r = E.run_seed(0, args, test, train_pairs, budgets=[2], log=lambda m: None)
    d = r["by_budget"][2]
    # bajo escasez, asignar por consecuencia NO es peor que repartir uniforme (no malgasta presupuesto)
    assert d["consequence"] >= d["uniform"] - 1e-9


def test_consequence_at_least_matches_passive():
    args, test, train_pairs = _setup()
    r = E.run_seed(1, args, test, train_pairs, budgets=[2], log=lambda m: None)
    d = r["by_budget"][2]
    # la controlabilidad (consecuencia) iguala o gana a la incertidumbre pasiva (control del arco v4)
    assert d["consequence"] >= d["passive"] - 1e-9


def test_budget_monotonic_helps():
    args, test, train_pairs = _setup()
    r = E.run_seed(2, args, test, train_pairs, budgets=[2, 4], log=lambda m: None)
    # más presupuesto (best-of-k con verificador) no empeora la consecuencia
    assert r["by_budget"][4]["consequence"] >= r["by_budget"][2]["consequence"] - 1e-9


def test_reproducible():
    args, test, train_pairs = _setup(M=40)
    a = E.run_seed(0, args, test, train_pairs, budgets=[2], log=lambda m: None)
    b = E.run_seed(0, args, test, train_pairs, budgets=[2], log=lambda m: None)
    # mismo seed -> base y muestreo deterministas -> idéntico
    assert a["by_budget"][2]["consequence"] == b["by_budget"][2]["consequence"]
    assert a["greedy_acc"] == b["greedy_acc"]
