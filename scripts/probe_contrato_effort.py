"""
probe_contrato_effort.py — ¿el contrato a effort=low es mas pobre?

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\probe_contrato_effort.py [n]

CONTEXTO (2026-07-26 ~16:50): todo el regimen post-fix (basefix 3,4,3;
bonfix 3,4,2; escalada 3,3,4) rinde ~3.0-3.3 contra 4.5 de la serie pre-fix.
El unico cambio comun a TODOS los brazos ademas del fix de reparacion es que
generar_contrato paso a reasoning_effort=low (commit 0a70f98). Sintomas
compatibles con contratos mas debiles: contador APROBADO por el juez interno
y reprobado por el contrato pre-escrito externo (3 replicas), contraejemplos
mas vagos, reparaciones que no rematan.

Esta sonda genera n contratos con effort=low y n con esfuerzo default (la
config pre-fix efectiva: linea "Reasoning: low" inerte en el system + template
default) para la MISMA idea y el MISMO inventario DOM (el contador fallido de
basefix3), y compara: nº de pasos, nº de checks con interaccion (click/
escribir), y si cubren las reglas duras del enunciado (empieza en 0, nunca
baja de 0, sumar/restar).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PRODUCTO = (RAIZ / "cognia" / "program_creator" / "generated_programs"
            / "b2_sistema_real" / "contador" / "index.html")
IDEA = ('Un contador en un solo archivo HTML. OBLIGATORIO: un <span '
        'id="valor"> que muestra el numero, un <button id="mas"> que suma 1 '
        'y un <button id="menos"> que resta 1. Empieza en 0 y NUNCA baja de 0.')


def resumen(c: dict | None) -> str:
    if not c:
        return "None (el pensador no produjo contrato)"
    pasos = c.get("pasos", [])
    acciones = []
    for p in pasos:
        if isinstance(p.get("acciones"), list):
            acciones += [s.get("accion", "?") for s in p["acciones"]
                         if isinstance(s, dict)]
        else:
            acciones.append(p.get("accion", "?"))
    inter = sum(1 for a in acciones if a in ("click", "escribir", "tecla"))
    txt = json.dumps(c, ensure_ascii=False)
    cubre_no_baja = ("0" in txt and ("menos" in txt or "#menos" in txt))
    return (f"{len(pasos)} pasos, {len(acciones)} acciones ({inter} de "
            f"interaccion), menciona menos/0: {cubre_no_baja}, "
            f"{len(txt)} chars")


def main(argv: list) -> int:
    n = int(argv[0]) if argv else 2
    from cognia.program_creator import juez_ejecutable as je
    from cognia import llm_local

    generar_real = llm_local.generar

    for etiqueta, effort in (("effort=low (actual)", "low"),
                             ("default (pre-fix)", None)):
        print(f"\n── {etiqueta} ──", flush=True)

        def _generar(*a, **kw):
            kw["reasoning_effort"] = effort
            kw.setdefault("timeout", 400)
            return generar_real(*a, **kw)

        for i in range(1, n + 1):
            # generar_contrato importa generar DENTRO de la funcion
            # (from ..llm_local import generar): se parchea en llm_local.
            with patch.object(llm_local, "generar", side_effect=_generar):
                c = je.generar_contrato(IDEA, PRODUCTO)
            print(f"  intento {i}: {resumen(c)}", flush=True)
            if c:
                destino = (RAIZ / "scripts"
                           / f"probe_contrato_{'low' if effort else 'def'}_{i}.json")
                destino.write_text(json.dumps(c, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
