# -*- coding: utf-8 -*-
"""Diagnóstico en vivo de la corrida de reparación: ¿cuántas tareas pueden
DISCORDAR de verdad? Es la cantidad que decide la potencia, y conviene verla
mientras corre, no al final.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"

d = json.loads((SALIDA / (sys.argv[1] if len(sys.argv) > 1
                          else "reparacion.json")).read_text(encoding="utf-8"))
por = defaultdict(list)
for m in d["muestras"]:
    por[m["tarea"]].append(m)
comp = {t: v for t, v in por.items() if any(x.get("cierre") for x in v)}

raiz_pasa_vis = 0
raiz_pasa_oc = 0
divergen = 0
for t, v in comp.items():
    r = next(x for x in v if x["brazo"] == "raiz")
    raiz_pasa_vis += bool(r["pasa_vis"])
    raiz_pasa_oc += bool(r["pasa_oc"])
    gen = [x for x in v if x["brazo"] in ("bon", "rep", "pla")
           and not x.get("no_generado")]
    if gen:
        divergen += 1

n = len(comp)
print(f"tareas completas          : {n}")
print(f"raiz pasa VISIBLES        : {raiz_pasa_vis} ({raiz_pasa_vis/max(1,n):.0%})"
      f"   <- ahi los 3 brazos paran juntos y NO pueden discordar")
print(f"raiz pasa OCULTO          : {raiz_pasa_oc} ({raiz_pasa_oc/max(1,n):.0%})")
print(f"tareas donde los brazos SI generan candidatos propios: {divergen} "
      f"({divergen/max(1,n):.0%})")

# de las que divergen, ¿en cuántas cambia el veredicto algún brazo?
def sel(pool):
    return sorted(pool, key=lambda m: (not m["pasa_vis"], -m["vis_ok"],
                                       m["idx"]))[0]

disc = 0
for t, v in comp.items():
    r = [x for x in v if x["brazo"] == "raiz"]
    res = {}
    for b in ("bon", "rep", "pla"):
        pool = r + [x for x in v if x["brazo"] == b
                    and not x.get("no_generado")]
        res[b] = sel(pool)["pasa_oc"]
    if len(set(res.values())) > 1:
        disc += 1
print(f"tareas DISCORDANTES entre brazos (lo que da potencia): {disc} "
      f"({disc/max(1,n):.0%})")

print(f"\n--- generaciones por brazo ---")
gen = [m for m in d["muestras"] if not m.get("cierre")
       and not m.get("no_generado")]
print(dict(Counter(m["brazo"] for m in gen)))
print(f"instrumento: {sum(1 for m in gen if m['instrumento'])}  "
      f"se rinde: {sum(1 for m in gen if m.get('sin_codigo_modelo'))}  "
      f"cortes: {sum(1 for m in d['muestras'] if m.get('no_generado'))}")

# ¿Se rinde MÁS cuando se le pide reparar? Es mecanismo, no un corte post-hoc:
# si el prompt de reparación dispara la negativa, el brazo REP se queda sin
# cadena y gasta MENOS cómputo que BoN — o sea, el experimento deja de ser
# iso-cómputo por una razón que hay que nombrar.
print(f"\n--- ¿se rinde mas al REPARAR? (por brazo) ---")
for b in ("raiz", "bon", "rep", "pla"):
    sub = [m for m in gen if m["brazo"] == b]
    if not sub:
        continue
    r = sum(1 for m in sub if m.get("sin_codigo_modelo"))
    print(f"  {b:<5} {r:>3}/{len(sub):<4} = {r/len(sub):>5.1%}   "
          f"tokens de salida {sum(m.get('tok_salida') or 0 for m in sub):>7}")
# Test de dos proporciones para la negativa: el numero se calcula, no se
# estima a ojo. Permutacion sobre las etiquetas de brazo (10.000 replicas),
# que no asume normalidad ni tamanos grandes.
import random as _r


def _perm_prop(a_ok, a_n, b_ok, b_n, semilla=20260731, reps=10000):
    obs = a_ok / a_n - b_ok / b_n
    bolsa = [1] * (a_ok + b_ok) + [0] * ((a_n - a_ok) + (b_n - b_ok))
    rng = _r.Random(semilla)
    ge = 0
    for _ in range(reps):
        rng.shuffle(bolsa)
        d1 = sum(bolsa[:a_n]) / a_n
        d2 = sum(bolsa[a_n:]) / b_n
        if abs(d1 - d2) >= abs(obs):
            ge += 1
    return obs, ge / reps


print(f"\n--- ¿el CONTRAEJEMPLO dispara la negativa? (permutacion, 2 colas) ---")
cuentas = {}
for b in ("bon", "rep", "pla"):
    sub = [m for m in gen if m["brazo"] == b]
    cuentas[b] = (sum(1 for m in sub if m.get("sin_codigo_modelo")), len(sub))
for x, y in (("rep", "bon"), ("rep", "pla"), ("pla", "bon")):
    dif, p = _perm_prop(cuentas[x][0], cuentas[x][1],
                        cuentas[y][0], cuentas[y][1])
    print(f"  {x} - {y}: {dif*100:+5.1f} pts   P = "
          f"{'< 1e-4' if p <= 1e-4 else f'{p:.4f}'}")

cortes = [m for m in d["muestras"] if m.get("no_generado")]
print(f"\n--- cortes de cadena, por brazo y motivo ---")
print(dict(Counter((m["brazo"], m.get("corte") or m.get("instrumento"))
                   for m in cortes)))
