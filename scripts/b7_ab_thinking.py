# -*- coding: utf-8 -*-
"""b7_ab_thinking.py — ¿el razonamiento de Nemotron paga lo que cuesta?

EL EJE. El chat template de Nemotron 3.5 arranca con `enable_thinking=True`.
Medido el 2026-08-14 sobre el mismo tool call: con pensamiento 44-256 tokens
y 3,5-16,6 s; sin pensamiento **24 tokens y 1,6 s**. Para un bucle de agente
que da muchos pasos, eso es mucha latencia acumulada — pero apagarlo puede
costar ACIERTO, y esa es justo la parte que no estaba medida. Hasta hoy el
default es lo que el modelo trae entrenado (on), declarado como hipótesis.

EL INSTRUMENTO. El gate del camino feliz del repo (`e2e_happy_path.py`): 5
tareas con postcondición comprobada **en DISCO**, no contra lo que el modelo
diga. Un modelo que responde "listo" sin tocar el workspace reprueba.

EL DISEÑO. Brazos INTERCALADOS (on, off, on, off, ...) y no en bloques: si la
máquina se degrada con el tiempo, en bloques el degradado se lo come entero
el último brazo. Se reportan aciertos Y segundos: si `off` empata en acierto
y baja la pared, gana; si pierde acierto, el ahorro no vale.

POTENCIA, declarada ANTES de mirar: con 5 tareas por corrida y N corridas por
brazo, esto detecta un colapso (5/5 -> 2/5), NO una diferencia fina. Un delta
de una sola tarea NO es un resultado: es ruido.

Uso:  venv312\\Scripts\\python.exe scripts\\b7_ab_thinking.py --corridas 2
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def una_corrida(thinking: str) -> tuple:
    """Corre el gate con COGNIA_THINKING fijado. Devuelve (aciertos, seg)."""
    env = dict(os.environ)
    env["COGNIA_THINKING"] = thinking
    env["PYTHONUTF8"] = "1"
    t0 = time.time()
    p = subprocess.run(
        [str(RAIZ / "venv312" / "Scripts" / "python.exe"),
         str(RAIZ / "scripts" / "e2e_happy_path.py")],
        capture_output=True, text=True, env=env, cwd=str(RAIZ),
        encoding="utf-8", errors="replace", timeout=5400)
    dt = time.time() - t0
    salida = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"E2E CAMINO FELIZ: (\d+)/(\d+)", salida)
    aciertos = int(m.group(1)) if m else -1
    return aciertos, dt, salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corridas", type=int, default=2,
                    help="corridas POR BRAZO (van intercaladas)")
    ap.add_argument("--salida", default="b7_ab_thinking.txt")
    args = ap.parse_args()

    filas, log = [], []
    for i in range(args.corridas):
        for brazo in ("on", "off"):      # INTERCALADOS
            print(f"[{i+1}/{args.corridas}] thinking={brazo} ...", flush=True)
            aciertos, dt, salida = una_corrida(brazo)
            filas.append((brazo, aciertos, dt))
            log.append(f"===== corrida {i+1} thinking={brazo} "
                       f"({aciertos}/5 en {dt/60:.1f} min) =====\n{salida}")
            print(f"    {aciertos}/5 en {dt/60:.1f} min", flush=True)

    print("\n" + "=" * 54)
    print(f"{'brazo':>8} {'aciertos':>20} {'min/corrida':>14}")
    for brazo in ("on", "off"):
        f = [x for x in filas if x[0] == brazo]
        if not f:
            continue
        detalle = " ".join(f"{a}/5" for _, a, _ in f)
        media = sum(d for _, _, d in f) / len(f) / 60
        print(f"{brazo:>8} {detalle:>20} {media:>14.1f}")
    print("\nRecordatorio de potencia: con este n, un delta de UNA tarea es "
          "ruido. Solo un colapso (5/5 -> 2/5) es senal.")
    Path(args.salida).write_text("\n\n".join(log), encoding="utf-8")
    print(f"log completo -> {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
