r"""
XRMT — memoria recurrente (RMT, Bulatov 2022) sobre el banded ganador: ¿los memory tokens
recuperan lo que la ventana de atención no ve? (bonus del goal OLMo/Chimera: "memoria recurrente"
estaba en la lista de técnicas y es además el análogo del write-gate del Chimera interno).

H-RMT (pre-registrada en goal-state ANTES de correr): 3 brazos, mismo modelo banded 3:1 (d=256,
8 capas), mismos datos (es-wiki bytes), midiendo bpb SOLO del 2do segmento (tokens 512-1023):
  (a) full1024      : atención sobre los 1024 completos (cota SUPERIOR: ve todo el pasado)
  (b) seg_ciego     : 2 segmentos de 512 independientes (cota INFERIOR: ciego al 1er segmento)
  (c) seg_rmt       : 2 segmentos + M=16 memory tokens escritos en el seg 1 y leídos en el 2 (BPTT)
PASA si (c) recupera >=30% del gap (b)-(a). Si (c)~(b): la memoria no aprende a transportar y se
DESCARTA a esta escala/presupuesto.

Self-contained, Kaggle T4, internet ON. Resultados a xrmt_results.json.
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xrmt_kernel.py --smoke
"""
import argparse
import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

RESULTS_PATH = "xrmt_results.json"
TIME_BUDGET_MIN = 45.0


def build_rope_cache(seq_len, dh, device, base=10000.0):
    half = dh // 2
    inv_freq = 1.0 / (base ** (torch.arange(0, half, device=device).float() / half))
    pos = torch.arange(seq_len, device=device).float()
    ang = torch.outer(pos, inv_freq)
    emb = torch.cat([ang, ang], dim=-1)
    return emb.cos(), emb.sin()


def apply_rope(x, cos, sin):
    L = x.shape[-2]
    cos = cos[:L].view(1, 1, L, -1)
    sin = sin[:L].view(1, 1, L, -1)
    half = x.shape[-1] // 2
    x1, x2 = x[..., :half], x[..., half:]
    rot = torch.cat([-x2, x1], dim=-1)
    return x * cos + rot * sin


class RMSNorm(nn.Module):
    def __init__(self, d, eps=1e-5):
        super().__init__()
        self.w = nn.Parameter(torch.ones(d))
        self.eps = eps

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.w


class SwiGLU(nn.Module):
    def __init__(self, d, d_ff):
        super().__init__()
        self.w1 = nn.Linear(d, d_ff, bias=False)
        self.w2 = nn.Linear(d, d_ff, bias=False)
        self.w3 = nn.Linear(d_ff, d, bias=False)

    def forward(self, x):
        return self.w3(F.silu(self.w1(x)) * self.w2(x))


class Attn(nn.Module):
    def __init__(self, d, n_heads, window=None):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos, sin, n_mem=0):
        """n_mem: cuántos tokens INICIALES son memoria (visibles para TODOS aunque haya ventana)."""
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)
        if self.window is None or self.window >= L:
            out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        else:
            idx = torch.arange(L, device=x.device)
            mask = (idx[None, :] <= idx[:, None]) & (idx[None, :] > (idx[:, None] - self.window))
            if n_mem:
                mask[:, :n_mem] = idx[:, None].expand(L, n_mem) >= idx[None, :n_mem]  # memoria siempre visible (causal)
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        return self.o(out.transpose(1, 2).reshape(B, L, D))


class Block(nn.Module):
    def __init__(self, d, n_heads, d_ff, window=None):
        super().__init__()
        self.norm1 = RMSNorm(d)
        self.attn = Attn(d, n_heads, window)
        self.norm2 = RMSNorm(d)
        self.mlp = SwiGLU(d, d_ff)

    def forward(self, x, cos, sin, n_mem=0):
        x = x + self.attn(self.norm1(x), cos, sin, n_mem)
        x = x + self.mlp(self.norm2(x))
        return x


