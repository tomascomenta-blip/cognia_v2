# -*- coding: utf-8 -*-
"""
b3_potencia_apareado.py — ¿tiene potencia el contraste REP vs BoN?

Un revisor adversarial midió que el diseño podría estar predeterminado al KILL:
si solo ~10 tareas pueden DISCORDAR entre brazos, un sign-flip apareado exige
9 victorias de 10 para P<0.05, y un efecto real de +4 tareas saldría P≈0.17.

Esto NO se acepta por plausible: se comprueba sobre los datos que ya están en
disco (`lcb_uniforme.json`, 167 tareas × 4 con el juez de anoche) y sobre
`lcb_hard_r2.json`. Es la misma disciplina que impidió firmar un KILL falso en
el descubridor metamórfico: medir el instrumento antes de creerse el veredicto.

Lo que se mide, por estrato:
  1. % de tareas donde s1 FALLA los visibles  -> sin eso los tres brazos son
     el mismo registro y la tarea aporta un empate garantizado.
  2. % de tareas DISCRIMINANTES (0 < aciertos ocultos < k) -> es el techo de
     lo que cualquier selector puede mover.
  3. % de tareas con fallo de instrumento -> las que la primaria excluye.
  4. La potencia resultante del sign-flip: cuántas victorias hacen falta.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import carga_lcb

SALIDA = RAIZ / "b3_codigo"


def victorias_necesarias(n_disc: int, alfa: float = 0.05) -> int:
    """Con `n_disc` tareas discordantes, ¿cuántas tiene que ganar REP para que
    el sign-flip de UNA COLA baje de alfa? (sign test exacto)."""
    for v in range(n_disc + 1):
        p = sum(comb(n_disc, x) for x in range(v, n_disc + 1)) / 2 ** n_disc
        if p < alfa:
            return v
    return n_disc + 1


def p_del_sign(n_disc: int, victorias: int) -> float:
    if n_disc == 0:
        return 1.0
    return sum(comb(n_disc, x)
               for x in range(victorias, n_disc + 1)) / 2 ** n_disc


def analiza(fichero: str, etiqueta: str):
    p = SALIDA / fichero
    if not p.exists():
        print(f"[!] no existe {p}")
        return
    res = json.loads(p.read_text(encoding="utf-8"))
    k = res["k"]
    por = defaultdict(list)
    for m in res["muestras"]:
        por[m["tarea"]].append(m)
    tareas = {t: v for t, v in por.items() if len(v) == k}
    meta = {str(t["task_id"]): t for t in carga_lcb()}

    print(f"\n{'='*72}\n{etiqueta}: {len(tareas)} tareas completas (k={k})\n"
          f"{'='*72}")
    print(f"{'estrato':<8} {'n':>4} {'s1 falla vis':>13} {'discrimin.':>11} "
          f"{'con instrum.':>13} {'ambos':>8}")
    for dif in ("easy", "medium", "hard", "TODOS"):
        sub = {t: v for t, v in tareas.items()
               if dif == "TODOS" or meta.get(t, {}).get("dificultad") == dif}
        if not sub:
            continue
        n = len(sub)
        s1_falla = sum(1 for v in sub.values()
                       if not sorted(v, key=lambda m: m["s"])[0]["pasa_vis"])
        disc = sum(1 for v in sub.values()
                   if 0 < sum(1 for m in v if m["pasa_oc"]) < k)
        inst = sum(1 for v in sub.values()
                   if any(m["instrumento"] for m in v))
        # las dos condiciones a la vez: es lo que de verdad puede discordar
        ambos = sum(1 for v in sub.values()
                    if not sorted(v, key=lambda m: m["s"])[0]["pasa_vis"]
                    and 0 < sum(1 for m in v if m["pasa_oc"]) < k
                    and not any(m["instrumento"] for m in v))
        print(f"{dif:<8} {n:>4} {s1_falla:>6} ({s1_falla/n:>4.0%}) "
              f"{disc:>5} ({disc/n:>4.0%}) {inst:>6} ({inst/n:>4.0%}) "
              f"{ambos:>4} ({ambos/n:>4.0%})")
    return tareas, meta


def potencia(tasa_discordancia: float, nombre: str):
    print(f"\n  --- POTENCIA con tasa de discordancia {tasa_discordancia:.0%} "
          f"({nombre}) ---")
    print(f"  {'N tareas':>9} {'discordantes':>13} {'victorias para P<0.05':>23}"
          f" {'P si gana 70%':>14}")
    for n in (50, 70, 90, 120, 154):
        d = int(round(n * tasa_discordancia))
        v = victorias_necesarias(d)
        gana70 = int(round(d * 0.7))
        pp = p_del_sign(d, gana70)
        print(f"  {n:>9} {d:>13} {v:>23} {pp:>14.4f}"
              f"{'   <- NO detecta un 70/30' if pp >= 0.05 else ''}")


if __name__ == "__main__":
    analiza("lcb_uniforme.json", "BANCO GLOBAL (juez uniforme, test6)")
    analiza("lcb_hard_r2.json", "HARD, replica de generacion")
    # La discordancia REP-vs-BoN es como mucho la fracción de tareas que
    # pueden cambiar de veredicto Y donde los brazos divergen. Se exploran
    # tres supuestos, del pesimista al optimista.
    for tasa, nombre in ((0.10, "pesimista"), (0.20, "medio"),
                         (0.30, "optimista")):
        potencia(tasa, nombre)
