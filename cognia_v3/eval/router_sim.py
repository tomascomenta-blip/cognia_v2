"""
Simulación del router de dificultad (corrida-2 tarea 4): ¿ahorra recursos?

NO re-corre los modelos (el 7B es lento/finicky de arrancar en el i3): usa los
resultados per-task YA medidos del 3B y del 7B sobre las MISMAS tasks_hard
(mismo batch, greedy) y simula qué habría hecho el router:
  router(tarea) = resultado del 3B si pick_model=3b, del 7B si pick_model=7b.
Compara accuracy y COSTO (nº de tareas despachadas al 7B) contra always-3B,
always-7B y la cascada reactiva.

Usage: venv312\\Scripts\\python.exe -m cognia_v3.eval.router_sim
"""
import glob
import json
import sys
from pathlib import Path

from cognia.agent.model_router import estimate_difficulty, pick_model

EVAL = Path(__file__).resolve().parent


def _load_passed(pattern, stage_filter=None):
    """{id: passed} del JSON mas reciente que matchee. stage_filter: si se da,
    solo cuenta results con ese 'stage' (para el 3B de la cascada = 'first')."""
    fs = sorted(glob.glob(str(EVAL / pattern)))
    if not fs:
        return None, None
    d = json.load(open(fs[-1], encoding="utf-8"))
    out = {}
    for r in d.get("results", []):
        if stage_filter and r.get("stage") not in (stage_filter, "cascade"):
            # la cascada anota stage; para el 3B puro tomamos 'first' (paso 3B)
            pass
        out[r["id"]] = bool(r["passed"])
    return out, Path(fs[-1]).name


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 3B per-task: baseline duro de esta corrida; 7B per-task: run de junio 12.
    p3, f3 = _load_passed("results_code_eje2_hard_baseline_*.json")
    if p3 is None:
        p3, f3 = _load_passed("results_code_hard_det_2026*.json")
    p7, f7 = _load_passed("results_code_hard7b_det_*.json")
    if p3 is None or p7 is None:
        print("FALTAN resultados 3B o 7B per-task; no se puede simular.")
        sys.exit(1)

    tasks = [json.loads(l) for l in open(EVAL / "tasks_hard.jsonl", encoding="utf-8")
             if l.strip()]
    ids = [t["id"] for t in tasks if t["id"] in p3 and t["id"] in p7]

    n = len(ids)
    n3 = sum(p3[i] for i in ids)
    n7 = sum(p7[i] for i in ids)

    router_pass = 0
    n_to_7b = 0
    rows = []
    for t in tasks:
        i = t["id"]
        if i not in ids:
            continue
        d = estimate_difficulty(t["prompt"])
        m = pick_model(t["prompt"])
        res = p7[i] if m == "7b" else p3[i]
        router_pass += res
        n_to_7b += (m == "7b")
        rows.append((i, d, m, p3[i], p7[i], res))

    # cascada reactiva (union): 3B + 7B en los que fallo el 3B
    cascade_pass = sum(1 for i in ids if p3[i] or p7[i])

    print("=" * 68)
    print(" ROUTER DE DIFICULTAD — SIMULACION sobre tasks_hard (n=%d)" % n)
    print("   3B: %s | 7B: %s" % (f3, f7))
    print("=" * 68)
    print(f" {'ID':<7} {'dif':>5} {'modelo':<4} {'3B':<3} {'7B':<3} {'router':<6}")
    print("-" * 68)
    for i, d, m, r3, r7, res in rows:
        print(f" {i:<7} {d:>5.2f} {m:<4} {'ok' if r3 else '.':<3} "
              f"{'ok' if r7 else '.':<3} {'PASS' if res else 'FAIL':<6}")
    print("-" * 68)
    print(f" always-3B : {n3}/{n} = {n3/n:.1%}   (barato, ~8 tok/s)")
    print(f" always-7B : {n7}/{n} = {n7/n:.1%}   (caro, ~2.2 tok/s)")
    print(f" cascada   : {cascade_pass}/{n} = {cascade_pass/n:.1%}   "
          f"(3B + 7B en los {n - n3} fallos)")
    print(f" ROUTER    : {router_pass}/{n} = {router_pass/n:.1%}   "
          f"(7B en {n_to_7b}/{n} tareas -> {n - n_to_7b} corren barato)")
    print("-" * 68)
    # veredicto de ahorro
    saving = n - n_to_7b
    print(f" AHORRO: el router corre el 7B (caro) en {n_to_7b}/{n} tareas en vez "
          f"de {n} (always-7B):")
    print(f"   -> {saving} tareas ({saving/n:.0%}) corren en el 3B barato.")
    if router_pass >= n7:
        print(f"   -> y NO pierde accuracy vs always-7B ({router_pass} >= {n7}).")
    elif router_pass > n3:
        print(f"   -> gana {router_pass - n3} sobre always-3B pagando 7B solo en "
              f"{n_to_7b} tareas (vs {n} de always-7B).")
    else:
        print(f"   -> NO mejora sobre always-3B: el predictor no acerto (honesto).")
    print("=" * 68)

    out = {"n": n, "always_3b": n3, "always_7b": n7, "cascade": cascade_pass,
           "router": router_pass, "n_to_7b": n_to_7b,
           "rows": [{"id": i, "difficulty": d, "model": m,
                     "p3b": r3, "p7b": r7, "router": res}
                    for i, d, m, r3, r7, res in rows]}
    (EVAL / "results_router_sim.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
