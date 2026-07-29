"""
b2_parse_lazo_vs_directo.py — FASE 2 (rama FLUJO) de la sonda del ladrón:
¿el PARSE del lazo tira respuestas que el parse directo salva? Cero GPU.
Se corre SOLO si el fork de fase 1 manda a flujo (PREREG_SONDA_LAZO, 1ª
enmienda); leerlo antes.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_parse_lazo_vs_directo.py

Sobre las respuestas CRUDAS guardadas por la 3ª enmienda: re-corre el parse
DEL LAZO (generator._parse_response: corte de <think>, fence estricto con
truncado→regenerar, exigencia de <html, mínimo 30 chars) y lo cruza con el
parse directo (el que aceptó la sonda) y con el outcome estricto. La celda
que el juez aprobó ESTRICTA pero cuyo crudo el parse del lazo RECHAZA es
capacidad que el flujo tira a la basura.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

SONDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
         / "b2_sonda_lazo")


def main(argv: list) -> int:
    from cognia.program_creator.generator import _parse_response

    res = json.loads((SONDA / "resultados.json").read_text(encoding="utf-8"))
    filas = []
    sin_crudo = 0
    for c in res["celdas"]:
        d = SONDA / f"{c['tarea']}__{c['brazo']}__r{c['rep']}"
        raw_f = d / "respuesta_cruda.txt"
        if not raw_f.is_file():
            sin_crudo += 1
            continue
        raw = raw_f.read_text(encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            prog = _parse_response(raw, c["tarea"], "html")
        filas.append({
            "celda": f"{c['tarea']}__{c['brazo']}__r{c['rep']}",
            "brazo": c["brazo"],
            "estricto": bool(c.get("estricto")),
            "aprobado_orig": bool(c.get("aprobado_orig")),
            "directo_acepto": (d / "index.html").is_file(),
            "lazo_acepta": prog is not None,
            "avisos_lazo": buf.getvalue().strip()[:200]})

    n = len(filas)
    rechaza = [f for f in filas if f["directo_acepto"] and not f["lazo_acepta"]]
    rechaza_buenas = [f for f in rechaza if f["estricto"]]
    print(f"celdas con crudo: {n} (sin crudo, fuera: {sin_crudo})")
    print(f"el lazo RECHAZARIA {len(rechaza)} respuestas que el directo "
          f"acepto; de ellas {len(rechaza_buenas)} eran ESTRICTO-OK "
          f"(capacidad tirada por el parse)")
    for f in rechaza:
        print(f"  {'ESTRICTO-OK' if f['estricto'] else 'fallida':<12} "
              f"{f['celda']:<34} {f['avisos_lazo'][:80]}")
    por_brazo = {}
    for b in ("replay", "crudo"):
        de_b = [f for f in filas if f["brazo"] == b]
        por_brazo[b] = {
            "n": len(de_b),
            "lazo_rechaza": sum(1 for f in de_b if f["directo_acepto"]
                                and not f["lazo_acepta"]),
            "rechaza_estrictas": sum(1 for f in de_b if f["estricto"]
                                     and not f["lazo_acepta"])}
    print(f"por brazo: {por_brazo}")
    salida = SONDA / "parse_lazo_vs_directo.json"
    salida.write_text(json.dumps(
        {"filas": filas, "sin_crudo": sin_crudo, "por_brazo": por_brazo},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
