#!/usr/bin/env python
"""
b2_diagnostico_por_pagina.py — ¿cuántos checks fallan A LA VEZ, y de qué tipo?

PREREG_ADAPTADOR_ANTIINVENCION_20260730. Cero GPU.

POR QUÉ. La sonda del bug de forma dio **0.0 pts**: arreglar el 41% de los
checks fallidos no cambió ni un veredicto, porque el veredicto es un **AND** y
a cada página le sobran checks malos de otros tipos. Eso deja una pregunta
accionable que la taxonomía por CHECK no puede responder:

    ¿cuántos checks críticos falla cada página sana, y de cuántas categorías
    distintas? ¿Hay una cola corta (arreglar 2 tipos bastaría) o larga?

Es la diferencia entre "esto se arregla" y "esto hay que rehacerlo".
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b2_taxonomia_checks import clasificar, _ideas                    # noqa: E402

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SALIDA = GENERADOS / "b2_contratos_ampliado"


def main() -> int:
    juicios = json.loads((SALIDA / "juicios.json").read_text(encoding="utf-8"))
    ideas = _ideas()

    # pasos por (tarea, nombre) para poder clasificar cada check fallido
    pasos = {}
    for f in json.loads((SALIDA / "indice.json").read_text(
            encoding="utf-8"))["filas"]:
        if not f["ok"]:
            continue
        corpus, carpeta = f["pagina"].split("/", 1)
        c = json.loads((GENERADOS / corpus / carpeta / "contrato_interno.json")
                       .read_text(encoding="utf-8"))
        for p in c.get("pasos", []):
            pasos.setdefault((f["tarea"], p.get("nombre")), p)

    n_fallos, n_tipos = [], []
    tipos_totales = Counter()
    por_pagina = []
    for f in juicios["filas"]:
        if not f.get("gt") or not f.get("detalle"):
            continue                       # solo páginas SANAS
        malos = [c for c in f["detalle"] if c["critico"] and not c["ok"]]
        cats = Counter()
        for c in malos:
            p = pasos.get((f["tarea"], c["n"]))
            cats[clasificar(p, ideas.get(f["tarea"], "")) if p else "NO_HALLADO"] += 1
        n_fallos.append(len(malos))
        n_tipos.append(len(cats))
        tipos_totales.update(cats)
        por_pagina.append((f["tarea"], len(malos), len(cats)))

    n = len(n_fallos)
    print(f"PAGINAS SANAS analizadas: {n}\n")
    print("checks CRITICOS que fallan por pagina:")
    d = Counter(n_fallos)
    for k in sorted(d):
        print(f"  {k:2d} fallos : {d[k]:3d} paginas  {'#'*d[k]}")
    print(f"  mediana {sorted(n_fallos)[n//2]}   media "
          f"{sum(n_fallos)/max(1,n):.1f}   maximo {max(n_fallos)}")

    print("\nCATEGORIAS DISTINTAS que fallan a la vez en la misma pagina:")
    d2 = Counter(n_tipos)
    for k in sorted(d2):
        print(f"  {k} categoria(s) : {d2[k]:3d} paginas")

    print(f"\nreparto de los {sum(tipos_totales.values())} checks criticos "
          f"fallidos:")
    for c, k in tipos_totales.most_common():
        print(f"  {c:24s} {k:4d} ({100*k/max(1,sum(tipos_totales.values())):4.1f}%)")

    # simulacion: ¿cuantas paginas se salvarian arreglando los N tipos top?
    print("\nSIMULACION — paginas sanas que APROBARIAN si se arreglaran "
          "por completo los tipos indicados:")
    orden = [c for c, _ in tipos_totales.most_common()]
    for i in range(1, len(orden) + 1):
        arreglados = set(orden[:i])
        salvadas = 0
        for f in juicios["filas"]:
            if not f.get("gt") or not f.get("detalle"):
                continue
            malos = [c for c in f["detalle"] if c["critico"] and not c["ok"]]
            resto = 0
            for c in malos:
                p = pasos.get((f["tarea"], c["n"]))
                cat = clasificar(p, ideas.get(f["tarea"], "")) if p else "NO_HALLADO"
                if cat not in arreglados:
                    resto += 1
            salvadas += (resto == 0)
        print(f"  arreglando {i} tipo(s) {str(orden[:i])[:52]:54s} "
              f"-> {salvadas:3d}/{n} paginas ({100*salvadas/max(1,n):.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
