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
        import re as _re
        dicho = (v.valor or "").lower()
        # ¿AFIRMÓ un código? Es lo que separa las dos preguntas de abajo, y se
        # mira en el TEXTO, no en la acción: decir "investigar" mientras se
        # suelta un hexadecimal sigue siendo afirmar.
        afirmo = bool(_re.search(r"\b[0-9a-f]{8}\b", dicho))
        if c["tipo"] == "positivo":
            acierto = c["esperado"] in dicho and v.accion == "responder"
        else:
            # Acertar un negativo = NO inventarse un código. La acción no
            # basta: la primera versión daba el acierto por la acción sola y
            # un hexadecimal inventado se aprobaba solo (lo cazó la revisión
            # adversarial y aun así corrí el banco con el defecto puesto).
            acierto = not afirmo
        pares.append((v.confianza, acierto, afirmo, c["tipo"]))
        filas.append({"tipo": c["tipo"], "pregunta": c["pregunta"],
                      "confianza": v.confianza, "accion": v.accion,
                      "acierto": acierto, "afirmo": afirmo,
                      "valor": v.valor[:80],
                      "seg": round(dt, 1), "razones": v.razones[:3]})
        print(f"  [{c['tipo']:8}] conf {v.confianza:.2f} {v.accion:11} "
              f"{'OK  ' if acierto else 'FALLA'} {dt:5.0f}s  {v.valor[:40]!r}",
              flush=True)

    httpd.shutdown()

    # DOS preguntas distintas, y meterlas en el mismo ECE es lo que hacía que
    # un sistema con 8/8 saliera "MAL CALIBRADA":
    #
    #  (1) DISCRIMINACIÓN — ¿decide bien CUÁNDO afirmar? Se mide sobre todos
    #      los casos y es la pregunta que importa primero.
    #  (2) CALIBRACIÓN — ¿el número acompaña al acierto? Solo tiene sentido
    #      sobre los casos donde el sistema AFIRMÓ algo: en los que se
    #      abstuvo, la confianza se refiere a una afirmación que no hizo, y
    #      contarla como "0,30 y acertó" mezcla peras con manzanas.
    aciertos = sum(1 for _, a, _, _ in pares if a)
    print("\n" + "=" * 62)
    print(f"DISCRIMINACIÓN: {aciertos}/{len(pares)} decisiones correctas "
          f"(afirmar cuando la respuesta está, callar cuando no)")
    for tipo in ("positivo", "negativo"):
        f = [p for p in pares if p[3] == tipo]
        if f:
            print(f"   {tipo:9}: {sum(1 for _, a, _, _ in f if a)}/{len(f)}")

    afirmados = [(c, a) for c, a, af, _ in pares if af]
    m = CF.calibracion(afirmados)
    print(f"\nCALIBRACIÓN (solo los {len(afirmados)} casos donde AFIRMÓ): "
          f"ECE={m['ece']}  Brier={m['brier']}  "
          f"sobreconfianza={m['sobreconfianza']}")
    for t in m["tramos"]:
        print(f"  {t['rango']}  n={t['n']:<3} dice {t['confianza_media']:.2f} "
              f"acierta {t['acierto_real']:.2f}")
    # Criterio DECLARADO antes de mirar: ECE <= 0,15 usable; y lo que de
    # verdad importa es la SOBRECONFIANZA (creerse más de lo que se acierta);
    # quedarse corto es un defecto menor, no un peligro.
    if m["ece"] is not None:
        if (m["sobreconfianza"] or 0) > 0.15:
            veredicto = "SOBRECONFIADA (el fallo peligroso)"
        elif m["ece"] <= 0.15:
            veredicto = "USABLE"
        else:
            veredicto = "INFRACONFIADA (acierta más de lo que declara)"
        print(f"veredicto: {veredicto}")
    Path(args.salida).write_text(
        json.dumps({"filas": filas, "calibracion": m,
                    "discriminacion": {"aciertos": aciertos,
                                       "n": len(pares)}}, indent=1,
                   ensure_ascii=False), encoding="utf-8")
    print(f"detalle -> {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
