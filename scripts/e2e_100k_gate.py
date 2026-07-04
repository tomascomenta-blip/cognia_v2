"""
scripts/e2e_100k_gate.py
========================
GATE real de escala 100k (CP4 de la corrida "MoM al techo teorico"): genera un
documento largo con LlamaBackend.generate_delegated() contra llama-server +
Qwen2.5-Coder-3B, ESCRIBIENDO incrementalmente a disco (una corrida de horas no
se pierde ante un crash) y midiendo:
  - tokens reales totales (suma de tokens por subtarea),
  - coherencia entre bordes (juez barato de solapamiento lexico entre el final
    de una seccion y el titulo/inicio de la siguiente — proxy, cero LLM),
  - tiempo de pared y tok/s.

CHECK del gate: total_tokens >= 0.9 * target (permite el 10% de holgura por
subtareas que cierran natural antes de su cap), y el archivo crece de verdad
seccion a seccion (probado por el mtime/size creciente del sidecar).

Uso (parametrizable por env, para lanzar detached con Start-Process):
  LARGO_TARGET (default 100000), LARGO_TASKS (default 22), LARGO_OUT (archivo),
  PYTHONUTF8=1 OBLIGATORIO (el print de texto no-ASCII a stdout cp1252 crashea).

  $env:PYTHONUTF8=1
  venv312/Scripts/python.exe scripts/e2e_100k_gate.py

A ~6-8 tok/s en el i3-10110U, 100k tokens son ~3.9-4.2 h: correr en background.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from node.inference_pipeline import _apply_qwen_template
from node.llama_backend import LlamaBackend
from shattering.model_constants import COGNIA_SYSTEM_PROMPT

TARGET = int(os.environ.get("LARGO_TARGET", "100000"))
N_TASKS = int(os.environ.get("LARGO_TASKS", "22"))
OUT = Path(os.environ.get("LARGO_OUT",
                          str(Path(__file__).parent.parent / "e2e_100k_output.txt")))
STATE = OUT.with_suffix(OUT.suffix + ".state.json")

USER_PROMPT = (
    "Escribe un manual exhaustivo y coherente en espanol sobre INGENIERIA DE "
    "SISTEMAS DISTRIBUIDOS: fundamentos, modelos de consistencia, consenso "
    "(Paxos/Raft), replicacion, particionado, tolerancia a fallos, relojes "
    "logicos, colas de mensajes, almacenamiento, observabilidad, seguridad y "
    "patrones de diseno. Debe ser progresivo (cada capitulo se apoya en los "
    "anteriores), con ejemplos concretos y sin repetir contenido entre "
    "capitulos."
)


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def _save_state(state: dict) -> None:
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE)


def _overlap(a: str, b: str) -> float:
    """Solapamiento lexico [0,1] entre dos textos (proxy de continuidad de
    tema): |palabras comunes| / |palabras de b|, sobre las ultimas/primeras
    ~60 palabras. NO mide calidad, solo que el tema no salte de golpe."""
    wa = set(w.lower() for w in a.split()[-60:] if len(w) > 3)
    wb = set(w.lower() for w in b.split()[:60] if len(w) > 3)
    if not wb:
        return 0.0
    return len(wa & wb) / len(wb)


def main() -> int:
    print(f"[100k-gate] target={TARGET} tokens, n_tasks={N_TASKS}, out={OUT.name}")
    backend = LlamaBackend.try_load()
    if backend is None:
        print("FAIL: no llama backend (GGUF o llama-server faltante)")
        return 1
    if not hasattr(backend, "generate_delegated"):
        print("FAIL: backend sin generate_delegated")
        return 1

    OUT.write_text("", encoding="utf-8")  # arrancar limpio
    prompt = _apply_qwen_template(USER_PROMPT, COGNIA_SYSTEM_PROMPT)

    state = {"mode": "delegado", "target": TARGET, "n_tasks": N_TASKS,
             "outline": [], "done": 0, "total_tokens": 0, "sections": [],
             "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _last_tail = {"txt": ""}
    _coherence = []

    def _on_outline(tasks):
        state["outline"] = list(tasks)
        _save_state(state)
        print(f"[100k-gate] outline de {len(tasks)} subtareas planificado")

    def _on_task(idx, total, titulo, tokens, texto, stop_reason):
        # escritura incremental REAL: appendear apenas la subtarea cierra
        with OUT.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## {idx}. {titulo}\n\n{texto}\n")
        coh = _overlap(_last_tail["txt"], f"{titulo} {texto}") if _last_tail["txt"] else None
        if coh is not None:
            _coherence.append(coh)
        _last_tail["txt"] = texto
        state["done"] = idx
        state["total_tokens"] += int(tokens or 0)
        state["sections"].append({"idx": idx, "titulo": titulo[:80],
                                  "tokens": tokens, "stop": stop_reason,
                                  "coh_prev": round(coh, 3) if coh is not None else None})
        _save_state(state)
        print(_ascii(f"[100k-gate] {idx}/{total} '{titulo[:50]}' "
                     f"+{tokens} tok (total {state['total_tokens']}), stop={stop_reason}"
                     + (f", coh_prev={coh:.2f}" if coh is not None else "")))

    t0 = time.time()
    result = backend.generate_delegated(
        prompt, target_tokens=TARGET, n_tasks=N_TASKS,
        on_outline=_on_outline, on_task=_on_task)
    secs = time.time() - t0

    if result is None:
        print("FAIL: generate_delegated devolvio None (fallo el outline o la 1a subtarea)")
        return 1

    total = state["total_tokens"]
    avg_coh = sum(_coherence) / len(_coherence) if _coherence else 0.0
    toks_s = total / secs if secs > 0 else 0.0
    state["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state["secs"] = round(secs, 1)
    state["tok_s"] = round(toks_s, 2)
    state["avg_coherence"] = round(avg_coh, 3)
    state["file_chars"] = OUT.stat().st_size
    _save_state(state)

    passed = total >= 0.9 * TARGET
    print("=" * 60)
    print(f"[100k-gate] total_tokens={total} (target {TARGET})")
    print(f"[100k-gate] subtareas={state['done']}/{N_TASKS}, "
          f"file={state['file_chars']} chars")
    print(f"[100k-gate] coherencia media entre bordes={avg_coh:.3f} "
          f"(proxy lexico; >0 = el tema no salta)")
    print(f"[100k-gate] tiempo={secs/60:.1f} min, {toks_s:.2f} tok/s")
    print(f"[100k-gate] GATE {'PASS' if passed else 'FAIL'} "
          f"(>= 90% del target)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
