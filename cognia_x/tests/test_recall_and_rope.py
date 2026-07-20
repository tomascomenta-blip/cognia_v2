"""
Tests de regresion para el modelo hibrido y el fix de CYCLE 6 (RoPE + recall).

El bug de CYCLE 6: el modelo no aprendia recall asociativo porque (a) faltaba senal
posicional para la cabeza de induccion y (b) el control positivo estaba sub-recurseado.
Fix: se agrego RoPE a la atencion softmax; con la receta adecuada la atencion resuelve recall.

Estos tests fallan SIN el fix y pasan CON el:
- test_rope_aplica / test_rope_relativa: RoPE existe y tiene la propiedad de posicion relativa.
- test_modelo_posicion_sensible: permutar el orden cambia la salida (no es permutacion-invariante).
- test_aprende_recall_1par: la atencion aprende copia-de-un-salto a acc ~1.0 (smoke rapido, ~30s CPU).

Correr: .\\venv312\\Scripts\\python.exe -m pytest cognia_x/tests/test_recall_and_rope.py -q
"""
import numpy as np
import torch

from cognia_x.model.hybrid import (HybridConfig, HybridLM, apply_rope,
                                    build_rope_cache)
from cognia_x.train.recall_task import train_and_eval


def test_rope_aplica():
    cos, sin = build_rope_cache(8, 16, "cpu")
    x = torch.randn(1, 2, 8, 16)
    y = apply_rope(x, cos, sin)
    assert not torch.allclose(x, y)          # RoPE cambia el tensor
    # norma preservada (rotacion): por par/posicion la norma no cambia
    assert torch.allclose(x.norm(dim=-1), y.norm(dim=-1), atol=1e-4)


def test_rope_relativa():
    """El producto q.k tras RoPE depende solo de la posicion RELATIVA (propiedad clave de RoPE)."""
    dh = 16
    cos, sin = build_rope_cache(32, dh, "cpu")
    torch.manual_seed(0)
    q = torch.randn(1, 1, 1, dh)
    k = torch.randn(1, 1, 1, dh)
    def dot(pi, pj):
        qi = apply_rope(q, cos[pi:pi + 1], sin[pi:pi + 1])
        kj = apply_rope(k, cos[pj:pj + 1], sin[pj:pj + 1])
        return float((qi * kj).sum())
    # misma distancia relativa (=3) en distintos offsets -> mismo producto
    assert abs(dot(5, 2) - dot(10, 7)) < 1e-4
    # distinta distancia relativa -> producto distinto (en general)
    assert abs(dot(5, 2) - dot(5, 4)) > 1e-4


def test_modelo_posicion_sensible():
    cfg = HybridConfig(vocab_size=17, d_model=64, n_layers=2, n_heads=4,
                       attn_every=1, window=99, max_seq_len=16)
    m = HybridLM(cfg).eval()
    a = torch.tensor([[3, 9, 3]])     # k v k
    b = torch.tensor([[9, 3, 3]])     # mismo multiset, otro orden
    la, _ = m(a)
    lb, _ = m(b)
    assert not torch.allclose(la[:, -1], lb[:, -1], atol=1e-5)


def test_aprende_recall_1par():
    """Control positivo minimo: atencion aprende copia-de-un-salto a acc ~1.0 (rapido)."""
    logs = []
    r = train_and_eval("test_np1", attn_every=1, steps=400, log=logs.append, seed=0,
                       d_model=64, n_layers=2, n_heads=4,
                       n_keys=8, n_vals=8, n_pairs=1, n_queries=1,
                       batch=64, lr=1e-3)
    assert r["final_acc"] >= 0.95, f"recall 1-par deberia ~1.0, dio {r['final_acc']}"


def test_aprende_recall_multipar():
    """Recall REAL con disambiguacion (np>=2): la atencion debe seleccionar el par correcto
    entre varios, no solo copiar. Esto SI ejerce la cabeza de induccion (a diferencia de np=1).
    Con supervision densa (n_queries alto) cruza rapido. Regresion del bug central de CYCLE 6."""
    logs = []
    r = train_and_eval("test_np3", attn_every=1, steps=1500, log=logs.append, seed=0,
                       d_model=64, n_layers=2, n_heads=4,
                       n_keys=12, n_vals=16, n_pairs=3, n_queries=12,
                       batch=64, lr=1e-3)
    # azar = 1/16 = 0.0625; debe estar MUY por encima (recall asociativo de verdad).
    assert r["final_acc"] >= 0.90, f"recall 3-pares deberia cruzar a ~1.0, dio {r['final_acc']}"
