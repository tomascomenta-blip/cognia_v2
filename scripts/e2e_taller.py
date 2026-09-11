# -*- coding: utf-8 -*-
"""E2E del TALLER con el modelo REAL (2026-09-10): tareas humanas cotidianas de
Blender/Godot y del cierre de programas, con postcondicion en DISCO o en el
ESCRITORIO (nunca en la prosa del modelo). Mismo esqueleto que
scripts/e2e_happy_path.py (agente real en proceso, modo efimero).

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_taller.py
Salida: 'E2E TALLER: N/4 OK'; exit 0 si 4/4.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# el repo por delante del cognia instalado en site-packages (leccion: `python
# -m cognia` fuera del repo importa el INSTALADO)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("COGNIA_EFIMERO", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}" + (f" — {str(detalle)[:160]}" if detalle else ""), flush=True)


def main():
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from cognia.agent import taller_tools as TT
    from cognia.agent import escritorio_propio as EP
    from cognia.agent import app_tools as AT
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch
    lineas = []

    def hacer(tarea, verificar, pasos=14):
        ws = Path(tempfile.mkdtemp(prefix="taller_")).resolve()
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.chdir(ws)
        salida = []
        try:
            resp = _cli._run_agent_task(ai, tarea, lambda s: salida.append(str(s)), max_steps=pasos)
        except Exception as exc:
            resp = f"EXCEPTION: {exc}"
        finally:
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        programas = [s for s in salida if "Programas:" in s]
        try:
            return verificar(ws), (str(resp) or "")[:200], programas, ws
        except Exception as exc:
            return False, f"verify exc: {exc}", programas, ws

    def _ventanas_mesa(trozo):
        try:
            return [t for _h, _p, t in EP.ventanas_en_escritorio() if trozo.lower() in (t or "").lower()]
        except Exception:
            return []

    # -- 1. Godot: proyecto que verifica sin errores ---------------------
    def v_godot(ws):
        proy = next((p.parent for p in ws.rglob("project.godot")), None)
        if proy is None:
            return False
        r = TT.verificar(str(proy))
        gd = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in proy.rglob("*.gd"))
        return r["errores"] == 0 and ("velocity" in gd.lower() or "velocidad" in gd.lower() or "move" in gd.lower())

    # -- 2. Blender: taza guardada y exportada; Blender cerrado al acabar --
    def v_blender(ws):
        glb = list(ws.rglob("*.glb")) + list(Path(TT.CARPETA).rglob("taza*.glb"))
        blend = list(ws.rglob("*.blend")) + list(Path(TT.CARPETA).rglob("taza*.blend"))
        ok_fich = any(p.stat().st_size > 500 for p in glb) and bool(blend)
        time.sleep(2)
        cerrado = not TT.puerto_abierto()
        check("  blender cerrado al acabar (ya no lo necesitaba)", cerrado)
        return ok_fich

    # -- 3. Referencias de internet --------------------------------------
    def v_refs(ws):
        carpeta = Path(TT.CARPETA) / "referencias"
        imgs = [p for p in carpeta.rglob("*") if p.suffix.lower() in (".png", ".jpg") and "mario" in str(p).lower()]
        return len(imgs) >= 2

    # -- 4. Cierre: lo que el usuario pide ver se queda abierto -----------
    def v_calc(ws):
        time.sleep(2)
        abiertas = _ventanas_mesa("calc")
        return bool(abiertas)

    tareas = [
        ("godot-pong", "creá un proyecto de Godot llamado pong con una pelota que rebote por la pantalla "
                       "y comprobá que no tiene errores", v_godot),
        ("blender-taza", "abrí Blender, modelá una taza sencilla (un cilindro hueco con un asa de toro) y "
                         "guardala como taza.blend y exportala como taza.glb en el workspace", v_blender),
        ("referencias", "buscá en internet imágenes de referencia de Mario Bros desde varios ángulos "
                        "para modelarlo en Blender", v_refs),
        ("calculadora", "abrime la calculadora en la mesa y dejala abierta que la voy a usar", v_calc),
    ]
    # `e2e_taller.py godot-pong calculadora` corre solo esas
    filtro = [a for a in sys.argv[1:] if not a.startswith("-")]
    if filtro:
        tareas = [t for t in tareas if t[0] in filtro]
    t0 = time.time()
    for nombre, tarea, verificar in tareas:
        t1 = time.time()
        print(f"\n== {nombre}: {tarea}", flush=True)
        ok, resp, programas, ws = hacer(tarea, verificar)
        check(nombre, ok, f"{int(time.time() - t1)}s · {resp}")
        for p in programas:
            print("    " + p[:200], flush=True)
        lineas.append((nombre, ok, resp, programas))
    # limpieza: cerrar lo que quedo (calculadora mantenida a proposito)
    try:
        for r in AT.cerrar_todas():
            print("  limpieza:", r)
    except Exception as exc:
        print("  limpieza fallo:", exc)
    try:
        TT.cerrar_blender(guardar_antes=False)
    except Exception:
        pass
    n_ok = sum(1 for _n, ok in CHECKS if ok)
    print(f"\nE2E TALLER: {n_ok}/{len(CHECKS)} OK  ({int(time.time() - t0)}s)")
    return 0 if n_ok == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
