# -*- coding: utf-8 -*-
"""tareas.py -- carga y VALIDA las 25 tareas largas del banco.

Una tarea mal formada es peor que ninguna: puntua cero a un producto sano. Por eso
`validar()` es estricto y `cargar()` grita en vez de tragar.
"""
from __future__ import annotations

import json
from pathlib import Path

from banco_largo.motor import TIPOS_VALIDOS

DIR = Path(__file__).resolve().parent / "tareas"

CAPAS = ("completitud", "funcionalidad", "robustez", "integridad", "regresion")

OBLIGATORIOS = ("id", "familia", "dificultad", "presupuesto_s", "pasos", "prompt",
                "criterios_exito", "criterios_fallo", "artefactos", "pruebas")


def validar(t, ruta=""):
    fallos = []
    for k in OBLIGATORIOS:
        if k not in t:
            fallos.append("falta la clave %s" % k)
    if fallos:
        return fallos
    if not isinstance(t["prompt"], str) or len(t["prompt"]) < 300:
        fallos.append("el prompt tiene %d chars: una tarea LARGA necesita un encargo largo"
                      % len(t.get("prompt") or ""))
    if not (1 <= int(t["dificultad"]) <= 5):
        fallos.append("dificultad fuera de 1..5")
    if not t.get("artefactos"):
        fallos.append("sin artefactos declarados")
    pruebas = t.get("pruebas") or []
    if len(pruebas) < 5:
        fallos.append("solo %d pruebas: hacen falta >=5" % len(pruebas))
    capas_vistas = set()
    for i, p in enumerate(pruebas):
        if p.get("tipo") not in TIPOS_VALIDOS:
            fallos.append("prueba %d: tipo %r desconocido" % (i, p.get("tipo")))
        capa = p.get("capa", "funcionalidad")
        if capa not in CAPAS:
            fallos.append("prueba %d: capa %r desconocida" % (i, capa))
        capas_vistas.add(capa)
        if not p.get("nombre"):
            fallos.append("prueba %d sin nombre" % i)
    for obligatoria in ("completitud", "funcionalidad"):
        if obligatoria not in capas_vistas:
            fallos.append("ninguna prueba de la capa %s" % obligatoria)
    if not any(p.get("entregable") for p in pruebas):
        fallos.append("ninguna prueba marcada 'entregable' (capa F sin evidencia)")
    return fallos


def cargar(estricto=True):
    tareas = []
    problemas = []
    for p in sorted(DIR.glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            problemas.append("%s: JSON invalido: %s" % (p.name, e))
            continue
        f = validar(t, p.name)
        if f:
            problemas.append("%s: %s" % (p.name, "; ".join(f)))
            continue
        t["_fichero"] = p.name
        tareas.append(t)
    if problemas and estricto:
        raise SystemExit("[banco] tareas invalidas:\n  - " + "\n  - ".join(problemas))
    tareas.sort(key=lambda t: (int(t.get("dificultad", 3)), t["id"]))
    return tareas


if __name__ == "__main__":
    ts = cargar(estricto=False)
    print("%d tareas validas" % len(ts))
    for t in ts:
        print("  d%s %-28s %-14s %4ds  %2d pruebas  %s" % (
            t["dificultad"], t["id"], t["familia"], t["presupuesto_s"],
            len(t["pruebas"]),
            "+".join(sorted({p.get("capa", "funcionalidad") for p in t["pruebas"]}))))
