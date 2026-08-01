# -*- coding: utf-8 -*-
"""
b3_rejuzga_grandes.py — re-juicio de los lotes `demasiado_grande` con tope
alto (enmienda 4 del DISENO_REFERENCIA_FRONTIER_20260731).

Mi juez "oficial" capa lotes a 8 MB / 120 s; el oficial real no capa nada.
Este script re-juzga SOLO las muestras cuyo `juez_oficial` empieza por
`demasiado_grande` o `lote_expirado`, con tope 64 MB y la fórmula de tiempo
oficial completa (7·n+5, sin el cap de 120 s), y escribe el resultado en
`b3_codigo/rejuicio_grandes.json` SIN tocar los ficheros originales.

El código de cada muestra: `frontier_60_raw.json` lo trae completo; en los
`factorial*.json` se re-extrae del `crudo` — solo si `chars <= 6000` (el
crudo se persiste truncado a 6000 y un código a medias no se juzga: se marca
`crudo_truncado` y fuera).

Control positivo pre-registrado: 2 tareas normales (lote < 8 MB) re-juzgadas
con el tope alto tienen que reproducir el veredicto del juez capado.

Sin GPU: subprocesos CPU. Corte por reloj (--minutos).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import SALIDA, carga_lcb, extract_code
from b3_factorial import DESDE, HASTA
from b3_oficial import casos_oficiales, juzga_oficial

MAX_BYTES_XL = 64_000_000
SEG_MAX_XL = 10_000          # en la práctica manda la fórmula 7n+5

# TODAS las celdas con juez oficial de la noche (revisión adversarial
# 2026-07-31 noche: la primera versión omitía mio_low, low198 y highxl — la
# lectura "estrato resuelto" habría salido de un re-juicio parcial).
FICHEROS = (
    ("factorial.json", "mio_low"),
    ("factorial.json", "oficial_low"),
    ("factorial_low2.json", "oficial_low"),
    ("factorial_low198.json", "oficial_low"),
    ("factorial_high2.json", "oficial_high"),
    ("factorial_highxl.json", "oficial_high"),
    ("frontier_resultados.json", "frontier_opus5"),
)
RAWS_FRONTIER = ("frontier_60_raw.json", "frontier_138_raw.json")


def _codigo_de(m: dict, raw_frontier: dict) -> tuple:
    """(codigo, motivo_si_no). El frontier trae el código completo en los
    raw; los factorial lo re-extraen del crudo si no está truncado."""
    if m["celda"] == "frontier_opus5":
        c = raw_frontier.get(m["tarea"])
        return (c, "") if c else (None, "sin_raw")
    if m.get("chars", 0) > 6000:
        return None, "crudo_truncado"
    code = extract_code(m.get("crudo") or "")
    return (code, "") if code else (None, "sin_codigo_en_crudo")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutos", type=int, default=150)
    args = ap.parse_args()

    pool = {str(t["task_id"]): t
            for t in carga_lcb(ficheros=("lcb_test5.jsonl", "lcb_test6.jsonl"))
            if DESDE <= t["fecha"] <= HASTA}
    raw_frontier = {}
    for nombre in RAWS_FRONTIER:
        p = SALIDA / nombre
        if p.exists():
            for m in json.loads(p.read_text(encoding="utf-8"))["muestras"]:
                raw_frontier[m["id"]] = m.get("codigo")

    pendientes = []
    for nombre, celda in FICHEROS:
        f = SALIDA / nombre
        if not f.exists():
            continue
        for m in json.loads(f.read_text(encoding="utf-8"))["muestras"]:
            if m.get("celda") != celda:
                continue
            jo = str(m.get("juez_oficial") or "")
            if jo.startswith(("demasiado_grande", "lote_expirado")):
                pendientes.append((nombre, m))
    print(f"[rej] {len(pendientes)} muestras con lote grande/expirado")

    # ---- controles: 2 que PASAN y 1 que FALLA con juez limpio, tope alto
    # tiene que reproducir el veredicto capado. Se exigen los 3 (revisión
    # adversarial: el guard viejo podía degradar a 0 controles y seguir, y
    # solo ejercitaba la polaridad 'pasa').
    ms_low = [m for m in json.loads(
        (SALIDA / "factorial.json").read_text(encoding="utf-8"))["muestras"]
        if m["celda"] == "oficial_low"
        and not str(m.get("juez_oficial") or "")
        and m.get("chars", 0) <= 6000]
    controles = ([m for m in ms_low if m["oficial_pasa"]][:2]
                 + [m for m in ms_low if not m["oficial_pasa"]][:1])
    validos = 0
    for m in controles:
        t = pool[m["tarea"]]
        code, mot = _codigo_de(m, raw_frontier)
        if code is None:
            print(f"[rej] control {m['tarea']}: sin código ({mot})")
            continue
        pasa, motivo = juzga_oficial(code, t, casos_oficiales(t),
                                     max_bytes=MAX_BYTES_XL,
                                     seg_max=SEG_MAX_XL)
        ok = bool(pasa) == bool(m["oficial_pasa"])
        validos += 1
        print(f"[rej] CONTROL {m['tarea']}: tope alto={pasa} vs "
              f"capado={m['oficial_pasa']} -> {'OK' if ok else 'DISCREPA'}")
        if not ok:
            print("ABORTA: el control discrepa — el tope alto no reproduce "
                  "al juez capado en lotes normales.")
            sys.exit(2)
    if validos < 3:
        print(f"ABORTA: solo {validos} controles válidos de 3 (2 pasa + "
              f"1 falla): el control positivo no se puede degradar.")
        sys.exit(2)

    destino = SALIDA / "rejuicio_grandes.json"
    res = {"experimento": "rejuicio_demasiado_grande",
           "diseno": "DISENO_REFERENCIA_FRONTIER (enmienda 4)",
           "max_bytes": MAX_BYTES_XL, "seg_max": "formula 7n+5 sin cap",
           "muestras": []}
    if destino.exists():
        res = json.loads(destino.read_text(encoding="utf-8"))
        # las no-rejuzgables NO cuentan como hechas: si aparece el raw que
        # faltaba, una re-corrida las reintenta (y su registro viejo se
        # retira para no duplicar)
        res["muestras"] = [m for m in res["muestras"] if m.get("rejuzgable")]
    hechas = {(m["fichero"], m["tarea"]) for m in res["muestras"]}

    t0 = time.time()
    for nombre, m in pendientes:
        if (nombre, m["tarea"]) in hechas:
            continue
        if (time.time() - t0) / 60 >= args.minutos:
            print(f"[rej] CORTE POR RELOJ a los {args.minutos} min")
            break
        t = pool.get(m["tarea"])
        code, mot = _codigo_de(m, raw_frontier)
        ts = time.time()
        if t is None or code is None:
            reg = {"fichero": nombre, "tarea": m["tarea"],
                   "celda": m["celda"], "rejuzgable": False,
                   "motivo": mot or "fuera_del_pool"}
        else:
            pasa, motivo = juzga_oficial(code, t, casos_oficiales(t),
                                         max_bytes=MAX_BYTES_XL,
                                         seg_max=SEG_MAX_XL)
            reg = {"fichero": nombre, "tarea": m["tarea"],
                   "celda": m["celda"], "rejuzgable": True,
                   "oficial_pasa_xl": bool(pasa), "motivo_xl": motivo,
                   "antes": m.get("juez_oficial"),
                   "segundos": round(time.time() - ts, 1)}
        res["muestras"].append(reg)
        import os
        tmp = destino.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, destino)
        print(f"[rej] {nombre:<24} {m['tarea']:<12} "
              f"{reg.get('oficial_pasa_xl', '-')} "
              f"({reg.get('motivo_xl', reg.get('motivo', ''))}) "
              f"{reg.get('segundos', 0)}s", flush=True)

    # resumen por celda
    from collections import defaultdict
    por = defaultdict(lambda: [0, 0])
    for m in res["muestras"]:
        if m.get("rejuzgable"):
            por[(m["fichero"], m["celda"])][0] += 1
            por[(m["fichero"], m["celda"])][1] += int(m["oficial_pasa_xl"])
    print("\n[rej] resumen (rejuzgadas, aprueban con tope alto):")
    for k, (n, ok) in sorted(por.items()):
        print(f"  {k[0]:<24} {k[1]:<16} {ok}/{n}")


if __name__ == "__main__":
    main()
