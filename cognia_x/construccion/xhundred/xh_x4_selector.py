r"""
X4 (04_MOM_GROKKING §6) — el CALIBRADOR del MoM: ¿seleccionar la mejor respuesta o FUSIONAR?
Corre LOCAL (CPU) sobre los checkpoints de X3 (results_x3/): gen + 3 expertos densos.

Sobre N ventanas de val por dominio (dominio OCULTO para los métodos):
  (i)   router n-grams de caracteres (frecuencias de trigramas por dominio; gate ≥95% acc)
        → elige UN modelo → bpb del elegido
  (ii)  bandit ε-greedy por cluster del router, reward = −loss medida (verificador post-hoc)
        → curva de regret completa
  (iii) FUSIÓN de logits estilo c-BTM: mezcla de probabilidades de los 4 modelos con pesos
        del posterior del router → bpb de la mezcla
Referencias: oracle (mejor modelo por ventana) y gen-siempre.

PREDICCIÓN congelada (04 §6): (iii) NO supera a (ii) → el calibrador ES un selector.
USO: venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_x4_selector.py [--smoke]
"""
import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
RES = HERE / "results_x3"
OUT = RES / "xh_x4_results.json"
DOMS = ("stories", "wiki", "code")
SEQ = 512
N_WIN = 30                       # ventanas por dominio
EPS = 0.15                       # ε-greedy

sys.path.insert(0, str(HERE))
from xh_x3_mom import XHLM  # noqa: E402  (misma clase; checkpoints compatibles)


def tri_profile(text, k=3):
    t = re.sub(r"\s+", " ", text.lower())
    c = Counter(t[i:i + k] for i in range(len(t) - k))
    tot = sum(c.values())
    return {g: n / tot for g, n in c.most_common(400)}


def tri_score(profile, text, k=3):
    t = re.sub(r"\s+", " ", text.lower())
    if len(t) < k + 1:
        return 0.0
    return sum(profile.get(t[i:i + k], 0.0) for i in range(len(t) - k)) / (len(t) - k)


def router_posterior(profiles, text):
    s = {d: tri_score(p, text) for d, p in profiles.items()}
    tot = sum(s.values()) or 1e-9
    return {d: v / tot for d, v in s.items()}


@torch.no_grad()
def window_ce(model, x, y):
    _, ce, _ = model(x, y)
    return float(ce)


