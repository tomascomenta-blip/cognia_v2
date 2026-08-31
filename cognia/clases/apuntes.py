# -*- coding: utf-8 -*-
"""
cognia/clases/apuntes.py
========================
De la TRANSCRIPCION CRUDA de una clase a los APUNTES que un buen alumno
habria escrito.

QUE ENTRA Y QUE SALE. Entra una `Sesion` del cuaderno (50 minutos de habla
transcrita, mas lo que el duenio aniadio a mano) y sale un dict con las
secciones de una hoja de cuaderno: titulo, resumen, ideas clave,
definiciones, formulas, deberes, dudas y "esto entra en el examen".

TRES DECISIONES QUE MANDAN SOBRE EL RESTO

1. LO DEL DUENIO NO SE TOCA. `Sesion.del_usuario()` (notas, marcas, fotos de
   la pizarra, clips) es el unico contenido del cuaderno del que CONSTA que a
   alguien le importo: no se resume, no se reescribe y no se traduce. Entra
   LITERAL y va primero. Lo marcado `importante=True` tiene garantia dura de
   aparecer en 'claves' o en 'examen' -- se comprueba al final, en todos los
   caminos (tambien al releer unos apuntes ya guardados), porque una garantia
   que solo vale en el camino feliz no es una garantia.

2. SIN MODELO NO SE DEVUELVE UN CUADERNO EN BLANCO. Con `orch=None` (o si el
   modelo se calla) se cae a un extractivo deterministico: frases con mayor
   densidad de terminos de contenido, mas deteccion lexica de deberes, de
   examen, de definiciones y de formulas por patron. Peor que el modelo, si;
   pero el fallo tipico de este repo es el vacio silencioso, y unos apuntes
   pobres se corrigen a mano en dos minutos mientras que una hoja vacia
   obliga a volver a escuchar la clase entera. El camino usado se dice en
   'via' ('modelo' | 'extractivo' | 'vacio') y el motivo en 'aviso'.

3. LA CLASE NO CABE EN LA VENTANA. 50 minutos son del orden de 40 000 chars.
   Se trocea en ventanas con solape, se pide una extraccion CORTA por ventana
   y se funden los resultados. MEDIDO EN ESTE REPO EL 2026-08-30: el modelo
   local es un razonador y con `max_tokens` grande se va a pensar y devuelve
   CERO contenido -- por eso cada llamada pide salida etiquetada, de pocas
   lineas, con tope chico (_TOK_VENTANA). Una ventana que vuelve vacia cae al
   extractivo SOLO en esa ventana y lo deja escrito en 'aviso'.

QUE SE REUSA Y QUE NO
  - `compactacion.cap_chars()` (el knob COGNIA_COMPACT_CAP que ya gobierna
    cuanto texto de resumen tolera el harness) fija el presupuesto del
    resumen. Su `compactar()` NO sirve aqui: opera sobre una lista de
    mensajes de chat y sobre el canal de estado del agente, no sobre prosa.
  - `summarizer/session_summarizer.py` se leyo y se descarto a proposito: su
    ranking es unicos/total, que premia frases CORTAS ("bueno, seguimos"
    puntua 1.0), y ademas esta atado a la sesion de chat y a su tabla SQL.
    Aqui el peso es TF sobre el texto de la clase: lo que el profesor repite
    es el tema del dia.

API publica:
    generar(sesion, orch=None, forzar=False) -> dict con claves fijas
    generar_jornada(nombre, orch=None, progreso=None) -> {'0': apuntes, ...}
        y los GUARDA en apuntes.json (via almacen), sesion a sesion
    compactar(texto, tope_chars) -> str   reduccion por relevancia
"""

from __future__ import annotations

import logging
import math
import re

from cognia.clases import almacen as alm
from cognia.clases import cuaderno as cua

_log = logging.getLogger(__name__)

# Ventanas de troceo. 2500 chars son ~400 palabras: un bloque en el que el
# profesor no ha cambiado de tema, y un prompt que le cabe holgado a un 3B
# junto con la instruccion. El solape evita partir en dos una definicion que
# cae justo en el corte.
_VENTANA_CHARS = 2500
_SOLAPE_CHARS = 200
# Tope de llamadas al modelo por sesion. Una clase muy larga se pre-compacta
# a este presupuesto antes de trocear: 12 llamadas ya son minutos de espera y
# el duenio genera la jornada entera, no una sesion.
_MAX_VENTANAS = 12
# Presupuestos de salida, cortos A PROPOSITO (ver decision 3 del encabezado).
_TOK_VENTANA = 320
_TOK_RESUMEN = 200
_TOK_TITULO = 32
_TEMP = 0.2

# Cuanto de cada seccion se guarda. Unos apuntes con 40 "ideas clave" no son
# apuntes, son la transcripcion otra vez.
_MAX_CLAVES = 8
_MAX_DEFINICIONES = 8
_MAX_FORMULAS = 6
_MAX_LISTA = 8
_MAX_FRASE = 240

_CLAVES_DICT = ("titulo", "resumen", "claves", "definiciones", "formulas",
                "deberes", "dudas", "examen", "chars_entrada", "chars_salida",
                "via", "aviso")

VIA_MODELO = "modelo"
VIA_EXTRACTIVO = "extractivo"
VIA_VACIO = "vacio"


