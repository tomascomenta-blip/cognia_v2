r"""
M0 / GATE G2 — Fragilidad estructural de recall del backbone híbrido, A ESCALA.

PREGUNTA (00_READINESS / 11_plan_maestro): a la escala objetivo (no el toy d=24), ¿una config
HÍBRIDA (mayoría capas de estado fijo/lineal + minoría de atención) CRUZA el recall asociativo
con el MÍNIMO de atención, o necesita volverse atención-mayoritaria? Y: ¿el arreglo (lineal-primero
vs atención-primero) y la VENTANA (SWA local vs atención global) cambian el resultado?

POR QUÉ IMPORTA: el lab probó que el techo del mezclador de estado fijo es ESTRUCTURAL (pigeonhole
exp002; 6 levers no-atención refutados exp010-012; el híbrido naive platea ~0.18 a d chico exp014/015,
solo la atención pura cruza ~0.88-0.95 exp013) — PERO esto se midió en el TOY (d=24-64). G2 lo lleva a
la escala objetivo para FIJAR el ratio/arreglo/ventana del backbone v1 (o confirmar que hay que subir
la cuota de atención -> acerca a la RAMA B = GQA denso, que es atención plena).

ESTE ARCHIVO ES SELF-CONTAINED (embebe el modelo HybridLM + la tarea de recall): corre en una Google
Colab LIMPIA (tier gratuito, GPU T4) sin clonar nada ni instalar nada (torch ya viene en Colab).
También corre local en CPU para smoke:  venv312\Scripts\python.exe ...m0_g2_recall_colab.py --smoke

EN COLAB (T4 gratis): Runtime -> Change runtime type -> T4 GPU. Pegá este archivo en una celda (o subilo
y %run). Ejecutá. Al final imprime una tabla + un JSON que me devolvés para interpretar el veredicto G2.
"""
import argparse
import functools  # noqa: F401  (paridad con hybrid.py)
import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ───────────────────────── modelo HybridLM (fiel a cognia_x/model/hybrid.py, path elu) ──────────────


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
        n = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return n * self.w


class SwiGLU(nn.Module):
    def __init__(self, d, d_ff):
        super().__init__()
        self.w1 = nn.Linear(d, d_ff, bias=False)
        self.w2 = nn.Linear(d, d_ff, bias=False)
        self.w3 = nn.Linear(d_ff, d, bias=False)

    def forward(self, x):
        return self.w3(F.silu(self.w1(x)) * self.w2(x))


class LinearAttention(nn.Module):
    """Atención lineal causal (feature map elu+1). Estado fijo acotado — el componente cuyo recall
    es estructuralmente limitado (exp002). Forma paralela O(L^2) para entrenar = recurrente O(L) infer."""

    def __init__(self, d, n_heads):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos=None, sin=None):       # cos/sin ignorados (kernel positivo)
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = F.elu(q) + 1.0
        k = F.elu(k) + 1.0
        scores = torch.matmul(q, k.transpose(-1, -2))
        mask = torch.tril(torch.ones(L, L, device=x.device, dtype=torch.bool))
        scores = scores.masked_fill(~mask, 0.0)
        denom = scores.sum(-1, keepdim=True) + 1e-6
        out = torch.matmul(scores, v) / denom
        out = out.transpose(1, 2).reshape(B, L, D)
        return self.o(out)


class SlidingWindowAttention(nn.Module):
    """Atención softmax causal restringida a una ventana W (KV-cache O(W)). window>=L => global."""

    def __init__(self, d, n_heads, window):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos=None, sin=None):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        if cos is not None:
            q = apply_rope(q, cos, sin)
            k = apply_rope(k, cos, sin)
        scores = torch.matmul(q, k.transpose(-1, -2)) / math.sqrt(self.dh)
        idx = torch.arange(L, device=x.device)
        causal = idx[None, :] <= idx[:, None]
        windowed = idx[None, :] > (idx[:, None] - self.window)
        mask = causal & windowed
        scores = scores.masked_fill(~mask, float("-inf"))
        attn = F.softmax(scores, dim=-1)
        out = torch.matmul(attn, v)
        out = out.transpose(1, 2).reshape(B, L, D)
        return self.o(out)


