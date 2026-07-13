# -*- coding: utf-8 -*-
"""Prueba directa del no-determinismo (ROMPER EL TECHO, hallazgo central):
3B greedy (temp 0, seed 42) sobre 2 tareas, 3 corridas cada una. Si el
código difiere entre corridas IDÉNTICAS, el techo tiene banda de varianza.

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.determinismo_check
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
OUT = REPO / "cognia_v3" / "eval" / "determinismo_check.json"
IDS = ["SPEC1", "NEWX2"]        # una recuperable + un parser
RUNS = 3
PORT = 8189


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from cognia_v3.eval.benchmark_code import (SYSTEM_PROMPT, build_prompt,
                                               extract_code, run_task_tests)
    from node.llama_backend import _LlamaServerBackend
    from shattering.model_constants import resolve_gguf_path

    tasks = {json.loads(l)["id"]: json.loads(l) for l in
             open(REPO / "cognia_v3" / "eval" / "tasks_hard_v2.jsonl",
                  encoding="utf-8") if l.strip()}
    res = {}
    b = _LlamaServerBackend(resolve_gguf_path("3b"), port=PORT, ctx_size=8192)
    try:
        for tid in IDS:
            t = tasks[tid]
            prompt = build_prompt(t["prompt"], system=SYSTEM_PROMPT)
            corridas = []
            for r in range(RUNS):
                raw = b.generate(prompt, max_tokens=768, temperature=0.0,
                                 seed=42, cache_prompt=False) or ""
                code = extract_code(raw)
                ok = bool(run_task_tests(code, t["tests"], t["entry_point"])[0])
                h = hashlib.sha256(code.encode()).hexdigest()[:12]
                corridas.append({"sha": h, "passed": ok, "len": len(code)})
                print(f"[{tid}] run {r}: sha={h} passed={ok} len={len(code)}",
                      flush=True)
            shas = {c["sha"] for c in corridas}
            passes = {c["passed"] for c in corridas}
            res[tid] = {"corridas": corridas,
                        "codigos_distintos": len(shas),
                        "resultados_distintos": len(passes) > 1,
                        "no_determinista": len(shas) > 1}
            OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    finally:
        b.stop()

    algun_nd = any(v["no_determinista"] for v in res.values())
    algun_flip = any(v["resultados_distintos"] for v in res.values())
    res["_veredicto"] = {
        "no_determinismo_confirmado": algun_nd,
        "flip_de_resultado_confirmado": algun_flip,
        "lectura": ("el techo TIENE banda de varianza (mismo protocolo, "
                    "distinto codigo)" if algun_nd
                    else "determinista: SPEC1 se recupero por otra causa")}
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("\nVEREDICTO:", json.dumps(res["_veredicto"], indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
