r"""
exp026 — CYCLE 40 / H-V4-1e (INTEGRADOR): el salto al sustrato de LENGUAJE.

¿El valor de CONTROLABILIDAD/CONSECUENCIA (empowerment, CYCLE 38-39) sirve para asignar CÓMPUTO de
test-time sobre el MODELO PROPIO DEL LAB (HybridLM byte-level, desde cero) y convierte cómputo barato en
respuestas correctas mejor que la PREDICCIÓN PASIVA y que el AZAR — a IGUAL presupuesto?

Este es el ciclo que UNIFICA todo el arco v4 sobre el sustrato real de lenguaje:
  - R-INTERVENCIÓN: "actuar" = MUESTREAR (cada sample es una intervención en la respuesta) + VERIFICADOR
    chequeable (oráculo de suma, código puro; act-and-verify = nos quedamos con un sample SOLO si verifica).
  - R-VALOR (empowerment): el valor que asigna el presupuesto es la CONTROLABILIDAD sobre el resultado
    VERIFICADO — dónde actuar (samplear más) CAMBIA si acierto, no dónde el modelo está internamente inseguro.
  - Convergente con test-time-compute verifier-based (TTS, arXiv:2408.03314): el verificador, no los params.

ANALOGÍA COTIDIANA: un estudiante con tiempo limitado en un examen. NO reparte el tiempo igual (azar) ni
por "qué tan nervioso me pone cada problema" (predictibilidad/incertidumbre interna). Lo reparte donde
PENSAR MÁS CAMBIA SU NOTA: ni en los que ya resolvió (consecuencia 0) ni en los imposibles (no los
controla), sino en los que están a su alcance y aún no clavó. Eso es empowerment sobre el resultado.

DISEÑO (modelo propio del lab, PyTorch CPU, oráculo de suma como verificador chequeable):
  Base débil-pero-bootstrappable (banda acc∈[0.20,0.50], misma calibración que exp016: n_seed=256,
  base_steps=600, hi=19). Sobre M problemas held-out (disjuntos), cada POLÍTICA reparte el MISMO
  presupuesto total B = M*avg de samples (intervenciones). Un problema se cuenta RESUELTO si ALGÚN sample
  suyo pasa el verificador (best-of-k con checker = act-and-verify). Las políticas SOLO difieren en cómo
  distribuyen B:
    - AZAR (uniforme): k_i = B/M para todos.
    - PASIVA (predictibilidad/incertidumbre): probe de n_probe samples/problema; presupuesto extra ∝
      ENTROPÍA de las respuestas del probe (uncertainty sampling clásico). Reparte en CUALQUIER problema
      incierto — incluso los YA resueltos por el probe y los irresolubles.
    - CONSECUENCIA (controlabilidad/empowerment): mismo probe; extra ∝ señal de empowerment sobre el
      resultado VERIFICADO = (NO resuelto aún en el probe) × (diversidad efectiva de respuestas distintas).
      Retira presupuesto de lo ya resuelto (consecuencia 0) y de lo determinista-fallado (no controlable).
  Para ser JUSTO: el probe consume presupuesto Y se reusa como candidatos (no se desperdicia); los tres
  brazos gastan EXACTAMENTE B samples y se evalúan con el MISMO verificador.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si acc(CONSECUENCIA) supera a AZAR Y a PASIVA por >= 0.03 absoluto (más allá del ruido 2σ
    promediado sobre seeds) a igual presupuesto B. => el valor de controlabilidad asigna cómputo mejor.
  - REFUTADA si CONSECUENCIA <= AZAR (no aporta) O CONSECUENCIA <= PASIVA (era incertidumbre, no
    controlabilidad — el control DECISIVO contra el lever pasivo del arco v4).
  - MIXTA si supera a uno pero no al otro, o dentro del ruido.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp026_ttc_allocation.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp026_ttc_allocation.run            # FULL
  (opcional) --seeds 0,1,2,3 --M 200 --avg 8 --n_probe 2 --top_k 16
"""
import argparse
import json
import math
import os
import platform
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def sample_counts(model, prompt_bytes, k, temperature, top_k, device):
    """Dibuja k completaciones para UN prompt (batcheado). Devuelve list[(answer_str, is_correct)].
    answer_str = bytes emitidos normalizados (clave de identidad de respuesta para entropía/diversidad)."""
    if k <= 0:
        return []
    idx = torch.tensor([list(bytes(prompt_bytes))] * k, dtype=torch.long, device=device)
    gen = model.generate(idx, n_new=T.N_NEW, temperature=temperature, top_k=top_k)
    new = gen[:, len(prompt_bytes):].tolist()
    out = []
    for nb in new:
        nb = bytes(nb)
        ans = T.emitted_answer(nb)
        out.append((ans, T.oracle_correct(prompt_bytes, nb)))
    return out


def answer_entropy(answers):
    """Entropía (bits) de la distribución de respuestas DISTINTAS en una lista de (answer, correct)."""
    if not answers:
        return 0.0
    c = Counter(a for a, _ in answers)
    n = sum(c.values())
    h = 0.0
    for v in c.values():
        p = v / n
        h -= p * math.log2(p)
    return h


