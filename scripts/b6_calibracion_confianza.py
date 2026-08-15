# -*- coding: utf-8 -*-
"""b6_calibracion_confianza.py — ¿la confianza SIGNIFICA algo?

Un número de confianza sin calibrar es peor que no tener ninguno: invita a
confiar. Este banco pone a prueba la única propiedad que lo hace útil — que
las respuestas dadas con 0,8 acierten alrededor del 80% de las veces.

EL DISEÑO, y por qué tiene las dos mitades:

  POSITIVOS — la respuesta ESTÁ en las páginas que se le dan. Acertar es
    decir el código correcto. Mide si la confianza sube cuando debe.
  NEGATIVOS — se pregunta por un equipo que NO EXISTE. Acertar es NO dar un
    código (abstenerse o decir que no está). Mide lo contrario: si la
    confianza baja cuando debe.

Sin la mitad negativa, un sistema que contesta "0,95" a todo saca un ECE
excelente con solo acertar los positivos. La mitad negativa es la que hace
del banco una prueba y no un trámite: es donde un modelo se inventa un
hexadecimal con toda la seguridad del mundo.

Todo offline (http.server local, mismas páginas del banco b5): lo que se mide
es la POLÍTICA de confianza, no la suerte del buscador.

Uso:
  venv312\\Scripts\\python.exe scripts\\b6_calibracion_confianza.py --items 6
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.b5_banco_busqueda import construir_sitio, servir  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--items", type=int, default=6,
                    help="positivos; se añaden los mismos negativos")
    ap.add_argument("--paginas", type=int, default=12)
    ap.add_argument("--puerto", type=int, default=8793)
    ap.add_argument("--salida", default="b6_calibracion.json")
    args = ap.parse_args()

    from cognia.search import confianza as CF
    from cognia.search.responder import responder
    from cognia.knowledge.navegador import extraer_muchas

    base = Path(__file__).resolve().parent.parent / ".banco_calibracion"
    items = construir_sitio(base, args.paginas, args.items,
                            profundidad=4000, chars_pagina=9000)
    httpd, raiz = servir(base, args.puerto)
    urls = [f"{raiz}/informe_{i:03d}.html" for i in range(args.paginas)]

    # El "buscador" devuelve SIEMPRE el sitio entero: así el eje que se mide
    # es la confianza, no el ranking. Que la respuesta esté disponible y aun
    # así no se encuentre es un fallo legítimo del pipeline, no del buscador.
    def _buscador(_consulta, _n=8):
        return [{"url": u, "titulo": u, "resumen": ""} for u in urls]

    casos = []
    for it in items:
        casos.append({"tipo": "positivo", "pregunta": it["pregunta"],
                      "esperado": it["dato"]})
    for i, it in enumerate(items):
        # Equipos que NO existen en ninguna página: la respuesta correcta es
        # no dar un código.
        casos.append({"tipo": "negativo", "esperado": None,
                      "pregunta": (f"¿Cual es el codigo de calibracion del "
                                   f"equipo QX-{900 + i:03d}?")})

    pares, filas = [], []
    for c in casos:
        t0 = time.time()
        try:
            v = responder(c["pregunta"], presupuesto_s=90,
                          buscar_fn=_buscador, extraer_fn=extraer_muchas)
        except Exception as exc:
            print(f"  EXCEPCION {type(exc).__name__}: {exc}")
            continue
        dt = time.time() - t0
        dicho = (v.valor or "").lower()
        if c["tipo"] == "positivo":
            acierto = c["esperado"] in dicho and v.accion == "responder"
        else:
            # Acertar un negativo = NO afirmar un código con confianza.
            import re as _re
            invento = bool(_re.search(r"\b[0-9a-f]{8}\b", dicho))
            acierto = (v.accion != "responder") or not invento
        pares.append((v.confianza, acierto))
        filas.append({"tipo": c["tipo"], "pregunta": c["pregunta"],
                      "confianza": v.confianza, "accion": v.accion,
                      "acierto": acierto, "valor": v.valor[:80],
                      "seg": round(dt, 1), "razones": v.razones[:3]})
        print(f"  [{c['tipo']:8}] conf {v.confianza:.2f} {v.accion:11} "
              f"{'OK  ' if acierto else 'FALLA'} {dt:5.0f}s  {v.valor[:40]!r}",
              flush=True)

    httpd.shutdown()

    m = CF.calibracion(pares)
    print("\n" + "=" * 62)
    print(f"n={m['n']}  ECE={m['ece']}  Brier={m['brier']}  "
          f"sobreconfianza={m['sobreconfianza']}")
    for t in m["tramos"]:
        print(f"  {t['rango']}  n={t['n']:<3} dice {t['confianza_media']:.2f} "
              f"acierta {t['acierto_real']:.2f}")
    # El veredicto en una línea, con el criterio DECLARADO antes de mirar:
    # ECE <= 0,15 es "usable"; sobreconfianza > 0,15 es el fallo que importa
    # (creerse más de lo que se acierta).
    if m["ece"] is not None:
        veredicto = ("USABLE" if m["ece"] <= 0.15 and
                     (m["sobreconfianza"] or 0) <= 0.15 else "MAL CALIBRADA")
        print(f"veredicto: {veredicto}")
    Path(args.salida).write_text(
        json.dumps({"filas": filas, "calibracion": m}, indent=1,
                   ensure_ascii=False), encoding="utf-8")
    print(f"detalle -> {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
