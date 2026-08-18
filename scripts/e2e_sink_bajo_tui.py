"""
e2e_sink_bajo_tui.py -- Verificacion REAL de que el movil sigue viendo el
progreso por agente con la TUI de Textual abierta.

QUE HACE: lanza un SUBPROCESO igual que lo lanza cognia/remoto/sesiones.py
(COGNIA_EVENTS_JSONL=1, PYTHONUNBUFFERED=1, stdout por PIPE, bufsize=1), el
subproceso abre una App de Textual y emite los eventos por agente desde un
HILO worker, y el padre pasa cada linea por el pipeline REAL del remoto
(parsear_evento -> interpretar_evento) para comprobar que llegan Y que se
clasifican bien.

LA CONDICION DE PRODUCCION: con la App abierta, sys.stdout es un
textual.app._PrintCapture que TIRA el texto salvo en modo headless
(textual/app.py:2098). run_test() fuerza headless, asi que el subproceso apaga
ese reenvio de cortesia (app._original_stdout, usado SOLO ahi) para medir lo
que pasa en la app de verdad.

USO:
    venv312\\Scripts\\python.exe scripts\\e2e_sink_bajo_tui.py [--viejo]

    --viejo   emite con el sink de ANTES (print) para medir el baseline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- lo que corre DENTRO del subproceso -------------------------------------
HIJO = r'''
import asyncio, sys, threading
from cognia.ux import events
from cognia.tui.app import CogniaTUI

VIEJO = "--viejo" in sys.argv

events.activar_sink_jsonl()          # lee COGNIA_EVENTS_JSONL=1 del entorno
if VIEJO:
    # El sink de ANTES del fix: print() al sys.stdout del momento.
    import cognia.ux.events as _e
    def _print_viejo(linea):
        print(_e.PREFIJO_STDOUT + linea, flush=True)
    _e._escribir_stdout_real = _print_viejo
    with _e._lock:
        _e._suscriptores.clear()
    _e._sink_jsonl = None
    _e.activar_sink_jsonl("1")

class _Nulo:
    def write(self, t): pass
    def flush(self): pass

def _trabajo():
    # Lo que ve el movil de una corrida de workflows: la vista por agente.
    events.emitir(events.WorkflowInicio(run_id="r1", nombre="e2e", total_agentes=2,
                                        interactivo=True))
    for i in (1, 2):
        aid = f"r1#pasos.{i}@{i}"
        tok = events.marcar_agente(aid)
        events.emitir(events.AgenteInicio(run_id="r1", agente_id=aid, indice=i,
                                          total=2, fase="pasos",
                                          etiqueta=f"paso {i}"))
        events.emitir(events.AgenteProgreso(run_id="r1", chars=120, intento=1))
        events.emitir(events.TokenTexto(texto="esto NO debe salir por stdout"))
        events.emitir(events.AgenteFin(run_id="r1", agente_id=aid, indice=i,
                                       total=2, fase="pasos",
                                       etiqueta=f"paso {i}", ok=True,
                                       tokens=10, intentos=1, resumen="ok"))
        events.desmarcar_agente(tok)
    events.emitir(events.WorkflowFin(run_id="r1", nombre="e2e", ok=True,
                                     agentes=2, tokens=20, total_agentes=2,
                                     arrancados=2))

async def main():
    events.emitir(events.Aviso(texto="antes-de-la-app", origen="e2e"))
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert type(sys.stdout).__name__ == "_PrintCapture", type(sys.stdout)
        app._original_stdout = _Nulo()      # <- la app real no reenvia nada
        h = threading.Thread(target=_trabajo)
        h.start(); h.join(timeout=20)
        await pilot.pause()
    events.emitir(events.Aviso(texto="despues-de-la-app", origen="e2e"))

asyncio.run(main())
'''

ESPERADOS = ["WorkflowInicio", "AgenteInicio", "AgenteProgreso", "AgenteFin",
             "AgenteInicio", "AgenteProgreso", "AgenteFin", "WorkflowFin"]


def main() -> int:
    viejo = "--viejo" in sys.argv
    env = dict(os.environ)
    # EXACTAMENTE lo que pone cognia/remoto/sesiones.py al lanzar el REPL.
    env["COGNIA_EVENTS_JSONL"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"

    cmd = [sys.executable, "-c", HIJO] + (["--viejo"] if viejo else [])
    proc = subprocess.run(cmd, cwd=RAIZ, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=180)

    sys.path.insert(0, RAIZ)
    from cognia.remoto.sesiones import parsear_evento, interpretar_evento

    print(f"== sink {'VIEJO (print)' if viejo else 'NUEVO (stdout real)'} ==")
    print(f"exit={proc.returncode}")

    eventos, clasificados, sin_clasificar = [], [], []
    for linea in proc.stdout.splitlines():
        d = parsear_evento(linea)
        if d is None:
            continue
        eventos.append(d)
        quien, texto, _ecos = interpretar_evento(d)
        if quien is None or not texto:
            sin_clasificar.append(d.get("tipo"))
        else:
            clasificados.append((d.get("tipo"), quien, texto))

    tipos = [d.get("tipo") for d in eventos]
    durante = [t for t in tipos if t in
               ("WorkflowInicio", "AgenteInicio", "AgenteProgreso",
                "AgenteFin", "WorkflowFin")]

    print(f"lineas @EV parseadas : {len(eventos)}")
    print(f"eventos POR AGENTE   : {len(durante)} de {len(ESPERADOS)} "
          f"(los emitidos con la App abierta)")
    print(f"clasificados por el remoto: {len(clasificados)}")
    for tipo, quien, texto in clasificados:
        print(f"   [{quien:9}] {tipo:16} {texto}")
    if sin_clasificar:
        print(f"sin anotar (esperado para TokenTexto y compania): {sin_clasificar}")

    ok = True
    if durante != ESPERADOS:
        print(f"FALLO: se esperaba {ESPERADOS}\n       llego     {durante}")
        ok = False
    if "TokenTexto" in tipos:
        print("FALLO: TokenTexto NO debe ir por stdout (contrato del canal)")
        ok = False
    # Los 8 por agente + los 2 Avisos (antes/despues de la App) = 10 lineas
    # que el remoto tiene que saber poner en algun lado.
    por_agente_clasificados = [c for c in clasificados if c[0] in set(ESPERADOS)]
    if len(por_agente_clasificados) != len(ESPERADOS):
        print(f"FALLO: el remoto solo clasifico {len(por_agente_clasificados)} "
              f"de {len(ESPERADOS)} eventos por agente")
        ok = False
    if len(clasificados) != len(eventos):
        print(f"FALLO: {len(eventos) - len(clasificados)} lineas llegaron pero "
              f"el remoto no supo que hacer con ellas")
        ok = False
    if not any(d.get("texto") == "antes-de-la-app" for d in eventos):
        print("FALLO: falta el evento de ANTES de abrir la App")
        ok = False
    if not any(d.get("texto") == "despues-de-la-app" for d in eventos):
        print("FALLO: falta el evento de DESPUES de cerrar la App")
        ok = False

    print("CHECK:", "OK -- el movil ve el progreso por agente con la TUI abierta"
          if ok else "ROTO -- el movil se queda ciego")
    if proc.stderr.strip():
        print("--- stderr del subproceso ---")
        print(proc.stderr.strip()[:2000])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
