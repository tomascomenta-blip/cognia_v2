#!/usr/bin/env python
"""
b2_j_ampliado.py — Youden J del contrato interno POR ENUNCIADO, sobre 21.

PREREG_ADAPTADOR_ANTIINVENCION_20260730 (paso previo). Fase 2: juzga cada
página congelada con el contrato interno que `b2_generar_contratos.py` acaba
de escribir para ella, y compara con la verdad de suelo.

Hasta hoy el J del contrato interno se tenía sobre **10 tareas** (y salió
+12.2, con el fallo dominante en CONDENAR SANOS: aprueba el 17.7% de las
sanas). Aquí se mide sobre **21 enunciados**, que es la línea base contra la
que cualquier adaptador tendrá que demostrar algo — y, sobre todo, la que
permite un held-out POR ENUNCIADO que hoy no existía.

Verdad de suelo por corpus:
  - banco DURO  -> `validacion_heldout_v2.json` (juez triple orig ∧ v1 ∧ v2)
  - CABECERA    -> `resultados.json`, clave `aprobado` (contrato original a
                   mano). Es un GT más débil y se reporta APARTE, nunca
                   fundido con el del duro.
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
PRESUPUESTO = 300          # la lección del juez colgado, otra vez


def _gt_duro() -> dict:
    d = json.loads((GENERADOS / "validacion_heldout_v2.json")
                   .read_text(encoding="utf-8"))
    return {(f["corpus"], f["pagina"]): bool(f["orig"] and f["v1"] and f["v2"])
            for f in d["filas"]}


def _gt_original(corpus: str) -> dict:
    p = GENERADOS / corpus / "resultados.json"
    if not p.is_file():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {(corpus, f"{m['tarea']}__r{m['rep']}__s{m['s']}"):
            bool(m.get("aprobado")) for m in d.get("muestras", [])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reanudar", action="store_true")
    args = ap.parse_args(argv)

    idx = json.loads((SALIDA / "indice.json").read_text(encoding="utf-8"))
    gt = dict(_gt_duro())
    for c in ("b2_bon_heldout_cabecera", "b2_bon_heldout_cabecera2_recal"):
        gt.update(_gt_original(c))

    f_out = SALIDA / "juicios.json"
    res = (json.loads(f_out.read_text(encoding="utf-8"))
           if args.reanudar and f_out.is_file() else {"filas": []})
    hechos = {f["pagina"] for f in res["filas"]}

    pendientes = [f for f in idx["filas"] if f["ok"] and f["pagina"] not in hechos]
    print(f"{len(pendientes)} paginas por juzgar "
          f"({len(hechos)} ya hechas)", flush=True)

    t0 = time.time()
    for k, f in enumerate(pendientes, 1):
        corpus, carpeta = f["pagina"].split("/", 1)
        d = GENERADOS / corpus / carpeta
        html = d / "index.html"
        contrato = json.loads((d / "contrato_interno.json")
                              .read_text(encoding="utf-8"))
        try:
            v = con_presupuesto(PRESUPUESTO, juez_ejecutable.juzgar_web,
                                html, contrato)
            aprueba, motivo = bool(v.aprobado), v.motivo[:120]
            criticos = sum(1 for c in v.checks if c.critico)
            # DETALLE POR CHECK: es el insumo de la etiqueta debil del
            # adaptador ("este check falla en TODAS las paginas sanas de su
            # enunciado" => candidato a valor inventado). Sin el, cualquier
            # via sobre el contrato interno tendria que re-ejecutar todo.
            detalle = [{"n": c.nombre, "ok": c.ok, "critico": c.critico}
                       for c in v.checks]
        except (PresupuestoAgotado, Exception) as exc:      # noqa: B014
            aprueba, motivo, criticos = None, f"{type(exc).__name__}"[:120], 0
            detalle = []
        res["filas"].append({
            "pagina": f["pagina"], "corpus": corpus, "tarea": f["tarea"],
            "interno_aprueba": aprueba, "criticos": criticos,
            "gt": gt.get((corpus, carpeta)), "motivo": motivo,
            "detalle": detalle})
        f_out.write_text(json.dumps(res, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        if k % 10 == 0 or k == len(pendientes):
            print(f"[{k}/{len(pendientes)}] {(time.time()-t0)/60:.1f} min",
                  flush=True)

    _resumir(res["filas"])
    return 0


def _resumir(filas: list) -> None:
    grupos = {
        "BANCO DURO (GT = juez triple)":
            lambda f: f["corpus"].startswith("b2_bon_heldout_duro"),
        "CABECERA (GT = contrato original, mas debil)":
            lambda f: "cabecera" in f["corpus"],
    }
    for titulo, filtro in grupos.items():
        sub = [f for f in filas if filtro(f) and f["gt"] is not None
               and f["interno_aprueba"] is not None]
        if not sub:
            continue
        print(f"\n{'='*74}\n{titulo}   (n={len(sub)})\n{'='*74}")
        print(f"{'enunciado':24s} {'n':>3s} {'sanas%':>7s} {'rotas%':>7s} "
              f"{'ACUSA':>6s} {'DEJA':>6s} {'J':>7s}")
        print("-" * 74)
        por_tarea = defaultdict(list)
        for f in sub:
            por_tarea[f["tarea"]].append(f)
        tot = [0, 0, 0, 0]
        for tarea in sorted(por_tarea):
            fs = por_tarea[tarea]
            sd = sum(1 for f in fs if f["gt"])
            sa = sum(1 for f in fs if f["gt"] and f["interno_aprueba"])
            rd = sum(1 for f in fs if not f["gt"])
            ra = sum(1 for f in fs if not f["gt"] and f["interno_aprueba"])
            tot[0] += sa; tot[1] += sd; tot[2] += ra; tot[3] += rd
            acusa = 100 * (1 - sa / sd) if sd else None
            deja = 100 * (ra / rd) if rd else None
            j = (100 - acusa - deja) if (acusa is not None
                                         and deja is not None) else None
            print(f"{tarea:24s} {len(fs):3d} "
                  f"{(f'{100*sa/sd:6.1f}%' if sd else '   n/a'):>7s} "
                  f"{(f'{100*ra/rd:6.1f}%' if rd else '   n/a'):>7s} "
                  f"{(f'{acusa:5.1f}' if acusa is not None else '  n/a'):>6s} "
                  f"{(f'{deja:5.1f}' if deja is not None else '  n/a'):>6s} "
                  f"{(f'{j:+6.1f}' if j is not None else '   n/a'):>7s}")
        sa, sd, ra, rd = tot
        if sd and rd:
            acusa = 100 * (1 - sa / sd)
            deja = 100 * (ra / rd)
            print("-" * 74)
            print(f"{'AGREGADO':24s} {sd+rd:3d} {100*sa/sd:6.1f}% "
                  f"{100*ra/rd:6.1f}% {acusa:5.1f} {deja:5.1f} "
                  f"{100-acusa-deja:+6.1f}")
        print(f"  (sanas {sd}, rotas {rd})")


if __name__ == "__main__":
    raise SystemExit(main())
