# -*- coding: utf-8 -*-
"""A/B de la EJECUCION ESPECULATIVA de acciones (2026-08-19).

QUE MIDE: mientras el modelo piensa el paso n (llamada bloqueante), un hilo
adelanta las acciones PURAS que probablemente pedira. La metrica PRIMARIA es la
TASA DE ACEPTACION (aceptadas/especuladas) y, dentro de ella, cuantas se aceptan
por igualdad exacta y cuantas por EQUIVALENCIA DE EFECTO -- que es el hueco que
la literatura declara abierto (Speculative Actions, arXiv 2510.04371, se queda
en 55% aceptando por sintaxis).

La SECUNDARIA es la pared. El control de seguridad obligatorio es el acierto: si
la especulacion cambia lo que la tarea logra, no vale ni aunque acelere.

BRAZOS INTERCALADOS A (COGNIA_ESPECULAR=0) y B (=1), postcondicion de DISCO.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\ab_especulacion.py [n]
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

TAREA = ("listá los ficheros del directorio actual, leé el fichero notas.txt y "
         "escribí en resumen.txt cuántas líneas tiene notas.txt")


def preparar(ws):
    (Path(ws) / "notas.txt").write_text("uno\ndos\ntres\n", encoding="utf-8")
    (Path(ws) / "otro.md").write_text("# doc\n", encoding="utf-8")


def postcondicion(ws):
    f = Path(ws) / "resumen.txt"
    return f.is_file() and "3" in f.read_text(encoding="utf-8", errors="replace")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli
    from cognia.multiverso import especulacion
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    res = {"A": [], "B": []}
    for i in range(n):
        for brazo, on in (("A", False), ("B", True)):
            os.environ["COGNIA_ESPECULAR"] = "1" if on else "0"
            if on:
                especulacion.reiniciar()
            ws = Path(tempfile.mkdtemp(prefix="ab_esp_")).resolve()
            preparar(ws)
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
            est = especulacion.estadisticas() if on else {}
            fila = {"ok": postcondicion(ws), "pared": pared, "est": est}
            res[brazo].append(fila)
            print(f"  {i+1}/{n} brazo {brazo} (especular={int(on)}): "
                  f"ok={fila['ok']} pared={pared:.0f}s"
                  + (f" espec={est.get('especuladas')} "
                     f"acept={est.get('aceptadas')} "
                     f"(igualdad {est.get('aceptadas_igualdad')}, "
                     f"equivalencia {est.get('aceptadas_equivalencia')})"
                     if on else ""), flush=True)

    print()
    for brazo in ("A", "B"):
        oks = sum(1 for r in res[brazo] if r["ok"])
        pared = sum(r["pared"] for r in res[brazo]) / max(1, len(res[brazo]))
        print(f"BRAZO {brazo}: {oks}/{len(res[brazo])} OK, pared media {pared:.0f}s")
    esp = sum((r["est"] or {}).get("especuladas", 0) for r in res["B"])
    acc = sum((r["est"] or {}).get("aceptadas", 0) for r in res["B"])
    ig = sum((r["est"] or {}).get("aceptadas_igualdad", 0) for r in res["B"])
    eq = sum((r["est"] or {}).get("aceptadas_equivalencia", 0) for r in res["B"])
    tasa = (acc / esp * 100) if esp else 0.0
    print(f"ESPECULACION: {esp} especuladas, {acc} aceptadas ({tasa:.0f}%) — "
          f"{ig} por igualdad, {eq} por equivalencia de efecto")
    neto = (sum(1 for r in res["B"] if r["ok"])
            - sum(1 for r in res["A"] if r["ok"]))
    d = (sum(r["pared"] for r in res["B"]) - sum(r["pared"] for r in res["A"])) / max(1, n)
    print(f"NETO acierto B-A: {neto:+d}   delta pared: {d:+.0f}s por tarea")


if __name__ == "__main__":
    main()
