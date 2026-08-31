"""
cognia/clases/materias.py
=========================
Donde EMPIEZA y donde ACABA cada asignatura dentro de una jornada grabada.

EL PROBLEMA. La jornada llega como UNA tira de seis horas: la transcripcion
no trae timbres ni titulos. El cuaderno, en cambio, se lee por materia
(`cuaderno.sesiones_de` parte la tira por los cortes que escribe este
modulo). Si aqui se falla, el dia entero acaba en una sesion gigante
"Sin clasificar" o, peor, troceado en veinte pedazos sin nombre.

EL FALLO TIPICO ES CORTAR DE MAS, NO DE MENOS. Un profesor cambia de ejemplo
cada tres minutos: pasa de derivadas a "el reparto de pizzas", habla dos
minutos de pizzas y vuelve. Todo detector que mire solo la ventana anterior
contra la siguiente ve ahi un cambio de vocabulario tan grande como el de
matematicas a historia. Por eso la deriva NO se mide contra los ultimos tres
minutos, sino contra EL BLOQUE ENTERO abierto hasta ahora:

    cobertura = |terminos de la ventana nueva que YA aparecieron en el bloque|
                --------------------------------------------------------------
                          |terminos de la ventana nueva|

Volver a un ejemplo ya usado da cobertura alta (el bloque ya conoce esas
palabras) aunque los ultimos tres minutos no se parezcan; una asignatura
nueva estrena vocabulario y da cobertura baja. Se usa contencion y no Jaccard
a proposito: el bloque crece con el tiempo y Jaccard bajaria solo por eso,
castigando los cortes tardios de la manana.

Encima van dos frenos mas, porque una sola medida no basta:
  - SOSTENIDO: el vocabulario nuevo tiene que seguir siendo nuevo en la
    ventana de despues (t+VENTANA .. t+2*VENTANA). La digresion vuelve al
    tema; la clase nueva no vuelve.
  - DURACION_MINIMA: un bloque aceptado tiene que durar lo que dura una
    clase. Sin este freno, cualquier medida continua acaba picando el dia.

LAS CUATRO SENIALES (cada una se puede apagar y medir por separado, ver
`pistas["senales"]`, y cada una tiene su propia funcion publica):
  1. `senal_silencio`  - hueco entre el t_fin de una entrada y el t de la
     siguiente. Entre clases hay cambio de aula; a mitad de clase no.
  2. `senal_deriva`    - lo de arriba. Con sentence-transformers si esta
     vivo (coseno de las medias); si no, contencion lexica, y el campo "por"
     lo DICE ("lexica" vs "embeddings"). No es cosmetico: los umbrales de
     una medida no valen para la otra.
  3. `vocabulario_de_materias` - que terminos son propios de cada asignatura,
     APRENDIDOS del propio cuaderno (`cuaderno.cuaderno()`). Es lo unico que
     permite decir "esto es Biologia" y no "Tema: celula, membrana".
  4. `senal_horario`   - si el duenio dio el horario, manda: fija los limites
     y solo se permite ajustarlos +-TOLERANCIA_HORARIO hasta el silencio mas
     cercano, porque el profesor no empieza en el segundo exacto del timbre.

SIN MODELO Y SIN HISTORIAL SIGUE FUNCIONANDO. `orch=None` y sin materias
conocidas, los cortes salen igual (silencio + deriva lexica) y el nombre es
"Tema: <los terminos propios del bloque>". Peor, pero real, y el "por" lo
declara para que nadie confunda "no lo cablearon" con "se rompio".

APAGADO / ENCENDIDO
    COGNIA_CLASES_SIN_EMBEDDINGS=1   fuerza la medida lexica (mas rapida y
                                     deterministica; util en tests y en
                                     maquinas sin sentence-transformers).
    pistas={"senales": {"silencio": False, ...}}   apaga una senial suelta.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata

from cognia.clases import almacen as alm
from cognia.clases import cuaderno as cua
from cognia.clases.cuaderno import Entrada, TIPO_TRANSCRIPCION

log = logging.getLogger(__name__)


# ── Umbrales ─────────────────────────────────────────────────────────────────
# NINGUNO es un numero elegido a ojo: los de tiempo salen de como es un dia de
# instituto, y los de similitud estan MEDIDOS sobre la tira de referencia de
# tests/test_clases_materias.py (tres bloques de 20 min con vocabularios
# disjuntos, una digresion de 3 min dentro del primero). Los numeros medidos
# van escritos al lado de cada uno para que se pueda repetir la medida.

# Un cambio de aula, un recreo o el rato en que el profesor recoge duran
# minutos. La pausa mas larga DENTRO de una clase (el profesor escribe en la
# pizarra en silencio) esta en decenas de segundos: 45 s deja fuera esas y
# 300 s satura la senial (a partir de cinco minutos, mas silencio ya no
# aporta evidencia; es lo mismo un recreo de 5 que uno de 20).
SILENCIO_MINIMO = 45.0
SILENCIO_SATURA = 300.0

# Una clase no dura 40 segundos. La unidad mas corta que el duenio querria ver
# como sesion propia en el cuaderno es media hora de clase partida; 600 s (10
# min) deja sitio a eso y mata de raiz el troceo cada dos minutos.
DURACION_MINIMA = 600.0

# Tres minutos de habla son ~350 palabras: suficientes para que el vocabulario
# de la ventana sea representativo y corto para no tragarse dos clases.
VENTANA = 180.0

# Con menos terminos de contenido que esto, la ventana no mide nada: dos
# frases sueltas comparten o no comparten palabras por azar.
MIN_TERMINOS = 8

# Cobertura por debajo de la cual la ventana trae vocabulario NUEVO.
# MEDIDO sobre la tira de referencia (32 ventanas dentro de materia, 6 al
# cruzar): dentro de la materia 1.00; cruzando a otra materia 0.00-0.28
# (mediana 0.13). 0.30 va justo por encima del maximo del cruce. El 1.00 de
# "dentro" es optimista -- la tira repite frases y el habla real no -- asi
# que el margen fiable es el de ABAJO, y por eso el umbral se pega al cruce
# y no se pone a la mitad. Ojo: es contencion, no Jaccard (ver cabecera).
UMBRAL_COBERTURA = 0.30

# El mismo corte con embeddings. El coseno de all-MiniLM sobre castellano NO
# baja a cero entre materias distintas (comparten estructura de frase): en la
# misma tira da 0.99-1.00 dentro de la materia y 0.54-0.67 al cruzar. Por eso
# NO se puede reusar UMBRAL_COBERTURA -- con 0.30 no cortaria jamas -- y por
# eso 0.75, encima del maximo medido del cruce.
# LO QUE ENSENIA LA MEDIDA, y es lo importante: la digresion de la pizza da
# 0.68 con embeddings, o sea DENTRO del rango del cambio de materia. Ningun
# umbral separa una digresion de un cambio de asignatura; lo que las separa
# es comparar contra el BLOQUE y exigir que la deriva se sostenga.
UMBRAL_COSENO = 0.75

# Cuanta evidencia total hace falta para aceptar un corte. La combinacion es
# un OR ruidoso (1-(1-a)(1-b)): un recreo de 5 min solo (fuerza 1.0) corta, y
# una deriva que pasa sus tres frenos sola tambien; un silencio de un minuto
# solo (0.2) no.
UMBRAL_ACEPTA = 0.55

# El suelo de cada medida: la similitud a partir de la cual dos trozos ya son
# "todo lo distintos que se ponen". Medido en la tira de referencia al cruzar
# de materia: la cobertura lexica llega a bajar a 0.00 y el coseno no baja de
# 0.54 (MiniLM esta entrenado en ingles y en castellano guarda un suelo alto).
# Sin este suelo por modo, la misma formula daba fuerza 1.0 al lexico y 0.19
# al coseno para EL MISMO corte -- y el camino con embeddings no cortaba
# nunca. Fue el bug que cazo el test de embeddings, no un ajuste de gusto.
PISO_COBERTURA = 0.0
PISO_COSENO = 0.55

# El horario manda, pero el timbre no. Cinco minutos de margen para pegar el
# corte al silencio real mas cercano.
TOLERANCIA_HORARIO = 300.0

# Presupuesto para la pregunta al modelo. MEDIDO contra el cerebro de la casa
# (Qwen3.8-27B-Ridge en :8080) el 2026-08-31 con este mismo prompt: es un
# RAZONADOR, escribe su cadena de pensamiento antes de la respuesta y el
# `content` viene VACIO hasta que termina. Con max_tokens=16 devolvio ''
# (finish_reason=length), con 48 tambien ''; con 160 respondio "Ingles"
# gastando 97 tokens. O sea: acotar de mas no es prudente, es garantizar cero.
# 160 deja margen sobre los 97 medidos sin dejarle sitio para divagar.
MAX_TOKENS_NOMBRE = 160

# Nombrado. Por debajo de SEGURO se le pregunta al modelo (si lo hay); por
# debajo de MINIMO no se le pone nombre de materia a nada y se cae a
# "Tema: ...", que es honesto en vez de inventar una asignatura.
UMBRAL_NOMBRE_SEGURO = 0.45
UMBRAL_NOMBRE_MINIMO = 0.20

# Vocabulario propio: un termino es de una materia si aparece al menos dos
# veces en ella y su peso relativo alli es >=2x el que tiene en el resto del
# cuaderno. Con una sola aparicion entra cualquier muletilla del profesor.
MIN_APARICIONES = 2
RATIO_PROPIO = 2.0

# Muletillas y palabras de aula. Hay dos listas de stopwords en el repo
# (memory/semantic_search.py y config.KG_STOPWORDS) pero son privadas de su
# modulo y de 20-30 entradas pensadas para chat; el habla de clase esta llena
# de "entonces / fijaos / vale / apuntad" y sin ellas dos materias distintas
# comparten el 20% de los terminos y la cobertura deja de separar.
STOPWORDS = frozenset("""
el la los las un una unos unas lo al del de que en y o u a ante bajo con
contra desde durante entre hacia hasta mediante para por segun sin sobre tras
es son era eran ser sido estar esta estan estaba estamos estais hay habia
haber tiene tienen tenia tener hace hacen hacer hecho va van iba ir vamos
vais puede pueden podemos poder pues pero aunque porque como cuando donde
cual cuales quien quienes cuyo esta este esto estos estas ese esa eso esos
esas aquel aquella aquello mismo misma mismos mismas otro otra otros otras
todo toda todos todas nada algo alguno alguna algunos algunas mucho mucha
muchos muchas poco poca pocos pocas mas menos muy tan tanto tambien tampoco
si no ni ya aun aqui ahi alli ahora luego despues antes entonces asi bien
mal solo solamente casi cada vez veces dos tres cuatro cinco seis siete ocho
nueve diez me te se nos os les le la lo mi tu su sus mis tus nuestro nuestra
vuestro vuestra yo tuyo suyo ustedes vosotros nosotros ellos ellas usted
vale venga mirad mira fijaos fijate apuntad apunta escuchad escucha vale
chicos chicas clase profesor profesora hoy maniana ayer dia semana tema
punto parte caso ejemplo ejemplos manera forma cosa cosas gente vez tipo
decir dice dicen digo dije dicho ver veis vemos visto sabe saben saber
queda quedan quiero quiere queremos vaya bueno buenas buenos venga oye
pagina paginas ejercicio ejercicios libro cuaderno pizarra deberes examen
""".split())


# ── Texto ────────────────────────────────────────────────────────────────────

_NO_LETRA = re.compile(r"[^a-z0-9]+")


def _sin_acentos(texto: str) -> str:
    """La transcripcion trae acentos y el resto del repo no. Sin plegarlos,
    'funcion' y 'función' cuentan como dos terminos distintos y la cobertura
    entre dos trozos de la MISMA clase se hunde por una tilde del ASR."""
    desc = unicodedata.normalize("NFD", texto)
    return "".join(c for c in desc if unicodedata.category(c) != "Mn")


def terminos(texto: str) -> list:
    """Los terminos de CONTENIDO de un texto, en orden y con repeticiones.

    Se conserva el orden y las repeticiones porque el vocabulario propio de
    una materia se aprende contando, no con conjuntos: 'derivada' dicho
    quince veces no es lo mismo que dicho una."""
    plano = _NO_LETRA.sub(" ", _sin_acentos(str(texto or "")).lower())
    return [t for t in plano.split()
            if len(t) >= 4 and t not in STOPWORDS and not t.isdigit()]


def _cobertura(bloque: set, ventana: list) -> float:
    """Fraccion de los terminos de la ventana que el bloque YA habia usado.

    Contencion y no Jaccard: el bloque crece durante la clase y Jaccard caeria
    solo por el tamanio del denominador, haciendo que cortar sea mas facil a
    las 13:00 que a las 08:30. Con contencion el criterio no depende de la
    hora."""
    unicos = set(ventana)
    if not unicos:
        return 1.0            # sin terminos no hay evidencia DE CAMBIO
    return len(unicos & bloque) / float(len(unicos))


# ── Embeddings (opcionales) ──────────────────────────────────────────────────

def embeddings_activos() -> bool:
    """True si hay backend SEMANTICO real y no esta apagado por entorno.

    Se pregunta por `semantic_model_active` y no por 'importa numpy': el
    fallback n-gram de cognia_embedding devuelve vectores igual, pero su
    coseno mide solapamiento de bigramas de caracteres, no significado, y
    UMBRAL_COSENO esta calibrado para el modelo de verdad. Confundirlos daria
    cortes al azar sin un solo error visible.
    """
    if os.environ.get("COGNIA_CLASES_SIN_EMBEDDINGS", "").strip() not in ("", "0"):
        return False
    try:
        from cognia.cognia_embedding import semantic_model_active
        return bool(semantic_model_active())
    except Exception as e:                     # noqa: BLE001 - motivo visible
        log.warning("clases/materias: sin embeddings (%s: %s); "
                    "la deriva se mide con lexico", type(e).__name__, e)
        return False


def _vector(texto: str):
    """Vector del texto, o None con motivo si el backend falla a mitad."""
    try:
        from cognia.cognia_embedding import text_to_vector_fast
        return text_to_vector_fast(texto)
    except Exception as e:                     # noqa: BLE001 - motivo visible
        log.warning("clases/materias: embedding fallido (%s: %s)",
                    type(e).__name__, e)
        return None


def _media(vectores: list):
    vivos = [v for v in vectores if v]
    if not vivos:
        return None
    n = len(vivos[0])
    return [sum(v[i] for v in vivos) / float(len(vivos)) for i in range(n)]


def _coseno(a, b) -> float:
    if not a or not b:
        return 1.0                             # sin medida, no hay evidencia
    from cognia.vectors import cosine_similarity
    return float(cosine_similarity(a, b))


# ── Entradas ─────────────────────────────────────────────────────────────────

def _normalizar_entradas(entradas) -> list:
    """Acepta Entrada o el dict crudo del JSONL. El dict aparece cuando quien
    llama viene de `almacen.leer_jsonl` sin pasar por el modelo; reventar ahi
    obligaria a cada llamador a acordarse de convertir."""
    fuera = []
    for e in entradas or []:
        if isinstance(e, dict):
            e = Entrada.de_dict(e)
        if not hasattr(e, "t"):
            log.warning("clases/materias: entrada ignorada, tipo %s sin .t",
                        type(e).__name__)
            continue
        fuera.append(e)
    fuera.sort(key=lambda x: float(x.t))
    return fuera


def _fin_de(entradas) -> float:
    return max([float(e.t_fin or e.t) for e in entradas] or [0.0])


def _habladas(entradas) -> list:
    """Solo lo transcrito CON texto: las notas y fotos del usuario no miden
    deriva de vocabulario (son cuatro palabras sueltas) y meterlas movia el
    corte al segundo en que el duenio saco una foto."""
    return [e for e in entradas
            if e.tipo == TIPO_TRANSCRIPCION and str(e.texto or "").strip()]


def _texto_entre(habladas, t0: float, t1: float) -> str:
    return " ".join(e.texto for e in habladas if t0 <= float(e.t) < t1)


# ── Senial 1: silencio ───────────────────────────────────────────────────────

# Un silencio de mas de esto ya NO es "el profesor se ha callado": es un
# cambio de clase. MEDIDO 2026-08-31: en la jornada de prueba los recreos
# reales son de 270 s y el detector los veia, pero DURACION_MINIMA (600 s, el
# largo tipico de una clase) vetaba el corte porque los bloques de prueba
# duraban 500 s. Un heuristico de duracion no puede vetar una senial
# INEQUIVOCA: cuatro minutos y medio sin que nadie hable no pasan a mitad de
# una explicacion. Con silencio concluyente el piso baja a PISO_CON_SILENCIO,
# que sigue impidiendo trocear la clase en pedacitos.
SILENCIO_CONCLUYENTE = 180.0
PISO_CON_SILENCIO = 120.0


def _piso(silencio) -> float:
    """El bloque minimo exigible para aceptar un corte en ese punto."""
    if silencio and float(silencio.get("gap") or 0.0) >= SILENCIO_CONCLUYENTE:
        return PISO_CON_SILENCIO
    return DURACION_MINIMA


def senal_silencio(entradas) -> list:
    """[{t, gap, fuerza}] por cada hueco >= SILENCIO_MINIMO.

    Publica y suelta para poder medirla sola: es la unica senial que no
    depende ni del idioma ni del modelo, y sirve de linea base contra la que
    comparar lo que aporta la deriva.
    """
    # SOLO LAS HABLADAS (2026-08-31, medido en la jornada de 28 min). La
    # transcripcion escribe una marca de PAUSA (texto vacio) tras varios
    # trozos seguidos de silencio; esa marca es metadato SOBRE el silencio, no
    # un hecho que lo termine. Contandola, cada recreo real de 270 s se partia
    # en dos huecos de 90 y 150, y la senial mas fuerte de todas -- un silencio
    # de cuatro minutos y medio entre clases -- se quedaba por debajo del
    # umbral. Con las habladas, los tres recreos salen a 510, 1020 y 1500 s
    # contra las fronteras reales 518, 1024 y 1521: ocho segundos de error.
    ent = _habladas(_normalizar_entradas(entradas))
    fuera = []
    for previa, actual in zip(ent, ent[1:]):
        gap = float(actual.t) - float(previa.t_fin or previa.t)
        if gap < SILENCIO_MINIMO:
            continue
        fuerza = min(1.0, gap / SILENCIO_SATURA)
        fuera.append({"t": float(actual.t), "gap": gap, "fuerza": fuerza})
    return fuera


# ── Senial 2: deriva de vocabulario ──────────────────────────────────────────

def senal_deriva(entradas, desde: float = 0.0, modo: str = "",
                 informe: dict = None) -> list:
    """[{t, fuerza, cobertura, sostenida, modo}] en cada frontera de entrada.

    `desde` es el inicio del bloque abierto: la comparacion es ventana nueva
    contra BLOQUE, no contra los ultimos tres minutos (ver cabecera). Por eso
    esta funcion se llama otra vez cada vez que se acepta un corte.

    `informe` es un dict opcional donde se deja `{"modo": ...}` con la medida
    que de VERDAD se uso. Hace falta porque aqui dentro se puede caer de
    embeddings a lexico (backend muerto) y quien llama tiene que poder
    DECLARARLO: la lista devuelta puede venir vacia, y entonces el modo real
    no se podria leer de ella.
    """
    modo = modo or ("embeddings" if embeddings_activos() else "lexica")
    if informe is not None:
        informe["modo"] = modo
    hab = _habladas(_normalizar_entradas(entradas))
    if len(hab) < 2:
        return []
    fin = _fin_de(hab)

    # Terminos y vectores por entrada, calculados UNA vez: el bucle de abajo
    # los pide O(n) veces y re-tokenizar seis horas de habla por candidato es
    # lo que hacia la deteccion inviable en la jornada completa.
    tokens = [terminos(e.texto) for e in hab]
    vectores = [_vector(e.texto) for e in hab] if modo == "embeddings" else []
    if modo == "embeddings" and not any(vectores):
        log.warning("clases/materias: el backend semantico no devolvio ningun "
                    "vector; deriva medida con lexico")
        modo = "lexica"
    elif modo == "embeddings":
        # Perdida PARCIAL: las ventanas que caigan en el hueco compararian
        # contra un vector medio que no existe, y `_coseno` devuelve ahi 1.0
        # (= "no hay evidencia de cambio"). Eso no puede pasar callando: seria
        # una jornada sin cortar por un backend a medias, sin nada que lo diga.
        muertos = sum(1 for v in vectores if not v)
        if muertos:
            log.warning("clases/materias: %d de %d entradas sin vector; esas "
                        "ventanas no miden deriva", muertos, len(vectores))
    if informe is not None:
        informe["modo"] = modo

    fuera = []
    for i in range(1, len(hab)):
        t = float(hab[i].t)
        if t <= desde:
            continue
        idx_bloque = [j for j in range(i) if float(hab[j].t) >= desde]
        idx_prox = [j for j in range(i, len(hab))
                    if float(hab[j].t) < t + VENTANA]
        idx_lejos = [j for j in range(i, len(hab))
                     if t + VENTANA <= float(hab[j].t) < t + 2 * VENTANA]
        if not idx_bloque or not idx_prox:
            continue

        term_bloque = [w for j in idx_bloque for w in tokens[j]]
        term_prox = [w for j in idx_prox for w in tokens[j]]
        if len(term_bloque) < MIN_TERMINOS or len(term_prox) < MIN_TERMINOS:
            continue

        if modo == "embeddings":
            v_bloque = _media([vectores[j] for j in idx_bloque])
            sim = _coseno(v_bloque, _media([vectores[j] for j in idx_prox]))
            umbral, piso = UMBRAL_COSENO, PISO_COSENO
            sim_lejos = (_coseno(v_bloque, _media([vectores[j] for j in idx_lejos]))
                         if idx_lejos else None)
        else:
            conj_bloque = set(term_bloque)
            sim = _cobertura(conj_bloque, term_prox)
            umbral, piso = UMBRAL_COBERTURA, PISO_COBERTURA
            term_lejos = [w for j in idx_lejos for w in tokens[j]]
            sim_lejos = (_cobertura(conj_bloque, term_lejos)
                         if len(term_lejos) >= MIN_TERMINOS else None)

        if sim >= umbral:
            continue
        # SOSTENIDO: si el vocabulario del bloque vuelve tres minutos despues,
        # era una digresion (el ejemplo de las pizzas), no una asignatura.
        # Al final de la jornada no hay ventana lejana: entonces no se puede
        # comprobar y se acepta con la fuerza recortada, en vez de fingir.
        if sim_lejos is not None and sim_lejos >= umbral:
            fuera.append({"t": t, "fuerza": 0.0, "cobertura": sim,
                          "sostenida": False, "modo": modo})
            continue
        # Pasar los TRES frenos (referencia al bloque, umbral y sostenido) ya
        # es evidencia suficiente por si sola: por eso la fuerza arranca en
        # UMBRAL_ACEPTA y la distancia al umbral solo la gradua. Escalarla
        # desde cero seria pedir dos veces la misma prueba.
        grado = min(1.0, max(0.0, (umbral - sim) / max(umbral - piso, 1e-6)))
        fuerza = UMBRAL_ACEPTA + (1.0 - UMBRAL_ACEPTA) * grado
        if sim_lejos is None:
            # No se pudo comprobar que la deriva se sostenga (no hay habla
            # suficiente despues). Se recorta por debajo del umbral: sola no
            # corta, pero suma si ademas hubo pausa.
            fuerza *= 0.6
        if t > fin - DURACION_MINIMA:
            # Un corte que abre un bloque mas corto que una clase no es un
            # cambio de asignatura: es el final de la manana.
            continue
        fuera.append({"t": t, "fuerza": fuerza, "cobertura": sim,
                      "sostenida": True, "modo": modo})
    return fuera


# ── Senial 3: vocabulario propio de cada materia ─────────────────────────────

_CACHE_VOCAB = {}


def olvidar_cache() -> None:
    """Tira el vocabulario aprendido. Los tests DEBEN llamarla entre casos:
    la cache vive en el modulo y sobrevive al cambio de COGNIA_CLASES_DIR,
    asi que sin esto el segundo test lee el cuaderno del primero."""
    _CACHE_VOCAB.clear()


def vocabulario_de_materias(refrescar: bool = False) -> dict:
    """{materia: {termino: peso}} aprendido del cuaderno del duenio.

    Un termino es propio de una materia si aparece MIN_APARICIONES veces en
    ella y su frecuencia relativa alli es RATIO_PROPIO veces la que tiene en
    el resto del cuaderno. Sin el ratio, 'ejercicio' seria caracteristico de
    las cinco asignaturas y no distinguiria ninguna.

    Con el cuaderno vacio devuelve {} y quien llama se apania con el nombre
    de la materia. No es un fallo: el primer dia de curso no hay historial.
    """
    clave = (str(alm.raiz()), tuple(alm.jornadas()))
    if not refrescar and clave in _CACHE_VOCAB:
        return _CACHE_VOCAB[clave]

    try:
        por_materia = cua.cuaderno()
    except Exception as e:                     # noqa: BLE001 - motivo visible
        log.warning("clases/materias: cuaderno ilegible (%s: %s); sin "
                    "vocabulario aprendido", type(e).__name__, e)
        _CACHE_VOCAB[clave] = {}
        return {}

    cuentas, total = {}, {}
    for materia, sesiones in por_materia.items():
        if not materia or materia == "Sin clasificar":
            continue
        c = cuentas.setdefault(materia, {})
        for s in sesiones:
            for w in terminos(s.texto_dicho()):
                c[w] = c.get(w, 0) + 1
                total[w] = total.get(w, 0) + 1
    suma_global = float(sum(total.values())) or 1.0

    vocab = {}
    for materia, c in cuentas.items():
        suma = float(sum(c.values())) or 1.0
        propios = {}
        for w, n in c.items():
            if n < MIN_APARICIONES:
                continue
            rel = (n / suma) / max(total[w] / suma_global, 1e-9)
            if rel >= RATIO_PROPIO:
                propios[w] = round(min(3.0, rel), 3)
        if propios:
            vocab[materia] = propios
    _CACHE_VOCAB[clave] = vocab
    return vocab


# ── Senial 4: horario ────────────────────────────────────────────────────────

def senal_horario(pistas, fin: float) -> list:
    """[{t, materia, hasta}] de las franjas del horario que caen en la jornada.

    Manda sobre las demas porque es la unica senial que no infiere nada: el
    duenio SABE a que hora tiene Fisica. Las otras solo pueden ajustar el
    limite +-TOLERANCIA_HORARIO.
    """
    horario = (pistas or {}).get("horario") or []
    fuera = []
    for franja in horario:
        try:
            desde = float(franja.get("desde", 0.0))
            materia = str(franja.get("materia") or "").strip()
        except (AttributeError, TypeError, ValueError) as e:
            log.warning("clases/materias: franja de horario ignorada (%s): %r",
                        type(e).__name__, franja)
            continue
        # `hasta` se valida APARTE y no descalifica la franja. Lo que fija el
        # corte es `desde`; `hasta` solo lo publica esta funcion. Tirar la
        # clase entera porque el duenio escribio mal el final era perder la
        # senial que "manda" sobre todas por un campo que nadie lee, y encima
        # el hueco lo rellenaba la materia anterior extendiendose sobre ella.
        try:
            hasta = float(franja.get("hasta", desde))
        except (TypeError, ValueError):
            log.warning("clases/materias: 'hasta' ilegible en la franja %r; "
                        "vale el 'desde' y el limite lo pone la franja "
                        "siguiente", franja)
            hasta = desde
        if not materia or desde > fin:
            continue
        fuera.append({"t": max(0.0, desde), "materia": materia, "hasta": hasta})
    fuera.sort(key=lambda f: f["t"])
    return fuera


# ── Nombrar ──────────────────────────────────────────────────────────────────

def _tema_de(texto: str) -> str:
    """'Tema: derivada, tangente' — el nombre honesto cuando no hay ni
    materias declaradas ni historial ni modelo. Los dos terminos de contenido
    mas repetidos dicen mas que 'Sin clasificar', que es lo que se ponia
    antes y hacia el cuaderno ilegible."""
    cuenta = {}
    for w in terminos(texto):
        cuenta[w] = cuenta.get(w, 0) + 1
    top = sorted(cuenta.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    if not top:
        return "Sin clasificar"
    return "Tema: " + ", ".join(w for w, _ in top)


def _puntuar_materias(texto: str, materias_conocidas) -> list:
    """[(materia, puntos)] ordenado. Dos aportes: que el nombre de la materia
    se diga en clase ('en matematicas...') y cuantos de sus terminos propios
    aparecen. El primero solo no basta (hay clases enteras donde nadie nombra
    la asignatura) y el segundo solo no existe el primer dia de curso."""
    presentes = set(terminos(texto))
    if not presentes:
        return []
    vocab = vocabulario_de_materias()
    fuera = []
    for materia in materias_conocidas or []:
        materia = str(materia).strip()
        if not materia:
            continue
        puntos = 0.0
        tokens_nombre = set(terminos(materia))
        if tokens_nombre and tokens_nombre & presentes:
            puntos += 0.6
        propios = vocab.get(materia) or {}
        if propios:
            tope = float(min(len(propios), 12))
            acertados = sum(1 for w in propios if w in presentes)
            puntos += 0.7 * min(1.0, acertados / tope)
        if puntos > 0:
            fuera.append((materia, round(min(0.95, puntos), 3)))
    fuera.sort(key=lambda mp: -mp[1])
    return fuera


def _preguntar_al_modelo(texto: str, materias_conocidas, orch):
    """La materia segun el modelo local, o None con motivo.

    Dos cosas, las dos medidas contra el modelo de verdad (ver
    MAX_TOKENS_NOMBRE): el presupuesto tiene que cubrir la cadena de
    pensamiento del razonador o la respuesta llega vacia, y el fragmento va
    recortado a 900 caracteres porque el prompt largo alarga esa cadena y
    encarece cada bloque de la jornada.

    Se pide el nombre EXACTO de la lista para poder validar la respuesta
    contra ella: un modelo que conteste "creo que es algo de ciencias" no
    puede acabar siendo una materia del cuaderno.

    SE LEE POR EL FINAL, y esto NO es un detalle. El mismo motivo que obliga a
    MAX_TOKENS_NOMBRE=160 -- el cerebro de la casa es un razonador y escribe
    su cadena de pensamiento en el MISMO campo que la respuesta -- hace que el
    texto contenga los nombres que el modelo considero y DESCARTO:
    "podria ser Matematicas, pero habla de trincheras: es Historia". Buscar
    "la primera materia de la lista que aparezca" devolvia ahi Matematicas,
    o sea la que el modelo acababa de rechazar, y con confianza 0.7. Se mira
    primero la ULTIMA linea (donde el razonador pone la conclusion) y, si ahi
    no hay ninguna, la ULTIMA mencion del texto entero.
    """
    lista = ", ".join(str(m) for m in materias_conocidas if str(m).strip())
    fragmento = " ".join(str(texto or "").split())[:900]
    prompt = ("Materias posibles: %s\n"
              "Fragmento de una clase grabada:\n\"%s\"\n"
              "Responde SOLO con el nombre exacto de una materia de la lista. "
              "Nada mas." % (lista, fragmento))
    try:
        salida = orch.infer(prompt, max_tokens=MAX_TOKENS_NOMBRE,
                            temperature=0.0).text or ""
    except Exception as e:                     # noqa: BLE001 - motivo visible
        log.warning("clases/materias: el modelo no nombro el bloque "
                    "(%s: %s); queda el nombre deterministico",
                    type(e).__name__, e)
        return None
    plano = _sin_acentos(salida).lower()
    lineas = [l for l in plano.splitlines() if l.strip()]
    elegida = (_ultima_materia_en(lineas[-1], materias_conocidas) if lineas
               else None)
    if elegida is None:
        elegida = _ultima_materia_en(plano, materias_conocidas)
    if elegida is not None:
        return elegida
    log.warning("clases/materias: respuesta del modelo fuera de la lista "
                "(%r); queda el nombre deterministico", salida.strip()[:60])
    return None


def _ultima_materia_en(plano: str, materias_conocidas):
    """La materia de la lista mencionada MAS TARDE en `plano`, o None.

    La ultima y no la primera porque la respuesta del razonador es lo ultimo
    que escribe (ver `_preguntar_al_modelo`). A igualdad de posicion gana el
    nombre mas largo: con "Historia" y "Historia del Arte" en la lista, la
    unica lectura que no pierde informacion es la larga.
    """
    mejor, pos_mejor, largo_mejor = None, -1, -1
    for materia in materias_conocidas or []:
        clave = _sin_acentos(str(materia)).lower().strip()
        if not clave:
            continue
        pos = plano.rfind(clave)
        if pos < 0:
            continue
        if pos > pos_mejor or (pos == pos_mejor and len(clave) > largo_mejor):
            mejor, pos_mejor, largo_mejor = str(materia), pos, len(clave)
    return mejor


def nombrar(texto, materias_conocidas=None, orch=None) -> tuple:
    """(materia, confianza 0..1) para el texto de un bloque.

    Orden: vocabulario propio -> modelo (solo si el deterministico duda, para
    no gastar el razonador en los bloques faciles) -> "Tema: ...". Nunca
    inventa una asignatura que no este en `materias_conocidas`: si el bloque
    no se parece a ninguna, decirlo vale mas que acertar por sorteo.
    """
    texto = str(texto or "")
    if not texto.strip():
        return ("Sin clasificar", 0.0)

    marcador = _puntuar_materias(texto, materias_conocidas or [])
    mejor, puntos = (marcador[0] if marcador else (None, 0.0))
    if mejor and puntos >= UMBRAL_NOMBRE_SEGURO:
        return (mejor, puntos)

    if orch is not None and materias_conocidas:
        elegida = _preguntar_al_modelo(texto, materias_conocidas, orch)
        if elegida:
            # 0.7 y no 0.95: el modelo acierta la asignatura mucho mas que el
            # lexico cuando no hay historial, pero es el unico camino del
            # modulo que no se puede reproducir dos veces igual.
            return (elegida, max(0.7, puntos))

    if mejor and puntos >= UMBRAL_NOMBRE_MINIMO:
        return (mejor, puntos)
    return (_tema_de(texto), 0.15)


# ── Deteccion ────────────────────────────────────────────────────────────────

def _senales_activas(pistas) -> dict:
    """Que seniales corren. Es el punto de extension: la siguiente senial se
    aniade aqui con su default, no en un if enterrado."""
    activas = {"silencio": True, "deriva": True, "horario": True,
               "vocabulario": True}
    pedidas = (pistas or {}).get("senales") or {}
    for k, v in pedidas.items():
        if k not in activas:
            log.warning("clases/materias: senial desconocida %r ignorada", k)
            continue
        activas[k] = bool(v)
    return activas


# Entradas seguidas que tienen que traer vocabulario nuevo para dar por
# empezada la materia siguiente. Con una sola, una frase rara del final de la
# clase anterior movia el corte; con tres (~30 s de habla) no hay falso.
CONSECUTIVAS_NUEVAS = 3


def _afinar(bloque: set, hab: list, t: float) -> float:
    """Mueve el corte al PRIMER momento en que empieza de verdad el
    vocabulario nuevo.

    Por que hace falta: la deriva se decide con una ventana de VENTANA
    segundos, y la ventana ya baja del umbral cuando solo un tercio de ella
    es de la materia nueva -- o sea, el corte cae hasta dos minutos ANTES del
    cambio real. Dos minutos se ven en el cuaderno (la sesion de Historia
    empieza con el final de Matematicas dentro). Aqui se recorre entrada a
    entrada hasta encontrar CONSECUTIVAS_NUEVAS seguidas con vocabulario que
    el bloque no habia usado, que es el cambio de verdad.

    La afinacion es SIEMPRE lexica, tambien en modo embeddings: el coseno de
    una entrada suelta de 10 s contra la media del bloque es demasiado
    ruidoso para localizar nada, y aqui no se esta decidiendo si hay corte
    (eso ya esta decidido) sino solo donde ponerlo.
    """
    indices = [i for i, e in enumerate(hab)
               if t <= float(e.t) < t + VENTANA]
    seguidas, inicio = 0, None
    for i in indices:
        tokens = terminos(hab[i].texto)
        if len(tokens) < 2:
            continue            # "vale, seguimos" no vota ni a favor ni en contra
        if _cobertura(bloque, tokens) < UMBRAL_COBERTURA:
            if seguidas == 0:
                inicio = i      # el indice del arranque, no i-N: las entradas
                                # sin terminos se saltan y la resta mentiria
            seguidas += 1
            if seguidas >= CONSECUTIVAS_NUEVAS:
                return float(hab[inicio].t)
        else:
            seguidas, inicio = 0, None
    return t


def _ajustar_al_silencio(t: float, silencios: list) -> tuple:
    """Pega el limite del horario al silencio real mas cercano dentro de la
    tolerancia. Devuelve (t_ajustado, hubo_silencio): lo segundo entra en la
    confianza, porque un limite del horario CORROBORADO por una pausa vale
    mas que uno que cae en mitad de una frase."""
    cercanos = [s for s in silencios if abs(s["t"] - t) <= TOLERANCIA_HORARIO]
    if not cercanos:
        return (t, False)
    mejor = min(cercanos, key=lambda s: abs(s["t"] - t))
    return (mejor["t"], True)


def detectar(entradas, materias_conocidas=None, pistas=None, orch=None) -> list:
    """Los cortes de materia de una jornada.

    [{t, materia, confianza, por}] ordenado por t, SIEMPRE con un corte en
    t=0.0 (`cuaderno.sesiones_de` mete uno "antes del primer corte" si falta,
    y esa sesion fantasma sin nombre era el bug visible del cuaderno).

    Devolver un solo corte no es fracasar: una jornada con una sola clase
    tiene exactamente un corte. Cortar de mas si lo es.
    """
    ent = _normalizar_entradas(entradas)
    if not ent:
        return [{"t": 0.0, "materia": "Sin clasificar", "confianza": 0.0,
                 "por": "jornada vacia"}]

    activas = _senales_activas(pistas)
    materias_conocidas = list(materias_conocidas or [])
    if not activas["vocabulario"]:
        materias_conocidas = []
    hab = _habladas(ent)
    fin = _fin_de(ent)
    modo = "embeddings" if (activas["deriva"] and embeddings_activos()) else "lexica"
    silencios = senal_silencio(ent) if activas["silencio"] else []

    # ── Camino 1: hay horario. Manda: fija los limites, las demas seniales
    # solo ajustan +-TOLERANCIA_HORARIO y suben o bajan la confianza.
    franjas = senal_horario(pistas, fin) if activas["horario"] else []
    if franjas:
        crudos = []
        for f in franjas:
            t, corroborado = _ajustar_al_silencio(f["t"], silencios)
            crudos.append({"t": round(float(t), 3), "materia": f["materia"],
                           "confianza": 0.95 if corroborado else 0.8,
                           "por": "horario" + (" + silencio" if corroborado
                                               else " (sin pausa que lo confirme)")})
        crudos.sort(key=lambda c: c["t"])
        if crudos[0]["t"] > 0.0:
            texto = _texto_entre(hab, 0.0, crudos[0]["t"])
            materia, conf = nombrar(texto, materias_conocidas, orch)
            crudos.insert(0, {"t": 0.0, "materia": materia,
                              "confianza": round(0.5 * conf, 3),
                              "por": "antes de la primera franja del horario"})
        else:
            crudos[0]["t"] = 0.0
        return _fundir(crudos)

    # ── Camino 2: sin horario. Silencio + deriva, en orden de tiempo, con
    # el bloque abierto como referencia (por eso senal_deriva se recalcula
    # tras cada corte aceptado y no una vez al principio).
    cortes = [{"t": 0.0, "evidencia": 1.0, "por": []}]
    ultimo = 0.0
    guardia = 0
    # `modo` es la medida PEDIDA; `modo_real` la que senal_deriva pudo usar.
    # No son la misma cosa cuando el backend semantico se cae a mitad, y el
    # "por" tiene que declarar la que se uso: escribir "deriva embeddings"
    # sobre un corte decidido con lexico invalida los umbrales que el lector
    # creeria aplicados (UMBRAL_COSENO=0.75 vs UMBRAL_COBERTURA=0.30).
    modo_real = modo
    while guardia < 64:
        guardia += 1
        informe = {}
        derivas = (senal_deriva(hab, desde=ultimo, modo=modo, informe=informe)
                   if activas["deriva"] else [])
        modo_real = informe.get("modo", modo_real)
        por_t = {}
        for d in derivas:
            if d["fuerza"] > 0:
                por_t[d["t"]] = {"deriva": d}
        for s in silencios:
            if s["t"] <= ultimo + _piso(s) or s["t"] > fin - _piso(s):
                continue
            por_t.setdefault(s["t"], {})["silencio"] = s

        candidato = None
        for t in sorted(por_t):
            piso = _piso(por_t[t].get("silencio"))
            if t - ultimo < piso or t > fin - piso:
                continue
            fs = por_t[t].get("silencio", {}).get("fuerza", 0.0)
            fd = por_t[t].get("deriva", {}).get("fuerza", 0.0)
            evidencia = 1.0 - (1.0 - fs) * (1.0 - fd)
            if evidencia < UMBRAL_ACEPTA:
                continue
            motivos = []
            t_corte = t
            if fs > 0:
                motivos.append("silencio %ds" % int(por_t[t]["silencio"]["gap"]))
            if fd > 0:
                motivos.append("vocabulario nuevo sostenido (deriva %s, "
                               "similitud %.2f)"
                               % (por_t[t]["deriva"]["modo"],
                                  por_t[t]["deriva"]["cobertura"]))
                if fs <= 0:
                    # Con pausa, el corte ya esta en el sitio exacto (el
                    # primer segundo de habla tras el hueco). Sin pausa hay
                    # que afinar: la ventana adelanta el corte (ver _afinar).
                    bloque = set(w for e in hab if ultimo <= float(e.t) < t
                                 for w in terminos(e.texto))
                    afinado = _afinar(bloque, hab, t)
                    if afinado <= fin - DURACION_MINIMA:
                        t_corte = afinado
            candidato = {"t": t_corte, "evidencia": evidencia, "por": motivos}
            break                      # el primero en el tiempo: el bloque
                                       # nuevo pasa a ser la referencia
        if candidato is None:
            break
        cortes.append(candidato)
        ultimo = candidato["t"]

    # El tope solo es un aviso si se llego a el CORTANDO: salir por falta de
    # candidatos en la vuelta 64 es el final normal de una jornada larga.
    if guardia >= 64 and candidato is not None:
        log.warning("clases/materias: tope de 64 cortes en una jornada; "
                    "se para (revisar DURACION_MINIMA=%.0fs)", DURACION_MINIMA)

    # Nombrar cada bloque con TODO su texto (no con la ventana del corte: el
    # profesor dice de que va la clase en cualquier momento de la hora).
    fuera = []
    for i, c in enumerate(cortes):
        t1 = cortes[i + 1]["t"] if i + 1 < len(cortes) else fin + 1.0
        materia, conf = nombrar(_texto_entre(hab, c["t"], t1),
                                materias_conocidas, orch)
        motivos = list(c["por"]) or ["inicio de jornada"]
        if not activas["deriva"]:
            motivos.append("deriva apagada")
        elif modo_real == "lexica":
            motivos.append("medida lexica (sin embeddings)"
                           if modo == "lexica" else
                           "medida lexica (el backend de embeddings fallo)")
        if not materias_conocidas:
            motivos.append("sin materias conocidas")
        fuera.append({"t": round(float(c["t"]), 3), "materia": materia,
                      "confianza": round(min(1.0, 0.5 * c["evidencia"]
                                             + 0.5 * conf), 3),
                      "por": "; ".join(motivos)})
    return _fundir(fuera)


def _fundir(cortes: list) -> list:
    """Junta bloques CONSECUTIVOS con la misma materia.

    Pasa de verdad: una clase doble con recreo en medio dispara la senial de
    silencio, y ahi el corte es correcto pero la sesion no: son dos horas de
    lo mismo. Fundir aqui y no evitar el corte deja la evidencia intacta (el
    silencio se detecto) sin partir la sesion en el cuaderno.

    LA FUSION SE DECLARA EN "por", y no es adorno. Sin decirlo, un corte de
    mas DENTRO de una misma materia -- el fallo caro de este modulo -- es
    INVISIBLE desde fuera: los dos bloques se llaman igual, se funden, y el
    resultado tiene el mismo aspecto que no haber cortado. Los
    contrafactuales del test (una sola materia seguida, la digresion de la
    pizza) no podian distinguir "no corto" de "corto y se tapo".
    """
    fuera = []
    for c in sorted(cortes, key=lambda x: float(x["t"])):
        if fuera and fuera[-1]["materia"] == c["materia"]:
            fuera[-1]["confianza"] = max(fuera[-1]["confianza"], c["confianza"])
            fuera[-1]["por"] = ("%s; fundido con el bloque de %ds (misma "
                                "materia)" % (fuera[-1]["por"],
                                              int(float(c["t"]))))
            continue
        fuera.append(dict(c))
    if fuera:
        fuera[0]["t"] = 0.0
    return fuera
