# -*- coding: utf-8 -*-
"""Audita las INVENCIONES de cada salida, sobre las 48 llamadas de crudo.json.

POR QUE existe (revision adversarial de la ronda 2): MANAGER_LOG.md publicaba
"Invenciones: 0 de 24" como la razon por la que se podia adoptar v2 "sin pagar
el riesgo que motivaba el default conservador". Ningun script calculaba eso:
resumen.json solo tiene llamadas/aceptadas/rechazadas/motivos/ms/chars. El 0/24
era un juicio a ojo del mismo agente que escribio v2, y ademas el denominador
estaba mal: 24 son los textos de pares.json, de los cuales 12 eran el original
sin tocar (invencion imposible por construccion). Las 24 salidas de replica 2
nunca se miraron.

Que hace este chequeo, y que NO hace:
- SI: para cada salida ACEPTADA, lista las palabras de contenido y las cifras
  que aparecen en la salida y no en el original (comparando sin tildes, en
  minusculas y con una lematizacion pobre de plurales).
- SI: separa las que caen dentro de una PREGUNTA al asistente de las que caen
  en una AFIRMACION. Solo las segundas son candidatas a invencion: preguntar
  "que presupuesto tengo" no afirma ningun presupuesto.
- NO: no decide sola. La lista de candidatas es una CRIBA sobre-inclusiva (el
  reformulador legitimamente nombra el formato: "lista", "plan", "pasos"). El
  veredicto por salida se anota a mano en VEREDICTOS, con el dato senalado, y
  queda en el JSON al lado de la criba que lo produjo.
"""
import json
import os
import re
import unicodedata

AQUI = os.path.dirname(os.path.abspath(__file__))

# Palabras que un prompt bien formado usa por su FUNCION, no como dato del
# mundo: nombran el formato, el turno o la estructura. Que aparezcan sin estar
# en el original no es inventar nada.
FUNCIONALES = set("""
a al algo alguna algun alguno antes aparece asi aunque bien cada como con
concreta concretas concreto concretos conmigo contar cual cuales cuando cuanto
cuantos cuanta cuantas dame de del desde despues devuelve devuelvas dime donde
dos el ella ellos en entonces entre esa ese eso esos esta estan este esto estos
exito falta forma frecuencia hacer hasta indica indicame indicando indique
informacion la las le lista listas lo los luego mas me mi mis modo momento nada
ni no nos para pasos paso pero por porque prefiero preferencia pregunta
preguntame preguntarme primero pueda puedo que quiero resultado respuesta
respuestas saber segun sea senal si sin sobre solo su sus tal tambien tener
tengo tiene tipo tipos todo todos tras un una uno unos usar vez y ya yo
plan planes tabla tablas correo correos guion script pasos punto puntos
opcion opciones criterio criterios objetivo objetivos detalle detalles
ordenada ordenado ordenados prioridad claro clara listo lista
""".split())

# Una frase es una PREGUNTA al asistente si trae uno de estos marcadores: lo
# que hay dentro no se afirma, se pide.
# Los marcadores son ESTRECHOS a proposito. La primera version incluia
# "antes de" y un "que .* tengo", y con eso la frase de 'receta' -- "Arma una
# lista de recetas para que yo cocine hoy con lo que tengo EN LA DESPENSA" --
# se clasificaba como pregunta y la unica invencion real del corpus no salia en
# la criba. Un marcador de mas convierte la criba en un sello de aprobado.
RE_PREGUNTA = re.compile(
    r"pregunt|dime|indicame|aclarame|confirmame|necesito saber|\?", re.I)

RE_CIFRA = re.compile(r"\d+")
RE_PLACEHOLDER = re.compile(r"\[[^\]]+\]")


def _sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if not unicodedata.combining(c))


def _lema(palabra):
    """Lematizacion pobre de plurales del espanol. Suficiente para no contar
    'gastos' como nueva cuando el original dice 'gasto'."""
    for fin in ("es", "s"):
        if len(palabra) > 4 and palabra.endswith(fin):
            return palabra[:-len(fin)]
    return palabra


def _tokens(texto):
    plano = _sin_tildes(texto).lower()
    return set(_lema(p) for p in re.findall(r"[a-z]{3,}", plano))


def _frases(texto):
    return [f.strip() for f in re.split(r"(?<=[.?!])\s+", texto) if f.strip()]


