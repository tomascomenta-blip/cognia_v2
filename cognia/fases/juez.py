# -*- coding: utf-8 -*-
"""
cognia/fases/juez.py — el juez que compara la version nueva con la mejor anterior.

El constructor no decide "mi codigo esta terminado". El juez recibe las
metricas de la version aceptada anterior y las de la nueva, la lista de
ficheros cambiados y la lista NO TOCAR, y decide:

  aceptar      hay mejora neta y ninguna regresion
  rechazar     alguna regresion (menos requisitos OK, menos tests, mas
               errores de consola, tracebacks nuevos, P0 nuevos), o toco
               algo marcado estable sin estar en una fase que lo permita,
               o cambio codigo sin demostrar mejora alguna
  sin_cambios  la iteracion no toco ningun fichero (no hay nada que juzgar)

Es determinista y multidimensional a proposito: un 95/100 con un bug
critico no esta listo, asi que las regresiones se miran una a una antes
de sumar nada.
"""
from __future__ import annotations

import fnmatch

# Fases en las que tocar un fichero "estable" NO es motivo de rechazo por si
# solo (la regresion final y el arreglo de red team pueden tener que entrar).
FASES_PERMITEN_ESTABLES = ("robustez", "redteam", "regresion", "release")


def _viola_no_tocar(cambios: list, estables: list) -> list:
    out = []
    for e in estables or []:
        que = (e.get("que") if isinstance(e, dict) else str(e)) or ""
        q = que.strip().replace("\\", "/").lower()
        if not q:
            continue
        for f in cambios:
            fl = f.replace("\\", "/").lower()
            if fl == q or fl.startswith(q.rstrip("/") + "/") or fnmatch.fnmatch(fl, q) or (q in fl and "/" in q or fl.endswith("/" + q)):
                out.append(f)
    return sorted(set(out))


def juzgar(prev: dict | None, nuevo: dict, cambios: list, estables: list = None,
           fase: str = "", issues_prev: dict = None, issues_nuevo: dict = None,
           cerrados_en_iteracion: int = 0) -> dict:
    """{decision, motivos[], deltas{}}."""
    motivos, deltas = [], {}
    if not cambios:
        return {"decision": "sin_cambios", "motivos": ["la iteracion no cambio ningun fichero"], "deltas": {}}
    viol = _viola_no_tocar(cambios, estables or [])
    if viol and fase not in FASES_PERMITEN_ESTABLES:
        return {"decision": "rechazar",
                "motivos": ["toco ficheros marcados NO TOCAR sin ser fase de regresion: " + ", ".join(viol[:5])],
                "deltas": {}}
    if prev is None:
        # primera version: se acepta como base si hay algo que juzgar despues
        motivos.append("primera version (base para comparar)")
        if nuevo.get("tracebacks"):
            motivos.append("ojo: %d traceback(s)" % nuevo["tracebacks"])
        return {"decision": "aceptar", "motivos": motivos, "deltas": {}}
    regresiones = []
    mejoras = []

    def _d(clave, mejor_si_sube=True, solo_si=lambda a, b: True):
        a, b = prev.get(clave), nuevo.get(clave)
        if a is None or b is None or not solo_si(a, b):
            return
        deltas[clave] = b - a
        if b == a:
            return
        subio = b > a
        if subio == mejor_si_sube:
            mejoras.append("%s %s -> %s" % (clave, a, b))
        else:
            regresiones.append("%s %s -> %s" % (clave, a, b))

    _d("req_ok", True)
    _d("tests_ok", True, solo_si=lambda a, b: prev.get("tests_total", 0) > 0 and nuevo.get("tests_total", 0) > 0)
    _d("consola_errores", False)
    _d("tracebacks", False)
    _d("req_fallan", False)
    # Regresion POR REQUISITO: si F4 pasaba y ahora falla, es regresion aunque
    # otro requisito haya pasado a OK y el conteo quede igual (cazado en la
    # obra Snake: F5 OK y F4 FALLA se compensaban y el juez aceptaba).
    perdidos = sorted(set(prev.get("ok_ids") or []) - set(nuevo.get("ok_ids") or []))
    if perdidos and "ok_ids" in nuevo:
        regresiones.append("requisitos que pasaban y ahora fallan: " + ", ".join(perdidos[:6]))
    if prev.get("revision_ok") is True and nuevo.get("revision_ok") is False:
        regresiones.append("la revision profunda pasaba y ahora falla")
    elif prev.get("revision_ok") is False and nuevo.get("revision_ok") is True:
        mejoras.append("la revision profunda ahora pasa")
    ip, inu = issues_prev or {}, issues_nuevo or {}
    if inu.get("P0", 0) > ip.get("P0", 0):
        regresiones.append("issues P0 abiertos %d -> %d" % (ip.get("P0", 0), inu.get("P0", 0)))
    if cerrados_en_iteracion:
        mejoras.append("%d issue(s) cerrados" % cerrados_en_iteracion)
    # tests nuevos que no existian (mas cobertura) cuentan como mejora
    if nuevo.get("tests_total", 0) > prev.get("tests_total", 0) and nuevo.get("tests_ok", 0) == nuevo.get("tests_total", 0):
        mejoras.append("tests %d -> %d, todos en verde" % (prev.get("tests_total", 0), nuevo["tests_total"]))
    if regresiones:
        return {"decision": "rechazar", "motivos": ["REGRESION: " + r for r in regresiones], "deltas": deltas}
    if mejoras:
        return {"decision": "aceptar", "motivos": mejoras, "deltas": deltas}
    # sin regresion ni mejora medible: en fases de pulido/visual/optimizacion se
    # exige evidencia (un requisito manual marcado, un issue cerrado); si no, se
    # rechaza: "nunca se acepta un cambio que no demuestre mejora neta"
    if fase in ("visual", "pulido", "optimizacion") and nuevo.get("visual_cambio"):
        return {"decision": "aceptar", "motivos": ["cambio visual %.1f%% sin regresion (fase %s)" % (nuevo["visual_cambio"] * 100, fase)],
                "deltas": deltas}
    return {"decision": "rechazar",
            "motivos": ["sin mejora neta demostrada: ningun requisito, test, issue o error cambio (revertido)"],
            "deltas": deltas}


def informe(prev: dict | None, nuevo: dict, veredicto: dict) -> str:
    lineas = ["JUEZ: %s" % veredicto["decision"].upper()]
    for k in ("req_ok", "tests_ok", "consola_errores", "tracebacks"):
        a = (prev or {}).get(k, "-")
        b = nuevo.get(k, "-")
        lineas.append("  %-16s %s -> %s" % (k, a, b))
    for mo in veredicto.get("motivos", []):
        lineas.append("  · " + mo)
    return "\n".join(lineas)


def puntuacion(m: dict, issues: dict) -> dict:
    """Puntuacion multidimensional 0-100 (para el informe final, no para decidir)."""
    tot = max(1, m.get("req_total", 0))
    func = int(100 * m.get("req_ok", 0) / tot)
    tests = int(100 * m.get("tests_ok", 0) / m["tests_total"]) if m.get("tests_total") else None
    calidad = 100
    calidad -= min(60, 20 * m.get("consola_errores", 0))
    calidad -= min(60, 30 * m.get("tracebacks", 0))
    calidad = max(0, calidad)
    robustez = max(0, 100 - 40 * issues.get("P0", 0) - 25 * issues.get("P1", 0) - 10 * issues.get("P2", 0)
                   - 4 * issues.get("P3", 0) - 1 * issues.get("P4", 0))
    return {"funcionalidad": func, "tests": tests, "calidad": calidad, "robustez": robustez}