# ── Normalizacion sin perder posiciones ──────────────────────────────────────

# Tabla de traduccion 1 a 1. Se usa `str.translate` y no `unicodedata.NFD` +
# quitar combinantes porque NFD CAMBIA LA LONGITUD de la cadena: aqui se
# buscan patrones sobre el texto normalizado y se recorta el texto ORIGINAL
# con esos mismos indices, asi que la normalizacion tiene que ser caracter a
# caracter. De paso, todo el lexico de mas abajo puede escribirse sin tildes.
_TILDES = str.maketrans(
    "áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ",
    "aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC",
)


def _norm(texto: str) -> str:
    """Minusculas y sin tildes, MISMA longitud que la entrada."""
    return (texto or "").translate(_TILDES).lower()


# Palabras vacias. Se toman las del grafo de conocimiento (cognia.config
# KG_STOPWORDS) para no mantener dos listas del mismo idioma que se separen
# con el tiempo; si ese import se cae (config arrastra dependencias
# opcionales), se sigue con el minimo local y se DICE en el log -- quedarse
# sin stopwords solo empeora el ranking, no impide hacer apuntes.
_VACIAS_LOCALES = {
    # Muletillas de clase: no aparecen en un corpus escrito y aqui son la
    # mitad de lo que se transcribe.
    "bueno", "vale", "entonces", "claro", "mira", "venga", "vamos", "vale",
    "veis", "vemos", "aqui", "ahora", "bien", "pues", "eso", "esto", "hacer",
    "hace", "tiene", "tienen", "puede", "pueden", "vamos", "decir", "cosa",
    "cosas", "poco", "mucho", "muy", "todo", "toda", "todos", "todas", "otra",
    "otro", "cada", "cual", "cuales", "para", "porque", "sobre", "entre",
    "seria", "tambien", "solo", "asi", "hay", "han", "son", "fue", "ser",
    "esta", "este", "estos", "estas", "una", "uno", "los", "las", "del",
    "que", "con", "por", "como", "sus", "les", "nos", "sin", "mas",
}
try:
    from cognia.config import KG_STOPWORDS as _KG
    _VACIAS = frozenset(_norm(w) for w in _KG) | _VACIAS_LOCALES
except Exception as exc:                      # pragma: no cover - depende del entorno
    _log.warning("apuntes: sin KG_STOPWORDS (%s); ranking con el lexico local", exc)
    _VACIAS = frozenset(_VACIAS_LOCALES)


# ── Lexico de la clase (todo en minusculas y SIN tildes: se busca sobre _norm) ─

_LEX_EXAMEN = (
    "entra en el examen", "esto entra", "eso entra", "para el examen",
    "cae en el examen", "cae en examen", "en el examen", "de examen",
    "lo voy a preguntar", "lo pregunto", "os lo pregunto", "materia de examen",
    "entra en la prueba", "entra en el parcial", "para el parcial",
)
_LEX_DEBERES = (
    "para manana", "para el lunes", "para el martes", "para el miercoles",
    "para el jueves", "para el viernes", "de deberes", "los deberes",
    "de tarea", "queda de tarea", "hacer los ejercicios", "haced los ejercicios",
    "ejercicios del", "ejercicio del", "hay que entregar", "para entregar",
    "entregar el", "traed", "traer para", "hay que traer",
)
_LEX_DUDA = (
    "no entiendo", "no me queda claro", "no queda claro", "no lo entiendo",
    "no lo pillo", "esto no lo", "duda:", "revisar", "preguntar al profesor",
    "preguntarle al profesor", "mirar esto", "no se por que",
)
# Marcadores de definicion. El grupo captura lo que va DESPUES; el termino se
# reconstruye con las ultimas palabras de antes (los profesores dicen "la
# energia cinetica se define como...", nunca al reves).
_LEX_DEFINICION = (
    "se define como", "se conoce como", "se denomina", "definimos como",
    "por definicion es", "se llama",
)
_RE_LLAMAMOS = re.compile(r"\bllamamos\s+(?P<term>[\w\- ]{2,40}?)\s+a\s+(?P<def>.{5,200})")
# Formula escrita: un identificador corto, un '=' y algo que no cierre frase.
# La coma CORTA a proposito: sin ella, "v = d / t, donde v es la velocidad, d
# es el espacio..." se guardaba entero como si fuera la formula (visto en la
# salida real del 2026-08-31).
_RE_FORMULA = re.compile(r"\b[a-z][a-z0-9_]{0,11}\s*=\s*[^.;:,\n]{1,40}")
# Un profesor que DICTA una formula la anuncia; una frase que solo menciona la
# palabra no lo es. Va con \b y no con `in`: buscar "formula de" como subcadena
# tambien casaba "formula DEspejada" y colaba en 'formulas' la frase "son la
# misma formula despejada" (visto en la salida real del 2026-08-31).
_RE_DICTA_FORMULA = re.compile(
    r"\b(?:formula|ecuacion|expresion)\s+(?:es|de|del|queda|seria)\b"
    r"|\bse calcula\s+(?:como|asi)\b")
_RE_FRASE = re.compile(r"[^.!?;\n]+")
# El bloque de razonamiento del modelo local (ver _sin_razonamiento).
_RE_THINK = re.compile(r"<think>.*?</think>", re.S)
_RE_PALABRA = re.compile(r"[a-z0-9]+")


