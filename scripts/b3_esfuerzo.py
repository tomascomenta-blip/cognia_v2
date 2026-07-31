# -*- coding: utf-8 -*-
"""
b3_esfuerzo.py — el eje ESFUERZO, apareado sobre las tareas comunes.

La celda `oficial_high` se corrió aparte (sonda dedicada, contexto 65536 y
presupuesto 60.000 tokens) porque con 30.000 truncaba el 60%. Comparte semilla
y pool con la corrida de dos celdas, así que sus tareas son un PREFIJO de
aquéllas y el apareado es exacto sobre la intersección.
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"


def carga(nombre):
    d = json.loads((SALIDA / nombre).read_text(encoding="utf-8"))
    por = defaultdict(dict)
    for m in d["muestras"]:
        por[m["tarea"]][m["celda"]] = m
    return por


bajo = carga("factorial.json")
alto = carga("factorial_high.json")
comunes = [t for t in alto if t in bajo and "oficial_high" in alto[t]
           and "oficial_low" in bajo[t]]
print(f"tareas en la sonda high : {len(alto)}")
print(f"tareas en la corrida low: {len(bajo)}")
print(f"COMUNES (apareadas)     : {len(comunes)}\n")

ms_h = [alto[t]["oficial_high"] for t in comunes]
tr = sum(1 for m in ms_h if m["instrumento"] == "truncado_por_longitud")
inst = sum(1 for m in ms_h if m["instrumento"])
seg = sum(m["segundos"] for m in ms_h) / max(1, len(ms_h))
print(f"--- SALUD de la celda high (contexto 65536, presupuesto 60.000) ---")
print(f"  truncadas   : {tr}/{len(ms_h)} ({tr/max(1,len(ms_h)):.0%})   "
      f"[con 30.000 sobre 32.768 eran 3/5 = 60%]")
print(f"  instrumento : {inst}/{len(ms_h)}")
print(f"  segundos    : {seg:.0f} por muestra")
print(f"  chars resp. : {sum(m['chars'] for m in ms_h)/max(1,len(ms_h)):.0f}")

print(f"\n--- EJE ESFUERZO, apareado sobre las {len(comunes)} comunes ---")
for juez, k in (("MIO", "mio_pasa"), ("OFICIAL", "oficial_pasa")):
    lo = sum(1 for t in comunes if bajo[t]["oficial_low"][k])
    hi = sum(1 for t in comunes if alto[t]["oficial_high"][k])
    difs = [int(alto[t]["oficial_high"][k]) - int(bajo[t]["oficial_low"][k])
            for t in comunes]
    g = sum(1 for x in difs if x > 0)
    p = sum(1 for x in difs if x < 0)
    d = g + p
    pv = (sum(comb(d, x) for x in range(g, d + 1)) / 2 ** d) if d else 1.0
    print(f"  juez {juez:<8} low {lo}/{len(comunes)}  high {hi}/{len(comunes)}"
          f"   neto {sum(difs):+d}  (gana {g}, pierde {p}, discordantes {d})"
          f"   P(signo, 1 cola) = {pv:.4f}")

# lo que hace falta para que un neto sea significativo con este n
for d in range(1, 12):
    v = next((v for v in range(d + 1)
              if sum(comb(d, x) for x in range(v, d + 1)) / 2 ** d < 0.05),
             None)
    if d in (4, 6, 8, 11):
        print(f"  [potencia] con {d} discordantes harian falta "
              f"{v if v is not None else 'IMPOSIBLE'} victorias para P<0.05")
