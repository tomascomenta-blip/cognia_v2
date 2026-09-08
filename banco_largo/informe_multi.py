# -*- coding: utf-8 -*-
"""informe_multi.py -- compara N rondas del banco en una sola tabla (brazos de configuracion).

Uso:  python -m banco_largo.informe_multi cfg_base cfg_esfuerzo_alto ... [--salida X.md]
Reusa cargar_ronda/agregados de informe.py: mismas capas, mismos numeros.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from banco_largo.informe import FILAS, _fmt, agregados, cargar_ronda

RAIZ = Path(__file__).resolve().parent / "corridas"


def _tok_s(regs) -> float:
    xs = []
    for r in regs.values():
        t = (r.get("telemetria") or {})
        seg, sal = t.get("segundos"), t.get("tokens_salida")
        if isinstance(seg, (int, float)) and seg > 0 and isinstance(sal, (int, float)) and sal > 0:
            xs.append(sal / seg)
    return round(sum(xs) / len(xs), 1) if xs else 0.0


def tabla(rondas: list) -> str:
    datos = {}
    for nombre in rondas:
        regs = cargar_ronda(RAIZ / nombre)
        datos[nombre] = (agregados(regs), regs)
    cab = "| Metrica | " + " | ".join(rondas) + " |"
    sep = "|---|" + "---|" * len(rondas)
    filas = [cab, sep]
    for etiqueta, clave, tipo in FILAS:
        filas.append("| %s | %s |" % (etiqueta, " | ".join(_fmt(datos[r][0], clave, tipo) for r in rondas)))
    filas.append("| tok/s medios (salida) | %s |" % " | ".join(str(_tok_s(datos[r][1])) for r in rondas))
    # detalle por tarea: global y funcionalidad
    tareas = sorted({t for r in rondas for t in datos[r][1]})
    filas.append("")
    filas.append("| Tarea | " + " | ".join("%s global/func" % r for r in rondas) + " |")
    filas.append(sep)
    for t in tareas:
        celdas = []
        for r in rondas:
            reg = datos[r][1].get(t)
            if not reg:
                celdas.append("-")
                continue
            ev = reg["evaluacion"]
            f = (ev["capas"].get("funcionalidad") or {}).get("nota")
            celdas.append("%.2f / %s" % (ev["global"], ("%.2f" % f) if isinstance(f, (int, float)) else "?"))
        filas.append("| %s | %s |" % (t, " | ".join(celdas)))
    return "\n".join(filas)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="banco_largo.informe_multi")
    ap.add_argument("rondas", nargs="+")
    ap.add_argument("--salida", default="")
    a = ap.parse_args(argv)
    existentes = [r for r in a.rondas if (RAIZ / r).is_dir()]
    faltan = [r for r in a.rondas if r not in existentes]
    txt = "# Brazos de configuracion -- banco de tareas largas\n\n"
    if faltan:
        txt += "Rondas ausentes: %s\n\n" % ", ".join(faltan)
    txt += tabla(existentes) + "\n"
    if a.salida:
        Path(a.salida).write_text(txt, encoding="utf-8")
    sys.stdout.write(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