# ── compactar: reduccion deterministica por relevancia ───────────────────────

def _frases(texto: str) -> list:
    """[(ini, fin, original)] de las frases con contenido. Se guardan los
    indices para poder devolver SIEMPRE el texto original (con sus tildes)
    aunque el analisis se haga sobre la version normalizada."""
    fuera = []
    for m in _RE_FRASE.finditer(texto or ""):
        crudo = m.group(0).strip()
        if len(crudo) < 12:               # "vale", "seguimos": ruido de aula
            continue
        ini = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
        fuera.append((ini, ini + len(crudo), crudo))
    return fuera


def _pesos(texto_norm: str) -> dict:
    """TF de los terminos de contenido. Lo que el profesor REPITE es el tema
    del dia: ese es todo el criterio de relevancia que hay sin modelo."""
    pesos: dict = {}
    for w in _RE_PALABRA.findall(texto_norm):
        if len(w) >= 4 and w not in _VACIAS:
            pesos[w] = pesos.get(w, 0) + 1
    return {w: 1.0 + math.log(n) for w, n in pesos.items()}


def _puntuar(frase_norm: str, pesos: dict) -> float:
    """Densidad de terminos de contenido, normalizada por la raiz del largo.

    Sin el sqrt gana siempre la frase mas larga; dividiendo por el largo
    entero gana el aullido de tres palabras (ese es justo el defecto del
    ranking de session_summarizer). La raiz es el punto medio y es el que
    hace que salgan frases de clase de verdad.
    """
    palabras = _RE_PALABRA.findall(frase_norm)
    if not palabras:
        return 0.0
    utiles = {w for w in palabras if len(w) >= 4 and w not in _VACIAS}
    bruto = sum(pesos.get(w, 1.0) for w in utiles)
    extra = 0.0
    for lex in (_LEX_EXAMEN, _LEX_DEBERES, _LEX_DEFINICION):
        if any(p in frase_norm for p in lex):
            extra += 3.0                  # lo que se pregunta y lo que se entrega manda
    return bruto / math.sqrt(len(palabras)) + extra


def compactar(texto: str, tope_chars: int) -> str:
    """Recorta `texto` a <= `tope_chars` quedandose con las frases mas
    relevantes, EN SU ORDEN ORIGINAL.

    El orden importa: un resumen con las frases reordenadas por puntuacion se
    lee como una lista de fragmentos sueltos, no como apuntes. Es
    deterministico (mismo texto -> misma salida) porque lo consume tanto el
    camino sin modelo como el troceado, y un resumen que cambia entre
    corridas hace imposible comparar dos generaciones.
    """
    texto = (texto or "").strip()
    tope = int(tope_chars or 0)
    if tope <= 0:
        return ""
    if len(texto) <= tope:
        return texto

    frases = _frases(texto)
    if not frases:
        return _cortar(texto, tope)

    norm = _norm(texto)
    pesos = _pesos(norm)
    ranking = sorted(
        range(len(frases)),
        key=lambda i: (-_puntuar(norm[frases[i][0]:frases[i][1]], pesos), i),
    )

    elegidas, usado = [], 0
    for i in ranking:
        # El separador cuesta 2 ('. '): se reponen los puntos que el troceo
        # por frases quito, porque una tira de frases pegadas con espacios se
        # lee como una sola frase absurda de 500 chars.
        coste = len(frases[i][2]) + (2 if elegidas else 0)
        if usado + coste > tope:
            continue                      # se sigue: cabe una frase mas corta
        elegidas.append(i)
        usado += coste
    if not elegidas:
        return _cortar(texto, tope)
    return ". ".join(frases[i][2] for i in sorted(elegidas))


def _cortar(texto: str, tope: int) -> str:
    """Corte duro por palabra. Ultimo recurso: una sola frase mas larga que
    todo el presupuesto (pasa con transcripciones sin puntuacion)."""
    if len(texto) <= tope:
        return texto
    trozo = texto[:tope]
    hueco = trozo.rfind(" ")
    return (trozo[:hueco] if hueco > tope * 0.6 else trozo).rstrip()


# ── Extraccion lexica (el camino sin modelo) ─────────────────────────────────

def _contiene(frase_norm: str, lexico) -> bool:
    return any(p in frase_norm for p in lexico)


def _limpiar_termino(antes: str) -> str:
    """El termino son las ultimas palabras antes del marcador, pero cortadas
    por la coma: sin esto, "...y aparece la aceleracion, que se define como"
    daba el termino "y aparece la aceleracion, que" (salida real del
    2026-08-31). Tambien se tira el 'que' final y los conectores de delante.

    Se prueban los trozos de DERECHA a IZQUIERDA: en "...aparece la
    aceleracion, que se define como", el ultimo trozo es solo "que" y el
    termino de verdad esta en el anterior. Quedarse con el ultimo perdia esa
    definicion entera.
    """
    for trozo in reversed(re.split(r"[,;:]", antes)):
        palabras = trozo.split()
        while palabras and _norm(palabras[-1]) in ("que", "se", "y", "e", "o"):
            palabras.pop()
        while palabras and _norm(palabras[0]) in ("y", "e", "o", "pero", "aqui",
                                                  "aparece", "entonces", "pues"):
            palabras.pop(0)
        cola = palabras[-5:]
        # Un termino en espaniol empieza en su determinante: cortando por el
        # ULTIMO articulo, "cambia y aparece la aceleracion" queda en "la
        # aceleracion", que es lo que el duenio buscaria en el indice.
        for i in range(len(cola) - 2, -1, -1):
            if _norm(cola[i]) in ("el", "la", "los", "las", "un", "una", "unos",
                                  "unas", "lo"):
                cola = cola[i:]
                break
        limpio = " ".join(cola).strip(" ,:;-")
        if len(limpio) >= 3:
            return limpio
    return ""


