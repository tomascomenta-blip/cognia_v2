"""
CYCLE 24 — regresion del kernel Taylor + mimetic init (los dos levers de H-CEIL-3).

Estos tests fallan SIN la implementacion del ciclo y pasan CON ella:
  - test_taylor_identidad: phi(q).phi(k) == 1 + (q.k) + (q.k)^2/2 EXACTO (la propiedad que hace que el
    feature map de Taylor aproxime exp(q.k)). Si alguien rompe la construccion del bloque cuadratico
    (los off-diagonal escalados por sqrt(2), el 1/sqrt(2) global), esta identidad se rompe.
  - test_taylor_dim: dim del feature = 1 + dh + dh(dh+1)/2 y el modelo construye/entrena con "taylor".
  - test_mimetic_aplica: con mimetic_init las capas LINEALES quedan W_k==W_q y W_o==I; SIN el, no.
  - test_mimetic_no_rompe_default: mimetic_init=False deja el modelo IDENTICO al previo (init estandar).
  - test_taylor_y_mimetic_entrenan: ambos brazos hacen forward+backward sin romper (smoke ~seg).

Correr: .\\venv312\\Scripts\\python.exe -m pytest cognia_x/tests/test_cycle24_kernel_init.py -q
"""
import torch

from cognia_x.model.hybrid import (HybridConfig, HybridLM, LinearAttention,
                                    taylor_feature_map, taylor_feature_dim)
from cognia_x.train.recall_task import train_and_eval


def test_taylor_identidad():
    """phi(q).phi(k) reproduce 1 + (q.k) + (q.k)^2/2 con precision de float32."""
    torch.manual_seed(0)
    dh = 8
    q = torch.randn(7, dh) * 0.3
    k = torch.randn(7, dh) * 0.3
    lhs = (taylor_feature_map(q) * taylor_feature_map(k)).sum(-1)
    qk = (q * k).sum(-1)
    rhs = 1.0 + qk + 0.5 * qk ** 2
    assert torch.allclose(lhs, rhs, atol=1e-5), (lhs - rhs).abs().max().item()


def test_taylor_dim():
    dh = 24
    assert taylor_feature_dim(dh) == 1 + dh + dh * (dh + 1) // 2 == 325
    x = torch.randn(3, dh)
    assert taylor_feature_map(x).shape[-1] == taylor_feature_dim(dh)


def test_modelo_construye_con_taylor():
    cfg = HybridConfig(vocab_size=50, d_model=24, n_layers=2, n_heads=1, attn_every=0,
                       window=65, max_seq_len=64, linear_feature_map="taylor")
    m = HybridLM(cfg)
    x = torch.randint(0, 50, (2, 16))
    logits, _ = m(x)
    assert logits.shape == (2, 16, 50)


def test_mimetic_aplica():
    cfg = HybridConfig(vocab_size=50, d_model=24, n_layers=3, n_heads=1, attn_every=0,
                       window=65, max_seq_len=64, mimetic_init=True)
    m = HybridLM(cfg)
    lin = [b.mixer for b in m.blocks if isinstance(b.mixer, LinearAttention)]
    assert lin, "deberia haber capas lineales"
    for la in lin:
        d = la.qkv.weight.shape[1]
        assert torch.allclose(la.qkv.weight[d:2 * d], la.qkv.weight[0:d]), "W_k debe == W_q"
        assert torch.allclose(la.o.weight, torch.eye(d)), "W_o debe == I"


def test_mimetic_no_rompe_default():
    """mimetic_init=False -> init estandar intacta (W_k NO alineada con W_q por construccion)."""
    cfg = HybridConfig(vocab_size=50, d_model=24, n_layers=2, n_heads=1, attn_every=0,
                       window=65, max_seq_len=64, mimetic_init=False)
    m = HybridLM(cfg)
    la = [b.mixer for b in m.blocks if isinstance(b.mixer, LinearAttention)][0]
    d = la.qkv.weight.shape[1]
    assert not torch.allclose(la.qkv.weight[d:2 * d], la.qkv.weight[0:d])


def test_taylor_y_mimetic_entrenan():
    """Smoke: ambos brazos del exp011 hacen unos pasos sin romper (no chequea recall, solo que corre)."""
    logs = []
    for fmap, mim in (("taylor", False), ("elu", True)):
        r = train_and_eval(f"smoke_{fmap}_{mim}", attn_every=0, steps=20, log=logs.append, seed=0,
                           d_model=24, n_layers=2, n_pairs=6, n_heads=1, n_vals=16, n_queries=6,
                           n_keys=60, batch=16, lr=1e-3, warmup=5,
                           linear_feature_map=fmap, mimetic_init=mim)
        assert 0.0 <= r["final_acc"] <= 1.0
