r"""
M1 (05_DSPARK_ANALISIS §5) — Selector de 3 ZONAS con umbral ASIMÉTRICO calibrado.
Local CPU sobre los checkpoints X3. Práctica adoptada de DSpark: medir ECE ANTES de que una
decisión use la señal; técnica NUESTRA: umbrales por pérdida esperada con los costos
direccionales MEDIDOS de X3 (errar-a-experto +0.94..+3.5 bpb; errar-a-generalista +0.17..0.30).

Zonas: A margen alto → experto top-1 (1 fwd) · B margen bajo → fusión top-2 (+1 fwd, solo
donde el router duda — X4: la fusión solo paga ahí) · C score máximo bajo → generalista.
Fix de rigor vs X4 (declarado): perfiles del router desde ventanas DECODIFICADAS del TRAIN
(disjuntas del val); queries = 300 ventanas del val (100/dominio), dominio oculto.

PREDICCIÓN CONGELADA (05 §5-M1): (a) ECE crudo >5%, calibrado ≤2%; (b) 3-zonas: bpb código ≤
fusión-siempre manteniendo cuentos/wiki ≈ oracle, con ≤1.10 fwd/query; (c) si AUC(margen→
misroute) <0.70, la zona B no paga → selección+fallback puro (falsación declarada).
USO: venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_m1_selector3z.py [--smoke]
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
RES = HERE / "results_x3"
OUT = RES / "xh_m1_results.json"
DOMS = ("stories", "wiki", "code")
SEQ = 512
N_WIN = 100                      # por dominio (X4 usó 30)
CAL_FRAC = 0.5                   # mitad calibración, mitad eval

sys.path.insert(0, str(HERE))
from xh_x3_mom import XHLM  # noqa: E402
from xh_x4_selector import fused_ce, window_ce  # noqa: E402

sys.path.insert(0, str(HERE.parents[2]))
from cognia_x.mom.selector import tri_profile  # noqa: E402


def posterior_raw(profiles, text, k=3):
    import re
    t = re.sub(r"\s+", " ", text.lower())
    if len(t) < k + 1:
        return {d: 1.0 / len(profiles) for d in profiles}
    s = {d: sum(p.get(t[i:i + k], 0.0) for i in range(len(t) - k)) / (len(t) - k)
         for d, p in profiles.items()}
    tot = sum(s.values()) or 1e-9
    return {d: v / tot for d, v in s.items()}


def apply_T(post, T):
    """temperature scaling sobre log-scores normalizados."""
    logs = {d: math.log(max(v, 1e-9)) / T for d, v in post.items()}
    mx = max(logs.values())
    ex = {d: math.exp(v - mx) for d, v in logs.items()}
    tot = sum(ex.values())
    return {d: v / tot for d, v in ex.items()}


def ece(posts, labels, bins=10):
    """Expected Calibration Error sobre la prob del top-1."""
    rows = [(max(p.values()), max(p, key=p.get) == y) for p, y in zip(posts, labels)]
    e = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(c, ok) for c, ok in rows if lo < c <= hi]
        if sel:
            conf = sum(c for c, _ in sel) / len(sel)
            acc = sum(ok for _, ok in sel) / len(sel)
            e += len(sel) / len(rows) * abs(acc - conf)
    return e


def auc(scores_pos, scores_neg):
    """AUC por conteo de pares (margen alto = ruteo correcto esperado)."""
    if not scores_pos or not scores_neg:
        return None
    wins = ties = 0
    for a in scores_pos:
        for b in scores_neg:
            wins += a > b
            ties += a == b
    return (wins + 0.5 * ties) / (len(scores_pos) * len(scores_neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    torch.set_num_threads(3)
    n_win = 6 if args.smoke else N_WIN

    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(RES / "tokenizer_3dom.json"))
    meta = json.loads((RES / "xh_x3data_meta.json").read_text(encoding="utf-8"))
    vocab = meta["vocab"]
    tpb = {d: meta["domains"][d]["val_tokens"] / meta["domains"][d]["val_bytes"] for d in DOMS}

    # perfiles desde TRAIN decodificado (disjunto del val — fix de leakage vs X4, declarado)
    profiles = {}
    for d in DOMS:
        tr = np.fromfile(RES / f"train_dom_{d}.bin", dtype=np.uint16)
        txt = tok.decode(tr[:120_000].astype(np.int64).tolist())
        profiles[d] = tri_profile(txt)

    models = {}
    names = ["gen"] + [f"exp_{d}" for d in DOMS]
    for n in names:
        m = XHLM(vocab).eval()
        sd = torch.load(RES / f"x3_{n}.pt", map_location="cpu")
        m.load_state_dict({k: v.float() for k, v in sd.items()})
        models[n] = m
    exp_of = {d: f"exp_{d}" for d in DOMS}

    # 300 queries (dominio oculto): texto decodificado para el router + tensores para CE
    queries = []
    for d in DOMS:
        va = torch.from_numpy(np.fromfile(RES / f"val_{d}_3dom.bin",
                                          dtype=np.uint16).astype(np.int64))
        for w in range(n_win):
            s = w * SEQ
            if s + SEQ + 1 > len(va):
                break
            x = va[s:s + SEQ].unsqueeze(0)
            y = va[s + 1:s + SEQ + 1].unsqueeze(0)
            queries.append((d, tok.decode(va[s:s + 256].tolist()), x, y))
    rng = np.random.default_rng(0)
    rng.shuffle(queries)
    n_cal = int(len(queries) * CAL_FRAC)
    print(f"[m1] {len(queries)} queries ({n_cal} cal / {len(queries) - n_cal} eval)", flush=True)

    posts_raw = [posterior_raw(profiles, q[1]) for q in queries]
    labels = [q[0] for q in queries]

    # (a) calibración: T minimiza NLL en cal; ECE antes/después en eval
    def nll_of(T):
        tot = 0.0
        for p, y in zip(posts_raw[:n_cal], labels[:n_cal]):
            tot -= math.log(max(apply_T(p, T)[y], 1e-9))
        return tot
    Ts = [0.05, 0.1, 0.15, 0.25, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0]
    T_best = min(Ts, key=nll_of)
    ece_raw = ece(posts_raw[n_cal:], labels[n_cal:])
    posts_cal = [apply_T(p, T_best) for p in posts_raw]
    ece_cal = ece(posts_cal[n_cal:], labels[n_cal:])
    print(f"[m1] T={T_best} ECE crudo={ece_raw:.4f} calibrado={ece_cal:.4f}", flush=True)

    # CE cache (todas las queries × modelos que hagan falta; oracle usa los 4)
    ce = {}
    t_ce = time.time()
    for qi, (d, _txt, x, y) in enumerate(queries):
        for nme in names:
            ce[(qi, nme)] = window_ce(models[nme], x, y)
        if (qi + 1) % 50 == 0:
            print(f"  [ce] {qi + 1}/{len(queries)} ({time.time() - t_ce:.0f}s)", flush=True)

    # (c) AUC del margen top1−top2 para separar misroutes (en eval split, con posts calibrados)
    marg_ok, marg_bad = [], []
    for qi in range(n_cal, len(queries)):
        p = posts_cal[qi]
        top = sorted(p.values(), reverse=True)
        margin = top[0] - top[1]
        (marg_ok if max(p, key=p.get) == labels[qi] else marg_bad).append(margin)
    auc_m = auc(marg_ok, marg_bad)
    print(f"[m1] AUC margen->misroute = {auc_m} (misroutes eval: {len(marg_bad)})", flush=True)

    # (b) 3 zonas: grid de umbrales en CAL minimizando bpb esperado; eval en EVAL
    def policy_ce(qi, m_hi, s_lo, forwards):
        p = posts_cal[qi]
        top1 = max(p, key=p.get)
        srt = sorted(p.items(), key=lambda kv: -kv[1])
        margin = srt[0][1] - srt[1][1]
        d_q, _txt, x, y = queries[qi]
        if srt[0][1] < s_lo:                       # zona C → generalista
            forwards.append(1)
            return ce[(qi, "gen")]
        if margin >= m_hi:                         # zona A → experto top-1
            forwards.append(1)
            return ce[(qi, exp_of[top1])]
        # zona B → fusión top-2 (pesos = posterior renormalizado)
        m1n, m2n = exp_of[srt[0][0]], exp_of[srt[1][0]]
        w1 = srt[0][1] / (srt[0][1] + srt[1][1])
        forwards.append(2)
        return fused_ce([models[m1n], models[m2n]], [w1, 1 - w1], x, y)

    best = None
    for m_hi in (0.05, 0.15, 0.3, 0.5):
        for s_lo in (0.34, 0.4, 0.5):
            fw = []
            tot = sum(policy_ce(qi, m_hi, s_lo, fw) for qi in range(n_cal))
            cand = (tot / n_cal, m_hi, s_lo)
            if best is None or cand < best:
                best = cand
    _, M_HI, S_LO = best
    print(f"[m1] umbrales elegidos (cal): margen>={M_HI} score_min>={S_LO}", flush=True)

    def eval_policy(fn):
        per = {d: [] for d in DOMS}
        fw = []
        for qi in range(n_cal, len(queries)):
            per[queries[qi][0]].append(fn(qi, fw))
        return ({d: round(sum(v) / len(v) * tpb[d] / math.log(2), 4) for d, v in per.items()},
                round(sum(fw) / max(1, len(fw)), 3))

    def sel_pura(qi, fw):
        fw.append(1)
        return ce[(qi, exp_of[max(posts_cal[qi], key=posts_cal[qi].get)])]

    def fus_siempre(qi, fw):
        fw.append(3)
        p = posts_cal[qi]
        w = [p[d] for d in DOMS]
        tot = sum(w) or 1
        _d, _t, x, y = queries[qi]
        return fused_ce([models[exp_of[d]] for d in DOMS], [v / tot for v in w], x, y)

    def ora(qi, fw):
        fw.append(1)
        return min(ce[(qi, n)] for n in names)

    def gen_always(qi, fw):
        fw.append(1)
        return ce[(qi, "gen")]

    r3z, f3z = eval_policy(lambda qi, fw: policy_ce(qi, M_HI, S_LO, fw))
    rsel, _ = eval_policy(sel_pura)
    rfus, _ = eval_policy(fus_siempre)
    rora, _ = eval_policy(ora)
    rgen, _ = eval_policy(gen_always)

    out = {"experiment": "xh_m1_selector3z", "n_queries": len(queries), "T": T_best,
           "ece_raw": round(ece_raw, 4), "ece_cal": round(ece_cal, 4),
           "auc_margen": round(auc_m, 4) if auc_m else None,
           "umbrales": {"margen_hi": M_HI, "score_lo": S_LO},
           "bpb": {"tres_zonas": r3z, "seleccion_pura": rsel, "fusion_siempre": rfus,
                   "oracle": rora, "gen_siempre": rgen},
           "forwards_promedio": {"tres_zonas": f3z},
           "prediccion": {
               "a_ece": bool(ece_raw > 0.05 and ece_cal <= 0.02),
               "c_auc_070": bool(auc_m is not None and auc_m >= 0.70)},
           "minutes_total": round((time.time() - t0) / 60, 1)}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[m1] bpb 3-zonas={r3z} (fwd {f3z}) | selección={rsel} | oracle={rora}", flush=True)
    print(f"[m1] VEREDICTO parcial: {out['prediccion']} | LISTO en "
          f"{out['minutes_total']} min -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
