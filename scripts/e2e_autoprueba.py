# -*- coding: utf-8 -*-
"""E2E de AUTOPRUEBA — Cognia prueba end-to-end sus propios productos (2026-07-23).

Recorre cognia/program_creator/generated_programs/, corre CADA producto de
verdad (compila -> importa -> arranca, todo en subproceso con timeout) y le
pone nota 0-10 con desglose explicito. Es la verificacion POSTERIOR de la
biblioteca: evaluator.py puntua en el momento de generar y despues nadie
vuelve a mirar si lo archivado sigue funcionando.

Uso:
  PYTHONUTF8=1 PYTHONPATH=. venv312\\Scripts\\python.exe scripts\\e2e_autoprueba.py --limite 8
  ... --filtro dashboard --detalle

Salida: 'E2E AUTOPRUEBA: N/M productos arrancan'; exit 0 si ninguno tiene fallo
duro, 1 si alguno no compila / no importa / revienta al arrancar.
"""
import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognia.autoprueba import DIR_PRODUCTOS, descubrir_productos, probar_todos   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Cognia prueba sus propios productos")
    ap.add_argument("--limite", type=int, default=None, help="probar solo los primeros N")
    ap.add_argument("--filtro", default=None, help="substring de id/title/carpeta")
    ap.add_argument("--timeout", type=float, default=6.0, help="segundos por arranque")
    ap.add_argument("--detalle", action="store_true", help="imprimir el desglose de cada producto")
    ap.add_argument("--solo-codigo", action="store_true",
                    help="saltear las carpetas que solo tienen assets (input_images/)")
    args = ap.parse_args()

    todos = descubrir_productos()
    con_codigo = [p for p in todos if p["lenguaje"] != "vacio"]
    print(f"Biblioteca: {len(todos)} carpetas en {DIR_PRODUCTOS} "
          f"({len(con_codigo)} con codigo)", flush=True)

    t0 = time.time()

    def por_producto(ev):
        ok = ev["fallo_duro"] is None
        print(f"  [{'OK ' if ok else 'FAIL'}] {ev['id'][:44]:<44} "
              f"{ev['puntaje']:>5.1f}/10  ({ev['lenguaje']})"
              + (f"  <- fallo en '{ev['fallo_duro']}'" if not ok else ""), flush=True)
        if args.detalle:
            for k, v in ev["desglose"].items():
                print(f"           {k:<22} {v:>4.1f}", flush=True)
            for m in ev["motivos"]:
                print(f"           - {m[:150]}", flush=True)

    rep = probar_todos(limite=args.limite, filtro=args.filtro,
                       solo_codigo=args.solo_codigo,
                       timeout_arranque=args.timeout, al_terminar_uno=por_producto)

    n = rep["total"]
    fallidos = [e for e in rep["evaluaciones"] if e["fallo_duro"]]
    print(f"\n--- REPORTE ({n} productos, {time.time()-t0:.0f}s) ---", flush=True)
    print(f"  compilan       : {rep['compilan']}/{n}", flush=True)
    print(f"  arrancan       : {rep['arrancan']}/{n}", flush=True)
    print(f"  sin codigo     : {rep['sin_codigo']}", flush=True)
    print(f"  puntaje medio  : {rep['puntaje_medio']}/10", flush=True)
    print(f"  por lenguaje   : {rep['por_lenguaje']}", flush=True)
    if rep["top"]:
        print(f"  TOP  : {rep['top']['id']} ({rep['top']['puntaje']}/10) "
              f"| {rep['top']['motivo'][:120]}", flush=True)
    if rep["peor"]:
        print(f"  PEOR : {rep['peor']['id']} ({rep['peor']['puntaje']}/10) "
              f"| {rep['peor']['motivo'][:120]}", flush=True)

    print(f"\nE2E AUTOPRUEBA: {n - len(fallidos)}/{n} productos sin fallo duro", flush=True)
    if fallidos:
        print("FALLARON:", [(e["id"], e["fallo_duro"]) for e in fallidos], flush=True)
    sys.exit(1 if fallidos else 0)


if __name__ == "__main__":
    main()
