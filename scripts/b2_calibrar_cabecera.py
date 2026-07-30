"""
b2_calibrar_cabecera.py — ¿discrimina la cabecera nueva?
PREREG_CABECERA_NUEVA_20260730.md: el criterio esta ALLI y se fijo ANTES de
escribir las tareas.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_calibrar_cabecera.py

Lee el pass@1 por tarea (n=4 muestras del sistema) y aplica el criterio:
  1/4 - 3/4  ENTRA (discrimina)
  4/4        SATURADA (no entra como esta)
  0/4        FUERA DE ALCANCE (no se usa para medir progreso todavia)
Objetivo pre-registrado: >=3 tareas en la banda que discrimina.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_cabecera.json"
CORPUS = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_bon_heldout_cabecera")


def main(argv: list) -> int:
    orden = [t["id"] for t in
             json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]]
    res = json.loads((CORPUS / "resultados.json").read_text(encoding="utf-8"))
    por: dict = {}
    for m in res["muestras"]:
        por.setdefault(m["tarea"], []).append(m)

    entran, saturadas, fuera, incompletas = [], [], [], []
    print(f"\n{'=' * 74}")
    print(f"  CALIBRACION DE LA CABECERA — criterio pre-registrado\n")
    for t in orden:
        ms = sorted(por.get(t, []), key=lambda m: int(m["s"]))
        if not ms:
            print(f"  {t:<24} sin muestras")
            continue
        ok = sum(1 for m in ms if m.get("aprobado"))
        n = len(ms)
        infra = sum(1 for m in ms if "EXCEPCION" in str(m.get("como", ""))
                    or (m.get("backend") or {}).get("degradado"))
        if n < 4:
            clase, dest = "PARCIAL", incompletas
        elif ok == n:
            clase, dest = "SATURADA (no entra)", saturadas
        elif ok == 0:
            clase, dest = "FUERA DE ALCANCE (no entra)", fuera
        else:
            clase, dest = "ENTRA (discrimina)", entran
        dest.append(t)
        motivos = [str(m.get("motivo", ""))[:60] for m in ms
                   if not m.get("aprobado")]
        print(f"  {t:<24} pass@1 {ok}/{n}  {clase}"
              + (f"  [infra {infra}]" if infra else ""))
        for mo in motivos[:2]:
            print(f"      falla: {mo}")
    print(f"\n  ENTRAN: {len(entran)} {entran}")
    print(f"  saturadas: {saturadas or '—'} | fuera de alcance: {fuera or '—'}"
          + (f" | parciales: {incompletas}" if incompletas else ""))
    veredicto = ("CABECERA UTIL" if len(entran) >= 3 else
                 "CABECERA INSUFICIENTE (el prereg exige >=3 que discriminen)")
    print(f"  VEREDICTO: {veredicto}")
    print(f"{'=' * 74}")
    salida = CORPUS / "calibracion.json"
    salida.write_text(json.dumps(
        {"entran": entran, "saturadas": saturadas, "fuera": fuera,
         "incompletas": incompletas, "veredicto": veredicto,
         "detalle": {t: {"ok": sum(1 for m in por.get(t, [])
                                   if m.get("aprobado")),
                         "n": len(por.get(t, []))} for t in orden}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
