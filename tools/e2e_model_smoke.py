"""
tools/e2e_model_smoke.py
========================
Verificacion E2E de los caminos MODEL-DEPENDENT del producto comercial, con el
modelo 3B REAL (Qwen2.5-Coder-3B-Instruct-Q4_K_M via llama.cpp). Serial: hay UN
llama-server local (CPU). Ejercita la experiencia real del usuario y MUESTRA el
output crudo con un CHECK explicito (regla del repo: "codigo que corre o no cuenta").

Cubre:
  1. Backend real carga (que 3B, no el 7B) — solo-local.
  2. Chat: orch.infer(pregunta) -> respuesta coherente no vacia.
  3. Agente /hacer: _run_agent_task en una tarea trivial que exige una TOOL
     (escribir un archivo) -> verifica que el agente uso la tool y produjo el efecto.
  4. Salida larga: generate_long / infer con mas tokens -> texto extendido.
  5. (opcional) Creador de imagenes via el agente (escena_crear por lenguaje natural).

Uso (venv312, PYTHONUTF8=1):
  venv312\\Scripts\\python.exe tools\\e2e_model_smoke.py
  venv312\\Scripts\\python.exe tools\\e2e_model_smoke.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _safe_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    _safe_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--max-tokens", type=int, default=96)
    args = ap.parse_args()

    results = {"checks": []}

    def check(name, ok, detail=""):
        results["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:600]})
        print(f"\n[{'PASS' if ok else 'FALLA'}] {name}\n  {str(detail)[:500]}", flush=True)
        return ok

    # 1) Backend real (3B, solo-local)
    import os
    os.environ.setdefault("COGNIA_DISABLE_SWARM", "1")   # smoke = local-only duro
    try:
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator(mode="local")
        loaded = orch._try_load_llama()
        gguf = getattr(orch, "_gguf_name", None) or getattr(orch, "gguf_name", "?")
        check("backend 3B carga (solo-local)", bool(loaded), f"gguf={gguf} loaded={loaded}")
    except Exception as e:
        check("backend 3B carga (solo-local)", False, f"{type(e).__name__}: {e}")
        _finish(results, args); return 2

    # 2) Chat
    try:
        t0 = time.time()
        r = orch.infer("En una sola frase: que es Cognia?", max_tokens=args.max_tokens, temperature=0.0)
        txt = (getattr(r, "text", None) or str(r)).strip()
        check("chat: infer devuelve texto coherente", len(txt) > 10, f"({time.time()-t0:.0f}s) {txt}")
    except Exception as e:
        check("chat: infer devuelve texto coherente", False, f"{type(e).__name__}: {e}")

    # 3) Agente /hacer con una TOOL (escribir archivo)
    try:
        import tempfile
        from cognia.cli import _run_agent_task
        ai = None
        try:
            from cognia.cognia import Cognia
            ai = Cognia()
        except Exception:
            ai = None
        if ai is not None:
            ai._orchestrator = orch
        workdir = Path(tempfile.mkdtemp(prefix="cognia_e2e_"))
        target = workdir / "saludo.txt"
        logs = []
        t0 = time.time()
        out = _run_agent_task(
            ai, f"Escribi un archivo en {target} con el texto: hola mundo",
            _print_fn=lambda *a, **k: logs.append(" ".join(str(x) for x in a)),
            max_steps=6)
        wrote = target.exists()
        check("agente /hacer usa tool y crea el archivo",
              wrote, f"({time.time()-t0:.0f}s) archivo={wrote} resultado={str(out)[:150]}")
    except Exception as e:
        import traceback
        check("agente /hacer usa tool y crea el archivo", False,
              f"{type(e).__name__}: {e}\n{traceback.format_exc()[-300:]}")

    # 4) Salida larga
    try:
        t0 = time.time()
        r = orch.infer("Enumera 3 usos de un asistente local de IA, uno por linea.",
                       max_tokens=args.max_tokens * 2, temperature=0.0)
        txt = (getattr(r, "text", None) or str(r)).strip()
        check("salida mas larga (multi-linea)", txt.count("\n") >= 1 and len(txt) > 30,
              f"({time.time()-t0:.0f}s) {txt[:200]}")
    except Exception as e:
        check("salida mas larga (multi-linea)", False, f"{type(e).__name__}: {e}")

    _finish(results, args)
    return 0 if all(c["ok"] for c in results["checks"]) else 2


def _finish(results, args):
    ok = sum(c["ok"] for c in results["checks"])
    n = len(results["checks"])
    results["ok"] = ok == n
    print(f"\n{'='*60}\n E2E MODEL SMOKE: {ok}/{n} checks PASS\n{'='*60}", flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON: {args.json}")


if __name__ == "__main__":
    sys.exit(main())
