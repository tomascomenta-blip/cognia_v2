"""
cognia/compilador/especificacion.py
==================================
EL PLANO. Convierte lo que el duenio teclea ("hazme una herramienta que me
diga cuanto ocupa cada carpeta del escritorio") en una ESPECIFICACION completa
y comprobable de un comando del CLI.

POR QUE EXISTE. `injertador.py` es el musculo: sabe escribir en los 5 sitios,
pero necesita que alguien le diga QUE escribir (cmd, nombre, descripcion,
cubo, categoria). `receta.py` es la ley: sabe que sitios hay y que categorias
tienen hueco. Entre el deseo en prosa y el injerto falta este paso, y es el
que decide si la herramienta se puede EVALUAR despues: una espec sin
postcondiciones comprobables produce un comando que nadie puede declarar
terminado -- solo "parece que anda". Por eso `criterios` no puede estar vacio
y `validar()` lo rechaza.

LO QUE ESTE MODULO NO HACE. No escribe codigo ni toca ficheros del repo: solo
produce un dato. Todo el riesgo vive en el injertador; aqui, como mucho, sale
una espec mala -- y para eso esta `validar()`, que se corre ANTES de injertar.

EL MODELO LOCAL MUERDE, POR LOS DOS LADOS (medido contra el 27B vivo el
2026-08-31, tabla en MAX_TOKENS_ESPEC). El cerebro es un razonador: con
presupuesto GRANDE se va a razonar y no emite nada (52.535 chars y cero salida
con 20.000 tokens), pero con presupuesto DEMASIADO CORTO pasa exactamente lo
mismo -- con 160 tokens la cadena de pensamiento se los come y la respuesta no
llega, 3 pedidos de 3 vacios. Hay una VENTANA, y esta medida: 384 tokens con
`/no_think`. Por eso al modelo se le pide lo minimo que solo el puede aportar
-- un nombre y una frase, en DOS lineas -- y hay camino deterministico para
todo. Sin `orch`, o con `orch` mudo, sale una espec peor pero REAL, con el
aviso puesto para que nadie confunda "no habia modelo" con "el modelo decidio
esto".

API publica:

    Espec                       dataclass con el contrato entero
    desde_texto(texto, orch)    -> Espec   (orch=None => reglas deterministicas)
    validar(espec)              -> [problemas]   (lista vacia = valida)
    a_dict(espec) / de_dict(d)  serializacion plana (JSON-able)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from functools import lru_cache

from cognia.compilador import receta as rec

log = logging.getLogger(__name__)


# ── Las consultas a la receta, cacheadas por HUELLA del fichero ──────────────
#
# MEDIDO en esta maquina el 2026-08-31, con `time.time()` alrededor de cada
# llamada: `receta.catalogo()` tarda 2,24 s, `validar_nombre()` 2,26 s y
# `categorias_con_hueco()` 2,38 s. No es culpa de la receta: cada una lee
# cli.py (23.000 lineas) y lo pasa por `ast.parse`, y esa es EXACTAMENTE la
# regla con la que examinan los guardianes, o sea que esta bien que lo haga
# asi. Lo que no puede ser es llamarla en bucle: elegir un nombre prueba hasta
# 17 candidatos, o sea 40 s para bautizar un comando.
#
# La cache se invalida por HUELLA (mtime en ns + tamanio) de los ficheros que
# deciden la respuesta. Una cache por tiempo, o sin invalidar, seria un error
# grave aqui: justo despues de un injerto cli.py CAMBIA, y un catalogo rancio
# haria que el compilador propusiera un nombre que se acaba de dar de alta.
def _huella(*relativos):
    """(mtime_ns, tamanio) de cada fichero, o None si alguno no se pudo medir.

    None NO es una clave: es la orden de SALTARSE la cache. La primera version
    marcaba el fichero ilegible con ceros, y eso es peor que no cachear:
    `(0, 0)` es una clave perfectamente ESTABLE, o sea que dos fallos seguidos
    dan la MISMA clave y el segundo se sirve de lo que se guardo en el primero
    -- exactamente el "fingir que nada cambio" que esta cache existe para
    impedir, y encima con el log diciendo "la cache se salta" cuando no se
    saltaba nada.
    """
    marcas = []
    for rel in relativos:
        try:
            st = (rec.RAIZ / rel).stat()
        except OSError as e:
            log.warning("compilador/especificacion: no se pudo medir %s "
                        "(%s: %s); se responde SIN cache", rel,
                        type(e).__name__, e)
            return None
        marcas.append((st.st_mtime_ns, st.st_size))
    return tuple(marcas)


@lru_cache(maxsize=2048)
def _validar_nombre_cacheado(cmd: str, huella: tuple) -> tuple:
    return rec.validar_nombre(cmd)


def validar_nombre_repo(cmd: str) -> tuple:
    """`receta.validar_nombre` con cache por huella de cli.py.

    Es el validador por defecto de `desde_texto`/`validar`. Se expone porque
    quien inyecte el suyo (los tests, o un compilador que ya tenga el catalogo
    en la mano) tiene que poder envolver este y no el crudo.
    """
    huella = _huella(rec.CLI)
    if huella is None:
        return rec.validar_nombre(cmd)          # sin huella no hay cache
    return _validar_nombre_cacheado(cmd, huella)


@lru_cache(maxsize=8)
def _categorias_cacheadas(huella: tuple) -> tuple:
    return tuple(rec.categorias_con_hueco())


def categorias_libres_repo() -> list:
    """`receta.categorias_con_hueco` con cache por huella de cli.py y de
    harness/ayuda.py, que son los dos ficheros que deciden la ocupacion."""
    huella = _huella(rec.CLI, rec.AYUDA)
    if huella is None:
        return list(rec.categorias_con_hueco())  # sin huella no hay cache
    return list(_categorias_cacheadas(huella))


# ── Medidas y topes ──────────────────────────────────────────────────────────

CUBOS_VALIDOS = ("NUCLEO", "AVANZADO", "LABORATORIO")

# PRESUPUESTO MEDIDO contra el Qwen3.8-27B vivo (:8080) el 2026-08-31, con
# este mismo prompt. La primera version puso 160 "por ser corto" y estaba MAL:
#
#   presupuesto   razonamiento   salida        tiempo
#   160           562 chars      VACIA         3,5 s
#   384           971 chars      las 2 lineas  6,2 s
#   768         1.883 chars      las 2 lineas 11,3 s
#   384 + /no_think 634 chars    las 2 lineas  4,3 s
#
# Dos cosas que solo se ven midiendo. (1) Un presupuesto DEMASIADO CORTO falla
# igual que uno demasiado largo: la cadena de pensamiento se come los 160
# tokens y la respuesta no llega nunca -- 3 de 3 pedidos salieron vacios. (2)
# El razonamiento CRECE hasta llenar lo que le des (562 -> 971 -> 1.883), que
# es el mismo mecanismo que con 20.000 tokens da 52.535 chars y cero salida.
# O sea que hay una ventana, y 384 esta dentro con margen.
MAX_TOKENS_ESPEC = 384
TEMP_ESPEC = 0.2

# `/no_think` es la convencion de Qwen3 para saltarse la cadena de
# pensamiento. Medido arriba: al mismo presupuesto baja el razonamiento de 971
# a 634 chars y el tiempo de 6,2 s a 4,3 s, o sea deja mas sitio para la
# respuesta dentro de la misma ventana. Con un modelo que no sea de la familia
# Qwen es texto de mas al final del prompt, inocuo; y si aun asi le molestase,
# el camino de degradacion (salida vacia -> reglas deterministicas) ya esta
# probado y avisa.
SUFIJO_SIN_RAZONAR = " /no_think"

# El texto del duenio se recorta antes de entrar al prompt: un prompt largo
# alarga la cadena de pensamiento del razonador, que es justo el fallo que
# deja la respuesta vacia.
TOPE_TEXTO_PROMPT = 220

TOPE_FRASE = 90            # la cabeza de la descripcion, la que ve /ayuda
TOPE_DESCRIPCION = 170     # frase + " Uso: /cmd [a | b]"
TOPE_NOMBRE = 20           # deja sitio a los sufijos de desambiguacion

# Cubo por defecto. AVANZADO y no NUCLEO: una herramienta recien compilada no
# es de uso diario hasta que el duenio la usa, y NUCLEO es la portada.
CUBO_DEFECTO = "AVANZADO"

# Nombre de ultimo recurso, cuando en el texto no queda ni un sustantivo util
# (pasa con pedidos escritos entero en verbos). Se avisa siempre que sale: un
# comando llamado asi no dice lo que hace, y eso el duenio tiene que saberlo
# ANTES de injertarlo, no despues de buscarlo en /ayuda.
BASE_GENERICA = "utilidad"


# ── La trampa de la descripcion ──────────────────────────────────────────────
#
# receta.TRAMPAS lo dice: harness/ayuda._REGLAS_DESC manda a "Agente y tareas"
# cualquier descripcion que lleve 'tarea', 'agente', 'plan ' o 'paso', y esa
# categoria esta a 25/25. O sea que UNA palabra mal elegida pone roja la suite
# sin tocar nada mas. Se comprueba con las claves REALES del clasificador (no
# con una copia a mano) para que el dia que cambien alli, cambie aqui.
#
# DONDE mira el clasificador: `clasificar()` hace
# `normalizar(descripcion) + " " + nombre` y busca la clave por SUBCADENA en
# todo eso -- la descripcion ENTERA y ademas el NOMBRE del comando, no solo la
# primera frase. Leido en el fuente y comprobado ejecutandolo el 2026-08-31;
# la primera version de este modulo miraba solo la cabeza y por ahi se colaban
# especs que `validar()` daba por perfectas.
def _claves_trampa() -> tuple:
    try:
        from cognia.harness import ayuda as _ay
        for palabras, cat in getattr(_ay, "_REGLAS_DESC", ()):
            if cat == "Agente y tareas":
                return tuple(palabras)
    except Exception as e:                      # noqa: BLE001 - motivo visible
        log.warning("compilador/especificacion: no se pudieron leer las reglas "
                    "de ayuda (%s: %s); se usan las claves cableadas",
                    type(e).__name__, e)
    return ("tarea", "agente", "plan ", "plan.", "paso")


PALABRAS_TRAMPA = _claves_trampa()

# Ademas de las claves literales del clasificador, se vigila la palabra suelta
# ('plan' al final de la frase no lleva espacio detras y el clasificador no la
# veria, pero el duenio pidio que esas cuatro palabras no aparezcan).
_RX_TRAMPA_PALABRA = re.compile(r"\b(tarea|tareas|agente|agentes|plan|planes|"
                                r"paso|pasos)\b")

# Reemplazos con el mismo significado y sin la palabra prohibida. Se aplican
# por palabra entera: sustituir por substring convierte 'traspaso' en
# 'trasetapa', que es peor que el problema.
# El genero importa: 'tarea' -> 'trabajo' deja "la trabajo", que en /ayuda se
# lee como una errata. Cada sinonimo conserva el genero del original
# ('labor' y 'tramo' en vez de 'trabajo' y 'etapa').
_SINONIMOS = {
    "tarea": "labor", "tareas": "labores",
    "agente": "asistente", "agentes": "asistentes",
    "plan": "guion", "planes": "guiones",
    "paso": "tramo", "pasos": "tramos",
}


def _plano(txt) -> str:
    """Minusculas sin acentos ni enies: la forma en la que se comparan las
    palabras en todo el modulo (el duenio escribe con acentos y el catalogo
    del CLI no los lleva)."""
    s = unicodedata.normalize("NFD", str(txt or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


def _sin_escapes(txt) -> str:
    # Docstring CRUDO (r) a proposito: lleva dentro el mismo escape
    # que documenta, y sin la r este fichero tampoco compilaba. El bug
    # es tan real que mordio aqui mismo, al escribir el arreglo.
    r"""Texto que se puede meter DENTRO de un literal de cli.py.

    La comilla doble ya estaba tratada; la BARRA INVERTIDA no, y es igual de
    mortal o mas. El injertador escribe la descripcion tal cual dentro de
    `    "/cmd":  "<descripcion>",` y `que_hace` dentro del docstring del
    handler, o sea que un texto del duenio con una ruta de Windows mete un
    escape de Python donde no lo hay. Medido con `ast.parse` sobre la linea
    que escribe el injertador, con un pedido completamente normal para una
    herramienta de carpetas:

        'hazme algo que mida la carpeta C:\Users\nuevo del escritorio'
        -> "cli.py NO COMPILA: (unicode error) truncated \UXXXXXXXX escape"

    y `validar()` decia que la espec estaba perfecta. Un cli.py que no compila
    no es una herramienta mala: es el REPL entero caido. La barra se cambia
    por '/', que en una ruta sigue leyendose bien.
    """
    return str(txt or "").replace("\\", "/").replace('"', "'")


def _primera_frase(descripcion: str) -> str:
    """La cabeza que mira el clasificador: lo que va antes del primer punto o
    antes del 'Uso:'."""
    d = " ".join(str(descripcion or "").split())
    corte = len(d)
    for marca in (". ", " Uso:", "Uso:"):
        pos = d.find(marca)
        if 0 <= pos < corte:
            corte = pos
    return d[:corte].strip(" .;,")


def cae_en_trampa(descripcion: str, cmd: str = "") -> str:
    """La palabra prohibida que hay en lo que MIRA el clasificador, o "".

    MIRA LA DESCRIPCION ENTERA, Y EL NOMBRE. La primera version solo miraba la
    cabeza ("lo que va detras del 'Uso:' no decide categoria"), y eso es
    FALSO: `ayuda.clasificar` hace `normalizar(descripcion) + " " + nombre` y
    busca la clave por SUBCADENA en todo eso. Comprobado contra el
    clasificador de verdad el 2026-08-31:

        clasificar("/x", "Mide carpetas. Uso: /x [tarea | estado]")
            -> 'Agente y tareas'      (la categoria que esta a 25/25)
        clasificar("/tareas-viejas",  "Revisa lo pendiente. Uso: ...")
            -> 'Agente y tareas'

    O sea que mirando solo la cabeza se colaba una espec que `validar()`
    declaraba perfecta y que ponia roja la suite igual. Reproducido con un
    pedido normal del duenio: "...mida las carpetas del escritorio. y que
    liste la tarea de cada una".

    Es a proposito mas ESTRICTA que el clasificador: este devuelve la primera
    regla que casa, asi que una descripcion con 'memoria' Y 'tarea' cae en
    'Memoria y notas' y se salva de milagro. Depender de ese orden es apostar
    a que nadie reordene `_REGLAS_DESC`; aqui las cuatro palabras no aparecen
    y punto -- que ademas es lo que pidio el duenio.

    Devuelve la palabra y no un bool a proposito: el que llama tiene que poder
    decir en el aviso QUE palabra iba a reventar la suite.
    """
    texto = ("%s %s" % (_plano(descripcion), _plano(cmd))).strip()
    if not texto:
        return ""
    m = _RX_TRAMPA_PALABRA.search(texto)
    if m:
        return m.group(1)
    for clave in PALABRAS_TRAMPA:
        if clave in texto:
            return clave.strip()
    return ""


def nombre_envenenado(cmd: str) -> str:
    """La palabra prohibida que lleva DENTRO el nombre del comando, o "".

    `ayuda.clasificar` concatena el nombre al texto que examina, asi que
    '/tareas-viejas' o '/traspaso' se autoclasifican en la categoria llena
    aunque su descripcion este impecable, y lo hacen hasta que alguien de de
    alta su patron exacto -- o sea justo mientras dura el injerto. La lista de
    palabras enteras no bastaba: 'tareas-viejas' no es 'tareas'.
    """
    return cae_en_trampa("", cmd)


def _desactivar_trampa(frase: str) -> tuple:
    """(frase_limpia, palabra_cambiada|""). Cambia la palabra por su sinonimo.

    Recibe la FRASE, nunca la descripcion ya compuesta: esta lleva dentro
    "Uso: /pasos [ver | estado]" y la sustitucion convertia el nombre del
    comando en /tramos, o sea una plantilla de uso que nombra un comando
    inexistente.

    Si tras el cambio sigue cayendo (p.ej. 'traspaso', donde 'paso' esta
    DENTRO de otra palabra y el clasificador igual lo ve), el que llama tiene
    que reconstruir la frase; aqui se devuelve la palabra que molestaba.
    """
    mala = cae_en_trampa(frase)
    if not mala:
        return frase, ""
    limpia = re.sub(r"\b(%s)\b" % "|".join(_SINONIMOS),
                    lambda m: _SINONIMOS[m.group(1).lower()], frase,
                    flags=re.IGNORECASE)
    return limpia, mala


# ── Vocabulario: lo unico que hace falta para elegir sin modelo ──────────────
#
# Las mismas palabras sirven para DOS cosas: elegir la categoria mas afin de
# entre las que tienen hueco, y reconocer cual de las palabras del texto es un
# sustantivo del dominio (el candidato a nombre del comando). Tener una sola
# tabla evita que las dos decisiones se contradigan.
AFINIDAD = {
    "Codigo y ficheros": (
        "carpeta", "carpetas", "fichero", "ficheros", "archivo", "archivos",
        "directorio", "directorios", "disco", "escritorio", "ruta", "rutas",
        "codigo", "repo", "repositorio", "git", "proyecto", "tamano",
        "tamanos", "ocupa", "ocupan", "peso", "pesan", "linea", "lineas",
        "duplicado", "duplicados", "extension", "descarga", "descargas",
    ),
    "Web e investigacion": (
        "web", "internet", "url", "pagina", "paginas", "navegador", "noticia",
        "noticias", "buscador", "google", "github", "online", "rss",
    ),
    "Memoria y notas": (
        "nota", "notas", "recuerdo", "recuerdos", "apunte", "apuntes",
        "concepto", "conceptos", "olvido", "vocabulario",
    ),
    "Metas y seguimiento": (
        "meta", "metas", "objetivo", "objetivos", "recordatorio",
        "recordatorios", "habito", "habitos", "progreso", "racha", "avance",
    ),
    "Reportes y metricas": (
        "reporte", "reportes", "informe", "informes", "estadistica",
        "estadisticas", "metrica", "metricas", "grafica", "graficas",
        "telemetria", "coste", "costo", "gasto", "consumo", "contador",
    ),
    "Modelos y flota": (
        "modelo", "modelos", "gguf", "backend", "flota", "gpu", "cpu",
        "cuantizacion", "tokens", "inferencia", "velocidad",
    ),
    "Sesion e historial": (
        "sesion", "sesiones", "historial", "conversacion", "conversaciones",
        "chat", "transcripcion", "exportar",
    ),
    "Aprender y repasar": (
        "aprender", "estudiar", "estudio", "repasar", "repaso", "examen",
        "examenes", "tarjeta", "tarjetas", "quiz", "clase", "clases",
        "apuntes", "temario", "leccion",
    ),
    "Pensar y razonar": (
        "razonar", "razonamiento", "hipotesis", "idea", "ideas", "debate",
        "argumento", "analisis", "reflexion", "contradiccion",
    ),
    "Grafo de conocimiento": (
        "grafo", "triple", "triples", "entidad", "entidades", "relacion",
        "relaciones", "hecho", "hechos", "ontologia",
    ),
    "Crear y construir": (
        "crear", "construir", "generar", "imagen", "imagenes", "juego",
        "juegos", "musica", "video", "plantilla", "maqueta", "prototipo",
        "pulir",
    ),
    "Perfil y personalizacion": (
        "perfil", "tema", "color", "colores", "estilo", "preferencia",
        "preferencias", "idioma", "atajo", "atajos", "interfaz",
    ),
    "Capacidades y maquina": (
        "capacidad", "capacidades", "maquina", "hardware", "ram", "vram",
        "memoria ram", "bateria", "temperatura", "cpu carga",
    ),
    "Permisos del agente": (
        "permiso", "permisos", "autorizar", "bloquear", "desbloquear",
        "sandbox", "allowlist",
    ),
    "Horizonte largo (TX)": (
        "horizonte", "bitacora", "provenance", "largo plazo", "libro",
    ),
    "Sistema y diagnostico": (
        "diagnostico", "doctor", "actualizar", "version", "modulo",
        "notificacion", "seguridad",
    ),
    "Agente y tareas": (
        "encargo", "cola", "encolar", "trabajo", "trabajos",
    ),
}

# Palabras que NUNCA pueden ser el nombre del comando: pegamento del idioma y
# el andamiaje con el que el duenio pide las cosas ("hazme una herramienta
# que me diga..."). Sin esta lista, el nombre deterministico sale siempre
# "herramienta".
_PARADA = frozenset("""
hazme haz hazte quiero necesito dame ponme crea crear creame construye
construir hacer hagas herramienta herramientas comando comandos cognia
utilidad funcion script programa
una uno un el la los las lo de del al a en con sin por para que quien como
cuando donde cuanto cuanta cuantos cuantas cual cuales cada todo toda todos
todas mi mis me te se su sus nos les y o u ni es sea son ser esta este esto
estos estas eso ese esa aquel muy mas menos algo alguna alguno cosa cosas
favor porfa please dime diga digas decir dice diciendo muestra mostrar
muestre mostrarme ver veo vea saber sepa sepas conocer mire mirar listar
liste lista listado dar da poder pueda puedas puedo sirva sirve tenga tener
tiene hay habia sobre entre desde hasta cuando luego despues antes tambien
solo solamente siempre nunca ahora hoy ayer anoche manana rapido rapida
bien mejor peor
""".split())


def _tokens(texto: str) -> list:
    """Palabras del texto en forma plana, sin pegamento del idioma."""
    crudo = re.findall(r"[a-z0-9]+", _plano(texto))
    return [t for t in crudo if t not in _PARADA and len(t) >= 3]


# Verbos. Sirven para AFINIDAD (una herramienta que "ocupa" habla de disco)
# pero NUNCA para bautizar: un comando se llama por lo que MIRA, no por como
# se pidio. Sin esta lista salia "/ocupa" en vez de "/carpetas" y
# "/notas-busque" en vez de "/notas-duplicadas" (medido con los ejemplos del
# duenio).
_VERBOS_FUERA = frozenset("""
ocupa ocupan ocupar ocupando pesa pesan pesar mide miden medir mida
busca busque buscar buscando encuentra encuentre encontrar filtra filtre
resume resuma resumir redacta redacte explica explique traduce traduzca
genera genere generar crea cree crear construye construya construir
guarda guarde guardar exporta exporte exportar escribe escriba
borra borre borrar elimina elimine limpia limpie limpiar vacia vacie
analiza analice analizar revisa revise revisar compara compare comparar
calcula calcule calcular ordena ordene ordenar detecta detecte
visita visite visito indica indique avisa avise sugiere sugiera
aprender estudiar repasar razonar pulir autorizar bloquear desbloquear
recorrer escanear interpretar clasificar responder
recuerda recuerde recordar recuerdame avise notifique notifica
numera numere numerar cuenta cuente contar hizo haga hagan
dejo deja deje dejar dejaron pasa pase
""".split())

# Las cuatro palabras que el clasificador de /ayuda usa para mandar un comando
# a "Agente y tareas" (llena) tampoco valen como NOMBRE: `clasificar()` mira
# la descripcion Y el nombre del comando, asi que un '/paso' se autoclasifica
# en la categoria llena mientras nadie le de de alta su patron. Quien decide
# es `nombre_envenenado()`, que es una regla de SUBCADENA y no una lista de
# palabras enteras: la lista dejaba pasar '/tareas-viejas' (nombre propuesto
# por el modelo) y '/traspaso' (sacado del texto del duenio), y los dos se
# autoclasifican en la categoria llena igual que '/paso'.
_PALABRAS_DOMINIO = {p for palabras in AFINIDAD.values() for p in palabras
                     if " " not in p and p not in _VERBOS_FUERA}


def _base_del_nombre(texto: str) -> str:
    """El sustantivo util del que sale el nombre del comando.

    Prioridad: una palabra del vocabulario del dominio (las mismas con las que
    se elige la categoria, o sea que nombre y categoria salen coherentes); si
    no hay ninguna, la primera palabra util de 4+ letras; si tampoco,
    'utilidad'. Es peor que un nombre pensado por el modelo, y por eso el
    camino sin modelo deja aviso.
    """
    toks = [t for t in _tokens(texto)
            if t not in _VERBOS_FUERA and not nombre_envenenado(t)]
    for t in toks:
        if t in _PALABRAS_DOMINIO and not t.isdigit():
            return t
    for t in toks:
        if len(t) >= 4 and not t.isdigit():
            return t
    return toks[0] if toks else BASE_GENERICA


def _sanear_nombre(bruto: str) -> str:
    """Un nombre que `receta.validar_nombre` pueda aceptar por FORMA:
    minusculas, digitos y guiones, empezando por letra."""
    n = re.sub(r"[^a-z0-9-]+", "-", _plano(bruto)).strip("-")
    n = re.sub(r"-{2,}", "-", n)
    n = re.sub(r"^[^a-z]+", "", n)
    return n[:TOPE_NOMBRE].strip("-")


def _plural(nombre: str) -> str:
    """Plural castellano de andar por casa. Existe porque el plural ingenuo
    (nombre + 's') daba '/historials', que no es una palabra: el nombre del
    comando lo va a leer el duenio en /ayuda todos los dias."""
    if not nombre or nombre.endswith("s"):
        return nombre
    if nombre.endswith("z"):
        return nombre[:-1] + "ces"
    return nombre + ("s" if nombre[-1] in "aeiou" else "es")


def _con_sufijo(base: str, sufijo: str) -> str:
    """`base-sufijo` recortando la BASE, nunca el sufijo.

    `_sanear_nombre` corta por la derecha a TOPE_NOMBRE, asi que con una base
    larga el corte se comia el sufijo entero y los 17 candidatos colapsaban en
    UNO. Medido: base 'resumen-de-carpetas' (19 chars, la que sale de un
    nombre propuesto por el modelo) daba `_candidatos` == ['resumen-de-carpetas']
    -- o sea que la desambiguacion desaparecia en silencio justo el dia que
    hace falta, y `elegir_nombre` devolvia "ningun nombre quedo libre" con 17
    nombres libres delante.
    """
    hueco = TOPE_NOMBRE - len(sufijo) - 1
    corto = _sanear_nombre(base[:hueco]) if hueco >= 3 else ""
    return _sanear_nombre("%s-%s" % (corto or base, sufijo))


def _candidatos(base: str, texto: str) -> list:
    """Nombres a probar, en orden, hasta que uno no colisione.

    Los primeros tienen SENTIDO (plural, sustantivo compuesto con la segunda
    palabra del dominio, sufijos que dicen que hace el comando); los ultimos
    son numericos, feos pero validos: mejor un '/carpetas-2' que devolver una
    espec con un nombre ya usado, que es lo unico que la receta prohibe.
    """
    base = _sanear_nombre(base) or BASE_GENERICA
    if nombre_envenenado(base):
        # Un '/traspaso' se autoclasifica en la categoria llena y NINGUN
        # sufijo lo arregla, porque la palabra va dentro de la raiz: no tiene
        # sentido gastar los 17 candidatos en variantes del mismo veneno.
        base = BASE_GENERICA
    fuera = [base, _plural(base)]
    # Compuesto con la siguiente palabra util del texto, EN ORDEN: asi
    # "/notas" ocupado da "/notas-duplicadas" y no "/notas-info", que no dice
    # nada. Los verbos quedan fuera por el mismo motivo que en el nombre base.
    otras = [t for t in _tokens(texto)
             if t not in _VERBOS_FUERA and not nombre_envenenado(t)
             and _sanear_nombre(t) and t != base]
    for t in otras[:2]:
        fuera.append(_con_sufijo(base, _sanear_nombre(t)))
    for sufijo in ("info", "ver", "resumen", "local"):
        fuera.append(_con_sufijo(base, sufijo))
    for i in range(2, 10):
        fuera.append(_con_sufijo(base, str(i)))
    # Sin duplicados, sin envenenados, y respetando el orden de preferencia.
    vistos, limpio = set(), []
    for n in fuera:
        n = _sanear_nombre(n)
        if n and n not in vistos and not nombre_envenenado(n):
            vistos.add(n)
            limpio.append(n)
    return limpio


def elegir_nombre(base: str, texto: str = "", validador=None) -> tuple:
    """(cmd, avisos). Prueba candidatos hasta que `validador` acepte uno.

    `validador` se inyecta por parametro (por defecto `validar_nombre_repo`,
    que es `receta.validar_nombre` cacheado) porque es lo unico que consulta el
    estado REAL del repo: asi el test puede simular una colision sin tener que
    dar de alta un comando de verdad.
    """
    validador = validador or validar_nombre_repo
    avisos, rechazos = [], []
    for nombre in _candidatos(base, texto):
        cmd = "/" + nombre
        try:
            ok, motivo = validador(cmd)
        except Exception as e:                  # noqa: BLE001 - motivo visible
            log.warning("compilador/especificacion: el validador de nombres "
                        "fallo con %r (%s: %s)", cmd, type(e).__name__, e)
            return cmd, ["no se pudo validar el nombre %s (%s)" % (cmd, e)]
        if ok:
            if rechazos:
                avisos.append("nombre desambiguado: %s estaba ocupado, va %s"
                              % (", ".join(rechazos), cmd))
            if motivo:
                # validar_nombre devuelve ok=True con motivo cuando el comando
                # lo captura otro por prefijo: no impide el alta, pero obliga
                # a ordenar la rama del elif, y quien injerte tiene que saberlo.
                avisos.append(motivo)
            return cmd, avisos
        rechazos.append(cmd)
    return "", ["ningun nombre derivado de %r quedo libre" % base]


def _categoria_afin(texto: str, libres) -> tuple:
    """(categoria, aviso). La mas afin SEMANTICAMENTE de las que tienen hueco.

    No vale coger la primera de `categorias_con_hueco()`: esa lista viene
    ordenada por HOLGURA, no por sentido, y meter una herramienta de ficheros
    en 'Permisos del agente' porque tiene 22 huecos es como se acaba con un
    /ayuda que nadie puede leer.
    """
    libres = [c for c in libres if c]
    if not libres:
        return "", "ninguna categoria de /ayuda admite un comando mas"
    plano = " " + " ".join(_tokens(texto)) + " "
    marcador = []
    for i, cat in enumerate(libres):
        puntos = 0
        for palabra in AFINIDAD.get(cat, ()):
            if (" %s " % palabra) in plano:
                puntos += 2 if len(palabra) >= 6 else 1
        # -i: a igualdad de afinidad gana la que tiene MAS hueco, que es como
        # viene ordenada la lista de receta.
        marcador.append((puntos, -i, cat))
    marcador.sort(reverse=True)
    puntos, _, mejor = marcador[0]
    if puntos == 0:
        return mejor, ("categoria elegida por holgura y no por afinidad: el "
                       "texto no toca el vocabulario de ninguna categoria "
                       "con hueco")
    return mejor, ""


# ── Subcomandos, criterios y demas piezas de la espec ────────────────────────

_VERBOS_SUB = (
    (("busca", "buscar", "encuentra", "encontrar", "filtra"), "buscar", "<texto>"),
    (("limpia", "limpiar", "borra", "borrar", "elimina", "vacia"), "limpiar", ""),
    (("exporta", "exportar", "guarda", "guardar", "escribe"), "exportar", "[ruta]"),
    (("compara", "comparar", "diferencia", "diff"), "comparar", "<a> <b>"),
)

# Palabras que delatan que la logica NO cabe en el handler del CLI: recorrer
# el disco, hablar por red o calcular algo. El handler del CLI es una puerta;
# si ademas lleva el algoritmo, cli.py (23.000 lineas) crece sin freno y el
# codigo queda donde no se puede testear solo.
_NECESITA_MODULO = (
    "carpeta", "carpetas", "fichero", "ficheros", "archivo", "archivos",
    "directorio", "disco", "escritorio", "recorrer", "escanear", "analizar",
    "calcular", "medir", "ordenar", "comparar", "web", "url", "internet",
    "api", "descargar", "grafica", "estadistica", "historial", "grafo",
)

# Palabras que piden al MODELO, no a la maquina: redactar, interpretar,
# resumir. Marcan pasa_ai, que es lo que decide si el comando puede correr
# con el modelo apagado.
_NECESITA_MODELO = (
    "resume", "resuma", "resumir", "resumen", "redacta", "redacte",
    "redactar", "escribe", "escriba", "explica", "explique", "explicar",
    "traduce", "traduzca", "traducir", "genera", "genere", "generar",
    "sugiere", "sugiera", "sugerir", "opina", "opine", "interpreta",
    "interprete", "clasifica", "clasifique", "responde", "responda",
)


def _subcomandos(texto: str) -> list:
    """Los subcomandos del comando: el que hace el trabajo y `estado`.

    `estado` es OBLIGATORIO por CLAUDE.md (punto 4 de la regla del CLI): toda
    capacidad necesita una puerta de diagnostico que diga si esta activa, con
    que config y cual fue la ultima degradacion. Sin ella, "no lo cablearon" y
    "se rompio" se ven igual desde fuera.
    """
    plano = " " + " ".join(_tokens(texto)) + " "
    principal, args = "ver", ""
    for palabras, nombre, plantilla in _VERBOS_SUB:
        if any((" %s " % p) in plano for p in palabras):
            principal, args = nombre, plantilla
            break
    if principal == "ver" and any((" %s " % p) in plano
                                  for p in ("carpeta", "carpetas", "ruta",
                                            "directorio", "escritorio")):
        args = "[ruta]"
    return [
        {"nombre": principal, "args": args,
         "que": "hace el trabajo principal del comando y lo imprime"},
        {"nombre": "estado", "args": "",
         "que": "imprime si esta activo, con que config corre y cual fue la "
                "ultima degradacion"},
    ]


def _criterios(cmd: str, subcomandos: list, asunto: str) -> list:
    """Postcondiciones COMPROBABLES: invocacion concreta -> lo que TIENE que salir.

    Son tres y ninguna es decorativa: la del trabajo principal (que el comando
    haga algo), la de `estado` (la puerta de diagnostico) y la del subcomando
    inventado (que el comando no reviente con basura, porque una excepcion en
    un handler del REPL se lleva por delante la consola entera).
    """
    principal = subcomandos[0]["nombre"] if subcomandos else "ver"
    args = subcomandos[0].get("args", "") if subcomandos else ""
    invoc = ("%s %s" % (cmd, principal)).strip()
    if args and not args.startswith("["):
        invoc = "%s %s" % (invoc, args.strip("<>"))
    # `espera` TIENE QUE SER UNA MARCA LITERAL, no una descripcion (2026-08-31,
    # medido en la primera compilacion real). El evaluador teclea la invocacion
    # en el REPL de verdad y busca `espera` COMO SUBCADENA de la salida; con una
    # frase en prosa ("imprime al menos una linea y no lanza excepcion") ningun
    # criterio puede cumplirse jamas, y la primera herramienta salio
    # "0/3 criterios" con el comando funcionando perfectamente. La intencion en
    # prosa se conserva en `que`, que es para leerlo un humano, y lo que se
    # COMPRUEBA es la marca.
    return [
        {"invocacion": invoc,
         "espera": principal,
         "que": "imprime informacion de %s sin lanzar" % asunto},
        {"invocacion": "%s estado" % cmd,
         "espera": "estado",
         "que": "la puerta de diagnostico responde"},
        {"invocacion": "%s zzz-subcomando-inexistente" % cmd,
         "espera": "desconocido",
         "que": ("avisa de subcomando desconocido en vez de reventar: una "
                 "excepcion en un handler se lleva por delante el REPL")},
    ]


def _frase_deterministica(texto: str, asunto: str) -> str:
    """La cabeza de la descripcion cuando no hay modelo: el propio deseo del
    duenio recortado, que es literal y por tanto honesto."""
    limpio = " ".join(str(texto or "").split())
    limpio = re.sub(r"(?i)^\s*(hazme|haz|creame|crea|quiero|necesito|dame)\b"
                    r"[^a-zA-Z0-9]*", "", limpio)
    limpio = re.sub(r"(?i)^\s*(una|un)\s+(herramienta|utilidad|comando|script|"
                    r"funcion)\s+(que\s+(me\s+)?)?", "", limpio)
    # El andamiaje de "decirme": lo que queda detras es el asunto de verdad.
    # Sin esto la descripcion empezaba por "Diga cuanto ocupa...", que en
    # /ayuda se lee como una orden al usuario y no como lo que hace el comando.
    limpio = re.sub(r"(?i)^\s*(que\s+)?(me\s+)?(diga|digas|dime|decirme|"
                    r"muestre|muestra|mostrarme|indique|liste|de)\s+",
                    "", limpio)
    limpio = limpio.strip(" .;,:")
    if len(limpio) > TOPE_FRASE:
        corte = limpio.rfind(" ", 0, TOPE_FRASE)
        limpio = limpio[:corte if corte > 20 else TOPE_FRASE].rstrip(" ,;")
    if not limpio:
        limpio = "informa sobre %s" % asunto
    return limpio[0].upper() + limpio[1:]


def _componer_descripcion(frase: str, cmd: str, subcomandos: list) -> str:
    """La linea de _CMD_DESCRIPTIONS: frase + plantilla de uso, como manda la
    receta. Sin comillas dobles (el injertador las cambiaria por simples) y en
    UNA sola linea (el dict se lee con ast.literal_eval)."""
    frase = _sin_escapes(" ".join(str(frase or "").split()).strip(" .;,"))
    if frase:
        # Mayuscula inicial aqui y no en cada camino: la frase puede venir del
        # modelo (que la escribe en minusculas) o de las reglas, y en /ayuda
        # las descripciones se leen en columna, donde una minuscula suelta
        # canta.
        frase = frase[0].upper() + frase[1:]
    nombres = " | ".join(s["nombre"] for s in subcomandos) or "estado"
    desc = "%s. Uso: %s [%s]" % (frase, cmd, nombres)
    if len(desc) > TOPE_DESCRIPCION:
        sobra = len(desc) - TOPE_DESCRIPCION
        frase = frase[:max(10, len(frase) - sobra)].rstrip(" ,;")
        desc = "%s. Uso: %s [%s]" % (frase, cmd, nombres)
    return desc


# ── El modelo: lo minimo que solo el puede aportar ───────────────────────────

_RX_LINEA = re.compile(r"^\s*(nombre|frase)\s*[:=]\s*(.+?)\s*$",
                       re.IGNORECASE | re.MULTILINE)


def _preguntar_al_modelo(texto: str, orch) -> tuple:
    """(nombre|"", frase|"", aviso|""). DOS lineas, presupuesto corto.

    Se le piden solo dos cosas porque son las dos que un humano hace mejor que
    una regla: bautizar el comando y decir en una frase para que sirve. Todo
    lo demas (categoria, cubo, criterios) sale de medir el repo, y medir no se
    delega en un modelo.
    """
    fragmento = " ".join(str(texto or "").split())[:TOPE_TEXTO_PROMPT]
    prompt = ("Comando de consola pedido asi: \"%s\"\n"
              "Responde EXACTAMENTE dos lineas, sin explicar nada:\n"
              "nombre: <una palabra en minusculas, sin acentos>\n"
              "frase: <para que sirve, menos de 12 palabras>%s"
              % (fragmento, SUFIJO_SIN_RAZONAR))
    try:
        salida = orch.infer(prompt, max_tokens=MAX_TOKENS_ESPEC,
                            temperature=TEMP_ESPEC).text or ""
    except Exception as e:                      # noqa: BLE001 - motivo visible
        log.warning("compilador/especificacion: el modelo no bautizo el "
                    "comando (%s: %s); queda la espec deterministica",
                    type(e).__name__, e)
        return "", "", ("el modelo fallo (%s); nombre y descripcion "
                        "deterministicos" % type(e).__name__)
    if not salida.strip():
        # EL fallo del razonador: se va a razonar y no emite nada. No se
        # reintenta con mas presupuesto -- el razonamiento CRECE hasta llenar
        # lo que le des (562 -> 971 -> 1.883 chars segun se sube; medido), asi
        # que reintentar mas grande es pagar mas por el mismo vacio. Se degrada
        # y se dice.
        return "", "", ("el modelo devolvio vacio (razonador sin salida); "
                        "nombre y descripcion deterministicos")
    campos = {k.lower(): v for k, v in _RX_LINEA.findall(salida)}
    nombre = _sanear_nombre(campos.get("nombre", ""))
    frase = " ".join(campos.get("frase", "").split()).strip(" .;,\"'")
    aviso = ""
    if not nombre and not frase:
        aviso = ("el modelo contesto fuera de formato (%r); nombre y "
                 "descripcion deterministicos" % salida.strip()[:60])
    return nombre, frase[:TOPE_FRASE], aviso


# ── El contrato ──────────────────────────────────────────────────────────────

@dataclass
class Espec:
    """La especificacion completa de un comando del CLI, lista para injertar.

    Cada campo mapea a algo que el injertador o el evaluador necesitan:
    `cmd`/`nombre` a los 3 sitios de cli.py, `descripcion` a la puerta visible,
    `cubo` a cli_visibilidad.py, `categoria` a harness/ayuda.py, y `criterios`
    a lo unico que permite decir si la herramienta quedo bien o solo compila.
    """
    cmd: str = ""
    nombre: str = ""
    descripcion: str = ""
    que_hace: str = ""
    subcomandos: list = field(default_factory=list)
    cubo: str = CUBO_DEFECTO
    categoria: str = ""
    pasa_ai: bool = False
    criterios: list = field(default_factory=list)
    modulo_apoyo: str = ""
    avisos: list = field(default_factory=list)


def desde_texto(texto, orch=None, *, validador_nombre=None,
                categorias_libres=None) -> Espec:
    """Una Espec completa a partir de lo que el duenio teclea.

    `orch` puede ser None (y suele serlo en los tests y con el modelo
    apagado): entonces TODO sale de reglas deterministicas y queda el aviso,
    porque una espec derivada por reglas es peor que una pensada -- pero es
    real, y "no habia modelo" no puede verse igual que "el modelo decidio
    esto".

    `validador_nombre` y `categorias_libres` se inyectan por parametro (por
    defecto, las funciones de `receta` que miden el repo en vivo) para poder
    probar la colision de nombres y la eleccion de categoria sin tocar el CLI.
    """
    texto = str(texto or "").strip()
    if not texto:
        # No se inventa una espec de la nada: sin deseo no hay postcondicion
        # que comprobar, y una herramienta sin criterio no se puede evaluar.
        raise ValueError("no hay texto que especificar")

    avisos = []
    base = _base_del_nombre(texto)
    if base == BASE_GENERICA:
        avisos.append("no hay ningun sustantivo util en el pedido: el nombre "
                      "sale generico y conviene darlo a mano")
    frase = ""

    if orch is None:
        avisos.append("sin modelo: nombre, descripcion y subcomandos salen de "
                      "reglas deterministicas")
    else:
        nombre_llm, frase_llm, aviso = _preguntar_al_modelo(texto, orch)
        if aviso:
            avisos.append(aviso)
        veneno = nombre_envenenado(nombre_llm) if nombre_llm else ""
        if veneno:
            avisos.append("el modelo propuso el nombre %r, que lleva %r y se "
                          "autoclasifica en 'Agente y tareas' (llena): se "
                          "ignora" % (nombre_llm, veneno))
        elif nombre_llm:
            base = nombre_llm
        if frase_llm:
            frase = frase_llm

    cmd, avisos_nombre = elegir_nombre(base, texto, validador_nombre)
    avisos.extend(avisos_nombre)
    if not cmd:
        # Se sigue construyendo la espec igual: validar() la va a rechazar con
        # el motivo delante. Devolver None obligaria a todos los llamadores a
        # distinguir dos formas de fallo para el mismo problema.
        cmd = "/" + (_sanear_nombre(base) or BASE_GENERICA)
    nombre = cmd.lstrip("/").replace("-", "_")

    asunto = base.replace("-", " ")
    if not frase:
        frase = _frase_deterministica(texto, asunto)

    subcomandos = _subcomandos(texto)
    # La trampa se desactiva sobre la FRASE y no sobre la descripcion ya
    # compuesta: la descripcion lleva dentro "Uso: /pasos [...]", y sustituir
    # ahi convertia el comando /pasos en /tramos -- una plantilla de uso que
    # nombra un comando que no existe. Cazado tecleando los ejemplos del
    # duenio, no por la suite.
    frase, mala = _desactivar_trampa(frase)
    descripcion = _componer_descripcion(frase, cmd, subcomandos)
    if mala:
        avisos.append("la descripcion llevaba %r, que manda el comando a "
                      "'Agente y tareas' (25/25): reescrita" % mala)
    # La re-comprobacion va SIEMPRE, no solo cuando hubo sustitucion. Estaba
    # colgada de `if mala` y por ahi se colaban dos casos reales: la palabra
    # prohibida dentro de otra ('traspaso'), y el recorte de
    # `_componer_descripcion`, que corta la frase por el tope y puede dejar un
    # 'plan' donde habia un 'planificar'. Y ademas se mira con `cmd`, que es
    # lo que el clasificador concatena.
    resto = cae_en_trampa(descripcion, cmd)
    if resto:
        # El sinonimo no basto (o la palabra venia por otro lado). Se
        # reconstruye la frase entera desde el asunto: fea pero limpia.
        descripcion = _componer_descripcion(
            "informa sobre %s" % asunto, cmd, subcomandos)
        avisos.append("descripcion reconstruida desde cero: %r seguia dentro "
                      "de lo que lee el clasificador" % resto)
        if cae_en_trampa(descripcion, cmd):
            # Aqui ya no queda nada que reescribir: la palabra esta en el
            # NOMBRE o en el asunto. Se dice, porque validar() va a rechazar
            # la espec y el motivo tiene que estar delante y no deducirse.
            avisos.append("la descripcion sigue cayendo en la trampa por %r: "
                          "hay que darle nombre y descripcion a mano"
                          % cae_en_trampa(descripcion, cmd))

    if categorias_libres is None:
        try:
            libres = categorias_libres_repo()
        except Exception as e:                  # noqa: BLE001 - motivo visible
            log.warning("compilador/especificacion: no se pudo medir la "
                        "ocupacion de /ayuda (%s: %s)", type(e).__name__, e)
            libres, avisos = [], avisos + [
                "no se pudo medir que categorias tienen hueco (%s)"
                % type(e).__name__]
    else:
        libres = list(categorias_libres)
    categoria, aviso_cat = _categoria_afin(texto, libres)
    if aviso_cat:
        avisos.append(aviso_cat)

    plano = " " + " ".join(_tokens(texto)) + " "
    pasa_ai = any((" %s " % p) in plano for p in _NECESITA_MODELO)
    necesita_modulo = any((" %s " % p) in plano for p in _NECESITA_MODULO)
    modulo = ("cognia/herramientas/%s.py" % nombre) if necesita_modulo else ""

    # El pedido va entre comillas SIMPLES, sin dobles y sin barras invertidas:
    # que_hace acaba dentro del docstring de _slash_<nombre>, y tanto un '"'
    # como un '\U' del texto del duenio dejan cli.py sin compilar (el '"'
    # cierra el triple-quote; la barra abre una secuencia de escape).
    pedido = _sin_escapes(" ".join(texto.split())[:200])
    que_hace = (
        "%s. Se pidio asi: '%s'. El comando expone %s; el trabajo de verdad "
        "%s. Punto de extension: una entrada por subcomando en el despacho "
        "interno del handler."
        % (_primera_frase(descripcion),
           pedido,
           " y ".join("'%s'" % s["nombre"] for s in subcomandos),
           ("vive en %s, que se importa de forma perezosa y en try/except"
            % modulo) if modulo else
           "cabe en el propio handler, sin modulo de apoyo")
    )

    return Espec(
        cmd=cmd,
        nombre=nombre,
        descripcion=descripcion,
        que_hace=que_hace,
        subcomandos=subcomandos,
        cubo=CUBO_DEFECTO,
        categoria=categoria,
        pasa_ai=pasa_ai,
        criterios=_criterios(cmd, subcomandos, asunto),
        modulo_apoyo=modulo,
        avisos=avisos,
    )


def validar(espec, *, validador_nombre=None, categorias_libres=None) -> list:
    """Lista de problemas de la espec. Vacia = se puede injertar.

    Se devuelve una LISTA y no un bool porque el compilador tiene que poder
    ensenar TODO lo que falta de una vez: arreglar de uno en uno con el modelo
    en medio cuesta una corrida por problema.
    """
    problemas = []
    if not isinstance(espec, Espec):
        return ["no es una Espec: %r" % type(espec).__name__]

    cmd = (espec.cmd or "").strip()
    if not cmd:
        problemas.append("cmd vacio")
    else:
        validador = validador_nombre or validar_nombre_repo
        try:
            ok, motivo = validador(cmd)
        except Exception as e:                  # noqa: BLE001 - motivo visible
            ok, motivo = False, "el validador de nombres fallo (%s)" % e
        if not ok:
            problemas.append("cmd %s no vale: %s" % (cmd, motivo))

    esperado = cmd.lstrip("/").replace("-", "_")
    if not espec.nombre:
        problemas.append("nombre vacio (es el de _slash_<nombre>)")
    elif espec.nombre != esperado:
        # El despacho y la funcion tienen que casar: '/mapa-codigo' se sirve
        # con _slash_mapa_codigo, y un guion en el nombre no es un
        # identificador de Python valido.
        problemas.append("nombre %r no casa con cmd %s (deberia ser %r)"
                         % (espec.nombre, cmd, esperado))

    desc = " ".join((espec.descripcion or "").split())
    if not desc:
        problemas.append("descripcion vacia: sin ella no hay puerta visible")
    else:
        if len(desc) > TOPE_DESCRIPCION:
            problemas.append("descripcion de %d chars: pasa del tope de %d"
                             % (len(desc), TOPE_DESCRIPCION))
        if '"' in desc:
            problemas.append("la descripcion lleva comillas dobles: rompe el "
                             "literal de _CMD_DESCRIPTIONS")
        if "\\" in desc:
            problemas.append("la descripcion lleva una barra invertida: dentro "
                             "del literal de _CMD_DESCRIPTIONS es una secuencia "
                             "de escape y deja cli.py SIN COMPILAR")
        mala = cae_en_trampa(desc, cmd)
        if mala:
            problemas.append("la primera frase de la descripcion lleva %r: el "
                             "clasificador la manda a 'Agente y tareas', que "
                             "esta llena, y pone roja la suite" % mala)

    que_hace = espec.que_hace or ""
    if not que_hace.strip():
        problemas.append("que_hace vacio: es el docstring del handler")
    else:
        if '"' in que_hace:
            problemas.append("que_hace lleva comillas dobles: cierra el "
                             "triple-quote del docstring del handler")
        if "\\" in que_hace:
            problemas.append("que_hace lleva una barra invertida: en el "
                             "docstring del handler es una secuencia de escape "
                             "y deja cli.py SIN COMPILAR")

    if espec.cubo not in CUBOS_VALIDOS:
        problemas.append("cubo %r invalido: tiene que ser uno de %s"
                         % (espec.cubo, ", ".join(CUBOS_VALIDOS)))

    # `medida` separa "no se pudo medir la ocupacion" de "se midio y no cabe
    # NADA". El `elif libres and ...` de la primera version las confundia, y
    # con la lista vacia el chequeo se apagaba entero: una espec con categoria
    # llena pasaba `validar()` sin un solo problema -- o sea que la fase no
    # ejecutada contaba como aprobada, y justo la fase que existe para que la
    # suite no se ponga roja por desborde de categoria.
    medida = True
    if categorias_libres is None:
        try:
            libres = categorias_libres_repo()
        except Exception as e:                  # noqa: BLE001 - motivo visible
            libres, medida = [], False
            problemas.append("no se pudo medir que categorias tienen hueco "
                             "(%s: %s)" % (type(e).__name__, e))
    else:
        libres = list(categorias_libres)
    if not espec.categoria:
        problemas.append("categoria vacia")
    elif medida and espec.categoria not in libres:
        problemas.append("la categoria %r no tiene hueco (las que si: %s)"
                         % (espec.categoria, ", ".join(libres) or "ninguna"))

    if not isinstance(espec.pasa_ai, bool):
        problemas.append("pasa_ai tiene que ser bool, no %r"
                         % type(espec.pasa_ai).__name__)

    if not espec.subcomandos:
        problemas.append("sin subcomandos: hace falta al menos 'estado', la "
                         "puerta de diagnostico que exige CLAUDE.md")
    else:
        nombres = []
        for i, s in enumerate(espec.subcomandos):
            if not isinstance(s, dict) or not str(s.get("nombre", "")).strip():
                problemas.append("subcomando %d sin nombre: %r" % (i, s))
                continue
            nombres.append(s["nombre"])
        if nombres and "estado" not in nombres:
            problemas.append("falta el subcomando 'estado': sin el, "
                             "'no se cableo' y 'se rompio' se ven igual")
        if len(nombres) != len(set(nombres)):
            problemas.append("subcomandos repetidos: %s" % ", ".join(nombres))

    # El corazon del asunto: sin postcondicion no hay nada que evaluar, asi
    # que una espec sin criterios se rechaza aunque todo lo demas este bien.
    if not espec.criterios:
        problemas.append("sin criterios: una herramienta sin postcondicion "
                         "comprobable no se puede evaluar")
    else:
        for i, c in enumerate(espec.criterios):
            if not isinstance(c, dict):
                problemas.append("criterio %d no es un dict: %r" % (i, c))
                continue
            invoc = str(c.get("invocacion", "")).strip()
            espera = str(c.get("espera", "")).strip()
            if not invoc:
                problemas.append("criterio %d sin invocacion" % i)
            elif cmd and not (invoc == cmd or invoc.startswith(cmd + " ")):
                # `startswith(cmd)` a secas daba por bueno '/carpetas-otro ver'
                # como criterio de '/carpetas': es OTRO comando. En un modulo
                # que existe por la colision de PREFIJOS, comparar por prefijo
                # es el error de siempre.
                problemas.append("criterio %d invoca %r y no el comando %s"
                                 % (i, invoc, cmd))
            if not espera:
                problemas.append("criterio %d sin 'espera': una invocacion sin "
                                 "postcondicion no comprueba nada" % i)

    modulo = (espec.modulo_apoyo or "").strip()
    if modulo:
        esperado_mod = "cognia/herramientas/%s.py" % esperado
        if modulo != esperado_mod:
            problemas.append("modulo_apoyo %r: tiene que ser %r"
                             % (modulo, esperado_mod))

    if not isinstance(espec.avisos, list):
        problemas.append("avisos tiene que ser una lista")

    return problemas


# ── Serializacion ────────────────────────────────────────────────────────────

def a_dict(espec) -> dict:
    """La espec como dict plano, listo para json.dumps o para guardar."""
    if not isinstance(espec, Espec):
        raise TypeError("a_dict espera una Espec, no %r" % type(espec).__name__)
    return asdict(espec)


def de_dict(d) -> Espec:
    """Espec desde un dict. Tolerante con lo que falte y con lo que sobre.

    Tolerante a proposito: la espec viaja por fichero y por prompt, y una
    clave de mas (o de menos) no puede hacer que el compilador explote en la
    carga; lo que este mal lo dice `validar()`, que es quien tiene la lista.
    """
    if not isinstance(d, dict):
        raise TypeError("de_dict espera un dict, no %r" % type(d).__name__)
    def _lista(clave):
        v = d.get(clave) or []
        return list(v) if isinstance(v, (list, tuple)) else []
    return Espec(
        cmd=str(d.get("cmd", "") or ""),
        nombre=str(d.get("nombre", "") or ""),
        descripcion=str(d.get("descripcion", "") or ""),
        que_hace=str(d.get("que_hace", "") or ""),
        subcomandos=_lista("subcomandos"),
        cubo=str(d.get("cubo", CUBO_DEFECTO) or CUBO_DEFECTO),
        categoria=str(d.get("categoria", "") or ""),
        pasa_ai=bool(d.get("pasa_ai", False)),
        criterios=_lista("criterios"),
        modulo_apoyo=str(d.get("modulo_apoyo", "") or ""),
        avisos=_lista("avisos"),
    )
