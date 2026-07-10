# -*- coding: utf-8 -*-
"""Diagnóstico G5: ¿los fallos del base son de IDIOMA (formato, entrenable
por adapter) o de CONTENIDO (capacidad, línea muerta post E-RZN/E-COD)?

Corre los 25 ítems G5 contra la base Q4_K_M capturando la respuesta CRUDA y
clasifica cada fallo:
  - no_espanol : oracle OK pero es_espanol(raw) False  -> gap de FORMATO
  - contenido  : es_espanol OK pero oracle False       -> gap de CAPACIDAD
  - ambos      : fallan los dos
Decide E-ESP con datos (regla del plan: medir el gap ANTES de construir).

Uso: .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.diag_g5
"""
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUITES = REPO / "cognia_v3" / "eval" / "suites"
sys.path.insert(0, str(SUITES))
from suite_oracle import oracle_pass, es_espanol, carga_suite  # noqa: E402


def main():
    os.environ["LLAMA_GGUF_PATH"] = str(
        REPO / "model_shards" / "qwen-coder-3b-q4" /
        "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf")
    from node.llama_backend import LlamaBackend
    backend = LlamaBackend.try_load()
    assert backend is not None, "no levanto llama-server"

    items = carga_suite(str(SUITES / "g5_espanol.jsonl"))
    res = {"pasa": [], "no_espanol": [], "contenido": [], "ambos": []}
    t0 = time.time()
    for it in items:
        raw = (backend.generate(
            f"<|im_start|>system\nEres un asistente útil.<|im_end|>\n"
            f"<|im_start|>user\n{it['prompt']}<|im_end|>\n<|im_start|>assistant\n",
            max_tokens=it["max_new_tokens"], temperature=0.0,
            cache_prompt=False) or "").strip()
        ok_o = oracle_pass(raw, it["oracle"])
        ok_e = es_espanol(raw)
        clase = ("pasa" if ok_o and ok_e else
                 "no_espanol" if ok_o else
                 "contenido" if ok_e else "ambos")
        res[clase].append({"id": it["id"], "prompt": it["prompt"][:70],
                           "raw": raw[:160]})
        print(f"  [{clase:10s}] {it['id']}: {raw[:70]!r}", flush=True)

    out = REPO / "cognia_v3" / "eval" / "results_diag_g5.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    n = len(items)
    print(f"\n[diag-g5] pasa={len(res['pasa'])}/{n}  "
          f"no_espanol(FORMATO)={len(res['no_espanol'])}  "
          f"contenido(CAPACIDAD)={len(res['contenido'])}  "
          f"ambos={len(res['ambos'])}  ({(time.time()-t0)/60:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
