# -*- coding: utf-8 -*-
"""b3_frontier_juzga.py — juzga las muestras frontier con MI arnés.

DISENO_REFERENCIA_FRONTIER_20260731.md (enmienda 1). Lee un JSON con
[{id, dificultad, codigo}] (lo que devolvió el workflow de subagentes) y lo
juzga EXACTAMENTE como b3_factorial juzgó oficial_low: mismo split de
visibles/ocultos (RNG determinista por tarea, SIN sin_fuga — el mismo del
factorial), mismo juez oficial con mis topes (8MB/120s, declarados como
estrato). Sin GPU: solo subprocesos CPU del venv.

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_frontier_juzga.py entrada.json
        [--salida frontier_resultados.json]

Acumula: si la salida ya existe, añade solo las tareas nuevas (las repetidas
ABORTAN: una tarea juzgada no se re-juzga en silencio).
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

from b3_codigo import SALIDA, carga_lcb, juzga_lcb, tests_lcb
from b3_factorial import DESDE, HASTA
from b3_oficial import casos_oficiales, juzga_oficial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada")
    ap.add_argument("--salida", default="frontier_resultados.json")
    args = ap.parse_args()

    entrada = Path(args.entrada)
    muestras = json.loads(entrada.read_text(encoding="utf-8"))
    if isinstance(muestras, dict):
        muestras = muestras.get("muestras", [])

    pool = {str(t["task_id"]): t
            for t in carga_lcb(ficheros=("lcb_test5.jsonl", "lcb_test6.jsonl"))
            if DESDE <= t["fecha"] <= HASTA}

    destino = SALIDA / args.salida
    res = {"experimento": "referencia_frontier",
           "diseno": "DISENO_REFERENCIA_FRONTIER_20260731.md (enmienda 1)",
           "modelo": "claude-opus-5 via subagentes Claude Code (plan)",
           "k": 1, "muestras": []}
    if destino.exists():
        res = json.loads(destino.read_text(encoding="utf-8"))
    hechas = {m["tarea"] for m in res["muestras"]}

    for m in muestras:
        tid = str(m["id"])
        if tid in hechas:
            print(f"ABORTA: {tid} ya está juzgada en {destino.name}; una "
                  f"tarea no se re-juzga en silencio.")
            sys.exit(2)
        t = pool.get(tid)
        if t is None:
            print(f"ABORTA: {tid} no está en el pool de la ventana.")
            sys.exit(2)
        # EL MISMO examen que factorial.json (b3_factorial._prepara)
        vis, oc = tests_lcb(t, random.Random(f"20260730:{tid}"))
        code = m.get("codigo") or ""
        ts = time.time()
        vis_ok, m_vis = juzga_lcb(code, t, vis)
        oc_ok, m_oc = juzga_lcb(code, t, oc, parar_al_fallar=True)
        oficiales = casos_oficiales(t)
        of_pasa, m_of = juzga_oficial(code, t, oficiales)
        reg = {
            "tarea": tid, "celda": "frontier_opus5",
            "dificultad": m.get("dificultad"),
            "mio_pasa": oc_ok == len(oc) and len(oc) > 0,
            "mio_vis_ok": vis_ok, "mio_vis_n": len(vis),
            "mio_oc_ok": oc_ok, "mio_oc_n": len(oc),
            "oficial_pasa": bool(of_pasa),
            "oficial_n_casos": len(oficiales),
            "instrumento": "" if code else "sin_codigo",
            "juez_mio": m_vis or m_oc, "juez_oficial": m_of,
            "segundos_juicio": round(time.time() - ts, 1),
            "chars": len(code),
        }
        res["muestras"].append(reg)
        tmp = destino.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        import os
        os.replace(tmp, destino)
        print(f"[fro] {tid:<12} {reg['dificultad'] or '?':<7} "
              f"mio={reg['mio_pasa']} of={reg['oficial_pasa']} "
              f"juez_of={reg['juez_oficial'] or 'ok'} "
              f"({reg['segundos_juicio']}s)", flush=True)

    n = len(res["muestras"])
    mio = sum(1 for x in res["muestras"] if x["mio_pasa"])
    ofi = sum(1 for x in res["muestras"] if x["oficial_pasa"])
    print(f"\n[fro] total {n}: juez MIO {mio}/{n}  juez OFICIAL {ofi}/{n} "
          f"-> {destino}")


if __name__ == "__main__":
    main()
