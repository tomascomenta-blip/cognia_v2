# -*- coding: utf-8 -*-
"""
b3_frontier_rejuzga_sinfuga.py — re-juzga el frontier en las hard comunes con
el split SIN FUGA, para el apareado contra reparacion.json.

ANALISIS_GOAL_RESPONDIDO_20260801.md: reparacion.json se juzgó con
`tests_lcb(..., sin_fuga=True)` y frontier_resultados.json con el split del
factorial (con fuga). La primaria del análisis del goal exige el MISMO examen
en ambos lados, así que aquí se re-juzga el CÓDIGO CRUDO del frontier
(frontier_60_raw.json + frontier_138_raw.json) con el split sin_fuga,
byte-idéntico al de reparacion, a un fichero NUEVO — el juzgado original no
se toca ni se re-juzga en silencio.

Solo CPU (subprocesos del venv). Universo: tareas hard del frontier que
también están en reparacion.json (81).

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_frontier_rejuzga_sinfuga.py
        [--salida frontier_hard_sinfuga.json]
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

from b3_codigo import SALIDA, carga_lcb, juzga_lcb, tests_lcb
from b3_factorial import DESDE, HASTA


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="frontier_hard_sinfuga.json")
    args = ap.parse_args()

    rep = json.loads((SALIDA / "reparacion.json").read_text(encoding="utf-8"))
    rep_tareas = {m["tarea"] for m in rep["muestras"]}

    fro = json.loads((SALIDA / "frontier_resultados.json")
                     .read_text(encoding="utf-8"))
    originales = {m["tarea"]: m for m in fro["muestras"]}
    comunes = sorted(t for t, m in originales.items()
                     if m["dificultad"] == "hard" and t in rep_tareas)
    print(f"[rej] tareas hard comunes: {len(comunes)}")

    crudos = {}
    for nombre in ("frontier_60_raw.json", "frontier_138_raw.json"):
        d = json.loads((SALIDA / nombre).read_text(encoding="utf-8"))
        for m in d["muestras"]:
            crudos[str(m["id"])] = m.get("codigo") or ""

    pool = {str(t["task_id"]): t
            for t in carga_lcb(ficheros=("lcb_test5.jsonl", "lcb_test6.jsonl"))
            if DESDE <= t["fecha"] <= HASTA}

    destino = SALIDA / args.salida
    res = {"experimento": "frontier_hard_sinfuga",
           "diseno": "ANALISIS_GOAL_RESPONDIDO_20260801.md",
           "derivado_de": "frontier_60_raw.json + frontier_138_raw.json",
           "split": "tests_lcb sin_fuga=True, rng 20260730:<tarea> "
                    "(el de reparacion.json)",
           "muestras": []}
    if destino.exists():
        res = json.loads(destino.read_text(encoding="utf-8"))
    hechas = {m["tarea"] for m in res["muestras"]}

    cambian = 0
    for tid in comunes:
        if tid in hechas:
            continue
        t = pool.get(tid)
        if t is None:
            print(f"ABORTA: {tid} no está en el pool de la ventana.")
            sys.exit(2)
        code = crudos.get(tid, "")
        vis, oc = tests_lcb(t, random.Random(f"20260730:{tid}"), sin_fuga=True)
        ts = time.time()
        vis_ok, m_vis = juzga_lcb(code, t, vis)
        oc_ok, m_oc = juzga_lcb(code, t, oc, parar_al_fallar=True)
        pasa = oc_ok == len(oc) and len(oc) > 0
        antes = bool(originales[tid]["mio_pasa"])
        if pasa != antes:
            cambian += 1
        reg = {"tarea": tid, "celda": "frontier_opus5", "dificultad": "hard",
               "pasa_oc": pasa, "vis_ok": vis_ok, "vis_n": len(vis),
               "oc_ok": oc_ok, "oc_n": len(oc),
               "instrumento": "" if code else "sin_codigo",
               "juez_vis": m_vis, "juez_oc": m_oc,
               "mio_pasa_confuga": antes,
               "segundos_juicio": round(time.time() - ts, 1)}
        res["muestras"].append(reg)
        tmp = destino.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, destino)
        print(f"[rej] {tid:<12} sin_fuga={pasa} con_fuga={antes} "
              f"{'<< CAMBIA' if pasa != antes else ''} "
              f"({reg['segundos_juicio']}s)", flush=True)

    n = len(res["muestras"])
    ok = sum(1 for m in res["muestras"] if m["pasa_oc"])
    print(f"\n[rej] FIN {n} tareas: pasa_oc {ok}/{n}  veredictos que cambian "
          f"respecto al split con fuga: {cambian}  -> {destino}")


if __name__ == "__main__":
    main()