class Block(nn.Module):
    def __init__(self, d_model, n_heads, d_ff, kind, window):
        super().__init__()
        self.kind = kind
        self.norm1 = RMSNorm(d_model)
        self.mixer = (SlidingWindowAttention(d_model, n_heads, window) if kind == "attn"
                      else LinearAttention(d_model, n_heads))
        self.norm2 = RMSNorm(d_model)
        self.mlp = SwiGLU(d_model, d_ff)

    def forward(self, x, cos=None, sin=None):
        x = x + self.mixer(self.norm1(x), cos, sin)
        x = x + self.mlp(self.norm2(x))
        return x


def build_layer_types(n_layers, attn_every, arrangement):
    """Devuelve la lista de tipos por capa. attn_every<=0 => todo lineal; ==1 => todo atención.
    arrangement controla DÓNDE caen las capas de atención (G2 testea si el arreglo importa)."""
    if attn_every <= 0:
        return ["linear"] * n_layers
    if attn_every == 1:
        return ["attn"] * n_layers
    linear_first = ["attn" if (i % attn_every == attn_every - 1) else "linear" for i in range(n_layers)]
    n_attn = linear_first.count("attn")
    if arrangement == "linear_first":   # default repo: atención al FINAL de cada grupo
        return linear_first
    if arrangement == "attn_first":     # atención al INICIO de cada grupo
        return ["attn" if (i % attn_every == 0) else "linear" for i in range(n_layers)]
    if arrangement == "front":          # todas las capas de atención adelante
        return ["attn"] * n_attn + ["linear"] * (n_layers - n_attn)
    if arrangement == "back":           # todas las capas de atención al final
        return ["linear"] * (n_layers - n_attn) + ["attn"] * n_attn
    return linear_first


class HybridLM(nn.Module):
    def __init__(self, vocab, d_model, n_heads, layer_types, window, max_seq_len, d_ff=None):
        super().__init__()
        d_ff = d_ff or max(16, int(round(8 * d_model / 3 / 16)) * 16)
        self.embed = nn.Embedding(vocab, d_model)
        self.blocks = nn.ModuleList([Block(d_model, n_heads, d_ff, t, window) for t in layer_types])
        self.dh = d_model // n_heads
        cos, sin = build_rope_cache(max_seq_len, self.dh, device="cpu")
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab, bias=False)
        self.lm_head.weight = self.embed.weight     # tied
        self.layer_types = layer_types
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        cos, sin = self.rope_cos[:L].to(x.dtype), self.rope_sin[:L].to(x.dtype)
        for b in self.blocks:
            x = b(x, cos, sin)
        x = self.norm_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-100)
        return logits, loss

    def num_params(self):
        n = sum(p.numel() for p in self.parameters())
        return n - self.embed.weight.numel()        # tied: contar una vez


# ───────────────────────── tarea de recall (fiel a cognia_x/train/recall_task.py) ──────────────────


def make_recall_batch(rng, batch, n_pairs, n_queries, n_keys, n_vals, device):
    KEY0, VAL0 = 1, 1 + n_keys
    seqs, tgts = [], []
    for _ in range(batch):
        keys = rng.choice(n_keys, size=n_pairs, replace=False)
        vals = rng.integers(0, n_vals, size=n_pairs)
        kv = {int(k): int(v) for k, v in zip(keys, vals)}
        seq, tgt = [], []
        for k, v in zip(keys, vals):
            seq += [KEY0 + int(k), VAL0 + int(v)]
            tgt += [-100, -100]
        for k in rng.choice(keys, size=n_queries, replace=True):
            seq.append(KEY0 + int(k))
            tgt.append(VAL0 + kv[int(k)])
        seqs.append(seq)
        tgts.append(tgt)
    x = torch.tensor(seqs, dtype=torch.long, device=device)
    y = torch.tensor(tgts, dtype=torch.long, device=device)
    return x, y


@torch.no_grad()
def eval_recall(model, rng, p, device, batches=20):
    model.eval()
    hits = total = 0
    for _ in range(batches):
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
        logits, _ = model(x)
        pred = logits.argmax(-1)
        m = y != -100
        hits += int((pred[m] == y[m]).sum())
        total += int(m.sum())
    model.train()
    return hits / max(1, total)


