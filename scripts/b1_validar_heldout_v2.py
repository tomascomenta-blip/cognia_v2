"""
b1_validar_heldout_v2.py — ¿el held-out ENDURECIDO discrepa del contrato
original? Cero GPU: juzga las 64 páginas ya guardadas (r1 + r2).

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b1_validar_heldout_v2.py

El v1 no discrepó ni una vez en 64 páginas, así que el "juez estricto" era
de facto el contrato original (caveat 2 del RESULTADO del goal). Esto mide
si el v2 —escrito para atacar SOLO los huecos que el original no cubre—
encuentra fallos que el original deja pasar, y qué le hace eso al 8/8.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_duras.json"
HELDOUT_V1 = RAIZ / "scripts" / "b1_contratos_heldout_duras.json"
HELDOUT_V2 = RAIZ / "scripts" / "b1_contratos_heldout_duras_v2.json"
GEN = RAIZ / "cognia" / "program_creator" / "generated_programs"
CORPUS = [GEN / "b2_bon_heldout_duro", GEN / "b2_bon_heldout_duro_r2"]


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia.presupuesto_pared import PresupuestoAgotado, con_presupuesto

    tareas = {t["id"]: t for t in
              json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    hv1 = {t["id"]: t["contrato"] for t in
           json.loads(HELDOUT_V1.read_text(encoding="utf-8"))["tareas"]}
    hv2 = {t["id"]: t["contrato"] for t in
           json.loads(HELDOUT_V2.read_text(encoding="utf-8"))["tareas"]}

    paginas = []
    for c in CORPUS:
        paginas += sorted(c.glob("*__r*__s*/index.html"))
    print(f"HELD-OUT v2 vs ORIGINAL — {len(paginas)} paginas congeladas\n",
          flush=True)

    filas = []
    fallos_check: dict = {}
    for p in paginas:
        tarea = p.parent.name.split("__")[0]
        if tarea not in hv2:
            continue

        def _tres(ruta, o, a, b):
            return (juez_ejecutable.juzgar_web(ruta, o),
                    juez_ejecutable.juzgar_web(ruta, a),
                    juez_ejecutable.juzgar_web(ruta, b))
        try:
            v, v1, v2 = con_presupuesto(400, _tres, p,
                                        tareas[tarea]["contrato"],
                                        hv1[tarea], hv2[tarea])
        except PresupuestoAgotado:
            print(f"  {p.parent.name:<26} juez colgado", flush=True)
            continue
        except Exception as exc:
            print(f"  {p.parent.name:<26} crash: {exc}"[:100], flush=True)
            continue
        for c in v2.checks:
            if c.nombre in ("carga", "sin_errores_js", "contenido",
                            "interactivo"):
                continue
            d = fallos_check.setdefault((tarea, c.nombre),
                                        {"n": 0, "falla": 0, "det": ""})
            d["n"] += 1
            if not c.ok:
                d["falla"] += 1
                d["det"] = (c.detalle or "")[:80]
        f = {"pagina": p.parent.name, "corpus": p.parent.parent.name,
             "tarea": tarea, "orig": bool(v.aprobado),
             "v1": bool(v1.aprobado), "v2": bool(v2.aprobado),
             "motivo_v2": (v2.motivo or "")[:100]}
        filas.append(f)
        marca = ""
        if f["orig"] and not f["v2"]:
            marca = "  <<< v2 CAZA lo que el original deja pasar"
        elif f["v2"] and not f["orig"]:
            marca = "  <<< el original reprueba y v2 no"
        print(f"  {p.parent.name:<26} orig={'OK' if f['orig'] else 'no':<3}"
              f"v1={'OK' if f['v1'] else 'no':<3}"
              f"v2={'OK' if f['v2'] else 'no':<3}{marca}", flush=True)

    caza = [f for f in filas if f["orig"] and not f["v2"]]
    inv = [f for f in filas if f["v2"] and not f["orig"]]
    print(f"\n{'=' * 74}")
    print(f"  paginas: {len(filas)}")
    print(f"  aprueba original: {sum(1 for f in filas if f['orig'])}/{len(filas)}"
          f" | v1: {sum(1 for f in filas if f['v1'])}/{len(filas)}"
          f" | v2: {sum(1 for f in filas if f['v2'])}/{len(filas)}")
    print(f"  v2 CAZA (orig OK, v2 no): {len(caza)}  <- lo que el v1 no hacia")
    for f in caza:
        print(f"     {f['pagina']:<26} [{f['corpus'][-2:]}] {f['motivo_v2']}")
    print(f"  v2 aprueba y original no: {len(inv)}")
    print(f"\n  CHECKS DE v2 QUE FALLAN SIEMPRE (sospecha de bug mio):")
    hay = False
    for (t, n), d in sorted(fallos_check.items()):
        if d["n"] >= 4 and d["falla"] == d["n"]:
            hay = True
            print(f"     {t:<18}{n[:44]:<44}{d['falla']}/{d['n']} :: {d['det']}")
    if not hay:
        print("     (ninguno)")
    print(f"{'=' * 74}")
    salida = GEN / "validacion_heldout_v2.json"
    salida.write_text(json.dumps(
        {"n": len(filas), "caza": caza, "inversos": inv, "filas": filas,
         "checks_siempre_fallan": [
             {"tarea": t, "check": n, **d}
             for (t, n), d in sorted(fallos_check.items())
             if d["n"] >= 4 and d["falla"] == d["n"]]},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