def _definiciones_de(texto: str) -> list:
    """[{'termino','definicion'}] por patron. El termino son las ultimas
    palabras antes del marcador, que es como se dicen en voz alta."""
    norm = _norm(texto)
    fuera, vistos = [], set()
    for ini, fin, crudo in _frases(texto):
        fn = norm[ini:fin]
        for marca in _LEX_DEFINICION:
            pos = fn.find(marca)
            if pos < 0:
                continue
            termino = _limpiar_termino(crudo[:pos].strip(" ,:;"))
            definicion = crudo[pos + len(marca):].strip(" ,:;-")[:_MAX_FRASE]
            if len(termino) >= 3 and len(definicion) >= 5:
                clave = _norm(termino)
                if clave not in vistos:
                    vistos.add(clave)
                    fuera.append({"termino": termino, "definicion": definicion})
            break
        m = _RE_LLAMAMOS.search(fn)
        if m:
            termino = crudo[m.start("term"):m.end("term")].strip(" ,:;-")
            definicion = crudo[m.start("def"):m.end("def")].strip(" ,:;-")[:_MAX_FRASE]
            clave = _norm(termino)
            if len(termino) >= 3 and clave not in vistos:
                vistos.add(clave)
                fuera.append({"termino": termino, "definicion": definicion})
    return fuera[:_MAX_DEFINICIONES]


def _formulas_de(texto: str) -> list:
    """Formulas escritas ('v = d / t') y, si no las hay en la frase, la frase
    entera cuando el profesor anuncia una ('la formula de la velocidad es...').
    El dictado de una formula sin simbolos es inutil si se pierde el contexto,
    por eso en ese caso se guarda la frase y no un trozo."""
    norm = _norm(texto)
    fuera, vistas = [], set()
    for ini, fin, crudo in _frases(texto):
        fn = norm[ini:fin]
        escritas = [m.group(0).strip(" ,;") for m in _RE_FORMULA.finditer(fn)]
        if escritas:
            for e in escritas:
                # Se recorta del ORIGINAL con los indices del normalizado.
                pos = fn.find(e)
                real = crudo[pos:pos + len(e)].strip(" ,;")
                if _norm(real) not in vistas:
                    vistas.add(_norm(real))
                    fuera.append(real)
        elif _RE_DICTA_FORMULA.search(fn):
            corto = crudo[:_MAX_FRASE]
            if _norm(corto) not in vistas:
                vistas.add(_norm(corto))
                fuera.append(corto)
    return fuera[:_MAX_FORMULAS]


def _por_lexico(texto: str, lexico) -> list:
    """Las frases que disparan un lexico, enteras y en orden. Enteras porque
    'para manana' sin lo que sigue no es un deber."""
    norm = _norm(texto)
    fuera, vistas = [], set()
    for ini, fin, crudo in _frases(texto):
        if _contiene(norm[ini:fin], lexico):
            corto = crudo[:_MAX_FRASE]
            if _norm(corto) not in vistas:
                vistas.add(_norm(corto))
                fuera.append(corto)
    return fuera[:_MAX_LISTA]


def _claves_extractivas(texto: str, excluir: list) -> list:
    """Las frases de mayor densidad que NO se hayan usado ya en otra seccion:
    repetir el deber en 'claves' gasta el sitio de una idea."""
    fuera = []
    ya = {_norm(x) for x in excluir}
    resumen = compactar(texto, _MAX_CLAVES * 160)
    for _, _, crudo in _frases(resumen):
        corto = crudo[:_MAX_FRASE]
        if _norm(corto) in ya:
            continue
        ya.add(_norm(corto))
        fuera.append(corto)
        if len(fuera) >= _MAX_CLAVES:
            break
    return fuera


def _frases_de(texto: str) -> list:
    """Solo los textos de las frases (sin indices). Lo consume el 'excluir' de
    las claves."""
    return [c for _, _, c in _frases(texto)]


def _delante(del_duenio: list, generado: list, cupo: int) -> list:
    """Lo del duenio primero y COMPLETO; lo generado detras y recortado al
    cupo. Al reves, unas notas prolijas dejarian fuera lo generado o -- peor --
    el recorte se comeria una nota suya."""
    ya = {_norm(x) for x in del_duenio}
    resto = [g for g in generado if _norm(g) not in ya]
    return list(del_duenio) + resto[:max(1, cupo - len(del_duenio))]


