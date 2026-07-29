"""
b2_piloto_qa.py — PILOTO DE FUTILIDAD de un candidato a pensador-QA.
PREREG_QA_FUERTE_20260728.md, primera enmienda: leerla ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_piloto_qa.py --etiqueta X

6 páginas frescas del corpus de la sonda (las SEGUNDAS de cada tarea + las
terceras de hoja y carrito; las primeras se quemaron en los humos), 2
intentos por página como el runner real. Un contrato es USABLE si
generar_contrato devuelve algo (parsea, pasos válidos, ≥1 crítico — el
descarte de producción ya lo garantiza). Umbral pre-registrado: <3/6 usables
= KILL DE APTITUD del candidato, el bloque completo no se corre.
La temperatura del candidato se fija FUERA (COGNIA_TEMP_CONTRATO).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
SONDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
         / "b2_sonda_prompt")


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    import os

    from cognia.program_creator import juez_ejecutable
    from cognia import backend_activo

    etiqueta = (argv[argv.index("--etiqueta") + 1]
                if "--etiqueta" in argv else "candidato")
    ideas = {t["id"]: t["idea"]
             for t in json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    plan = []
    for tid in sorted(ideas):
        pags = sorted(SONDA.glob(f"{tid}__*/index.html"))
        if len(pags) > 1:
            plan.append((tid, pags[1]))
    for tid in ("hoja_calculo", "carrito_stock"):
        pags = sorted(SONDA.glob(f"{tid}__*/index.html"))
        if len(pags) > 2:
            plan.append((tid, pags[2]))
    plan = plan[:6]

    print(f"PILOTO QA '{etiqueta}' — {len(plan)} páginas, 2 intentos c/u, "
          f"temp={os.environ.get('COGNIA_TEMP_CONTRATO', '0.2')}", flush=True)
    filas, usables = [], 0
    for tid, pag in plan:
        t0 = time.time()
        c = None
        for _ in (1, 2):
            c = juez_ejecutable.generar_contrato(ideas[tid], pag,
                                                 modo="clasico")
            if c:
                break
        segs = round(time.time() - t0, 1)
        ok = c is not None
        usables += ok
        crit = (sum(1 for p in c["pasos"]
                    if isinstance(p, dict) and p.get("critico")) if c else 0)
        filas.append({"tarea": tid, "pagina": pag.parent.name, "usable": ok,
                      "pasos": len(c["pasos"]) if c else 0, "criticos": crit,
                      "segundos": segs,
                      "backend": backend_activo.ultimo()})
        print(f"  {pag.parent.name:<34} {'USABLE' if ok else 'inutil'} "
              f"(pasos={filas[-1]['pasos']}, criticos={crit}, {segs}s)",
              flush=True)

    veredicto = "SIGUE (bloque completo)" if usables >= 3 else "KILL DE APTITUD"
    print(f"\nPILOTO: {usables}/{len(plan)} usables -> {veredicto}", flush=True)
    salida = SONDA.parent / f"piloto_qa_{etiqueta}.json"
    salida.write_text(json.dumps(
        {"etiqueta": etiqueta, "usables": usables, "n": len(plan),
         "veredicto": veredicto, "filas": filas}, indent=2,
        ensure_ascii=False), encoding="utf-8")
    print(f"JSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
