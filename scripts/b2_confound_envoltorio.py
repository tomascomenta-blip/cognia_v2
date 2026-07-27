"""
b2_confound_envoltorio.py — ¿el 17% del sistema en el banco brutal es el
ENVOLTORIO del lazo, o deriva de la noche?

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_confound_envoltorio.py [n]

CONTEXTO (2026-07-27 ~21:45): el sistema real saco 2/12 (17%) en el banco
brutal; el pass@1 del modelo CRUDO en ese banco es 75% — pero se midio OTRA
noche, y hoy aprendimos que la deriva entre noches es del tamaño de los
efectos que buscamos (tres series n=6: 4.5 / 3.17 / 3.33). Antes de firmar
"el envoltorio resta", reproducir las condiciones: n muestras DIRECTAS por
tarea (la idea pelada por _call_llm, sin brief ni TARGET LOOK ni lazo),
ESTA noche, contra ESTE server, juzgadas por el MISMO juez.

- Si el directo-de-hoy ronda el 75%: la brecha es del ENVOLTORIO (accionable:
  probar el lazo sin adornos en la idea).
- Si el directo-de-hoy tambien se hunde: la brecha era deriva (server/estado)
  y el envoltorio queda sin cargo.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_confound_envoltorio")


def _cargar(nombre: str):
    spec = importlib.util.spec_from_file_location(
        nombre, RAIZ / "scripts" / f"{nombre}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list) -> int:
    n = int(argv[0]) if argv else 3
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    oraculo = _cargar("b1_router_oraculo")
    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    SALIDA.mkdir(parents=True, exist_ok=True)

    res: dict = {}
    aprobadas = total = 0
    for t in tareas:
        filas = []
        for rep in range(1, n + 1):
            d = SALIDA / f"{t['id']}__r{rep}"
            d.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            html = oraculo.generar_html(t["idea"])
            segs = time.time() - t0
            if not html:
                filas.append({"rep": rep, "aprobado": False,
                              "motivo": "sin HTML", "segundos": segs})
                print(f"  {t['id']} r{rep}: SIN HTML ({segs:.0f}s)",
                      flush=True)
                total += 1
                continue
            (d / "index.html").write_text(html, encoding="utf-8")
            v = juez_ejecutable.juzgar_web(d / "index.html", t["contrato"])
            filas.append({"rep": rep, "aprobado": v.aprobado,
                          "checks_ok": sum(1 for c in v.checks if c.ok),
                          "checks": len(v.checks),
                          "motivo": v.motivo[:100], "segundos": segs})
            total += 1
            aprobadas += bool(v.aprobado)
            print(f"  {t['id']} r{rep}: "
                  f"{'APROBADO' if v.aprobado else 'FALLIDO'} "
                  f"({sum(1 for c in v.checks if c.ok)}/{len(v.checks)}, "
                  f"{segs:.0f}s)", flush=True)
        res[t["id"]] = filas

    print(f"\nDIRECTO (sin envoltorio), esta noche: {aprobadas}/{total} "
          f"({100 * aprobadas / max(total, 1):.0f}%)")
    (SALIDA / "resultados.json").write_text(
        json.dumps({"n_por_tarea": n, "aprobadas": aprobadas,
                    "total": total, "detalle": res},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
