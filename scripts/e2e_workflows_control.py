# -*- coding: utf-8 -*-
"""
scripts/e2e_workflows_control.py — verificacion REAL del control por agente
===========================================================================
No es pytest: es el cierre obligatorio (regla 4 del CLAUDE.md). Lanza UNA
corrida de 3 agentes contra :8080 EN UN HILO y, desde el hilo principal:

  (1) INTERRUMPE al agente 2 a mitad de generacion  -> se mide el corte;
  (2) le HABLA al agente 3 a mitad de generacion    -> la respuesta final
      tiene que reflejar el mensaje, no el prompt original.

Y ademas comprueba que el slot del server queda LIBRE tras el corte: apenas
llega el AgenteFin del 2, el hilo principal dispara una peticion minima
(max_tokens=8) y la cronometra. Si el corte no hubiera cerrado la conexion,
esa peticion quedaria encolada detras de los ~2048 tokens que el 2 todavia
estaria generando.

Uso:  venv312\\Scripts\\python.exe scripts\\e2e_workflows_control.py
"""
from __future__ import annotations

import sys
import threading
import time

from cognia.agent.workflows import (agente, cancelar_agente, corrida, decirle,
                                    estado_agente)
from cognia.ux import events as ux

PALABRA = "BANANA"
PROMPTS = [
    "Responde en UNA sola linea, sin preambulo: cual es la capital de Francia.",
    ("Escribe un ensayo LARGO y detallado (minimo 600 palabras) sobre la "
     "historia del reloj mecanico en Europa. No resumas."),
    ("Escribe un ensayo LARGO y detallado (minimo 600 palabras) sobre la "
     "historia de la navegacion astronomica. No resumas."),
]

_t0 = time.perf_counter()
_reloj_lock = threading.Lock()


def _log(msg: str) -> None:
    with _reloj_lock:
        print(f"[{time.perf_counter() - _t0:7.3f}s] {msg}", flush=True)


# --- lo que el hilo principal necesita saber, via BUS (el unico handle que
# --- tiene una vista: WorkflowInicio.run_id y AgenteInicio.agente_id)
ids: dict = {}
fines: dict = {}
chars: dict = {}
prog: dict = {}


def _escucha(ev) -> None:
    if isinstance(ev, ux.AgenteInicio):
        ids[ev.indice] = ev.agente_id
        _log(f"AgenteInicio  idx={ev.indice} id={ev.agente_id}")
    elif isinstance(ev, ux.AgenteProgreso):
        prog[ev.agente_id] = prog.get(ev.agente_id, 0) + 1
    elif isinstance(ev, ux.TokenTexto):
        chars[ev.agente_id] = chars.get(ev.agente_id, 0) + len(ev.texto)
    elif isinstance(ev, ux.MensajeAlAgente):
        _log(f"MensajeAlAgente destino={ev.destino} aceptado={ev.aceptado} "
             f"estado={ev.estado} pendientes={ev.pendientes}")
    elif isinstance(ev, ux.AgenteFin):
        fines[ev.indice] = ev
        _log(f"AgenteFin     idx={ev.indice} ok={ev.ok} cancelado={ev.cancelado} "
             f"repreguntas={ev.repreguntas} intentos={ev.intentos} "
             f"tokens={ev.tokens} descartado_chars={ev.descartado_chars} "
             f"dur={ev.duracion_s:.2f}s motivo={ev.motivo[:70]!r}")
    elif isinstance(ev, ux.WorkflowFin):
        _log(f"WorkflowFin   ok={ev.ok} agentes={ev.agentes} "
             f"fallidos={ev.fallidos} cancelados={ev.cancelados} "
             f"tokens={ev.tokens} resumen={ev.resumen!r}")


def _sonda_slot() -> float:
    """Peticion minima al server; devuelve la pared en segundos."""
    from cognia.agent.chat_client import completar
    t = time.perf_counter()
    r = completar([{"role": "user", "content": "di OK"}],
                  url="http://127.0.0.1:8080", max_tokens=8, razonador=False,
                  via="sonda_slot")
    seg = time.perf_counter() - t
    _log(f"sonda del slot: {seg:.2f}s  error={r.error!r} texto={r.texto[:30]!r}")
    return seg