def train_one(name, attn_every, arrangement, window_frac, p, steps, warmup, device, seed, deadline, log,
              early_stop=0.97):
    rng = np.random.default_rng(seed)
    eval_rng = np.random.default_rng(seed + 10**6)
    torch.manual_seed(seed)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    chance = 1.0 / p["n_vals"]
    window = (L + 1) if window_frac >= 1.0 else max(2, int(round(window_frac * L)))
    layer_types = build_layer_types(p["n_layers"], attn_every, arrangement)
    n_attn = layer_types.count("attn")
    model = HybridLM(vocab, p["d_model"], p["n_heads"], layer_types, window, L + 1).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=p["lr"], weight_decay=0.01)
    attn_frac = n_attn / p["n_layers"]
    log(f"[{name}] params={model.num_params():,} L={L} capas={layer_types.count('linear')}lin/{n_attn}attn "
        f"({attn_frac:.0%} attn) arreglo={arrangement} window={window}{'(global)' if window > L else '(SWA)'} "
        f"azar={chance:.4f}")
    model.train()
    acc = 0.0
    for step in range(1, steps + 1):
        if warmup > 0 and step <= warmup:
            for g in opt.param_groups:
                g["lr"] = p["lr"] * step / warmup
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
        _, loss = model(x, y)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % max(1, steps // 12) == 0 or step == steps:
            acc = eval_recall(model, eval_rng, p, device, batches=12)
            log(f"[{name}] step {step}/{steps} loss {loss.item():.3f} acc {acc:.3f} (azar {chance:.4f})")
            if acc >= early_stop and step >= warmup:
                log(f"[{name}] early-stop step {step} (acc {acc:.3f})")
                break
        if deadline and time.time() > deadline and step >= warmup:
            log(f"[{name}] deadline en step {step}")
            break
    acc = eval_recall(model, eval_rng, p, device, batches=24)
    log(f"[{name}] FINAL acc {acc:.3f} (azar {chance:.4f}) attn_frac {attn_frac:.0%}")
    return {"name": name, "attn_every": attn_every, "arrangement": arrangement, "window": window,
            "window_global": window > L, "attn_layers": n_attn, "n_layers": p["n_layers"],
            "attn_frac": round(attn_frac, 3), "final_acc": round(acc, 4), "chance": round(chance, 4),
            "params": model.num_params()}


# ───────────────────────── el sweep G2 ──────────────────────────────────────────────────────────────


def sweep(p, steps, warmup, per_cfg_sec, device, seed, log):
    """3 ejes: (1) RATIO -> ¿mínima cuota de atención que cruza recall?; (2) ARREGLO; (3) VENTANA (SWA vs global)."""
    runs = []

    def run(name, ae, arr="linear_first", wf=1.0):
        dl = time.time() + per_cfg_sec
        try:
            r = train_one(name, ae, arr, wf, p, steps, warmup, device, seed, dl, log)
        except Exception as e:  # noqa: BLE001
            log(f"[{name}] ERROR {e!r}")
            r = {"name": name, "attn_every": ae, "arrangement": arr, "error": repr(e)}
        runs.append(r)
        _save(runs, p, steps)
        return r

    log("==== EJE 1: RATIO (arreglo=linear_first, ventana=global) — mínima cuota de atención que cruza ====")
    for ae in [0, 8, 6, 4, 3, 2, 1]:        # 0=todo lineal ... 1=todo atención
        run(f"ratio_ae{ae}", ae)

    log("==== EJE 2: ARREGLO (a attn_every=4, ventana=global) — ¿importa dónde caen las capas de atención? ====")
    for arr in ["attn_first", "front", "back"]:   # linear_first ya está como ratio_ae4
        run(f"arr_{arr}_ae4", 4, arr=arr)

    log("==== EJE 3: VENTANA (a attn_every=2, arreglo=linear_first) — ¿la SWA local basta o hace falta global? ====")
    run("win_swa25_ae2", 2, wf=0.25)         # ventana = 25% de L (SWA local)
    run("win_global_ae2", 2, wf=1.0)         # global (referencia)

    return runs


def _verdict(runs, recover=0.80):
    ok = [r for r in runs if isinstance(r.get("final_acc"), float)]
    ratio = sorted([r for r in ok if r["name"].startswith("ratio_")], key=lambda r: r["attn_frac"])
    crossing = [r for r in ratio if r["final_acc"] >= recover]
    min_attn = min((r["attn_frac"] for r in crossing), default=None)
    pure_lin = next((r for r in ratio if r["attn_every"] == 0), None)
    pure_attn = next((r for r in ratio if r["attn_every"] == 1), None)
    swa = next((r for r in ok if r["name"] == "win_swa25_ae2"), None)
    glob = next((r for r in ok if r["name"] == "win_global_ae2"), None)
    lines = []
    lines.append(f"recall objetivo = {recover}")
    if pure_lin:
        lines.append(f"lineal puro (0% attn): acc={pure_lin['final_acc']} (confirma/niega el techo estructural ~0.18)")
    if pure_attn:
        lines.append(f"atención pura (100% attn = RAMA B): acc={pure_attn['final_acc']}")
    if min_attn is not None:
        lines.append(f"MÍNIMA cuota de atención que cruza {recover}: {min_attn:.0%}  "
                     f"-> {'RAMA A viable (el híbrido cruza con minoría de atención)' if min_attn <= 0.34 else 'la cuota de atención necesaria es ALTA (>1/3) -> acerca a RAMA B (atención-mayoritaria/GQA denso)'}")
    else:
        lines.append(f"NINGUNA config híbrida cruzó {recover} -> el recall a esta escala exige atención plena (RAMA B)")
    if swa and glob:
        lines.append(f"VENTANA @ae2: SWA(25%L) acc={swa['final_acc']} vs global acc={glob['final_acc']} -> "
                     f"{'la SWA local BASTA para recall' if swa['final_acc'] >= 0.9 * glob['final_acc'] else 'el recall NECESITA atención GLOBAL (la SWA local no basta) -> las pocas capas de atención deben ser GLOBALES'}")
    return lines


_RESULTS_PATH = "g2_recall_results.json"


def _save(runs, p, steps):
    try:
        with open(_RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump({"experiment": "m0_g2_recall", "params": p, "steps": steps, "runs": runs}, f, indent=2)
    except Exception:  # noqa: BLE001
        pass


def main():
    ap = argparse.ArgumentParser(description="G2 — fragilidad de recall del híbrido a escala (Colab GPU / CPU smoke)")
    ap.add_argument("--smoke", action="store_true", help="tiny en CPU para verificar que corre")
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)

    if args.smoke:                  # tiny: verifica el pipeline sin GPU
        p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=64, n_vals=16, n_pairs=12, n_queries=8, batch=32, lr=1e-3)
        steps = args.steps or 60
        warmup, per_cfg = 10, 60.0
    else:                            # escala objetivo (Colab T4)
        p = dict(d_model=256, n_heads=8, n_layers=12, n_keys=512, n_vals=64, n_pairs=64, n_queries=16, batch=64, lr=1e-3)
        steps = args.steps or 6000
        warmup, per_cfg = 300, 420.0

    t0 = time.time()
    print(f"[g2] device={device} smoke={args.smoke} steps={steps} scale={p}", flush=True)

    def log(s):
        print(s, flush=True)

    runs = sweep(p, steps, warmup, per_cfg, device, args.seed, log)
    verdict = _verdict(runs)
    out = {"experiment": "m0_g2_recall", "device": device, "params": p, "steps": steps,
           "seed": args.seed, "runs": runs, "verdict": verdict, "minutes": round((time.time() - t0) / 60, 1)}
    _save_full(out)

    print("\n================== G2 - RESUMEN (recall por config) ==================", flush=True)
    print(f"{'config':>18} | {'attn%':>6} | {'arreglo':>12} | {'ventana':>8} | {'recall':>7}")
    print("-" * 64)
    for r in runs:
        if "final_acc" in r:
            print(f"{r['name']:>18} | {r['attn_frac']:>5.0%} | {r['arrangement']:>12} | "
                  f"{'global' if r['window_global'] else 'SWA':>8} | {r['final_acc']:>7.3f}")
    print("\n================== VEREDICTO G2 ==================")
    for line in verdict:
        print(" - " + line)
    print(f"\n[g2] tiempo total {out['minutes']} min. Resultados en {_RESULTS_PATH}")
    print("\n>>> COPIÁ Y DEVOLVÉ ESTE JSON para interpretar el veredicto G2:")
    print(json.dumps({"runs": runs, "verdict": verdict, "params": p, "minutes": out["minutes"]}, ensure_ascii=False))


def _save_full(out):
    try:
        with open(_RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
