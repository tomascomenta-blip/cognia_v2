# -*- coding: utf-8 -*-
"""E2E REAL del fleet en el CLI (no mocks): server fresco con adapters.json,
ruteo identidad->experto, chat general->base, tarea de agente con experto
ACCION y postcondicion verificada.

Uso (venv312, sin LLAMA_LORA_PATH para que el fleet arranque):
  .\\venv312\\Scripts\\python.exe scripts/e2e_fleet_smoke.py
"""
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.pop("LLAMA_LORA_PATH", None)   # fleet, no modo estatico
os.environ.setdefault(
    "LLAMA_GGUF_PATH",
    str(REPO / "model_shards/qwen-coder-3b-q4/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"))

CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}" + (f" — {detalle}" if detalle else ""),
          flush=True)


def main():
    from node.llama_backend import LlamaBackend, _DEFAULT_PORT

    backend = LlamaBackend.try_load()
    if backend is None:
        print("FATAL: backend no levanto")
        sys.exit(1)

    # 1. fleet cargado
    check("fleet_experts == ['accion']", backend.fleet_experts == ["accion"],
          str(backend.fleet_experts))
    with urllib.request.urlopen(f"http://127.0.0.1:{_DEFAULT_PORT}/lora-adapters",
                                timeout=5) as r:
        vivos = json.loads(r.read())
    check("server cargo 1 adapter con scale 0.0",
          len(vivos) == 1 and vivos[0].get("scale") == 0.0, json.dumps(vivos))

    # 2. ruteo de chat: identidad -> experto; general -> base
    from cognia.agent.fleet_router import expert_for_chat_turn
    check("router: identidad -> accion",
          expert_for_chat_turn("¿quién sos?") == "accion")
    check("router: general -> base",
          expert_for_chat_turn("¿cuál es la capital de Francia?") is None)

    # 3. identidad REAL: experto activo responde como Cognia
    backend.activate_expert("accion")
    prompt = ("<|im_start|>system\nEres un asistente útil.<|im_end|>\n"
              "<|im_start|>user\n¿Quién sos?<|im_end|>\n<|im_start|>assistant\n")
    resp = backend.generate(prompt, max_tokens=80, temperature=0.0) or ""
    check("experto responde como Cognia", "cognia" in resp.lower(), resp[:120])

    # 4. base pura NO responde como Cognia (sanity del swap real)
    backend.activate_expert(None)
    resp_base = backend.generate(prompt, max_tokens=80, temperature=0.0) or ""
    check("base NO responde como Cognia (swap real)",
          "cognia" not in resp_base.lower(), resp_base[:120])

    # 5. tarea de agente real (mismo camino que /hacer): experto ACCION activo
    #    durante el loop + postcondicion en el workspace. Mismo armado que
    #    bench_estancamiento (orquestador real con manifest + workspace aislado).
    ws = Path(tempfile.mkdtemp(prefix="fleet_e2e_")).resolve()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(manifest_path="shattering/manifests/cognia_desktop.json")
    orch._try_load_llama()

    class _AI:  # minimo: _run_agent_task solo usa ai._orchestrator como cache
        pass

    ai = _AI()
    ai._orchestrator = orch
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    prev_cwd = os.getcwd()
    os.chdir(ws)
    logs = []
    try:
        resp_ag = _cli._run_agent_task(
            ai, "escribí un archivo llamado nota.txt con el texto exacto: hola fleet",
            lambda s: logs.append(str(s)), max_steps=6)
    finally:
        os.chdir(prev_cwd)
    check("loop activo el experto ACCION",
          any("Experto ACCION activo" in l for l in logs) or
          backend.active_expert == "accion",
          f"active={backend.active_expert}")
    hits = list(ws.rglob("nota.txt"))
    contenido = hits[0].read_text(encoding="utf-8", errors="replace") if hits else ""
    check("postcondicion: nota.txt con 'hola fleet'", "hola fleet" in contenido,
          f"archivos={len(hits)} resp={str(resp_ag)[:80]}")

    fallos = [n for n, ok in CHECKS if not ok]
    print(f"\nE2E FLEET: {len(CHECKS) - len(fallos)}/{len(CHECKS)} checks OK")
    if fallos:
        print("FALLARON:", fallos)
        sys.exit(1)


if __name__ == "__main__":
    main()
