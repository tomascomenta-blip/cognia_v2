# -*- coding: utf-8 -*-
"""informe.py -- compara dos rondas del banco y saca la tabla ANTES/DESPUES.

No inventa metricas: todas salen de los JSON que dejo el runner. Una tarea que
no se ejecuto sale como 'no ejecutada', nunca como cero disimulado.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def cargar_ronda(dirr):
    dirr = Path(dirr)
    regs = {}
    for p in sorted(dirr.glob("*.json")):
        if p.name == "corrida.json":
            continue
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            regs[r["id"]] = r
        except Exception:
            continue
    return regs


def _tel(r, clave, defecto=0):
    v = (r.get("telemetria") or {}).get(clave)
    return defecto if v is None else v


def agregados(regs):
    if not regs:
        return {}
    n = len(regs)
    vals = list(regs.values())
    vered = {}
    for r in vals:
        v = r["evaluacion"]["veredicto"]
        vered[v] = vered.get(v, 0) + 1

    def media(f):
        xs = [f(r) for r in vals]
        xs = [x for x in xs if isinstance(x, (int, float))]
        return round(sum(xs) / len(xs), 3) if xs else 0.0

    def capa(nombre):
        xs = [(r["evaluacion"]["capas"].get(nombre) or {}).get("nota") for r in vals]
        xs = [x for x in xs if isinstance(x, (int, float))]
        return round(sum(xs) / len(xs), 3) if xs else None

    pruebas_tot = sum(r["evaluacion"]["n_pruebas"] for r in vals)
    pruebas_ok = sum(r["evaluacion"]["n_pasadas"] for r in vals)
    return {
        "tareas": n,
        "completadas": vered.get("completado", 0),
        "parciales": vered.get("parcial", 0),
        "esqueletos": vered.get("esqueleto", 0),
        "truncadas": sum(1 for r in vals if _tel(r, "truncado", False)),
        "fallos": vered.get("fallo", 0) + vered.get("error_evaluador", 0),
        "productos_funcionales": sum(
            1 for r in vals
            if ((r["evaluacion"]["capas"].get("funcionalidad") or {}).get("nota") or 0) >= 0.8),
        "productos_incompletos": sum(
            1 for r in vals
            if 0 < ((r["evaluacion"]["capas"].get("funcionalidad") or {}).get("nota") or 0) < 0.8),
        "productos_muertos": sum(
            1 for r in vals
            if ((r["evaluacion"]["capas"].get("funcionalidad") or {}).get("nota") or 0) == 0),
        "tests_superados": pruebas_ok,
        "tests_totales": pruebas_tot,
        "tasa_tests": round(pruebas_ok / pruebas_tot, 3) if pruebas_tot else 0.0,
        "nota_global_media": media(lambda r: r["evaluacion"]["global"]),
        "capa_completitud": capa("completitud"),
        "capa_funcionalidad": capa("funcionalidad"),
        "capa_calidad": capa("calidad"),
        "capa_robustez": capa("robustez"),
        "capa_integridad": capa("integridad"),
        "capa_entregabilidad": capa("entregabilidad"),
        "capa_verificacion": capa("verificacion"),
        "capa_regresion": capa("regresion"),
        "duracion_media_s": media(lambda r: _tel(r, "segundos")),
        "tokens_medios": media(lambda r: _tel(r, "tokens_totales")),
        "tokens_salida_medios": media(lambda r: _tel(r, "tokens_salida")),
        "pasos_medios": media(lambda r: _tel(r, "pasos")),
        "tool_calls_medias": media(lambda r: _tel(r, "n_tool_calls")),
        "errores_criticos": sum(_tel(r, "ejecuciones_fallo") for r in vals),
        "errores_reparados": sum(_tel(r, "errores_reparados") for r in vals),
        "agente_dice_completo": sum(1 for r in vals if _tel(r, "agente_dice_completo", False)),
    }


FILAS = [
    ("tareas evaluadas", "tareas", "n"),
    ("tareas completadas", "completadas", "n"),
    ("tareas parciales", "parciales", "n"),
    ("tareas truncadas", "truncadas", "n"),
    ("productos funcionales (func>=0,8)", "productos_funcionales", "n"),
    ("productos incompletos", "productos_incompletos", "n"),
    ("productos muertos (func=0)", "productos_muertos", "n"),
    ("tests superados / totales", "tests_superados", "frac"),
    ("tasa de tests", "tasa_tests", "f"),
    ("nota global media", "nota_global_media", "f"),
    ("  A completitud", "capa_completitud", "f"),
    ("  B funcionalidad", "capa_funcionalidad", "f"),
    ("  C calidad", "capa_calidad", "f"),
    ("  D robustez", "capa_robustez", "f"),
    ("  E integridad", "capa_integridad", "f"),
    ("  F entregabilidad", "capa_entregabilidad", "f"),
    ("  G verificacion propia", "capa_verificacion", "f"),
    ("  H regresiones", "capa_regresion", "f"),
    ("errores en tool calls", "errores_criticos", "n"),
    ("errores recuperados", "errores_reparados", "n"),
    ("duracion media (s)", "duracion_media_s", "n"),
    ("tokens medios por tarea", "tokens_medios", "n"),
    ("pasos medios", "pasos_medios", "f"),
    ("tool calls medias", "tool_calls_medias", "f"),
    ("el agente dijo 'completo'", "agente_dice_completo", "n"),
]


def _fmt(a, clave, tipo):
    v = a.get(clave)
    if v is None:
        return "-"
    if tipo == "frac":
        return "%s / %s" % (v, a.get("tests_totales", "?"))
    if tipo == "f":
        return "%.3f" % v if isinstance(v, (int, float)) else str(v)
    return str(v)


def tabla(antes, despues, nombre_a="antes", nombre_d="despues"):
    a, d = agregados(antes), agregados(despues)
    filas = ["| Metrica | %s | %s |" % (nombre_a, nombre_d), "|---|---|---|"]
    for etiqueta, clave, tipo in FILAS:
        filas.append("| %s | %s | %s |" % (etiqueta, _fmt(a, clave, tipo), _fmt(d, clave, tipo)))
    return "\n".join(filas)


def por_tarea(regs, nombre):
    filas = ["| Tarea | d | veredicto | global | A | B | trunc | pasos | tokens | s |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for tid in sorted(regs):
        r = regs[tid]
        e = r["evaluacion"]
        c = e["capas"]
        filas.append("| %s | %s | %s | %.2f | %s | %s | %s | %s | %s | %s |" % (
            tid, r.get("dificultad"), e["veredicto"], e["global"],
            (c.get("completitud") or {}).get("nota"),
            (c.get("funcionalidad") or {}).get("nota"),
            ",".join(_tel(r, "motivos_truncado", []) or []) or "-",
            _tel(r, "pasos", "-"), _tel(r, "tokens_totales", "-"),
            int(_tel(r, "segundos", 0))))
    return "\n".join(filas)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="banco_largo.informe")
    ap.add_argument("--antes", required=True)
    ap.add_argument("--despues", default="")
    ap.add_argument("--salida", default="")
    args = ap.parse_args(argv)
    base = RAIZ / "banco_largo" / "corridas"
    antes = cargar_ronda(base / args.antes if not Path(args.antes).exists() else args.antes)
    despues = cargar_ronda(base / args.despues) if args.despues else {}
    comunes = set(antes) & set(despues) if despues else set(antes)
    if despues:
        antes_c = {k: v for k, v in antes.items() if k in comunes}
        despues_c = {k: v for k, v in despues.items() if k in comunes}
    else:
        antes_c, despues_c = antes, {}
    txt = []
    txt.append("# Banco de tareas largas -- comparacion\n")
    txt.append("Ronda A: %s (%d tareas)   Ronda B: %s (%d tareas)   Comparables: %d\n"
               % (args.antes, len(antes), args.despues or "-", len(despues), len(comunes)))
    txt.append(tabla(antes_c, despues_c, args.antes, args.despues or "-"))
    txt.append("\n## Detalle ronda A\n")
    txt.append(por_tarea(antes, args.antes))
    if despues:
        txt.append("\n## Detalle ronda B\n")
        txt.append(por_tarea(despues, args.despues))
    salida = "\n".join(txt)
    print(salida)
    if args.salida:
        Path(args.salida).write_text(salida, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
