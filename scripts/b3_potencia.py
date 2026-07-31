# -*- coding: utf-8 -*-
"""
b3_potencia.py — ¿puede este diseño DETECTAR el efecto que busca?

Se calcula ANTES de correr (PREREG_BANCO_CODIGO, sección 4). Un diseño sin
potencia produce un "no supera el nulo" que no distingue "no hay efecto" de
"no lo veríamos aunque lo hubiera": eso sería un KILL falso, y el repo ya se
comió uno parecido (el descubridor moría, no la idea).

Modelo: N tareas, K muestras. Cada tarea tiene su propia tasa de acierto p_t
(heterogénea, que es lo realista: hay tareas fáciles e imposibles). El
selector ideal acierta si ALGUNA muestra es correcta (=techo). Un selector
con ruido acierta el techo solo una fracción del tiempo.
"""
from __future__ import annotations

import random
import sys

REPLICAS = 4000
RNG = random.Random(20260730)


def simula(n, k, p_media, calidad_selector, dispersion=0.35):
    """calidad_selector: 1.0 = elige siempre una correcta si existe (techo);
    0.0 = elige uniformemente al azar. Devuelve (bon, azar, techo, control)."""
    bon = azar = techo = control = 0.0
    for _ in range(n):
        # p_t heterogénea por tarea (beta centrada en p_media)
        a = max(0.05, p_media / dispersion)
        b = max(0.05, (1 - p_media) / dispersion)
        p = RNG.betavariate(a, b)
        muestras = [RNG.random() < p for _ in range(k)]
        hay = any(muestras)
        techo += hay
        control += muestras[0]
        azar += sum(muestras) / k
        if hay and RNG.random() < calidad_selector:
            bon += 1
        else:
            bon += sum(muestras) / k        # cae al azar cuando no discrimina
    return bon, azar, techo, control


def p95_nulo(n, k, p_media, dispersion=0.35):
    """p95 de los aciertos del brazo nulo (una muestra uniforme por tarea)."""
    rng = random.Random(99)
    tareas = []
    for _ in range(n):
        a = max(0.05, p_media / dispersion)
        b = max(0.05, (1 - p_media) / dispersion)
        p = rng.betavariate(a, b)
        tareas.append([rng.random() < p for _ in range(k)])
    vals = []
    for _ in range(REPLICAS):
        vals.append(sum(1 for m in tareas if m[rng.randrange(k)]))
    vals.sort()
    return vals[int(0.95 * REPLICAS)], sum(vals) / len(vals)


def main():
    print("POTENCIA del diseno (K=4). 'gana' = el BoN supera el p95 del nulo\n")
    print(f"{'N':>5} {'p@1':>6} {'calidad':>8} {'azar':>7} {'p95':>6} "
          f"{'BoN':>7} {'neto':>7}  veredicto")
    for n in (60, 100, 175):
        for p in (0.30, 0.45):
            p95, media = p95_nulo(n, 4, p)
            for q in (1.0, 0.6, 0.3, 0.0):
                bon, azar, techo, ctrl = simula(n, 4, p, q)
                print(f"{n:>5} {p:>6.2f} {q:>8.1f} {azar:>7.1f} {p95:>6} "
                      f"{bon:>7.1f} {bon-azar:>+7.1f}  "
                      f"{'GANA' if bon > p95 else 'no'}")
            print()


if __name__ == "__main__":
    main()
