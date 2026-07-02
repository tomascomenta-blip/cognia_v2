r"""
XFINAL — entreno DESDE CERO en T4 (fase final del goal OLMo/Chimera): la prueba e2e de que las
decisiones de diseño funcionan de punta a punta, no en componentes aislados.

ARQUITECTURA: se fija con las constantes ARCH_* de abajo SEGÚN los veredictos del A/B
(xarch_results.json) — no antes. Modelo byte-level (vocab 256) entrenado sobre es-wiki real,
NUNCA pesos de OLMo. Objetivo mínimo del goal: que empiece a formular oraciones coherentes.

Además valida a escala propia el hallazgo OLMo: colapso de PPL al extrapolar largo (512→1024/2048)
y si dynamic-NTK en eval lo recupera (en banded, las capas SWA son inmunes por construcción).

Salidas: xfinal_results.json (bpb train/val, extrapolación, MUESTRAS GENERADAS reales) +
xfinal_model.pt (pesos fp16, descargable).
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xfinal_kernel.py --smoke
"""
import argparse
import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

RESULTS_PATH = "xfinal_results.json"
MODEL_PATH = "xfinal_model.pt"
TIME_BUDGET_MIN = 55.0

# ── ARQUITECTURA GANADORA (fijar según xarch_results.json ANTES de pushear) ──
ARCH_D = 512
ARCH_HEADS = 8
ARCH_WINDOW = 256
ARCH_LAYER_WINDOWS = [ARCH_WINDOW, ARCH_WINDOW, ARCH_WINDOW, None,
                      ARCH_WINDOW, ARCH_WINDOW, ARCH_WINDOW, None,
                      ARCH_WINDOW, ARCH_WINDOW, ARCH_WINDOW, None]   # banded 3:1 (placeholder)
ARCH_LOOPS = 1
TRAIN_SEQ = 512
TRAIN_BATCH = 32
TRAIN_STEPS = 4000
LR = 6e-4
CORPUS_BYTES = 20_000_000


# ───────────────────────── modelo (idéntico a xarch_kernel.TinyLM + NTK en eval) ───────────────────


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

    def forward(self, x, cos, sin):
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
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        return self.o(out.transpose(1, 2).reshape(B, L, D))


class Block(nn.Module):
    def __init__(self, d, n_heads, d_ff, window=None):
        super().__init__()
        self.norm1 = RMSNorm(d)
        self.attn = Attn(d, n_heads, window)
        self.norm2 = RMSNorm(d)
        self.mlp = SwiGLU(d, d_ff)

    def forward(self, x, cos, sin):
        x = x + self.attn(self.norm1(x), cos, sin)
        x = x + self.mlp(self.norm2(x))
        return x


class FinalLM(nn.Module):
    def __init__(self, vocab, d, n_heads, layer_windows, loops=1, max_seq=4096, rope_base=10000.0):
        super().__init__()
        d_ff = max(16, int(round(8 * d / 3 / 16)) * 16)
        self.embed = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList([Block(d, n_heads, d_ff, w) for w in layer_windows])
        self.loops = loops
        self.dh = d // n_heads
        self.max_seq = max_seq
        self.set_rope(rope_base)
        self.norm_f = RMSNorm(d)
        self.lm_head = nn.Linear(d, vocab, bias=False)
        self.lm_head.weight = self.embed.weight
        self.apply(self._init)

    def set_rope(self, base):
        """Recalcula la tabla RoPE con otra base (dynamic-NTK en EVAL: base*factor^(dh/(dh-2)))."""
        cos, sin = build_rope_cache(self.max_seq, self.dh, device="cpu", base=base)
        self.register_buffer("rope_cos", cos.to(next(self.parameters()).device
                                                if list(self.parameters()) else "cpu"),
                             persistent=False)
        self.register_buffer("rope_sin", sin.to(self.rope_cos.device), persistent=False)

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        cos, sin = self.rope_cos[:L].to(x.dtype).to(x.device), self.rope_sin[:L].to(x.dtype).to(x.device)
        for _ in range(self.loops):
            for b in self.blocks:
                x = b(x, cos, sin)
        x = self.norm_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, n_new, temperature=0.8, top_k=40):
        self.eval()
        for _ in range(n_new):
            logits, _ = self(idx[:, -TRAIN_SEQ:])
            logits = logits[:, -1, :] / max(1e-6, temperature)
            if top_k:
                v, _ = torch.topk(logits, top_k)
                logits[logits < v[:, [-1]]] = float("-inf")
            probs = F.softmax(logits, dim=-1)
            nxt = torch.multinomial(probs, 1)
            idx = torch.cat([idx, nxt], dim=1)
        self.train()
        return idx

    def num_params(self):
        return sum(p.numel() for p in self.parameters()) - self.embed.weight.numel()


# ───────────────────────── datos / eval ─────────────────────────────────────────────────────────────


def get_text(smoke, target_bytes=CORPUS_BYTES):
    if smoke:
        return ("la casa es azul y el cielo se llena de nubes blancas cuando llueve. "
                "los gatos duermen al sol mientras los ninos juegan en el parque. " * 3000)
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
        print(f"[data] es-wiki: {total} bytes, {len(parts)} articulos", flush=True)
        return "\n\n".join(parts)
    except Exception as e:  # noqa: BLE001
        print(f"[data] es-wiki fallo ({e!r}) -> wikitext-103", flush=True)
        ds = load_dataset("wikitext", "wikitext-103-raw-v1", split="train")
        parts, total = [], 0
        for t in ds["text"]:
            if t.strip():
                parts.append(t)
                total += len(t)
            if total >= target_bytes:
                break
        return "\n".join(parts)


