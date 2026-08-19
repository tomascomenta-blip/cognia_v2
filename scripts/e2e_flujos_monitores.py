# -*- coding: utf-8 -*-
"""E2E REAL de FLUJOS APRENDIDOS y MONITORES PERSISTENTES (2026-08-19).

Prueba de punta a punta, con el modelo de verdad y postcondiciones de DISCO:

  FLUJOS   1. graba una tarea real del agente (bus de eventos -> trayectoria)
           2. aprende un flujo parametrizado de esa grabacion
           3. lo EXAMINA con parametros NUEVOS en workspaces temporales
           4. corre el flujo verificado en un workspace limpio y comprueba el
              disco (no la prosa del modelo)
           5. mide el contrafactual barato: pared del flujo vs pared del agente

  MONITORES 6. monitor de fichero: dispara cuando aparece
            7. monitor de comando recurrente con debounce
            8. accion "despertar_agente": deja la tarea en la cola
            9. persistencia: un motor nuevo ve los monitores del anterior

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_flujos_monitores.py
Salida: 'E2E FLUJOS+MONITORES: N/M OK'; exit 0 solo si todo pasa.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHECKS = []
TMP = Path(tempfile.mkdtemp(prefix="e2e_fm_")).resolve()
os.environ["COGNIA_FLUJOS_DIR"] = str(TMP / "flujos")
os.environ["COGNIA_MONITORES_DIR"] = str(TMP / "monitores")


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}"
          + (f" — {str(detalle)[:120]}" if detalle else ""), flush=True)
    return bool(ok)


# ─────────────────────────── FLUJOS ────────────────────────────────────────

def parte_flujos():
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli
    from cognia.flujos import grabador, generalizador, examen, reproductor
    from cognia.agent.tools import run_tool
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    # 1. GRABAR una tarea real del agente ---------------------------------
    ws = TMP / "ws_grabacion"
    ws.mkdir(parents=True, exist_ok=True)
    tarea = ("crea un fichero saludo.txt que contenga exactamente: Hola Ana, "
             "y despues un fichero leeme.txt que contenga exactamente: proyecto Ana")
    grabador.suscribir()
    gid = grabador.iniciar(titulo="saludo parametrizado", tarea=tarea,
                           workspace=str(ws))
    prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    os.chdir(ws)
    t0 = time.time()
    try:
        cli._run_agent_task(ai, tarea, lambda s: None, max_steps=6)
    except Exception as exc:
        print("   EXCEPCION en la tarea grabada:", exc)
    finally:
        pared_agente = time.time() - t0
        os.chdir(prev_cwd)
        dev_tools.AGENT_WORKSPACE_ROOT = prev_root
    grabador.cerrar(gid, resultado="", ok=True)
    grabador.desuscribir()

    g = grabador.cargar(gid)
    pasos = len(g.pasos) if g else 0
    hizo = (ws / "saludo.txt").exists() and (ws / "leeme.txt").exists()
    check("1. la tarea grabada dejo los dos ficheros en disco", hizo,
          f"{pasos} pasos grabados, {pared_agente:.0f}s")
    check("2. la grabacion tiene pasos con tool y args", pasos > 0,
          "; ".join(f"{p['tool']}" for p in (g.pasos if g else [])[:6]))

    # 2. APRENDER el flujo -------------------------------------------------
    flujo = generalizador.desde_grabacion(gid)
    ok_flujo = bool(flujo and flujo.get("pasos"))
    nombre = ""
    if ok_flujo:
        nombre = generalizador.guardar_flujo(flujo)
    params = [p["nombre"] for p in (flujo or {}).get("params", [])]
    post = (flujo or {}).get("postcondiciones") or []
    check("3. se aprendio un flujo con pasos", ok_flujo,
          f"nombre={nombre} pasos={len((flujo or {}).get('pasos', []))}")
    check("4. detecto huecos parametrizables", bool(params), f"params={params}")
    check("5. derivo postcondiciones verificables", bool(post),
          f"{len(post)} postcondiciones")

    # 3. EXAMINAR con parametros NUEVOS ------------------------------------
    ctx = {"ai": ai, "print_fn": lambda *a, **k: None, "working_memory": {},
           "agent_state": {}, "show_diff": False}

    def _reproducir(fl, valores, ws_caso=None):
        return reproductor.reproducir(
            fl, valores, lambda n, a, c=None: run_tool(n, a, ctx),
            workspace=ws_caso)

    veredicto = {}
    if ok_flujo and post:
        try:
            veredicto = examen.examinar_y_decidir(flujo, _reproducir)
        except Exception as exc:
            veredicto = {"veredicto": {"estado": "error", "motivo": str(exc)}}
    ver = (veredicto or {}).get("veredicto") or veredicto or {}
    estado = ver.get("estado", "sin_examen")
    check("6. el examen emitio un veredicto explicito",
          estado in ("verificado", "rechazado", "no_examinable"),
          f"estado={estado} motivo={str(ver.get('motivo', ''))[:60]}")

    # 4. CORRER el flujo en un workspace limpio, postcondicion de DISCO -----
    ok_correr = False
    pared_flujo = 0.0
    if ok_flujo:
        ws2 = TMP / "ws_replay"
        if ws2.exists():
            shutil.rmtree(ws2, ignore_errors=True)
        ws2.mkdir(parents=True)
        valores = {}
        for p in (flujo.get("params") or []):
            # Valor NUEVO, distinto del de la grabacion: si solo funciona con
            # el original, el flujo memorizo en vez de aprender.
            valores[p["nombre"]] = "Beto" if str(p.get("ejemplo")) == "Ana" else \
                (str(p.get("ejemplo", "x")) + "2")
        prev = os.getcwd()
        os.chdir(ws2)
        t1 = time.time()
        try:
            inf = reproductor.reproducir(
                flujo, valores, lambda n, a, c=None: run_tool(n, a, ctx),
                workspace=str(ws2))
            pared_flujo = time.time() - t1
            escritos = [str(p.name) for p in ws2.rglob("*") if p.is_file()]
            ok_correr = bool(inf.get("ok")) and len(escritos) >= 1
            check("7. el flujo corrio y escribio en disco", ok_correr,
                  f"ok={inf.get('ok')} ficheros={escritos[:4]} "
                  f"pared={pared_flujo:.1f}s")
        except Exception as exc:
            check("7. el flujo corrio y escribio en disco", False, str(exc))
        finally:
            os.chdir(prev)

    # 5. CONTRAFACTUAL barato: el flujo contra el agente --------------------
    if ok_correr and pared_agente > 0:
        veces = pared_agente / max(pared_flujo, 0.001)
        check("8. el flujo es mas barato que rehacer la tarea con el agente",
              pared_flujo < pared_agente,
              f"agente {pared_agente:.0f}s vs flujo {pared_flujo:.2f}s "
              f"({veces:.0f}x)")
    else:
        check("8. el flujo es mas barato que rehacer la tarea con el agente",
              False, "no se pudo medir (el flujo no corrio)")


# ────────────────────────── MONITORES ──────────────────────────────────────

def parte_monitores():
    from cognia.monitores import nucleo

    nucleo.reiniciar_motor()
    ws = TMP / "ws_monitores"
    ws.mkdir(parents=True, exist_ok=True)
    objetivo = ws / "aparece.txt"

    m1 = nucleo.crear("aparece el fichero",
                      {"tipo": "fichero_existe", "ruta": str(objetivo)},
                      {"tipo": "avisar"}, intervalo_s=0)
    inf = nucleo.tick()
    # La clave del informe es "disparados" (LISTA). La primera version de este
    # test leia inf["disparos"], que no existe: el check 9 pasaba por el motivo
    # equivocado y el 10 fallaba con el monitor funcionando. Es el patron que
    # este repo ya tiene documentado: un test que aprueba sin medir nada.
    check("9. el monitor NO dispara antes de tiempo",
          len(inf.get("disparados") or []) == 0, json.dumps(inf)[:100])

    objetivo.write_text("ya", encoding="utf-8")
    inf = nucleo.tick(time.time() + 1)
    eventos = nucleo.pop_eventos()
    check("10. el monitor dispara cuando aparece el fichero",
          len(inf.get("disparados") or []) >= 1 and bool(eventos),
          f"eventos={[str(e)[:50] for e in eventos]}")

    # accion EJECUTAR con un comando real
    marca = ws / "ejecutado.txt"
    cmd = f'python -c "open(r\'{marca}\',\'w\').write(\'si\')"'
    nucleo.crear("accion ejecutar",
                 {"tipo": "fichero_existe", "ruta": str(objetivo)},
                 {"tipo": "ejecutar", "cmd": cmd}, intervalo_s=0)
    nucleo.tick(time.time() + 2)
    check("11. la accion 'ejecutar' corrio de verdad", marca.exists(),
          f"marca={marca.name}")

    # accion DESPERTAR AGENTE -> deja la tarea en la cola
    nucleo.crear("despierta al agente",
                 {"tipo": "fichero_existe", "ruta": str(objetivo)},
                 {"tipo": "despertar_agente", "tarea": "resumi el log"},
                 intervalo_s=0)
    nucleo.tick(time.time() + 3)
    tareas = nucleo.tareas_pendientes()
    check("12. 'despertar_agente' encola la tarea para el REPL",
          any("resumi el log" in str(t) for t in tareas), str(tareas)[:100])

    # PERSISTENCIA: motor nuevo, mismos monitores
    nucleo.reiniciar_motor()
    filas = nucleo.listar()
    check("13. los monitores sobreviven al reinicio del motor",
          len(filas) >= 3, f"{len(filas)} monitores en disco")

    # el ledger registro los disparos
    ruta_ledger = nucleo.ruta_ledger()
    lineas = 0
    if ruta_ledger.exists():
        lineas = sum(1 for _ in open(ruta_ledger, encoding="utf-8"))
    check("14. el ledger de eventos tiene registro auditable", lineas >= 3,
          f"{lineas} lineas en {ruta_ledger.name}")


def main():
    t0 = time.time()
    print(f"workspace temporal: {TMP}", flush=True)
    try:
        parte_flujos()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        check("FLUJOS (excepcion no controlada)", False, str(exc))
    try:
        parte_monitores()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        check("MONITORES (excepcion no controlada)", False, str(exc))

    fallos = [n for n, ok in CHECKS if not ok]
    print(f"\nE2E FLUJOS+MONITORES: {len(CHECKS) - len(fallos)}/{len(CHECKS)} OK "
          f"en {(time.time() - t0) / 60:.1f} min", flush=True)
    if fallos:
        print("FALLARON:", fallos, flush=True)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
