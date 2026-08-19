# -*- coding: utf-8 -*-
"""Guion de MEDICION del catastro: corre medir_distribucion sobre trazas REALES.

QUE RESUELVE: el numero de la fraccion por cubo no puede declararse, tiene que
salir de trazas de esta maquina. Este guion las busca donde de verdad estan,
las clasifica y escupe la tabla que va al informe y al docstring.

POR QUE EXISTE: para que cualquiera pueda RE-CORRERLO y comprobar que los
porcentajes del docstring de reversibilidad.py no me los invente.

USO:  ./venv312/Scripts/python.exe -m cognia.multiverso.medir
"""

import json
import os
import sys
from pathlib import Path

from cognia.multiverso.reversibilidad import cargar_trazas, medir_distribucion

HOME = Path.home()
REPO = Path(__file__).resolve().parents[2]

# Las tres fuentes REALES que existen en esta maquina (2026-08-19).
FUENTES = {
    "A_bitacora_con_args": sorted(
        (HOME / ".cognia" / "data" / "tareas").glob("*/bitacora.jsonl")),
    "B_tool_usage_agregado": [REPO / "cognia" / "agent" / "generated_tools"
                              / "_tool_usage.json"],
    "C_checkpoints_mutaciones": sorted(
        (HOME / ".cognia" / "checkpoints").glob("*/indice.jsonl")),
}


def _tabla(nombre, res):
    print(f"\n=== {nombre}  n={res['n']}")
    for cubo in res["cubos"]:
        print(f"  {cubo:13} {res['conteo'][cubo]:8}  {res['porcentaje'][cubo]:6.2f}%")
    print(f"  especulable(puro)={res['fraccion_especulable']}%  "
          f"irreversible={res['fraccion_irreversible']}%  "
          f"acciones_shell={res['acciones_de_shell']} "
          f"(sin args: {res['shell_sin_args']})")


def main(argv=None):
    total = []
    resumen = {}
    for nombre, rutas in FUENTES.items():
        trazas = []
        for r in rutas:
            trazas.extend(cargar_trazas(r))
        if not trazas:
            print(f"\n=== {nombre}: SIN TRAZAS ({len(rutas)} ficheros mirados)")
            continue
        res = medir_distribucion(trazas)
        resumen[nombre] = {"n": res["n"], "porcentaje": res["porcentaje"],
                           "conteo": res["conteo"]}
        _tabla(nombre, res)
        if nombre.startswith("A") or nombre.startswith("C"):
            total.extend(trazas)
        # detalle por tool de las que reparten en mas de un cubo
        for tool, d in sorted(res["por_tool"].items()):
            usados = [c for c in d if d[c]]
            if len(usados) > 1:
                print(f"    * '{tool}' REPARTE: "
                      + ", ".join(f"{c}={d[c]}" for c in usados))
    if total:
        res = medir_distribucion(total)
        _tabla("A+C acciones individuales (sin agregados)", res)
        resumen["A+C"] = {"n": res["n"], "porcentaje": res["porcentaje"]}
    salida = REPO / "cognia" / "multiverso" / "medicion_reversibilidad.json"
    salida.write_text(json.dumps(resumen, indent=1, ensure_ascii=False),
                      encoding="utf-8")
    print(f"\n[guardado] {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
