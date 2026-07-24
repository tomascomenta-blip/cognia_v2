# -*- coding: utf-8 -*-
"""E2E REAL del pensamiento profundo en tres actos (2026-07-23).

Corre el pipeline completo contra los modelos de verdad:
  ACTO 1  sonar la idea      (Qwen3-4B-Thinking en :8093, temperatura alta)
  ACTO 2  bajarla a un plan  (mismo razonador, temperatura baja)
  ACTO 3  ejecutarla         (agente real de cli.py, 7B en :8088)

El pedido es una semilla corta A PROPOSITO: la gracia del acto 1 es que el
resultado sea mucho mas grande que lo pedido.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_pensamiento_profundo.py
Salida: los tres actos con su conteo real + CHECK final.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PEDIDO = os.environ.get(
    "PP_PEDIDO",
    "Hace un juego dificil en Python que se juegue en la terminal.")
MAX_PASOS = int(os.environ.get("PP_MAX_PASOS", "8"))


def main():
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from cognia.pensamiento_profundo import pensar_profundo, resumen
    from shattering.orchestrator import ShatteringOrchestrator

    ws = Path(tempfile.mkdtemp(prefix="pp_")).resolve()
    os.environ["COGNIA_AGENT_WORKSPACE"] = str(ws)
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    print(f"workspace: {ws}", flush=True)

    def log(s):
        print(str(s).replace("[detail]", "").replace("[/detail]", ""), flush=True)

    orch = ShatteringOrchestrator(mode="local")

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    def runner(tarea, guia):
        return _cli._run_agent_task(ai, tarea, log, guidance=guia)

    t0 = time.time()
    res = pensar_profundo(PEDIDO, runner=runner, print_fn=log,
                          max_pasos=MAX_PASOS)
    dt = time.time() - t0

    print("\n" + "=" * 70, flush=True)
    print(resumen(res), flush=True)
    print("=" * 70, flush=True)

    idea, plan = res.get("idea", ""), res.get("plan")
    hechos = sum(1 for r in res.get("resultados", []) if r["ok"])
    creados = [p for p in ws.rglob("*.py")]
    total_chars = sum(p.stat().st_size for p in creados)
    print(f"\nminutos: {dt/60:.1f} | idea: {len(idea)} chars | "
          f"pasos: {hechos}/{len(plan.pasos)} | "
          f"archivos .py: {len(creados)} ({total_chars} bytes)", flush=True)
    for p in sorted(creados):
        print(f"  - {p.relative_to(ws)} ({p.stat().st_size} bytes)", flush=True)

    # El gate exige CODIGO QUE COMPILA: la primera corrida (2026-07-23) dio
    # 7/7 pasos "hechos" con 4 de 8 archivos que ni parseaban. Un gate que
    # solo cuenta archivos miente.
    import ast
    parsean = 0
    for p in creados:
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            parsean += 1
        except SyntaxError as e:
            print(f"    !! {p.name}: linea {e.lineno}: {e.msg}", flush=True)
        except Exception:
            pass
    print(f"\ncompilan: {parsean}/{len(creados)}", flush=True)

    # ...y que ARRANQUE. Un juego de terminal se queda esperando input: si a
    # los 6s sigue vivo, arranco bien. Morir con Traceback es el fallo real.
    arranca = None
    entrada = ws / "main.py"
    if entrada.is_file():
        import subprocess
        try:
            pr = subprocess.run([sys.executable, str(entrada)], cwd=str(ws),
                                input="\n", capture_output=True, text=True,
                                timeout=6, errors="replace")
            # OJO: un SyntaxError del script principal NO imprime 'Traceback'
            # (medido 2026-07-23: el gate decia "arranca: True" con main.py
            # roto). Hay que mirar tambien el nombre del error.
            err = pr.stderr or ""
            arranca = not any(m in err for m in
                              ("Traceback", "SyntaxError", "IndentationError"))
            if not arranca:
                print("    !! main.py revienta:\n"
                      + "\n".join(pr.stderr.strip().splitlines()[-4:]), flush=True)
        except subprocess.TimeoutExpired:
            arranca = True          # sigue corriendo = arranco bien
    print(f"main.py arranca: {arranca}", flush=True)

    ok = (len(idea) > 2000 and len(plan.pasos) >= 5 and creados
          and total_chars > 1500 and parsean == len(creados)
          and arranca is True)
    print(f"CHECK pipeline completo: {'OK' if ok else 'FALLO'}", flush=True)
    print(f"IDEA guardada en: {res.get('archivo_idea')}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
