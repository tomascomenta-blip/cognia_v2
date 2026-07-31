# -*- coding: utf-8 -*-
"""
b3_rejuzgar.py — deja la corrida con UN SOLO juez (ENMIENDA 2 del prereg).

La corrida de B-LCB empezó con hasta 35 casos ocultos sin límite de tamaño y
se reanudó con el cap (≤100 KB por caso, 15 ocultos). Mezclar dos jueces en
un mismo apareado no vale: aquí se re-juzgan TODAS las muestras con el
criterio ACTUAL, sobre el código ya generado, para que el instrumento sea
uniforme de punta a punta.

No gasta GPU: la generación no se repite, solo el juicio.

Distinguir pre/post-cap es trivial y no hace falta marcarlo en el runner: una
muestra juzgada con el cap tiene `oc_n == MAX_OCULTOS`; las de antes, más.
Eso permite medir la FIDELIDAD del re-juicio solo donde el criterio no
cambió — que es el control que dice si el `crudo` guardado basta para
re-juzgar (si estuviera truncado, la réplica saldría sesgada a la baja).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import (MAX_OCULTOS, SALIDA, carga_lcb, extract_code,
                       juzga_lcb, tests_lcb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fichero", default="lcb.json", nargs="?")
    ap.add_argument("--semilla-split", type=int, default=0,
                    help="0 = el split original; otro valor = RÉPLICA con "
                         "otro examen sobre las mismas muestras")
    ap.add_argument("--salida", default="")
    args = ap.parse_args()

    p = Path(args.fichero)
    if not p.is_absolute():
        p = SALIDA / args.fichero
    base = json.loads(p.read_text(encoding="utf-8"))
    semilla = args.semilla_split or base["semilla"]
    destino = Path(args.salida) if args.salida else (
        SALIDA / (p.stem + ("_uniforme" if not args.semilla_split
                            else f"_split{args.semilla_split}") + ".json"))

    tareas = {str(t["task_id"]): t for t in carga_lcb()}
    res = dict(base)
    res["muestras"] = []
    res["rejuzgado"] = {"semilla_split": semilla,
                        "max_ocultos": MAX_OCULTOS,
                        "derivado_de": p.name}

    t0 = time.time()
    cambios = fid_n = fid_disc = 0
    for i, m in enumerate(base["muestras"]):
        t = tareas.get(m["tarea"])
        if t is None:
            continue
        vis, oc = tests_lcb(t, random.Random(f"{semilla}:{m['tarea']}"))
        if not vis or not oc:
            continue
        code = extract_code(m.get("crudo") or "")
        vis_ok, mv = juzga_lcb(code, t, vis)
        oc_ok, mo = juzga_lcb(code, t, oc, parar_al_fallar=True)
        n = dict(m)
        n.update(vis_ok=vis_ok, vis_n=len(vis), oc_ok=oc_ok, oc_n=len(oc),
                 pasa_vis=vis_ok == len(vis), pasa_oc=oc_ok == len(oc),
                 juez_vis=mv, juez_oc=mo)
        if n["pasa_oc"] != m["pasa_oc"]:
            cambios += 1
        # FIDELIDAD: solo donde el criterio NO cambió (ya venía con el cap)
        # y el split es el original. Ahí un veredicto distinto solo puede
        # venir del `crudo` guardado, no del juez.
        if not args.semilla_split and m.get("oc_n") == MAX_OCULTOS:
            fid_n += 1
            if n["pasa_oc"] != m["pasa_oc"]:
                fid_disc += 1
        res["muestras"].append(n)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(base['muestras'])} "
                  f"({(time.time()-t0)/60:.1f} min)", flush=True)

    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, destino)

    n = len(res["muestras"])
    ok = sum(1 for x in res["muestras"] if x["pasa_oc"])
    print(f"\nre-juzgadas {n} muestras en {(time.time()-t0)/60:.1f} min")
    print(f"  pass@1 = {ok/max(1,n):.1%}   veredictos que cambian vs el "
          f"fichero original: {cambios} ({cambios/max(1,n):.1%})")
    if fid_n:
        print(f"  CONTROL DE FIDELIDAD (mismo criterio y mismo split, "
              f"n={fid_n}): {fid_disc} discrepan ({fid_disc/fid_n:.1%})")
        if fid_disc / fid_n > 0.02:
            print(f"  [!] >2%: el `crudo` guardado NO basta para re-juzgar; "
                  f"cualquier réplica estaría sesgada.")
        else:
            print(f"  OK: el código guardado reproduce el veredicto, así que "
                  f"re-juzgar es legítimo.")
    print(f"-> {destino}")


if __name__ == "__main__":
    main()
