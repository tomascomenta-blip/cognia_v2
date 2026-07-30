#!/usr/bin/env python
"""
b2_metamorfico_analisis.py — métricas del juez metamórfico.

PREREG_METAMORFICO_20260730.md (ENMIENDA 2). Las etiquetas son las del repo,
no las invertidas del prereg v1:

    ACUSA_SANOS = páginas GT-aprobadas que el metamórfico REPRUEBA
    DEJA_PASAR  = páginas GT-reprobadas que el metamórfico APRUEBA

El veredicto se RECOMPUTA desde los crudos guardados por el instrumento, así
que barrer umbrales y subconjuntos del catálogo no cuesta ni una corrida.
Las páginas NO_CONCLUYENTE e INFRA se cuentan aparte y NUNCA entran en el
denominador: meterlas como acierto o como fallo fabricaría el número en
cualquiera de los dos sentidos.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"


def veredicto(meta: dict, umbral_r0: float, activas: set) -> str:
    """APROBADO / REPROBADO / NO_CONCLUYENTE / INFRA con el catálogo dado."""
    if meta.get("motivo_infra"):
        return "INFRA"

    viol = [v for v in meta.get("violaciones", [])
            if v["relacion"].split("[")[0] in activas]
    # R0 se recomputa desde los crudos: su violación depende del umbral
    viol = [v for v in viol if not v["relacion"].startswith("R0")]
    instanciadas = meta.get("relaciones_instanciadas", 0)

    if "R0" in activas and meta.get("r0_probados", 0) > 0:
        frac = meta["r0_inertes"] / meta["r0_probados"]
        if frac >= umbral_r0:
            viol.append({"relacion": "R0[actividad]", "detalle": f"frac={frac:.2f}"})
    elif "R0" not in activas:
        instanciadas -= 1 if meta.get("r0_probados", 0) > 0 else 0

    if instanciadas <= 0:
        return "NO_CONCLUYENTE"
    return "REPROBADO" if viol else "APROBADO"


def metricas(filas: list, umbral_r0: float, activas: set) -> dict:
    ac_n = ac_d = dp_n = dp_d = 0
    noconc = infra = 0
    for f in filas:
        gt = f.get("estricto")
        if gt is None:
            gt = f.get("aprobado_orig")
        v = veredicto(f["meta"], umbral_r0, activas)
        if v == "INFRA":
            infra += 1
            continue
        if v == "NO_CONCLUYENTE":
            noconc += 1
            continue
        if gt:
            ac_d += 1
            ac_n += (v == "REPROBADO")
        else:
            dp_d += 1
            dp_n += (v == "APROBADO")
    return {
        "acusa_sanos": (ac_n / ac_d if ac_d else None), "acusa_n": ac_n, "acusa_d": ac_d,
        "deja_pasar": (dp_n / dp_d if dp_d else None), "deja_n": dp_n, "deja_d": dp_d,
        "no_concluyente": noconc, "infra": infra, "juzgadas": ac_d + dp_d,
    }


def _pct(x):
    return "  n/a" if x is None else f"{100*x:5.1f}%"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json", help="salida del instrumento (calib_v2.json)")
    ap.add_argument("--umbrales", default="0.34,0.5,0.67,0.84,1.0")
    ap.add_argument("--gt-duro", action="store_true",
                    help="usa validacion_heldout_v2.json como ground truth "
                         "(OBLIGATORIO para el banco duro: su resultados.json "
                         "tiene estricto=false en las 32 de r1 porque el "
                         "held-out no corrio en linea)")
    args = ap.parse_args(argv)

    p = Path(args.json)
    if not p.is_absolute():
        p = GENERADOS / "b2_metamorfico" / args.json
    filas = json.loads(p.read_text(encoding="utf-8"))["filas"]

    if args.gt_duro:
        gt = {}
        for f in json.loads((GENERADOS / "validacion_heldout_v2.json")
                            .read_text(encoding="utf-8"))["filas"]:
            gt[(f["corpus"], f["pagina"])] = bool(f["orig"] and f["v1"] and f["v2"])
        vivas = []
        for f in filas:
            partes = Path(f["html"]).parts
            clave = (partes[-3], partes[-2])
            if clave not in gt:
                continue
            f["estricto"] = gt[clave]
            vivas.append(f)
        print(f"[gt-duro] {len(vivas)}/{len(filas)} paginas cruzadas con el "
              f"juez triple\n")
        filas = vivas

    print(f"corpus: {p}   n={len(filas)}")
    gts = [f.get("estricto") if f.get("estricto") is not None
           else f.get("aprobado_orig") for f in filas]
    print(f"ground truth: {sum(1 for g in gts if g)} aprobadas / "
          f"{sum(1 for g in gts if not g)} reprobadas\n")

    catalogos = [
        ({"R0", "R1", "R3", "R4"}, "R0+R1+R3+R4"),
        ({"R0"}, "solo R0"),
        ({"R1", "R3", "R4"}, "sin R0"),
        ({"R1"}, "solo R1"),
    ]
    umbrales = [float(x) for x in args.umbrales.split(",")]

    print(f"{'catalogo':14s} {'umbR0':>6s} {'ACUSA_SANOS':>12s} "
          f"{'DEJA_PASAR':>12s} {'juzg':>5s} {'noconc':>7s} {'infra':>6s}")
    print("-" * 70)
    for activas, nombre in catalogos:
        for u in (umbrales if "R0" in activas else [umbrales[0]]):
            m = metricas(filas, u, activas)
            print(f"{nombre:14s} {u:6.2f} "
                  f"{_pct(m['acusa_sanos'])} {m['acusa_n']:3d}/{m['acusa_d']:<3d} "
                  f"{_pct(m['deja_pasar'])} {m['deja_n']:3d}/{m['deja_d']:<3d} "
                  f"{m['juzgadas']:5d} {m['no_concluyente']:7d} {m['infra']:6d}")

    # cobertura: el número que el revisor pidió publicar sí o sí
    print("\nCOBERTURA (relaciones instanciadas por pagina)")
    inst = sorted(f["meta"].get("relaciones_instanciadas", 0) for f in filas)
    from collections import Counter
    print("  distribucion:", dict(sorted(Counter(inst).items())))
    print(f"  mediana: {inst[len(inst)//2]}   minimo: {inst[0]}   maximo: {inst[-1]}")
    pares = Counter(len(f["meta"].get("detalle_acciones", {}).get("pares", []))
                    for f in filas)
    print("  pares inversos por pagina:", dict(sorted(pares.items())))
    amb = sum(f["meta"].get("detalle_acciones", {}).get("pares_ambiguos", 0)
              for f in filas)
    print(f"  pares AMBIGUOS descartados (total): {amb}")
    anim = sum(1 for f in filas if f["meta"].get("animada"))
    print(f"  paginas ANIMADAS: {anim}/{len(filas)}")
    masc = sorted(f["meta"].get("campos_enmascarados", 0) for f in filas)
    print(f"  campos enmascarados por volatilidad: mediana {masc[len(masc)//2]}, "
          f"maximo {masc[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
