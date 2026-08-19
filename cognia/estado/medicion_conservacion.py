# -*- coding: utf-8 -*-
"""
cognia/estado/medicion_conservacion.py
======================================
LA MEDICION del canal de estado: recall de artefactos tras una compactacion
REAL de juguete, CON el canal y SIN el canal.

POR QUE UN COMPACTADOR DE JUGUETE Y NO UN LLM: el compactador que se usa aca
se queda con las ultimas N lineas de la conversacion. No es una caricatura: es
literalmente lo que hace el fallback de todos los harnesses cuando el resumidor
no esta disponible, y es el limite superior de lo que un resumidor conserva
cuando el material viejo ya no "parece relevante". Ademas es DETERMINISTA, que
es lo unico que permite comparar dos brazos sin ruido de modelo. Un resumidor
LLM daria un numero distinto por corrida y no cambiaria la conclusion: el
articulo publicado mide 2,19-2,45/5 CON resumidores reales.

Se miden dos compactadores para no elegir el mas conveniente:
  cola     -> ultimas N lineas (el fallback universal)
  cabeza+cola -> primeras 3 lineas + ultimas N (lo que hace un resumidor
                 extractivo naif, que al menos retiene el encabezado)

Correr:
    PYTHONUTF8=1 ./venv312/Scripts/python.exe -m cognia.estado.medicion_conservacion
"""

import sys

from cognia.estado import canal

# 6 ficheros REALES del repo: `anotar_fichero` lee el disco y saca sha256 y
# bytes de verdad. Si se usaran rutas inventadas, el estado registraria ok=False
# y la medicion mediria otra cosa.
FICHEROS = [
    "cognia/estado/canal.py",
    "cognia/estado/__init__.py",
    "tests/conftest.py",
    "CLAUDE.md",
    "cognia/harness/limites.py",
    "cognia/harness/verificacion.py",
]

RESTRICCIONES = [
    "no publicar a PyPI sin autorizacion explicita del dueno",
    "nunca commitear el fichero .env ni tokens",
    "usar siempre venv312/Scripts/python.exe, nunca python pelado",
]


def construir_turno(semilla=7):
    """Conversacion sintetica de 40 mensajes con 6 ficheros tocados y 3
    restricciones. Devuelve (estado, mensajes).

    Reparto deliberado: las restricciones se enuncian al principio (asi es en
    produccion: van en el prompt de sistema o en el primer turno) y 5 de los 6
    ficheros se tocan en la primera mitad. El sexto se toca cerca del final:
    sin ese fichero el brazo SIN canal daria 0,0 y pareceria un banco amanado."""
    estado = canal.EstadoVerificado("refactor del modulo de contexto", "medicion-40")
    mensajes = []

    mensajes.append("SISTEMA: objetivo = refactor del modulo de contexto.")
    for r in RESTRICCIONES:
        canal.anotar_restriccion(estado, r)
        mensajes.append("SISTEMA: RESTRICCION -> " + r)

    trz = canal.sembrar_trazadores(estado, k=4, semilla=semilla)
    for t in trz:
        mensajes.append("USUARIO: " + t["texto"])

    # Trabajo. Los ficheros se tocan en los mensajes 8, 11, 14, 17, 20 y 33.
    posiciones = {8: 0, 11: 1, 14: 2, 17: 3, 20: 4, 33: 5}
    relleno = [
        "AGENTE: leo el modulo y busco los puntos de entrada.",
        "AGENTE: el import circular viene de la carga perezosa.",
        "AGENTE: corro los tests dirigidos del area.",
        "AGENTE: reviso el diff antes de seguir.",
        "AGENTE: mido el tiempo de arranque para no regresionar.",
    ]
    i = len(mensajes)
    while len(mensajes) < 40:
        if i in posiciones:
            ruta = FICHEROS[posiciones[i]]
            canal.anotar_fichero(estado, ruta, "editar")
            canal.anotar_comando(estado, "pytest -q tests/", 0, "12 passed")
            canal.anotar_verificacion(estado, "pytest -q tests/", True)
            mensajes.append("AGENTE: edito %s y corro los tests." % ruta)
        else:
            mensajes.append(relleno[i % len(relleno)])
        i += 1

    canal.anotar_pendiente(estado, "cablear el canal en el bucle del agente")
    return estado, mensajes


def compactar_cola(mensajes, n=12):
    """El fallback universal: quedarse con las ultimas N lineas."""
    return "\n".join(mensajes[-n:])


