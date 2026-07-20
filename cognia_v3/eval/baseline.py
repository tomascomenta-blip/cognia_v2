"""
Cognia evaluation baseline.
Run before and after any training to measure improvement.
Usage:
    python -m cognia_v3.eval.baseline            # stub + modelo real si hay backend
    python -m cognia_v3.eval.baseline --stub     # solo stub (sin modelo)
    # Or import and call run_baseline(query_fn, label="my_model")

Backend real (en orden de preferencia):
  1. ShatteringOrchestrator con shards INT4 locales (shattering/manifests/cognia_desktop.json)
  2. Ollama (si el server local responde)
"""
import json
import sys
import datetime
from pathlib import Path
from typing import Callable

EVAL_DIR = Path(__file__).resolve().parent

BASELINE_QUESTIONS = [
    {"id": "R1", "prompt": "If a dog is a mammal and all mammals are warm-blooded, is a dog warm-blooded? Answer yes or no and explain.", "keywords": ["yes", "warm"], "category": "reasoning"},
    {"id": "R2", "prompt": "If it rains the ground gets wet. The ground is wet. Did it necessarily rain?", "keywords": ["not necessarily", "maybe", "could"], "category": "logic"},
    {"id": "F1", "prompt": "What causes rain?", "keywords": ["water", "evaporation", "cloud"], "category": "factual"},
    {"id": "F2", "prompt": "What is the capital of France?", "keywords": ["paris"], "category": "factual"},
    {"id": "F3", "prompt": "What is machine learning?", "keywords": ["data", "model", "learn", "pattern"], "category": "factual"},
    {"id": "M1", "prompt": "What is 15% of 200?", "keywords": ["30"], "category": "math"},
    {"id": "C1", "prompt": "Write a Python function that reverses a string.", "keywords": ["def", "return"], "category": "code"},
    {"id": "C2", "prompt": "In Python, what is the difference between a list and a tuple?", "keywords": ["mutable", "immutable"], "category": "code"},
    {"id": "C3", "prompt": "Write Python code to iterate a list printing index and value.", "keywords": ["enumerate", "for"], "category": "code"},
    {"id": "C4", "prompt": "Name 3 common sorting algorithms.", "keywords": ["sort"], "category": "cs"},
]


def _fold(text: str) -> str:
    """lowercase + sin acentos: el modelo responde a veces en español ('París')."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


def score_response(response: str, keywords: list[str]) -> float:
    """Keyword scoring (accent-insensitive). Returns 0.0 to 1.0."""
    r = _fold(response)
    return sum(1 for kw in keywords if _fold(kw) in r) / len(keywords)


def run_baseline(query_fn: Callable[[str], str], label: str = "model") -> dict:
    """
    Run all baseline questions.
    query_fn: callable(prompt: str) -> str
    """
    results = []
    for q in BASELINE_QUESTIONS:
        try:
            response = query_fn(q["prompt"])
        except Exception as e:
            response = f"<ERROR: {e}>"
        score = score_response(response, q["keywords"])
        results.append({"id": q["id"], "category": q["category"],
                        "prompt": q["prompt"], "response": response[:200], "score": score})

    avg = sum(r["score"] for r in results) / len(results)
    output = {"label": label, "timestamp": datetime.datetime.now().isoformat(),
              "avg_score": avg, "results": results}

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = EVAL_DIR / f"eval_{label}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n=== BASELINE: {label} ===")
    print(f"Average score: {avg:.1%}")
    for r in results:
        icon = "+" if r["score"] >= 0.5 else "x"
        print(f"  {icon} [{r['category']}] {r['id']}: {r['score']:.0%}")
    print(f"Saved: {path}\n")
    return output


def make_real_query_fn() -> tuple[Callable[[str], str], str] | tuple[None, str]:
    """Devuelve (query_fn, label) con el primer backend real disponible, o (None, motivo)."""
    # 1. Shattering local: llama.cpp+GGUF (fast path) o shards INT4 .npz
    try:
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator(
            manifest_path="shattering/manifests/cognia_desktop.json", mode="local",
            max_new_tokens=200,
        )
        orch._try_load_llama()
        if orch._llama is not None:
            return (lambda p: orch.infer(p).text, "shattering_llamacpp")
        if orch._shards_available():
            return (lambda p: orch.infer(p).text, "shattering_int4")
    except Exception as e:
        print(f"[baseline] Shattering no disponible: {e}")

    # 2. Ollama directo
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        from cognia_v3.interfaces.respuestas_articuladas import llamar_ollama
        return (lambda p: llamar_ollama(p), "ollama")
    except Exception as e:
        return (None, f"sin backend real: shards/Ollama no disponibles ({e})")


if __name__ == "__main__":
    def stub_query(prompt: str) -> str:
        return "I don't know."

    run_baseline(stub_query, label="stub")
    print("baseline.py OK — stub medido.")

    if "--stub" not in sys.argv:
        fn, label = make_real_query_fn()
        if fn is None:
            print(f"[baseline] SKIP modelo real: {label}")
        else:
            print(f"[baseline] Backend real: {label}")
            run_baseline(fn, label=f"{label}_baseline")
