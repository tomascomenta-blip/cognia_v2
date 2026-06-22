r"""
exp021 / bench_cascade_e2e.py — Latencia conversacional real CON vs SIN cascada
==============================================================================
Mide (solo mide, no toca producción) cuánto más rápida se siente una conversación
multi-turno realista cuando los turnos sociales van al 0.5B (cascada) en vez de todo
al 3B. Wall-time por turno (prefill + decode), que es lo que percibe el usuario.

  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_cascade_e2e.py
Solo stdlib + el backend real del repo.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from node.llama_backend import _LlamaServerBackend           # noqa: E402
from node.speech_cascade import classify_turn, _chatml       # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
FAST = REPO / "model_shards" / "qwen-0.5b-instruct-q4" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
DEEP = REPO / "model_shards" / "qwen-coder-3b-q4" / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"
SYS = "Eres Cognia, un asistente que habla en español de forma clara, breve y natural."

# conversación realista (social + sustantiva intercaladas)
CONVO = [
    "Hola, ¿cómo estás?",
    "¿Por qué el cielo es azul?",
    "Gracias, muy claro.",
    "Explícame en breve qué es la fotosíntesis.",
    "Perfecto, ¿algo más?",
    "Escribe una función para invertir una cadena en Python.",
]


def _gen(backend, turn):
    # single-turn (sin historia/HYDRA) en AMBOS casos → aísla el efecto del TAMAÑO del
    # modelo; es una estimación CONSERVADORA (el path real 'sin cascada' lleva más prefill).
    t0 = time.time()
    txt = backend.generate(_chatml(turn, SYS), max_tokens=90, temperature=0.7)
    return time.time() - t0, (txt or "").strip()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    res = {"experiment": "exp021/cascade_e2e", "convo": CONVO, "rounds": {}}

    # ── SIN cascada: todo al 3B ────────────────────────────────────────────
    b3 = _LlamaServerBackend(DEEP, port=8091)
    try:
        b3.generate(_chatml("Hola.", SYS), max_tokens=8, temperature=0.0)  # warmup
        rows = []
        for t in CONVO:
            dt, _ = _gen(b3, t)
            rows.append({"turn": t, "model": "3B", "wall_s": round(dt, 2)})
            print(f"[sin] {dt:5.2f}s  {t}", flush=True)
        res["rounds"]["sin_cascada"] = {"per_turn": rows,
                                        "total_s": round(sum(r["wall_s"] for r in rows), 2)}
    finally:
        p = getattr(b3, "_proc", None)
        if p:
            p.terminate()
            try: p.wait(timeout=10)
            except Exception: p.kill()
        time.sleep(1.0)

    # ── CON cascada: social→0.5B (prompt mínimo), sustancia→3B ──────────────
    bf = _LlamaServerBackend(FAST, port=8090)
    bd = _LlamaServerBackend(DEEP, port=8091)
    try:
        bf.generate(_chatml("Hola.", SYS), max_tokens=8, temperature=0.0)  # warmup 0.5B
        bd.generate(_chatml("Hola.", SYS), max_tokens=8, temperature=0.0)  # warmup 3B
        rows = []
        for t in CONVO:
            route = classify_turn(t)
            backend = bf if route == "fast" else bd
            dt, _ = _gen(backend, t)
            rows.append({"turn": t, "route": route,
                         "model": "0.5B" if route == "fast" else "3B", "wall_s": round(dt, 2)})
            print(f"[con] {dt:5.2f}s  [{route:>4}]  {t}", flush=True)
        res["rounds"]["con_cascada"] = {"per_turn": rows,
                                        "total_s": round(sum(r["wall_s"] for r in rows), 2)}
    finally:
        for b in (bf, bd):
            p = getattr(b, "_proc", None)
            if p:
                p.terminate()
                try: p.wait(timeout=10)
                except Exception: p.kill()

    sin = res["rounds"]["sin_cascada"]["total_s"]
    con = res["rounds"]["con_cascada"]["total_s"]
    res["summary"] = {"total_sin_s": sin, "total_con_s": con,
                      "speedup_conversacion": round(sin / con, 2) if con else None,
                      "ahorro_s": round(sin - con, 2)}
    (OUT / "results_cascade_e2e.json").write_text(json.dumps(res, indent=2, ensure_ascii=False),
                                                  encoding="utf-8")
    print(f"\n[e2e] conversación: SIN={sin}s  CON={con}s  -> {res['summary']['speedup_conversacion']}x "
          f"(ahorro {res['summary']['ahorro_s']}s). results_cascade_e2e.json")


if __name__ == "__main__":
    main()