def compactar_cabeza_cola(mensajes, n=12, cabeza=3):
    """Resumidor extractivo naif: encabezado + cola."""
    return "\n".join(mensajes[:cabeza] + ["... (compactado) ..."] + mensajes[-n:])


def _pct(x):
    return "  n/a" if x is None else ("%5.2f" % x)


def main(argv=None):
    estado, mensajes = construir_turno()
    # Las rutas son relativas: si esto no se corre desde la raiz del repo, los
    # ficheros salen ok=False y la medicion mide otra cosa. Se avisa en vez de
    # reportar un numero silenciosamente equivocado.
    faltan = [r for r, d in estado["ficheros"].items() if not d["ok"]]
    if faltan:
        print("AVISO: correr desde la raiz del repo. Sin medir: %s" % ", ".join(faltan))
    bloque = canal.render(estado, tope_chars=1200)

    filas = []
    for nombre, fn in (("cola(12)", compactar_cola), ("cabeza3+cola(12)", compactar_cabeza_cola)):
        post = fn(mensajes)
        sin = canal.conservacion(estado, post)
        # CON el canal: el mismo contexto compactado MAS el bloque de estado
        # reinyectado entero. El bloque no pasa por el compactador; ese es el
        # unico cambio entre brazos.
        con = canal.conservacion(estado, post + "\n" + bloque)
        filas.append((nombre, sin, con))

    print("MEDICION DE CONSERVACION - canal de estado")
    print("conversacion: %d mensajes | ficheros tocados: %d | restricciones: %d | trazadores: %d"
          % (len(mensajes), len(estado["ficheros"]), len(estado["restricciones"]),
             len(estado["trazadores"])))
    print("bloque render(tope=1200): %d chars, %d lineas"
          % (len(bloque), bloque.count("\n") + 1))
    print("")
    cab = "%-17s %-5s %7s %7s %7s %7s %8s" % (
        "compactador", "brazo", "fich", "restr", "trz", "global", "sobre5")
    print(cab)
    print("-" * len(cab))
    for nombre, sin, con in filas:
        for brazo, d in (("SIN", sin), ("CON", con)):
            print("%-17s %-5s %7s %7s %7s %7s %8s" % (
                nombre, brazo,
                _pct(d["recall_ficheros"]), _pct(d["recall_restricciones"]),
                _pct(d["recall_trazadores"]), _pct(d["recall_global"]),
                d["escala_5"]))
    print("")
    sin0 = filas[0][1]
    print("PERDIDOS sin canal (compactador cola(12)): %d de %d" % (len(sin0["perdidos"]), sin0["n"]))
    for p in sin0["perdidos"]:
        print("  - %-12s %s" % (p["tipo"], p["valor"]))
    con0 = filas[0][2]
    print("PERDIDOS con canal (compactador cola(12)): %d de %d" % (len(con0["perdidos"]), con0["n"]))
    for p in con0["perdidos"]:
        print("  - %-12s %s" % (p["tipo"], p["valor"]))

    # Barrido de cuanta cola sobrevive. Sirve para ver que el brazo SIN canal
    # depende ENTERAMENTE de la agresividad del compactador, mientras el brazo
    # CON canal no se mueve: esa es la diferencia estructural, no el numero.
    print("")
    print("barrido de cola (recall_global):")
    print("  %-8s %8s %8s" % ("cola(n)", "SIN", "CON"))
    for n in (6, 12, 20, 30, 40):
        post = compactar_cola(mensajes, n=n)
        s = canal.conservacion(estado, post)["recall_global"]
        c = canal.conservacion(estado, post + "\n" + bloque)["recall_global"]
        print("  %-8d %8.2f %8.2f" % (n, s, c))

    # Caso adverso: el bloque no cabe. Sirve para ver QUE se sacrifica cuando
    # el tope aprieta (deben caer comandos/decisiones, nunca restricciones).
    apretado = canal.render(estado, tope_chars=400)
    dj = canal.conservacion(estado, compactar_cola(mensajes) + "\n" + apretado)
    print("")
    print("CON canal, tope apretado (400 chars -> %d reales): fich=%s restr=%s trz=%s global=%s"
          % (len(apretado), _pct(dj["recall_ficheros"]), _pct(dj["recall_restricciones"]),
             _pct(dj["recall_trazadores"]), _pct(dj["recall_global"])))
    print(apretado.splitlines()[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