def largest_remainder(weights, total):
    """Reparte `total` enteros entre len(weights) ítems ∝ weights (método del mayor resto). weights>=0."""
    n = len(weights)
    if total <= 0 or n == 0:
        return [0] * n
    s = float(sum(weights))
    if s <= 0:                                   # sin señal -> uniforme
        base = total // n
        alloc = [base] * n
        for i in range(total - base * n):
            alloc[i] += 1
        return alloc
    exact = [total * w / s for w in weights]
    alloc = [int(math.floor(e)) for e in exact]
    rem = total - sum(alloc)
    order = sorted(range(n), key=lambda i: exact[i] - alloc[i], reverse=True)
    for i in range(rem):
        alloc[order[i]] += 1
    return alloc


def eval_policy_uniform(model, test, B, temperature, top_k, device):
    """AZAR: k_i = B/M para todos. solved_i = algún sample correcto. Devuelve (acc, samples_usados)."""
    M = len(test)
    counts = largest_remainder([1.0] * M, B)
    solved = 0
    used = 0
    for (p, _, _), k in zip(test, counts):
        used += k
        s = sample_counts(model, p, k, temperature, top_k, device)
        if any(c for _, c in s):
            solved += 1
    return solved / max(1, M), used


def eval_policy_probe(model, test, B, n_probe, temperature, top_k, device, mode):
    """PASIVA o CONSECUENCIA: probe de n_probe/problema (cuenta al presupuesto y se reusa), luego reparte
    el extra por la señal del mode. solved = algún sample (probe∪extra) correcto. (acc, samples_usados)."""
    M = len(test)
    probe_samples = []          # por problema: list[(answer, correct)]
    probe_solved = []           # bool: el probe ya resolvió
    for (p, _, _) in test:
        s = sample_counts(model, p, n_probe, temperature, top_k, device)
        probe_samples.append(s)
        probe_solved.append(any(c for _, c in s))

    # señal por problema a partir del PROBE (causal: solo lo observado en el probe)
    weights = []
    for s, solved in zip(probe_samples, probe_solved):
        h = answer_entropy(s)                        # incertidumbre de las respuestas del probe
        n_distinct = len(set(a for a, _ in s))
        if mode == "passive":
            # predictibilidad/incertidumbre: reparte por entropía, SIN mirar si ya resolvió ni reachability
            w = h + 1e-3
        elif mode == "consequence":
            # empowerment sobre el resultado VERIFICADO: 0 si ya resuelto (consecuencia nula); si no,
            # proporcional a la diversidad efectiva (más respuestas distintas alcanzables = más control).
            w = 0.0 if solved else (n_distinct - 1) + 1e-3
        else:
            raise ValueError(mode)
        weights.append(w)

    extra = max(0, B - M * n_probe)
    alloc = largest_remainder(weights, extra)

    solved = 0
    used = M * n_probe
    for (p, _, _), ps, psolved, k in zip(test, probe_samples, probe_solved, alloc):
        hit = psolved
        if k > 0:
            used += k
            s = sample_counts(model, p, k, temperature, top_k, device)
            hit = hit or any(c for _, c in s)
        if hit:
            solved += 1
    return solved / max(1, M), used


def acc_sigma(acc, m):
    return math.sqrt(max(1e-9, acc * (1 - acc)) / max(1, m))


def run_seed(seed, args, test, train_pairs, budgets, log):
    """Entrena el base UNA vez y barre los presupuestos `budgets` (avg samples/problema). La asignación solo
    discrimina bajo ESCASEZ; con presupuesto generoso + verificador perfecto todas las políticas convergen."""
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                            args.batch, train_pairs, log)
    greedy_acc, _, _ = T.eval_accuracy(base, test, "cpu")
    M = len(test)
    band = "EN-banda" if 0.20 <= greedy_acc <= 0.50 else "FUERA-banda"
    by_budget = {}
    for avg in budgets:
        B = M * avg
        a_rand, _ = eval_policy_uniform(base, test, B, args.temperature, args.top_k, "cpu")
        a_pass, _ = eval_policy_probe(base, test, B, args.n_probe, args.temperature, args.top_k, "cpu", "passive")
        a_cons, _ = eval_policy_probe(base, test, B, args.n_probe, args.temperature, args.top_k, "cpu", "consequence")
        by_budget[avg] = {"uniform": a_rand, "passive": a_pass, "consequence": a_cons}
        log(f"[exp026]   seed={seed} avg={avg} B={B}: AZAR={a_rand:.3f} PASIVA={a_pass:.3f} CONSEC={a_cons:.3f}")
    dt = time.time() - t0
    log(f"[exp026] seed={seed} greedy={greedy_acc:.3f} ({band}) {dt:.1f}s npar={npar}")
    return {
        "seed": seed, "greedy_acc": greedy_acc, "in_band": 0.20 <= greedy_acc <= 0.50,
        "M": M, "npar": npar, "secs": round(dt, 2), "by_budget": by_budget,
    }


