# -*- coding: utf-8 -*-
"""Cuantos DATOS puede integrar en una respuesta, no cuantos puede encontrar.

POR QUE (2026-08-13): `rlm_escala.py` mide ALCANCE — una aguja literal en hasta
300M tokens, con cobertura del 0,0001%. Eso responde "¿lo encuentra?", no
"¿cuantos datos puede USAR a la vez?". Son preguntas distintas y la segunda es la
que decide si sirve para trabajar: localizar una constante es util, pero sumar
doce valores dispersos es lo que se parece a razonar sobre un proyecto.

Hipotesis a falsar (apuesta firmada ANTES de medir): el RLM amplia el ALCANCE, no
la MEMORIA DE TRABAJO. Todo lo recuperado vuelve a la ventana del raiz para
combinarse alli, asi que el numero de datos integrables deberia parecerse al del
modelo solo, y romperse entre 8 y 16 agujas.

Protocolo: pajar fijo, N agujas numericas dispersas uniformemente, pregunta =
SUMAR las N. Acierto ESTRICTO (el total exacto). Se compara el mismo N por dos
vias: con RLM y —cuando el pajar cabe— con prompt directo, para separar lo que
aporta el RLM de lo que ya hacia el modelo.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\rlm_integracion.py [Ns...]
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEED = 20260813
URL = "http://127.0.0.1:8080"
CHARS_PAJAR = 2_000_000          # ~500k tokens: 2,5x la ventana, RLM obligatorio
NS = [2, 4, 8, 16, 32]

_FRASES = [
    "El turno {n} cerro sin incidencias segun el parte de la guardia.",
    "La medicion {n} quedo archivada junto al resto del lote.",
    "El informe {n} sigue pendiente de revision tecnica.",
    "Se anoto que el canal {n} mantuvo su nivel previsto.",
]


def _pajar(ruta: Path, n_agujas: int):
    """Escribe el pajar con n agujas repartidas uniformemente. Devuelve valores."""
    random.seed(SEED + n_agujas)
    valores = [random.randint(100, 999) for _ in range(n_agujas)]
    cortes = [int(CHARS_PAJAR * (i + 0.5) / n_agujas) for i in range(n_agujas)]
    acum, i, idx = 0, 0, 0
    buf, buf_len = [], 0
    with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
        while acum < CHARS_PAJAR:
            if idx < n_agujas and acum >= cortes[idx]:
                linea = (f"REGISTRO CRITICO numero {idx + 1}: el contador "
                         f"marco {valores[idx]} unidades.")
                idx += 1
            else:
                linea = random.choice(_FRASES).format(n=i)
                i += 1
            buf.append(linea)
            buf_len += len(linea) + 1
            acum += len(linea) + 1
            if buf_len >= 4_000_000:
                fh.write("\n".join(buf) + "\n")
                buf, buf_len = [], 0
        if buf:
            fh.write("\n".join(buf) + "\n")
    return valores


def _pregunta(n: int) -> str:
    return (f"En el texto hay {n} lineas que empiezan por 'REGISTRO CRITICO', "
            f"numeradas del 1 al {n}, cada una con un valor de unidades. "
            f"Suma los {n} valores y responde SOLO con el numero total.")


def main() -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.agent.model_profiles import url_del_backend
    from cognia.agent.rlm import correr_rlm

    url = url_del_backend()
    ns = [int(a) for a in sys.argv[1:]] or NS
    print(f"pajar fijo: {CHARS_PAJAR:,} chars (~{CHARS_PAJAR//4:,} tokens)")
    print(f"{'agujas':>7} {'esperado':>9} {'resultado':>10} {'seg':>6} "
          f"{'tokens':>9} {'hijos':>6}")
    print("-" * 54)

    filas = []
    for n in ns:
        ruta = Path(tempfile.mkdtemp(prefix="rlm_int_")) / "pajar.txt"
        valores = _pajar(ruta, n)
        esperado = sum(valores)
        t0 = time.time()
        try:
            res = correr_rlm(_pregunta(n), str(ruta), url=url)
        except Exception as exc:
            print(f"{n:>7} {esperado:>9,} {'EXCEPCION':>10} — {exc}")
            filas.append((n, False))
            continue
        dt = time.time() - t0
        resp = str(res.get("texto") or "")
        limpio = resp.replace(".", "").replace(",", "").replace(" ", "")
        ok = str(esperado) in limpio
        med = res.get("medidor") or {}
        tokens = (med.get("tokens_in_raiz", 0) + med.get("tokens_out_raiz", 0)
                  + med.get("tokens_in_hijos", 0) + med.get("tokens_out_hijos", 0))
        print(f"{n:>7} {esperado:>9,} {'PASS' if ok else 'FALLO':>10} {dt:>6.0f} "
              f"{tokens:>9,} {med.get('llamadas_hijo', 0):>6}")
        if not ok:
            print(f"        respuesta: {resp[:150]!r}")
        filas.append((n, ok))
        try:
            ruta.unlink()
            ruta.parent.rmdir()
        except Exception:
            pass

    buenas = [n for n, ok in filas if ok]
    print(f"\nDATOS INTEGRABLES: hasta {max(buenas) if buenas else 0} agujas "
          f"({'sin techo en este barrido' if buenas and max(buenas) == max(ns) else 'techo encontrado'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
