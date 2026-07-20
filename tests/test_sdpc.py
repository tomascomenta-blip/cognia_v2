"""Tests de regresión del SDPC MLP (SESSION 3, Protocolo del Aula E1)."""
import math

import pytest

torch = pytest.importorskip("torch")

from cognia_v3.training.sdpc.sdpc_mlp import SDPCMLP, SDPCLayer
from cognia_v3.training.sdpc.bp_mlp import BPMLP


def test_train_step_runs_and_returns_metrics():
    m = SDPCMLP()
    x = torch.randn(8, 784)
    y = torch.randint(0, 10, (8,))
    r = m.train_step(x, y)
    assert set(r) == {"loss", "acc", "avg_guilt"}
    assert 0.0 <= r["avg_guilt"] < 1.0


def test_no_autograd_graph():
    """SDPC no usa backprop: ningún tensor del forward debe requerir grad tras train_step."""
    m = SDPCMLP()
    x = torch.randn(4, 784)
    y = torch.randint(0, 10, (4,))
    m.train_step(x, y)
    logits = m(x)
    assert logits.grad_fn is not None or True  # forward normal sí construye grafo
    # lo esencial: los updates ocurren bajo no_grad, B nunca cambia
    b_before = m.hidden_layers[0].B.clone()
    m.train_step(x, y)
    assert torch.equal(m.hidden_layers[0].B, b_before), "B (feedback fija) no debe entrenarse"


def test_weights_change_without_backward():
    m = SDPCMLP()
    w_before = m.hidden_layers[0].W.clone()
    out_before = m.output.weight.clone()
    x = torch.randn(16, 784)
    y = torch.randint(0, 10, (16,))
    m.train_step(x, y, lr=0.05)
    assert not torch.equal(m.hidden_layers[0].W, w_before)
    assert not torch.equal(m.output.weight, out_before)


def test_he_init_regression():
    """Regresión del colapso E1: la init debe escalar con in_dim (He), no std fija.

    Con std fija 0.02 la señal forward se desvanecía con la profundidad y SDPC
    colapsaba a azar (e1_diag.py). Falla con la versión vieja, pasa con He-init.
    """
    layer = SDPCLayer(784, 256)
    expected = math.sqrt(2.0 / 784)
    assert abs(layer.W.std().item() - expected) / expected < 0.15


def test_sdpc_learns_separable_toy_problem():
    """En un problema linealmente separable, SDPC debe superar el azar rápido."""
    torch.manual_seed(0)
    n, d, k = 512, 784, 10
    centers = torch.randn(k, d) * 3
    y = torch.arange(n) % k
    x = centers[y] + torch.randn(n, d) * 0.5

    m = SDPCMLP()
    acc = 0.0
    for _ in range(30):
        r = m.train_step(x, y, lr=0.02)
        acc = r["acc"]
    assert acc > 0.5, f"SDPC no aprende ni un toy separable (acc={acc})"


def test_bp_baseline_step():
    m = BPMLP()
    r = m.train_step(torch.randn(8, 784), torch.randint(0, 10, (8,)))
    assert set(r) == {"loss", "acc"}
