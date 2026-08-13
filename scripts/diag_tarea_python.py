# -*- coding: utf-8 -*-
"""Reproduccion MINIMA de la tarea que rompe el gate del camino feliz.

De las 8 corridas del gate medidas el 2026-08-13 (4 en el commit base y 4 con
el arnes), la tarea 'python' fallo en 6. Las otras cuatro tareas fallan de
forma dispersa; esta falla casi siempre. Este script la corre aislada N veces
con el bus de eventos enganchado, para ver QUE hace el agente en cada intento
en vez de adivinar por el resultado final.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\diag_tarea_python.py [N]

Registra por corrida: herramientas llamadas (en orden, con ok/error), numero de
pasos, tokens, motivo de cierre y si la respuesta final contiene '350'.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TAREA = "escribí y ejecutá un script python que imprima la suma de 100 más 250"


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6

    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from cognia.ux import events as ev
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    from cognia.agent.model_profiles import perfil_del_agente
    perfil = perfil_del_agente(forzar=True)
    print(f"perfil: {perfil.get('nombre')} | modelo: {perfil.get('modelo')}")
    print(f"        tools={perfil.get('tools')} temp={perfil.get('temperature')} "
          f"top_p={perfil.get('top_p')} n_ctx={perfil.get('n_ctx')} "
          f"max_tokens={perfil.get('max_tokens')}")
    print()

    aciertos = 0
    for i in range(1, n + 1):
        traza: list = []

        def _oir(evento, _t=traza):
            nombre = type(evento).__name__
            if nombre == "ToolInicio":
                _t.append(f"{evento.tool}(")
            elif nombre == "ToolFin":
                marca = "ok" if getattr(evento, "ok", True) else "ERR"
                _t.append(f"{marca})")
            elif nombre == "TareaFin":
                _t.append(f"[fin pasos={getattr(evento, 'pasos', '?')} "
                          f"tokens={getattr(evento, 'tokens', '?')}]")

        ev.suscribir(_oir)
        ws = Path(tempfile.mkdtemp(prefix="diag_py_")).resolve()
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.chdir(ws)
        t0 = time.time()
        try:
            resp = _cli._run_agent_task(ai, TAREA, lambda s: None, max_steps=6)
        except Exception as exc:
            resp = f"EXCEPTION: {exc}"
        finally:
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root
            ev.desuscribir(_oir)

        resp = str(resp or "")
        ok = "350" in resp
        aciertos += bool(ok)
        ficheros = sorted(p.name for p in ws.rglob("*.py"))
        print(f"--- corrida {i}: {'OK' if ok else 'FALLO'} ({time.time()-t0:.0f}s)")
        print(f"    tools : {' '.join(traza) or '(NINGUNA: el modelo no llamo herramientas)'}")
        print(f"    .py   : {ficheros or '(no escribio ningun .py)'}")
        print(f"    resp  : {resp[:200]!r}")

    print(f"\nTAREA python: {aciertos}/{n} OK")
    return 0 if aciertos == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