class RMTLM(nn.Module):
    """Banded LM con memoria RMT opcional: [read_mem | tokens | write_mem]; los estados finales de
    write_mem del segmento t son el read_mem del segmento t+1 (BPTT a través del borde)."""

    def __init__(self, vocab, d, n_heads, layer_windows, n_mem=0, max_seq=2048):
        super().__init__()
        d_ff = max(16, int(round(8 * d / 3 / 16)) * 16)
        self.embed = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList([Block(d, n_heads, d_ff, w) for w in layer_windows])
        self.n_mem = n_mem
        if n_mem:
            self.mem_read0 = nn.Parameter(torch.randn(n_mem, d) * 0.02)
            self.mem_write = nn.Parameter(torch.randn(n_mem, d) * 0.02)
        cos, sin = build_rope_cache(max_seq, d // n_heads, device="cpu")
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d)
        self.lm_head = nn.Linear(d, vocab, bias=False)
        self.lm_head.weight = self.embed.weight
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def _run(self, x, n_mem):
        L = x.shape[1]
        cos, sin = self.rope_cos[:L].to(x.dtype), self.rope_sin[:L].to(x.dtype)
        for b in self.blocks:
            x = b(x, cos, sin, n_mem)
        return x

    def seg_forward(self, idx, mem_in=None):
        """Un segmento: devuelve (logits de los tokens reales, mem_out)."""
        B = idx.shape[0]
        tok = self.embed(idx)
        if self.n_mem == 0:
            h = self._run(tok, 0)
            return self.lm_head(self.norm_f(h)), None
        rd = (self.mem_read0.unsqueeze(0).expand(B, -1, -1) if mem_in is None else mem_in)
        wr = self.mem_write.unsqueeze(0).expand(B, -1, -1)
        x = torch.cat([rd, tok, wr], dim=1)
        h = self._run(x, self.n_mem)
        h_tok = h[:, self.n_mem:self.n_mem + idx.shape[1]]
        mem_out = h[:, self.n_mem + idx.shape[1]:]
        return self.lm_head(self.norm_f(h_tok)), mem_out

    def num_params(self):
        return sum(p.numel() for p in self.parameters()) - self.embed.weight.numel()


def loss_two_segments(model, x1, y1, x2, y2, mode):
    """Devuelve (loss total para entrenar, nll del SEGUNDO segmento para medir)."""
    if mode == "full1024":
        logits, _ = model.seg_forward(torch.cat([x1, x2], dim=1))
        L1 = x1.shape[1]
        nll1 = F.cross_entropy(logits[:, :L1].reshape(-1, 256), y1.reshape(-1))
        nll2 = F.cross_entropy(logits[:, L1:].reshape(-1, 256), y2.reshape(-1))
        return (nll1 + nll2) / 2, nll2
    mem = None
    logits1, mem = model.seg_forward(x1, mem)
    nll1 = F.cross_entropy(logits1.reshape(-1, 256), y1.reshape(-1))
    if mode == "seg_ciego":
        mem = None
    logits2, _ = model.seg_forward(x2, mem)
    nll2 = F.cross_entropy(logits2.reshape(-1, 256), y2.reshape(-1))
    return (nll1 + nll2) / 2, nll2


def get_text(smoke, target_bytes=9_000_000):
    if smoke:
        return ("la casa azul del pueblo guarda libros viejos que hablan de rios y montanas. "
                "cada tarde el bibliotecario ordena mapas y cartas de viajeros antiguos. " * 900)
    from datasets import load_dataset
    try:
        ds = load_dataset("wikimedia/wikipedia", "20231101.es", split="train", streaming=True)
        parts, total = [], 0
        for a in ds:
            t = a.get("text", "")
            if len(t) > 500:
                parts.append(t)
                total += len(t)
            if total >= target_bytes:
                break
        return "\n\n".join(parts)
    except Exception:  # noqa: BLE001
        from datasets import load_dataset as ld
        ds = ld("wikitext", "wikitext-103-raw-v1", split="train")
        parts, total = [], 0
        for t in ds["text"]:
            if t.strip():
                parts.append(t)
                total += len(t)
            if total >= target_bytes:
                break
        return "\n".join(parts)


