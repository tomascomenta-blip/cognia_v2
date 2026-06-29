r"""
PALANCA DE DESACOPLE #1 — MoE (compute condicional): ¿escalar params TOTALES sin escalar el costo?

La raíz de "más params = más lento": el costo (FLOPs/step, bytes/token) escala con los params. MoE rompe
ese acople: con top-k routing sobre E expertos, sólo k se activan por token -> FLOPs ∝ params ACTIVOS, no
TOTALES. Test (regla 10×, calidad↔velocidad): comparar a params ACTIVOS igualados
  - DENSO:  MLP SwiGLU de ancho d_ff.
  - MoE:    E expertos SwiGLU(d_ff), top-1 -> activo ≈ 1 experto ≈ denso, pero TOTAL ≈ E×.
Si el MoE entrena a ~la misma velocidad que el denso (mismo activo) teniendo E× params totales, DESACOPLA
(más capacidad sin más costo). Mide train tok/s Y recall (no sacrificar inteligencia). OJO: a escala chica
el ruteo (gather/scatter) puede dominar -> el desacople se ve mejor a escala; este script lo MIDE, no asume.

Self-contained (importa los mixers/normas del modelo G2 = single source). Corre en Colab T4 o CPU (--smoke).
"""
import argparse
import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from m0_g2_recall_colab import (RMSNorm, SwiGLU, LinearAttention, SlidingWindowAttention,
                                 build_rope_cache, build_layer_types, make_recall_batch)


def sync(device):
    if device == "cuda":
        torch.cuda.synchronize()


class MoESwiGLU(nn.Module):
    """Mezcla de expertos SwiGLU con router top-k (Switch-style) + aux loss de balanceo de carga.
    Activo por token = k expertos (FLOPs ∝ k, no E). Total params ∝ E. fp16-seguro: el router en fp32."""

    def __init__(self, d, d_ff, n_experts, top_k=1):
        super().__init__()
        self.E = n_experts
        self.k = top_k
        self.router = nn.Linear(d, n_experts, bias=False)
        self.experts = nn.ModuleList([SwiGLU(d, d_ff) for _ in range(n_experts)])

    def forward(self, x):
        B, L, d = x.shape
        xf = x.reshape(-1, d)                          # (N, d)
        with torch.autocast(device_type=x.device.type, enabled=False):
            logits = self.router(xf.float())           # (N, E)  router en fp32 (estable)
            gates = F.softmax(logits, dim=-1)
        topv, topi = gates.topk(self.k, dim=-1)        # (N, k)
        topv = topv / (topv.sum(-1, keepdim=True) + 1e-9)
        out = torch.zeros_like(xf)
        for e in range(self.E):                        # dispatch por experto (sólo sus tokens)
            mask = (topi == e)
            if not bool(mask.any()):
                continue
            tok_idx, slot = mask.nonzero(as_tuple=True)
            xe = xf[tok_idx]
            ye = self.experts[e](xe)
            w = topv[tok_idx, slot].unsqueeze(-1).to(ye.dtype)
            out.index_add_(0, tok_idx, ye * w)
        # aux loss de balanceo (Switch): E * sum_e (frac_tokens_e * mean_gate_e). Min cuando uniforme.
        with torch.autocast(device_type=x.device.type, enabled=False):
            one_hot = F.one_hot(topi[:, 0], self.E).float()       # asignación top-1
            frac = one_hot.mean(0)                                 # fracción de tokens por experto
            meang = gates.float().mean(0)                          # gate medio por experto
            aux = self.E * torch.sum(frac * meang)
        return out.reshape(B, L, d), aux


class Block(nn.Module):
    """Block con mixer (lineal/attn) + MLP que puede ser denso (SwiGLU) o MoE (MoESwiGLU)."""

    def __init__(self, d_model, n_heads, d_ff, kind, window, n_experts=1, top_k=1):
        super().__init__()
        self.kind = kind
        self.norm1 = RMSNorm(d_model)
        self.mixer = (SlidingWindowAttention(d_model, n_heads, window) if kind == "attn"
                      else LinearAttention(d_model, n_heads))
        self.norm2 = RMSNorm(d_model)
        self.is_moe = n_experts > 1
        self.mlp = (MoESwiGLU(d_model, d_ff, n_experts, top_k) if self.is_moe
                    else SwiGLU(d_model, d_ff))

    def forward(self, x, cos=None, sin=None):
        x = x + self.mixer(self.norm1(x), cos, sin)
        if self.is_moe:
            y, aux = self.mlp(self.norm2(x))
            x = x + y
            return x, aux
        x = x + self.mlp(self.norm2(x))
        return x, x.new_zeros(())


