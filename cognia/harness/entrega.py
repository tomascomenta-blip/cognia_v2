# -*- coding: utf-8 -*-
"""ENTREGA: el turno nunca cierra sin decir QUE quedo en disco (2026-08-31).

POR QUE EXISTE
--------------
Traza real del dueno, tres tareas seguidas sobre el mismo juego:

    ✗ 819.0s · 31714 tokens · 15 pasos · sin progreso verificado: meseta_de_coste
      (cerrada sin progreso verificado: meseta_de_coste)
      Salida de la ejecución: extraido 19630 chars SINTAXIS_OK

    ✗ 422.4s · 10816 tokens · 10 pasos · sin progreso verificado: sin_arranque
      (cerrada sin progreso verificado: sin_arranque)
      Salida de la ejecución: OK

    ✗ 763.4s · 20405 tokens · 12 pasos · sin progreso verificado: sin_arranque
      Salida de la ejecución: btnContinue, btnCredits, btnCreditsMenu, ...

Media hora de trabajo por tarea y el dueno se queda con el nombre de un motivo
interno del arnes y con el stdout de la ULTIMA tool, que casi nunca es la
entrega. En disco habia un `index.html` de 32 KB cortado a mitad de una clase
-- pero eso no se lo dijo nadie, y en las dos ultimas tareas no se escribio ni
un byte, que tampoco se lo dijo nadie.

El cierre informativo que ya existia (`salida_de_ejecucion`, E8 en agent/loop)
responde "que imprimio lo que corriste". Este responde la otra pregunta, la
que el dueno hace de verdad: **"¿y que me llevo?"**. Es DETERMINISTA y gratis:
mira el disco, no le pregunta al modelo. Un cierre que dice "no escribi nada"
es infinitamente mas util que uno que dice "meseta_de_coste".

CONTRATO
    - Nunca lanza: ante cualquier fallo devuelve un informe vacio y el bloque "".
    - Nunca inventa: cada linea sale de `os.stat` y del validador de estructura.
    - No opina sobre la tarea, solo sobre los ficheros: decir "cumplido" o "no
      cumplido" es del gobernador de progreso, no de aqui.

API
    informe(ficheros, fallidos=None, borrados=None) -> dict
    bloque(inf) -> str          # el texto que se pega a la respuesta del turno
    hace_falta(result_text) -> bool
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

MARCA = "ENTREGA"
MAX_FICHEROS = 12
ENV_ACTIVO = "COGNIA_ENTREGA"

# Ultimo informe de la sesion, para la puerta `/entrega`. En RAM del proceso a
# proposito: es el cierre del turno, no un almacen.
_ULTIMO: dict = {}
_TOTAL = [0]
# Un fallo componiendo la entrega NO puede costar el turno, pero tampoco puede
# ser mudo (regla del repo: "no lo cablearon" y "se rompio" no pueden verse
# igual desde afuera). Se guarda aqui y sale por `/entrega`.
_ULTIMO_ERROR: dict = {}


def activo() -> bool:
    """El bloque de entrega esta encendido (default: si)."""
    return os.environ.get(ENV_ACTIVO, "1").strip().lower() not in (
        "0", "off", "false", "no")


def ultimo() -> dict:
    """El informe del ultimo turno que entrego algo (o {})."""
    return dict(_ULTIMO)


def estado() -> dict:
    """Foto para `/entrega` (json-able, no toca disco)."""
    u = ultimo()
    return {"activo": activo(), "total": _TOTAL[0],
            "ficheros": len(u.get("escritos") or []),
            "rotos": u.get("rotos", 0), "enteros": u.get("enteros", 0),
            "ts": u.get("ts", ""), "ultimo_error": dict(_ULTIMO_ERROR)}


# Cuanto del final del fichero se ensena cuando quedo cortado: lo justo para
# que se vea DONDE se corto (y para que el turno siguiente pueda continuarlo
# con apendar_archivo sin releer 700 lineas).
COLA_CHARS = 160


def _tam(p: Path):
    try:
        return p.stat().st_size
    except OSError:
        return None


def _miles(n) -> str:
    return f"{n:,}".replace(",", ".")


def _cola_de(p: Path) -> tuple:
    """(numero_de_lineas, ultimos COLA_CHARS chars) o (None, "")."""
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return (None, "")
    cola = txt[-COLA_CHARS:].replace("\r", "").replace("\n", " ⏎ ").strip()
    return (len(txt.splitlines()), cola)


_RE_BYTES = re.compile(r"\(\s*\d+\s*bytes\s*\)\s*$")


def _motivo_corto(motivo, p) -> str:
    """El motivo del validador, sin lo que esta linea ya dice en su columna.

    El validador escribe para un log ("existe y compila: C:/x/y.py (912
    bytes)"); aqui la ruta es el nombre de la izquierda y los bytes son la
    columna del medio, asi que repetirlos deja basura ("...:  (912 bytes)").
    """
    t = str(motivo or "").replace(str(p), "").replace(p.name, "")
    t = _RE_BYTES.sub("", t).strip()
    t = t.strip(" :·-").strip()
    if t.lower().startswith("existe y "):
        t = t[len("existe y "):]
    return " ".join(t.split())


def _estado_de(ruta) -> dict:
    """El estado de UN fichero: existe, tamano, y si esta entero."""
    p = Path(str(ruta))
    d = {"ruta": str(p), "nombre": p.name, "existe": False, "bytes": None,
         "lineas": None, "ok": None, "motivo": "", "cola": ""}
    tam = _tam(p)
    if tam is None:
        d["motivo"] = "no existe en disco (se escribio y se borro, o nunca llego a escribirse)"
        return d
    d["existe"], d["bytes"] = True, tam
    if tam == 0:
        d["ok"], d["motivo"] = False, "VACIO (0 bytes)"
        return d
    try:
        from cognia.estado.presupuesto_progreso import _validar_fichero
        ok, motivo = _validar_fichero(str(p))
        d["ok"] = bool(ok)
        d["motivo"] = _motivo_corto(motivo, p)
    except Exception as exc:
        d["ok"], d["motivo"] = None, f"no evaluable ({type(exc).__name__})"
    if d["ok"] is False:
        d["lineas"], d["cola"] = _cola_de(p)
    return d


def informe(ficheros, fallidos=None, borrados=None) -> dict:
    """Que quedo en disco tras el turno. NUNCA lanza.

    `ficheros`  rutas que el turno escribio con exito (RegistroMutaciones.
                ficheros_escritos()).
    `fallidos`  rutas cuya escritura fallo (rutas_fallidas()).
    `borrados`  rutas que el turno borro, si el llamador las tiene.
    """
    inf = {"escritos": [], "fallidos": [], "borrados": [],
           "rotos": 0, "enteros": 0, "nada": True}
    try:
        vistas = set()
        for r in list(ficheros or [])[:MAX_FICHEROS]:
            clave = str(r).lower()
            if clave in vistas:
                continue
            vistas.add(clave)
            e = _estado_de(r)
            inf["escritos"].append(e)
            if e["ok"] is False:
                inf["rotos"] += 1
            elif e["ok"] is True:
                inf["enteros"] += 1
        inf["fallidos"] = [str(r) for r in list(fallidos or [])[:MAX_FICHEROS]]
        inf["borrados"] = [str(r) for r in list(borrados or [])[:MAX_FICHEROS]]
        inf["nada"] = not (inf["escritos"] or inf["fallidos"] or inf["borrados"])
    except Exception:
        return {"escritos": [], "fallidos": [], "borrados": [],
                "rotos": 0, "enteros": 0, "nada": True}
    return inf


def _glifo(ok) -> str:
    return "OK " if ok is True else "ROTO" if ok is False else "?  "


def bloque(inf) -> str:
    """El texto de la entrega, listo para pegar al final de la respuesta.

    Devuelve "" solo si `inf` no es un informe utilizable. Cuando NO se escribio
    nada tambien devuelve texto: "no escribi ningun fichero" es la informacion
    mas importante que puede dar un turno que no entrego.
    """
    if not isinstance(inf, dict):
        return ""
    lineas = [f"{MARCA} — lo que quedo en disco:"]
    if inf.get("nada"):
        lineas.append("  (ningun fichero escrito ni modificado en esta tarea)")
        return "\n".join(lineas)
    for e in inf.get("escritos") or []:
        if not e.get("existe"):
            lineas.append(f"  ?   {e['nombre']} — {e.get('motivo', '')}")
            continue
        tam = f"{_miles(e['bytes'])} bytes"
        lineas.append(f"  {_glifo(e.get('ok'))} {e['nombre']} — {tam}"
                      + (f" · {e['motivo']}" if e.get("motivo") else ""))
        if e.get("ok") is False and e.get("cola"):
            lineas.append(f"       se corta en la linea {e.get('lineas') or '?'}, "
                          f"despues de: …{e['cola']}")
    for r in inf.get("fallidos") or []:
        lineas.append(f"  ROTO {Path(r).name} — la escritura fallo y no se recupero")
    for r in inf.get("borrados") or []:
        lineas.append(f"  --  {Path(r).name} — borrado en esta tarea")
    rotos = inf.get("rotos") or 0
    if rotos:
        lineas.append(f"  → {rotos} fichero(s) quedaron INCOMPLETOS: NO uses la "
                      "entrega tal cual. Para continuar uno, apendar_archivo "
                      "desde donde se corta (arriba se dice la linea).")
    elif inf.get("enteros"):
        lineas.append("  → los ficheros estan completos (estructura), pero eso "
                      "no dice que hagan lo que pediste.")
    return "\n".join(lineas)


def hace_falta(result_text) -> bool:
    """True si la respuesta del turno NO lleva ya un bloque de entrega."""
    return MARCA + " — lo que quedo en disco" not in (result_text or "")


def anexar(result_text, ficheros, fallidos=None, borrados=None) -> str:
    """`result_text` con el bloque de entrega pegado. NUNCA lanza."""
    try:
        if not activo() or not hace_falta(result_text):
            return result_text
        inf = informe(ficheros, fallidos, borrados)
        txt = bloque(inf)
        if not txt:
            return result_text
        inf["ts"] = time.strftime("%H:%M:%S")
        _ULTIMO.clear()
        _ULTIMO.update(inf)
        _TOTAL[0] += 1
        base = (result_text or "").rstrip()
        return (base + "\n\n" + txt) if base else txt
    except Exception as exc:
        # El fallo NO cuesta el turno (esto es un anexo, no la respuesta) pero
        # tampoco es mudo: queda dicho en `/entrega`. Un `except: pass` aqui
        # haria indistinguible "no se cableo" de "se rompio", que es el fallo
        # de diagnostico mas caro de esta casa.
        _ULTIMO_ERROR.clear()
        _ULTIMO_ERROR.update({"motivo": f"{type(exc).__name__}: {exc}",
                              "ts": time.strftime("%H:%M:%S")})
        return result_text
