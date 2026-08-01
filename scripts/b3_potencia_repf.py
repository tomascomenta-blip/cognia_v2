# -*- coding: utf-8 -*-
"""b3_potencia_repf.py — POTENCIA del brazo REP-F ANTES de gastar GPU.

REP-F = la cadena de reparación con FALLBACK a generación fresca cuando el
modelo se niega o no hay nada que reparar (el corolario de diseño del
2026-07-31: el contraejemplo triplica la negativa, 5.3%→15.8%, y 34 cadenas
de REP se cortaron sin gastar su presupuesto).

Este script NO genera nada. Lee `b3_codigo/reparacion.json` y calcula:

1. En cuántas tareas la cadena REP se cortó ANTES de agotar k=4 sin aprobar
   los visibles — las únicas donde REP-F puede diferir de REP.
2. La COTA SUPERIOR de la ganancia de REP-F sobre REP: de esas tareas, en
   cuántas REP falló el oculto Y algún candidato ya generado de esa tarea
   (BoN o raíz) lo acierta. Si ni el pool entero de la tarea lo acierta, un
   par de muestras frescas más difícilmente lo harían — es cota optimista.
3. El contraste que importa (REP-F − BoN): parte del −2 medido de REP−BoN y
   le suma la cota; con los discordantes resultantes, el efecto mínimo
   detectable del sign-flip apareado.

Un diseño que no distingue "no hay efecto" de "no lo veríamos" no tiene
derecho a correrse caro (potencia-antes-de-matar-una-via).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def victorias_necesarias(d: int) -> int:
    """Mínimo de victorias en d discordantes para P<0.05 (binomial, 1 cola)."""
    from math import comb
    for k in range(d, -1, -1):
        p = sum(comb(d, j) for j in range(k, d + 1)) / 2 ** d
        if p >= 0.05:
            return k + 1
    return d + 1


def main():
    fichero = RAIZ / "b3_codigo" / "reparacion.json"
    d = json.loads(fichero.read_text(encoding="utf-8"))
    por_tarea = defaultdict(list)
    for m in d["muestras"]:
        if not m.get("cierre"):
            por_tarea[m["tarea"]].append(m)

    k = d["k"]
    seleccion = {}      # tarea -> {brazo: pasa_oc del ELEGIDO}
    corte_rep = {}      # tarea -> por qué se cortó la cadena REP (o None)
    pool_acierta = {}   # tarea -> algún candidato de CUALQUIER brazo pasa_oc

    for tarea, ms in por_tarea.items():
        raiz = [m for m in ms if m["brazo"] == "raiz"]
        if not raiz:
            continue
        raiz = raiz[0]
        pool_acierta[tarea] = any(m.get("pasa_oc") for m in ms)
        sel = {}
        for brazo in ("bon", "rep", "pla"):
            cand = [raiz] + [m for m in ms if m["brazo"] == brazo
                             and not m.get("no_generado")]
            # la política literal de bon.py: aprobado > vis_ok > el más temprano
            elegido = max(cand, key=lambda m: (bool(m.get("pasa_vis")),
                                               m.get("vis_ok", 0),
                                               -m.get("idx", 9)))
            sel[brazo] = bool(elegido.get("pasa_oc"))
        seleccion[tarea] = sel

        reps = [m for m in ms if m["brazo"] == "rep"]
        gastadas = [m for m in reps if not m.get("no_generado")]
        cortes = [m for m in reps if m.get("no_generado")]
        aprobo = raiz.get("pasa_vis") or any(m.get("pasa_vis")
                                             for m in gastadas)
        negativa = any(m.get("sin_codigo_modelo") for m in gastadas)
        # la cadena se quedó CORTA si no aprobó visibles y no llegó a k-1
        # generaciones reales (raíz aparte), sea por corte explícito o por
        # negativa que dejó sin código al eslabón siguiente
        if not aprobo and (cortes or negativa) and len(gastadas) < k - 1:
            # (bug de precedencia cazado en la verificación adversarial del
            # 2026-07-31: la versión anterior parseaba `A or B if c else d`
            # como `A or (B if c else d)` y habría reventado sin `cortes`)
            if cortes:
                corte_rep[tarea] = (cortes[0].get("corte")
                                    or cortes[0].get("instrumento"))
            else:
                corte_rep[tarea] = "negativa_sin_corte"
        elif not aprobo and (cortes or negativa):
            corte_rep[tarea] = None  # negativa hubo, pero gastó el presupuesto
        else:
            corte_rep[tarea] = None

    tareas = sorted(seleccion)
    n = len(tareas)
    bon = sum(seleccion[t]["bon"] for t in tareas)
    rep = sum(seleccion[t]["rep"] for t in tareas)
    print(f"tareas con raiz: {n}   BoN {bon}   REP {rep}   "
          f"(neto REP-BoN {rep - bon:+d})")

    cortadas = [t for t in tareas if corte_rep[t]]
    print(f"\ncadenas REP cortadas antes de agotar presupuesto: "
          f"{len(cortadas)}")
    for causa in set(corte_rep[t] for t in cortadas):
        print(f"  {causa}: {sum(1 for t in cortadas if corte_rep[t] == causa)}")

    # dónde puede REP-F ganar lo que REP no ganó
    gana_max = [t for t in cortadas
                if not seleccion[t]["rep"] and pool_acierta[t]]
    gana_vs_bon = [t for t in gana_max if not seleccion[t]["bon"]]
    print(f"\nde esas, REP falla el oculto y el POOL de la tarea sí lo "
          f"acierta (cota de mejora de REP-F sobre REP): {len(gana_max)}")
    print(f"  y además BoN TAMBIÉN falla (únicas que moverían "
          f"REP-F − BoN a favor): {len(gana_vs_bon)}")
    print(f"  tareas: {gana_vs_bon}")

    # el contraste primario REP-F vs BoN, en el mejor mundo posible.
    # CONTABILIDAD CORREGIDA por la verificación adversarial del 2026-07-31:
    # la primera versión sumaba al neto solo las tareas gana_vs_bon, pero
    # arreglar una tarea (bon=1, rep=0) TAMBIÉN sube el neto en +1 (el
    # discordante a favor de BoN pasa a empate). Con fallback perfecto las
    # 9 de gana_max cuentan enteras, y los discordantes del techo son
    # 20 − (las que BoN ganaba y ahora empatan) + (las nuevas a favor).
    disc_actual = [t for t in tareas
                   if seleccion[t]["rep"] != seleccion[t]["bon"]]
    neto_actual = rep - bon
    quita = len(gana_max) - len(gana_vs_bon)   # bon=1 -> pasan a empate
    neto_maximo = neto_actual + len(gana_max)
    d_max = len(disc_actual) - quita + len(gana_vs_bon)
    v = victorias_necesarias(d_max)
    mde = 2 * v - d_max
    vic_techo = sum(1 for t in disc_actual if seleccion[t]["rep"]) \
        + len(gana_vs_bon)
    print(f"\ncontraste REP-F − BoN (techo con fallback PERFECTO):")
    print(f"  discordantes hoy (REP vs BoN): {len(disc_actual)}")
    print(f"  neto hoy: {neto_actual:+d}   neto TECHO: {neto_maximo:+d}   "
          f"(d_techo={d_max}, victorias techo {vic_techo}/{d_max}, "
          f"necesarias {v})")
    print(f"  efecto mínimo detectable en d={d_max}: {mde:+d} tareas netas")
    print(f"\n  Y el techo del POOL no acota el mecanismo FRESCO: en las "
          f"tareas cortadas donde el pool entero falla, REP-F añadiría "
          f"muestras frescas nuevas (tasa condicional medida en este mismo "
          f"fichero: P(s4 pasa oc | s1..s3 fallan) = 2/62 = 3.2%).")
    if neto_maximo < mde:
        print(f"\nVEREDICTO DE POTENCIA: el TECHO ({neto_maximo:+d}) queda "
              f"por debajo del MDE ({mde:+d}): correr el diseño tal cual "
              f"desemboca en SIN POTENCIA salvo suerte en el mecanismo "
              f"fresco. La decisión de correr o no es de INVERSIÓN y se "
              f"registra en el prereg, no aquí.")
    else:
        print(f"\nVEREDICTO DE POTENCIA: el techo ({neto_maximo:+d}) alcanza "
              f"el MDE ({mde:+d}): el diseño PODRÍA ver el efecto si el "
              f"fallback rindiera cerca del máximo. Decidir por esperanza "
              f"realista, no por el techo.")


if __name__ == "__main__":
    main()
