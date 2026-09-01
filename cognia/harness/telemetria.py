# -*- coding: utf-8 -*-
"""telemetria.py -- el diario OBJETIVO de una tarea: un JSONL por corrida.

POR QUE EXISTE
    El bucle ya SABE casi todo lo que hace falta para diagnosticar una tarea
    larga (pasos, tokens del turno, finish_reason, motivo de cierre, que tool
    corrio y si fallo)... y lo tira: `cognia hacer --json` devuelve cuatro
    campos y el resto muere en stderr como prosa coloreada. Analizar por que
    fallo una tarea de 40 pasos leyendo ese texto es arqueologia.

    Este modulo es el sumidero. Cada evento es una linea JSON con reloj
    monotono. Nadie tiene que parsear color, y los numeros son los del propio
    bucle, no una estimacion de fuera.

DISENO
  - APAGADO por defecto. Sin COGNIA_TELEMETRIA no hay fichero, no hay coste y
    no cambia una sola decision del agente: es un observador, no un actor.
  - NUNCA lanza. Un diario que rompe el turno que venia a explicar es peor que
    no tener diario.
  - Escritura linea a linea con flush: si la tarea muere a mitad (que es
    justo el caso interesante), lo escrito hasta ahi esta en disco.
  - Sin dependencias del resto de Cognia: se puede importar desde cualquier
    punto del bucle sin ciclos.

USO
    export COGNIA_TELEMETRIA=/ruta/tarea.jsonl
    from cognia.harness import telemetria as _tel
    _tel.evento("turno", paso=3, tokens_salida=812, finish="stop")

    resumen = telemetria.resumir("/ruta/tarea.jsonl")   # dict agregado
"""
from __future__ import annotations

import json
import os
import threading
import time

ENV = "COGNIA_TELEMETRIA"

_lock = threading.Lock()
_t0 = time.monotonic()
_ruta_cache = None
_avisado = False


def ruta():
    """La ruta activa, o cadena vacia si la telemetria esta apagada."""
    return os.environ.get(ENV, "") or ""


def activa():
    return bool(ruta())


def reiniciar_reloj():
    global _t0
    _t0 = time.monotonic()


def evento(tipo, **campos):
    """Escribe un evento. Silencioso y a prueba de todo."""
    destino = ruta()
    if not destino:
        return
    global _avisado
    try:
        reg = {"t": round(time.monotonic() - _t0, 3), "tipo": tipo}
        for k, v in campos.items():
            # nada de objetos vivos en el diario: solo json-able y acotado
            if isinstance(v, (int, float, bool)) or v is None:
                reg[k] = v
            elif isinstance(v, str):
                reg[k] = v[:600]
            elif isinstance(v, (list, tuple)):
                reg[k] = [str(x)[:200] for x in list(v)[:40]]
            elif isinstance(v, dict):
                reg[k] = {str(a)[:60]: (b if isinstance(b, (int, float, bool)) else str(b)[:200])
                          for a, b in list(v.items())[:40]}
            else:
                reg[k] = str(v)[:300]
        linea = json.dumps(reg, ensure_ascii=False)
        with _lock:
            with open(destino, "a", encoding="utf-8") as f:
                f.write(linea + "\n")
    except Exception as exc:
        # Un solo aviso por proceso: si el sumidero no se puede escribir, el
        # dueno tiene que enterarse UNA vez, no en cada turno.
        if not _avisado:
            _avisado = True
            try:
                import sys
                print("[telemetria] no puedo escribir en %s (%s); sigo sin diario"
                      % (destino, exc), file=sys.stderr)
            except Exception:
                pass


# -- lectura y agregado ------------------------------------------------------

def leer(ruta_jsonl):
    out = []
    try:
        with open(ruta_jsonl, "r", encoding="utf-8", errors="replace") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    out.append(json.loads(linea))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def resumir(ruta_jsonl):
    """Agrega el diario a los numeros que se comparan entre corridas."""
    evs = leer(ruta_jsonl)
    turnos = [e for e in evs if e["tipo"] == "turno"]
    tools = [e for e in evs if e["tipo"] == "tool"]
    cierres = [e for e in evs if e["tipo"] == "cierre"]
    inicios = [e for e in evs if e["tipo"] == "inicio"]

    por_nombre = {}
    for e in tools:
        n = e.get("nombre", "?")
        por_nombre[n] = por_nombre.get(n, 0) + 1
    fallidas = [e for e in tools if e.get("ok") is False]

    tok_in = sum(int(e.get("tokens_entrada") or 0) for e in turnos)
    tok_out = sum(int(e.get("tokens_salida") or 0) for e in turnos)
    cortados = [e for e in turnos if e.get("finish") == "length"]

    dur = max([e.get("t", 0) for e in evs] or [0])
    res = {
        "eventos": len(evs),
        "turnos": len(turnos),
        "tokens_entrada": tok_in,
        "tokens_salida": tok_out,
        "tokens_totales": tok_in + tok_out,
        "tok_s_salida": round(tok_out / dur, 2) if dur else 0.0,
        "tool_calls": len(tools),
        "tool_calls_por_nombre": por_nombre,
        "tool_calls_fallidas": len(fallidas),
        "tools_que_fallaron": sorted({e.get("nombre", "?") for e in fallidas})[:12],
        "turnos_cortados_por_tope": len(cortados),
        "duracion_s": round(dur, 1),
        "prompt_tokens_max": max([int(e.get("tokens_entrada") or 0) for e in turnos] or [0]),
        "eventos_por_tipo": {},
    }
    for e in evs:
        res["eventos_por_tipo"][e["tipo"]] = res["eventos_por_tipo"].get(e["tipo"], 0) + 1
    if inicios:
        res["presupuesto_pasos"] = inicios[0].get("presupuesto")
        res["techo_pasos"] = inicios[0].get("techo")
        res["tarea_chars"] = inicios[0].get("tarea_chars")
    if cierres:
        c = cierres[-1]
        res["cierre_motivo"] = c.get("motivo")
        res["cierre_razon"] = c.get("razon")
        res["cierre_ok"] = c.get("ok")
        res["cierre_pasos"] = c.get("pasos")
        res["cierre_finish"] = c.get("finish")
    incidencias = [e for e in evs if e["tipo"] in ("compactacion", "corte", "reintento",
                                                   "rescate", "degradado")]
    res["incidencias"] = [{"tipo": e["tipo"], "t": e.get("t"),
                           "detalle": e.get("motivo") or e.get("detalle") or ""}
                          for e in incidencias][:40]
    res["n_compactaciones"] = sum(1 for e in evs if e["tipo"] == "compactacion")
    res["n_cortes"] = sum(1 for e in evs if e["tipo"] == "corte")
    return res
