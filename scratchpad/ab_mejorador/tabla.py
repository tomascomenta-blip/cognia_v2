# -*- coding: utf-8 -*-
"""Vuelca la tabla cruda de las 12 tareas (los dos brazos, las dos replicas)."""
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(AQUI, "crudo.json"), encoding="utf-8") as fh:
    filas = json.load(fh)

orden = []
for f in filas:
    if f["tarea"] not in orden:
        orden.append(f["tarea"])

for tid in orden:
    grupo = [f for f in filas if f["tarea"] == tid]
    print("=" * 78)
    print("IN  : " + grupo[0]["original"])
    for brazo in ("v1", "v2"):
        for f in sorted([g for g in grupo if g["brazo"] == brazo],
                        key=lambda x: x["replica"]):
            marca = "OK " if f["ok"] else "RECH"
            print("  {} r{} [{}] {}ms {}c  motivo={}".format(
                brazo, f["replica"], marca, f["ms"], f["chars"], f["motivo"]))
            muestra = f["bruto"].strip().replace("\n", " ")
            print("      " + muestra)
