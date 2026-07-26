"""
b1_fp_contrato.py — mide la tasa de FALSOS POSITIVOS del contrato brutal.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b1_fp_contrato.py [--solo-frontier]

Protocolo (pre-registrado en PREREG_FP_CONTRATO_20260725.md — leerlo antes de
tocar esto):

  FASE 1  valida el held-out contra frontier_brutal/: un producto que aprueba
          el contrato ORIGINAL tiene que aprobar el HELD-OUT. Si no, el bug es
          del held-out y el script corta ahi (exit 2) para arreglar el contrato.
  FASE 2  re-juzga los 48 productos del pool (b1_oraculo/) con ambos contratos.
          FP = aprueba-original y falla-held-out.

No llama a ningun LLM. No toca la flota. Solo Playwright sobre bytes en disco.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
POOL_DIR = GENERADOS / "b1_oraculo"
FRONTIER_DIR = GENERADOS / "frontier_brutal"
TAREAS = ["hoja_calculo", "carrito_stock", "kanban", "buscaminas"]
MODELOS = ["pensar", "laguna"]          # gpt-oss-20b / Laguna-16k (33B)
N = 6


def _contratos(nombre: str) -> dict:
    d = json.loads((RAIZ / "scripts" / nombre).read_text(encoding="utf-8"))
    return {t["id"]: t["contrato"] for t in d["tareas"]}


def _juzgar(html: Path, contrato: dict) -> dict:
    from cognia.program_creator import juez_ejecutable
    v = juez_ejecutable.juzgar_web(html, contrato)
    fallas = [f"{c.nombre} ({c.detalle})" for c in v.checks
              if c.critico and not c.ok]
    return {"aprobado": v.aprobado, "motivo": v.motivo[:160],
            "checks_ok": sum(1 for c in v.checks if c.ok),
            "checks": len(v.checks), "fallas_criticas": fallas[:4],
            "cargo": bool(v.checks) and v.checks[0].ok}


def main(argv: list) -> int:
    orig = _contratos("b1_tareas_brutales.json")
    heldout = _contratos("b1_contratos_heldout.json")
    global TAREAS
    sufijo = ""
    if "--tareas" in argv:
        pedidas = argv[argv.index("--tareas") + 1].split(",")
        TAREAS = [t for t in TAREAS if t in pedidas]
        sufijo = "__" + "_".join(TAREAS)

    # ── FASE 1: el held-out contra la referencia frontier ────────────────────
    print("=" * 78)
    print("FASE 1 — validacion del held-out contra frontier_brutal/")
    print("=" * 78)
    frontier: dict = {}
    heldout_roto = False
    for t in TAREAS:
        html = FRONTIER_DIR / t / "index.html"
        vo = _juzgar(html, orig[t])
        vh = _juzgar(html, heldout[t])
        frontier[t] = {"original": vo, "heldout": vh}
        marca = ""
        if vo["aprobado"] and not vh["aprobado"]:
            marca = "  <-- SOSPECHA DE FALSO NEGATIVO DEL HELD-OUT"
            heldout_roto = True
        print(f"  {t:<14} original={'OK' if vo['aprobado'] else 'falla'}"
              f"  heldout={'OK' if vh['aprobado'] else 'falla'}{marca}")
        for f in (vh["fallas_criticas"] if not vh["aprobado"] else []):
            print(f"      heldout FALLA: {f}")
        for f in (vo["fallas_criticas"] if not vo["aprobado"] else []):
            print(f"      original FALLA: {f}")

    salida = POOL_DIR / f"fp_contrato{sufijo}.json"
    if heldout_roto:
        salida.write_text(json.dumps({"fase1_frontier": frontier},
                                     indent=2, ensure_ascii=False),
                          encoding="utf-8")
        print("\nHELD-OUT INVALIDO: un producto que aprueba el original lo "
              "falla. Arreglar el contrato held-out (no el producto) y "
              "re-correr. JSON parcial en", salida)
        return 2
    print("\n  held-out VALIDADO: ningun aprobado-original de frontier lo falla.")
    if "--solo-frontier" in argv:
        salida.write_text(json.dumps({"fase1_frontier": frontier},
                                     indent=2, ensure_ascii=False),
                          encoding="utf-8")
        return 0

    # ── FASE 2: los 48 productos del pool ────────────────────────────────────
    print("\n" + "=" * 78)
    print("FASE 2 — 48 productos del pool con ambos contratos")
    print("=" * 78)
    pool: dict = {}
    for t in TAREAS:
        for m in MODELOS:
            for r in range(1, N + 1):
                nombre = f"{t}__{m}__r{r}"
                html = POOL_DIR / nombre / "index.html"
                if not html.is_file():
                    pool[nombre] = {"sin_html": True}
                    print(f"  {nombre:<32} SIN HTML")
                    continue
                vo = _juzgar(html, orig[t])
                fila = {"original": vo}
                if vo["aprobado"]:
                    fila["heldout"] = _juzgar(html, heldout[t])
                pool[nombre] = fila
                if not vo["aprobado"]:
                    et = "orig=falla (fuera del denominador)"
                elif fila["heldout"]["aprobado"]:
                    et = "orig=OK  heldout=OK"
                else:
                    et = "orig=OK  heldout=FALLA  <-- FALSO POSITIVO"
                print(f"  {nombre:<32} {et}", flush=True)

    # ── Numeros ──────────────────────────────────────────────────────────────
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

    print("\n" + "=" * 78)
    print("TASA DE FALSOS POSITIVOS DEL CONTRATO (pre-registro: "
          "<=10% sostiene / 10-30% techo / >30% aprobador)")
    print("=" * 78)
    for m, r in resumen.items():
        tasa = f"{r['tasa_fp']:.1%}" if r["tasa_fp"] is not None else "n/a"
        print(f"  {m:<8} aprueban original: {r['aprueban_original']:>2}"
              f"   FP: {r['falsos_positivos']:>2}   tasa: {tasa}"
              f"   (errores de harness aparte: {r['errores_harness']})")

    salida.write_text(json.dumps(
        {"fase1_frontier": frontier, "fase2_pool": pool, "resumen": resumen},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