def _presupuesto_resumen(texto: str) -> int:
    """Chars del resumen: la quinta parte de la clase, con suelo y con el techo
    del knob del harness. Un resumen de tope fijo es absurdo en los dos
    extremos -- 1200 chars para una clase de 1500 no resume nada, y para una de
    40 000 se queda corto igual que 700."""
    return max(300, min(_cap_resumen(), len(texto) // 5))


def _titulo_extractivo(sesion, texto: str) -> str:
    """Materia + los dos terminos mas repetidos. No es bonito, pero un titulo
    generico ('Apuntes') hace inutil la lista de sesiones del cuaderno."""
    materia = (getattr(sesion, "materia", "") or "Sin clasificar").strip()
    pesos = _pesos(_norm(texto))
    # Se prefieren terminos largos: los de 4-5 letras que sobreviven al filtro
    # de vacias suelen ser genericos ("media", "hora") y dan titulos que no
    # distinguen una sesion de otra, que es justo para lo que sirve el titulo.
    largos = {w: p for w, p in pesos.items() if len(w) >= 6}
    fuente = largos or pesos
    top = sorted(fuente.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    if not top:
        return materia
    return "%s: %s" % (materia, ", ".join(w for w, _ in top))


# ── Lo que el duenio aniadio a mano ──────────────────────────────────────────

def _texto_del_usuario(e) -> str:
    """El texto LITERAL de una entrada del duenio, sin tocar ni un caracter.

    Para imagen/audio sin texto se devuelve un puntero al adjunto: no es
    reescribir nada, es la unica forma de que la foto de la pizarra exista en
    la hoja de apuntes.
    """
    texto = (getattr(e, "texto", "") or "").strip()
    if texto:
        return texto
    adj = (getattr(e, "adjunto", "") or "").strip()
    tipo = getattr(e, "tipo", "")
    if adj:
        return "[%s: %s]" % (tipo, adj)
    if tipo == cua.TIPO_MARCA:
        return "[marca en %.0f s]" % float(getattr(e, "t", 0.0) or 0.0)
    return ""


def _repartir_usuario(usuario: list) -> tuple:
    """(para_claves, para_examen, para_dudas) con lo del duenio, LITERAL y en
    orden: las marcadas importante primero.

    El reparto es por DONDE lo va a buscar el duenio: una nota que habla de
    examen a 'examen' (la vispera se lee esa seccion y ninguna otra), un "no
    me queda claro" a 'dudas'. Lo marcado importante NUNCA va a dudas: su
    garantia es aparecer en claves o examen y una garantia con excepciones no
    se puede comprobar.
    """
    claves, examen, dudas = [], [], []
    for e in sorted(usuario, key=lambda x: (not getattr(x, "importante", False),
                                            float(getattr(x, "t", 0.0) or 0.0))):
        txt = _texto_del_usuario(e)
        if not txt:
            continue
        norm = _norm(txt)
        if _contiene(norm, _LEX_EXAMEN):
            examen.append(txt)
        elif _contiene(norm, _LEX_DUDA) and not getattr(e, "importante", False):
            dudas.append(txt)
        else:
            claves.append(txt)
    return claves, examen, dudas


def _asegurar_importantes(ap: dict, usuario: list) -> dict:
    """Garantia dura: todo lo marcado importante=True esta en 'claves' o en
    'examen', y esta LITERAL. Se aplica en TODOS los caminos (modelo,
    extractivo y relectura de unos apuntes ya guardados) porque una garantia
    que solo vale en el camino feliz no es una garantia -- el modelo puede
    haber reescrito la nota, y unos apuntes viejos pueden ser de antes de que
    el duenio marcara la nota."""
    presentes = {_norm(x) for x in (ap.get("claves") or [])}
    presentes |= {_norm(x) for x in (ap.get("examen") or [])}
    for e in usuario:
        if not getattr(e, "importante", False):
            continue
        txt = _texto_del_usuario(e)
        if not txt or _norm(txt) in presentes:
            continue
        destino = "examen" if _contiene(_norm(txt), _LEX_EXAMEN) else "claves"
        ap[destino] = [txt] + list(ap.get(destino) or [])
        presentes.add(_norm(txt))
    return ap


# ── El modelo ────────────────────────────────────────────────────────────────

_PROMPT_VENTANA = (
    "Eres un alumno tomando apuntes de una clase. Del FRAGMENTO de abajo\n"
    "extrae SOLO lo que aparezca en el, sin inventar nada.\n"
    # El "en espanol" no es decorativo: medido el 2026-08-31, con el fragmento
    # en espaniol y sin la instruccion, el modelo local contesto en INGLES y
    # dejo unos apuntes que el duenio no puede ni leer en clase.
    "Escribe en espanol, con las palabras del profesor.\n"
    "Responde en lineas con estas etiquetas y NADA mas (maximo 8 lineas):\n"
    "CLAVE: idea principal en una linea\n"
    "DEF: termino | definicion\n"
    "FORM: formula\n"
    "DEBER: tarea o entrega\n"
    "EXAMEN: lo que el profesor dijo que entra\n"
    "DUDA: lo que quedo sin explicar\n"
    "Omite la etiqueta que no aplique. No expliques tu razonamiento.\n\n"
    "FRAGMENTO:\n%s\n"
)


def _sin_razonamiento(texto: str) -> str:
    """Quita el bloque <think> del razonador.

    MEDIDO EL 2026-08-31 con el modelo local: pedirle el titulo devolvio
    literalmente "<think>\\nThe user wants me to..." y el titulo de la sesion
    quedo en "<think>". El bloque hay que quitarlo AQUI, en la unica puerta
    por la que pasa todo lo que dice el modelo, y no en cada llamada -- y si
    lo unico que hay es razonamiento, esto devuelve '' y el llamador cae al
    extractivo, que es justo el caso 'se fue a pensar y no emitio nada'.
    """
    limpio = _RE_THINK.sub(" ", texto or "")
    abre = limpio.find("<think>")
    if abre >= 0:                          # se quedo pensando: no cerro la etiqueta
        limpio = limpio[:abre]
    cierra = limpio.rfind("</think>")      # cerro sin abrir (pasa con algunos templates)
    if cierra >= 0:
        limpio = limpio[cierra + len("</think>"):]
    return limpio.strip()


def _infer(orch, prompt: str, max_tokens: int) -> str:
    """Una llamada al modelo, con el motivo del fallo VISIBLE. Devuelve '' si
    no hay texto util: el llamador decide si eso es caer al extractivo."""
    try:
        r = orch.infer(prompt, max_tokens=max_tokens, temperature=_TEMP)
    except Exception as exc:
        _log.warning("apuntes: el modelo fallo (%s: %s)", type(exc).__name__, exc)
        return ""
    crudo = (getattr(r, "text", "") or "").strip()
    texto = _sin_razonamiento(crudo)
    if not texto:
        _log.warning("apuntes: el modelo no dejo nada util con max_tokens=%d "
                     "(%d chars, todos de razonamiento)", max_tokens, len(crudo))
    return texto


def _ventanas(texto: str, ancho: int, solape: int) -> list:
    """Trozos de <= ancho chars cortados en un espacio, con solape para no
    partir en dos una definicion que cae justo en el limite."""
    texto = texto.strip()
    if len(texto) <= ancho:
        return [texto] if texto else []
    fuera, i = [], 0
    while i < len(texto):
        fin = min(i + ancho, len(texto))
        if fin < len(texto):
            hueco = texto.rfind(" ", i + int(ancho * 0.6), fin)
            if hueco > i:
                fin = hueco
        fuera.append(texto[i:fin].strip())
        if fin >= len(texto):
            break
        i = max(fin - solape, i + 1)
    return [v for v in fuera if v]


_ETIQUETAS = {"CLAVE": "claves", "DEF": "definiciones", "FORM": "formulas",
              "DEBER": "deberes", "EXAMEN": "examen", "DUDA": "dudas"}


def _parsear(salida: str) -> dict:
    """Las lineas etiquetadas de una respuesta. Se ignora TODO lo demas: el
    modelo local es un razonador y suele escupir su deliberacion antes de la
    respuesta; parsear por etiqueta es lo que sobrevive a eso."""
    fuera = {v: [] for v in _ETIQUETAS.values()}
    for linea in (salida or "").splitlines():
        linea = linea.strip().lstrip("-*# ").strip()
        if ":" not in linea:
            continue
        etiqueta, resto = linea.split(":", 1)
        destino = _ETIQUETAS.get(etiqueta.strip().upper())
        resto = resto.strip()
        if not destino or len(resto) < 3:
            continue
        if destino == "definiciones":
            termino, _, definicion = resto.partition("|")
            if not definicion.strip():
                continue
            fuera[destino].append({"termino": termino.strip()[:80],
                                   "definicion": definicion.strip()[:_MAX_FRASE]})
        else:
            fuera[destino].append(resto[:_MAX_FRASE])
    return fuera


def _fundir(acumulado: dict, nuevo: dict) -> None:
    """Une sin repetir. El solape entre ventanas hace que la misma idea llegue
    dos veces por diseno; deduplicar por texto normalizado es lo que evita
    unos apuntes con todo escrito dos veces."""
    for seccion, items in nuevo.items():
        destino = acumulado.setdefault(seccion, [])
        vistos = {_norm(x["termino"] if isinstance(x, dict) else x) for x in destino}
        for it in items:
            clave = _norm(it["termino"] if isinstance(it, dict) else it)
            if clave and clave not in vistos:
                vistos.add(clave)
                destino.append(it)


# ── API publica ──────────────────────────────────────────────────────────────

def _plantilla() -> dict:
    return {"titulo": "", "resumen": "", "claves": [], "definiciones": [],
            "formulas": [], "deberes": [], "dudas": [], "examen": [],
            "chars_entrada": 0, "chars_salida": 0, "via": VIA_VACIO, "aviso": ""}


def _normalizar(crudo: dict) -> dict:
    """Fuerza el juego de claves EXACTO del contrato. Unos apuntes leidos del
    disco pueden venir de una version anterior del modulo, y la vista HTML
    hace `ap['formulas']` sin defensa: una clave que falta seria un KeyError
    en mitad del cuaderno."""
    ap = _plantilla()
    for k in _CLAVES_DICT:
        if k not in (crudo or {}):
            continue
        v = crudo[k]
        if isinstance(ap[k], list) and isinstance(v, list):
            ap[k] = v
        elif isinstance(ap[k], int) and not isinstance(ap[k], bool):
            try:
                ap[k] = int(v)
            except (TypeError, ValueError):
                _log.warning("apuntes: '%s' no era un entero (%r)", k, v)
        elif isinstance(ap[k], str) and isinstance(v, str):
            ap[k] = v
    return ap


def _chars_salida(ap: dict) -> int:
    total = len(ap["titulo"]) + len(ap["resumen"])
    for k in ("claves", "formulas", "deberes", "dudas", "examen"):
        total += sum(len(x) for x in ap[k])
    for d in ap["definiciones"]:
        total += len(d.get("termino", "")) + len(d.get("definicion", ""))
    return total


def generar(sesion, orch=None, forzar=False) -> dict:
    """Los apuntes de UNA sesion. Ver el encabezado del modulo para las tres
    decisiones que gobiernan el resultado."""
    if not (hasattr(sesion, "texto_dicho") and hasattr(sesion, "del_usuario")):
        _log.warning("apuntes: %s no es una Sesion del cuaderno", type(sesion).__name__)
        ap = _plantilla()
        ap["aviso"] = "el objeto recibido no es una Sesion del cuaderno"
        return ap

    usuario = list(sesion.del_usuario() or [])
    previos = getattr(sesion, "apuntes", None) or {}
    if previos and not forzar:
        # Regenerar cuesta minutos de modelo por sesion; lo ya escrito se
        # devuelve tal cual, pero la garantia de lo importante se re-aplica.
        return _asegurar_importantes(_normalizar(previos), usuario)

    texto = (sesion.texto_dicho() or "").strip()
    ap = _plantilla()
    ap["chars_entrada"] = len(texto)
    avisos = []

    if not texto and not usuario:
        ap["aviso"] = "la sesion no tiene transcripcion ni notas del usuario"
        return ap

    del_usuario_claves, del_usuario_examen, del_usuario_dudas = _repartir_usuario(usuario)

    if not texto:
        # Hay notas del duenio pero no se transcribio nada (micro mudo, o una
        # clase apuntada a mano). Se entrega lo suyo, literal: es todo lo que
        # existe de esa hora.
        ap["via"] = VIA_EXTRACTIVO
        ap["claves"] = del_usuario_claves
        ap["examen"] = del_usuario_examen
        ap["dudas"] = del_usuario_dudas
        ap["titulo"] = _titulo_extractivo(sesion, " ".join(del_usuario_claves))
        ap["resumen"] = compactar(" ".join(del_usuario_claves), 400)
        ap["aviso"] = "sin transcripcion: solo lo que aniadio el usuario"
        ap = _asegurar_importantes(ap, usuario)
        ap["chars_salida"] = _chars_salida(ap)
        return ap

    # ── extractivo: se calcula SIEMPRE, es la red de seguridad del modelo ──
    ext_deberes = _por_lexico(texto, _LEX_DEBERES)
    ext_examen = _por_lexico(texto, _LEX_EXAMEN)
    ext_dudas = _por_lexico(texto, _LEX_DUDA)
    ext_definiciones = _definiciones_de(texto)
    ext_formulas = _formulas_de(texto)
    # El resumen se calcula ANTES que las claves para poder excluir sus frases:
    # medido el 2026-08-31, con las dos secciones sacadas del mismo ranking los
    # apuntes salian MAS LARGOS que la transcripcion (2662 chars de salida para
    # 1932 de entrada) porque claves y resumen eran las mismas frases.
    ext_resumen = compactar(texto, _presupuesto_resumen(texto))
    ext_claves = _claves_extractivas(
        texto, ext_deberes + ext_examen + ext_dudas + _frases_de(ext_resumen))

    del_modelo = {}
    if orch is not None:
        base = texto
        if len(texto) > _MAX_VENTANAS * _VENTANA_CHARS:
            base = compactar(texto, _MAX_VENTANAS * _VENTANA_CHARS)
            avisos.append("clase muy larga: pre-compactada a %d chars antes de trocear"
                          % len(base))
        ventanas = _ventanas(base, _VENTANA_CHARS, _SOLAPE_CHARS)
        mudas = 0
        for v in ventanas:
            trozo = _parsear(_infer(orch, _PROMPT_VENTANA % v, _TOK_VENTANA))
            if not any(trozo.values()):
                mudas += 1
                continue
            _fundir(del_modelo, trozo)
        if mudas:
            avisos.append("%d de %d ventanas volvieron vacias del modelo: "
                          "esa parte va extractiva" % (mudas, len(ventanas)))

    if any(del_modelo.get(k) for k in _ETIQUETAS.values()):
        ap["via"] = VIA_MODELO
        ap["claves"] = list(del_modelo.get("claves") or [])[:_MAX_CLAVES]
        ap["definiciones"] = list(del_modelo.get("definiciones") or [])[:_MAX_DEFINICIONES]
        ap["formulas"] = list(del_modelo.get("formulas") or [])[:_MAX_FORMULAS]
        ap["deberes"] = list(del_modelo.get("deberes") or [])[:_MAX_LISTA]
        ap["dudas"] = list(del_modelo.get("dudas") or [])[:_MAX_LISTA]
        ap["examen"] = list(del_modelo.get("examen") or [])[:_MAX_LISTA]
        # Lo lexico no se descarta aunque haya modelo: "para manana el 4 y el
        # 5" es literal del profesor y perderlo es perder el deber.
        for seccion, extra in (("deberes", ext_deberes), ("examen", ext_examen)):
            for x in extra:
                if _norm(x) not in {_norm(y) for y in ap[seccion]}:
                    ap[seccion].append(x)
        resumen = _infer(orch, "Resume en espanol, en 3 frases cortas, estos "
                               "apuntes de %s. Responde solo el resumen.\n%s"
                         % (getattr(sesion, "materia", "clase"),
                            "\n".join(ap["claves"])[:1500]), _TOK_RESUMEN)
        ap["resumen"] = resumen[:_cap_resumen()] if resumen else ext_resumen
        titulo = _infer(orch, "Titulo en espanol de maximo 8 palabras para unos "
                              "apuntes de %s sobre esto. Responde solo el titulo.\n%s"
                        % (getattr(sesion, "materia", "clase"),
                           "\n".join(ap["claves"][:4])[:600]), _TOK_TITULO)
        ap["titulo"] = titulo.splitlines()[0][:100] if titulo else _titulo_extractivo(sesion, texto)
    else:
        ap["via"] = VIA_EXTRACTIVO
        ap["claves"] = ext_claves
        ap["definiciones"] = ext_definiciones
        ap["formulas"] = ext_formulas
        ap["deberes"] = ext_deberes
        ap["dudas"] = ext_dudas
        ap["examen"] = ext_examen
        ap["resumen"] = ext_resumen
        ap["titulo"] = _titulo_extractivo(sesion, texto)
        if orch is not None:
            avisos.append("el modelo no devolvio contenido util: apuntes extractivos")
        else:
            avisos.append("sin modelo: apuntes extractivos")

    # Rellenos: si el camino elegido dejo una seccion corta y el otro tenia
    # algo, se completa. Un apartado vacio no es una opinion del modelo, es una
    # omision -- y medido el 2026-08-31, el modelo local devolvio UNA sola
    # CLAVE para una clase entera mientras el extractivo sacaba ocho.
    for seccion, extra, minimo in (("definiciones", ext_definiciones, 1),
                                   ("formulas", ext_formulas, 1),
                                   ("dudas", ext_dudas, 1),
                                   ("claves", ext_claves, 3)):
        if len(ap[seccion]) >= minimo or not extra:
            continue
        ya = {_norm(x["termino"] if isinstance(x, dict) else x) for x in ap[seccion]}
        for x in extra:
            clave = _norm(x["termino"] if isinstance(x, dict) else x)
            if clave not in ya:
                ya.add(clave)
                ap[seccion].append(x)

    # Lo del duenio va DELANTE de lo generado, literal y sin deduplicar contra
    # el texto del modelo: aunque diga lo mismo, la suya es la version que el
    # escribio. Y lo suyo NO consume el cupo -- el cupo lo paga lo generado,
    # que es lo prescindible.
    ap["claves"] = _delante(del_usuario_claves, ap["claves"], _MAX_CLAVES)
    ap["examen"] = _delante(del_usuario_examen, ap["examen"], _MAX_LISTA)
    ap["dudas"] = _delante(del_usuario_dudas, ap["dudas"], _MAX_LISTA)
    ap = _asegurar_importantes(ap, usuario)
    ap["aviso"] = "; ".join(avisos)
    ap["chars_salida"] = _chars_salida(ap)
    return ap


def _cap_resumen() -> int:
    """Presupuesto del resumen. Se lee del knob que ya existe
    (COGNIA_COMPACT_CAP via harness.compactacion) para no inventar un segundo
    mando del mismo tamanio, acotado a lo que cabe en una hoja de cuaderno."""
    try:
        from cognia.harness import compactacion as compact
        return max(300, min(int(compact.cap_chars()), 900))
    except Exception as exc:              # pragma: no cover - depende del entorno
        _log.warning("apuntes: sin cap_chars del harness (%s); se usa 700", exc)
        return 700


def generar_jornada(nombre: str, orch=None, progreso=None) -> dict:
    """Apuntes de TODAS las sesiones de una jornada, guardados en apuntes.json.

    Se guarda DESPUES DE CADA SESION, no al final. Una jornada son 5-7 horas y
    con modelo son minutos por sesion: si el portatil se suspende en la cuarta,
    guardar al final tiraria las tres primeras -- que es exactamente el modo de
    fallo por el que `almacen` es incremental.

    Las claves son str(indice), las MISMAS que relee `cuaderno.sesiones_de`;
    devolverlas como int haria que el llamador que compara con el disco no
    encontrara nada.
    """
    sesiones = cua.sesiones_de(nombre)
    ruta = alm.dir_jornada(nombre) / alm.APUNTES
    mapa = alm.leer_json(ruta, {}) or {}
    fuera: dict = {}
    for i, s in enumerate(sesiones):
        ap = generar(s, orch=orch)
        fuera[str(i)] = ap
        mapa[str(i)] = ap
        alm.guardar_json(ruta, mapa)
        if callable(progreso):
            try:
                progreso(i + 1, len(sesiones), s.materia)
            except Exception as exc:
                # El callback es de la interfaz: que se caiga la barra de
                # progreso no puede costar la jornada entera de apuntes.
                _log.warning("apuntes: el callback de progreso fallo (%s: %s)",
                             type(exc).__name__, exc)
    return fuera
