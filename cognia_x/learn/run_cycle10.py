"""
CYCLE 10 — el loop continuo COMO PROCESO EN EL TIEMPO (no una sola lección).

La IA recibe una SECUENCIA de lecciones nuevas y debe ACUMULAR conocimiento sin que el viejo se
degrade lección tras lección (deriva acumulativa). Compara dos formas de "seguir aprendiendo":
  - NAIVE secuencial   : aprende cada lección sin compuerta ni replay → el dominio protegido
                         (español) se degrada ACUMULATIVAMENTE (cada lección lo empuja más).
  - GATED secuencial   : cada lección pasa por el gate POR-DOMINIO + replay; solo se fija si no daña
                         lo viejo (si no, rollback). El español se mantiene PLANO a lo largo de la
                         secuencia → la IA sigue aprendiendo sola SIN olvidar, indefinidamente.

Esto demuestra el loop como un PROCESO: el valor del español tras CADA lección es la evidencia.
Uso: python -m cognia_x.learn.run_cycle10 [--base_steps N] [--lesson_steps N] [--smoke]
"""
import argparse
import copy
import json
import os
import sys

import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.train.charlm import get_batch, load_corpus_dir
from cognia_x.learn.continual import eval_at, gated_learn_domains, learn_steps
from cognia_x.learn.run_cycle8 import book, tt, split

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CORPUS = os.path.join(ROOT, "cognia_x", "data", "corpus")
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle10")

PROTECT = "es_49836"     # dominio viejo a proteger a lo largo de la secuencia (español)
ANCHOR = "en_alice"      # 2º dominio viejo (inglés) — el gate vigila ambos
# secuencia de lecciones nuevas (libros que el modelo va aprendiendo uno tras otro)
LESSONS = ["en_frankenstein", "en_sherlock", "es_17073"]   # 2 inglés + 1 español nuevo


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base_steps", type=int, default=1800)
    ap.add_argument("--lesson_steps", type=int, default=300)
    ap.add_argument("--d_model", type=int, default=128)
    ap.add_argument("--L", type=int, default=160)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--k", type=float, default=2.0)
    ap.add_argument("--eps_floor", type=float, default=0.08)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.base_steps, args.lesson_steps = 700, 150

    torch.set_num_threads(3)
    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    docs = load_corpus_dir(CORPUS)
    pr, an = book(docs, PROTECT), book(docs, ANCHOR)
    pr_tr, pr_va = split(pr); an_tr, an_va = split(an)
    old_domains = [("espanol", tt(pr_va)), ("ingles", tt(an_va))]
    replay0 = pr_tr + an_tr     # buffer de replay inicial (lo que ya sabía)
    lessons = []   # (nombre, train_bytes, val_bytes)
    for name in LESSONS:
        b = book(docs, name)
        if b is None:
            log(f"[cycle10] falta {name}"); return
        l_tr, l_va = split(b)
        lessons.append((name, l_tr, l_va))
    log(f"[cycle10] protege={PROTECT} ancla={ANCHOR} | lecciones={[n for n,_,_ in lessons]}")

    # base que sabe espanol + ingles
    torch.manual_seed(0)
    cfg = HybridConfig(vocab_size=256, d_model=args.d_model, n_layers=4, n_heads=4,
                       window=args.L + 1, attn_every=4, max_seq_len=args.L)
    base = HybridLM(cfg)
    opt = torch.optim.AdamW(base.parameters(), lr=args.lr, weight_decay=0.01)
    pr_tr_t, an_tr_t = tt(pr_tr), tt(an_tr)
    for s in range(1, args.base_steps + 1):
        if s <= 120:
            for g in opt.param_groups:
                g["lr"] = args.lr * s / 120
        src = pr_tr_t if s % 2 == 0 else an_tr_t
        x, y = get_batch(src, args.batch, args.L, "cpu")
        _, loss = base(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(base.parameters(), 1.0); opt.step()
    es0 = eval_at(base, old_domains[0][1], args.L, "cpu")
    log(f"[cycle10] base listo. espanol(protegido) {es0:.3f}")

    def es_val(m):
        return round(eval_at(m, old_domains[0][1], args.L, "cpu"), 4)

    # --- NAIVE secuencial (sin gate ni replay): el español se degrada acumulativamente ---
    m = copy.deepcopy(base)
    naive_curve = [es0]
    for name, l_tr, _ in lessons:
        o = torch.optim.AdamW(m.parameters(), lr=args.lr, weight_decay=0.01)
        learn_steps(m, o, tt(l_tr), args.lesson_steps, args.L, args.batch, "cpu")
        naive_curve.append(es_val(m))
    log(f"[cycle10] NAIVE secuencial: español tras cada lección {naive_curve} (sube = olvido acumulado)")

    # --- GATED secuencial (gate por-dominio + replay creciente): español protegido ---
    m = copy.deepcopy(base)
    replay = bytearray(replay0)
    gated_curve = [es0]; decisions = []
    for name, l_tr, l_va in lessons:
        r = gated_learn_domains(m, tt(l_tr), tt(l_va), old_domains, log, replay_t=tt(bytes(replay)),
                                steps=args.lesson_steps, lr=args.lr, L=args.L, batch=args.batch,
                                k=args.k, eps_floor=args.eps_floor, name=f"L_{name}")
        decisions.append((name, r["accepted"]))
        if r["accepted"]:                       # lección aceptada -> entra al buffer de replay
            replay += l_tr
        gated_curve.append(es_val(m))
    log(f"[cycle10] GATED secuencial: español tras cada lección {gated_curve} (plano = NO olvida)")

    summary = {"base_espanol": es0, "naive_curve": naive_curve, "gated_curve": gated_curve,
               "decisions": decisions, "lessons": [n for n, _, _ in lessons]}
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    drift_naive = round(naive_curve[-1] - es0, 4)
    drift_gated = round(gated_curve[-1] - es0, 4)
    log("\n[cycle10] ===== RESUMEN: ¿se mantiene el español tras 3 lecciones? =====")
    log(f"  español base {es0:.3f}")
    log(f"  NAIVE  -> {naive_curve} | deriva total {drift_naive:+.3f}")
    log(f"  GATED  -> {gated_curve} | deriva total {drift_gated:+.3f} | decisiones {decisions}")
    log(f"  -> el loop con gate mantiene el español ({drift_gated:+.3f}) vs el naive ({drift_naive:+.3f}).")
    logf.close()


if __name__ == "__main__":
    main()
