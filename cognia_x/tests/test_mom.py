"""Tests del paquete MoM (selector + modelo + fleet). Rápidos, CPU, sin checkpoints grandes."""
import json
from pathlib import Path

import pytest
import torch

from cognia_x.mom.selector import Selector, eval_selector, tri_profile
from cognia_x.mom.model import XHLM

XH = Path(__file__).resolve().parents[1] / "construccion" / "xhundred"
MANIFEST = Path(__file__).resolve().parents[1] / "mom" / "manifest.json"

CODE = "def foo(x):\n    return x + 1\n\nclass Bar:\n    pass\n" * 30
STORY = "habia una vez un nino que jugaba en el parque con su perro feliz. " * 30
WIKI = "la provincia se encuentra en la region historica del norte peninsular. " * 30


def test_tri_profile_normalizado():
    p = tri_profile(CODE)
    assert p and abs(sum(p.values())) <= 1.0 + 1e-6
    assert all(0 < v <= 1 for v in p.values())


def test_selector_rutea_y_fallback():
    sel = Selector.from_texts({"code": CODE, "stories": STORY, "wiki": WIKI},
                              threshold=0.45)
    dest, post = sel.select("def bar(y):\n    return y * 2")
    assert dest == "code" and max(post.values()) >= 0.45
    dest2, _ = sel.select("el nino jugaba feliz en el parque")
    assert dest2 == "stories"
    # ambigüedad (texto sin señal) → fallback al generalista, nunca a otro experto
    sel_estricto = Selector.from_texts({"code": CODE, "stories": STORY, "wiki": WIKI},
                                       threshold=0.99)
    dest3, _ = sel_estricto.select("zzz qqq 123")
    assert dest3 == "gen"


def test_selector_serializacion_roundtrip():
    sel = Selector.from_texts({"code": CODE, "stories": STORY}, threshold=0.5)
    sel2 = Selector.from_dict(json.loads(json.dumps(sel.to_dict())))
    txt = "def f():\n    pass"
    assert sel.select(txt) == sel2.select(txt)


def test_eval_selector_sintetico_perfecto():
    sel = Selector.from_texts({"code": CODE, "stories": STORY, "wiki": WIKI})
    rep = eval_selector(sel, {"code": CODE, "stories": STORY, "wiki": WIKI},
                        chunk=200, max_chunks=5)
    assert rep["acc"] == 1.0 and rep["n"] == 15


def test_xhlm_tiny_forward_y_generate():
    torch.manual_seed(0)
    m = XHLM(vocab=64, d=32, n_heads=2, n_layers=2, global_layers=(1,))
    x = torch.randint(1, 64, (2, 16))
    logits, loss = m(x, x)
    assert logits.shape == (2, 16, 64) and torch.isfinite(loss)
    y = m.generate(x[:1, :4], n_new=5, eos_id=-1)
    assert y.shape[1] == 9


@pytest.mark.skipif(not MANIFEST.exists(), reason="manifest del MoM no construido")
def test_fleet_carga_manifest_y_rutea_sin_modelos():
    from cognia_x.mom.fleet import Fleet
    fl = Fleet(MANIFEST)
    dest, post = fl.route("def suma(a, b):\n    return a + b")
    assert dest in ("code", "gen") and abs(sum(post.values()) - 1.0) < 1e-6
    assert not fl._models, "route() no debe cargar modelos (lazy)"
    assert set(fl.paths) == {"gen", "stories", "wiki", "code"}
