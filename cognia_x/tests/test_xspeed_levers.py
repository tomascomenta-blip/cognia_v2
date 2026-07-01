r"""
XSPEED — regresion de los levers de velocidad portados al hybrid.py canonico (TAREA 1).

Medidos en Kaggle T4 (construccion/results_xspeed/xspeed_results.json): cheap16 recupera el 100%
del costo del fix fp16-seguro (68.1k vs 59.4k tok/s a b64) y con compile+fused da 148.7k tok/s
(4.10x fp32); SDPA +36% en capas de atencion. Gates que pasaron en GPU: NaN-watch 3000 steps en la
config que NaNeaba, paridad de loss 1.3%, grokking e2e en el MISMO step 3600 que fp32.

Estos tests protegen lo que puede verificarse en CPU:
  - cheap16 es matematicamente NEUTRO (mismos pesos -> mismos logits en fp32, solo redondeo).
  - SDPA reproduce el nucleo manual (global y ventanado) con precision float.
  - Los DEFAULTS quedan intactos (safe32 + nucleo manual = comportamiento previo EXACTO).
  - taylor cae a safe32 aunque se pida cheap16 (no es kernel positivo total).
  - cheap16+sdpa ENTRENAN (smoke).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_xspeed_levers.py -q
"""
import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.train.recall_task import train_and_eval


def _pair(cfg_kwargs_a, cfg_kwargs_b, seed=0, vocab=50, L=24):
    """Dos modelos con los MISMOS pesos y configs distintas; devuelve logits de ambos."""
    base = dict(vocab_size=vocab, d_model=32, n_layers=4, n_heads=2, window=65, max_seq_len=64)
    torch.manual_seed(seed)
    ma = HybridLM(HybridConfig(**{**base, **cfg_kwargs_a}))
    torch.manual_seed(seed)
    mb = HybridLM(HybridConfig(**{**base, **cfg_kwargs_b}))
    mb.load_state_dict(ma.state_dict())
    x = torch.randint(0, vocab, (3, L))
    la, _ = ma(x)
    lb, _ = mb(x)
    return la, lb


def test_cheap16_es_neutro():
    """cheap16 vs safe32 con mismos pesos en fp32: la escala de q se cancela en el cociente."""
    la, lb = _pair(dict(attn_every=0, amp_linear_core="safe32"),
                   dict(attn_every=0, amp_linear_core="cheap16"))
    rel = (la - lb).abs().max().item() / la.abs().max().item()
    assert rel < 1e-3, f"cheap16 debe ser neutro (medido 7e-06 en T4); rel={rel:.2e}"


def test_sdpa_reproduce_nucleo_manual_global():
    """SDPA (window >= L -> is_causal) vs nucleo manual: misma atencion softmax."""
    la, lb = _pair(dict(attn_every=1, attn_sdpa=False),
                   dict(attn_every=1, attn_sdpa=True))
    assert torch.allclose(la, lb, atol=1e-4), (la - lb).abs().max().item()


def test_sdpa_reproduce_nucleo_manual_ventanado():
    """SDPA con mascara de ventana (window < L) vs nucleo manual ventanado."""
    base = dict(attn_every=1, window=8)
    la, lb = _pair(dict(**base, attn_sdpa=False), dict(**base, attn_sdpa=True), L=24)
    assert torch.allclose(la, lb, atol=1e-4), (la - lb).abs().max().item()


def test_defaults_intactos():
    """HybridConfig() default = safe32 + nucleo manual (cero cambio de comportamiento sin opt-in)."""
    cfg = HybridConfig()
    assert cfg.amp_linear_core == "safe32"
    assert cfg.attn_sdpa is False
    la, lb = _pair(dict(attn_every=4), dict(attn_every=4, amp_linear_core="safe32", attn_sdpa=False))
    assert torch.equal(la, lb)


def test_taylor_cae_a_safe32():
    """taylor + cheap16 no revienta: cae al nucleo fp32 (documentado en la config) y da finito."""
    cfg = HybridConfig(vocab_size=50, d_model=32, n_layers=2, n_heads=2, attn_every=0,
                       window=65, max_seq_len=64, linear_feature_map="taylor",
                       amp_linear_core="cheap16")
    m = HybridLM(cfg)
    x = torch.randint(0, 50, (2, 16))
    logits, _ = m(x)
    assert torch.isfinite(logits).all()


def test_cheap16_sdpa_entrenan():
    """Smoke: el combo rapido (cheap16 + sdpa) entrena unos pasos sin romper."""
    logs = []
    r = train_and_eval("smoke_fast16", attn_every=2, steps=20, log=logs.append, seed=0,
                       d_model=24, n_layers=2, n_pairs=6, n_heads=1, n_vals=16, n_queries=6,
                       n_keys=60, batch=16, lr=1e-3, warmup=5,
                       amp_linear_core="cheap16", attn_sdpa=True)
    assert 0.0 <= r["final_acc"] <= 1.0
