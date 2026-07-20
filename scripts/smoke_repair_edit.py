"""
scripts/smoke_repair_edit.py
============================
Smoke REAL del repair por EDICION (--repair-mode edit) sobre UNA task del
baseline hard_det que fallo por runtime con traceback claro (LONG2:
AttributeError 'list' object has no attribute 'split').

Reusa repair_failures() de verdad (mismo code path que el benchmark): siembra
el resultado FAIL persistido en results_code_hard_det_20260611_1701.json y
corre 1 ronda de repair edit contra llama-server. Imprime el SEARCH/REPLACE
que propuso el modelo TAL CUAL, si aplico, y si paso los tests.

Run:  .\\venv312\\Scripts\\python.exe scripts\\smoke_repair_edit.py [TASK_ID]
(default TASK_ID = LONG2; el server :8088 debe estar libre)
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from cognia_v3.eval.benchmark_code import (
    apply_edits, make_backend, parse_search_replace, repair_failures,
)

BASELINE_JSON = REPO / "cognia_v3" / "eval" / "results_code_hard_det_20260611_1701.json"
TASKS_FILE = REPO / "cognia_v3" / "eval" / "tasks_hard.jsonl"


def main():
    task_id = sys.argv[1] if len(sys.argv) > 1 else "LONG2"

    tasks = [json.loads(ln) for ln in
             TASKS_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    task = next(t for t in tasks if t["id"] == task_id)
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    r = next(x for x in baseline["results"] if x["id"] == task_id)
    assert not r["passed"], f"{task_id} paso en el baseline, no hay nada que reparar"

    print(f"[smoke] task={task_id} error_type={r['error_type']}")
    print(f"[smoke] error_detail: {r['error_detail']}")
    print(f"[smoke] codigo fallido: {len(r['extracted_code'].splitlines())} lineas")

    backend, gguf = make_backend()
    if backend is None:
        print("ERROR: no llama backend available")
        sys.exit(1)
    print(f"[smoke] backend OK, model={gguf}")

    # Mismo flujo que el benchmark: seed 42, cache_prompt=False (dentro de
    # repair_failures), temp 0.5 (default de --repair-temp), 1 ronda.
    results = [{
        "id": r["id"], "difficulty": r["difficulty"],
        "entry_point": r["entry_point"], "passed": False,
        "error_type": r["error_type"], "error_detail": r["error_detail"],
        "extracted_code": r["extracted_code"],
    }]
    stats = repair_failures(backend, [task], results, repair_rounds=1,
                            max_tokens=768, repair_temperature=0.5,
                            seed=42, grammar=None, repair_mode="edit")

    att = results[0]["repair_attempts"][0]
    print()
    print("=" * 72)
    print(" RESPUESTA CRUDA DEL MODELO (SEARCH/REPLACE propuesto):")
    print("=" * 72)
    print(att["response"])
    print("=" * 72)
    edits = parse_search_replace(att["response"])
    applied = apply_edits(r["extracted_code"], edits) is not None
    print(f" bloques parseados: {len(edits)}  |  aplico: {applied}")
    print(f" resultado: {'PASS' if att['passed'] else 'FAIL'} "
          f"({att['error_type']}) {att['error_detail'][:120]}")
    print(f" tokens={att['tokens_predicted']}  gen_s={att['gen_seconds']}  "
          f"recovered={stats['recovered']}")
    print(f" CHECK smoke: {'RECOVERED' if att['passed'] else 'NOT RECOVERED'} "
          "(el smoke vale igual: muestra que propuso el modelo)")


if __name__ == "__main__":
    main()
