# -*- coding: utf-8 -*-
"""¿Hay casos DUPLICADOS entre visibles y ocultos?

El split es disjunto POR ÍNDICE, pero si un caso visible tiene la misma entrada
que uno oculto, enseñarle al brazo REP la salida esperada del visible le está
regalando la del oculto. Sería una fuga por CONTENIDO, invisible para un split
por índice — y haría que un REP > BoN fuera un artefacto.

Se mide sobre las tareas `hard` reales, con el MISMO sorteo que usa la corrida.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import carga_lcb, tests_lcb

tareas = [t for t in carga_lcb(ficheros=("lcb_test5.jsonl", "lcb_test6.jsonl"))
          if t["dificultad"] == "hard"]

con_fuga = []
tot_vis = tot_dup = 0
for t in tareas:
    tid = str(t["task_id"])
    vis, oc = tests_lcb(t, random.Random(f"20260730:{tid}"))
    if not vis or not oc:
        continue
    ent_oc = {(c.get("input") or "") for c in oc}
    dup = [c for c in vis if (c.get("input") or "") in ent_oc]
    tot_vis += len(vis)
    tot_dup += len(dup)
    if dup:
        con_fuga.append((tid, len(dup), len(vis), len(oc)))

print(f"tareas hard con split valido : {sum(1 for t in tareas)}")
print(f"casos visibles totales       : {tot_vis}")
print(f"visibles DUPLICADOS en ocultos: {tot_dup} ({tot_dup/max(1,tot_vis):.2%})")
print(f"tareas con al menos una fuga : {len(con_fuga)}/{len(tareas)} "
      f"({len(con_fuga)/max(1,len(tareas)):.1%})")
for tid, d, v, o in con_fuga[:15]:
    print(f"   {tid}: {d}/{v} visibles duplicados entre {o} ocultos")
if not con_fuga:
    print("\nSIN FUGA POR CONTENIDO: el split es disjunto tambien en entradas.")
