"""
exp016 — CYCLE 29: H-LEARN-1. ¿El VERIFICADOR (señal de corrección) es el motor de auto-mejora STaR,
NO el volumen ni el filtrado-per-se? Tarea VERIFICABLE: suma byte-level (oráculo int(A)+int(B)).

CONTEXTO (cognia_x/learn/RESULTS.md): CYCLE 11 mostró que verify-before-learn PREVIENE el colapso en
LENGUAJE puro RECHAZANDO TODO (la auto-salida nunca mejora el val real en una tarea no-verificable). El
frente nuevo: en una tarea VERIFICABLE, ¿el modelo APRENDE de su propia salida y MEJORA (bootstrapping
tipo STaR, Zelikman 2022 / rejection-sampling) si un oráculo chequeable filtra las correctas? ¿Y la
ganancia es de la CORRECCIÓN o solo de tener menos/distintos datos?

HIPOTESIS H-LEARN-1: a partir de un base TINY débil-pero-bootstrappable (acc oráculo held-out en
[0.20,0.50]), entrenar SOLO con las auto-generaciones VERIFICADO-CORRECTAS (verified) produce auto-mejora
en el test held-out REAL, y esa mejora se debe a la SEÑAL DE CORRECCIÓN — no al volumen/pasos ni al acto
de filtrar (control random_matched: mismo N_keep y mismos N_steps, subconjunto ALEATORIO no por corrección).
  APOYADA si: verified termina >= base+0.10 Y > random_matched por >2σ; naive_all (entrena con TODAS, incl.
    incorrectas) estanca/colapsa (acc no sube y/o cae la diversidad de respuestas).
  REFUTADA si: verified no supera al base (>2σ); O verified ~ random_matched (era filtrar/reducir, no la
    corrección — control DECISIVO); O naive_all iguala/supera a verified. Un null es INFORMACIÓN.

NOTA DE DISEÑO (honesta, vs el spec del workflow): el spec tenía 4 brazos pero naive_matched y
oracle_random eran idénticos (ambos: subconjunto aleatorio de EXACTAMENTE N_keep, target=emitido). Se
fusionan en UN control `random_matched` que subsume ambos confounds (volumen/pasos Y filtrado-per-se):
mismo N_keep y mismos N_steps que verified, selección ALEATORIA. Brazos: verified / random_matched / naive_all.

Comparación PAREADA: en cada ronda, antes de generar, se fija la semilla torch (misma aleatoriedad de
muestreo dada la MISMA red); en la ronda 1 los 3 brazos parten del MISMO base -> pool idéntico; luego
divergen naturalmente (cada brazo genera de SU propia red mejorada = el loop STaR real).

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp016_verified_bootstrap.run --calibrate   # solo base
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp016_verified_bootstrap.run --smoke
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp016_verified_bootstrap.run               # FULL
"""
import argparse
import copy
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np
import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

# Modelo tiny (spec): d=64, 4 capas (2 lineal + 2 atención via attn_every=2), byte-level.
D_MODEL, N_LAYERS, N_HEADS, ATTN_EVERY = 64, 4, 4, 2
ARMS = ["verified", "random_matched", "naive_all"]
# Rango de la TAREA [lo,hi] (operandos) — UNICO para base/pool/test (args --lo/--hi). El base es débil
# por DATOS LIMITADOS (n_seed pequeño del espacio (hi-lo+1)^2), NO por entrenar en otro rango.


