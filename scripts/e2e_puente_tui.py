"""
scripts/e2e_puente_tui.py -- Verificacion REAL del puente bus -> Textual.

Que corre (nada de juguetes):
  * la App REAL (cognia.tui.app.CogniaTUI) headless via app.run_test();
  * el bus REAL (cognia.ux.events) con el SINK STDOUT del movil activado
    (COGNIA_EVENTS_JSONL=1) al mismo tiempo que el puente;
  * 4 hilos emitiendo 400 TokenTexto cada uno, como el motor de workflows.

Que exige (los dos lados del contrato a la vez):
  1. El puente reconstruye los 4 streams BYTE A BYTE, sin cruzarlos, y cierra
     los 4 agentes y la corrida.
  2. El TELEFONO NO SE ROMPE: las lineas "@EV " que salen por el stdout real se
     parsean con el parser REAL del remoto (remoto/sesiones.parsear_evento +
     interpretar_evento) y los eventos por agente siguen llegando enteros. Esa
     es la restriccion dura: una vista de agentes que deje ciego al movil no
     sirve para nada.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_puente_tui.py
Sale 0 si todo pasa, 1 si algo falla (y dice que).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import threading
import time

# El sink stdout se engancha en el import del CLI/arranque; aca se activa a mano
# ANTES de crear la App, que es como lo hace remoto/sesiones.py (env + arranque).
os.environ.setdefault("COGNIA_EVENTS_JSONL", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognia.remoto.sesiones import interpretar_evento, parsear_evento  # noqa: E402
from cognia.tui.app import CogniaTUI                                    # noqa: E402
from cognia.tui.puente import conectar_puente, desconectar_puente       # noqa: E402
from cognia.ux import events                                            # noqa: E402

N_AGENTES = 4
N_EVENTOS = 400
RUN = "e2e-puente"

fallos: list = []


def check(cond: bool, etiqueta: str, detalle: str = "") -> None:
    marca = "OK  " if cond else "FALLA"
    print(f"  [{marca}] {etiqueta}" + (f" -- {detalle}" if detalle else ""))
    if not cond:
        fallos.append(etiqueta)


def texto_esperado(k: int) -> str:
    return "".join(f"[{k}:{i}]" for i in range(N_EVENTOS))


def emisor(k: int, barrera: threading.Barrier, peores: list) -> None:
    """Un agente entero desde SU hilo, igual que workflows.agente()."""
    aid = f"{RUN}#pasos.{k + 1}@{k + 1}"
    tok = events.marcar_agente(aid)
    try:
        barrera.wait(timeout=20)
        events.emitir(events.AgenteInicio(
            run_id=RUN, agente_id=aid, indice=k + 1, total=N_AGENTES,
            fase="pasos", etiqueta=f"lente {k}"))
        peor = 0.0
        for i in range(N_EVENTOS):
            t0 = time.perf_counter()
            events.emitir(events.TokenTexto(texto=f"[{k}:{i}]"))
            peor = max(peor, time.perf_counter() - t0)
            if i % 100 == 99:
                events.emitir(events.AgenteProgreso(
                    run_id=RUN, chars=(i + 1) * 8, intento=1))
        events.emitir(events.AgenteFin(
            run_id=RUN, agente_id=aid, indice=k + 1, total=N_AGENTES,
            fase="pasos", etiqueta=f"lente {k}", ok=True, tokens=100 + k,
            intentos=1, duracion_s=1.0, resumen=f"listo {k}"))
        peores.append(peor)
    finally:
        events.desmarcar_agente(tok)


def emisor_a_ritmo(k: int, n: int, pausa: float, run: str) -> None:
    """Un agente al ritmo REAL de un modelo local (~70 tok/s por agente)."""
    aid = f"{run}#pasos.{k + 1}@{k + 1}"
    tok = events.marcar_agente(aid)
    try:
        events.emitir(events.AgenteInicio(run_id=run, agente_id=aid,
                                          indice=k + 1, total=N_AGENTES,
                                          fase="pasos", etiqueta=f"ritmo {k}"))
        for i in range(n):
            events.emitir(events.TokenTexto(texto=f"({k}:{i})"))
            time.sleep(pausa)
        events.emitir(events.AgenteFin(run_id=run, agente_id=aid, indice=k + 1,
                                       total=N_AGENTES, ok=True, tokens=n))
    finally:
        events.desmarcar_agente(tok)


async def fase_ritmo_real(pilot, p) -> tuple:
    """Segunda fase: 4 agentes a 70 tok/s (lo que da el modelo de verdad).

    POR QUE EXISTE: la fase de rafaga emite ~50.000 eventos/s, 700x mas rapido
    que el modelo real, y con 4 hilos hambrientos el GIL no le deja un hueco al
    loop de Textual hasta que terminan. Eso NO mide si el panel va en vivo:
    mide el GIL. A ritmo real (time.sleep suelta el GIL) si se puede medir."""
    run = "e2e-puente-ritmo"
    n, pausa = 40, 1.0 / 70
    base = p.estado.aplicados
    events.emitir(events.WorkflowInicio(run_id=run, nombre="ritmo",
                                        total_agentes=N_AGENTES))
    hilos = [threading.Thread(target=emisor_a_ritmo, args=(k, n, pausa, run),
                              name=f"ritmo-{k}") for k in range(N_AGENTES)]
    for h in hilos:
        h.start()
    lecturas, en_vivo = [], 0
    for _ in range(4000):
        await pilot.pause()
        await asyncio.sleep(0.005)
        if any(h.is_alive() for h in hilos):
            en_vivo = max(en_vivo, p.estado.aplicados - base)
            lecturas.append(p.estado.aplicados - base)
        elif p.pendientes == 0:
            break
    for h in hilos:
        h.join(timeout=20)
    p.drenar(10 ** 6)
    total = 1 + N_AGENTES * (n + 2)
    return run, total, en_vivo, len(set(lecturas))


async def main() -> int:
    # El stdout REAL se desvia a un buffer para poder LEER lo que el sink
    # escribe (es lo que hace el pipe de remoto/sesiones.py con stdout=PIPE).
    # events._stdout_real() devuelve sys.__stdout__, asi que se reemplaza ese.
    consola = sys.__stdout__
    tuberia = io.StringIO()
    sys.__stdout__ = tuberia
    events.activar_sink_jsonl()          # el canal del movil, encendido
    try:
        print("== e2e puente TUI: App REAL headless + sink del movil ==",
              file=consola)
        app = CogniaTUI()
        async with app.run_test() as pilot:
            p = conectar_puente(app)
            events.emitir(events.WorkflowInicio(
                run_id=RUN, nombre="e2e-puente", total_agentes=N_AGENTES,
                interactivo=True))

            peores: list = []
            barrera = threading.Barrier(N_AGENTES)
            hilos = [threading.Thread(target=emisor, args=(k, barrera, peores),
                                      name=f"emisor-{k}")
                     for k in range(N_AGENTES)]
            t0 = time.perf_counter()
            for h in hilos:
                h.start()
            # Se mide si el panel se entera EN VIVO o recien al final: cuantos
            # eventos ya estaban aplicados mientras los hilos seguian emitiendo.
            en_vivo = 0
            for _ in range(6000):
                await pilot.pause()
                await asyncio.sleep(0.001)
                if any(h.is_alive() for h in hilos):
                    en_vivo = max(en_vivo, p.estado.aplicados)
                elif p.pendientes == 0:
                    break
            for h in hilos:
                h.join(timeout=20)
            for _ in range(300):
                if p.pendientes == 0:
                    break
                await pilot.pause()
            p.drenar(10 ** 6)
            events.emitir(events.WorkflowFin(
                run_id=RUN, nombre="e2e-puente", ok=True, agentes=N_AGENTES,
                fallidos=0, tokens=406, duracion_s=time.perf_counter() - t0,
                total_agentes=N_AGENTES, arrancados=N_AGENTES))
            p.drenar(10 ** 6)
            pared = time.perf_counter() - t0
            ritmo = await fase_ritmo_real(pilot, p)
            estado, met = p.estado, p.metricas()
            desconectar_puente()
    finally:
        sys.__stdout__ = consola

    salida = tuberia.getvalue()

    # ---- 1. el puente ----------------------------------------------------
    print("\n-- LADO TUI (el puente) --")
    for k in range(N_AGENTES):
        aid = f"{RUN}#pasos.{k + 1}@{k + 1}"
        a = estado.agente(aid)
        esperado = texto_esperado(k)
        ok = a is not None and a.texto == esperado and a.completo and a.estado == "ok"
        check(ok, f"agente {k}: {len(esperado)} chars byte a byte",
              "" if ok else f"reconstruido={0 if a is None else len(a.texto)}")
        if a is not None:
            check(all(f"[{j}:" not in a.texto for j in range(N_AGENTES) if j != k),
                  f"agente {k}: sin contaminacion cruzada")
    c = estado.corrida(RUN)
    check(c is not None and len(c.agentes_vista) == N_AGENTES and not c.abierta
          and c.vivos == [], "corrida cerrada con los 4 agentes")
    run2, total2, en_vivo2, lecturas2 = ritmo
    total = 1 + N_AGENTES * (N_EVENTOS + 2 + 4) + 1 + total2
    check(met["encolados"] == total and estado.aplicados == total,
          f"{total} eventos encolados y aplicados (rafaga + ritmo real)",
          f"encolados={met['encolados']} aplicados={estado.aplicados}")
    for k in range(N_AGENTES):
        a = estado.agente(f"{run2}#pasos.{k + 1}@{k + 1}")
        esperado2 = "".join(f"({k}:{i})" for i in range(40))
        check(a is not None and a.texto == esperado2 and a.estado == "ok",
              f"ritmo real, agente {k}: stream byte a byte")
    check(met["descartados"] == 0, "cero descartes con la App al dia")
    check(met["wakeups"] < total, "despertador coalescido",
          f"wakeups={met['wakeups']} para {total} eventos")

    # ---- 2. el telefono --------------------------------------------------
    print("\n-- LADO MOVIL (stdout del sink, parser REAL del remoto) --")
    lineas = [x for x in salida.splitlines() if x.strip()]
    eventos, no_parseables = [], 0
    for linea in lineas:
        d = parsear_evento(linea)
        if d is None:
            no_parseables += 1
        else:
            eventos.append(d)
    check(no_parseables == 0, "todas las lineas del sink parsean",
          f"no parseables={no_parseables} de {len(lineas)}")
    tipos: dict = {}
    for d in eventos:
        tipos[d.get("tipo", "?")] = tipos.get(d.get("tipo", "?"), 0) + 1
    # Las dos fases: 4 agentes cada una, 2 WorkflowInicio y 1 WorkflowFin.
    check(tipos.get("AgenteInicio", 0) == 2 * N_AGENTES
          and tipos.get("AgenteFin", 0) == 2 * N_AGENTES,
          "los 8 AgenteInicio y los 8 AgenteFin llegaron al movil", str(tipos))
    check(tipos.get("WorkflowInicio", 0) == 2 and tipos.get("WorkflowFin", 0) == 1,
          "WorkflowInicio/Fin llegaron al movil")
    check("TokenTexto" not in tipos,
          "TokenTexto sigue SIN ir por stdout (contrato del sink intacto)")
    clasificados = 0
    for d in eventos:
        quien, texto, _ecos = interpretar_evento(d)
        if quien and texto:
            clasificados += 1
    check(clasificados >= 2 * N_AGENTES,
          "el remoto clasifica las lineas por agente",
          f"clasificadas={clasificados} de {len(eventos)}")

    print("\n-- EN VIVO (el panel se entera mientras el motor genera) --")
    check(en_vivo2 > 0 and lecturas2 > 3,
          "a ritmo real (70 tok/s x 4) el panel avanza DURANTE la generacion",
          f"{en_vivo2} de {total2} aplicados con los hilos aun emitiendo, "
          f"en {lecturas2} lecturas distintas")
    print(f"  RAFAGA (~50.000 ev/s, 700x el modelo real): {en_vivo} de "
          f"{1 + N_AGENTES * (N_EVENTOS + 6) + 1} aplicados en vivo.")
    print("    No es un defecto del puente: 4 hilos emitiendo a esa velocidad")
    print("    no le sueltan el GIL al loop de Textual hasta que terminan.")
    print("    Nada se pierde ni se cruza; el panel salta de golpe al final.")

    print(f"\n  pared rafaga={pared * 1000:.0f} ms  peor emitir()="
          f"{max(peores) * 1000:.3f} ms  pasadas={met['pasadas']}  "
          f"pico_pendientes={met['pico_pendientes']}")
    print(f"  lineas @EV al movil: {len(lineas)}")

    if fallos:
        print(f"\nRESULTADO: {len(fallos)} FALLOS -> " + ", ".join(fallos))
        return 1
    print("\nRESULTADO: todo OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
