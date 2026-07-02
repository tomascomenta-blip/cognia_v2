r"""
XH-FINAL (K3) — LA corrida: ~110M params hasta "estado funcional" en ≤30 min de T4, con la
receta ganadora de K2 y los gates PRE-REGISTRADOS de 00_DISENO.md §3 (+ desvío D1 de 01_DESVIOS.md):

  G1  val bpb wiki ≤ 1.35 (stretch ≤1.25; falsación dura >1.45). bpb = CE×(tok/byte)/ln2.
  G2  ≥7/10 muestras coherentes (checklist manual post-hoc; acá se generan las 10 congeladas).
  G3  distinct-2 ≥0.60 y distinct-3 ≥0.75 promedio; ninguna muestra con 4-grama repetida ≥4×.
  G4  mini-cloze-es (40 ítems×3 opciones, azar 33.3%) ≥65% — el precedente 37.7M midió 62.5%.

Contabilidad HONESTA del wall (nada se esconde): setup+datos / compile (step 1) / train /
batería de evals. El gate de 30 min es sobre compile+train+evals (la preparación de datos es
one-time en cognia-xh-data, pre-registrado). CONSTANTES AJUSTAR SEGÚN xh_ablate_results.json
ANTES DE PUSHEAR (patrón xfinal). Salidas: xh_final_results.json + xh_model.pt (fp16).
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_final_kernel.py --smoke
"""
import argparse
import gc
import json
import math
import os
import time

os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")  # anti-fragmentación T4

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

RESULTS_PATH = "xh_final_results.json"
MODEL_PATH = "xh_model.pt"
_DATA_DIR_CACHE = []


def find_data_dir():
    if _DATA_DIR_CACHE:
        return _DATA_DIR_CACHE[0]
    base = "/kaggle/input"
    try:
        print(f"[data] /kaggle/input: {os.listdir(base)}", flush=True)
    except OSError:
        pass
    for root, _dirs, files in os.walk(base):
        if "xh_data_meta.json" in files:
            _DATA_DIR_CACHE.append(root)
            return root
    raise FileNotFoundError("xh_data_meta.json no está bajo /kaggle/input")


# ── RECETA GANADORA (fijar según xh_ablate_results.json ANTES de pushear) ──
ARCH_D = 768
ARCH_HEADS = 12
ARCH_LAYERS = 12
ARCH_WINDOW = 256
GLOBAL_LAYERS = (3, 7, 11)
SEQ = 512
BATCH = 48                       # <- confirmar con bench/ablate
OPTIMIZER = "muon"               # "muon" | "adamw_ctl"  <- según brazo ganador
MUON_LR = 0.02
ADAMW_LR = 3e-3
DATA_KIND = "mix"                # "mix" | "wiki" | "16k" | "bytes"  <- según brazos D/E/G
ATTN_MODE = "mask"               # "mask" | "chunked"  <- según brazo H (con gate extrapolación)
ZLOSS = 1e-4
WARMUP_STEPS = 200
EMA_DECAY = 0.998
TRAIN_WALL_S = 1500.0            # 25 min de train puro
TIME_BUDGET_MIN = 45.0           # tope duro del kernel (colchón sobre los 30)

G2_PROMPTS = [                   # congelados en 01_DESVIOS.md D2 (5 precedente + 5 nuevos)
    "La historia de ", "El sol es ", "Los animales del bosque ",
    "En la ciudad de Madrid ", "La ciencia estudia ",
    "Había una vez un niño que ", "Un día, la pequeña Sofía encontró ",
    "El agua es una sustancia que ", "Los planetas del sistema solar ",
    "Desde la ventana de mi casa se puede ver ",
]