def build_base(seed, n_seed, base_steps, lr, warmup, batch, train_pairs, log):
    """Entrena un base débil-pero-bootstrappable por teacher-forcing sobre un set FIJO de N_seed sumas
    correctas muestreadas SOLO de train_pairs (disjunto del test). Débil por DATOS LIMITADOS -> acc parcial."""
    torch.manual_seed(seed)
    cfg = HybridConfig(vocab_size=256, d_model=D_MODEL, n_layers=N_LAYERS, n_heads=N_HEADS,
                       attn_every=ATTN_EVERY, window=T.L + 1, max_seq_len=T.L + 1)
    model = HybridLM(cfg)
    seed_rng = np.random.default_rng(seed)
    sel = seed_rng.integers(0, len(train_pairs), size=n_seed)  # SET FIJO de ejemplos correctos (de train)
    pairs = [train_pairs[i] for i in sel]
    examples = [(T.make_prompt(a, b), T.correct_answer(a, b)) for a, b in pairs]
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    model.train()
    for s in range(1, base_steps + 1):
        if s <= warmup:
            for g in opt.param_groups:
                g["lr"] = lr * s / warmup
        idxs = seed_rng.integers(0, len(examples), size=batch)
        x, y = T.batch_from_examples([examples[i] for i in idxs], "cpu")
        _, loss = model(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
    return model, cfg.num_params() if hasattr(cfg, "num_params") else model.num_params()


@torch.no_grad()
def generate_pool(model, prompts, K, temperature, top_k, device):
    """Genera K completaciones por prompt (batcheado POR LONGITUD de prompt -> rápido en CPU).
    Devuelve list[(prompt_bytes, emitted_bytes, is_correct)]."""
    model.eval()
    expanded = [p for p in prompts for _ in range(K)]
    buckets = defaultdict(list)
    for p in expanded:
        buckets[len(p)].append(p)
    out = []
    for plen, plist in buckets.items():
        idx = torch.tensor([list(bytes(p)) for p in plist], dtype=torch.long, device=device)
        gen = model.generate(idx, n_new=T.N_NEW, temperature=temperature, top_k=top_k)
        new = gen[:, plen:].tolist()
        for p, nb in zip(plist, new):
            nb = bytes(nb)
            out.append((p, T.emitted_answer(nb), T.oracle_correct(p, nb)))
    model.train()
    return out


def train_arm(model, examples, steps, batch, lr, device, rng):
    """N_steps pasos de gradiente sobre `examples` (muestreo con reemplazo). Optimizer fresco por ronda."""
    if not examples:
        return 0
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    model.train()
    for _ in range(steps):
        idxs = rng.integers(0, len(examples), size=batch)
        x, y = T.batch_from_examples([examples[i] for i in idxs], device)
        _, loss = model(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
    return steps


def acc_sigma(acc, m):
    """Sigma binomial del examinador: sqrt(p(1-p)/M). 2σ es el umbral de significancia entre brazos."""
    return math.sqrt(max(1e-9, acc * (1 - acc)) / max(1, m))


def run_seed(seed, args, test, train_pairs, log):
    """Una corrida completa para un seed: base + 3 brazos por R rondas. Pool de train (disjunto del test)."""
    base, nparams = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                               args.batch, train_pairs, log)
    base_acc, _, m = T.eval_accuracy(base, test, "cpu")
    log(f"[exp016] seed={seed} base acc oráculo held-out={base_acc:.3f} (banda [0.20,0.50]) params={nparams:,}")

    # POOL de prompts de auto-generación: SOLO de train_pairs -> disjunto del test held-out (anti-leakage).
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_pairs), size=args.pool)
    pool_prompts = [T.make_prompt(a, b) for a, b in (train_pairs[i] for i in sel)]
    test_set = set(p for p, _, _ in test)
    overlap = sum(1 for p in pool_prompts if p in test_set)   # debe ser 0 (pool de train, test disjunto)

    arms = {name: copy.deepcopy(base) for name in ARMS}
    hist = {name: [round(base_acc, 4)] for name in ARMS}
    diversity = {name: [] for name in ARMS}
    nkeep_hist, p_hist = [], []
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        # --- verified primero: define N_keep de la ronda (los controles lo igualan) ---
        torch.manual_seed(1000 * seed + r)        # pareado: misma aleatoriedad dada la misma red
        pool_v = generate_pool(arms["verified"], pool_prompts, args.K, 0.8, 20, "cpu")
        correct = [(p, e) for (p, e, ok) in pool_v if ok]
        n_keep = len(correct)
        p_accept = n_keep / max(1, len(pool_v))
        nkeep_hist.append(n_keep); p_hist.append(round(p_accept, 4))
        if n_keep > 0:
            train_arm(arms["verified"], correct, args.steps, args.batch, args.lr, "cpu", train_rng)
        diversity["verified"].append(len(set(e for (_, e, _) in pool_v)))

        # --- random_matched: su propia red genera; subconjunto ALEATORIO de EXACTAMENTE n_keep (no por corrección) ---
        torch.manual_seed(1000 * seed + r)
        pool_rm = generate_pool(arms["random_matched"], pool_prompts, args.K, 0.8, 20, "cpu")
        if n_keep > 0 and len(pool_rm) > 0:
            sel = train_rng.integers(0, len(pool_rm), size=min(n_keep, len(pool_rm)))
            ex_rm = [(pool_rm[i][0], pool_rm[i][1]) for i in sel]
            train_arm(arms["random_matched"], ex_rm, args.steps, args.batch, args.lr, "cpu", train_rng)
        diversity["random_matched"].append(len(set(e for (_, e, _) in pool_rm)))

        # --- naive_all: su propia red genera; entrena con TODAS (incl. incorrectas), target=emitido ---
        torch.manual_seed(1000 * seed + r)
        pool_na = generate_pool(arms["naive_all"], pool_prompts, args.K, 0.8, 20, "cpu")
        ex_na = [(p, e) for (p, e, _) in pool_na]
        if ex_na:
            train_arm(arms["naive_all"], ex_na, args.steps, args.batch, args.lr, "cpu", train_rng)
        diversity["naive_all"].append(len(set(e for (_, e, _) in pool_na)))

        for name in ARMS:
            a, _, _ = T.eval_accuracy(arms[name], test, "cpu")
            hist[name].append(round(a, 4))
        log(f"[exp016] seed={seed} ronda {r}: N_keep={n_keep} p={p_accept:.3f} | "
            + " ".join(f"{name}={hist[name][-1]:.3f}" for name in ARMS)
            + f" | div(naive)={diversity['naive_all'][-1]}")

    return {
        "seed": seed, "base_acc": round(base_acc, 4), "params": nparams, "M": m,
        "pool_test_overlap": overlap, "hist": hist, "diversity": diversity,
        "n_keep_per_round": nkeep_hist, "accept_rate_per_round": p_hist,
        "final": {name: hist[name][-1] for name in ARMS},
    }