class HybridLMMoE(nn.Module):
    def __init__(self, vocab, d_model, n_heads, layer_types, window, max_seq_len, d_ff=None,
                 n_experts=1, top_k=1):
        super().__init__()
        d_ff = d_ff or max(16, int(round(8 * d_model / 3 / 16)) * 16)
        self.embed = nn.Embedding(vocab, d_model)
        self.blocks = nn.ModuleList([Block(d_model, n_heads, d_ff, t, window, n_experts, top_k)
                                     for t in layer_types])
        self.dh = d_model // n_heads
        cos, sin = build_rope_cache(max_seq_len, self.dh, device="cpu")
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab, bias=False)
        self.lm_head.weight = self.embed.weight
        self.n_experts = n_experts
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None, aux_weight=0.01):
        x = self.embed(idx)
        L = idx.shape[1]
        cos, sin = self.rope_cos[:L].to(x.dtype), self.rope_sin[:L].to(x.dtype)
        aux_total = x.new_zeros(())
        for b in self.blocks:
            x, aux = b(x, cos, sin)
            aux_total = aux_total + aux
        x = self.norm_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            ce = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-100)
            loss = ce + aux_weight * aux_total
        return logits, loss

    def num_params(self):
        n = sum(p.numel() for p in self.parameters()) - self.embed.weight.numel()
        return n

    def active_params(self):
        """Params 'leídos' por token: todo menos los expertos no-elegidos. Aprox top-1: 1 de E experts."""
        if self.n_experts <= 1:
            return self.num_params()
        expert_params = sum(p.numel() for b in self.blocks if getattr(b, "is_moe", False)
                            for p in b.mlp.experts.parameters())
        per_expert = expert_params / self.n_experts
        return self.num_params() - expert_params + per_expert  # 1 experto activo por capa MoE


@torch.no_grad()
def eval_recall_moe(model, rng, p, device, batches=12, amp=False):
    model.eval()
    hits = total = 0
    for _ in range(batches):
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
        if amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                logits, _ = model(x)
        else:
            logits, _ = model(x)
        pred = logits.argmax(-1)
        m = y != -100
        hits += int((pred[m] == y[m]).sum())
        total += int(m.sum())
    model.train()
    return hits / max(1, total)


def run_one(tag, p, n_experts, top_k, steps, device, amp, log, measure_steps=20, warmup=8):
    rng = np.random.default_rng(0)
    eval_rng = np.random.default_rng(10**6)
    torch.manual_seed(0)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    layer_types = build_layer_types(p["n_layers"], p["attn_every"], "linear_first")
    model = HybridLMMoE(vocab, p["d_model"], p["n_heads"], layer_types, L + 1, L + 1,
                        n_experts=n_experts, top_k=top_k).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=p["lr"], weight_decay=0.01)
    use_amp = amp and device == "cuda"
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    def step_once():
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
        else:
            _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            loss.backward(); opt.step()
        return loss

    # medir throughput (warmup + measure_steps con sync)
    for _ in range(warmup):
        step_once()
    sync(device)
    t0 = time.time()
    for _ in range(measure_steps):
        step_once()
    sync(device)
    tok_s = (p["batch"] * L * measure_steps) / (time.time() - t0)

    # entrenar hasta `steps` y medir recall
    for s in range(steps):
        step_once()
    acc = eval_recall_moe(model, eval_rng, p, device, batches=16, amp=use_amp)
    r = {"tag": tag, "n_experts": n_experts, "top_k": top_k, "params_total": model.num_params(),
         "params_active": int(model.active_params()), "train_tok_s": round(tok_s, 1),
         "recall_acc": round(acc, 4)}
    log(f"  [{tag}] E={n_experts} k={top_k} total={r['params_total']:,} activo={r['params_active']:,} "
        f"| {r['train_tok_s']:.0f} tok/s | recall {r['recall_acc']:.3f}")
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--steps", type=int, default=None)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    amp = device == "cuda"
    if device == "cpu":
        torch.set_num_threads(3)

    if args.smoke:
        p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=64, n_vals=16, n_pairs=12, n_queries=8,
                 batch=16, lr=1e-3, attn_every=2)
        steps = args.steps or 30
        ms, wu = 5, 2
    else:
        p = dict(d_model=256, n_heads=8, n_layers=12, n_keys=256, n_vals=32, n_pairs=32, n_queries=16,
                 batch=64, lr=1e-3, attn_every=2)
        steps = args.steps or 3000
        ms, wu = 25, 10

    print(f"[moe] device={device} amp={amp} scale={p}", flush=True)
    out = {"device": device, "scale": p, "steps": steps, "runs": []}
    if device == "cuda":
        out["gpu_name"] = torch.cuda.get_device_name(0)

    def log(s):
        print(s, flush=True)

    # DENSO (E=1) vs MoE top-1 con E=4 y E=8 (a paridad de ancho de experto => mismo ACTIVO, E× total)
    print("==== DESACOPLE MoE: denso vs MoE top-1 (mismo activo, E× total) ====", flush=True)
    for (tag, E, k) in [("denso", 1, 1), ("moe_E4_top1", 4, 1), ("moe_E8_top1", 8, 1), ("moe_E4_top2", 4, 2)]:
        try:
            out["runs"].append(run_one(tag, p, E, k, steps, device, amp, log, measure_steps=ms, warmup=wu))
        except Exception as e:  # noqa: BLE001
            log(f"  [{tag}] ERROR {e!r}")
            out["runs"].append({"tag": tag, "error": repr(e)})
        with open("g2_moe_results.json", "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

    # veredicto del desacople
    dense = next((r for r in out["runs"] if r.get("tag") == "denso"), None)
    if dense and "train_tok_s" in dense:
        for r in out["runs"]:
            if r.get("tag", "").startswith("moe") and "train_tok_s" in r:
                sp = r["train_tok_s"] / dense["train_tok_s"]
                pr = r["params_total"] / dense["params_total"]
                r["speed_vs_dense"] = round(sp, 3)
                r["params_x_vs_dense"] = round(pr, 2)
                log(f"  [{r['tag']}] {pr:.1f}× params totales a {sp:.2f}× la velocidad del denso "
                    f"(desacople {'SÍ' if sp > 0.7 else 'NO (ruteo domina a esta escala)'})")
    with open("g2_moe_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(">>> MOE JSON:", flush=True)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