CLOZE_ES = [                     # batería CONGELADA (xh_cloze_es.py; baseline 37.7M = 62.5%)
    {"cat": "concordancia", "prompt": "Las casas del pueblo son", "opts": [" blancas", " blanca", " blanco"], "ans": 0},
    {"cat": "concordancia", "prompt": "El niño está muy", "opts": [" cansado", " cansada", " cansadas"], "ans": 0},
    {"cat": "concordancia", "prompt": "Los libros están sobre la", "opts": [" mesa", " mesas", " meso"], "ans": 0},
    {"cat": "concordancia", "prompt": "María es una mujer muy", "opts": [" inteligente", " inteligentes", " inteligento"], "ans": 0},
    {"cat": "concordancia", "prompt": "Nosotros", "opts": [" somos amigos", " sois amigos", " soy amigos"], "ans": 0},
    {"cat": "concordancia", "prompt": "Ellos", "opts": [" tienen dinero", " tiene dinero", " tengo dinero"], "ans": 0},
    {"cat": "concordancia", "prompt": "Yo", "opts": [" tengo hambre", " tienes hambre", " tiene hambre"], "ans": 0},
    {"cat": "concordancia", "prompt": "El agua del lago está muy", "opts": [" fría", " frío", " fríos"], "ans": 0},
    {"cat": "concordancia", "prompt": "Es un problema muy", "opts": [" difícil", " difícila", " difíciles"], "ans": 0},
    {"cat": "concordancia", "prompt": "Las flores del jardín son", "opts": [" hermosas", " hermosos", " hermosa"], "ans": 0},
    {"cat": "concordancia", "prompt": "Mi hermano y yo", "opts": [" vamos al parque", " van al parque", " va al parque"], "ans": 0},
    {"cat": "concordancia", "prompt": "Ayer por la tarde", "opts": [" fuimos al cine", " iremos al cine", " vamos a ir al cine"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La capital de Francia es", "opts": [" París", " Madrid", " Roma"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La capital de España es", "opts": [" Madrid", " Barcelona", " Lisboa"], "ans": 0},
    {"cat": "conocimiento", "prompt": "El sol sale por el", "opts": [" este", " oeste", " norte"], "ans": 0},
    {"cat": "conocimiento", "prompt": "El agua hierve a cien", "opts": [" grados", " metros", " litros"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La Tierra gira alrededor del", "opts": [" Sol", " mar", " viento"], "ans": 0},
    {"cat": "conocimiento", "prompt": "El océano más grande del mundo es el", "opts": [" Pacífico", " Atlántico", " Índico"], "ans": 0},
    {"cat": "conocimiento", "prompt": "Cervantes escribió Don", "opts": [" Quijote", " Juan", " Pedro"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La Segunda Guerra Mundial terminó en", "opts": [" 1945", " 1918", " 1989"], "ans": 0},
    {"cat": "conocimiento", "prompt": "El río más largo de Sudamérica es el", "opts": [" Amazonas", " Nilo", " Danubio"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La moneda de Estados Unidos es el", "opts": [" dólar", " euro", " peso"], "ans": 0},
    {"cat": "conocimiento", "prompt": "Los seres humanos respiran", "opts": [" oxígeno", " helio", " carbono"], "ans": 0},
    {"cat": "conocimiento", "prompt": "La fotosíntesis la realizan las", "opts": [" plantas", " piedras", " nubes"], "ans": 0},
    {"cat": "semantica", "prompt": "El hielo es muy", "opts": [" frío", " caliente", " ruidoso"], "ans": 0},
    {"cat": "semantica", "prompt": "Por la noche se puede ver la", "opts": [" luna", " playa", " lluvia"], "ans": 0},
    {"cat": "semantica", "prompt": "El fuego produce calor y", "opts": [" luz", " hielo", " silencio"], "ans": 0},
    {"cat": "semantica", "prompt": "Los pájaros vuelan por el", "opts": [" cielo", " mar", " subsuelo"], "ans": 0},
    {"cat": "semantica", "prompt": "En invierno hace mucho", "opts": [" frío", " calor", " ruido"], "ans": 0},
    {"cat": "semantica", "prompt": "Los peces viven en el", "opts": [" agua", " aire", " fuego"], "ans": 0},
    {"cat": "semantica", "prompt": "Para escribir se usa un", "opts": [" lápiz", " zapato", " plato"], "ans": 0},
    {"cat": "semantica", "prompt": "El bebé llora porque tiene", "opts": [" hambre", " biblioteca", " montaña"], "ans": 0},
    {"cat": "semantica", "prompt": "La lluvia cae desde las", "opts": [" nubes", " raíces", " piedras"], "ans": 0},
    {"cat": "semantica", "prompt": "El médico trabaja en el", "opts": [" hospital", " bosque", " océano"], "ans": 0},
    {"cat": "sintaxis", "prompt": "Todos los días voy", "opts": [" a la escuela", " en la escuela", " de la escuela"], "ans": 0},
    {"cat": "sintaxis", "prompt": "El libro está encima", "opts": [" de la mesa", " a la mesa", " por la mesa"], "ans": 0},
    {"cat": "sintaxis", "prompt": "Yo soy", "opts": [" de Madrid", " a Madrid", " por Madrid"], "ans": 0},
    {"cat": "sintaxis", "prompt": "Estoy pensando", "opts": [" en ti", " de ti", " a ti"], "ans": 0},
    {"cat": "sintaxis", "prompt": "La decisión depende", "opts": [" de ti", " a ti", " en ti"], "ans": 0},
    {"cat": "sintaxis", "prompt": "Gracias", "opts": [" por tu ayuda", " de tu ayuda", " a tu ayuda"], "ans": 0},
]


# ───────────────────────── modelo/optim (canónicos de xh_ablate_kernel) ─────────────────────────


def build_rope_cache(seq_len, dh, base=10000.0):
    half = dh // 2
    inv_freq = 1.0 / (base ** (torch.arange(0, half).float() / half))
    pos = torch.arange(seq_len).float()
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


def chunked_swa(q, k, v, w):
    B, h, L, dh = q.shape
    nb = L // w
    qb = q.view(B, h, nb, w, dh).transpose(1, 2).reshape(B * nb, h, w, dh)
    kb = k.view(B, h, nb, w, dh)
    vb = v.view(B, h, nb, w, dh)
    kprev = torch.cat([torch.zeros_like(kb[:, :, :1]), kb[:, :, :-1]], dim=2)
    vprev = torch.cat([torch.zeros_like(vb[:, :, :1]), vb[:, :, :-1]], dim=2)
    kk = torch.cat([kprev, kb], dim=3).transpose(1, 2).reshape(B * nb, h, 2 * w, dh)
    vv = torch.cat([vprev, vb], dim=3).transpose(1, 2).reshape(B * nb, h, 2 * w, dh)
    i = torch.arange(w, device=q.device)
    m = torch.arange(2 * w, device=q.device)
    base = (m[None, :] > i[:, None]) & (m[None, :] <= w + i[:, None])
    m0 = base & (m[None, :] >= w)
    mask = torch.stack([m0] + [base] * (nb - 1)).repeat(B, 1, 1)
    out = F.scaled_dot_product_attention(qb, kk, vv, attn_mask=mask[:, None, :, :])
    return out.view(B, nb, h, w, dh).transpose(1, 2).reshape(B, h, L, dh)


class Attn(nn.Module):
    def __init__(self, d, n_heads, window=None, attn_mode="mask"):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.attn_mode = attn_mode
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)
        self.q_norm = RMSNorm(self.dh)
        self.k_norm = RMSNorm(self.dh)

    def forward(self, x, cos, sin, mask):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = apply_rope(self.q_norm(q), cos, sin)
        k = apply_rope(self.k_norm(k), cos, sin)
        if (self.window is not None and self.attn_mode == "chunked"
                and L % self.window == 0 and L > self.window):
            out = chunked_swa(q, k, v, self.window)
        elif mask is None:
            out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        else:
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        return self.o(out.transpose(1, 2).reshape(B, L, D))


class Block(nn.Module):
    def __init__(self, d, n_heads, d_ff, window=None, attn_mode="mask"):
        super().__init__()
        self.norm1 = RMSNorm(d)
        self.attn = Attn(d, n_heads, window, attn_mode)
        self.norm2 = RMSNorm(d)
        self.mlp = SwiGLU(d, d_ff)

    def forward(self, x, cos, sin, mask):
        x = x + self.attn(self.norm1(x), cos, sin, mask)
        x = x + self.mlp(self.norm2(x))
        return x


class XHLM(nn.Module):
    def __init__(self, vocab, d=ARCH_D, n_heads=ARCH_HEADS, n_layers=ARCH_LAYERS,
                 window=ARCH_WINDOW, global_layers=GLOBAL_LAYERS, d_ff=None,
                 attn_mode="mask", max_seq=2048):
        super().__init__()
        d_ff = d_ff or max(64, int(round(8 * d / 3 / 64)) * 64)
        windows = [None if i in global_layers else window for i in range(n_layers)]
        self.embed = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList([Block(d, n_heads, d_ff, w, attn_mode) for w in windows])
        self.layer_windows = windows
        self.attn_mode = attn_mode
        self.dh = d // n_heads
        self.max_seq = max_seq
        cos, sin = build_rope_cache(max_seq, self.dh)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d)
        self.lm_head = nn.Linear(d, vocab, bias=False)
        self.lm_head.weight = self.embed.weight
        self.apply(self._init)
        for b in self.blocks:
            nn.init.zeros_(b.attn.o.weight)
            nn.init.zeros_(b.mlp.w3.weight)
        for w in sorted({w for w in windows if w is not None}):
            idx = torch.arange(max_seq)
            m = (idx[None, :] <= idx[:, None]) & (idx[None, :] > (idx[:, None] - w))
            self.register_buffer(f"mask_{w}", m, persistent=False)

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def set_rope_base(self, base):
        cos, sin = build_rope_cache(self.max_seq, self.dh, base=base)
        self.rope_cos.copy_(cos.to(self.rope_cos.device))
        self.rope_sin.copy_(sin.to(self.rope_sin.device))

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        cos = self.rope_cos[:L].to(x.dtype)
        sin = self.rope_sin[:L].to(x.dtype)
        for b, w in zip(self.blocks, self.layer_windows):
            use_mask = (w is not None and w < L and self.attn_mode == "mask")
            mask = getattr(self, f"mask_{w}")[:L, :L] if use_mask else None
            x = b(x, cos, sin, mask)
        x = self.norm_f(x)
        if targets is None:
            return self.lm_head(x), None, None
        xf = x.reshape(-1, x.shape[-1])
        tf = targets.reshape(-1)
        n = xf.shape[0]
        ce = xf.new_zeros((), dtype=torch.float32)
        zl = xf.new_zeros((), dtype=torch.float32)
        for i in range(4):
            # checkpoint: sin él los 4 chunks de logits fp32 viven hasta el backward (OOM K1 v2)
            sl = slice(i * n // 4, (i + 1) * n // 4)
            if self.training and torch.is_grad_enabled():
                ce_i, zl_i = checkpoint(self._ce_chunk, xf[sl], tf[sl], use_reentrant=False)
            else:
                ce_i, zl_i = self._ce_chunk(xf[sl], tf[sl])
            ce = ce + ce_i
            zl = zl + zl_i
        ce = ce / n
        return None, ce, ce + ZLOSS * (zl / n)

    def _ce_chunk(self, xc, tc):
        lg = self.lm_head(xc).float()
        return (F.cross_entropy(lg, tc, reduction="sum"),
                (torch.logsumexp(lg, dim=-1) ** 2).sum())

    @torch.no_grad()
    def generate(self, idx, n_new, temperature=0.8, top_p=0.95, eos_id=None):
        self.eval()
        for _ in range(n_new):
            logits, _, _ = self(idx[:, -SEQ:])
            logits = logits[:, -1, :].float() / max(1e-6, temperature)
            probs = F.softmax(logits, dim=-1)
            sp, si = torch.sort(probs, descending=True)
            keep = (sp.cumsum(-1) - sp) <= top_p
            keep[..., 0] = True
            sp = sp * keep
            nxt = si.gather(-1, torch.multinomial(sp / sp.sum(-1, keepdim=True), 1))
            idx = torch.cat([idx, nxt], dim=1)
            if eos_id is not None and int(nxt[0, 0]) == eos_id:
                break
        self.train()
        return idx

    def num_params(self):
        total = sum(p.numel() for p in self.parameters())
        return total, total - self.embed.weight.numel()


@torch.no_grad()
def ns5(G, steps=5, eps=1e-7, dtype=torch.float16):
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.to(dtype)
    X = X / (X.norm() + eps)
    transposed = X.size(0) > X.size(1)
    if transposed:
        X = X.mT
    for _ in range(steps):
        A = X @ X.mT
        B = b * A + c * A @ A
        X = a * X + B @ X
    if transposed:
        X = X.mT
    return X


class Muon(torch.optim.Optimizer):
    def __init__(self, params, lr=MUON_LR, momentum=0.95, nesterov=True,
                 weight_decay=0.0, ns_dtype=torch.float16):
        super().__init__(params, dict(lr=lr, momentum=momentum, nesterov=nesterov,
                                      weight_decay=weight_decay))
        self.ns_dtype = ns_dtype

    @torch.no_grad()
    def step(self, closure=None):
        for group in self.param_groups:
            lr, mu, wd = group["lr"], group["momentum"], group["weight_decay"]
            for p in group["params"]:
                if p.grad is None:
                    continue
                g = p.grad
                st = self.state[p]
                if "buf" not in st:
                    st["buf"] = torch.zeros_like(g, dtype=torch.float32)
                buf = st["buf"]
                buf.mul_(mu).add_(g)
                gg = g.add(buf, alpha=mu) if group["nesterov"] else buf
                O = ns5(gg.reshape(gg.size(0), -1), dtype=self.ns_dtype).reshape_as(gg).to(p.dtype)
                if wd:
                    p.mul_(1 - lr * wd)
                p.add_(O, alpha=-lr * max(1, p.size(0) / p.size(1)) ** 0.5)


def make_optimizers(model, device):
    fused = device == "cuda"
    if OPTIMIZER == "adamw_ctl":
        opt = torch.optim.AdamW(model.parameters(), lr=1.5e-3, betas=(0.9, 0.95),
                                weight_decay=0.1, fused=fused or None)
        return [opt], [1.5e-3]
    body2d, emb, oned = [], [], []
    for n, p in model.named_parameters():
        if "embed" in n or "lm_head" in n:
            emb.append(p)
        elif p.ndim >= 2:
            body2d.append(p)
        else:
            oned.append(p)
    muon = Muon(body2d, lr=MUON_LR, momentum=0.95, weight_decay=0.0)
    adamw = torch.optim.AdamW(
        [{"params": emb, "weight_decay": 0.01}, {"params": oned, "weight_decay": 0.0}],
        lr=ADAMW_LR, betas=(0.9, 0.95), fused=fused or None)
    return [muon, adamw], [MUON_LR, ADAMW_LR]


def lr_factor(step, progress):
    if step <= WARMUP_STEPS:
        return step / WARMUP_STEPS
    if progress >= 0.8:
        return max(0.0, (1.0 - progress) / 0.2)
    return 1.0


def set_lrs(opts, base_lrs, factor):
    for opt, base in zip(opts, base_lrs):
        for gr in opt.param_groups:
            gr["lr"] = base * factor


def load_data(device, smoke):
    if smoke:
        g = torch.Generator().manual_seed(0)
        tr = torch.randint(1, 500, (300_000,), generator=g).to(torch.int32).to(device)
        va = torch.randint(1, 500, (30_000,), generator=g).to(torch.int32).to(device)
        return tr, va, va, 500, 1.0, 1.0, None, 0
    data_dir = find_data_dir()
    meta = json.loads(open(f"{data_dir}/xh_data_meta.json", encoding="utf-8").read())
    if DATA_KIND == "bytes":
        tr = np.fromfile(f"{data_dir}/train_bytes.bin", dtype=np.uint8)
        vw = np.frombuffer(open(f"{data_dir}/val_wiki.txt", encoding="utf-8").read()
                           .encode("utf-8"), dtype=np.uint8)
        vs = np.frombuffer(open(f"{data_dir}/val_stories.txt", encoding="utf-8").read()
                           .encode("utf-8"), dtype=np.uint8)
        return (torch.from_numpy(tr.astype(np.int32)).to(device),
                torch.from_numpy(vw.astype(np.int32).copy()).to(device),
                torch.from_numpy(vs.astype(np.int32).copy()).to(device),
                256, 1.0, 1.0, None, 0)
    tag = "16k" if DATA_KIND == "16k" else "32k"
    fn = f"train_wiki_{tag}.bin" if DATA_KIND == "wiki" else f"train_mix_{tag}.bin"
    m = meta["vocabs"][tag]
    tr = np.fromfile(f"{data_dir}/{fn}", dtype=np.uint16)
    vw = np.fromfile(f"{data_dir}/val_wiki_{tag}.bin", dtype=np.uint16)
    vs = np.fromfile(f"{data_dir}/val_stories_{tag}.bin", dtype=np.uint16)
    return (torch.from_numpy(tr.astype(np.int32)).to(device),
            torch.from_numpy(vw.astype(np.int32)).to(device),
            torch.from_numpy(vs.astype(np.int32)).to(device),
            m["vocab_size"], m["val_wiki_tokens"] / meta["val_wiki_bytes"],
            m["val_stories_tokens"] / meta["val_stories_bytes"],
            f"{data_dir}/tokenizer_{tag}.json", m["eos_id"])


@torch.no_grad()
def eval_bpb(model, va, seq, tokens_per_byte, device, n_windows=48, eval_batch=8):
    model.eval()
    nll, n = 0.0, 0
    for s in range(0, n_windows, eval_batch):
        k = min(eval_batch, n_windows - s)
        idx = (torch.arange(k, device=device)[:, None] * seq
               + torch.arange(seq, device=device)[None, :]) + s * seq
        if int(idx.max()) + 1 >= len(va):
            break
        x, y = va[idx].long(), va[idx + 1].long()
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
            _, ce, _ = model(x, y)
        nll += float(ce) * k * seq
        n += k * seq
    model.train()
    return round(nll / n * tokens_per_byte / math.log(2), 4) if n else None


def distinct_n(ids, n=2):
    if len(ids) < n + 1:
        return 0.0
    grams = [tuple(ids[i:i + n]) for i in range(len(ids) - n + 1)]
    return round(len(set(grams)) / len(grams), 3)


def max_ngram_repeat(ids, n=4):
    from collections import Counter
    if len(ids) < n:
        return 0
    return max(Counter(tuple(ids[i:i + n]) for i in range(len(ids) - n + 1)).values())


@torch.no_grad()
def cloze_score(model, tok, device):
    """NLL media por token de cada opción; prefijo común por si el BPE fusiona en la frontera."""
    model.eval()
    per_cat, correct = {}, 0
    for item in CLOZE_ES:
        nlls = []
        pid = tok.encode(item["prompt"]).ids
        for opt in item["opts"]:
            fid = tok.encode(item["prompt"] + opt).ids
            k = 0
            while k < min(len(pid), len(fid)) and pid[k] == fid[k]:
                k += 1
            k = max(1, k)
            x = torch.tensor([fid], dtype=torch.long, device=device)
            logits, _, _ = model(x[:, :-1])
            logp = F.log_softmax(logits[0].float(), dim=-1)
            tgt = x[0, 1:]
            span = logp[k - 1:, :].gather(1, tgt[k - 1:, None])
            nlls.append(-float(span.mean()))
        ok = min(range(len(nlls)), key=lambda i: nlls[i]) == item["ans"]
        correct += ok
        c = per_cat.setdefault(item["cat"], [0, 0])
        c[0] += ok
        c[1] += 1
    model.train()
    out = {"total": round(correct / len(CLOZE_ES), 4), "n": len(CLOZE_ES)}
    for cat, (k, n) in per_cat.items():
        out[cat] = round(k / n, 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    smoke = args.smoke
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    torch.backends.cudnn.benchmark = True
    t_start = time.time()
    out = {"experiment": "xh_final", "device": device, "torch": torch.__version__,
           "receta": {"d": ARCH_D, "layers": ARCH_LAYERS, "heads": ARCH_HEADS,
                      "window": ARCH_WINDOW, "globals": list(GLOBAL_LAYERS), "seq": SEQ,
                      "batch": BATCH, "opt": OPTIMIZER, "muon_lr": MUON_LR,
                      "adamw_lr": ADAMW_LR, "data": DATA_KIND, "attn": ATTN_MODE,
                      "warmup": WARMUP_STEPS, "ema": EMA_DECAY,
                      "train_wall_s": TRAIN_WALL_S}, "wall": {}}

    tr, vw, vs, vocab, tpb_w, tpb_s, tok_path, eos_id = load_data(device, smoke)
    torch.manual_seed(0)
    if smoke:
        model = XHLM(vocab, d=64, n_heads=4, n_layers=2, global_layers=(1,))
    else:
        model = XHLM(vocab, attn_mode=ATTN_MODE)
    model = model.to(device)
    base = model
    total, nonemb = model.num_params()
    out["params_total"], out["params_nonemb"] = total, nonemb
    li = math.log(vocab)
    print(f"[xh-final] params={total / 1e6:.1f}M (nonemb {nonemb / 1e6:.1f}M) vocab={vocab} "
          f"ln(V)={li:.2f}", flush=True)
    if not smoke:
        model = torch.compile(model, mode="default", fullgraph=False, dynamic=False)
    opts, base_lrs = make_optimizers(model, device)
    scaler = torch.amp.GradScaler(device, enabled=device == "cuda")
    g = torch.Generator(device=device)
    g.manual_seed(0)
    batch = 8 if smoke else BATCH
    seq = 64 if smoke else SEQ
    wall = 10.0 if smoke else TRAIN_WALL_S
    arange = torch.arange(seq, device=device, dtype=torch.int32)
    out["wall"]["setup_s"] = round(time.time() - t_start, 1)

    ema = [p.detach().clone() for p in base.parameters()]
    lawa_snaps = []
    lawa_marks = [0.60, 0.70, 0.80, 0.90]
    out["curve"] = []
    skips = 0
    t0 = time.time()
    next_eval = 120.0 if not smoke else 4.0
    step, tokens_seen = 0, 0
    while (time.time() - t0) < wall:
        step += 1
        progress = (time.time() - t0) / wall
        set_lrs(opts, base_lrs, lr_factor(step, progress))
        starts = torch.randint(0, len(tr) - seq - 1, (batch,), generator=g,
                               device=device, dtype=torch.int32)
        idx = starts[:, None] + arange[None, :]
        x, y = tr[idx].long(), tr[idx + 1].long()
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
            _, ce, tot = model(x, y)
        for o in opts:
            o.zero_grad(set_to_none=True)
        scale_before = scaler.get_scale() if scaler.is_enabled() else 1.0
        scaler.scale(tot).backward()
        for o in opts:
            scaler.unscale_(o)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        for o in opts:
            scaler.step(o)
        scaler.update()
        if scaler.is_enabled() and scaler.get_scale() < scale_before:
            skips += 1
        if step == 1:
            out["wall"]["compile_first_step_s"] = round(time.time() - t0, 1)
            print(f"[xh-final] step1 (compile) {out['wall']['compile_first_step_s']}s "
                  f"loss={float(ce.detach()):.3f} (esperado ~{li:.1f})", flush=True)
        if step > WARMUP_STEPS:
            with torch.no_grad():
                torch._foreach_lerp_(ema, [p.detach() for p in base.parameters()],
                                     1 - EMA_DECAY)
        if lawa_marks and progress >= lawa_marks[0]:
            lawa_marks.pop(0)
            lawa_snaps.append([p.detach().to("cpu", copy=True) for p in base.parameters()])
        tokens_seen += batch * seq
        lf = float(ce.detach())
        if not math.isfinite(lf):
            out["died"] = {"step": step, "loss": lf}
            print(f"[xh-final] NaN/inf en step {step} — ABORTO honesto", flush=True)
            break
        if (time.time() - t0) >= next_eval:
            next_eval += 120.0 if not smoke else 4.0
            bpb = eval_bpb(base, vw, seq, tpb_w, device, n_windows=24)
            out["curve"].append({"s": round(time.time() - t0), "step": step,
                                 "loss": round(lf, 4), "bpb_wiki": bpb,
                                 "tokens_seen": tokens_seen})
            print(f"  {out['curve'][-1]}", flush=True)
            with open(RESULTS_PATH, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2, ensure_ascii=False)

    out["wall"]["train_s"] = round(time.time() - t0, 1)
    out["steps"] = step
    out["tokens_seen"] = tokens_seen
    out["tok_per_s"] = round(tokens_seen / max(1e-9, out["wall"]["train_s"]))
    out["scaler_skips"] = skips
    out["tok_per_param"] = round(tokens_seen / max(1, total), 3)
    print(f"[xh-final] train: {step} steps, {tokens_seen:,} tokens "
          f"({out['tok_per_s']:,} tok/s, {out['tok_per_param']} tok/param)", flush=True)

    # ── batería de gates (con last vs EMA vs LAWA; se elige por bpb wiki y se DECLARA) ──
    t_ev = time.time()
    cand = {"last": None}
    cand["last"] = eval_bpb(base, vw, seq, tpb_w, device)
    ema_bpb = None
    with torch.no_grad():
        saved = [p.detach().clone() for p in base.parameters()]
        for p, q in zip(base.parameters(), ema):
            p.copy_(q)
    ema_bpb = eval_bpb(base, vw, seq, tpb_w, device)
    cand["ema"] = ema_bpb
    lawa_bpb = None
    if lawa_snaps:
        snaps = lawa_snaps + [[t.cpu() for t in saved]]
        avg = [torch.stack([s[i].float() for s in snaps]).mean(0).to(device)
               for i in range(len(snaps[0]))]
        with torch.no_grad():
            for p, q in zip(base.parameters(), avg):
                p.copy_(q)
        lawa_bpb = eval_bpb(base, vw, seq, tpb_w, device)
        cand["lawa"] = lawa_bpb
    best = min((k for k in cand if cand[k] is not None), key=lambda k: cand[k])
    out["averaging"] = {"candidatos": cand, "elegido": best}
    with torch.no_grad():
        src = {"last": saved, "ema": ema}.get(best)
        if src is None:
            src = avg
        for p, q in zip(base.parameters(), src):
            p.copy_(q)
    print(f"[xh-final] averaging: {cand} -> {best}", flush=True)

    out["bpb_wiki"] = cand[best]
    out["bpb_stories"] = eval_bpb(base, vs, seq, tpb_s, device)
    out["extrapolacion"] = {"bpb_wiki_512": out["bpb_wiki"],
                            "bpb_wiki_1024": eval_bpb(base, vw, seq * 2, tpb_w, device,
                                                      n_windows=12)}
    if not smoke:
        base.set_rope_base(10000.0 * (2.0 ** (base.dh / max(1, base.dh - 2))))
        out["extrapolacion"]["bpb_wiki_1024_ntk2"] = eval_bpb(base, vw, seq * 2, tpb_w,
                                                              device, n_windows=12)
        base.set_rope_base(10000.0)

    tok = None
    if tok_path:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(tok_path)
    out["samples"] = []
    d2s, d3s, rep4 = [], [], []
    for prompt in (G2_PROMPTS if not smoke else G2_PROMPTS[:1]):
        try:
            if DATA_KIND == "bytes" or tok is None:
                pi = torch.from_numpy(np.frombuffer(prompt.encode(), dtype=np.uint8)
                                      .astype(np.int32).copy()).to(device).long().unsqueeze(0)
                y = base.generate(pi.clone(), 200 if not smoke else 20, eos_id=eos_id)
                ids = y[0].tolist()
                txt = bytes(t % 256 for t in ids).decode("utf-8", "ignore")
            else:
                pi = torch.tensor([tok.encode(prompt).ids], dtype=torch.long, device=device)
                y = base.generate(pi.clone(), 200 if not smoke else 20, eos_id=eos_id)
                ids = y[0].tolist()
                txt = tok.decode(ids)
            d2, d3, r4 = distinct_n(ids, 2), distinct_n(ids, 3), max_ngram_repeat(ids, 4)
            d2s.append(d2)
            d3s.append(d3)
            rep4.append(r4)
            out["samples"].append({"prompt": prompt, "text": txt, "distinct2": d2,
                                   "distinct3": d3, "max_4gram_repeat": r4})
            print(f"\n--- {prompt!r} (d2={d2} d3={d3} rep4={r4}) ---\n{ascii(txt)[:400]}\n",
                  flush=True)
        except Exception as e:  # noqa: BLE001
            out["samples"].append({"prompt": prompt, "error": repr(e)})
    if tok is not None and not smoke:
        out["cloze"] = cloze_score(base, tok, device)
        print(f"[xh-final] cloze: {out['cloze']}", flush=True)
    out["wall"]["evals_s"] = round(time.time() - t_ev, 1)

    # ── veredicto pre-registrado (G2 exige checklist manual → queda "manual") ──
    g1 = out["bpb_wiki"] is not None and out["bpb_wiki"] <= 1.35
    g1_falsado = out["bpb_wiki"] is not None and out["bpb_wiki"] > 1.45
    g3 = (d2s and sum(d2s) / len(d2s) >= 0.60 and sum(d3s) / len(d3s) >= 0.75
          and max(rep4 or [99]) < 4)
    g4 = out.get("cloze", {}).get("total", 0) >= 0.65
    out["gates"] = {"G1_bpb_wiki<=1.35": bool(g1), "G1_falsado_bpb>1.45": bool(g1_falsado),
                    "G2_coherencia": "manual (checklist 00_DISENO §3-G2 sobre samples)",
                    "G3_no_degeneracion": bool(g3),
                    "G4_cloze>=65%": bool(g4),
                    "wall_30min": bool((out["wall"].get("compile_first_step_s", 0)
                                        + out["wall"]["train_s"]
                                        + out["wall"]["evals_s"]) <= 1800)}
    print(f"[xh-final] GATES: {out['gates']}", flush=True)

    try:
        sd = {k: v.half().cpu() for k, v in base.state_dict().items()}
        torch.save(sd, MODEL_PATH)
        print(f"[xh-final] pesos ({best}) -> {MODEL_PATH}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[xh-final] no se pudo guardar: {e!r}", flush=True)

    out["minutes_total"] = round((time.time() - t_start) / 60, 1)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[xh-final] LISTO en {out['minutes_total']} min "
          f"(wall: {out['wall']})", flush=True)


if __name__ == "__main__":
    main()
