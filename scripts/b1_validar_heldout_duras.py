"""
b1_validar_heldout_duras.py — valida los held-outs A MANO del banco DURO
contra las páginas ya generadas. PREREG_GOAL_DURO_20260730.md, paso 3:
sin esta auditoría el número del goal NO se firma.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b1_validar_heldout_duras.py

Por cada página del corpus juzga con el contrato ORIGINAL y con el
HELD-OUT y lista los DESACUERDOS (uno aprueba, el otro no) con el detalle
del check que falló. Cada desacuerdo se audita a mano: o es bug del
held-out (se corrige y se declara) o es un fallo real que un examen ve y
el otro no. También reporta los checks del held-out que fallan en TODAS
las páginas — firma típica de una aserción mal escrita (la lección de
b1_validar_heldout_facil, que cazó 3 FN míos).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_duras.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout_duras.json"
CORPUS = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_bon_heldout_duro")


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia.presupuesto_pared import PresupuestoAgotado, con_presupuesto

    tareas = {t["id"]: t for t in
              json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    heldout = {t["id"]: t["contrato"] for t in
               json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}

    paginas = sorted(CORPUS.glob("*__r*__s*/index.html"))
    print(f"VALIDACION de los held-outs DUROS — {len(paginas)} paginas\n",
          flush=True)
    filas, desacuerdos = [], []
    fallos_por_check: dict = {}
    vistos_por_tarea: Counter = Counter()

    for p in paginas:
        tarea = p.parent.name.split("__")[0]
        if tarea not in heldout:
            continue
        vistos_por_tarea[tarea] += 1

        def _dos(ruta, o, h):
            return (juez_ejecutable.juzgar_web(ruta, o),
                    juez_ejecutable.juzgar_web(ruta, h))
        try:
            v, vh = con_presupuesto(300, _dos, p, tareas[tarea]["contrato"],
                                    heldout[tarea])
        except PresupuestoAgotado:
            print(f"  {p.parent.name:<28} juez colgado (JS bloqueante)",
                  flush=True)
            continue
        except Exception as exc:
            print(f"  {p.parent.name:<28} crash: {exc}"[:110], flush=True)
            continue
        for c in vh.checks:
            if c.nombre in ("carga", "sin_errores_js", "contenido",
                            "interactivo"):
                continue
            d = fallos_por_check.setdefault((tarea, c.nombre),
                                            {"n": 0, "falla": 0, "det": ""})
            d["n"] += 1
            if not c.ok:
                d["falla"] += 1
                d["det"] = c.detalle[:90]
        fila = {"pagina": p.parent.name, "tarea": tarea,
                "orig": bool(v.aprobado), "held": bool(vh.aprobado),
                "motivo_orig": (v.motivo or "")[:90],
                "motivo_held": (vh.motivo or "")[:90]}
        filas.append(fila)
        if fila["orig"] != fila["held"]:
            desacuerdos.append(fila)
        print(f"  {p.parent.name:<28} orig={'OK ' if fila['orig'] else 'no '}"
              f"held={'OK ' if fila['held'] else 'no '}"
              f"{'  <<< DESACUERDO' if fila['orig'] != fila['held'] else ''}",
              flush=True)

    print(f"\n{'=' * 72}")
    print(f"  paginas juzgadas: {len(filas)} | DESACUERDOS: "
          f"{len(desacuerdos)}")
    for f in desacuerdos:
        quien = "held-out reprueba" if f["orig"] else "original reprueba"
        motivo = f["motivo_held"] if f["orig"] else f["motivo_orig"]
        print(f"    {f['pagina']:<28} {quien}: {motivo}")
    print(f"\n  CHECKS DEL HELD-OUT QUE FALLAN SIEMPRE (sospecha de bug mio):")
    hay = False
    for (tarea, nombre), d in sorted(fallos_por_check.items()):
        if d["n"] >= 2 and d["falla"] == d["n"]:
            hay = True
            print(f"    {tarea:<18} {nombre[:40]:<40} {d['falla']}/{d['n']}"
                  f"  :: {d['det']}")
    if not hay:
        print("    (ninguno)")
    print(f"\n  cobertura por tarea: {dict(vistos_por_tarea)}")
    print(f"{'=' * 72}")
    salida = CORPUS.parent / "validacion_heldout_duras.json"
    salida.write_text(json.dumps(
        {"n": len(filas), "desacuerdos": desacuerdos, "filas": filas,
         "checks_siempre_fallan": [
             {"tarea": t, "check": n, "falla": d["falla"], "n": d["n"],
              "detalle": d["det"]}
             for (t, n), d in sorted(fallos_por_check.items())
             if d["n"] >= 2 and d["falla"] == d["n"]]},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
