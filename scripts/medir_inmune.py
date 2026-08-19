# -*- coding: utf-8 -*-
"""MEDICION del sistema inmune: coste real de `evaluar` + contrafactual de los tests.

POR QUE EXISTE
--------------
`cognia/inmune/anticuerpos.py:evaluar` es el UNICO codigo que corre en cada tool
call del agente. Un numero declarado ahi no vale nada (regla del repo: "el coste
se MIDE, nunca se declara"), asi que la cabecera del modulo cita ESTE guion.

Y la segunda mitad: una suite que pasa 32/32 a la primera es sospechosa en este
repo ("el test que pasa por el motivo EQUIVOCADO"). El modo `--contrafactual`
rompe el modulo a proposito, de siete maneras distintas, y comprueba que los
tests LO NOTAN. Un mutante que sobrevive es un test que no protegia nada.

USO
    ./venv312/Scripts/python.exe scripts/medir_inmune.py
    ./venv312/Scripts/python.exe scripts/medir_inmune.py --contrafactual
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

MODULO = RAIZ / "cognia" / "inmune" / "anticuerpos.py"
TESTS = RAIZ / "tests" / "test_inmune_anticuerpos.py"


# ── Parte 1: el coste ─────────────────────────────────────────────────────────

def _antibody(i: int) -> dict:
    return {
        "id": f"ab-perf-{i}",
        "nombre": f"perf {i}",
        "origen": {"trayectoria": "perf", "paso": i},
        "disparador": {"tool": "ejecutar", "patron_args": None, "contexto": {}},
        "chequeo": {"tipo": "patron_args", "patron": f"prohibido_{i}"},
        "remedio": "no lo hagas",
        "estado": "activo",
        "creado": "2026-08-19T00:00:00",
        "aciertos": 0, "falsos_positivos": 0, "ultima_vez": None,
    }


def medir() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="inmune_med_"))
    os.environ["COGNIA_INMUNE_DIR"] = str(tmp)
    os.environ["COGNIA_INMUNE_TTL"] = "1.0"     # el valor de PRODUCCION
    from cognia.inmune import anticuerpos as ac

    try:
        ac.recargar()
        ac._guardar([_antibody(i) for i in range(50)])
        assert len(ac.activos()) == 50, "el andamiaje no dejo 50 activos"

        escenarios = [
            # (etiqueta, tool, args, ctx, espera_veto)
            ("PASA  (recorre los 50 sin cortar)", "ejecutar",
             "pytest -q tests/ --maxfail=1", {}, False),
            ("VETO  (dispara el ultimo del indice)", "ejecutar",
             "correr prohibido_49 ahora", {}, True),
            ("tool SIN anticuerpos (corte rapido)", "leer_archivo",
             "README.md", {}, False),
        ]
        n = 1000
        print(f"MEDICION DEL CAMINO CALIENTE — {len(ac.activos())} anticuerpos "
              f"activos, {n} llamadas por escenario")
        print(f"  python : {sys.version.split()[0]}   almacen: {ac.ruta_almacen()}")
        peor = 0.0
        for etiqueta, tool, args, ctx, espera in escenarios:
            r = ac.evaluar(tool, args, ctx)                 # calienta regex/cache
            assert bool(r) is espera, f"escenario '{etiqueta}' no hizo lo que dice"
            t0 = time.perf_counter()
            for _ in range(n):
                ac.evaluar(tool, args, ctx)
            us = (time.perf_counter() - t0) / n * 1e6
            peor = max(peor, us)
            print(f"  {etiqueta:38s} {us:8.2f} us/llamada")
        print(f"\n  PRESUPUESTO: ~1000 us (1 ms) por llamada.")
        print(f"  PEOR CASO MEDIDO: {peor:.2f} us  ->  "
              f"{'CABE en el camino caliente' if peor < 1000 else 'NO CABE: hay que sacarlo del camino caliente'}")
        return 0 if peor < 1000 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Parte 2: el contrafactual de los tests ────────────────────────────────────
#
# Cada mutante rompe UNA garantia. Si la suite sigue en verde, ese test no
# protegia nada y hay que escribirlo mejor.

MUTANTES = [
    ("la compuerta: activar sin examen",
     'nuevo["estado"] = "cuarentena"      # nace SIEMPRE',
     'nuevo["estado"] = "activo"      # nace SIEMPRE'),
    ("la compuerta: tolerar UN falso positivo",
     'elif res["falsos_positivos"]:',
     'elif len(res["falsos_positivos"]) > 1:'),
    ("la compuerta: activar aunque escape un positivo",
     "elif escapados:",
     "elif False:"),
    ("sintetizar: inventar prosa en vez de devolver None",
     "        if chequeo is None:\n            return None   # NO se inventa",
     '        if chequeo is None:\n            chequeo = {"tipo": "patron_args", "patron": "."}   # NO se inventa'),
    ("evaluar: ignorar el estado y vetar desde cuarentena",
     'if ab.get("estado") != "activo":\n            continue',
     'if False:\n            continue'),
    ("retiro automatico: no retirar nunca",
     'if ab["falsos_positivos"] >= _max_fp():',
     'if ab["falsos_positivos"] >= 10 ** 9:'),
    ("persistencia: no escribir el JSON",
     "    os.replace(str(tmp), str(ruta))",
     "    tmp.unlink()"),
    ("leido_antes: comparar rutas sin normalizar NTFS",
     "        return os.path.normcase(os.path.normpath(",
     "        return (str("),
    ("comando_prohibido: exigir subcadena contigua",
     "    pos = 0\n    for t in aguja.split():",
     "    return aguja in pajar\n    pos = 0\n    for t in aguja.split():"),
]


def contrafactual() -> int:
    original = MODULO.read_text(encoding="utf-8")
    print("CONTRAFACTUAL — se rompe el modulo a proposito y se mira si los tests LO NOTAN\n")
    sobrevivientes = []
    try:
        for etiqueta, viejo, nuevo in MUTANTES:
            if viejo not in original:
                print(f"  [ROTO EL GUION] no encuentro el ancla de '{etiqueta}'")
                sobrevivientes.append(etiqueta)
                continue
            MODULO.write_text(original.replace(viejo, nuevo, 1), encoding="utf-8")
            r = subprocess.run(
                [str(RAIZ / "venv312" / "Scripts" / "python.exe"), "-m", "pytest",
                 str(TESTS), "-q", "--no-header", "-p", "no:cacheprovider"],
                cwd=str(RAIZ), capture_output=True, text=True,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            cazado = r.returncode != 0
            cola = [l for l in r.stdout.strip().splitlines() if l.strip()][-1:]
            print(f"  [{'CAZADO ' if cazado else 'SOBREVIVE'}] {etiqueta:52s} {cola[0] if cola else ''}")
            if not cazado:
                sobrevivientes.append(etiqueta)
    finally:
        MODULO.write_text(original, encoding="utf-8")

    print(f"\n  {len(MUTANTES) - len(sobrevivientes)}/{len(MUTANTES)} mutantes cazados")
    if sobrevivientes:
        print("  SOBREVIVEN (tests que no protegen lo que dicen):")
        for s in sobrevivientes:
            print(f"    - {s}")
    return 1 if sobrevivientes else 0


if __name__ == "__main__":
    if "--contrafactual" in sys.argv:
        raise SystemExit(contrafactual())
    raise SystemExit(medir())