def save(out):
    try:
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    smoke = args.smoke
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    t0 = time.time()

    if smoke:
        d, heads, seg, batch, steps, win, n_mem = 32, 4, 32, 8, 20, 16, 8
    else:
        d, heads, seg, batch, steps, win, n_mem = 256, 8, 512, 16, 2000, 256, 16
    layer_windows = [win, win, win, None, win, win, win, None]

    out = {"experiment": "xrmt", "device": device, "torch": torch.__version__,
           "cfg": {"d": d, "seg": seg, "batch": batch, "steps": steps, "n_mem": n_mem, "win": win}}
    print(f"[xrmt] {out['cfg']}", flush=True)
    text = get_text(smoke)
    arr = np.frombuffer(text.encode("utf-8", "ignore"), dtype=np.uint8)
    ids = torch.from_numpy(arr.copy()).long().to(device)
    n_val = min(len(ids) // 10, 300_000)
    ids_tr, ids_va = ids[:-n_val], ids[-n_val:]
    out["data_bytes"] = int(len(ids))
    save(out)

    def batch_pair(src, g):
        starts = torch.randint(0, len(src) - 2 * seg - 1, (batch,), generator=g, device=device)
        x = torch.stack([src[s:s + 2 * seg] for s in starts])
        y = torch.stack([src[s + 1:s + 2 * seg + 1] for s in starts])
        return x[:, :seg], y[:, :seg], x[:, seg:], y[:, seg:]

    @torch.no_grad()
    def eval_seg2(model, mode, n_batches=12):
        model.eval()
        g = torch.Generator(device=device)
        g.manual_seed(999)
        tot = 0.0
        for _ in range(n_batches):
            x1, y1, x2, y2 = batch_pair(ids_va, g)
            if device == "cuda":
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    _, nll2 = loss_two_segments(model, x1, y1, x2, y2, mode)
            else:
                _, nll2 = loss_two_segments(model, x1, y1, x2, y2, mode)
            tot += float(nll2)
        model.train()
        return round(tot / n_batches / math.log(2), 4)

    def over():
        return (time.time() - t0) / 60 > TIME_BUDGET_MIN

    ARMS = [("full1024", 0), ("seg_ciego", 0), ("seg_rmt", n_mem)]
    out["arms"] = {}
    for mode, m in ARMS:
        if over():
            out["arms"][mode] = {"skipped": "budget"}
            save(out)
            continue
        print(f"\n==== {mode} ====", flush=True)
        torch.manual_seed(0)
        model = RMTLM(256, d, heads, layer_windows, n_mem=m,
                      max_seq=2 * seg + 2 * max(1, m) + 8).to(device)
        use_amp = device == "cuda"
        opt = torch.optim.AdamW(model.parameters(), lr=6e-4, weight_decay=0.01, fused=use_amp or None)
        try:
            scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
        except (AttributeError, TypeError):
            scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
        g = torch.Generator(device=device)
        g.manual_seed(0)
        warmup = min(100, steps // 10)
        t1 = time.time()
        for step in range(1, steps + 1):
            if step <= warmup:
                for gr in opt.param_groups:
                    gr["lr"] = 6e-4 * step / warmup
            x1, y1, x2, y2 = batch_pair(ids_tr, g)
            if use_amp:
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    loss, _ = loss_two_segments(model, x1, y1, x2, y2, mode)
                opt.zero_grad(set_to_none=True)
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt)
                scaler.update()
            else:
                loss, _ = loss_two_segments(model, x1, y1, x2, y2, mode)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            if step % max(1, steps // 5) == 0 or step == steps:
                b2 = eval_seg2(model, mode)
                print(f"  step {step}/{steps} loss {float(loss):.3f} bpb_seg2 {b2:.4f}", flush=True)
        out["arms"][mode] = {"params": model.num_params(), "bpb_seg2": eval_seg2(model, mode, 24),
                             "wall_s": round(time.time() - t1, 1)}
        print(f"  FINAL bpb_seg2={out['arms'][mode]['bpb_seg2']}", flush=True)
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
        save(out)

    a = out["arms"].get("full1024", {}).get("bpb_seg2")
    b = out["arms"].get("seg_ciego", {}).get("bpb_seg2")
    c = out["arms"].get("seg_rmt", {}).get("bpb_seg2")
    if a and b and c and b > a:
        out["recovery_frac"] = round((b - c) / (b - a), 3)     # 1.0 = recupera todo el gap; <=0 = nada
        out["verdict_H_RMT"] = "PASA (>=0.30)" if out["recovery_frac"] >= 0.30 else "DESCARTADA (<0.30)"
        print(f"\n[xrmt] gap ciego-full={b - a:.4f} bpb; RMT recupera {out['recovery_frac']:.0%} -> "
              f"{out['verdict_H_RMT']}", flush=True)
    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    save(out)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
