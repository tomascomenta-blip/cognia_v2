# -*- coding: utf-8 -*-
"""¿Hay EFECTO DE ORDEN entre las K muestras de una tarea?

El control de independencia de `b3_analisis.py` compara el BoN que desempata
por "índice más temprano" contra el que desempata AL AZAR. Con muestras i.i.d.
los dos deberían coincidir; tras corregir la fuga, la diferencia subió a +2.30,
justo por encima de su umbral de aviso de 2 puntos.

Si `s1` fuera sistemáticamente mejor que `s2..s4`, el BoN estaría cobrando en
parte por un artefacto del orden y no por selección. Se mide directamente:
pass@1 por índice de muestra, y el reparto de quién gana los empates.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"

for nombre in (sys.argv[1:] or ["lcb_sinfuga.json", "lcb_hard_r2.json"]):
    p = SALIDA / nombre
    if not p.exists():
        print(f"[!] no existe {p}")
        continue
    res = json.loads(p.read_text(encoding="utf-8"))
    k = res["k"]
    por = defaultdict(list)
    for m in res["muestras"]:
        por[m["tarea"]].append(m)
    tareas = {t: sorted(v, key=lambda m: m["s"])
              for t, v in por.items() if len(v) == k}
    n = len(tareas)
    print(f"\n=== {nombre}  ({n} tareas, k={k}) ===")
    print(f"  {'indice':>7} {'pasa_oc':>9} {'pass@1':>8} {'pasa_vis':>10} "
          f"{'instrum.':>9}")
    tot = []
    for s in range(1, k + 1):
        ms = [v[s - 1] for v in tareas.values()]
        oc = sum(1 for m in ms if m["pasa_oc"])
        vis = sum(1 for m in ms if m["pasa_vis"])
        inst = sum(1 for m in ms if m["instrumento"])
        tot.append(oc)
        print(f"  s{s:<6} {oc:>9} {oc/max(1,len(ms)):>7.1%} {vis:>10} "
              f"{inst:>9}")
    # test binomial exacto: ¿s1 esta por encima de la media de los demas?
    resto = sum(tot[1:]) / max(1, (k - 1))
    print(f"  s1 = {tot[0]}   media de s2..s{k} = {resto:.2f}   "
          f"diferencia {tot[0]-resto:+.2f}")

    # el reparto de los EMPATES: cuando varias muestras empatan en
    # (pasa_vis, vis_ok), ¿la mas temprana acierta el oculto mas a menudo?
    gana_temprana = gana_tardia = empatan = 0
    for v in tareas.values():
        clave = min((not m["pasa_vis"], -m["vis_ok"]) for m in v)
        emp = [m for m in v
               if (not m["pasa_vis"], -m["vis_ok"]) == clave]
        if len(emp) < 2:
            continue
        prim = emp[0]["pasa_oc"]
        otros = [m["pasa_oc"] for m in emp[1:]]
        if prim and not any(otros):
            gana_temprana += 1
        elif not prim and any(otros):
            gana_tardia += 1
        else:
            empatan += 1
    disc = gana_temprana + gana_tardia
    p = (sum(comb(disc, x) for x in range(gana_temprana, disc + 1))
         / 2 ** disc) if disc else 1.0
    print(f"  EMPATES resueltos: la mas TEMPRANA acierta sola "
          f"{gana_temprana}, una TARDIA acierta sola {gana_tardia}, "
          f"indiferentes {empatan}")
    print(f"  P(signo, una cola) = {p:.4f}   "
          f"{'<< hay efecto de orden' if p < 0.05 else 'sin efecto de orden detectable'}")

    # TEST DE INTERCAMBIABILIDAD: si las K muestras de una tarea son i.i.d.,
    # da igual cuál se llame "la primera". Se permutan las etiquetas dentro de
    # cada tarea 10.000 veces y se mira dónde cae el conteo REAL de s1.
    import random as _r
    rng = _r.Random(20260731)
    vals = [[m["pasa_oc"] for m in v] for v in tareas.values()]
    nulo = []
    for _ in range(10000):
        nulo.append(sum(1 for f in vals if f[rng.randrange(k)]))
    nulo.sort()
    mayor = sum(1 for x in nulo if x >= tot[0]) / len(nulo)
    print(f"  INTERCAMBIABILIDAD: s1={tot[0]}, nulo mediana "
          f"{nulo[len(nulo)//2]}, p95 {nulo[int(0.95*len(nulo))]}   "
          f"P(nulo >= s1) = {mayor:.4f}   "
          f"{'<< s1 NO es intercambiable' if mayor < 0.05 else 'compatible con i.i.d.'}")
