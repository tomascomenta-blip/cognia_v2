r"""
cascade_router.py — Router de cascada de habla (CYCLE 7, F-SPEED)
================================================================
Operativiza el lever MEDIDO en exp021: el 0.5B da ~36 tok/s (4.3× el 3B) pero es
poco fiable en hechos → se usa SOLO para turnos sociales/triviales (saludos, charla,
backchannel); todo lo sustantivo escala al 3B (calidad). classify() es una heurística
CONCRETA y testeable; el demo corre generación REAL contra ambos modelos y muestra
la decisión + tok/s + texto.

  .\venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\cascade_router.py
Solo stdlib + el backend real del repo.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from node.llama_backend import _LlamaServerBackend  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
FAST_GGUF = REPO / "model_shards" / "qwen-0.5b-instruct-q4" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
DEEP_GGUF = REPO / "model_shards" / "qwen-coder-3b-q4" / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"
SYS = "Eres Cognia, un asistente que habla en español de forma clara, breve y natural."

# señales de PROFUNDIDAD → 3B (la calidad gana ante la duda; el 0.5B inventa hechos)
_DEEP = re.compile(
    r"\b(por\s?qu[eé]|c[oó]mo\s+funciona|expl[ií]ca\w*|calcul\w*|cu[aá]nto[s]?|qu[eé]\s+es|"
    r"defin\w*|demuestr\w*|resuelv\w*|c[oó]digo|programa\w*|funci[oó]n|algoritmo|compar\w*|"
    r"analiz\w*|diferencia|historia|cu[aá]ndo|d[oó]nde|enumera|lista de|pasos para|traduc\w*)\b",
    re.I)
# señales SOCIALES/triviales → 0.5B (rápido, bajo riesgo)
_SOCIAL = re.compile(
    r"\b(hola|buenos d[ií]as|buenas|qu[eé] tal|c[oó]mo est[aá]s|gracias|adi[oó]s|chau|"
    r"hasta (luego|ma[ñn]ana)|encantado|mucho gusto|s[ií]|no|ok|vale|genial|perfecto|"
    r"jaj\w*|hey|saludos|buenas noches)\b", re.I)


def classify(turn: str) -> str:
    """'fast' (0.5B) para turnos sociales/triviales; 'deep' (3B) para sustancia.
    Diseño conservador: ante la duda → 'deep' (calidad), porque el 0.5B no es fiable
    en hechos (exp021)."""
    t = turn.strip()
    words = len(t.split())
    if _DEEP.search(t):
        return "deep"
    if "?" in t and words > 6:          # pregunta larga → probablemente sustantiva
        return "deep"
    if _SOCIAL.search(t) or words <= 4:  # social o muy corto → rápido
        return "fast"
    return "deep"                        # por defecto: calidad


DEMO_TURNS = [
    "Hola, ¿cómo estás?",
    "Gracias, muy amable.",
    "sí",
    "Buenas noches, hasta mañana.",
    "¿Por qué el cielo es azul?",
    "Explícame qué es la fotosíntesis.",
    "Escribe una función en Python para ordenar una lista.",
    "Cuéntame la historia de Roma en detalle.",
]


def chatml(u: str) -> str:
    return (f"<|im_start|>system\n{SYS}<|im_end|>\n<|im_start|>user\n{u}<|im_end|>\n"
            f"<|im_start|>assistant\n")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # consola Windows = cp1252 (no encodea →)
    except Exception:
        pass
    routed = [(t, classify(t)) for t in DEMO_TURNS]
    print("=== decisiones del router (heurística) ===")
    for t, r in routed:
        print(f"  [{r:>4}] {t}")

    results = {"experiment": "exp021/cascade_router", "routed": []}
    groups = {"fast": (FAST_GGUF, 8097), "deep": (DEEP_GGUF, 8098)}
    for route, (gguf, port) in groups.items():
        turns = [t for t, r in routed if r == route]
        if not turns or not gguf.is_file():
            continue
        b = _LlamaServerBackend(gguf, port=port)
        try:
            for t in turns:
                t0 = time.time()
                txt = b.generate(chatml(t), max_tokens=80, temperature=0.7)
                dt = time.time() - t0
                n = getattr(b, "last_tokens_predicted", None) or 0
                tps = round(n / dt, 1) if dt > 0 and n else None
                results["routed"].append({"turn": t, "route": route, "model": gguf.name,
                                          "tok_s": tps, "text": (txt or "").strip()})
                print(f"\n##### [{route}] ({tps} tok/s) {t}\n{(txt or '').strip()}")
        finally:
            proc = getattr(b, "_proc", None)
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except Exception:
                    proc.kill()

    n_fast = sum(1 for _, r in routed if r == "fast")
    fast_tps = [x["tok_s"] for x in results["routed"] if x["route"] == "fast" and x["tok_s"]]
    deep_tps = [x["tok_s"] for x in results["routed"] if x["route"] == "deep" and x["tok_s"]]
    results["summary"] = {
        "n_fast": n_fast, "n_deep": len(routed) - n_fast,
        "fast_tps_medio": round(sum(fast_tps) / len(fast_tps), 1) if fast_tps else None,
        "deep_tps_medio": round(sum(deep_tps) / len(deep_tps), 1) if deep_tps else None,
    }
    (OUT / "results_cascade.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    s = results["summary"]
    print(f"\n[cascade] {n_fast}/{len(routed)} turnos -> 0.5B rapido ({s['fast_tps_medio']} tok/s), "
          f"resto -> 3B ({s['deep_tps_medio']} tok/s). -> results_cascade.json")


if __name__ == "__main__":
    main()
