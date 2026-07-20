"""
Emite tooluse_eval.jsonl: los prompts iniciales (held-out) del agent loop para
las tareas de EVAL. El kernel de Kaggle los usa para medir 'valid_single_accion'
base vs base+adapter. El prompt es el MISMO formato que ve el modelo en el primer
paso del deploy: TOOLS_DOC + 'TAREA: ...' + 'Siguiente ACCION:'.

Uso:
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.make_eval_prompts
"""
from __future__ import annotations

import json
from pathlib import Path


def main():
    from cognia_v3.training.tooluse.gen_trajectories import build_tools_doc_full
    from cognia_v3.training.tooluse.tasks import eval_tasks

    tools_doc = build_tools_doc_full()
    out = Path("cognia_v3/training/tooluse/data/tooluse_eval.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    n = 0
    with out.open("w", encoding="utf-8") as f:
        for t in eval_tasks():
            ctx_text = f"TAREA: {t['prompt']}"
            prompt = (f"{tools_doc}\n\nContexto de la tarea:\n{ctx_text}\n\n"
                      f"Siguiente ACCION:")
            f.write(json.dumps({"task_id": t["id"], "prompt": prompt,
                                "expected_tools": t.get("tools", [])},
                               ensure_ascii=False) + "\n")
            n += 1
    print(f"[eval-prompts] {n} prompts held-out -> {out}")


if __name__ == "__main__":
    main()
