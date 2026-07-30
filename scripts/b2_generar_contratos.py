#!/usr/bin/env python
"""
b2_generar_contratos.py — contratos internos sobre páginas YA congeladas.

PREREG_ADAPTADOR_ANTIINVENCION_20260730 (paso previo obligatorio).

POR QUÉ. El adaptador anti-invención no se puede medir hoy porque los 318
contratos en disco salen de **solo 4 enunciados**: el held-out honesto es por
ENUNCIADO, así que habría 4 grupos y cualquier número sería memorización.

La forma barata de arreglarlo NO es generar páginas nuevas (eso es el lazo
entero, horas de GPU): es generar el CONTRATO sobre las páginas que ya
existen congeladas. `generar_contrato(idea, html)` solo necesita el enunciado
y el DOM, y de ambos hay de sobra: 64 páginas del banco duro (8 enunciados) y
52 de la cabecera (9 enunciados) — 17 enunciados nuevos, que llevan el corpus
de 4 a 21.

De paso sale un número que hoy solo se tiene sobre 10 tareas: el **Youden J
del contrato interno por enunciado**, que es la línea base contra la que
cualquier adaptador tendrá que demostrar algo.

Esto NO decide nada por sí solo: es instrumentación. Sin umbral y sin
veredicto.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from cognia.presupuesto_pared import con_presupuesto, PresupuestoAgotado  # noqa: E402
from cognia.program_creator import juez_ejecutable                        # noqa: E402

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
PRESUPUESTO = 240          # s por contrato (el pensador razona; margen 3x)

# (corpus, fichero de tareas). El id de la tarea es la clave del enunciado.
CORPUS = [
    ("b2_bon_heldout_duro",            "b1_tareas_duras.json"),
    ("b2_bon_heldout_duro_r2",         "b1_tareas_duras.json"),
    ("b2_bon_heldout_cabecera",        "b1_tareas_cabecera.json"),
    ("b2_bon_heldout_cabecera2_recal", "b1_tareas_cabecera2.json"),
]


def _ideas(fichero: str) -> dict:
    d = json.loads((RAIZ / "scripts" / fichero).read_text(encoding="utf-8"))
    tareas = d["tareas"] if isinstance(d, dict) and "tareas" in d else d
    return {t["id"]: (t.get("idea") or t.get("enunciado") or t.get("prompt"))
            for t in tareas}


def _verificar_backend() -> None:
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/props",
                                    timeout=10) as r:
            props = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        sys.exit(f"ABORTO: backend :8080 no responde ({exc})")
    slots = props.get("total_slots")
    ctx = (props.get("default_generation_settings") or {}).get("n_ctx", 0)
    if slots != 1:
        sys.exit(f"ABORTO: total_slots={slots} (el ctx se parte entre slots)")
    if ctx < 16384:
        sys.exit(f"ABORTO: n_ctx={ctx} < 16384")
    print(f"backend OK: slots=1, n_ctx={ctx}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reanudar", action="store_true")
    ap.add_argument("--corpus", default=None, help="limita a un corpus")
    args = ap.parse_args(argv)

    _verificar_backend()
    destino = GENERADOS / "b2_contratos_ampliado"
    destino.mkdir(parents=True, exist_ok=True)
    f_idx = destino / "indice.json"
    idx = (json.loads(f_idx.read_text(encoding="utf-8"))
           if args.reanudar and f_idx.is_file() else {"filas": []})
    hechos = {f["pagina"] for f in idx["filas"]}

    trabajos = []
    for corpus, fichero in CORPUS:
        if args.corpus and corpus != args.corpus:
            continue
        raiz = GENERADOS / corpus
        if not raiz.is_dir():
            print(f"  (falta {corpus}, se salta)", flush=True)
            continue
        ideas = _ideas(fichero)
        for d in sorted(raiz.glob("*__r*__s*")):
            html = d / "index.html"
            if not html.is_file():
                continue
            tarea = d.name.split("__")[0]
            if tarea not in ideas or not ideas[tarea]:
                continue
            trabajos.append((corpus, tarea, d, html, ideas[tarea]))

    print(f"{len(trabajos)} paginas · {len({t[1] for t in trabajos})} "
          f"enunciados distintos · {len(hechos)} ya hechas", flush=True)

    t0 = time.time()
    for k, (corpus, tarea, d, html, idea) in enumerate(trabajos, 1):
        clave = f"{corpus}/{d.name}"
        if clave in hechos:
            continue
        ini = time.time()
        try:
            contrato = con_presupuesto(PRESUPUESTO,
                                       juez_ejecutable.generar_contrato,
                                       idea, html)
            motivo = ""
        except PresupuestoAgotado as exc:
            contrato, motivo = None, f"presupuesto: {exc}"[:120]
        except Exception as exc:
            contrato, motivo = None, f"{type(exc).__name__}: {exc}"[:120]

        if contrato:
            (d / "contrato_interno.json").write_text(
                json.dumps(contrato, ensure_ascii=False, indent=1),
                encoding="utf-8")
        pasos = len(contrato.get("pasos", [])) if contrato else 0
        idx["filas"].append({
            "pagina": clave, "corpus": corpus, "tarea": tarea,
            "ok": bool(contrato), "pasos": pasos, "motivo": motivo,
            "segundos": round(time.time() - ini, 1)})
        f_idx.write_text(json.dumps(idx, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print(f"[{k}/{len(trabajos)}] {tarea:22s} "
              f"{'OK' if contrato else 'FALLO'} pasos={pasos:2d} "
              f"{time.time()-ini:5.1f}s", flush=True)

    ok = sum(1 for f in idx["filas"] if f["ok"])
    print(f"\nTOTAL {len(idx['filas'])} contratos ({ok} OK) en "
          f"{(time.time()-t0)/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
