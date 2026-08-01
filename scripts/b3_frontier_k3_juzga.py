# -*- coding: utf-8 -*-
"""
b3_frontier_k3_juzga.py — juzga las muestras s=2/s=3 del frontier (enmienda 5).

DISENO_REFERENCIA_FRONTIER_20260731.md, enmienda 5: varianza del denominador.
Lee frontier_k3_raw.json ([{id, s, dificultad, codigo}]) y juzga cada muestra
con MI juez bajo LOS DOS splits:
  - `pasa_oc` con el split del factorial (con fuga) — para el apareado contra
    oficial_low, idéntico al de las s=1 firmadas;
  - `pasa_oc_sinfuga` — para el informe del goal (el split de reparacion).
El juez oficial-con-mis-topes NO se corre para s=2,3 (enmienda 5, declarado).

Clave de reanudación: (tarea, s). Los ficheros de s=1 no se tocan.

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_frontier_k3_juzga.py
        [--entrada frontier_k3_raw.json] [--salida frontier_k3_resultados.json]
"""
from __future__ import annotations

import argparse
import hashlib
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
    ap.add_argument("--entrada", default="frontier_k3_raw.json")
    ap.add_argument("--salida", default="frontier_k3_resultados.json")
    args = ap.parse_args()

    d = json.loads((SALIDA / args.entrada).read_text(encoding="utf-8"))
    muestras = d["muestras"] if isinstance(d, dict) else d

    pool = {str(t["task_id"]): t
            for t in carga_lcb(ficheros=("lcb_test5.jsonl", "lcb_test6.jsonl"))
            if DESDE <= t["fecha"] <= HASTA}

    destino = SALIDA / args.salida
    res = {"experimento": "frontier_k3",
           "diseno": "DISENO_REFERENCIA_FRONTIER_20260731.md (enmienda 5)",
           "modelo": "claude-opus-5 via subagentes Claude Code (plan)",
           "muestras": []}
    if destino.exists():
        res = json.loads(destino.read_text(encoding="utf-8"))
    hechas = {(m["tarea"], m["s"]) for m in res["muestras"]}

    # el fichero de entrada NO puede traer duplicados (tarea,s): un duplicado
    # es señal de workflow relanzado con colección rota, y juzgar los dos en
    # silencio promediaría 4 registros donde el prereg dice 3 (BLOQUEA de la
    # revisión adversarial del 2026-08-01). Se valida ANTES de juzgar nada.
    vistos = set()
    for m in muestras:
        clave = (str(m["id"]), int(m["s"]))
        if clave in vistos:
            print(f"ABORTA: ({clave[0]}, s={clave[1]}) duplicado en "
                  f"{args.entrada}; la colección del raw está rota.")
            sys.exit(2)
        vistos.add(clave)

    hard_ids = {m["tarea"] for m in json.loads(
        (SALIDA / "frontier_resultados.json").read_text(encoding="utf-8"))
        ["muestras"] if m["dificultad"] == "hard"}

    for m in muestras:
        tid, s = str(m["id"]), int(m["s"])
        if (tid, s) in hechas:
            continue
        hechas.add((tid, s))
        if s not in (2, 3):
            print(f"ABORTA: s={s} fuera de la enmienda 5 (solo 2 y 3).")
            sys.exit(2)
        if tid not in hard_ids:
            print(f"ABORTA: {tid} no está en las 83 hard de la enmienda 5.")
            sys.exit(2)
        t = pool.get(tid)
        if t is None:
            print(f"ABORTA: {tid} no está en el pool de la ventana.")
            sys.exit(2)
        code = m.get("codigo") or ""
        ts = time.time()
        vis, oc = tests_lcb(t, random.Random(f"20260730:{tid}"))
        vis_ok, m_vis = juzga_lcb(code, t, vis)
        oc_ok, m_oc = juzga_lcb(code, t, oc, parar_al_fallar=True)
        _, oc_sf = tests_lcb(t, random.Random(f"20260730:{tid}"), sin_fuga=True)
        oc_sf_ok, m_sf = juzga_lcb(code, t, oc_sf, parar_al_fallar=True)
        reg = {"tarea": tid, "s": s, "celda": "frontier_opus5",
               "dificultad": m.get("dificultad"),
               "pasa_oc": oc_ok == len(oc) and len(oc) > 0,
               "vis_ok": vis_ok, "vis_n": len(vis),
               "oc_ok": oc_ok, "oc_n": len(oc),
               "pasa_oc_sinfuga": oc_sf_ok == len(oc_sf) and len(oc_sf) > 0,
               "oc_sinfuga_ok": oc_sf_ok, "oc_sinfuga_n": len(oc_sf),
               "instrumento": m.get("instrumento")
                              or ("" if code else "sin_codigo"),
               "juez_vis": m_vis, "juez_oc": m_oc, "juez_oc_sinfuga": m_sf,
               "segundos_juicio": round(time.time() - ts, 1),
               "chars": len(code),
               # provenance: el skip de reanudación no re-compara el código;
               # el hash permite auditar que el veredicto corresponde al raw
               "sha256_codigo": hashlib.sha256(
                   code.encode("utf-8")).hexdigest()[:16]}
        res["muestras"].append(reg)
        tmp = destino.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, destino)
        print(f"[k3] {tid:<12} s={s} oc={reg['pasa_oc']} "
              f"sf={reg['pasa_oc_sinfuga']} "
              f"inst={reg['instrumento'] or '-'} "
              f"({reg['segundos_juicio']}s)", flush=True)

    n = len(res["muestras"])
    ok = sum(1 for x in res["muestras"] if x["pasa_oc"])
    print(f"\n[k3] FIN {n} muestras juzgadas: pasa_oc {ok}/{n} -> {destino}")


if __name__ == "__main__":
    main()