def main() -> int:
    ux.suscribir(_escucha)
    c = corrida("control-e2e", presupuesto_tokens=60_000, total_agentes=3,
                interactivo=True, print_fn=lambda *a, **k: None)
    _log(f"corrida {c.run_id} interactivo={c.interactivo} dir={c.dir}")

    resultados: dict = {}
    listo = threading.Event()

    def _correr():
        try:
            for i, p in enumerate(PROMPTS, 1):
                resultados[i] = agente(c, p, indice=i, total=3, fase="pasos",
                                       max_tokens=2048,
                                       url="http://127.0.0.1:8080")
                time.sleep(1.2)     # ventana para la sonda del slot
        finally:
            listo.set()

    hilo = threading.Thread(target=_correr, name="corrida", daemon=True)
    hilo.start()

    def _esperar_id(idx: int, tope: float = 180.0) -> str:
        fin = time.perf_counter() + tope
        while time.perf_counter() < fin:
            if idx in ids:
                return ids[idx]
            time.sleep(0.02)
        raise SystemExit(f"el agente {idx} nunca arranco")

    # ── (1) interrumpir al agente 2 a mitad de generacion ──────────────────
    aid2 = _esperar_id(2)
    time.sleep(3.0)                 # que este generando de verdad
    _log(f"estado del 2 antes de cortar: {estado_agente(aid2)} "
         f"(chars ya emitidos: {chars.get(aid2, 0)})")
    t_corte = time.perf_counter()
    env = cancelar_agente(aid2, "el usuario aprieta interrumpir")
    _log(f"cancelar_agente -> {env}")
    while 2 not in fines and time.perf_counter() - t_corte < 30:
        time.sleep(0.01)
    corte_s = time.perf_counter() - t_corte
    _log(f"*** CORTE MEDIDO: {corte_s:.3f}s desde cancelar_agente hasta "
         f"AgenteFin ***")
    sonda_s = _sonda_slot()

    # ── (2) hablarle al agente 3 a mitad de generacion ─────────────────────
    aid3 = _esperar_id(3)
    time.sleep(3.0)
    _log(f"chars del 3 antes de hablarle: {chars.get(aid3, 0)}")
    env3 = decirle(aid3, "OLVIDA todo lo anterior. Responde EXACTAMENTE con "
                         f"una sola palabra en mayusculas: {PALABRA}. Nada mas.")
    _log(f"decirle -> {env3}")

    listo.wait(600)
    c.cerrar(ok=True)

    # ── veredicto ──────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    r3 = str(resultados.get(3, ""))
    print(f"resultado del agente 1: {str(resultados.get(1, ''))[:120]!r}")
    print(f"resultado del agente 2: {str(resultados.get(2, ''))[:160]!r}")
    print(f"resultado del agente 3: {r3[:200]!r}")
    print(f"progreso (AgenteProgreso por agente): "
          f"{ {k[-12:]: v for k, v in prog.items()} }")
    print(f"chars en vivo por agente: { {k[-12:]: v for k, v in chars.items()} }")
    print("=" * 72)

    f2, f3 = fines.get(2), fines.get(3)
    checks = [
        ("CORTE < 1 s", corte_s < 1.0, f"{corte_s:.3f}s"),
        ("el 2 sale cancelado", bool(f2 and f2.cancelado and not f2.ok),
         f"cancelado={getattr(f2, 'cancelado', None)} ok={getattr(f2, 'ok', None)}"),
        ("el 2 tiro lo generado",
         bool(f2 and f2.descartado_chars > 0),
         f"descartado_chars={getattr(f2, 'descartado_chars', 0)}"),
        ("el slot quedo libre", sonda_s < 5.0, f"sonda {sonda_s:.2f}s"),
        ("el 3 re-pregunto", bool(f3 and f3.repreguntas == 1),
         f"repreguntas={getattr(f3, 'repreguntas', 0)}"),
        (f"el 3 refleja el mensaje ({PALABRA})", PALABRA in r3.upper(),
         r3[:60]),
        ("el 3 no cacheo el dialogo", bool(f3 and len(c.cache) <= 2),
         f"claves en cache={len(c.cache)}"),
    ]
    ok_total = True
    for nombre, ok, detalle in checks:
        print(f"  {'CHECK OK ' if ok else 'CHECK FAIL'}  {nombre}: {detalle}")
        ok_total = ok_total and ok
    print(f"\njournal: {c.dir / 'journal.jsonl'}")
    ux.desuscribir(_escucha)
    return 0 if ok_total else 1


if __name__ == "__main__":
    sys.exit(main())
