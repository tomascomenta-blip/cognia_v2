#!/usr/bin/env python
"""
b2_bon_vs_azar.py — ¿el BoN SELECCIONA, o solo evita s1?

PREREG_MEDOIDE_20260730 (hallazgo de la réplica). Cero GPU.

POR QUÉ. Midiendo el medoide salió un dato que no era sobre el medoide:
**elegir una muestra AL AZAR bate sistemáticamente al control s1** (neto medio
+1.16 a +2.70 según el conjunto, siempre positivo). Si `s1` es peor que una
muestra cualquiera, entonces parte de la ganancia que el BoN se apunta contra
el control podría venir de **no usar s1**, no de seleccionar bien.

Este script separa las dos cosas sobre las corridas congeladas:

    CONTROL  = s1                      (la referencia que se ha usado siempre)
    AZAR     = una muestra al azar     (la referencia HONESTA)
    BoN      = la que eligió el selector held-out

Si BoN ≈ AZAR, el selector no está aportando: la ganancia es del muestreo.
Si BoN > AZAR con claridad, el selector sí selecciona.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SEMILLA = 20260730
N_NULO = 10000


def _corpus_gate(raiz: Path) -> list:
    """[(estrictos:set, disponibles:list, elegida_bon:int, s1:bool|None)]"""
    res = json.loads((raiz / "resultados.json").read_text(encoding="utf-8"))
    salida = []
    for e in res["ensayos"]:
        sel = {int(m["s"]): m for m in (e.get("bon") or {}).get("muestras", [])}
        disp, estr = [], set()
        for k, v in (e.get("orig") or {}).items():
            s = int(k)
            if not (raiz / f"{e['tarea']}__r{e['rep']}" / f"s{s}"
                    / "index.html").is_file():
                continue
            disp.append(s)
            if v.get("aprobado") and sel.get(s, {}).get("aprobado_sel"):
                estr.add(s)
        if not disp:
            continue
        elegida = (e.get("bon") or {}).get("elegida_s") or e.get("elegida_s")
        salida.append({
            "ensayo": f"{e['tarea']}:r{e['rep']}", "disp": sorted(disp),
            "estrictos": sorted(estr),
            "bon": int(elegida) if elegida else None,
            "s1": (1 in estr) if 1 in disp else None})
    return salida


def _corpus_duro(raiz: Path) -> list:
    """El banco duro: el veredicto estricto vive en goal.json."""
    goal = json.loads((raiz / "goal.json").read_text(encoding="utf-8"))
    salida = []
    for f in goal["filas"]:
        estr = set(f.get("estrictos") or [])
        disp = sorted({1, 2, 3, 4})
        salida.append({
            "ensayo": f"{f['tarea']}:{raiz.name}", "disp": disp,
            "estrictos": sorted(estr), "bon": f.get("elegida_s"),
            "s1": 1 in estr})
    return salida


def analizar(nombre: str, ens: list) -> None:
    apar = [e for e in ens if e["s1"] is not None and e["bon"]]
    n = len(apar)
    if n < 3:
        return
    ctrl = sum(1 for e in apar if e["s1"])
    bon = sum(1 for e in apar if e["bon"] in e["estrictos"])
    techo = sum(1 for e in apar if e["estrictos"])

    rng = random.Random(SEMILLA)
    azar = []
    for _ in range(N_NULO):
        azar.append(sum(1 for e in apar
                        if rng.choice(e["disp"]) in e["estrictos"]))
    azar.sort()
    media = sum(azar) / len(azar)
    p95 = azar[int(0.95 * len(azar))]
    p_azar = sum(1 for x in azar if x >= bon) / len(azar)

    print(f"\n{'='*70}\n{nombre}  (n={n} ensayos apareados)\n{'='*70}")
    print(f"  CONTROL (s1)  {ctrl:3d}/{n}   ({100*ctrl/n:.1f}%)")
    print(f"  AZAR          {media:6.2f}/{n}   ({100*media/n:.1f}%)  "
          f"p95={p95}  max={azar[-1]}")
    print(f"  BoN           {bon:3d}/{n}   ({100*bon/n:.1f}%)")
    print(f"  TECHO         {techo:3d}/{n}")
    print(f"  --> ganancia del BoN sobre el CONTROL: {bon-ctrl:+d}")
    print(f"  --> ganancia del BoN sobre el AZAR:    {bon-media:+.2f}")
    print(f"  --> P(azar >= BoN) = {p_azar:.4f}   "
          f"{'BoN SUPERA el p95' if bon > p95 else 'BoN NO supera el p95'}")
    if ctrl < media:
        print(f"  [!] el control esta POR DEBAJO del azar "
              f"({ctrl} < {media:.2f}): medir contra s1 sobrestima")


def main() -> int:
    analizar("GATE del modo BoN (b2_bon_gate_v2)",
             _corpus_gate(GENERADOS / "b2_bon_gate_v2"))
    for d in ("b2_bon_heldout_duro", "b2_bon_heldout_duro_r2"):
        p = GENERADOS / d
        if (p / "goal.json").is_file():
            analizar(f"GOAL banco duro ({d})", _corpus_duro(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
