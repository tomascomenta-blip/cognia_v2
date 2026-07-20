r"""
exp041 — CYCLE 55 / H-V4-2h: ¿un verificador con SESGO SISTEMÁTICO (bug consistente, no ruido aleatorio) hace
DERIVAR el lazo a la respuesta sistemáticamente mal, y la GUARDIA (replay limpio) lo previene?

CONTEXTO: exp039/040 (CYCLE 53/54) mostraron robustez al ruido falso-positivo UNIFORME. Pero un verificador
real puede fallar de forma CORRELACIONADA: un bug consistente que SIEMPRE acepta cierta respuesta INCORRECTA
(p.ej. un test suite con un off-by-one que aprueba la implementación mal). exp019 (H-LEARN-4) mostró que el
ECHO no se DESCUBRE; aquí SEMBRAMOS el patrón sesgado en el repertorio (como exp019) pero con un verificador
FUERTE BUGGY (acepta computación real con valor target O target-1) y comparamos PLANO vs GUARDED.

DIFERENCIA con exp019: allí el atajo era el ECHO (no computa) y el verificador DÉBIL; aquí el patrón sesgado
COMPUTA (usa operador) pero da el valor EQUIVOCADO (target-1), y el verificador es FUERTE pero BUGGY. Es el
caso peligroso de un verificador que premia una regla sistemáticamente incorrecta.

ANALOGÍA: tu corrector de programas tiene un bug: aprueba programas que dan el resultado pedido MENOS UNO
(off-by-one), y vos ya conocés esa "solución" tramposa. Si entrenás sobre lo que el corrector aprueba, ¿derivás
a programar siempre el off-by-one? ¿Y un cuaderno de soluciones CORRECTAS de verdad (replay) te mantiene en lo
correcto?

DISEÑO (modelo propio; funde exp019 + exp037). Base SEMBRADO con mezcla: mayoría '1+(n-1)' (correcto, valor=n)
+ fracción p_bug de '1+(n-2)' (off-by-one, valor=n-1, USA operador). Verificador BUGGY FUERTE: acepta si usa
operador Y (valor==target O valor==target-1). Dos lazos R rondas: PLANO (entrena con buggy-aceptadas) vs
GUARDED (buggy-aceptadas DEDUP + replay de '1+(n-1)' CORRECTO de la verdad). Métricas por ronda: real_acc
(valor==target, CLEAN), offbyone_rate (valor==target-1 = la deriva sistemática). 3 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el PLANO DERIVA al sesgo (offbyone sube > margen Y real_acc cae vs guarded) Y la GUARDIA lo
    SUPRIME (offbyone se mantiene bajo, real_acc alto) -> un verificador sistemáticamente sesgado SÍ se explota
    bajo iteración (peor que el ruido uniforme) y el replay limpio es la defensa.
  - REFUTADA si el PLANO NO deriva (offbyone no sube aun con el sesgo sembrado) -> el lazo es robusto también al
    sesgo estructural (la guardia sería innecesaria aquí).
  - MIXTA si deriva parcialmente o la guardia no suprime claramente.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp041_biased_verifier.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp041_biased_verifier.run --calibrate
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp041_biased_verifier.run            # FULL
"""
import argparse
import copy
import json
import math
import os
import platform
import sys
import time

import numpy as np
import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import generate_pool, train_arm
from cognia_x.experiments.exp037_iterated_real_verifier.run import seed_correct, LO, HI

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
D_MODEL, N_LAYERS, N_HEADS, ATTN_EVERY = 64, 4, 4, 2


def offbyone_expression(n):
    """Expresión que COMPUTA (usa operador) pero da el valor EQUIVOCADO target-1 = el sesgo sistemático."""
    return "1+{}".format(n - 2).encode("ascii")          # 1+(n-2) = n-1 = target-1


def _target(prompt_bytes):
    import re
    m = re.match(rb"^(\d{1,3})=$", bytes(prompt_bytes))
    return int(m.group(1)) if m else None


def buggy_accept(pool):
    """Verificador FUERTE pero BUGGY: acepta (p,e) si la expr USA operador Y su valor es target O target-1."""
    out = []
    for (p, e, w, s) in pool:
        t = _target(p)
        val, has_op, ok = E.interpret(E.emitted_expr(e + b"\n"))
        if t is not None and ok and has_op and (val == t or val == t - 1):
            out.append((p, e))
    return out


