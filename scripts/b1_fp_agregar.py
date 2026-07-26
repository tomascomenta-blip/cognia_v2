"""
b1_fp_agregar.py — junta los fp_contrato__<tarea>.json de las corridas
paralelas en el fp_contrato.json final y aplica la lectura pre-registrada.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b1_fp_agregar.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
POOL_DIR = (RAIZ / "cognia" / "program_creator" / "generated_programs"
            / "b1_oraculo")
TAREAS = ["hoja_calculo", "carrito_stock", "kanban", "buscaminas"]
MODELOS = ["pensar", "laguna"]


def main() -> int:
    frontier: dict = {}
    pool: dict = {}
    for t in TAREAS:
        f = POOL_DIR / f"fp_contrato__{t}.json"
        if not f.is_file():
            print(f"FALTA {f.name}: la corrida de esa tarea no termino",
                  file=sys.stderr)
            return 1
        d = json.loads(f.read_text(encoding="utf-8"))
        frontier.update(d.get("fase1_frontier", {}))
        pool.update(d.get("fase2_pool", {}))

    resumen: dict = {}
    for m in MODELOS + ["total"]:
        filas = [v for k, v in pool.items()
                 if ("__" + m + "__" in k or m == "total") and "original" in v]
        aprob = [v for v in filas if v["original"]["aprobado"]]
        fp = [v for v in aprob if not v["heldout"]["aprobado"]]
        harness = [v for v in fp if not v["heldout"].get("cargo", True)]
        resumen[m] = {
            "juzgados": len(filas), "aprueban_original": len(aprob),
            "falsos_positivos": len(fp) - len(harness),
            "errores_harness": len(harness),
            "tasa_fp": round((len(fp) - len(harness)) / len(aprob), 3)
            if aprob else None}

    print("=" * 78)
    print("TASA DE FALSOS POSITIVOS DEL CONTRATO BRUTAL (48 productos, "
          "pre-registro: <=10% sostiene / 10-30% techo / >30% aprobador)")
    print("=" * 78)
    for m, r in resumen.items():
        tasa = f"{r['tasa_fp']:.1%}" if r["tasa_fp"] is not None else "n/a"
        print(f"  {m:<8} juzgados: {r['juzgados']:>2}   aprueban original: "
              f"{r['aprueban_original']:>2}   FP: {r['falsos_positivos']:>2}"
              f"   tasa: {tasa}   (harness aparte: {r['errores_harness']})")

    print("\nFP por producto (aprueba original, falla held-out):")
    alguno = False
    for k, v in sorted(pool.items()):
        if v.get("original", {}).get("aprobado") \
                and not v.get("heldout", {}).get("aprobado", True):
            alguno = True
            print(f"  {k:<32} {'; '.join(v['heldout']['fallas_criticas'][:2])}")
    if not alguno:
        print("  (ninguno)")

    salida = POOL_DIR / "fp_contrato.json"
    salida.write_text(json.dumps(
        {"fase1_frontier": frontier, "fase2_pool": pool, "resumen": resumen},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
