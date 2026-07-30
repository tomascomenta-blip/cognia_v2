"""
b2_varianza_juez.py — ¿cuánta varianza es del JUEZ? Re-juzgado triple de
páginas CONGELADAS. PREREG_VARIANZA_JUEZ_20260730.md: leerlo ANTES. Cero GPU.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_varianza_juez.py

Toma las 24 páginas del brazo LAZO de b2_lazo_vs_replay (veredicto ya
medido = evaluación #1), las re-juzga 2 veces más con el mismo código y
mide cuántas quedan NO UNÁNIMES. Si el juez es determinista, la varianza
observada esta semana es del GENERADOR y las conclusiones apareadas se
sostienen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

FUENTE = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_lazo_vs_replay")
TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
EVALUACIONES_EXTRA = 2


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia.presupuesto_pared import PresupuestoAgotado, con_presupuesto

    tareas = {t["id"]: t for t in
              json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    heldout = {t["id"]: t["contrato"] for t in
               json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    res_fuente = json.loads((FUENTE / "resultados.json")
                            .read_text(encoding="utf-8"))

    filas = []
    for c in res_fuente["celdas"]:
        p = FUENTE / f"{c['tarea']}__r{c['rep']}" / "lazo" / "index.html"
        if not p.is_file():
            continue
        filas.append({"pagina": f"{c['tarea']}:r{c['rep']}",
                      "tarea": c["tarea"], "ruta": p,
                      "eval1_estricto": bool(c.get("estricto_lazo")),
                      "eval1_orig": bool(c.get("orig_lazo"))})
    print(f"VARIANZA DEL JUEZ — {len(filas)} paginas congeladas, "
          f"{EVALUACIONES_EXTRA} re-juzgados c/u\n", flush=True)

    def _juzgar(ruta, orig, held):
        v = juez_ejecutable.juzgar_web(ruta, orig)
        vh = juez_ejecutable.juzgar_web(ruta, held)
        return v, vh

    for f in filas:
        f["evals_estricto"] = [f["eval1_estricto"]]
        f["evals_orig"] = [f["eval1_orig"]]
        f["evals_held"] = []
        f["checks_ok"] = []
        for k in range(EVALUACIONES_EXTRA):
            try:
                v, vh = con_presupuesto(300, _juzgar, f["ruta"],
                                        tareas[f["tarea"]]["contrato"],
                                        heldout[f["tarea"]])
                f["evals_estricto"].append(bool(v.aprobado and vh.aprobado))
                f["evals_orig"].append(bool(v.aprobado))
                f["evals_held"].append(bool(vh.aprobado))
                f["checks_ok"].append(sum(1 for c in v.checks if c.ok))
            except PresupuestoAgotado:
                f["evals_estricto"].append(None)
                f["evals_orig"].append(None)
                f["evals_held"].append(None)
                f["checks_ok"].append(-1)
            except Exception as exc:
                f["evals_estricto"].append(None)
                f["evals_orig"].append(None)
                f["evals_held"].append(None)
                f["checks_ok"].append(-1)
                f["error"] = f"{exc}"[:80]
        f["unanime"] = len(set(f["evals_estricto"])) == 1
        f["unanime_orig"] = len(set(f["evals_orig"])) == 1
        f["unanime_held"] = len(set(f["evals_held"])) <= 1
        f["ruta"] = str(f["ruta"])
        print(f"  {f['pagina']:<20} estricto={f['evals_estricto']} "
              f"checks_ok={f['checks_ok']} "
              f"{'' if f['unanime'] else '<<< NO UNANIME'}", flush=True)

    no_un = [f for f in filas if not f["unanime"]]
    no_un_o = [f for f in filas if not f["unanime_orig"]]
    no_un_h = [f for f in filas if not f["unanime_held"]]
    # ¿el ruido vive en los checks (conteos que bailan) aunque el veredicto
    # aguante? Señal temprana de inestabilidad aunque el binario coincida.
    checks_varian = [f for f in filas
                     if len(set(c for c in f["checks_ok"] if c >= 0)) > 1]
    n = len(filas)
    print(f"\n{'=' * 70}")
    print(f"  NO UNANIMES (estricto): {len(no_un)}/{n} "
          f"= {len(no_un)/max(1,n)*100:.0f}%   "
          f"(prereg: <=1 juez ESTABLE; 2-3 ruido moderado; >=4 INESTABLE)")
    print(f"    por contrato original: {len(no_un_o)}/{n} | "
          f"por held-out: {len(no_un_h)}/{n}")
    print(f"    paginas cuyo checks_ok VARIA entre evaluaciones: "
          f"{len(checks_varian)}/{n}")
    if no_un:
        print(f"    detalle: "
              + ", ".join(f"{f['pagina']}{f['evals_estricto']}"
                          for f in no_un))
    print(f"{'=' * 70}")
    salida = FUENTE.parent / "varianza_juez.json"
    salida.write_text(json.dumps(
        {"n": n, "no_unanimes": len(no_un),
         "no_unanimes_original": len(no_un_o),
         "no_unanimes_heldout": len(no_un_h),
         "checks_varian": len(checks_varian),
         "detalle_no_unanimes": [f["pagina"] for f in no_un],
         "filas": filas}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
