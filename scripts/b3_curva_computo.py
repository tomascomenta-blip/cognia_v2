# -*- coding: utf-8 -*-
"""
b3_curva_computo.py — REP contra la CURVA de BoN, no contra un solo punto.

El prereg comparaba a iso-PRESUPUESTO (4 candidatos por brazo). Pero el gasto
REALIZADO salió muy distinto: REP gasta menos porque sus cadenas se cortan
(el modelo se niega a reparar en el 15.8% de las rondas). Comparar 57 aciertos
con 187k tokens contra 59 con 318k no es iso-cómputo: es comparar dos puntos de
dos curvas distintas.

Aquí se reconstruye la curva de BoN con presupuestos K=1..4 **sobre las MISMAS
muestras ya generadas** (truncar el pool no requiere generar nada) y se sitúa
REP encima. Es descriptivo y post-hoc: se etiqueta como tal y NO cambia el
veredicto pre-registrado.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"

d = json.loads((SALIDA / (sys.argv[1] if len(sys.argv) > 1
                          else "reparacion.json")).read_text(encoding="utf-8"))
por = defaultdict(list)
for m in d["muestras"]:
    por[m["tarea"]].append(m)
comp = {t: v for t, v in por.items() if any(x.get("cierre") for x in v)}


def sel(pool):
    return sorted(pool, key=lambda m: (not m["pasa_vis"], -m["vis_ok"],
                                       m["idx"]))[0]


def brazo(v, b):
    r = [x for x in v if x["brazo"] == "raiz"]
    return r + sorted([x for x in v if x["brazo"] == b
                       and not x.get("no_generado")],
                      key=lambda m: m["idx"])


print(f"tareas: {len(comp)}\n")
print(f"{'brazo':<22} {'presup.':>7} {'aciertos':>9} {'%':>6} "
      f"{'generac.':>9} {'tok salida':>11} {'aciertos/100k tok':>18}")

filas = []
for b, etiqueta, presups in (("bon", "BoN", (1, 2, 3, 4)),
                             ("rep", "REP (contraejemplo)", (4,)),
                             ("pla", "PLACEBO", (4,))):
    for K in presups:
        ok = gen = tok = 0
        for v in comp.values():
            pool = brazo(v, b)[:K]
            ok += bool(sel(pool)["pasa_oc"])
            gen += len(pool)
            tok += sum((m.get("tok_salida") or 0) for m in pool)
        filas.append((etiqueta, K, ok, gen, tok))
        print(f"{etiqueta:<22} {'K='+str(K):>7} {ok:>9} "
              f"{ok/len(comp):>5.1%} {gen:>9} {tok:>11} "
              f"{ok/max(1,tok)*100000:>18.2f}")

print(f"\nLECTURA (descriptiva, post-hoc): se busca el presupuesto de BoN que "
      f"gasta\nmas o menos los mismos tokens que REP con K=4, y se comparan "
      f"sus aciertos.")
rep = next(f for f in filas if f[0].startswith("REP"))
bons = [f for f in filas if f[0] == "BoN"]
cerca = min(bons, key=lambda f: abs(f[4] - rep[4]))
print(f"  REP  K=4  ->  {rep[2]} aciertos con {rep[4]} tokens")
print(f"  BoN  K={cerca[1]}  ->  {cerca[2]} aciertos con {cerca[4]} tokens "
      f"(el mas cercano en gasto)")
print(f"  diferencia a gasto parecido: {rep[2]-cerca[2]:+d} tareas "
      f"({rep[4]-cerca[4]:+d} tokens)")
