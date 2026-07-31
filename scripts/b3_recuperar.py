# -*- coding: utf-8 -*-
"""
b3_recuperar.py — re-juzga SOLO las muestras cuyo juez falló por instrumento.

Durante el re-juicio uniforme, 107 muestras (16%) salieron con
`sin_sentinel`: el subprocess del arnés no llegó a imprimir ni una línea. Al
reproducir uno de esos casos A MANO funciona perfectamente (rc=0, sentinel
presente), así que **no es una propiedad del código juzgado**: es transitorio
del entorno (el harness mató procesos de fondo justo en esa ventana).

Contarlas como fallo del modelo sería facturar INSTRUMENTO al modelo — el
error que esta misma sesión ya cazó tres veces en el arnés. Aquí se vuelven a
juzgar, y solo esas.

Cero GPU.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import SALIDA, carga_lcb, extract_code, juzga_lcb, tests_lcb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fichero", nargs="?", default="lcb_uniforme.json")
    ap.add_argument("--semilla-split", type=int, default=20260730)
    ap.add_argument("--salida", default="")
    args = ap.parse_args()

    p = Path(args.fichero)
    if not p.is_absolute():
        p = SALIDA / args.fichero
    base = json.loads(p.read_text(encoding="utf-8"))
    destino = Path(args.salida) if args.salida else p

    tareas = {str(t["task_id"]): t for t in carga_lcb()}
    # Solo las que fallaron por INSTRUMENTO del juez. `sin_codigo` NO se
    # reintenta: ahí no hay código que juzgar, es un fallo real de generación.
    reintentar = [i for i, m in enumerate(base["muestras"])
                  if (m.get("juez_vis") or m.get("juez_oc")) not in
                  ("", "sin_codigo", None)]
    print(f"muestras a reintentar: {len(reintentar)}/{len(base['muestras'])}")
    print("  motivos:", dict(Counter(
        (base['muestras'][i].get('juez_oc') or
         base['muestras'][i].get('juez_vis')) for i in reintentar)))

    t0 = time.time()
    recuperadas = cambios = 0
    for j, i in enumerate(reintentar):
        m = base["muestras"][i]
        t = tareas.get(m["tarea"])
        if t is None:
            continue
        vis, oc = tests_lcb(t, random.Random(
            f"{args.semilla_split}:{m['tarea']}"))
        if not vis or not oc:
            continue
        code = extract_code(m.get("crudo") or "")
        vis_ok, mv = juzga_lcb(code, t, vis)
        oc_ok, mo = juzga_lcb(code, t, oc, parar_al_fallar=True)
        antes = m["pasa_oc"]
        m.update(vis_ok=vis_ok, vis_n=len(vis), oc_ok=oc_ok, oc_n=len(oc),
                 pasa_vis=vis_ok == len(vis), pasa_oc=oc_ok == len(oc),
                 juez_vis=mv, juez_oc=mo, reintentado=True)
        if not (mv or mo):
            recuperadas += 1
        if m["pasa_oc"] != antes:
            cambios += 1
        if (j + 1) % 25 == 0:
            print(f"  {j+1}/{len(reintentar)} "
                  f"({(time.time()-t0)/60:.1f} min)", flush=True)

    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(base, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, destino)

    ms = base["muestras"]
    quedan = sum(1 for x in ms if (x.get("juez_vis") or x.get("juez_oc"))
                 not in ("", "sin_codigo", None))
    print(f"\nrecuperadas {recuperadas}/{len(reintentar)} "
          f"({(time.time()-t0)/60:.1f} min); veredictos que cambian: {cambios}")
    print(f"  fallos de instrumento del juez que QUEDAN: {quedan}/{len(ms)} "
          f"({quedan/len(ms):.1%})")
    print(f"  pass@1 ahora: "
          f"{sum(1 for x in ms if x['pasa_oc'])/len(ms):.1%}")
    print(f"-> {destino}")


if __name__ == "__main__":
    main()
