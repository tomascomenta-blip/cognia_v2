#!/usr/bin/env python
"""
b2_etiqueta_debil.py — el DATASET del adaptador anti-invención, sin GPU.

PREREG_ADAPTADOR_ANTIINVENCION_20260730 (paso 3 del orden de ejecución).

LA ETIQUETA. Un check que exige un valor **que el enunciado no fija** no lo
acierta ninguna implementación correcta: **falla en TODAS las páginas SANAS de
su enunciado**. Uno correcto solo falla en las malas. Eso da una etiqueta
automática:

    INVENTADO-candidato : falla en todas las paginas sanas del enunciado
    CORRECTO-candidato  : pasa en todas
    MIXTO               : ni una cosa ni la otra (se excluye)

Hasta hoy esto solo se podía calcular sobre **4 enunciados**; con los
contratos generados sobre páginas congeladas son **21**, y el
leave-one-task-out del adaptador pasa a tener 21 grupos.

LO QUE ESTA ETIQUETA CONFUNDE, y por eso NO se entrena a ciegas con ella
(está declarado en el prereg): mezcla (a) valor inventado —lo que queremos—,
(b) check correcto que las referencias no cubren, y (c) **ruido puro de API**:
una aserción de `texto` sobre un `<input>` falla SIEMPRE porque `innerText` de
un campo es vacío (medido: 55/55). El tipo (c) se marca aquí de forma
automática para poder excluirlo; (a) y (b) siguen exigiendo auditoría a mano.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SALIDA = GENERADOS / "b2_contratos_ampliado"

# Firma del ruido de API tipo (c): el nombre del check delata que compara el
# TEXTO de algo que en realidad es un campo de formulario.
RE_RUIDO_INPUT = re.compile(r"\b(input|campo|casilla|textarea|valor del campo)\b",
                            re.I)


def main() -> int:
    juicios = json.loads((SALIDA / "juicios.json").read_text(encoding="utf-8"))
    filas = [f for f in juicios["filas"]
             if f.get("detalle") and f.get("gt") is not None]
    if not filas:
        sys.exit("sin juicios con detalle: corre antes b2_j_ampliado.py")

    # (tarea, nombre_del_check) -> [(ok, gt_sana, critico)]
    obs = defaultdict(list)
    for f in filas:                                   # DIAGONAL
        for c in f["detalle"]:
            obs[(f["tarea"], c["n"])].append((bool(c["ok"]), bool(f["gt"]),
                                              bool(c["critico"])))

    # MATRIZ CRUZADA: el mismo check visto contra las demás páginas de su
    # enunciado. Sin esto, casi todos los checks se observan UNA vez y se
    # caen por n<2 (medido: 501 de 653).
    f_cruz = SALIDA / "matriz_cruzada.json"
    n_cruz = 0
    if f_cruz.is_file():
        for celda in json.loads(f_cruz.read_text(encoding="utf-8"))["celdas"]:
            for c in celda.get("detalle") or []:
                obs[(celda["tarea"], c["n"])].append(
                    (bool(c["ok"]), bool(celda["gt_pagina"]),
                     bool(c["critico"])))
                n_cruz += 1
        print(f"(matriz cruzada: {n_cruz} observaciones extra)\n")

    inventado, correcto, mixto, sin_n = [], [], [], 0
    for (tarea, nombre), vs in obs.items():
        sanas = [ok for ok, gt, _ in vs if gt]
        if len(sanas) < 2:                 # sin al menos 2 sanas no se decide
            sin_n += 1
            continue
        critico = any(cr for _, _, cr in vs)
        item = {"tarea": tarea, "check": nombre, "critico": critico,
                "n_sanas": len(sanas), "ruido_api": bool(RE_RUIDO_INPUT.search(nombre))}
        if not any(sanas):
            inventado.append(item)
        elif all(sanas):
            correcto.append(item)
        else:
            mixto.append(item)

    total = len(inventado) + len(correcto) + len(mixto)
    print(f"checks unicos evaluables : {total}   (descartados por n<2: {sin_n})")
    print(f"  INVENTADO-candidato    : {len(inventado):4d}  "
          f"({100*len(inventado)/max(1,total):.1f}%)")
    print(f"  CORRECTO-candidato     : {len(correcto):4d}  "
          f"({100*len(correcto)/max(1,total):.1f}%)")
    print(f"  MIXTO (se excluye)     : {len(mixto):4d}  "
          f"({100*len(mixto)/max(1,total):.1f}%)")
    ruido = sum(1 for i in inventado if i["ruido_api"])
    print(f"\n  de los INVENTADO, con firma de RUIDO DE API: {ruido} "
          f"({100*ruido/max(1,len(inventado)):.1f}%) -> excluibles sin auditoria")
    print(f"  quedan como candidatos REALES a valor inventado: "
          f"{len(inventado)-ruido}")

    por_tarea = defaultdict(lambda: [0, 0])
    for i in inventado:
        por_tarea[i["tarea"]][0] += 1
    for c in correcto:
        por_tarea[c["tarea"]][1] += 1
    print(f"\n{'enunciado':24s} {'inventado':>10s} {'correcto':>9s}")
    print("-" * 46)
    for t in sorted(por_tarea):
        a, b = por_tarea[t]
        print(f"{t:24s} {a:10d} {b:9d}")
    print("-" * 46)
    print(f"{'ENUNCIADOS':24s} {len(por_tarea):10d}")

    destino = SALIDA / "dataset_etiqueta_debil.json"
    destino.write_text(json.dumps(
        {"inventado": inventado, "correcto": correcto, "mixto": mixto},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {destino}")
    print("\nRECORDATORIO del prereg: esta etiqueta NO basta para entrenar a "
          "ciegas.\nMezcla valor inventado, check correcto no cubierto y ruido "
          "de API; solo\nel ultimo se separa automaticamente. Los otros dos "
          "exigen auditoria a mano.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
