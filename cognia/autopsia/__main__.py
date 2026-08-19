"""
cognia/autopsia/__main__.py
===========================
QUE RESUELVE: poder correr el replay desde la consola sin escribir un guion.
`python -m cognia.autopsia <traza.jsonl|traza.json> [--hasta N] [--saltar i]`.

POR QUE EXISTE: la regla del repo es "codigo que corre o no cuenta". Un modulo
de replay al que solo se llega desde tests es una promesa; con esta entrada un
humano abre una grabacion real y ve pasos, ms, fuentes y huella.

NO tiene modo REAL a proposito: re-ejecutar una trayectoria desde la linea de
comandos, con un flag, es la forma mas facil de borrar algo por accidente. El
modo real se pide desde codigo, pasando run_tool_fn y ws explicitos.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from cognia.autopsia import replay as R


def _cargar(ruta: Path):
    if ruta.suffix.lower() == ".jsonl":
        return R.cargar_jsonl(ruta)
    return R.normalizar(json.loads(ruta.read_text(encoding="utf-8")))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    ruta = Path(argv[0])
    if not ruta.exists():
        print(f"ERROR: no existe {ruta}")
        return 2
    hasta = saltar = None
    for i, a in enumerate(argv):
        if a == "--hasta" and i + 1 < len(argv):
            hasta = int(argv[i + 1])
        if a == "--saltar" and i + 1 < len(argv):
            saltar = int(argv[i + 1])

    t = _cargar(ruta)
    print(f"trayectoria: origen={t.origen} pasos={len(t)} huella={R.huella(t)}")
    for aviso in t.avisos:
        print(f"  aviso: {aviso}")
    cache = R.grabar_resultados(t)
    inf = R.reproducir(t, hasta=hasta, cache=cache)
    print("replay: " + R.resumen_linea(inf))
    for p in inf["pasos"]:
        print(f"  {p['i']:>3} [{p['fuente']:<9}] {'ok ' if p['ok'] else 'FAIL'} "
              f"{p['tool']:<18} {p['args'][:46]!r}")
    det = R.verificar_determinismo(t, cache, hasta=hasta)
    print(f"determinismo: {det['determinista']} (huellas {set(det['huellas'])})")

    if saltar is not None:
        ab = R.ablacionar(t, saltar, "saltar")
        d = R.divergencia(t, ab)
        inf2 = R.reproducir(ab, cache=cache)
        print(f"ablacion saltar({saltar}): pasos {len(t)}->{len(ab)} "
              f"huella {R.huella(t)}->{R.huella(ab)} es_real={ab.es_real}")
        print(f"  divergencia: paso={d['paso']} campo={d['campo']} {d['motivo']}")
        print("  replay ablacionado: " + R.resumen_linea(inf2))
    return 0 if inf["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