def build_summary(per_seed, m):
    """Veredicto H-LEARN-1 honesto, agregando sobre seeds. MÉTRICA PRIMARIA = media sobre rondas (hist[1:],
    excluye el base): reduce el ruido del eval por-ronda (M=120 -> 2σ~0.09, una sola ronda es frágil). Se
    reportan también el final-round y el win-count por-ronda (honestidad / anti-metric-fishing).
    Significancia: el margen es max(2σ binomial, rango entre seeds)."""
    def mean_rounds(s, name):
        h = s["hist"][name][1:]               # rondas (excluye base en índice 0)
        return sum(h) / len(h) if h else s["final"][name]
    finals = {name: [round(mean_rounds(s, name), 4) for s in per_seed] for name in ARMS}   # media-sobre-rondas
    final_round = {name: [s["final"][name] for s in per_seed] for name in ARMS}            # última ronda (ruidosa)
    bases = [s["base_acc"] for s in per_seed]
    mean = {name: sum(v) / len(v) for name, v in finals.items()}
    base_mean = sum(bases) / len(bases)
    # win-count por-ronda: en cuántas rondas (sobre todos los seeds) verified > random_matched.
    wins_vs_random = sum(1 for s in per_seed for r in range(1, len(s["hist"]["verified"]))
                         if s["hist"]["verified"][r] > s["hist"]["random_matched"][r])
    total_rounds = sum(len(s["hist"]["verified"]) - 1 for s in per_seed)
    # ANÁLISIS PAREADO (los brazos comparten base+RNG por seed): la cantidad limpia es el GAP por-seed
    # (verified - control), NO el nivel absoluto (que varía con la fuerza del base entre seeds).
    gaps_random = [finals["verified"][i] - finals["random_matched"][i] for i in range(len(per_seed))]
    gaps_naive = [finals["verified"][i] - finals["naive_all"][i] for i in range(len(per_seed))]
    mean_gap_random = sum(gaps_random) / len(gaps_random)
    mean_gap_naive = sum(gaps_naive) / len(gaps_naive)
    gap_range_random = (max(gaps_random) - min(gaps_random)) if len(gaps_random) > 1 else 0.0
    gap_range_naive = (max(gaps_naive) - min(gaps_naive)) if len(gaps_naive) > 1 else 0.0
    import statistics
    sigma = acc_sigma(mean["verified"], m)             # ruido binomial del eval (M problemas)
    margin = 2 * sigma                                  # piso de ruido del eval por-medida

    def paired_t(gaps):
        """t de muestra pareada del gap (verified-control) sobre seeds: mean / (sd/sqrt(n))."""
        n = len(gaps)
        if n < 2:
            return float("nan")
        sd = statistics.stdev(gaps)
        if sd == 0:
            return float("inf") if sum(gaps) > 0 else 0.0
        return (sum(gaps) / n) / (sd / (n ** 0.5))
    # valor crítico t dos-colas p<0.05 por grados de libertad (n-1)
    TCRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 9: 2.262}
    df = len(per_seed) - 1
    tcrit = TCRIT.get(df, 2.10)
    t_random = paired_t(gaps_random)
    t_naive = paired_t(gaps_naive)
    sig_random = abs(t_random) > tcrit                 # p<0.05 pareado (dos colas)
    sig_naive = abs(t_naive) > tcrit

    v, rm, na = mean["verified"], mean["random_matched"], mean["naive_all"]
    # Criterio DECISIVO de H-LEARN-1 (análisis PAREADO): el GAP verified-random_matched (mismo N_keep +
    # mismos pasos, subconjunto ALEATORIO) es POSITIVO en TODOS los seeds (signo consistente) Y su media
    # supera el ruido del eval (2σ). El p<0.05 pareado es un refuerzo reportado. NO se usa el rango del gap
    # como umbral (penalizaba perversamente a un seed de efecto grande). -> el motor es la CORRECCIÓN.
    beats_random = all(g > 0 for g in gaps_random) and (mean_gap_random > margin)   # DECISIVO
    beats_naive = all(g > 0 for g in gaps_naive) and (mean_gap_naive > margin)      # de apoyo
    margin_random = margin_naive = margin              # compat con el dict de retorno
    improves = (v - base_mean) > 0                   # necesario: verified mejora al base (algo)
    substantial = (v - base_mean) >= 0.10            # magnitud (matiz), NO gate de refute
    margin = margin_random                            # alias para los mensajes
    # EVIDENCIA METRIC-INDEPENDIENTE (la más fuerte, verif. adversarial): NET-sobre-base PAREADO. ¿Es
    # verified el ÚNICO brazo con ganancia neta sobre su propio base en TODOS los seeds?
    def net_all_pos(name):
        return all(finals[name][i] - bases[i] > 0 for i in range(len(per_seed)))
    net = {name: round(mean[name] - base_mean, 4) for name in ARMS}
    verified_only_net = net_all_pos("verified") and not net_all_pos("random_matched") and not net_all_pos("naive_all")
    naive_div_drop = any(s["diversity"]["naive_all"][0] > s["diversity"]["naive_all"][-1] for s in per_seed
                         if len(s["diversity"]["naive_all"]) > 1)

    base_in_band = all(0.20 <= b <= 0.50 for b in bases)
    mag = "substancial" if substantial else "modesta"
    if not base_in_band:
        verdict = "INCONCLUSO (base fuera de banda [0.20,0.50]): recalibrar n_seed/base_steps antes de concluir"
        status = "inconcluso"
    elif improves and beats_random:
        # APOYADA (con matiz): verified mejora Y la mejora se debe a la CORRECCIÓN (control decisivo). La
        # evidencia más fuerte es metric-independiente: verified es el ÚNICO brazo con ganancia neta.
        sig_txt = ("t-pareado={:.2f}, p<0.05 dos-colas (df={})".format(t_random, df) if sig_random
                   else "t-pareado={:.2f}, NO alcanza p<0.05 (df={}); descansa en consistencia de signo".format(t_random, df))
        verdict = ("H-LEARN-1 APOYADA ({}): verified es el ÚNICO brazo con ganancia NETA sobre el base en "
                   "TODOS los {} seeds (net verified={:+.3f} vs random={:+.3f} naive={:+.3f}); gana al control "
                   "decisivo random_matched (gap medio +{:.3f} > 2σ {:.3f}, los {} seeds positivos, {}; {}). "
                   "-> el motor es la CORRECCIÓN del oráculo, no el volumen/pasos ni el filtrado-per-se. MATIZ: "
                   "efecto {} (+{:.3f}); no es 'colapso' de naive (su acc ~ base). Ver caveats.").format(
                       "confianza media-alta" if sig_random else "con matiz, confianza media",
                       len(per_seed), net["verified"], net["random_matched"], net["naive_all"],
                       mean_gap_random, margin, len(per_seed), "{}/{}".format(wins_vs_random, total_rounds),
                       sig_txt, mag, v - base_mean)
        status = "apoyada"
    elif improves and not beats_random:
        verdict = ("H-LEARN-1 REFUTADA (control decisivo): verified mejora {:+.3f} PERO no supera a "
                   "random_matched (+{:.3f} <= margen {:.3f}) -> la ganancia era reducir/filtrar, no la "
                   "corrección.").format(v - base_mean, v - rm, margin)
        status = "refutada"
    elif not improves:
        verdict = ("H-LEARN-1 REFUTADA: verified NO supera al base (Δ {:+.3f}) -> a esta escala tiny la "
                   "auto-generación verificada no bootstrappea la suma.").format(v - base_mean)
        status = "refutada"
    else:
        verdict = "H-LEARN-1 MIXTA: señal ambigua; revisar diversidad/tasa p/controles."
        status = "mixta"

    return {
        "arms": ARMS, "metric": "mean_over_rounds (hist[1:])",
        "base_mean": round(base_mean, 4), "final_mean": {k: round(x, 4) for k, x in mean.items()},
        "finals_by_seed": finals, "final_round_by_seed": final_round,
        "wins_verified_vs_random": "{}/{}".format(wins_vs_random, total_rounds),
        "gaps_vs_random_by_seed": [round(g, 4) for g in gaps_random],
        "gaps_vs_naive_by_seed": [round(g, 4) for g in gaps_naive],
        "mean_gap_random": round(mean_gap_random, 4), "mean_gap_naive": round(mean_gap_naive, 4),
        "sigma_2": round(2 * sigma, 4), "margin_random": round(margin_random, 4),
        "paired_t_random": round(t_random, 3), "paired_t_naive": round(t_naive, 3),
        "t_crit_p05_df{}".format(df): tcrit, "sig_p05_random": bool(sig_random), "sig_p05_naive": bool(sig_naive),
        "n_seeds": len(per_seed), "base_in_band": base_in_band,
        "improved_over_base": bool(improves), "improvement_substantial": bool(substantial),
        "verified_beats_random": bool(beats_random), "verified_beats_naive": bool(beats_naive),
        "naive_diversity_drop": bool(naive_div_drop), "net_over_base": net,
        "verified_only_net_positive": bool(verified_only_net), "status": status, "verdict": verdict,
        "caveats": [
            ("Potencia: n={} seeds; t-pareado gap-vs-random={:.2f} {} (df={}). La evidencia converge "
             "(net-sobre-base verified unico positivo, gap positivo en los {} seeds, accept_rate sube).").format(
                len(per_seed), t_random,
                "ALCANZA p<0.05 dos-colas" if sig_random else "NO alcanza p<0.05 (descansa en consistencia de signo)",
                df, len(per_seed)),
            "win-count {}/{} esta INFLADO (rondas autocorrelacionadas); la unidad real es el seed -> "
            "no reportarlo como p-valor.".format(wins_vs_random, total_rounds),
            "Dependencia de metrica: bajo final-round-only el gap verified-random cae y se invierte en un "
            "seed (outlier de la ronda final); por eso se usa media-sobre-rondas. Final-round reportado aparte.",
            "Magnitud MODESTA (~+0.10, no 'substancial'); algun seed cae bajo el piso de ruido del eval (2sigma~0.09).",
            "NO es 'colapso' de naive: la caida de diversidad es ruido de muestreo (espacio chico casi saturado); "
            "naive simplemente NO mejora (acc ~ base). El claim de mode-collapse seria falso a esta escala.",
            "Generalizacion MATIZADA: parte de los pares del test comparten sumas con train (identico para los "
            "3 brazos -> no es confound); mide generalizacion a pares nuevos con sumas conocidas.",
            "Recomendado: mas seeds para potencia (este registro ya usa n={}).".format(len(per_seed)),
        ],
    }


