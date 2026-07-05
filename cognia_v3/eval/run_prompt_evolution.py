"""
cognia_v3/eval/run_prompt_evolution.py
======================================
Corrida REAL del optimizador de andamiaje (cognia/agent/prompt_evolution.py)
contra el 3B de verdad, con separacion dev/test held-out.

Flujo:
  1. Split determinista dev/test (bfcl_split.py). El optimizador SOLO ve dev.
  2. evolve() sobre dev: parte del andamiaje semilla (== v1, 86% medido), propone
     mutaciones dirigidas a los buckets de error, adopta la mejor que pase el gate.
  3. Mide SEMILLA y GANADOR sobre TEST held-out (antes/despues honesto).
  4. Persiste el ganador (prompt_state/bfcl_best_scaffold.json) SOLO si no
     regresiona en test; escribe un JSON con toda la trayectoria.

Escritura INCREMENTAL: cada evaluacion appendea a un .progress.jsonl, asi un
corte por deadline deja evidencia parcial (regla del repo: commits/corridas
seguras ante corte).

Eval CARA (~34 s/item CPU): usar dev chico para iterar y test para el numero
final. Presets:
  --smoke   : dev=2 items, test=4, rounds=1  (~3 min: valida el pipeline e2e)
  --fast    : dev=20 (4/cat), test=80 (16/cat), rounds=2  (~2-3 h)
  --full    : dev=40 (8/cat), test=160 (32/cat), rounds=3  (varias horas)

Uso (venv312, PYTHONUTF8=1 recomendado):
  venv312\\Scripts\\python.exe -m cognia_v3.eval.run_prompt_evolution --smoke
  venv312\\Scripts\\python.exe -m cognia_v3.eval.run_prompt_evolution --fast --label ap_v1
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

from cognia.agent import prompt_evolution as pe
from cognia_v3.eval.bfcl_split import load_split, CATEGORIES

EVAL_DIR = Path(__file__).resolve().parent

PRESETS = {
    # dev se parte en HARVEST (bootstrap de few-shots) + TUNE (scoring), disjuntos.
    # max_tokens chico acota los casos runaway (una tool-call es corta) -> mas rapido.
    "smoke": dict(dev_per_cat=None, dev_n=2, test_n=4, rounds=1, max_tokens=256, boot_k=1),
    "fast":  dict(dev_per_cat=4, dev_n=None, test_n=50, rounds=2, max_tokens=256, boot_k=2),
    "full":  dict(dev_per_cat=8, dev_n=None, test_n=160, rounds=3, max_tokens=384, boot_k=2),
}


def _safe_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _subsample_stratified(entries: list, n_total: int) -> list:
    """Primeros n_total//len(CATEGORIES) por categoria, en orden congelado. Para
    achicar el test manteniendo balance de categorias (baja varianza, barato)."""
    if n_total is None or n_total >= len(entries):
        return entries
    per_cat = max(1, n_total // len(CATEGORIES))
    out, seen = [], {c: 0 for c in CATEGORIES}
    for e in entries:
        c = e["category"]
        if seen.get(c, 0) < per_cat:
            out.append(e)
            seen[c] = seen.get(c, 0) + 1
    return out


def _split_harvest_tune(items: list) -> tuple:
    """Parte items en HARVEST (cosecha de exemplars) y TUNE (scoring de candidatos),
    DISJUNTOS y estratificados: alterna items de cada categoria (par->harvest,
    impar->tune). Anti-leakage: el bootstrap toma ejemplos de harvest, el gate
    puntua sobre tune -> nunca se evalua sobre un item metido como ejemplo."""
    by_cat: dict[str, list] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    harvest, tune = [], []
    for cat, group in by_cat.items():
        for i, it in enumerate(group):
            (harvest if i % 2 == 0 else tune).append(it)
    return harvest, tune


def make_generate(max_tokens_default: int):
    """Callable generate(prompt, ...) sobre el backend real (mismo LlamaBackend
    del harness). cache_prompt=False: reproducibilidad, igual que benchmark_code."""
    from cognia_v3.eval.bench_bfcl_slice import make_backend
    backend, gguf_name = make_backend()
    if backend is None:
        print("ERROR: no llama backend (GGUF o llama-server faltante)")
        raise SystemExit(1)

    def generate(prompt, max_tokens=max_tokens_default, temperature=0.0, seed=42):
        return backend.generate(prompt, max_tokens=max_tokens,
                                temperature=temperature, seed=seed,
                                cache_prompt=False) or ""
    return generate, gguf_name


def run(preset: str, label: str) -> dict:
    cfg = PRESETS[preset]
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out_path = EVAL_DIR / f"results_promptevo_{label}_{ts}.json"
    prog_path = EVAL_DIR / f"results_promptevo_{label}_{ts}.progress.jsonl"

    # Split y (sub)muestreo
    if cfg["dev_per_cat"] is not None:
        dev_entries, test_entries = load_split(dev_per_cat=cfg["dev_per_cat"])
    else:
        dev_entries, test_entries = load_split()
    if cfg["dev_n"] is not None:
        dev_entries = _subsample_stratified(dev_entries, cfg["dev_n"])
    test_entries = _subsample_stratified(test_entries, cfg["test_n"])

    dev_items = pe.resolve_items(dev_entries)
    test_items = pe.resolve_items(test_entries)

    generate, gguf_name = make_generate(cfg["max_tokens"])

    # Log incremental: cada linea es un evento (item o hito). Corte -> evidencia.
    def _prog(event: dict):
        event["t"] = datetime.datetime.now().isoformat()
        with open(prog_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _gen_logged(prompt, **kw):
        t0 = time.perf_counter()
        r = generate(prompt, **kw)
        _prog({"ev": "gen", "secs": round(time.perf_counter() - t0, 1)})
        return r

    print(f"[promptevo] preset={preset} model={gguf_name} "
          f"dev={len(dev_items)} test={len(test_items)} rounds={cfg['rounds']} "
          f"max_tokens={cfg['max_tokens']}", flush=True)
    _prog({"ev": "start", "preset": preset, "model": gguf_name,
           "n_dev": len(dev_items), "n_test": len(test_items),
           "rounds": cfg["rounds"], "max_tokens": cfg["max_tokens"]})

    log_lines = []

    def _log(msg):
        print(msg, flush=True)
        log_lines.append(msg)
        _prog({"ev": "log", "msg": msg})

    # DEV se parte en HARVEST (cosecha de exemplars) + TUNE (scoring), disjuntos.
    harvest_items, tune_items = _split_harvest_tune(dev_items)
    _log(f"[split] dev={len(dev_items)} -> harvest={len(harvest_items)} "
         f"tune={len(tune_items)} | test held-out={len(test_items)}")

    seed = pe.seed_scaffold()
    t_evo = time.perf_counter()

    # 0) BOOTSTRAP (DSPy): cosechar few-shots de las trazas que el 3B YA resuelve
    # bien en HARVEST (verificadas por el oraculo). Punto de arranque candidato.
    _log(f"[bootstrap] cosechando exemplars verificados de {len(harvest_items)} "
         f"harvest (k={cfg['boot_k']})...")
    exemplars = pe.bootstrap_exemplars(seed, harvest_items, _gen_logged,
                                       k=cfg["boot_k"], max_tokens=cfg["max_tokens"])
    booted = pe.make_bootstrapped(seed, exemplars)
    _log(f"[bootstrap] cosechados {len(exemplars)} exemplars "
         f"{'-> candidato bootstrapeado' if booted else '(ninguno; sigue la semilla)'}")

    # Elegir el mejor punto de arranque {semilla, bootstrapeado} sobre TUNE.
    seed_tune = pe.score_scaffold(seed, tune_items, _gen_logged, repair=True,
                                  max_tokens=cfg["max_tokens"])
    _log(f"[bootstrap] semilla en tune: {seed_tune.summary()}")
    start = seed
    if booted is not None:
        boot_tune = pe.score_scaffold(booted, tune_items, _gen_logged, repair=True,
                                      max_tokens=cfg["max_tokens"])
        _log(f"[bootstrap] bootstrapeado en tune: {boot_tune.summary()}")
        # arrancar del bootstrapeado solo si NO regresiona en tune (no-regresion)
        if boot_tune.accuracy >= seed_tune.accuracy:
            start = booted
            _log(f"[bootstrap] arranca del bootstrapeado ({boot_tune.accuracy:.3f} "
                 f">= {seed_tune.accuracy:.3f})")
        else:
            _log(f"[bootstrap] descartado (regresiona en tune) -> arranca de la semilla")

    # 1) EVOLUCION sobre TUNE (operadores dirigidos + siempre-candidatos + gate)
    ev = pe.evolve(start, tune_items, _gen_logged, rounds=cfg["rounds"],
                   min_gain=0.0, repair=True, log=_log)
    evo_secs = round(time.perf_counter() - t_evo, 1)

    # 2) MEDICION HONESTA sobre TEST held-out (seed vs ganador)
    _log(f"[test] midiendo SEMILLA sobre {len(test_items)} test held-out...")
    seed_test = pe.score_scaffold(seed, test_items, _gen_logged,
                                  repair=True, max_tokens=cfg["max_tokens"])
    _log(f"[test] semilla: {seed_test.summary()}")

    if ev.best_scaffold.name == seed.name:
        _log("[test] la evolucion no cambio el andamiaje (semilla ya optima en dev)")
        winner_test = seed_test
    else:
        _log(f"[test] midiendo GANADOR ({ev.best_scaffold.name}) sobre test...")
        winner_test = pe.score_scaffold(ev.best_scaffold, test_items, _gen_logged,
                                        repair=True, max_tokens=cfg["max_tokens"])
        _log(f"[test] ganador: {winner_test.summary()}")

    delta_test = round(winner_test.accuracy - seed_test.accuracy, 4)
    # Persistir SOLO si el ganador NO regresiona en test (honestidad: no publicar
    # en vivo un andamiaje que overfitteo dev y empeora en held-out).
    persisted = False
    if winner_test.accuracy >= seed_test.accuracy and ev.best_scaffold.name != seed.name:
        pe.persist_best(ev.best_scaffold, meta={
            "label": label, "preset": preset, "model": gguf_name,
            "dev_acc": ev.best_score.accuracy, "test_acc": winner_test.accuracy,
            "seed_test_acc": seed_test.accuracy, "delta_test": delta_test,
            "timestamp": ts,
        })
        persisted = True
        _log(f"[persist] ganador persistido (test {seed_test.accuracy:.3f} -> "
             f"{winner_test.accuracy:.3f}, delta {delta_test:+.3f})")
    else:
        _log(f"[persist] NO se persiste: delta_test={delta_test:+.3f} "
             f"(sin mejora en held-out) -> se mantiene el andamiaje actual")

    output = {
        "label": label, "preset": preset, "timestamp": ts, "model": gguf_name,
        "config": cfg, "evo_seconds": evo_secs,
        "dev": {"n_dev": len(dev_items), "n_harvest": len(harvest_items),
                "n_tune": len(tune_items),
                "seed_tune_acc": seed_tune.accuracy,        # semilla v1 en tune
                "n_bootstrapped_exemplars": len(exemplars),
                "start_scaffold": start.name,               # semilla o bootstrapeado
                "start_tune_acc": ev.seed_score.accuracy,   # arranque de la evolucion
                "best_tune_acc": ev.best_score.accuracy,
                "best_scaffold": ev.best_scaffold.name,
                "accepted_path": ev.accepted_path},
        "test_held_out": {
            "n": len(test_items),
            "seed_acc": seed_test.accuracy,
            "seed_by_category": {c: list(v) for c, v in seed_test.by_category.items()},
            "seed_error_buckets": seed_test.error_buckets,
            "winner_acc": winner_test.accuracy,
            "winner_by_category": {c: list(v) for c, v in winner_test.by_category.items()},
            "winner_error_buckets": winner_test.error_buckets,
            "delta": delta_test,
            "winner_token_cost": winner_test.token_cost,
            "seed_token_cost": seed_test.token_cost,
        },
        "trajectory": ev.trajectory,
        "winner_scaffold": ev.best_scaffold.to_dict(),
        "persisted_to_live": persisted,
        "log": log_lines,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    _prog({"ev": "done", "out": str(out_path), "delta_test": delta_test})

    print()
    print("=" * 72)
    print(f" PROMPT-EVOLUTION -- label={label} preset={preset} model={gguf_name}")
    print("=" * 72)
    print(f" TUNE ({len(tune_items)}): seed {seed_tune.accuracy:.3f} | "
          f"start[{start.name}] {ev.seed_score.accuracy:.3f} -> "
          f"best {ev.best_score.accuracy:.3f}  ({ev.best_scaffold.name})")
    print(f" TEST ({len(test_items)}): seed {seed_test.accuracy:.3f} -> "
          f"winner {winner_test.accuracy:.3f}  (delta {delta_test:+.3f})")
    print(f" persistido en vivo: {persisted}")
    print(f" JSON: {out_path}")
    print("=" * 72)
    return output


def main():
    _safe_stdout()
    ap = argparse.ArgumentParser(description="Corrida real del optimizador de andamiaje")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--smoke", action="store_true", help="valida el pipeline e2e (~3 min)")
    g.add_argument("--fast", action="store_true", help="dev=20 (harvest10+tune10) test=50 rounds=2")
    g.add_argument("--full", action="store_true", help="dev=40 (harvest20+tune20) test=160 rounds=3")
    ap.add_argument("--label", default=None, help="etiqueta del JSON de salida")
    args = ap.parse_args()

    preset = "smoke" if args.smoke else "full" if args.full else "fast"
    label = args.label or f"{preset}"
    run(preset, label)


if __name__ == "__main__":
    main()