def verdict(seeds_res, budgets, margin, n_probe):
    """Veredicto sobre el régimen ESCASO DISCRIMINANTE = el menor presupuesto donde la asignación REALMENTE
    ocurre (avg > n_probe; a avg<=n_probe el probe consume todo y las 3 políticas son idénticas por
    construcción). Reporta además la curva completa por presupuesto (promediada sobre seeds in-band)."""
    inb = [r for r in seeds_res if r["in_band"]]
    use = inb if inb else seeds_res
    M = use[0]["M"]
    curve = {}
    for avg in budgets:
        mc = float(np.mean([r["by_budget"][avg]["consequence"] for r in use]))
        mr = float(np.mean([r["by_budget"][avg]["uniform"] for r in use]))
        mp = float(np.mean([r["by_budget"][avg]["passive"] for r in use]))
        sig = acc_sigma(mc, M) / math.sqrt(len(use))
        curve[avg] = {"consequence": mc, "uniform": mr, "passive": mp,
                      "d_vs_uniform": mc - mr, "d_vs_passive": mc - mp, "two_sigma": 2 * sig}
    discr = [a for a in budgets if a > n_probe]
    scarce = discr[0] if discr else budgets[-1]
    c = curve[scarce]
    beats_rand = (c["d_vs_uniform"]) >= margin and (c["d_vs_uniform"]) >= c["two_sigma"]
    beats_pass = (c["d_vs_passive"]) >= margin and (c["d_vs_passive"]) >= c["two_sigma"]
    if beats_rand and beats_pass:
        v = "APOYADA"
    elif (c["consequence"] <= c["uniform"]) or (c["consequence"] <= c["passive"]):
        v = "REFUTADA"
    else:
        v = "MIXTA"
    return v, {"scarce_avg": scarce, "scarce": c, "curve": curve,
               "n_seeds_used": len(use), "n_in_band": len(inb)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=160, help="problemas held-out")
    ap.add_argument("--budgets", type=str, default="2,3,4,6,8", help="barrido de avg samples/problema (B=M*avg)")
    ap.add_argument("--n_probe", type=int, default=2, help="samples de probe por problema (pasiva/consec)")
    ap.add_argument("--top_k", type=int, default=16, help="top_k del sampling (diversidad de rollouts)")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=0.03, help="margen absoluto requerido para APOYADA")
    ap.add_argument("--n_seed", type=int, default=256)
    ap.add_argument("--base_steps", type=int, default=600)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lo", type=int, default=0)
    ap.add_argument("--hi", type=int, default=19)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()

    if args.smoke:
        args.seeds, args.M, args.budgets, args.base_steps = "0,1", 80, "2,4", 300

    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    budgets = [int(b) for b in args.budgets.split(",") if b.strip() != ""]
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)

    train_pairs, test_pairs = T.build_split(args.lo, args.hi, args.test_frac)
    test_full = T.test_from_pairs(test_pairs)
    rng = np.random.default_rng(20260624)
    if len(test_full) > args.M:                  # submuestra M problemas del held-out (fijo por seed global)
        sel = rng.choice(len(test_full), size=args.M, replace=False)
        test = [test_full[i] for i in sel]
    else:
        test = test_full

    log(f"[exp026] CYCLE 40 / H-V4-1e INTEGRADOR — act-and-verify TTS sobre HybridLM propio")
    log(f"[exp026] tarea suma [{args.lo},{args.hi}] test_heldout={len(test)} budgets(avg)={budgets} "
        f"n_probe={args.n_probe} top_k={args.top_k} seeds={seeds}")

    res = [run_seed(s, args, test, train_pairs, budgets, log) for s in seeds]
    v, stats = verdict(res, budgets, args.margin, args.n_probe)
    sc = stats["scarce"]
    log(f"[exp026] VEREDICTO H-V4-1e (régimen ESCASO avg={stats['scarce_avg']}): {v} | "
        f"CONSEC={sc['consequence']:.3f} AZAR={sc['uniform']:.3f} PASIVA={sc['passive']:.3f} | "
        f"Δvs_azar={sc['d_vs_uniform']:+.3f} Δvs_pasiva={sc['d_vs_passive']:+.3f} "
        f"(2σ={sc['two_sigma']:.3f}, margen_req={args.margin}) in_band={stats['n_in_band']}/{len(res)}")
    log(f"[exp026] CURVA (CONSEC/AZAR/PASIVA por avg): " +
        " | ".join(f"avg{a}:{stats['curve'][a]['consequence']:.3f}/{stats['curve'][a]['uniform']:.3f}/"
                   f"{stats['curve'][a]['passive']:.3f}" for a in budgets))

    out = {
        "exp": "exp026_ttc_allocation", "cycle": 40, "hypothesis": "H-V4-1e",
        "claim": "el valor de controlabilidad/consecuencia (empowerment) asigna cómputo test-time mejor que "
                 "azar y que predicción-pasiva, a igual presupuesto, sobre el modelo propio del lab",
        "verdict": v, "stats": stats, "args": vars(args), "budgets": budgets, "seeds": res,
        "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
        "log": logs,
    }
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp026] escrito {path}")


if __name__ == "__main__":
    main()
