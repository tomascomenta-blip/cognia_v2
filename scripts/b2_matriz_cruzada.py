#!/usr/bin/env python
"""
b2_matriz_cruzada.py — cada contrato contra TODAS las páginas de su enunciado.

PREREG_ADAPTADOR_ANTIINVENCION_20260730 (paso 3). Cero GPU.

POR QUÉ NO BASTA LA DIAGONAL. La etiqueta débil ("este check falla en todas
las páginas SANAS de su enunciado") necesita ver el mismo check contra
**varias** páginas. Juzgando cada página solo con su propio contrato, un check
se observa **una vez**: medido, 501 de 653 checks quedaron sin n suficiente y
el dataset se quedó en 152.

La matriz cruzada resuelve eso sin generar nada nuevo: el contrato de la
muestra i se ejecuta contra las páginas j del MISMO enunciado. Cada check pasa
así de 1 observación a tantas como páginas tenga su tarea.

Es la misma forma que ya usó `b2_consenso2` (de donde salieron los 548 checks
sobre 4 enunciados); aquí se aplica a los 17 enunciados nuevos.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from cognia.presupuesto_pared import con_presupuesto, PresupuestoAgotado  # noqa: E402
from cognia.program_creator import juez_ejecutable                        # noqa: E402

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SALIDA = GENERADOS / "b2_contratos_ampliado"
PRESUPUESTO = 300


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reanudar", action="store_true")
    ap.add_argument("--tope-por-tarea", type=int, default=8,
                    help="paginas por enunciado (acota el coste cuadratico)")
    args = ap.parse_args(argv)

    juicios = json.loads((SALIDA / "juicios.json").read_text(encoding="utf-8"))
    # por enunciado: paginas con GT conocido y con contrato en disco
    por_tarea = defaultdict(list)
    for f in juicios["filas"]:
        if f.get("gt") is None:
            continue
        corpus, carpeta = f["pagina"].split("/", 1)
        d = GENERADOS / corpus / carpeta
        if not (d / "contrato_interno.json").is_file():
            continue
        por_tarea[f["tarea"]].append({"pagina": f["pagina"], "dir": d,
                                      "gt": bool(f["gt"])})

    f_out = SALIDA / "matriz_cruzada.json"
    res = (json.loads(f_out.read_text(encoding="utf-8"))
           if args.reanudar and f_out.is_file() else {"celdas": []})
    hechas = {(c["contrato"], c["pagina"]) for c in res["celdas"]}

    trabajos = []
    for tarea, pgs in sorted(por_tarea.items()):
        pgs = pgs[:args.tope_por_tarea]
        for ci in pgs:
            for pj in pgs:
                if ci["pagina"] == pj["pagina"]:
                    continue          # la diagonal ya está medida
                if (ci["pagina"], pj["pagina"]) in hechas:
                    continue
                trabajos.append((tarea, ci, pj))

    print(f"{len(trabajos)} celdas cruzadas · {len(por_tarea)} enunciados",
          flush=True)
    t0 = time.time()
    for k, (tarea, ci, pj) in enumerate(trabajos, 1):
        contrato = json.loads((ci["dir"] / "contrato_interno.json")
                              .read_text(encoding="utf-8"))
        try:
            v = con_presupuesto(PRESUPUESTO, juez_ejecutable.juzgar_web,
                                pj["dir"] / "index.html", contrato)
            detalle = [{"n": c.nombre, "ok": c.ok, "critico": c.critico}
                       for c in v.checks]
            aprueba = bool(v.aprobado)
        except (PresupuestoAgotado, Exception) as exc:      # noqa: B014
            detalle, aprueba = [], None
        res["celdas"].append({
            "tarea": tarea, "contrato": ci["pagina"], "pagina": pj["pagina"],
            "gt_pagina": pj["gt"], "aprueba": aprueba, "detalle": detalle})
        if k % 25 == 0 or k == len(trabajos):
            f_out.write_text(json.dumps(res, ensure_ascii=False),
                             encoding="utf-8")
            print(f"[{k}/{len(trabajos)}] {(time.time()-t0)/60:.1f} min",
                  flush=True)
    f_out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"TOTAL {len(res['celdas'])} celdas en {(time.time()-t0)/60:.1f} min",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
