# -*- coding: utf-8 -*-
"""
b3_rejuzgar_fuga.py — ¿cuánto del +21.00 de anoche era FUGA por contenido?

El split de B-LCB es disjunto POR ÍNDICE, pero medido hoy
(`b3_fuga_split.py`): **20 de las 175 tareas del banco de anoche (11.4%)**
tienen algún caso VISIBLE cuya entrada se repite entre los OCULTOS — y dos
tareas tienen los CINCO. En esas, el examen del selector contiene literalmente
un trozo del juez: la selección deja de medir generalización y mide identidad.

Esto no se estima: se re-juzga. Solo hacen falta las tareas afectadas, y solo
el juez OCULTO — el código ya está en disco, así que no se gasta ni un token
de GPU. Después se corre b3_analisis.py sobre el fichero corregido y se compara
el neto con el publicado anoche.

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_rejuzgar_fuga.py \\
        --entrada lcb_uniforme.json --salida lcb_sinfuga.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import SALIDA, carga_lcb, extract_code, juzga_lcb, tests_lcb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", default="lcb_uniforme.json")
    ap.add_argument("--salida", default="lcb_sinfuga.json")
    ap.add_argument("--ficheros", default="lcb_test6.jsonl")
    args = ap.parse_args()

    res = json.loads((SALIDA / args.entrada).read_text(encoding="utf-8"))
    tareas = {str(t["task_id"]): t for t in carga_lcb(
        ficheros=tuple(x.strip() for x in args.ficheros.split(",")))}

    # qué tareas cambian de examen oculto al quitar la fuga
    afectadas, nuevos = {}, {}
    for tid, t in tareas.items():
        rng = random.Random(f"{res['semilla']}:{tid}")
        vis, oc = tests_lcb(t, rng)
        rng2 = random.Random(f"{res['semilla']}:{tid}")
        vis2, oc2 = tests_lcb(t, rng2, sin_fuga=True)
        if len(oc2) != len(oc):
            afectadas[tid] = (len(oc), len(oc2))
            nuevos[tid] = (vis2, oc2)
    print(f"tareas cuyo OCULTO cambia: {len(afectadas)}")
    for tid, (a, b) in list(afectadas.items())[:25]:
        print(f"   {tid}: {a} -> {b} ocultos")

    cambios = 0
    n = 0
    t0 = time.time()
    for m in res["muestras"]:
        tid = m["tarea"]
        if tid not in nuevos:
            continue
        n += 1
        vis2, oc2 = nuevos[tid]
        if not oc2:
            # sin ocultos que no sean copia de un visible: la tarea deja de
            # poder juzgarse y se MARCA, no se inventa un veredicto
            m["oc_n"] = 0
            m["pasa_oc"] = False
            m["juez_oc"] = "sin_ocultos_tras_quitar_fuga"
            continue
        code = extract_code(m.get("crudo") or "")
        oc_ok, motivo = juzga_lcb(code, tareas[tid], oc2,
                                  parar_al_fallar=True)
        antes = m["pasa_oc"]
        m["oc_ok"] = oc_ok
        m["oc_n"] = len(oc2)
        m["pasa_oc"] = (oc_ok == len(oc2))
        m["juez_oc"] = motivo
        if antes != m["pasa_oc"]:
            cambios += 1
    print(f"\nmuestras re-juzgadas : {n}   ({time.time()-t0:.0f} s)")
    print(f"VEREDICTOS QUE CAMBIAN: {cambios}")

    res["nota_fuga"] = ("ocultos sin los casos cuya entrada coincide con un "
                        "visible (b3_fuga_split.py, 2026-07-31)")
    (SALIDA / args.salida).write_text(
        json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"-> {SALIDA / args.salida}")


if __name__ == "__main__":
    main()
