"""
b2_banco_brutal.py — el banco BRUTAL por el SISTEMA REAL (primera medicion).

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_banco_brutal.py
        [--tareas id1,id2] [--candidatos N] [--rondas-progreso N]

QUE MIDE: b2_sistema_real corre el banco facil de 6 (saturado por el pool);
el examen verdadero del lazo con juez son las 4 tareas COMPOSICIONALES de
b1_tareas_brutales.json. Baseline del sistema real sobre ellas: NO EXISTE —
esta corrida es la primera. Referencias del pool (mismo hardware, sin lazo):
gpt-oss-20b pass@1 75%, pass@6 100%; y el FP del contrato esta medido
(PREREG_FP_CONTRATO_20260725.md: gpt-oss 0/18), asi que el numero que salga
es una medida, no un techo.

Cada producto se juzga con el contrato ORIGINAL y, si aprueba, tambien con el
HELD-OUT (b1_contratos_heldout.json, validado contra frontier): un aprobado
que falla el held-out se reporta aparte — paso el examen y no la materia.

Reusa correr_sistema de b2_sistema_real.py (mismo camino de produccion, misma
meta de atribucion bon/rondas/sello); scripts/ no es paquete, se carga por
ruta con importlib.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_banco_brutal")


def _cargar_b2():
    spec = importlib.util.spec_from_file_location(
        "b2_sistema_real", RAIZ / "scripts" / "b2_sistema_real.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    b2 = _cargar_b2()

    datos = json.loads(TAREAS.read_text(encoding="utf-8"))
    tareas = datos["tareas"]
    heldout = {t["id"]: t["contrato"]
               for t in json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    if "--tareas" in argv:
        pedidas = argv[argv.index("--tareas") + 1].split(",")
        tareas = [t for t in tareas if t["id"] in pedidas]

    def _flag_entero(nombre: str):
        if nombre not in argv:
            return None
        try:
            return int(argv[argv.index(nombre) + 1])
        except (IndexError, ValueError):
            print(f"uso: {nombre} <entero>", file=sys.stderr)
            raise SystemExit(2)

    candidatos = _flag_entero("--candidatos") or 1
    rondas_progreso = _flag_entero("--rondas-progreso")
    max_rondas = _flag_entero("--max-rondas")
    print(f"Banco BRUTAL por el sistema real — {len(tareas)} tareas "
          f"(candidatos={candidatos}, rondas_progreso={rondas_progreso}, "
          f"max_rondas={max_rondas})\n",
          flush=True)

    SALIDA.mkdir(parents=True, exist_ok=True)
    reales: dict = {}
    for t in tareas:
        d = SALIDA / t["id"]
        d.mkdir(parents=True, exist_ok=True)
        print(f"  {t['id']} ...", flush=True)
        html, segs, como, meta = b2.correr_sistema(
            t["idea"], d, candidatos=candidatos,
            rondas_progreso=rondas_progreso, max_rondas=max_rondas)
        if not html:
            reales[t["id"]] = {"aprobado": False, "motivo": "sin HTML",
                               "segundos": segs, "como": como, **meta}
            print(f"    SIN HTML ({segs:.0f}s, via {como})", flush=True)
            continue
        (d / "index.html").write_text(html, encoding="utf-8")
        v = juez_ejecutable.juzgar_web(d / "index.html", t["contrato"])
        fila = {"aprobado": v.aprobado, "motivo": v.motivo[:120],
                "segundos": segs, "como": como,
                "checks_ok": sum(1 for c in v.checks if c.ok),
                "checks": len(v.checks), **meta}
        # El held-out solo se corre sobre aprobados: mide FP, no FN.
        if v.aprobado and t["id"] in heldout:
            vh = juez_ejecutable.juzgar_web(d / "index.html", heldout[t["id"]])
            fila["aprobado_heldout"] = vh.aprobado
            fila["heldout_motivo"] = vh.motivo[:120]
        reales[t["id"]] = fila
        sufijo = ""
        if "aprobado_heldout" in fila:
            sufijo = ("  [held-out OK]" if fila["aprobado_heldout"]
                      else "  [HELD-OUT FALLA: paso el examen, no la materia]")
        print(f"    {'APROBADO' if v.aprobado else 'FALLIDO '} "
              f"({segs:.0f}s, via {como}){sufijo}", flush=True)

    n = len(tareas)
    aprob = sum(1 for r in reales.values() if r.get("aprobado"))
    limpios = sum(1 for r in reales.values()
                  if r.get("aprobado") and r.get("aprobado_heldout", True))
    print(f"\n{'=' * 70}")
    print(f"  BANCO BRUTAL x SISTEMA REAL : {aprob}/{n} aprobados por contrato"
          f"  ({limpios}/{n} sobreviven el held-out)")
    print(f"{'=' * 70}")

    salida = SALIDA / "resultados.json"
    salida.write_text(json.dumps(
        {"config": {"candidatos": candidatos,
                    "rondas_progreso": rondas_progreso,
                    "max_rondas": max_rondas},
         "sistema_real": reales, "aprobados": aprob,
         "aprobados_heldout": limpios, "n_tareas": n},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
