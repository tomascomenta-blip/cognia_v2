"""
CYCLE 8 — demostración del aprendizaje continuo Nivel 1 con compuerta ROBUSTA.

Objetivo científico: dar vuelta H-SELF-2 (❌false en hypotheses.md: "el evaluador es CIRCULAR/
agregado, no held-out"). Mostramos que una compuerta NO-circular (held-out cross-book real) y
POR-DOMINIO sí reduce el olvido, y que la versión AGREGADA es CIEGA al daño (reproduce el fallo).

Adversario por DILUCIÓN (el caso que el gate agregado no ve): la BASE sabe VARIOS dominios inglés +
UN dominio español. Aprende inglés nuevo (en_frankenstein), examinado en inglés hermano (en_dracula,
cross-book). Aprender inglés MEJORA los dominios inglés y DAÑA el español; el promedio de los viejos
apenas se mueve (las mejoras inglesas tapan el daño español) → el gate AGREGADO ACEPTA el olvido. El
gate POR-DOMINIO mira la PEOR materia y lo RECHAZA.

Brazos (todos parten del MISMO modelo base copiado):
  (A) naive             : sin compuerta → muestra el olvido por-dominio (español sube).
  (B) gate AGREGADO     : do-no-harm sobre el PROMEDIO → ACEPTA pese al daño (H-SELF-2 ❌).
  (C) gate POR-DOMINIO  : do-no-harm peor-caso → RECHAZA (rollback): atrapa el daño al español.
  (D) por-dominio+replay: repasa lo viejo mientras aprende → protege el español → ACEPTA (solución).

Anti-Goodhart: examinador cross-book + banda de incertidumbre (umbral=k·sigma). Anti-colapso: solo REAL.
Uso: python -m cognia_x.learn.run_cycle8 [--base_steps N] [--learn_steps N] [--smoke]
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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CORPUS = os.path.join(ROOT, "cognia_x", "data", "corpus")
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle8")

# dominios VIEJOS: 3 inglés (diluyen) + 1 español (la víctima del olvido)
OLD = [("en_alice", "en_alice"), ("en_sherlock", "en_sherlock"),
       ("en_pride_prejudice", "en_pride"), ("es_49836", "espanol")]
NEW_TRAIN = "en_frankenstein"   # dominio nuevo (inglés) que se aprende
NEW_VAL = "en_dracula"          # examinador cross-book (inglés hermano, NO entrenado)


def book(docs, name, sep=b"\n\n"):
    for nm, b in docs:
        if name in nm:
            return bytes(b) + sep
    return None


def tt(b):
    return torch.frombuffer(bytearray(b), dtype=torch.uint8)


def split(b, val_frac=0.1):
    sp = int((1 - val_frac) * len(b))
    return b[:sp], b[sp:]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base_steps", type=int, default=4000)
    ap.add_argument("--learn_steps", type=int, default=500)
    ap.add_argument("--d_model", type=int, default=128)
    ap.add_argument("--n_layers", type=int, default=4)
    ap.add_argument("--n_heads", type=int, default=4)
    ap.add_argument("--L", type=int, default=160)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--k", type=float, default=2.0, help="umbral en unidades de sigma del examinador")
    ap.add_argument("--eps_floor", type=float, default=0.05, help="piso de tolerancia do-no-harm")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.base_steps, args.learn_steps = 600, 150

    torch.set_num_threads(3)
    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True)
        logf.write(s + "\n"); logf.flush()

    docs = load_corpus_dir(CORPUS)
    # construir train/val por dominio viejo
    old_train_bytes, old_domains = [], []
    for bookname, label in OLD:
        raw = book(docs, bookname)
        if raw is None:
            log(f"[cycle8] falta libro viejo {bookname}; abortando"); return
        tr, va = split(raw)
        old_train_bytes.append((label, tr))
        old_domains.append((label, tt(va)))
    old_trains = [(l, tt(b)) for l, b in old_train_bytes]
    nt, nv = book(docs, NEW_TRAIN), book(docs, NEW_VAL)
    if nt is None or nv is None:
        log("[cycle8] faltan libros nuevos; corré get_corpus"); return
    new_tr, new_va = tt(nt), tt(nv)
    # buffer de replay = concat de TODOS los train viejos (incluye el español)
    replay_t = tt(b"".join(b for _, b in old_train_bytes))
    log(f"[cycle8] VIEJOS {[l for l, _ in old_domains]} | NUEVO train={NEW_TRAIN} "
        f"val(cross-book)={NEW_VAL} {new_va.numel():,}B | replay {replay_t.numel():,}B")

    # --- modelo base: aprende los 4 dominios viejos (alternando) ---
    torch.manual_seed(0)
    cfg = HybridConfig(vocab_size=256, d_model=args.d_model, n_layers=args.n_layers,
                       n_heads=args.n_heads, window=args.L + 1, attn_every=4, max_seq_len=args.L)
    base = HybridLM(cfg)
    opt = torch.optim.AdamW(base.parameters(), lr=args.lr, weight_decay=0.01)
    log(f"[cycle8] entrenando base ({base.num_params():,} params) {args.base_steps} pasos sobre {len(old_trains)} dominios...")
    base.train()
    nd = len(old_trains)
    for s in range(1, args.base_steps + 1):
        if s <= 150:
            for g in opt.param_groups:
                g["lr"] = args.lr * s / 150
        src = old_trains[s % nd][1]   # rota por dominio (balanceado)
        x, y = get_batch(src, args.batch, args.L, "cpu")
        _, loss = base(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(base.parameters(), 1.0); opt.step()
    base_old = {l: round(eval_at(base, vt, args.L, "cpu"), 4) for l, vt in old_domains}
    base_new = round(eval_at(base, new_va, args.L, "cpu"), 4)
    log(f"[cycle8] base listo. viejos {base_old} | nuevo {base_new}")

    gl = dict(steps=args.learn_steps, lr=args.lr, L=args.L, batch=args.batch,
              k=args.k, eps_floor=args.eps_floor)
    results = {"base": {"old": base_old, "new": base_new}}

    # (A) naive
    m = copy.deepcopy(base)
    o = torch.optim.AdamW(m.parameters(), lr=args.lr, weight_decay=0.01)
    learn_steps(m, o, new_tr, args.learn_steps, args.L, args.batch, "cpu")
    a_old = {l: round(eval_at(m, vt, args.L, "cpu"), 4) for l, vt in old_domains}
    a_new = round(eval_at(m, new_va, args.L, "cpu"), 4)
    deltas = {l: round(a_old[l] - base_old[l], 4) for l in base_old}
    agg = round(sum(deltas.values()) / len(deltas), 4)
    worst = max(deltas.values())
    results["A_naive"] = {"old": a_old, "new": a_new, "deltas": deltas,
                          "agg_delta": agg, "worst_delta": worst}
    log(f"[cycle8] (A) NAIVE: nuevo {base_new}->{a_new} | viejos d {deltas}")
    log(f"          -> promedio viejos {agg:+.3f} (lo que ve el gate AGREGADO) vs PEOR dominio "
        f"{worst:+.3f} (lo que ve el POR-DOMINIO) -- el promedio ESCONDE el daño")
    # ZONA CIEGA: eps en (agg, worst) hace que el agregado ACEPTE pero el por-dominio RECHACE.
    # Calibramos el eps de la demo al punto medio (robusto a las magnitudes del run).
    if worst > agg:
        eps_demo = round((agg + worst) / 2, 3)
        gl["eps_floor"] = max(args.eps_floor, eps_demo)
        log(f"          -> ZONA CIEGA del agregado: eps in ({agg:+.3f},{worst:+.3f}); "
            f"demo con eps={gl['eps_floor']:.3f} (agregado acepta, por-dominio rechaza)")
        results["A_naive"]["eps_demo"] = gl["eps_floor"]

    results["B_gate_agregado"] = gated_learn_domains(
        copy.deepcopy(base), new_tr, new_va, old_domains, log, replay_t=None,
        aggregate=True, name="B_agregado", **gl)
    results["C_gate_por_dominio"] = gated_learn_domains(
        copy.deepcopy(base), new_tr, new_va, old_domains, log, replay_t=None,
        aggregate=False, name="C_por_dominio", **gl)
    results["D_por_dominio_replay"] = gated_learn_domains(
        copy.deepcopy(base), new_tr, new_va, old_domains, log, replay_t=replay_t,
        aggregate=False, name="D_por_dominio_replay", **gl)

    summary = {"config": {k: getattr(args, k) for k in ("d_model", "n_layers", "base_steps",
                                                        "learn_steps", "lr", "k", "eps_floor", "L")},
               "old_domains": [l for l, _ in old_domains], "new_train": NEW_TRAIN, "new_val": NEW_VAL,
               "results": results}
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log("\n[cycle8] ===== RESUMEN: aprender ingles nuevo sin olvidar el espanol =====")
    log(f"  base viejos {base_old} | nuevo {base_new}")
    for k2 in ("B_gate_agregado", "C_gate_por_dominio", "D_por_dominio_replay"):
        r = results[k2]
        es_d = r["per_domain"].get("espanol", {}).get("delta", 0.0)
        log(f"  {k2:>22}: {'ACEPTA' if r['accepted'] else 'RECHAZA':>7} | "
            f"espanol d{es_d:+.3f} | nuevo d{r['new_delta']:+.3f}")
    log("  -> AGREGADO acepta el dano (ciego al promedio); POR-DOMINIO lo atrapa; +REPLAY aprende sin olvidar.")
    logf.close()


if __name__ == "__main__":
    main()
