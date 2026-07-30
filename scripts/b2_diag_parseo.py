"""
b2_diag_parseo.py — DIAGNÓSTICO (cero GPU): ¿el parseo de las sondas
explica la brecha lazo-vs-replay?

Contradicción a diagnosticar (2026-07-29 ~18:10): la etapa A midió el LAZO
OFF a 11/12 (92%) y la etapa B midió el REPLAY del MISMO prompt a 5/12
(42%). Candidato concreto: `_parsear` de las sondas llama
`_parse_response(crudo, lenguaje="html")` con firma incorrecta (TypeError,
documentado en la revisión de la mañana) y SIEMPRE cae al fallback de
fence `crudo.split("```")[1]`, mientras el lazo usa `_parse_response(raw,
idea, "html")` de verdad — que elige el mejor bloque, corta <think>,
rechaza truncados y exige <html.

Sobre los crudos guardados: computa html_fence (el de las sondas) vs
html_real (el del lazo) y, donde DIFIEREN, juzga el real con contrato
original ∧ held-out para ver si el estricto cambia.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_diag_parseo.py
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

GEN = RAIZ / "cognia" / "program_creator" / "generated_programs"
TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
CORRIDAS = ["b2_ablacion_texto_fresca", "b2_ablacion_texto", "b2_sonda_lazo"]


def _fence(crudo: str) -> str | None:
    """El parseo de las sondas (heredado de b1_router_oraculo)."""
    from cognia.program_creator.generator import _parse_response
    html = None
    try:
        prog = _parse_response(crudo, lenguaje="html")   # TypeError real
        html = getattr(prog, "code", None) or getattr(prog, "codigo", None)
    except Exception:
        html = None
    if not html:
        if "```" in crudo:
            trozo = crudo.split("```")[1]
            html = trozo[4:] if trozo.lstrip()[:4].lower() == "html" else trozo
        else:
            html = crudo
    return html if html and "<" in html else None


def _real(crudo: str, tarea: str) -> str | None:
    """El parseo del LAZO (firma correcta)."""
    from cognia.program_creator.generator import _parse_response
    buf = io.StringIO()
    with redirect_stdout(buf):
        prog = _parse_response(crudo, tarea, "html")
    return getattr(prog, "code", None) if prog is not None else None


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia.presupuesto_pared import PresupuestoAgotado, con_presupuesto

    tareas = {t["id"]: t for t in
              json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    heldout = {t["id"]: t["contrato"] for t in
               json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    salida = {"corridas": {}}

    for corrida in CORRIDAS:
        d = GEN / corrida
        if not (d / "resultados.json").is_file():
            continue
        res = json.loads((d / "resultados.json").read_text(encoding="utf-8"))
        filas, n_raw, difieren, rescates, perdidas = [], 0, 0, 0, 0
        for c in res["celdas"]:
            dc = d / f"{c['tarea']}__{c['brazo']}__r{c['rep']}"
            raw_f = dc / "respuesta_cruda.txt"
            if not raw_f.is_file():
                continue
            n_raw += 1
            crudo = raw_f.read_text(encoding="utf-8")
            hf = _fence(crudo)
            hr = _real(crudo, c["tarea"])
            fila = {"celda": dc.name, "brazo": c["brazo"],
                    "estricto_medido": bool(c.get("estricto")),
                    "fence_chars": len(hf or ""),
                    "real_chars": len(hr or ""),
                    "iguales": (hf or "") == (hr or "")}
            if not fila["iguales"]:
                difieren += 1
                if hr:
                    p = dc / "index_real.html"
                    p.write_text(hr, encoding="utf-8")
                    try:
                        def _juzgar(ruta, orig, held):
                            v = juez_ejecutable.juzgar_web(ruta, orig)
                            vh = juez_ejecutable.juzgar_web(ruta, held)
                            return v, vh
                        v, vh = con_presupuesto(
                            300, _juzgar, p, tareas[c["tarea"]]["contrato"],
                            heldout[c["tarea"]])
                        fila["estricto_real"] = bool(v.aprobado and vh.aprobado)
                        fila["motivo_real"] = (v.motivo if not v.aprobado
                                               else vh.motivo or "")[:90]
                    except PresupuestoAgotado:
                        fila["estricto_real"] = None
                        fila["motivo_real"] = "juez colgado"
                    except Exception as exc:
                        fila["estricto_real"] = None
                        fila["motivo_real"] = f"crash: {exc}"[:80]
                else:
                    fila["estricto_real"] = False
                    fila["motivo_real"] = "el parse del LAZO rechaza (regenera)"
                if fila.get("estricto_real") and not fila["estricto_medido"]:
                    rescates += 1
                if fila["estricto_medido"] and fila.get("estricto_real") is False:
                    perdidas += 1
            filas.append(fila)
            print(f"  {fila['celda']:<34} "
                  f"{'IGUAL' if fila['iguales'] else 'DIFIERE'} "
                  f"fence={fila['fence_chars']} real={fila['real_chars']} "
                  f"estricto {fila['estricto_medido']}"
                  f"{'' if fila['iguales'] else ' -> ' + str(fila.get('estricto_real'))}",
                  flush=True)
        print(f"\n== {corrida}: {n_raw} crudos, {difieren} con parseo DISTINTO; "
              f"el parseo del lazo rescata {rescates} y pierde {perdidas} ==\n",
              flush=True)
        salida["corridas"][corrida] = {
            "n_crudos": n_raw, "difieren": difieren,
            "rescates_del_parse_real": rescates,
            "perdidas_del_parse_real": perdidas, "filas": filas}

    f = GEN / "diag_parseo.json"
    f.write_text(json.dumps(salida, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    print(f"JSON: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