def criba(original, salida):
    """(nuevas_en_afirmacion, nuevas_en_pregunta, cifras_nuevas)."""
    base = _tokens(original)
    afirm, preg = set(), set()
    for frase in _frases(salida):
        # Sin tildes ANTES de buscar el marcador: el modelo escribe
        # "preguntame" y la version acentuada indistintamente, y con la version
        # acentuada el marcador no matcheaba y la frase entera se contaba como
        # afirmacion (ruido que ahoga las candidatas de verdad).
        destino = preg if RE_PREGUNTA.search(_sin_tildes(frase)) else afirm
        for tok in _tokens(RE_PLACEHOLDER.sub(" ", frase)):
            if tok not in base and tok not in FUNCIONALES:
                destino.add(tok)
    cifras = set(RE_CIFRA.findall(salida)) - set(RE_CIFRA.findall(original))
    return sorted(afirm - preg), sorted(preg), sorted(cifras)


# Veredicto humano por salida, con el dato concreto senalado. Clave:
# "<tarea>/<brazo>/r<replica>". Lo que NO esta aca salio con la criba vacia de
# candidatas afirmativas o solo con palabras de formato, y se cuenta como
# "sin invencion". El veredicto se escribe MIRANDO la salida completa, no la
# criba: la criba solo dice donde mirar.
VEREDICTOS = {
    "receta/v2/r1": ("INVENCION", "anade 'en la despensa': un lugar que el "
                     "usuario no dijo, y 'lugares' esta en la lista de "
                     "PROHIBIDO del propio system v2"),
    "receta/v2/r2": ("INVENCION", "anade 'en casa' como lugar de los "
                     "ingredientes; el usuario solo dijo 'lo que tengo'"),
    "curriculum/v2/r2": ("LIMITE", "anade 'guardar como PDF': un formato de "
                         "fichero que el usuario no pidio. No cambia el "
                         "entregable ni afirma un dato sobre el usuario, pero "
                         "'formatos y herramientas' es justo lo que el system "
                         "v2 lista como prohibido"),
    "escritorio/v2/r1": ("ENTREGABLE", "cambia el pedido: de organizar el "
                         "escritorio a 'arma una lista de los elementos que "
                         "deberia tener'. No inventa un dato, pero cambia lo "
                         "que se entrega, que para el usuario es el mismo dano"),
}


def main():
    with open(os.path.join(AQUI, "crudo.json"), encoding="utf-8") as fh:
        llamadas = json.load(fh)

    filas, resumen = [], {}
    for c in llamadas:
        clave = "{}/{}/r{}".format(c["tarea"], c["brazo"], c["replica"])
        if not c["ok"]:
            # Una celda rechazada devuelve el texto del usuario: no puede
            # inventar nada por construccion, y contarla como "0 invenciones"
            # infla el denominador del audit. Se registra aparte.
            filas.append({"clave": clave, "auditada": False,
                          "motivo_rechazo": c["motivo"]})
            continue
        afirm, preg, cifras = criba(c["original"], c["texto"])
        veredicto, dato = VEREDICTOS.get(clave, ("SIN INVENCION", ""))
        filas.append({
            "clave": clave, "auditada": True,
            "original": c["original"], "salida": c["texto"],
            "candidatas_en_afirmacion": afirm,
            "nuevas_dentro_de_preguntas": preg,
            "cifras_nuevas": cifras,
            "veredicto": veredicto, "dato": dato,
        })
        resumen[veredicto] = resumen.get(veredicto, 0) + 1

    auditadas = [f for f in filas if f["auditada"]]
    salida = {
        "que_se_audito": "las salidas ACEPTADAS de las 48 llamadas de "
                         "crudo.json (r1 y r2 de los dos brazos)",
        "auditadas": len(auditadas),
        "no_auditadas_por_rechazo": len(filas) - len(auditadas),
        "veredictos": resumen,
        "quien": "el mismo agente que escribio v2 (conflicto declarado); la "
                 "criba es reproducible corriendo este script",
        "filas": filas,
    }
    with open(os.path.join(AQUI, "rubrica_invenciones.json"), "w",
              encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=2)

    print("auditadas: {}  (rechazadas, sin auditar: {})".format(
        len(auditadas), len(filas) - len(auditadas)))
    print("veredictos: " + json.dumps(resumen, ensure_ascii=False))
    print("\n--- filas con candidatas en AFIRMACION (donde mirar) ---")
    for f in auditadas:
        if f["candidatas_en_afirmacion"] or f["cifras_nuevas"]:
            print("  {:>18} {:<14} {} {}".format(
                f["clave"], f["veredicto"],
                f["candidatas_en_afirmacion"], f["cifras_nuevas"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
