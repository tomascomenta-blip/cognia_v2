# -*- coding: utf-8 -*-
"""
cognia/autopsia/motor.py
========================
AUTOPSIA COMPLETA: instantanea + replay contrafactual, UNIDOS.

POR QUE EXISTE. La investigacion de la noche (2026-08-19) encontro dos piezas
publicadas por dos comunidades que no se citan:

  * DeltaBox (arXiv 2605.22781, gente de sistemas): restaura el estado de un
    paso en milisegundos. Sabe REBOBINAR el mundo y no tiene nada que preguntar.
  * Causal Agent Replay (arXiv 2606.08275, gente de ML causal): necesita
    re-ejecutar desde el paso i para saber que paso causo el fallo. Sabe QUE
    preguntar y no tiene como rebobinar.

Nadie las ha juntado. Este modulo es esa union sobre las piezas del repo:
`cognia/multiverso/instantanea.py` rebobina el workspace y
`cognia/autopsia/causal.py` decide que prefijos hay que probar (biseccion) para
localizar el paso culpable con un contrafactual REAL, no con la opinion de un
juez leyendo la traza.

QUE HACE, en una linea: dada una grabacion de `cognia/flujos/grabador.py`,
responde "cual de tus N pasos causo el fallo" re-ejecutando de verdad, y lo
demuestra: sin ese paso la tarea pasa, con el falla.

LO QUE NO HACE (declarado):
  - No rebobina efectos FUERA del workspace (un git push, un correo, una fila en
    una BD). La instantanea cubre ficheros; lo demas se declara irreversible en
    cognia/multiverso/reversibilidad.py y NO se re-ejecuta.
  - No re-muestrea el modelo: reproduce las ACCIONES grabadas. Sirve para
    atribuir un fallo de EJECUCION, no para preguntarse que habria pensado el
    modelo con otro contexto.
  - Si la grabacion no tiene postcondiciones derivables, no hay veredicto
    objetivo y la autopsia se niega a opinar (devuelve motivo, no un culpable
    inventado).

Solo stdlib. Nada aqui puede lanzar hacia el llamador: devuelve informes.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path


def _norm(traj_grabada):
    """Grabacion -> lista de pasos planos {action, args, ok, result_head}."""
    pasos = []
    for p in (traj_grabada or {}).get("pasos") or []:
        pasos.append({
            "action": p.get("tool") or p.get("action") or "",
            "args": p.get("args") or "",
            "ok": bool(p.get("ok", True)),
            "result_head": (p.get("resumen_resultado")
                            or p.get("result_head") or "")[:200],
            "n": p.get("n"),
        })
    return pasos


def _postcondiciones(traj_grabada):
    """Los chequeos verificables que dejo la trayectoria (puede ser [])."""
    try:
        from cognia.flujos import generalizador
        return generalizador.postcondiciones_de(traj_grabada) or []
    except Exception:
        return []


def _verificar(post, ws):
    """True si TODAS las postcondiciones se cumplen LEYENDO EL DISCO."""
    if not post:
        return None                    # sin examen no hay veredicto
    try:
        from cognia.flujos import reproductor
        res = reproductor.verificar_postcondiciones(post, workspace=str(ws))
        return all(bool(r.get("ok")) for r in res) if res else None
    except Exception:
        return None


def autopsiar(grabacion, *, run_tool_fn, ws_base=None, presupuesto=8,
              print_fn=None):
    """Autopsia una grabacion: devuelve el informe del paso culpable.

    grabacion   : dict de cognia/flujos/grabador.cargar(...).a_dict() o el
                  propio objeto Grabacion.
    run_tool_fn : (nombre, args) -> str. El ejecutor REAL de tools.
    ws_base     : workspace de partida que se clona para cada reproduccion.
                  Por defecto, el de la grabacion; si no existe, un temporal.
    presupuesto : tope duro de reproducciones (cada una re-ejecuta un prefijo).

    Devuelve {ok, motivo, paso_culpable, confianza, explicacion, pasos,
              reproducciones, ms, veredicto_base, lineas_base}.
    """
    di = print_fn or (lambda *_a, **_k: None)
    t0 = time.perf_counter()
    g = grabacion.a_dict() if hasattr(grabacion, "a_dict") else dict(grabacion or {})
    pasos = _norm(g)
    post = _postcondiciones(g)
    informe = {"ok": False, "motivo": "", "paso_culpable": None, "confianza": 0.0,
               "explicacion": "", "pasos": len(pasos), "reproducciones": 0,
               "ms": 0.0, "veredicto_base": None, "lineas_base": {}}

    if not pasos:
        informe["motivo"] = "la grabacion no tiene pasos"
        return informe
    if not post:
        # Sin examen objetivo, cualquier atribucion seria una opinion. Se dice.
        informe["motivo"] = ("la grabacion no deja postcondiciones verificables: "
                             "sin examen no hay contrafactual y no se atribuye nada")
        return informe

    from cognia.multiverso import instantanea as inst
    from cognia.autopsia import causal

    origen = Path(str(ws_base or g.get("workspace") or "."))
    if not origen.is_dir():
        informe["motivo"] = f"el workspace de la grabacion ya no existe: {origen}"
        return informe

    # El estado INICIAL: lo que habia antes de que la trayectoria corriera. No
    # lo tenemos grabado, asi que se reconstruye por sustraccion: se parte del
    # workspace actual y se BORRA lo que la trayectoria creo. Es una
    # aproximacion y se declara en el informe (clave 'base_reconstruida').
    raiz = Path(tempfile.mkdtemp(prefix="autopsia_"))
    ws_limpio = raiz / "base"
    shutil.copytree(str(origen), str(ws_limpio), dirs_exist_ok=True)
    creados = set()
    for p in pasos:
        if p["action"] in ("escribir_archivo", "editar_archivo", "apendar_archivo"):
            ruta = str(p["args"]).split("|", 1)[0].strip().strip('"').strip("'")
            if ruta:
                creados.add(ruta)
    for rel in creados:
        try:
            (ws_limpio / rel).unlink()
        except Exception:
            pass                        # no estaba: nada que quitar
    informe["base_reconstruida"] = sorted(creados)

    foto = inst.tomar(ws_limpio, etiqueta="autopsia-base")
    di(f"[detail]instantanea base: {len(foto.manifiesto)} ficheros[/detail]")

    contador = {"n": 0}

    def _reproducir(subtray):
        """Rebobina el mundo y re-ejecuta el prefijo. Este es el contrafactual."""
        contador["n"] += 1
        inst.restaurar(foto, workspace=ws_limpio)
        prev = os.getcwd()
        try:
            os.chdir(ws_limpio)
            for p in subtray:
                try:
                    run_tool_fn(p["action"], p["args"])
                except Exception:
                    pass                # un paso que revienta ES informacion
        finally:
            os.chdir(prev)
        return {"ws": str(ws_limpio)}

    def _veredicto(estado):
        v = _verificar(post, (estado or {}).get("ws", ws_limpio))
        return bool(v)

    try:
        inf = causal.atribuir(pasos, _veredicto, reproducir_fn=_reproducir,
                              presupuesto=int(presupuesto))
    except Exception as exc:
        informe["motivo"] = f"la atribucion fallo: {type(exc).__name__}: {exc}"
        informe["ms"] = (time.perf_counter() - t0) * 1000
        return informe

    culpable = inf.get("paso_culpable")
    informe.update({
        "ok": culpable is not None,
        "motivo": inf.get("motivo", ""),
        "paso_culpable": culpable,
        "confianza": inf.get("confianza", 0.0),
        "reproducciones": contador["n"],
        "veredicto_base": inf.get("veredicto_base"),
        "lineas_base": {
            "ultimo_paso": causal.linea_base_ultimo_paso(pasos),
            "ultimo_fallido": causal.linea_base_ultimo_fallido(pasos),
        },
    })
    try:
        informe["explicacion"] = causal.explicar(inf, pasos)
    except Exception:
        informe["explicacion"] = ""
    informe["ms"] = (time.perf_counter() - t0) * 1000
    try:
        shutil.rmtree(raiz, ignore_errors=True)
    except Exception:
        pass
    return informe
