"""
CYCLE 11 — Nivel 2: colapso del modelo y su GUARDA (el frontier de "investigar por sí misma").

Cuando la IA "investiga sola" puede caer en la tentación de aprender de SU PROPIA salida (fotocopia de
una fotocopia). Esto colapsa: la distribución se estrecha generación tras generación. Demostramos el
peligro y la guarda, por transformación cotidiana (estudiar de tus propios apuntes mal copiados):

  BRAZO COLAPSO (control negativo): K rondas donde el modelo GENERA texto y se entrena con su PROPIA
    salida. Predicción: la pérdida sobre texto REAL held-out SUBE (colapso) y la diversidad de bytes
    de lo generado CAE (estrechamiento).
  BRAZO GUARD (la solución): mismas rondas, pero (a) el EXAMINADOR es SIEMPRE texto REAL (nunca
    sintético); (b) antes de aprender, filtro de DEGENERACIÓN — gzip(generado) debe estar en rango
    del gzip real (texto demasiado comprimible = colapsado → se descarta); (c) si una ronda sube el
    val real, ROLLBACK. Predicción: el val real se mantiene plano (la realidad ancla el aprendizaje).

Anti-colapso = anclar a datos REALES + verificar antes de aprender. Reusa generate(), gzip y eval.
Uso: python -m cognia_x.learn.run_cycle11 [--rounds K] [--gen_bytes N] [--smoke]
"""
import argparse
import copy
import json
import os
import sys

import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.train.charlm import get_batch, gzip_bits_per_byte, load_corpus_dir
from cognia_x.learn.continual import eval_at, learn_steps, snapshot_model, restore_model
from cognia_x.learn.run_cycle8 import book, tt, split

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CORPUS = os.path.join(ROOT, "cognia_x", "data", "corpus")
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle11")


def generate_bytes(model, n_bytes, L, device, seed_text=b"The ", chunk=256):
    """Genera ~n_bytes de texto del modelo (autoregresivo). Determinista por temperatura baja."""
    model.eval()
    out = bytearray()
    while len(out) < n_bytes:
        idx = torch.tensor([list(seed_text)], dtype=torch.long, device=device)
        gen = model.generate(idx, n_new=chunk, temperature=0.9, top_k=40)
        out += bytes(gen[0].tolist())
    model.train()
    return bytes(out[:n_bytes])


def byte_diversity(b):
    return len(set(b))   # nº de bytes distintos (cae con el colapso)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--gen_bytes", type=int, default=4000)
    ap.add_argument("--base_steps", type=int, default=2500)
    ap.add_argument("--learn_steps", type=int, default=250)
    ap.add_argument("--d_model", type=int, default=128)
    ap.add_argument("--L", type=int, default=160)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--eps", type=float, default=0.05)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.rounds, args.gen_bytes, args.base_steps, args.learn_steps = 3, 1500, 800, 120

    torch.set_num_threads(3)
    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    docs = load_corpus_dir(CORPUS)
    en = book(docs, "en_alice")
    en_tr, en_va = split(en)
    real_tr, real_va = tt(en_tr), tt(en_va)
    real_gzip = gzip_bits_per_byte(en_tr)
    log(f"[cycle11] base sobre en_alice | gzip REAL train {real_gzip:.3f} bits/byte")

    torch.manual_seed(0)
    cfg = HybridConfig(vocab_size=256, d_model=args.d_model, n_layers=4, n_heads=4,
                       window=args.L + 1, attn_every=4, max_seq_len=args.L)
    base = HybridLM(cfg)
    opt = torch.optim.AdamW(base.parameters(), lr=args.lr, weight_decay=0.01)
    for s in range(1, args.base_steps + 1):
        if s <= 120:
            for g in opt.param_groups:
                g["lr"] = args.lr * s / 120
        x, y = get_batch(real_tr, args.batch, args.L, "cpu")
        _, loss = base(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(base.parameters(), 1.0); opt.step()
    v0 = eval_at(base, real_va, args.L, "cpu")
    log(f"[cycle11] base listo. val REAL held-out {v0:.3f}")

    # --- BRAZO COLAPSO: entrenar con la propia salida, sin guarda ---
    m = copy.deepcopy(base)
    col = {"real_val": [round(v0, 4)], "gen_gzip": [], "gen_diversity": []}
    for r in range(1, args.rounds + 1):
        gen = generate_bytes(m, args.gen_bytes, args.L, "cpu")
        col["gen_gzip"].append(gzip_bits_per_byte(gen)); col["gen_diversity"].append(byte_diversity(gen))
        o = torch.optim.AdamW(m.parameters(), lr=args.lr, weight_decay=0.01)
        learn_steps(m, o, tt(gen), args.learn_steps, args.L, args.batch, "cpu")
        col["real_val"].append(round(eval_at(m, real_va, args.L, "cpu"), 4))
        log(f"[cycle11] COLAPSO ronda {r}: gen_gzip {col['gen_gzip'][-1]:.3f} "
            f"div {col['gen_diversity'][-1]} | val REAL {col['real_val'][-1]:.3f}")

    # --- BRAZO GUARD: examinador real + filtro de degeneración + rollback ---
    m = copy.deepcopy(base)
    grd = {"real_val": [round(v0, 4)], "accepted": [], "gen_gzip": []}
    for r in range(1, args.rounds + 1):
        gen = generate_bytes(m, args.gen_bytes, args.L, "cpu")
        g = gzip_bits_per_byte(gen); grd["gen_gzip"].append(g)
        # filtro de degeneración: gzip del generado debe estar en rango del real (no demasiado comprimible)
        degenerate = g < 0.85 * real_gzip
        before = eval_at(m, real_va, args.L, "cpu")
        snap = snapshot_model(m)
        if not degenerate:
            o = torch.optim.AdamW(m.parameters(), lr=args.lr, weight_decay=0.01)
            learn_steps(m, o, tt(gen), args.learn_steps, args.L, args.batch, "cpu")
        after = eval_at(m, real_va, args.L, "cpu")
        accept = (not degenerate) and (after <= before + args.eps)   # examinador REAL + do-no-harm
        if not accept:
            restore_model(m, snap)
        grd["accepted"].append(bool(accept)); grd["real_val"].append(round(eval_at(m, real_va, args.L, "cpu"), 4))
        log(f"[cycle11] GUARD ronda {r}: gen_gzip {g:.3f} degenerate={degenerate} accept={accept} | "
            f"val REAL {grd['real_val'][-1]:.3f}")

    summary = {"base_real_val": round(v0, 4), "real_gzip": real_gzip, "colapso": col, "guard": grd}
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    d_col = round(col["real_val"][-1] - v0, 4)
    d_grd = round(grd["real_val"][-1] - v0, 4)
    log("\n[cycle11] ===== RESUMEN: ¿la guarda evita el colapso? =====")
    log(f"  val REAL base {v0:.3f}")
    log(f"  COLAPSO -> {col['real_val']} | deriva {d_col:+.3f} | gzip generado {col['gen_gzip']} (cae=estrechamiento)")
    log(f"  GUARD   -> {grd['real_val']} | deriva {d_grd:+.3f} | aceptadas {grd['accepted']}")
    log(f"  -> el colapso sube el val real ({d_col:+.3f}); la guarda lo mantiene ({d_grd:+.3f}) anclando a lo REAL.")
    logf.close()


if __name__ == "__main__":
    main()
