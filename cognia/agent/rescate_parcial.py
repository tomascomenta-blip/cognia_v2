"""
cognia/agent/rescate_parcial.py
===============================
Rescatar el fichero a medio escribir de un tool call que se corto.

POR QUE EXISTE. Cuando el turno se agota a mitad del JSON de argumentos, el
bucle recibia esto y lo TIRABA ENTERO:

    {"path": "minecraft.html", "contenido": "<!DOCTYPE html> ... <meta charset=

...y le pedia al modelo que lo escribiera "por partes". Pero el modelo vuelve
a empezar POR EL PRINCIPIO y con el MISMO presupuesto, asi que se corta en la
misma columna: en la corrida del 2026-08-30 el aviso salio cuatro veces
seguidas y el fichero nunca existio. Se tiraban ~2.100 chars de HTML valido
por vuelta -- lo unico util que el turno habia producido.

QUE HACE. Saca del JSON roto la ruta y el trozo de contenido que SI llego, lo
recorta a una frontera de linea (media etiqueta HTML no es progreso) y deja
que el bucle lo escriba de verdad. A partir de ahi el modelo no reescribe: al
turno siguiente CONTINUA con apendar_archivo desde el ancla que se le da. Un
corte deja de costar una vuelta y pasa a costar un tramo.

Es aritmetica de texto, sin disco ni red: el que escribe es el bucle, con las
mismas guardas de workspace de siempre.

API
---
    partes(crudo)                 -> {'campos','ruta','clave','parcial'} | None
    recortar_a_frontera(texto)    -> (texto_seguro, chars_descartados)
    ancla(texto, n=200)           -> las ultimas n chars, para "sigue por aqui"
"""

from __future__ import annotations

import json

# Claves donde vive el CONTENIDO en las tools de escritura del agente. Si el
# corte cayo en otra clave (la ruta, un offset) no hay nada que rescatar: un
# fichero con la ruta a medias no se escribe.
CLAVES_CONTENIDO = ("contenido", "texto", "content", "nuevo", "bloque")

# Claves donde vive la RUTA. Sin ruta no hay rescate posible.
CLAVES_RUTA = ("path", "ruta", "archivo", "fichero", "file")

# Un rescate por debajo de esto no compensa: se le mete al modelo un fichero
# de tres lineas y un aviso de continuacion por algo que reescribe mas barato.
MINIMO_RESCATABLE = 200


def _decodificar(escapado: str) -> str:
    """Decodifica una cadena JSON a la que le falta la comilla de cierre.

    El corte puede caer DENTRO de una secuencia de escape (una barra suelta,
    media escapada unicode), y entonces no hay cierre que valga: se recortan
    hasta 7 chars del final (la escapada mas larga mide 6) hasta que parsee.
    strict=False porque un salto de linea crudo dentro de la cadena es ilegal
    en JSON estricto y aqui no es motivo para tirar el rescate entero.
    """
    for corte in range(len(escapado), max(-1, len(escapado) - 8), -1):
        try:
            return json.loads('"' + escapado[:corte] + '"', strict=False)
        except ValueError:
            continue
    return ""


def _leer_cadena(crudo: str, i: int):
    """(contenido_escapado, indice_tras_la_comilla, se_cerro) leyendo desde
    DENTRO de una cadena JSON (i apunta al primer char del contenido)."""
    ini, n = i, len(crudo)
    while i < n:
        c = crudo[i]
        if c == "\\":
            i += 2                             # se salta el escapado entero
            continue
        if c == '"':
            return crudo[ini:i], i + 1, True
        i += 1
    return crudo[ini:n], n, False              # se acabo sin cerrar


def _escanear(crudo: str):
    """(campos_completos, clave_abierta, valor_parcial_escapado).

    Recorre el JSON a mano porque json.loads no devuelve NADA de un objeto
    incompleto, y lo que hace falta es justo lo que llego antes del corte.
    Solo entiende objetos planos de pares clave->valor, que es la forma de
    los argumentos de todas las tools de escritura.
    """
    campos, i, n = {}, 0, len(crudo)
    while i < n and crudo[i] != "{":
        i += 1
    i += 1                                     # dentro del objeto
    while i < n:
        while i < n and crudo[i] in " \t\r\n,":
            i += 1
        if i >= n or crudo[i] == "}":
            return campos, "", ""
        if crudo[i] != '"':                    # forma inesperada: se para
            return campos, "", ""
        clave, i, cerrada = _leer_cadena(crudo, i + 1)
        if not cerrada:                        # el corte cayo en la CLAVE
            return campos, "", ""
        while i < n and crudo[i] in " \t\r\n":
            i += 1
        if i >= n or crudo[i] != ":":
            return campos, "", ""
        i += 1
        while i < n and crudo[i] in " \t\r\n":
            i += 1
        if i >= n:
            return campos, "", ""
        if crudo[i] == '"':
            valor, i, cerrada = _leer_cadena(crudo, i + 1)
            if not cerrada:                    # AQUI cayo el corte
                return campos, _decodificar(clave), valor
            campos[_decodificar(clave)] = _decodificar(valor)
        else:                                  # numero/bool/null: hasta , o }
            j = i
            while j < n and crudo[j] not in ",}":
                j += 1
            campos[_decodificar(clave)] = crudo[i:j].strip()
            i = j
    return campos, "", ""


def partes(crudo: str):
    """Lo rescatable de unos argumentos cortados, o None.

    None cuando: no es JSON de objeto, el corte no cayo en una clave de
    contenido, no hay ruta, o lo rescatado no llega a MINIMO_RESCATABLE. En
    todos esos casos el bucle sigue por el camino de siempre (pedir "por
    partes"), que es lo unico que se puede hacer sin inventar.
    """
    if not crudo or "{" not in crudo:
        return None
    try:
        campos, clave, parcial_esc = _escanear(crudo)
    except Exception:                          # un crudo aun mas raro
        return None
    if not clave or clave not in CLAVES_CONTENIDO:
        return None
    ruta = ""
    for k in CLAVES_RUTA:
        v = campos.get(k)
        if isinstance(v, str) and v.strip():
            ruta = v.strip()
            break
    if not ruta:
        return None
    parcial = _decodificar(parcial_esc)
    if len(parcial) < MINIMO_RESCATABLE:
        return None
    return {"campos": campos, "ruta": ruta, "clave": clave, "parcial": parcial}


def recortar_a_frontera(texto: str):
    """(texto_seguro, chars_descartados) cortando en el ultimo salto de
    linea: media etiqueta HTML o media sentencia no es progreso, y dejarla en
    el fichero obliga al modelo a adivinar donde empalmar.

    Sin ningun salto de linea se devuelve el texto entero: es una sola linea
    larga, y tirarla seria tirar el rescate completo por prudencia.
    """
    if not texto:
        return "", 0
    corte = texto.rfind("\n")
    if corte <= 0:
        return texto, 0
    return texto[:corte + 1], len(texto) - corte - 1


def ancla(texto: str, n: int = 200) -> str:
    """Las ultimas n chars de lo escrito: el ancla EXACTA por la que el modelo
    tiene que continuar. Sin esto el modelo repite o se salta un tramo, que es
    como se corrompian los ficheros escritos por partes."""
    texto = texto or ""
    return texto[-n:] if len(texto) > n else texto
