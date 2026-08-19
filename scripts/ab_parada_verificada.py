# -*- coding: utf-8 -*-
"""A/B de la PARADA VERIFICADA (arnes Hermes, 2026-08-19).

QUE MIDE: la tarea del camino feliz que cambio al cablear el arnes -- "escribi
y ejecuta un script python que imprima la suma" -- paso de 15 s a 41 s en la
primera corrida con COGNIA_HERMES=1. Un numero de UNA corrida no distingue
ruido de regresion (la varianza entre corridas de este repo esta medida), asi
que esto corre los dos brazos INTERCALADOS y reporta netos apareados.

BRAZOS
  A (control)  COGNIA_HERMES=0  -- bucle de siempre
  B (arnes)    COGNIA_HERMES=1  -- presupuesto+refund, guardia de bucle,
                                   footer de mutaciones y parada verificada

PRIMARIA: postcondicion de DISCO (el .py existe, corre con exit 0 e imprime
350). SECUNDARIAS: pared, pasos y razon de salida. La respuesta del modelo NO
se juzga: un modelo que dice "listo" sin escribir tiene que FALLAR.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\ab_parada_verificada.py [n]
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TAREA = "escribí y ejecutá un script python que imprima la suma de 100 más 250"
ESPERADO = "350"


def postcondicion(ws):
    """La misma de scripts/e2e_happy_path.py: se comprueba EJECUTANDO."""
    for p in sorted(Path(ws).rglob("*.py")):
        try:
            r = subprocess.run([sys.executable, str(p)], cwd=str(p.parent),
                               capture_output=True, text=True, timeout=30,
                               stdin=subprocess.DEVNULL,
                               encoding="utf-8", errors="replace")
        except Exception:
            continue
        if r.returncode == 0 and ESPERADO in ((r.stdout or "") + (r.stderr or "")):
            return True
    return False


def una_corrida(ai, cli, dev_tools, hermes):
    os.environ["COGNIA_HERMES"] = "1" if hermes else "0"
    ws = Path(tempfile.mkdtemp(prefix="ab_pv_")).resolve()
    prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    os.chdir(ws)
    t0 = time.time()
    try:
        cli._run_agent_task(ai, TAREA, lambda s: None, max_steps=6)
    except Exception as exc:
        print("   EXCEPCION:", exc)
    finally:
        pared = time.time() - t0
        os.chdir(prev_cwd)
        dev_tools.AGENT_WORKSPACE_ROOT = prev_root
    return {"ok": postcondicion(ws), "pared": pared}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    res = {"A": [], "B": []}
    for i in range(n):
        # INTERCALADOS: A,B,A,B... Un bloque entero de un brazo mezcla el
        # efecto con la deriva del server (cache de prefijo, VRAM, termica).
        for brazo, hermes in (("A", False), ("B", True)):
            r = una_corrida(ai, cli, dev_tools, hermes)
            res[brazo].append(r)
            print(f"  {i+1}/{n} brazo {brazo} (hermes={int(hermes)}): "
                  f"ok={r['ok']} pared={r['pared']:.0f}s", flush=True)

    print()
    for brazo in ("A", "B"):
        oks = sum(1 for r in res[brazo] if r["ok"])
        pared = sum(r["pared"] for r in res[brazo]) / max(1, len(res[brazo]))
        print(f"BRAZO {brazo}: {oks}/{len(res[brazo])} OK, pared media {pared:.0f}s")
    neto = sum(1 for r in res["B"] if r["ok"]) - sum(1 for r in res["A"] if r["ok"])
    d_pared = (sum(r["pared"] for r in res["B"]) - sum(r["pared"] for r in res["A"])) / max(1, n)
    print(f"NETO acierto B-A: {neto:+d}   delta pared: {d_pared:+.0f}s por tarea")


if __name__ == "__main__":
    main()