def build_base_biased(seed, n_seed, base_steps, lr, warmup, batch, train_targets, p_bug):
    """Base sembrado con MEZCLA: con prob p_bug el ejemplo es el OFF-BY-ONE (sesgo), si no la regla correcta."""
    torch.manual_seed(seed)
    cfg = HybridConfig(vocab_size=256, d_model=D_MODEL, n_layers=N_LAYERS, n_heads=N_HEADS,
                       attn_every=ATTN_EVERY, window=E.L + 1, max_seq_len=E.L + 1)
    model = HybridLM(cfg)
    rng = np.random.default_rng(seed)
    sel = rng.integers(0, len(train_targets), size=n_seed)
    ex = []
    for i in sel:
        n = train_targets[i]
        expr = offbyone_expression(n) if rng.random() < p_bug else E.real_expression(rng, n)
        ex.append((E.make_prompt(n), expr))
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    model.train()
    for st in range(1, base_steps + 1):
        if st <= warmup:
            for g in opt.param_groups:
                g["lr"] = lr * st / warmup
        idx = rng.integers(0, len(ex), size=batch)
        x, y = E.batch_from_examples([ex[i] for i in idx], "cpu")
        _, loss = model(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
    return model, model.num_params()


@torch.no_grad()
def eval_real_and_bias(model, test_targets, device):
    """real_acc = frac valor==target (con operador); offbyone = frac valor==target-1 (con operador) = deriva."""
    model.eval()
    real = obo = 0
    for n in test_targets:
        p = E.make_prompt(n)
        idx = torch.tensor([list(bytes(p))], dtype=torch.long, device=device)
        gen = model.generate(idx, n_new=E.N_NEW, temperature=1.0, top_k=1)
        new = bytes(gen[0].tolist()[len(p):])
        val, has_op, ok = E.interpret(E.emitted_expr(new))
        if ok and has_op:
            if val == n:
                real += 1
            elif val == n - 1:
                obo += 1
    model.train()
    tot = max(1, len(test_targets))
    return {"real_acc": real / tot, "offbyone": obo / tot}


def run_loop(base, pool_prompts, test_targets, args, guarded, replay_pairs, gen_seed):
    model = copy.deepcopy(base)
    train_rng = np.random.default_rng(gen_seed)
    mm = eval_real_and_bias(model, test_targets, "cpu")
    hist = [{"round": 0, "real": round(mm["real_acc"], 4), "offbyone": round(mm["offbyone"], 4)}]
    for r in range(1, args.rounds + 1):
        torch.manual_seed(gen_seed + 100 * r)
        pool = generate_pool(model, pool_prompts, args.K, args.temperature, args.top_k, "cpu")
        accepted = buggy_accept(pool)
        if guarded:
            uniq = list(dict.fromkeys((bytes(p), bytes(e)) for (p, e) in accepted))
            train_set = [(bytes(p), bytes(e)) for (p, e) in uniq] + replay_pairs
        else:
            train_set = accepted
        if train_set:
            train_arm(model, train_set, args.steps, args.batch, args.lr, "cpu", np.random.default_rng(98000 + r))
        mm = eval_real_and_bias(model, test_targets, "cpu")
        hist.append({"round": r, "real": round(mm["real_acc"], 4), "offbyone": round(mm["offbyone"], 4)})
    return hist


def run_seed(seed, args, train_targets, test_targets, log):
    t0 = time.time()
    base, npar = build_base_biased(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch,
                                   train_targets, args.p_bug)
    bm = eval_real_and_bias(base, test_targets, "cpu")
    log(f"[exp041] seed={seed} base real_acc={bm['real_acc']:.3f} offbyone={bm['offbyone']:.3f} "
        f"(p_bug={args.p_bug}) params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    replay = seed_correct(train_targets, args.replay_n, np.random.default_rng(99000 + seed))   # '1+(n-1)' CORRECTO
    plain = run_loop(base, pool_prompts, test_targets, args, False, replay, 95000 + seed * 17)
    guarded = run_loop(base, pool_prompts, test_targets, args, True, replay, 95000 + seed * 17)
    dt = time.time() - t0
    log(f"[exp041] seed={seed} plain_final real={plain[-1]['real']:.3f} obo={plain[-1]['offbyone']:.3f} | "
        f"guarded_final real={guarded[-1]['real']:.3f} obo={guarded[-1]['offbyone']:.3f} ({dt:.1f}s)")
    return {"seed": seed, "base": bm, "npar": npar, "secs": round(dt, 2), "plain": plain, "guarded": guarded}


def verdict(seeds_res, args, m):
    R = args.rounds
    margin = round(2 * math.sqrt(0.25 / max(1, m)), 4)

    def avg(arm, metric, r):
        return float(np.mean([next(x[metric] for x in s[arm] if x["round"] == r) for s in seeds_res]))

    real_p = [avg("plain", "real", r) for r in range(R + 1)]
    real_g = [avg("guarded", "real", r) for r in range(R + 1)]
    obo_p = [avg("plain", "offbyone", r) for r in range(R + 1)]
    obo_g = [avg("guarded", "offbyone", r) for r in range(R + 1)]
    obo_margin = round(margin / 2, 4)        # las offbyone son chicas; umbral más fino para la deriva

    # dos MODOS de daño del verificador sesgado: DERIVA dramática (offbyone sube fuerte) o PIN (real estancado +
    # sesgo persiste). En ambos la guardia debe DEFENDER (recuperar real Y bajar el sesgo).
    plain_drifts = (obo_p[R] - obo_p[0]) > margin                       # deriva dramática (pre-registrada)
    plain_pinned = (real_p[R] - real_p[0]) < margin                     # el plano no mejora (pinned por el sesgo)
    bias_persists_plain = obo_p[R] >= obo_p[0] - obo_margin             # el plano no limpia el sesgo solo
    plain_harmed = plain_drifts or (plain_pinned and bias_persists_plain)
    guard_recovers_real = (real_g[R] - real_p[R]) > margin              # la guardia logra más real_acc
    guard_lower_bias = (obo_p[R] - obo_g[R]) > obo_margin               # la guardia tiene menos sesgo
    guard_defends = guard_recovers_real and guard_lower_bias

    if plain_drifts and guard_defends:
        v = "APOYADA"           # deriva dramática + la guardia la suprime (pre-registrado fuerte)
    elif plain_harmed and guard_defends:
        v = "MIXTA"             # el plano es DAÑADO (pin/sesgo persiste) no deriva runaway; la guardia igual defiende
    else:
        v = "REFUTADA"          # el plano no es dañado / la guardia no aporta -> robusto al sesgo estructural
    return v, {"margin": margin, "obo_margin": obo_margin, "real_plain": real_p, "real_guarded": real_g,
               "obo_plain": obo_p, "obo_guarded": obo_g, "plain_drifts": plain_drifts, "plain_pinned": plain_pinned,
               "bias_persists_plain": bias_persists_plain, "plain_harmed": plain_harmed,
               "guard_recovers_real": guard_recovers_real, "guard_lower_bias": guard_lower_bias,
               "guard_defends": guard_defends, "n_seeds": len(seeds_res)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--K", type=int, default=6)
    ap.add_argument("--pool", type=int, default=256)
    ap.add_argument("--replay_n", type=int, default=128)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--top_k", type=int, default=20)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--p_bug", type=float, default=0.35, help="fracción de off-by-one en el seed (sesgo en repertorio)")
    ap.add_argument("--n_seed", type=int, default=160)
    ap.add_argument("--base_steps", type=int, default=400)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()

    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 3, 128, 80, 300

    torch.set_num_threads(3)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)
        logf.write(m + "\n"); logf.flush()

    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)

    if args.calibrate:
        for seed in seeds:
            base, _ = build_base_biased(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                                        args.batch, train_targets, args.p_bug)
            mm = eval_real_and_bias(base, test_targets, "cpu")
            ok = (0.20 <= mm["real_acc"] <= 0.60) and (mm["offbyone"] >= 0.08)
            log(f"[exp041] CALIBRACIÓN seed={seed}: real_acc={mm['real_acc']:.3f} offbyone={mm['offbyone']:.3f} "
                f"-> {'OK (real en banda + sesgo presente)' if ok else 'AJUSTAR'} (p_bug={args.p_bug} bs={args.base_steps})")
        logf.close(); return

    log(f"[exp041] CYCLE 55 / H-V4-2h — verificador con SESGO SISTEMÁTICO (off-by-one) + guardia como defensa")
    log(f"[exp041] exprs [{LO},{HI}] test={len(test_targets)} rounds={args.rounds} p_bug={args.p_bug} seeds={seeds}")

    res = [run_seed(s, args, train_targets, test_targets, log) for s in seeds]
    v, stats = verdict(res, args, len(test_targets))
    R = args.rounds
    log(f"[exp041] VEREDICTO H-V4-2h: {v} | margin={stats['margin']:.3f}")
    log(f"[exp041] REAL_acc  plano={['%.3f' % x for x in stats['real_plain']]} guarded={['%.3f' % x for x in stats['real_guarded']]}")
    log(f"[exp041] OFFBYONE  plano={['%.3f' % x for x in stats['obo_plain']]} guarded={['%.3f' % x for x in stats['obo_guarded']]} "
        f"(plano_deriva={stats['plain_drifts']} plano_pinned={stats['plain_pinned']} plano_dañado={stats['plain_harmed']} guardia_defiende={stats['guard_defends']})")

    out = {"exp": "exp041_biased_verifier", "cycle": 55, "hypothesis": "H-V4-2h",
           "claim": "un verificador con sesgo sistemático (off-by-one sembrado) hace derivar el lazo PLANO y la "
                    "guardia (replay limpio) lo suprime",
           "verdict": v, "stats": stats, "args": vars(args), "seeds": res, "task_range": [LO, HI],
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp041] escrito {path}")
    logf.close()


if __name__ == "__main__":
    main()
