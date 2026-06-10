"""Integration test for CognitiveLoop con módulos REALES.
Run: .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.test_cognitive_loop

Usa la instancia Cognia real (KG + episódica + inferencia sobre cognia_memory.db)
y el primer backend LLM disponible (shards Shattering INT4 / Ollama). Si no hay
backend generativo, cae al pipeline simbólico de Cognia (ai.process) y lo declara.
"""
import sys

from cognia_v3.interfaces.cognitive_loop import CognitiveLoop
from cognia_v3.core.cognia_v3 import Cognia, text_to_vector
from cognia_v3.eval.baseline import make_real_query_fn


def main() -> int:
    ai = Cognia()

    llm_fn, label = make_real_query_fn()
    if llm_fn is None:
        print(f"[test] SIN backend LLM ({label}) — fallback al pipeline simbólico ai.process")
        llm_fn, label = (lambda p: ai.process(p)), "symbolic_fallback"
    print(f"[test] Backend de lenguaje: {label}\n")

    loop = CognitiveLoop(
        kg=ai.kg, language_engine=llm_fn,
        episodic_memory=ai.episodic, inference_engine=ai.inference,
        cognia=ai, vectorize=text_to_vector,
    )

    tests = [
        ("What is 2 plus 2?",                            "FAST"),
        ("What do I know about dogs?",                   "RECALL"),
        ("Explain why rain causes floods step by step.", "DELIBERATE"),
        ("Write a Python function to sort a list.",      "ACT"),
        ("Hello, how are you today?",                    "FAST"),
    ]

    print("=== CognitiveLoop Integration Test ===\n")
    passed = answered = 0
    for prompt, expected in tests:
        resp = loop.process(prompt)
        ok = resp.mode_used == expected
        if ok:
            passed += 1
        if resp.answer and resp.answer.strip():
            answered += 1
        icon = "+" if ok else "!"
        print(f"{icon} [{resp.mode_used:11s} / expected {expected:11s}] {prompt[:50]}")
        print(f"  Answer: {resp.answer[:100].replace(chr(10), ' ')}...")
        print(f"  Context: {len(resp.context_used)} facts | Confidence: {resp.confidence:.0%}\n")

    print(f"Routing accuracy: {passed}/{len(tests)}")
    print(f"Respuestas no vacías: {answered}/{len(tests)}")
    print("Note: routing mismatches are informational — tune _classify() keywords.")
    return 0 if answered == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
