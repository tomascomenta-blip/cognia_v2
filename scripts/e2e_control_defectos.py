# -*- coding: utf-8 -*-
"""
scripts/e2e_control_defectos.py — verificacion REAL de los 6 defectos del
control por agente (2026-08-17), contra :8080
=========================================================================
No es pytest: es el cierre obligatorio (regla 4 del CLAUDE.md). Corre UNA
corrida de 3 pasos por el camino de PRODUCCION —workflows_adapter.ejecutar(
..., interactivo=True)— en un hilo, y desde el hilo principal.

OJO: `interactivo=True` todavia NO lo enciende ningun consumidor. /workflow
(cli.py) y la tool 'workflow' (tools_harness.py) llaman a ejecutar() SIN el
parametro, asi que hoy corren por el camino no-interactivo, byte-identico al
historico. Lo va a encender la vista de agentes; hasta entonces este script es
la unica cosa que ejercita el control.

  (1) CORTA el paso 2 a mitad de generacion,
  (2) le HABLA al paso 3 a mitad de generacion,
  (3) le habla OTRA VEZ al 2, ya cancelado  -> tiene que rechazarlo (#2),
  (4) tras un PANICO global, intenta cancelar el paso 1, que YA ENTREGO ->
      tiene que decir ya_termino (#3).

Y despues imprime, con sus numeros: el ENVELOPE de ejecutar() contra el
WorkflowFin que fue al bus (#1), las tres claves de conteo de los envelopes
de control (#4), el PRESUPUESTO con su parte estimada (#5) y las lineas del
JOURNAL. El coste del corte se contrasta ademas con /tokenize del server.

Uso:  venv312\\Scripts\\python.exe scripts\\e2e_control_defectos.py
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request

from cognia.agent import workflows as motor
from cognia.harness import workflows_adapter as adaptador
from cognia.ux import events as ux

URL = "http://127.0.0.1:8080"
PALABRA = "BANANA"
PASOS = [
    "Responde en UNA sola linea, sin preambulo: cual es la capital de Francia.",
    ("Escribe un ensayo LARGO y detallado (minimo 600 palabras) sobre la "
     "historia del reloj mecanico en Europa. No resumas."),
    ("Escribe un ensayo LARGO y detallado (minimo 600 palabras) sobre la "
     "historia de la navegacion astronomica. No resumas."),
]

_t0 = time.perf_counter()
_lock = threading.Lock()


def _log(msg: str) -> None:
    with _lock:
        print(f"[{time.perf_counter() - _t0:7.3f}s] {msg}", flush=True)


ids: dict = {}
fines: dict = {}
chars: dict = {}
corrida_id: dict = {}
wf_fin: list = []


def _escucha(ev) -> None:
    if isinstance(ev, ux.WorkflowInicio):
        corrida_id["run_id"] = ev.run_id
        # Referencia FUERTE a la Corrida: _VIVAS es debil y cerrar() la da de
        # baja, asi que despues del cierre no habria forma de leer su
        # presupuesto — que es justo lo que este script tiene que enseñar.
        corrida_id["c"], _ = motor._buscar_corrida(ev.run_id)
        _log(f"WorkflowInicio run_id={ev.run_id} interactivo={ev.interactivo}")
    elif isinstance(ev, ux.AgenteInicio):
        ids[ev.indice] = ev.agente_id
        _log(f"AgenteInicio  idx={ev.indice} id={ev.agente_id}")
    elif isinstance(ev, ux.TokenTexto):
        chars[ev.agente_id] = chars.get(ev.agente_id, 0) + len(ev.texto)
    elif isinstance(ev, ux.MensajeAlAgente):
        _log(f"MensajeAlAgente destino=…{ev.destino[-14:]} "
             f"aceptado={ev.aceptado} estado={ev.estado} "
             f"pendientes={ev.pendientes}")
    elif isinstance(ev, ux.AgenteFin):
        fines[ev.indice] = ev
        _log(f"AgenteFin     idx={ev.indice} ok={ev.ok} "
             f"cancelado={ev.cancelado} repreguntas={ev.repreguntas} "
             f"intentos={ev.intentos} tokens={ev.tokens} "
             f"descartado_chars={ev.descartado_chars}")
    elif isinstance(ev, ux.WorkflowFin):
        wf_fin.append(ev)
        _log(f"WorkflowFin   ok={ev.ok} agentes={ev.agentes} "
             f"fallidos={ev.fallidos} cancelados={ev.cancelados} "
             f"tokens={ev.tokens} tokens_estimados={ev.tokens_estimados} "
             f"resumen={ev.resumen!r}")


def _tokenize(texto: str) -> int:
    """Los tokens REALES de un texto, segun el server que lo genero."""
    try:
        req = urllib.request.Request(
            URL + "/tokenize",
            data=json.dumps({"content": texto}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return len(json.load(r).get("tokens") or [])
    except Exception as exc:
        _log(f"(no se pudo tokenizar: {exc})")
        return -1


def _esperar(idx: int, tope: float = 240.0) -> str:
    fin = time.perf_counter() + tope
    while time.perf_counter() < fin:
        if idx in ids:
            return ids[idx]
        time.sleep(0.02)
    raise SystemExit(f"el paso {idx} nunca arranco")


def main() -> int:
    ux.suscribir(_escucha)
    envelope: dict = {}
    envs_control: dict = {}
    listo = threading.Event()

    def _correr():
        try:
            envelope.update(adaptador.ejecutar(
                PASOS, modo="secuencial", nombre="e2e-defectos",
                presupuesto=60_000, interactivo=True))
        finally:
            listo.set()

    hilo = threading.Thread(target=_correr, name="workflow", daemon=True)
    hilo.start()

    # (1) CORTAR el paso 2 a mitad de generacion
    aid2 = _esperar(2)
    time.sleep(3.0)
    _log(f"chars del 2 antes de cortar: {chars.get(aid2, 0)}")
    t_corte = time.perf_counter()
    envs_control["cancelar_agente(2)"] = adaptador.cancelar_agente(
        aid2, "el usuario aprieta interrumpir")
    _log(f"cancelar_agente -> {envs_control['cancelar_agente(2)']}")
    while 2 not in fines and time.perf_counter() - t_corte < 30:
        time.sleep(0.01)
    corte_s = time.perf_counter() - t_corte
    _log(f"*** CORTE MEDIDO: {corte_s:.3f}s ***")

    # (3) hablarle al 2, YA CANCELADO -> defecto #2
    envs_control["decirle(2 cancelado)"] = adaptador.decirle(
        aid2, "esto no lo tiene que leer nadie")
    _log(f"decirle al cancelado -> {envs_control['decirle(2 cancelado)']}")

    # (2) HABLARLE al paso 3 a mitad de generacion
    aid3 = _esperar(3)
    time.sleep(3.0)
    _log(f"chars del 3 antes de hablarle: {chars.get(aid3, 0)}")
    envs_control["decirle(3 vivo)"] = adaptador.decirle(
        aid3, "OLVIDA todo lo anterior. Responde EXACTAMENTE con una sola "
              f"palabra en mayusculas: {PALABRA}. Nada mas.")
    _log(f"decirle al vivo -> {envs_control['decirle(3 vivo)']}")

    # (4) PANICO global y cancelar el paso 1, que YA ENTREGO -> defecto #3
    aid1 = ids.get(1, "")
    envs_control["cancelar_agente(1) SIN panico"] = adaptador.cancelar_agente(aid1)
    panico = adaptador.cancelar_corrida("")
    envs_control["cancelar_corrida vacio (panico)"] = panico
    tras = adaptador.cancelar_agente(aid1)
    envs_control["cancelar_agente(1) TRAS panico"] = tras
    _log(f"panico -> {panico}")
    _log(f"cancelar el 1 (ya entregado) TRAS el panico -> {tras}")

    listo.wait(900)
    fin = wf_fin[-1] if wf_fin else None
    c = corrida_id.get("c")

    # ── lo que hay que ver ────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("ENVELOPE de ejecutar() (lo que ve cli.py y la tool):")
    for k in sorted(envelope):
        v = envelope[k]
        if k == "texto":
            v = f"<{len(str(v))} chars>"
        print(f"    {k:12} = {v!r}")
    print("\nWorkflowFin (lo que fue al bus):")
    print(f"    ok={getattr(fin, 'ok', None)} cancelados="
          f"{getattr(fin, 'cancelados', None)} agentes="
          f"{getattr(fin, 'agentes', None)} fallidos="
          f"{getattr(fin, 'fallidos', None)}")
    print(f"    tokens={getattr(fin, 'tokens', None)} "
          f"tokens_estimados={getattr(fin, 'tokens_estimados', None)}")
    print(f"    resumen={getattr(fin, 'resumen', None)!r}")

    print("\nENVELOPES de control (#4: pendientes / agentes / corridas):")
    for nombre, env in envs_control.items():
        print(f"    {nombre:32} ok={str(env['ok']):5} "
              f"estado={env['estado']:20} pend={env['pendientes']} "
              f"agentes={env['agentes']} corridas={env['corridas']}")

    # journal
    lineas = []
    if envelope.get("run_id"):
        ruta = motor._dir_base() / envelope["run_id"] / "journal.jsonl"
        crudo = ruta.read_text(encoding="utf-8")
        lineas = [json.loads(l) for l in crudo.splitlines() if l.strip()]
        print(f"\nJOURNAL ({ruta}):")
        for d in lineas:
            t = d.get("tipo")
            if t == "corte":
                print(f"    corte    causa={d['causa']} "
                      f"descartado_chars={d['descartado_chars']} "
                      f"usage={d['usage']} desconocido={d['usage_desconocido']} "
                      f"estimado={d['usage_estimado']} via={d['usage_via']!r}")
            elif t == "mensaje_no_atendido":
                print(f"    mensaje_no_atendido motivo={d['motivo']!r} "
                      f"texto={str(d.get('texto'))[:50]!r}")
            elif t == "mensaje":
                print(f"    mensaje  texto={str(d.get('texto'))[:50]!r}")
            elif t == "agente":
                print(f"    agente   …{d['agente_id'][-14:]} "
                      f"error={str(d.get('error'))[:60]!r} "
                      f"usage={d.get('usage')}")
            else:
                print(f"    {t}")

    # presupuesto
    p = c.presupuesto if c is not None else None
    cortes = [d for d in lineas if d.get("tipo") == "corte"]
    print("\nPRESUPUESTO (#5):")
    if p is not None:
        print(f"    gastado()    = {p.gastado()}")
        print(f"    estimados()  = {p.estimados()}   "
              f"(cobrados, y declarados como estimados)")
        print(f"    sin_prompt() = {p.sin_prompt()}   "
              f"(llamadas cuyo PROMPT no se pudo contar: el agujero que queda,"
              f" visible)")
    print(f"    cortes en el journal = {len(cortes)}")
    print("    contraste con /tokenize del server sobre el texto descartado:")
    for i, d in enumerate(cortes, 1):
        crudo = d.get("descartado") or ""
        completo = len(crudo) >= d.get("descartado_chars", 0)
        n = _tokenize(crudo)
        est = int((d.get("usage") or {}).get("completion_tokens") or 0)
        print(f"      corte {i}: estimado por frames = {est}  |  /tokenize = "
              f"{n}  |  texto completo en el journal: {completo}")
    # EL AGUJERO QUE QUEDA, con su numero: el prompt de un turno cortado no lo
    # manda nadie y no se inventa. Se mide aca para que este declarado.
    prompts = [_tokenize(p) for p in PASOS[1:]]
    print(f"    prompts de los pasos cortados (sin el envoltorio de la "
          f"plantilla): {prompts} tokens -> es lo que sigue SIN contarse, "
          f"{sum(x for x in prompts if x > 0)} de {p.gastado() if p else 0} "
          f"+ eso")


    print("=" * 78)
    checks = [
        ("#1 envelope y WorkflowFin coinciden en ok",
         fin is not None and envelope.get("ok") == fin.ok,
         f"envelope={envelope.get('ok')} WorkflowFin={getattr(fin, 'ok', None)}"),
        ("#1 el error habla de la CANCELACION, no de 'no salio nada'",
         "cancel" in str(envelope.get("error", "")).lower(),
         str(envelope.get("error"))[:90]),
        ("#1 el envelope trae 'cancelados' con el mismo numero",
         fin is not None and envelope.get("cancelados") == fin.cancelados,
         f"{envelope.get('cancelados')} vs {getattr(fin, 'cancelados', None)}"),
        ("#2 decirle a un cancelado NO dice aceptado",
         envs_control["decirle(2 cancelado)"]["estado"] == motor.YA_CANCELADO,
         envs_control["decirle(2 cancelado)"]["estado"]),
        ("#2 y deja 'mensaje_no_atendido' en el journal",
         any(d.get("tipo") == "mensaje_no_atendido" for d in lineas),
         str([d.get("motivo") for d in lineas
              if d.get("tipo") == "mensaje_no_atendido"])),
        ("#3 el que YA ENTREGO sale ya_termino tras el panico",
         tras["estado"] == motor.YA_TERMINO, tras["estado"]),
        ("#4 'pendientes' solo cuenta mensajes",
         panico["pendientes"] == 0 and panico["corridas"] >= 1,
         f"pend={panico['pendientes']} corridas={panico['corridas']}"),
        ("#5 el corte NO se conto como cero",
         p is not None and p.estimados() > 0, f"estimados={p.estimados() if p else '?'}"),
        ("#5 el journal del corte declara la via",
         bool(cortes) and cortes[0].get("usage_via") == "frames",
         str([d.get("usage_via") for d in cortes])),
        ("el corte fue rapido (<1 s)", corte_s < 1.0, f"{corte_s:.3f}s"),
    ]
    ok_total = True
    for nombre, ok, detalle in checks:
        print(f"  {'CHECK OK  ' if ok else 'CHECK FAIL'}  {nombre}: {detalle}")
        ok_total = ok_total and bool(ok)
    ux.desuscribir(_escucha)
    return 0 if ok_total else 1


if __name__ == "__main__":
    sys.exit(main())
