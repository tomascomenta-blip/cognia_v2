#!/usr/bin/env python
"""
b2_j_contrato_interno.py — ¿cuánto DISCRIMINA el contrato interno, de verdad?

PREREG_PODA_CHECKS_20260730 (resultado 4). Cero GPU: solo lee lo congelado.

POR QUÉ ESTE SCRIPT. El repo venía diciendo "el contrato interno está al nivel
del azar" a partir de tasas de FP/FN medidas por separado. Medido con la
métrica correcta sobre la DIAGONAL (el contrato juzgando su propia página, que
es lo que el sistema vivo ejecuta) sale algo más fuerte: **Youden J = −1.1**,
o sea aprueba sanas y rotas en la MISMA proporción. Aquí se comprueba si ese
número aguanta fuera de las 4 tareas donde se midió.

Youden J = 100 − ACUSA_SANOS − DEJA_PASAR. J=0 es no informativo; J=100
perfecto; J<0 es peor que la moneda. Se usa J y no una tasa suelta porque
CUALQUIER transformación que solo relaja (o solo endurece) mueve las dos tasas
a la vez y cruza cualquier umbral de una sola — la lección que mató la poda.

El sello del lazo (`sello_lazo`) es APROBADO/FALLIDO según el contrato
autogenerado. El ground truth es `estricto` (original ∧ held-out a mano) si
está, y si no `aprobado` (contrato original a mano).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"


def _filas(res: dict) -> list:
    for clave in ("muestras", "celdas", "ensayos"):
        if isinstance(res.get(clave), list) and res[clave]:
            return res[clave]
    return []


def _gt(m: dict):
    if m.get("estricto") is not None and m.get("aprobado_heldout") is not None:
        return bool(m["estricto"])
    for k in ("aprobado", "aprobado_orig"):
        if m.get(k) is not None:
            return bool(m[k])
    return None


def main() -> int:
    print(f"{'corpus':38s} {'tareas':>6s} {'n':>4s} {'sanas%':>7s} "
          f"{'rotas%':>7s} {'ACUSA':>6s} {'DEJA':>6s} {'J':>6s}")
    print("-" * 86)
    tot = {"sa": 0, "sd": 0, "ra": 0, "rd": 0, "tareas": set()}

    for d in sorted(GENERADOS.glob("*/resultados.json")):
        try:
            res = json.loads(d.read_text(encoding="utf-8"))
        except Exception:
            continue
        sa = sd = ra = rd = 0
        tareas = set()
        for m in _filas(res):
            if not isinstance(m, dict):
                continue
            sello = m.get("sello_lazo")
            if sello not in ("APROBADO", "FALLIDO"):
                continue
            g = _gt(m)
            if g is None:
                continue
            ok = sello == "APROBADO"
            tareas.add(m.get("tarea", "?"))
            if g:
                sd += 1; sa += ok
            else:
                rd += 1; ra += ok
        if sd < 3 or rd < 3:            # sin ambas clases no hay J que medir
            continue
        acusa = 100 * (1 - sa / sd)
        deja = 100 * (ra / rd)
        print(f"{d.parent.name:38s} {len(tareas):6d} {sd+rd:4d} "
              f"{100*sa/sd:6.1f}% {100*ra/rd:6.1f}% "
              f"{acusa:5.1f} {deja:5.1f} {100-acusa-deja:+6.1f}")
        tot["sa"] += sa; tot["sd"] += sd
        tot["ra"] += ra; tot["rd"] += rd
        tareas and tot["tareas"].update(tareas)

    if tot["sd"] and tot["rd"]:
        acusa = 100 * (1 - tot["sa"] / tot["sd"])
        deja = 100 * (tot["ra"] / tot["rd"])
        print("-" * 86)
        print(f"{'AGREGADO':38s} {len(tot['tareas']):6d} "
              f"{tot['sd']+tot['rd']:4d} "
              f"{100*tot['sa']/tot['sd']:6.1f}% {100*tot['ra']/tot['rd']:6.1f}% "
              f"{acusa:5.1f} {deja:5.1f} {100-acusa-deja:+6.1f}")
        print(f"\ntareas distintas cubiertas: {sorted(tot['tareas'])}")
        print("\nLectura: J cercano a 0 = el contrato interno aprueba sanas y "
              "rotas en la misma proporcion, o sea NO INFORMA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
