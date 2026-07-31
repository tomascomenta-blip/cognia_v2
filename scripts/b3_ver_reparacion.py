# -*- coding: utf-8 -*-
"""Inspección a mano de una corrida de b3_reparacion.py.

Existe porque la lección más cara de esta semana fue *reproducir un caso a mano
antes de contarlo como fallo del modelo*. Esto imprime los registros crudos y,
con --prompt, el prompt de reparación EXACTO que vio el modelo.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

ap = argparse.ArgumentParser()
ap.add_argument("fichero", nargs="?", default="reparacion_humo.json")
ap.add_argument("--prompt", action="store_true",
                help="imprime el prompt de reparación de la primera cadena")
args = ap.parse_args()

p = Path(args.fichero)
if not p.is_absolute():
    p = RAIZ / "b3_codigo" / args.fichero
d = json.loads(p.read_text(encoding="utf-8"))

for m in d["muestras"]:
    if m.get("cierre"):
        print("   ---- cierre de tarea ----")
        continue
    ce = m.get("contraejemplo") or {}
    print(f'{m["tarea"]:>7} {m["brazo"]:<5} idx={m["idx"]} '
          f'vis={m["vis_ok"]}/{m["vis_n"]} oc={m["oc_ok"]}/{m["oc_n"]} '
          f'pasa_vis={int(m["pasa_vis"])} pasa_oc={int(m["pasa_oc"])} '
          f'inst={m["instrumento"]!r} pchars={m["prompt_chars"]} '
          f'seg={m["segundos"]} ce={"si" if ce else "--"}'
          f'{" EXC" if ce.get("excepcion") else ""}')

if args.prompt:
    from b3_codigo import carga_lcb
    from b3_reparacion import prompt_reparar
    raiz = next((m for m in d["muestras"]
                 if m["brazo"] == "raiz" and (m.get("contraejemplo") or {})),
                None)
    if not raiz:
        print("\n(ninguna raíz con contraejemplo en esta corrida)")
        sys.exit(0)
    tareas = {str(t["task_id"]): t for t in carga_lcb(
        ficheros=tuple(x.strip() for x in d["ficheros"].split(",")))}
    t = tareas[raiz["tarea"]]
    txt = prompt_reparar(t, raiz.get("_code", ""), raiz["contraejemplo"])
    print("\n" + "=" * 70)
    print(f"PROMPT DE REPARACIÓN REAL (tarea {raiz['tarea']}, "
          f"{len(txt)} chars)")
    print("=" * 70)
    # el enunciado ya se ha auditado; lo que importa es la cola
    print("[...enunciado recortado...]\n" + txt[-2500:])
