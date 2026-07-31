# -*- coding: utf-8 -*-
"""
b3_hard_comparar.py — el estrato `hard` en las TRES lecturas.

ENMIENDA 3 (post-hoc, declarada). Compara el mismo estrato bajo tres fuentes
de variación distintas, para separar de qué depende el neto:

  1. `hard` del banco original            -> examen A, muestras A
  2. `hard` de la réplica de EXAMEN       -> examen B, muestras A
  3. `hard` de la réplica de GENERACIÓN   -> examen A, muestras B  <- lo nuevo

Si el neto sobrevive a (2) y a (3), no depende ni del sorteo del examen ni de
la tirada de generación. La memoria `varianza-entre-corridas` mide ±34 puntos
entre corridas del mismo lazo: (3) es lo único que controla eso.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"
sys.path.insert(0, str(RAIZ / "scripts"))

REPLICAS = 10000


def carga(fichero: str, solo_hard: bool = True) -> dict:
    p = SALIDA / fichero
    if not p.exists():
        return {}
    res = json.loads(p.read_text(encoding="utf-8"))
    from b3_codigo import carga_lcb
    meta = {str(t["task_id"]): t for t in carga_lcb()}
    por = {}
    for m in res["muestras"]:
        if solo_hard and meta.get(m["tarea"], {}).get("dificultad") != "hard":
            continue
        por.setdefault(m["tarea"], []).append(m)
    return {t: sorted(v, key=lambda z: z["s"])
            for t, v in por.items() if len(v) == res["k"]}


def brazos(tareas: dict, k: int = 4) -> dict:
    if not tareas:
        return {}
    limpias = {t: v for t, v in tareas.items()
               if not any(z["instrumento"] for z in v)}
    tt = limpias or tareas
    ctrl = sum(1 for v in tt.values() if v[0]["pasa_oc"])
    bon = sum(1 for v in tt.values()
              if sorted(v, key=lambda z: (not z["pasa_vis"], -z["vis_ok"],
                                          z["s"]))[0]["pasa_oc"])
    techo = sum(1 for v in tt.values() if any(z["pasa_oc"] for z in v))
    azar = sum(sum(1 for z in v if z["pasa_oc"]) / k for v in tt.values())
    az1 = 0.0
    for v in tt.values():
        vivas = [z for z in v if z["vis_ok"] > 0] or v
        az1 += sum(1 for z in vivas if z["pasa_oc"]) / len(vivas)
    rng = random.Random(20260730)
    vals = [[z["pasa_oc"] for z in v] for v in tt.values()]
    nulo = sorted(sum(1 for f in vals if f[rng.randrange(k)])
                  for _ in range(REPLICAS))
    p95 = nulo[int(0.95 * REPLICAS)]
    p = sum(1 for x in nulo if x >= bon) / REPLICAS
    pass1 = sum(sum(1 for z in v if z["pasa_oc"]) for v in tt.values()) / (
        len(tt) * k)
    return {"n": len(tt), "pass1": pass1, "s1": ctrl, "azar": azar,
            "azar1": az1, "bon": bon, "techo": techo, "p95": p95, "p": p}


def main():
    fuentes = [
        ("original      (examen A, muestras A)", "lcb_uniforme.json"),
        ("replica EXAMEN(examen B, muestras A)", "lcb_split2.json"),
        ("replica GENER.(examen A, muestras B)", "lcb_hard_r2.json"),
    ]
    print("ESTRATO `hard` — de qué depende el neto\n")
    print(f"{'fuente':<38} {'n':>3} {'pass@1':>7} {'AZAR':>7} {'BoN':>4} "
          f"{'techo':>6} {'neto':>7} {'P':>8} {'vs AZAR-1':>10}")
    for nombre, f in fuentes:
        b = brazos(carga(f))
        if not b:
            print(f"{nombre:<38}  (sin datos: {f})")
            continue
        ps = "< 1e-4" if b["p"] <= 1.0 / REPLICAS else f"{b['p']:.4f}"
        print(f"{nombre:<38} {b['n']:>3} {b['pass1']:>6.1%} "
              f"{b['azar']:>7.2f} {b['bon']:>4} {b['techo']:>6} "
              f"{b['bon']-b['azar']:>+7.2f} {ps:>8} "
              f"{b['bon']-b['azar1']:>+10.2f}")
    print("\nLectura: (2) controla el sorteo del EXAMEN; (3) controla la")
    print("tirada de GENERACION, que es la que la memoria varianza-entre-")
    print("corridas mide en +-34 pts y que una replica de examen NO toca.")


if __name__ == "__main__":
    main()