@torch.no_grad()
def fused_ce(models, weights, x, y):
    """CE de la mezcla de probabilidades (c-BTM)."""
    probs = None
    for m, w in zip(models, weights):
        logits, _, _ = m(x)
        p = F.softmax(logits.float(), dim=-1) * w
        probs = p if probs is None else probs + p
    lp = torch.log(probs.clamp_min(1e-12))
    return float(F.nll_loss(lp.view(-1, lp.size(-1)), y.view(-1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    torch.set_num_threads(3)
    device = "cpu"

    if args.smoke:
        vocab = 512
        names = ["gen"] + [f"exp_{d}" for d in DOMS]
        torch.manual_seed(0)
        models = {n: XHLM(vocab, d=64, n_heads=4, n_layers=2, global_layers=(1,)).eval()
                  for n in names}
        g = torch.Generator().manual_seed(0)
        vals = {d: torch.randint(1, vocab, (N_WIN * (SEQ + 1) + 8,), generator=g).long()
                for d in DOMS}
        val_txts = {"stories": "habia una vez un nino feliz " * 200,
                    "wiki": "la historia de la provincia y el municipio " * 200,
                    "code": "def foo(x):\n    return x + 1\n" * 200}
        tpb = {d: 1.0 for d in DOMS}
        n_win, seq = 4, 64
    else:
        meta = json.loads((RES / "xh_x3data_meta.json").read_text(encoding="utf-8")) \
            if (RES / "xh_x3data_meta.json").exists() else \
            json.loads((RES / "meta_copy.json").read_text(encoding="utf-8"))
        vocab = meta["vocab"]
        names = ["gen"] + [f"exp_{d}" for d in DOMS]
        models = {}
        for n in names:
            m = XHLM(vocab).eval()
            sd = torch.load(RES / f"x3_{n}.pt", map_location="cpu")
            m.load_state_dict({k: v.float() for k, v in sd.items()})
            models[n] = m
        vals = {d: torch.from_numpy(np.fromfile(RES / f"val_{d}_3dom.bin",
                                                dtype=np.uint16).astype(np.int64))
                for d in DOMS}
        val_txts = {d: (RES / f"val_{d}.txt").read_text(encoding="utf-8") for d in DOMS}
        tpb = {d: meta["domains"][d]["val_tokens"] / meta["domains"][d]["val_bytes"]
               for d in DOMS}
        n_win, seq = N_WIN, SEQ

    # router n-grams: perfil con la 1ª mitad del val.txt; queries de la 2ª (sin solaparse)
    profiles = {d: tri_profile(val_txts[d][:len(val_txts[d]) // 2]) for d in DOMS}
    router_ok = tot = 0
    for d in DOMS:
        half = val_txts[d][len(val_txts[d]) // 2:]
        for i in range(0, min(len(half) - 400, 20 * 400), 400):
            post = router_posterior(profiles, half[i:i + 400])
            router_ok += int(max(post, key=post.get) == d)
            tot += 1
    router_acc = router_ok / max(1, tot)
    print(f"[router] acc n-grams = {router_acc:.3f} (gate >=0.95)", flush=True)

    # queries: ventanas por dominio (dominio oculto para los métodos)
    queries = []
    for d in DOMS:
        va = vals[d]
        for w in range(n_win):
            s = w * seq
            if s + seq + 1 > len(va):
                break
            queries.append((d, va[s:s + seq].unsqueeze(0), va[s + 1:s + seq + 1].unsqueeze(0)))
    rng = np.random.default_rng(0)
    rng.shuffle(queries)
    print(f"[x4] {len(queries)} queries, {len(models)} modelos", flush=True)

    mnames = list(models)
    ce_cache = {}                                 # (query_idx, model) -> ce
    out = {"experiment": "xh_x4_selector", "router_acc": round(router_acc, 4),
           "n_queries": len(queries), "arms": {}}

    def ce_of(qi, mn):
        if (qi, mn) not in ce_cache:
            d, x, y = queries[qi]
            ce_cache[(qi, mn)] = window_ce(models[mn], x, y)
        return ce_cache[(qi, mn)]

    # métricas por método: bpb medio por dominio de la CE del modelo usado
    def collect(tag, chooser, fused=False):
        per_dom = {d: [] for d in DOMS}
        for qi, (d, x, y) in enumerate(queries):
            if fused:
                post = router_posterior(profiles, decode_approx(x))
                w = [post.get("stories", 0) if "stories" in mn else
                     post.get("wiki", 0) if "wiki" in mn else
                     post.get("code", 0) if "code" in mn else 0.25 for mn in mnames]
                totw = sum(w) or 1
                ce = fused_ce([models[mn] for mn in mnames], [x_ / totw for x_ in w], x, y)
            else:
                ce = ce_of(qi, chooser(qi, d, x))
            per_dom[d].append(ce)
        row = {d: round(sum(v) / len(v) * tpb[d] / math.log(2), 4)
               for d, v in per_dom.items() if v}
        out["arms"][tag] = row
        print(f"[{tag}] bpb por dominio: {row}", flush=True)

    # decode aproximado para el router (los bins son ids; el router usa texto)
    tok = None
    if not args.smoke:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(RES / "tokenizer_3dom.json"))

    def decode_approx(x):
        if tok is None:
            return "def foo" if float(x.float().mean()) < vocab / 3 else "la historia de"
        return tok.decode(x[0][:256].tolist())

    collect("gen_siempre", lambda qi, d, x: "gen")
    collect("oracle", lambda qi, d, x: min(mnames, key=lambda mn: ce_of(qi, mn)))
    collect("router_ngrams", lambda qi, d, x: {
        "stories": "exp_stories", "wiki": "exp_wiki", "code": "exp_code"}[
        max(router_posterior(profiles, decode_approx(x)),
            key=router_posterior(profiles, decode_approx(x)).get)])

    # (ii) bandit ε-greedy por cluster del router (sin ground-truth de dominio)
    q_est = {}                                    # (cluster, arm) -> media de reward
    n_pulls = {}
    regret_curve = []
    cum_regret = 0.0
    order = list(range(len(queries)))
    rng.shuffle(order)
    per_dom = {d: [] for d in DOMS}
    for t_i, qi in enumerate(order):
        d, x, y = queries[qi]
        cluster = max(router_posterior(profiles, decode_approx(x)),
                      key=router_posterior(profiles, decode_approx(x)).get)
        if rng.random() < EPS:
            arm = mnames[rng.integers(len(mnames))]
        else:
            arm = max(mnames, key=lambda mn: q_est.get((cluster, mn), 0.0))
        ce = ce_of(qi, arm)
        r = -ce
        k = (cluster, arm)
        n_pulls[k] = n_pulls.get(k, 0) + 1
        q_est[k] = q_est.get(k, 0.0) + (r - q_est.get(k, 0.0)) / n_pulls[k]
        best_ce = min(ce_of(qi, mn) for mn in mnames)
        cum_regret += ce - best_ce
        per_dom[d].append(ce)
        if (t_i + 1) % 20 == 0:
            regret_curve.append({"t": t_i + 1, "regret_medio": round(cum_regret / (t_i + 1), 4)})
    out["arms"]["bandit_verifier"] = {d: round(sum(v) / len(v) * tpb[d] / math.log(2), 4)
                                      for d, v in per_dom.items() if v}
    out["bandit"] = {"regret_medio_final": round(cum_regret / len(order), 4),
                     "curve": regret_curve}
    print(f"[bandit_verifier] bpb: {out['arms']['bandit_verifier']} "
          f"regret={out['bandit']['regret_medio_final']}", flush=True)

    # (iii) fusión de logits
    collect("fusion_cbtm", None, fused=True)

    # veredicto pre-registrado
    sel = out["arms"].get("bandit_verifier", {})
    fus = out["arms"].get("fusion_cbtm", {})
    if sel and fus:
        out["veredicto"] = {
            "fusion_supera_seleccion": bool(all(fus.get(d, 9) < sel.get(d, 9) - 0.01
                                                for d in DOMS)),
            "P_calibrador_es_selector": bool(any(fus.get(d, 0) >= sel.get(d, 9) - 0.01
                                                 for d in DOMS)),
            "router_gate_95": bool(router_acc >= 0.95)}
        print(f"[x4] VEREDICTO: {out['veredicto']}", flush=True)
    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[x4] LISTO en {out['minutes_total']} min -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
