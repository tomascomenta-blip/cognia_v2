r"""
LoRA / adapters para HybridLM — la palanca "rápido + REENTRENABLE" (entrenar POCOS params).

Por qué (goal): "fácilmente reentrenable y rápida". LoRA congela el modelo base y entrena adaptadores de
bajo rango (A: r×in, B: out×r) en las proyecciones lineales -> #params entrenables cae ~100×, los
gradientes/estado-de-optimizer caen igual, y el CHECKPOINT REENTRENABLE pesa KB en vez de MB (sólo A,B).
Combina con base cuantizada (QLoRA) para inferencia barata. delta = (x A^T) B^T * (alpha/r); B se inicia
en 0 -> el modelo arranca IDÉNTICO al base (finetune estable).

Uso: inject_lora(model, r, alpha, targets) reemplaza los nn.Linear objetivo por LoRALinear; luego
mark_only_lora_trainable(model) deja sólo A,B con requires_grad. lora_state_dict(model) = checkpoint chico.
NO toca lm_head/embed (atados). Smoke: venv312\Scripts\python.exe -m cognia_x.train.lora
"""
import math

import torch
import torch.nn as nn


class LoRALinear(nn.Module):
    """Envuelve un nn.Linear: base congelado + delta de bajo rango entrenable."""

    def __init__(self, base: nn.Linear, r=8, alpha=16, dropout=0.0):
        super().__init__()
        assert isinstance(base, nn.Linear)
        self.base = base
        self.base.weight.requires_grad_(False)
        if self.base.bias is not None:
            self.base.bias.requires_grad_(False)
        self.r = r
        self.scaling = alpha / r
        self.A = nn.Parameter(torch.zeros(r, base.in_features))
        self.B = nn.Parameter(torch.zeros(base.out_features, r))
        nn.init.kaiming_uniform_(self.A, a=math.sqrt(5))   # A ~ ruido pequeño
        # B = 0 -> delta inicial = 0 -> forward idéntico al base al empezar (finetune estable)
        self.drop = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

    def forward(self, x):
        delta = (self.drop(x) @ self.A.t()) @ self.B.t()
        return self.base(x) + delta * self.scaling


def inject_lora(model, r=8, alpha=16, targets=("qkv", "o", "w1", "w2", "w3")):
    """Reemplaza in-place los nn.Linear cuyo nombre de atributo esté en `targets` por LoRALinear.
    Devuelve cuántos se envolvieron. Evita lm_head/embed (atados -> romperían el tying)."""
    n = 0
    for module in model.modules():
        for child_name, child in list(module.named_children()):
            if isinstance(child, nn.Linear) and child_name in targets:
                setattr(module, child_name, LoRALinear(child, r, alpha))
                n += 1
    return n


def mark_only_lora_trainable(model):
    """Sólo A,B entrenables; todo lo demás congelado. Devuelve (#entrenables, #total)."""
    trn = tot = 0
    for name, p in model.named_parameters():
        is_lora = name.endswith(".A") or name.endswith(".B")
        p.requires_grad_(is_lora)
        tot += p.numel()
        if is_lora:
            trn += p.numel()
    return trn, tot


def lora_state_dict(model):
    """Sólo los params de LoRA (checkpoint REENTRENABLE chico)."""
    return {k: v for k, v in model.state_dict().items() if k.endswith(".A") or k.endswith(".B")}


def _smoke():
    from cognia_x.model.hybrid import HybridConfig, HybridLM
    torch.manual_seed(0)
    cfg = HybridConfig(vocab_size=80, d_model=64, n_layers=4, n_heads=4, window=40,
                       attn_every=2, max_seq_len=40)
    model = HybridLM(cfg)
    base_qkv = model.blocks[0].mixer.qkv.weight.clone()
    n_wrapped = inject_lora(model, r=8, alpha=16)
    trn, tot = mark_only_lora_trainable(model)
    print(f"LoRA envueltos: {n_wrapped} linears | entrenables {trn:,}/{tot:,} = {100*trn/tot:.2f}%")

    x = torch.randint(0, 80, (4, 30))
    y = torch.randint(0, 80, (4, 30))
    logits, loss = model(x, y)
    loss.backward()
    # el base NO debe tener gradiente; A/B sí
    qkv_mod = model.blocks[0].mixer.qkv
    assert qkv_mod.base.weight.grad is None, "el base no debe entrenar"
    assert qkv_mod.A.grad is not None and qkv_mod.B.grad is not None, "los adapters deben entrenar"
    # un paso de opt no debe cambiar el peso base
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-2)
    opt.step()
    assert torch.allclose(qkv_mod.base.weight, base_qkv), "el peso base cambió (no debería)"
    sd = lora_state_dict(model)
    sd_bytes = sum(v.numel() * v.element_size() for v in sd.values())
    full_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
    print(f"checkpoint LoRA: {len(sd)} tensores, {sd_bytes/1024:.1f} KB vs modelo full {full_bytes/1024:.1f} KB "
          f"({full_bytes/sd_bytes:.0f}× más chico)")
    print("CHECK LoRA OK: base congelado, sólo adapters entrenan, checkpoint chico, forward+backward corre.")


if __name__ == "__main__":
    _smoke()