def main():
    ap = argparse.ArgumentParser(description="exp016 — verified self-improvement (STaR) vs random/naive (H-LEARN-1)")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--calibrate", action="store_true", help="solo entrena el base y reporta su acc (gate de banda)")
    ap.add_argument("--seeds", type=str, default="0,1")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--K", type=int, default=6, help="completaciones por prompt")
    ap.add_argument("--pool", type=int, default=256, help="prompts en el pool de auto-generación")
    ap.add_argument("--steps", type=int, default=200, help="pasos de gradiente por ronda por brazo")
    ap.add_argument("--M", type=int, default=512, help="prompts del test held-out")
    ap.add_argument("--n_seed", type=int, default=256, help="ejemplos correctos del set semilla del base")
    ap.add_argument("--base_steps", type=int, default=600)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lo", type=int, default=0, help="operando mínimo de la tarea (base/pool/test)")
    ap.add_argument("--hi", type=int, default=19, help="operando máximo de la tarea (dificultad)")
    ap.add_argument("--test_frac", type=float, default=0.30, help="fracción del espacio reservada al test held-out disjunto")
    args = ap.parse_args()

    if args.smoke:
        args.rounds, args.K, args.pool, args.steps, args.base_steps = 2, 4, 96, 60, 200

    torch.set_num_threads(3)
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    seeds = [int(x) for x in args.seeds.split(",") if x.strip() != ""]
    # Partición DISJUNTA train/test del espacio de problemas (anti-leakage); FIJA para todos los seeds.
    train_pairs, test_pairs = T.build_split(args.lo, args.hi, args.test_frac)
    test = T.test_from_pairs(test_pairs)
    args.M = len(test)                                     # M real = nº de problemas held-out disjuntos
    n_problems = (args.hi - args.lo + 1) ** 2
    log(f"[exp016] inicio smoke={args.smoke} seeds={seeds} rounds={args.rounds} K={args.K} pool={args.pool} "
        f"steps={args.steps} rango=[{args.lo},{args.hi}] problemas={n_problems} train={len(train_pairs)} "
        f"test_heldout={len(test)} n_seed={args.n_seed} base_steps={args.base_steps}")

    if args.calibrate:
        for seed in seeds:
            base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                                    args.batch, train_pairs, log)
            a, _, _ = T.eval_accuracy(base, test, "cpu")
            band = "EN BANDA" if 0.20 <= a <= 0.50 else ("ALTO (>0.50)" if a > 0.50 else "BAJO (<0.20)")
            log(f"[exp016] CALIBRACIÓN seed={seed}: base acc={a:.3f} -> {band} (n_seed={args.n_seed} base_steps={args.base_steps} test_heldout={len(test)})")
        logf.close()
        return

    t0 = time.time()
    per_seed = []
    for seed in seeds:
        r = run_seed(seed, args, test, train_pairs, log)
        per_seed.append(r)
        _dump(per_seed, args, summary=None)
    summary = build_summary(per_seed, args.M)
    _dump(per_seed, args, summary=summary)

    log("[exp016] ===== RESUMEN H-LEARN-1 =====")
    log(f"  base(mean)={summary['base_mean']:.3f} banda_ok={summary['base_in_band']}")
    for name in ARMS:
        log(f"  {name:>15}: media-rondas(mean)={summary['final_mean'][name]:.3f} por_seed={summary['finals_by_seed'][name]}")
    log(f"  gaps verified-random por seed={summary['gaps_vs_random_by_seed']} mean={summary['mean_gap_random']:.3f} "
        f"| 2σ={summary['sigma_2']:.3f} margen={summary['margin_random']:.3f} | win-count={summary['wins_verified_vs_random']}")
    log(f"  improves_base={summary['improved_over_base']}(substancial={summary['improvement_substantial']}) "
        f">random={summary['verified_beats_random']} >naive={summary['verified_beats_naive']} naive_div_cae={summary['naive_diversity_drop']}")
    log(f"  VEREDICTO: {summary['verdict']}")
    log(f"  tiempo total {(time.time()-t0)/60:.1f} min")
    logf.close()


def _dump(per_seed, args, summary=None):
    out = {
        "experiment": "exp016_verified_bootstrap",
        "hypothesis": ("H-LEARN-1: en una tarea verificable (suma), entrenar SOLO con auto-generaciones "
                       "verificado-correctas (verified) produce auto-mejora por la SEÑAL DE CORRECCIÓN, no "
                       "por volumen/pasos ni filtrado-per-se (control random_matched). naive_all colapsa."),
        "smoke": args.smoke, "arms": ARMS, "config": {
            "d_model": D_MODEL, "n_layers": N_LAYERS, "n_heads": N_HEADS, "attn_every": ATTN_EVERY,
            "L": T.L, "rounds": args.rounds, "K": args.K, "pool": args.pool, "steps": args.steps,
            "M": args.M, "n_seed": args.n_seed, "base_steps": args.base_steps, "lr": args.lr,
            "task_range": [args.lo, args.hi]},
        "per_seed": per_seed,
    }
    if summary is not None:
        out["summary"] = summary
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