def to_ids(text, device):
    arr = np.frombuffer(text.encode("utf-8", "ignore"), dtype=np.uint8)
    return torch.from_numpy(arr.copy()).long().to(device)


@torch.no_grad()
def eval_bpb(model, ids, seq, device, n_windows=24):
    model.eval()
    use_amp = device == "cuda"
    nll = n = 0
    for i in range(n_windows):
        s = i * seq
        if s + seq + 1 > len(ids):
            break
        x = ids[s:s + seq].unsqueeze(0)
        y = ids[s + 1:s + seq + 1].unsqueeze(0)
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                _, loss = model(x, y)
        else:
            _, loss = model(x, y)
        nll += float(loss) * seq
        n += seq
    model.train()
    return round(nll / max(1, n) / math.log(2), 4)


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
        d, heads, seq, batch, steps = 32, 4, 64, 8, 30
        layer_windows, loops = [16, None], 1
        gen_len = 80
    else:
        d, heads, seq, batch, steps = ARCH_D, ARCH_HEADS, TRAIN_SEQ, TRAIN_BATCH, TRAIN_STEPS
        layer_windows, loops = ARCH_LAYER_WINDOWS, ARCH_LOOPS
        gen_len = 350

    out = {"experiment": "xfinal_scratch", "device": device, "torch": torch.__version__,
           "arch": {"d": d, "heads": heads, "layer_windows": [w if w else "global" for w in layer_windows],
                    "loops": loops, "seq": seq, "batch": batch, "steps": steps, "lr": LR}}
    print(f"[xfinal] {out['arch']}", flush=True)

    text = get_text(smoke)
    ids = to_ids(text, device)
    n_val = min(len(ids) // 20, 400_000)
    ids_tr, ids_va = ids[:-n_val], ids[-n_val:]
    out["data_bytes"] = int(len(ids))
    out["tokens_seen"] = steps * batch * seq
    print(f"[xfinal] corpus={len(ids)} bytes; tokens a ver={out['tokens_seen']:,}", flush=True)

    torch.manual_seed(0)
    model = FinalLM(256, d, heads, layer_windows, loops=loops).to(device)
    out["params"] = model.num_params()
    print(f"[xfinal] params={out['params']:,}", flush=True)
    use_amp = device == "cuda"
    if use_amp:
        try:
            model = torch.compile(model)
            print("[xfinal] compile ON", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[xfinal] compile OFF ({e!r})", flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01, fused=use_amp or None)
    try:
        scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    except (AttributeError, TypeError):
        scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
    g = torch.Generator(device=device)
    g.manual_seed(0)
    warmup = min(200, steps // 10)
    out["curve"] = []
    t_train = time.time()
    for step in range(1, steps + 1):
        if step <= warmup:
            for gr in opt.param_groups:
                gr["lr"] = LR * step / warmup
        starts = torch.randint(0, len(ids_tr) - seq - 1, (batch,), generator=g, device=device)
        x = torch.stack([ids_tr[s:s + seq] for s in starts])
        y = torch.stack([ids_tr[s + 1:s + seq + 1] for s in starts])
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
        else:
            _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        if step % max(1, steps // 10) == 0 or step == steps:
            bpb = eval_bpb(model, ids_va, seq, device)
            tps = round(step * batch * seq / (time.time() - t_train))
            out["curve"].append({"step": step, "loss": round(float(loss), 4), "val_bpb": bpb,
                                 "tok_per_s": tps})
            print(f"  step {step}/{steps} loss {float(loss):.3f} val_bpb {bpb:.3f} ({tps} tok/s)",
                  flush=True)
            save(out)
        if (time.time() - t0) / 60 > TIME_BUDGET_MIN:
            print("[xfinal] BUDGET — corto entreno", flush=True)
            break

    # ── extrapolación de largo + NTK en eval (validación a escala propia del hallazgo OLMo) ──
    out["extrapolation"] = {"bpb_512": eval_bpb(model, ids_va, seq, device),
                            "bpb_1024": eval_bpb(model, ids_va, seq * 2, device, n_windows=12)}
    base_model = getattr(model, "_orig_mod", model)
    base_model.set_rope(10000.0 * (2.0 ** (base_model.dh / max(1, base_model.dh - 2))))
    out["extrapolation"]["bpb_1024_ntk2"] = eval_bpb(model, ids_va, seq * 2, device, n_windows=12)
    base_model.set_rope(10000.0)
    print(f"[xfinal] extrapolación: {out['extrapolation']}", flush=True)
    save(out)

    # ── MUESTRAS GENERADAS (la prueba de oraciones coherentes) ──
    prompts = ["La historia de ", "El sol es ", "Los animales del bosque ",
               "En la ciudad de Madrid ", "La ciencia estudia "]
    out["samples"] = []
    for p in prompts:
        x = to_ids(p, device).unsqueeze(0)
        for temp in (0.7,):
            y = base_model.generate(x.clone(), gen_len, temperature=temp)
            txt = bytes(int(t) % 256 for t in y[0].tolist()).decode("utf-8", "ignore")
            out["samples"].append({"prompt": p, "temp": temp, "text": txt})
            try:
                print(f"\n--- muestra (t={temp}) ---\n{txt}\n", flush=True)
            except UnicodeEncodeError:      # consola Windows cp1252 en el smoke; el JSON guarda el real
                print(f"\n--- muestra (t={temp}) ---\n{ascii(txt)}\n", flush=True)
    save(out)

    try:
        sd = {k: v.half().cpu() for k, v in base_model.state_dict().items()}
        torch.save(sd, MODEL_PATH)
        print(f"[xfinal] pesos -> {MODEL_PATH}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[xfinal] no se pudo guardar el modelo: {e!r}", flush=True)

    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    save(out)
    print(f"[xfinal] LISTO en {out['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()
