# -*- coding: utf-8 -*-
"""Miniagente que REFORMULA el pedido crudo del usuario antes de enviarlo.

El usuario teclea "arregla el login" y el cerebro recibe "arregla el login".
Este modulo mete un paso barato en medio: el modelo local reescribe esa linea
como una instruccion mas precisa y accionable, PRESERVANDO la intencion.

Reglas de diseno (por que este modulo es asi):
- PURO: no importa cognia.cli, no lee la config y no imprime nada. Quien lo
  cablea decide si pregunta, si avisa y si guarda estado. Asi es testeable sin
  REPL y sin backend.
- Degradacion SILENCIOSA hacia el original: si algo falla (no hay backend,
  timeout, salida rara) se devuelve el texto TAL CUAL con ok=False y un motivo
  legible. Reformular es una mejora opcional; jamas puede tragarse ni deformar
  el mensaje del usuario.
- La falla mas grave posible aqui NO es "no mejoro": es INVENTAR requisitos que
  el usuario no dijo. Por eso el system prompt lo prohibe explicitamente y por
  eso `sanear_salida` rechaza las salidas que crecen o encogen demasiado.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

# Estados del interruptor de la funcionalidad (los interpreta quien cablea).
ESTADOS = ("off", "preguntar", "auto")

# Presupuesto de generacion. Corto y frio a proposito: reformular no es crear.
# Con temperatura alta el modelo "mejora" inventando; con 0.2 se limita a
# reordenar y a explicitar lo que ya estaba en el texto.
TEMPERATURA = 0.2
N_PREDICT = 600
TIMEOUT_DEFECTO = 25.0

# Tope duro del texto de entrada: por encima de esto ya no es una linea de chat
# sino un documento pegado, y reformularlo cuesta mas de lo que aporta.
MAX_CHARS = 4000

# Tope ADAPTATIVO del largo de la salida (defensa anti-invencion). Antes era un
# ratio fijo de 8x, que castigaba justo el caso principal: el dueno teclea
# pedidos CORTOS y vagos ("arregla el bug del login", 24 chars) y 8x los dejaba
# en 192 chars, menos de la mitad de lo que ocupa un prompt bien formado. Con
# ese tope el modulo no podia mejorar sus entradas tipicas: medido sobre 5
# tareas cotidianas, 0 invenciones (bien) y 0 mejoras (el producto no sirve).
#
# El piso sale de una cuenta MEDIDA, no de un gusto. Un prompt bien formado de
# una tarea cotidiana tiene tres partes; los largos son de las salidas reales
# del reformulador v2 contra el modelo local:
#   objetivo + resultado esperado ....... ~110 chars
#     "Arregla el bug del login."  /  "Redacta un correo formal para
#      solicitar un aumento salarial."
#   preguntas por los datos que FALTAN .. ~190 chars
#     "Antes de tocar el codigo, preguntame que sistema operativo y navegador
#      usa el usuario, que mensaje de error exacto ve y en que momento ocurre."
#   formato + criterio de exito ......... ~120 chars
#     "Devuelve un plan paso a paso e indica como verificar que el login
#      funciona de nuevo."
# Suma ~420.
#
# CALIBRACION (recalibrada 2026-08-19 tras la revision adversarial de la ronda
# 2). El piso valia 600 y salia de n=5 muestras del diagnostico de la ronda 1
# (355, 357, 360, 375, 423 chars): "el techo medido mas ~40%". La corrida A/B de
# la misma ronda lo desmintio con n=24 (las 24 salidas de v2 en
# scratchpad/ab_mejorador/crudo.json, las 24 en el regimen del piso porque las
# entradas son cortas):
#     n=24  min=291  p50=382  p95=458  max=541  ("organizame el escritorio", r2)
# O sea el margen REAL contra el techo observado era del 10,9%, no del 40%: una
# cuarta pregunta (los ejemplos del propio system tienen cuatro) cruzaba los 600
# y el usuario perdia una reformulacion legitima. 800 = 541 (max de n=24) mas
# ~48% de margen, y sigue siendo ~120 palabras: no cabe un documento.
#
# Honestidad sobre lo que este numero SI defiende: para un pedido de 24 chars
# ningun tope por largo distingue "expansion legitima" de "invencion", porque
# las dos ocupan lo mismo; quien separa esas dos cosas es el system prompt. Por
# eso el rechazo por largo se reporta como lo que ES -- un rechazo por
# PRESUPUESTO, con las cifras -- y no como una acusacion de invencion: el
# usuario y el log tienen que poder distinguir "se paso de lo previsto" de "el
# modelo se invento el pedido". Lo que el tope impide es la fuga: que el modelo
# entregue un documento entero en vez de una linea. Y por encima de 100 chars de
# entrada vuelve a mandar el ratio, asi que el limite superior existe siempre.
RATIO_MAX_SALIDA = 8.0
PISO_MAX_SALIDA = 800
# Encoger mucho = perdio datos del usuario. Es simetrico y no necesita piso:
# ningun pedido corto se "arregla" acortandolo.
RATIO_MIN_SALIDA = 0.6


def tope_salida(base: str) -> int:
    """Largo maximo aceptable de la reformulacion de `base`, en chars."""
    return max(PISO_MAX_SALIDA, int(RATIO_MAX_SALIDA * len(base)))

_URL_DEFECTO = "http://127.0.0.1:8080"

_SYSTEM_V1 = (
    "Eres un reformulador de prompts. Recibes el texto crudo que un usuario "
    "escribio para un asistente y lo reescribes como una instruccion clara, "
    "precisa y accionable.\n"
    "REGLAS OBLIGATORIAS:\n"
    "1. Preserva EXACTAMENTE la intencion, el idioma y todos los datos del "
    "usuario (nombres, rutas, numeros, nombres de fichero, versiones).\n"
    "2. Esta PROHIBIDO inventar requisitos, ficheros, cifras, tecnologias o "
    "restricciones que el usuario no dijo. Es el peor error posible: antes de "
    "anadir algo dudoso, no lo anadas.\n"
    "3. Explicita lo implicito SOLO cuando se deduce del propio texto (el "
    "objeto de un verbo suelto, el formato de salida que el pedido ya supone).\n"
    "4. No respondas al pedido ni resuelvas la tarea: solo la reescribes.\n"
    "5. Si el texto ya es claro y especifico, devuelvelo casi igual. Mejor no "
    "tocar que empeorar.\n"
    "6. Tu salida es SOLO el prompt reformulado: sin preambulo, sin comillas, "
    "sin markdown de envoltorio, sin explicar lo que cambiaste.\n"
    "7. Conserva la intencion y el SUJETO de la accion: si el usuario pide "
    "que el asistente HAGA algo, la version mejorada sigue pidiendo que el "
    "asistente lo haga. Nunca conviertas una orden en preguntas al usuario "
    "ni en un plan para que lo ejecute el usuario.\n"
    "8. Los tokens que empiezan por '@' (por ejemplo @cognia/cli.py) son "
    "MARCADORES de la herramienta, no prosa: copialos LITERALES, con su '@', "
    "sin convertirlos en 'el fichero X'. Si los borras, el usuario pierde el "
    "fichero adjunto."
)

# --- v2 -------------------------------------------------------------------
# POR QUE existe: v1 ordenaba al modelo "si ya es claro, devuelvelo casi igual",
# y con las entradas del dueno -- cortas y vagas -- eso significaba no hacer
# nada. Medido sobre 5 tareas cotidianas: 0 invenciones (bien) y 0 mejoras (el
# producto no sirve). v2 cambia el objetivo: la reformulacion tiene que ser MAS
# exacta y accionable SIEMPRE, y lo que falta se pide, no se supone.
# Los dos ejemplos van DENTRO del system a proposito: un 9B sigue mucho mejor un
# ejemplo concreto que una regla abstracta, y la frontera legitimo/prohibido es
# justo lo que hay que ensenar. El caso de los ejemplos ('quiero ponerme en
# forma') no es ninguna de las tareas con las que se mide, para no contaminar
# la medicion.
_SYSTEM_V2 = (
    "Eres un reformulador de prompts. Recibes el texto crudo que un usuario "
    "escribio para un asistente y devuelves ESE MISMO pedido reescrito para "
    "que el asistente pueda ejecutarlo bien a la primera. No respondes al "
    "pedido: solo lo reescribes.\n"
    "\n"
    "PROHIBIDO (es el peor fallo posible y anula la mejora):\n"
    "- Afirmar datos que el usuario no dio: fechas, plazos, presupuestos, "
    "cantidades, precios, nombres, lugares, tecnologias, versiones, rutas de "
    "fichero o herramientas. Si no esta en su texto, no existe.\n"
    "- Cambiar la intencion, el idioma, el tono o el sujeto. Lo que el usuario "
    "marca como suyo sigue siendo suyo: 'organizame el escritorio' habla del "
    "escritorio DEL USUARIO, no de un escritorio cualquiera.\n"
    "- Cambiar QUIEN ejecuta la accion. Si el usuario pide que el asistente "
    "HAGA algo ('limpia mis descargas', 'quiero que borres los duplicados'), "
    "la version mejorada sigue pidiendo que el asistente lo HAGA: nunca la "
    "conviertas en un plan 'para que yo lo haga', en instrucciones que el "
    "usuario deba ejecutar ni en una lista de preguntas que reemplace a la "
    "accion.\n"
    "- Hablar del usuario en tercera persona. El prompt lo va a enviar el "
    "propio usuario, asi que se escribe con 'mi', 'me' y 'preguntame'; nunca "
    "'el usuario', 'su escritorio' ni 'preguntale'.\n"
    "- Responder el pedido, resolverlo, opinar o explicar que cambiaste.\n"
    "\n"
    "OBLIGATORIO (esto es la mejora):\n"
    "1. Enuncia el objetivo y el resultado esperado, en imperativo, dirigido "
    "al asistente.\n"
    "2. Nombra el FORMATO de la salida que el pedido ya supone (lista, correo, "
    "plan por pasos, tabla, script), sin fijar cifras que el usuario no dio.\n"
    "3. Los datos que FALTAN se piden: convierte cada hueco en una PREGUNTA "
    "explicita al asistente o en un [placeholder] entre corchetes. Nunca en un "
    "dato supuesto. Si el propio OBJETO del pedido admite dos lecturas, "
    "preguntalo tambien en vez de elegir una por tu cuenta.\n"
    "4. Anade un criterio de exito verificable, construido solo con lo que el "
    "usuario dijo.\n"
    "5. De 2 a 5 frases, texto corrido. Sin titulos, sin markdown, sin listas "
    "de relleno.\n"
    "6. Copia LITERALES los tokens que empiezan por '@' (por ejemplo "
    "@cognia/cli.py): son marcadores de la herramienta, no prosa. Si los "
    "borras, el usuario pierde el fichero adjunto.\n"
    "\n"
    "EJEMPLO 1 - expansion legitima (asi si)\n"
    "Usuario: quiero ponerme en forma\n"
    "Salida: Arma un plan de entrenamiento para que yo me ponga en forma "
    "partiendo de cero. Antes de proponer nada, preguntame cuantos dias por "
    "semana puedo entrenar, de cuanto tiempo dispongo cada dia, que material o "
    "gimnasio tengo a mano y si arrastro alguna lesion. Con esas respuestas "
    "devuelve un plan semana a semana, con que hacer cada dia y una senal "
    "concreta para saber si voy progresando.\n"
    "\n"
    "EJEMPLO 2 - invencion prohibida (asi NO)\n"
    "Usuario: quiero ponerme en forma\n"
    "Salida mala: Arma un plan de 12 semanas para bajar 8 kilos entrenando "
    "45 minutos en el gimnasio los lunes, miercoles y viernes, con una dieta "
    "de 1800 calorias.\n"
    "Por que esta mal: 12 semanas, 8 kilos, 45 minutos, los dias, el gimnasio "
    "y las 1800 calorias son datos que el usuario nunca dijo. Eso no es "
    "reformular, es inventar el pedido de otra persona.\n"
    "\n"
    "Tu salida es SOLO el prompt reformulado: sin preambulo, sin comillas, sin "
    "markdown de envoltorio, sin comentarios."
)

# --- v3 -------------------------------------------------------------------
# POR QUE existe: contado sobre las 24 salidas de v2 del A/B
# (scratchpad/ab_mejorador/crudo.json), v2 no aprendio una REGLA: copio la
# PLANTILLA del EJEMPLO 1. 24/24 contienen "Antes de", 19/24 "Con esas
# respuestas" y 16/24 empiezan literalmente por "Arma " CON las tres conectivas
# del ejemplo. El unico fallo de entregable medido sale de ahi: "organizame el
# escritorio" -- un pedido de ACTUAR sobre algo que ya existe -- salio como
# "Arma una lista de los elementos que deberia tener mi escritorio", porque la
# plantilla solo sabe producir-tras-preguntar.
# v3 = v2 mas dos ejemplos con OTRA forma: actuar sobre algo existente (se
# conserva el verbo del usuario) y pedido ya especifico (se toca poco). Se
# construye por insercion sobre _SYSTEM_V2 para que el brazo medido siga siendo
# byte-identico a si mismo; si el ancla dejara de existir, v3 seria igual a v2 y
# lo caza test_v3_anade_las_dos_formas_que_le_faltaban_a_v2.
#
# v3 NO es el default: el brazo servido tiene que ser el brazo MEDIDO, y v3
# todavia no gano ningun A/B. Se selecciona con COGNIA_MEJORA_PROMPT=v3 o con
# la clave de config 'mejorar_prompt_estilo'.
_ANCLA_CIERRE = "Tu salida es SOLO el prompt reformulado"

_EJEMPLOS_V3 = (
    "EJEMPLO 3 - actuar sobre algo que YA existe (conserva el verbo)\n"
    "Usuario: organizame el escritorio\n"
    "Salida: Organiza mi escritorio. Antes de mover nada, preguntame si hablo "
    "del escritorio fisico o del de la computadora, que hay encima ahora mismo "
    "y con que criterio quiero agruparlo. Con esas respuestas devuelve los "
    "pasos concretos para dejarlo organizado y como sabre que quedo listo.\n"
    "Por que esta bien: el usuario pidio ORGANIZAR algo que ya existe, asi que "
    "el entregable sigue siendo organizarlo. Cambiarlo por 'arma una lista de "
    "lo que deberia tener' seria otro pedido: el objeto ambiguo se PREGUNTA, "
    "no se resuelve eligiendo por el usuario.\n"
    "\n"
    "EJEMPLO 4 - ya es especifico (se toca poco)\n"
    "Usuario: reescribi este parrafo en 3 frases y en tono formal: <parrafo>\n"
    "Salida: Reescribe este parrafo en 3 frases y en tono formal, conservando "
    "su significado: <parrafo>. Devuelve solo el parrafo reescrito.\n"
    "Por que esta bien: el pedido ya trae objetivo, formato y datos. No hay "
    "huecos, asi que no se inventan preguntas de relleno: anadir 'preguntame "
    "el publico y el plazo' aqui cuesta un turno y no aporta nada.\n"
    "\n"
)

_SYSTEM_V3 = _SYSTEM_V2.replace(_ANCLA_CIERRE, _EJEMPLOS_V3 + _ANCLA_CIERRE, 1)

# Punto de extension: la siguiente version se anade aqui y se selecciona por la
# misma env var.
#
# Default v2 (2026-08-19). LO QUE ESTA MEDIDO, corregido tras la revision
# adversarial de la ronda 2 (12 tareas cotidianas x 2 brazos x 2 replicas = 48
# llamadas contra llama-server; artefactos en scratchpad/ab_mejorador/):
#
#   (a) SOPORTADO -- "v2 entrega y v1 no": v1 devolvio el texto del usuario
#       INTACTO en 22 de 24 llamadas (`sanear_salida` las rechaza por "identico
#       al original"); v2 fue aceptado en 24/24. Apareado por tarea sobre la
#       replica 1: 10 discordantes a favor de v2, 0 a favor de v1, test de
#       signos exacto p = 1,95e-3. El default anterior era un passthrough caro.
#       ESTO es lo que justifica el cambio de default.
#   (b) NO SOPORTADO -- "v2 reformula mejor que v1": en 10 de las 12 filas v1
#       no produjo ninguna reescritura, asi que esas filas comparan "reescribir"
#       contra "no hacer nada", no un estilo contra otro. En las 2 unicas filas
#       donde AMBOS brazos escribieron algo (escritorio, viaje) el marcador es
#       1-1 sobre n=2: sin poder. El "+10" que se publico antes NO midio esto.
#       Y esas 2 aceptaciones de v1 son inestables: sus replicas 2 fueron
#       rechazadas las dos.
#   (c) NO ES UNA MEDICION -- "0 invenciones en 24/24": ningun chequeo lo
#       calculo; era un juicio a ojo del mismo agente que escribio v2, y la fila
#       'receta' anade "en la despensa", un lugar que el usuario no dio. La
#       auditoria por salida vive en scratchpad/ab_mejorador/rubrica_invenciones.json.
#
# Modo de fallo conocido de v2 (por eso el interruptor se queda): puede correr
# el ENTREGABLE cuando el objeto del pedido admite dos lecturas -- 'organizame
# el escritorio' -> 'arma una lista de los elementos que deberia tener'. Medido
# 1 de 2 replicas de esa tarea (la otra conserva el entregable), no 1 de 1.
# Coste de la mejora: la mediana sube de 218 ms (v1, n=24) a 1413 ms (v2, n=24).
# La mediana de chars por salida ACEPTADA no es comparable entre brazos (v1
# n=2: 29 chars; v2 n=24: 382), porque v1 casi nunca produjo salida.
# COGNIA_MEJORA_PROMPT=v1 devuelve el comportamiento anterior; =v3 prueba el
# estilo con mas formas de ejemplo (sin medir todavia).
#
# ENMIENDA 2026-08-25 (transcript real del dueno, 11:52): "bueno quiero que
# limpies todas las capturas de pantalla en mi computador porfavor" salio
# reformulado como "Arma un plan de limpieza para que YO elimine... preguntame
# en que directorio..." -- la orden al asistente se convirtio en un plan con
# preguntas PARA EL USUARIO. Los tres system llevan desde entonces la regla
# "conserva quien ejecuta la accion". La clausula NO esta medida en A/B (v2 ya
# no es byte-identico al brazo del 2026-08-19); lo que la respalda no es el
# prompt sino el post-check DETERMINISTA `cambio_de_intencion` (abajo), que
# descarta la salida aunque el modelo ignore la regla.
VERSIONES_SYSTEM = {"v1": _SYSTEM_V1, "v2": _SYSTEM_V2, "v3": _SYSTEM_V3}
VERSION_DEFECTO = "v2"
ENV_VERSION = "COGNIA_MEJORA_PROMPT"


def _resolver_version(version: Optional[str] = None) -> tuple:
    """(nombre_valido, aviso). Un valor desconocido NO se traga en silencio: se
    cae al default y devuelve el aviso para que quien cablea lo grite. Sin esto,
    un 'COGNIA_MEJORA_PROMPT=V2 ' mal escrito daria v1 sin que nadie lo note y
    el A/B mediria dos veces el mismo brazo."""
    pedido = version if version is not None else os.environ.get(ENV_VERSION, "")
    nombre = str(pedido or "").strip().lower()
    if not nombre:
        return VERSION_DEFECTO, ""
    if nombre in VERSIONES_SYSTEM:
        return nombre, ""
    return VERSION_DEFECTO, ("version de system prompt desconocida '{}' "
                             "(hay: {}); se usa {}".format(
                                 nombre, ", ".join(sorted(VERSIONES_SYSTEM)),
                                 VERSION_DEFECTO))


def system_prompt(version: Optional[str] = None) -> str:
    """System prompt del reformulador. `version` gana a la env var
    COGNIA_MEJORA_PROMPT; sin ninguna de las dos manda VERSION_DEFECTO."""
    return VERSIONES_SYSTEM[_resolver_version(version)[0]]


# Tokens '@ruta' del REPL: solo abren mencion al principio o tras un espacio
# (asi 'juan@correo.com' NO cuenta). Mismo criterio que
# cognia/harness/menciones.py, que es quien los expande DESPUES de este modulo.
_RE_ARROBA = re.compile(r"(?:^|(?<=\s))@[^\s]+")
# Puntuacion de cierre que no forma parte del token (igual que menciones.py).
_FIN_TOKEN = ".:!,;)]}\"'"


def _sumar_aviso(registro: dict, mensaje: str) -> None:
    """Acumula avisos en vez de pisarlos. Hay tres fuentes de fallo interno
    (version desconocida, perfil ilegible, audit caido) y una sola ranura: si
    la segunda machaca a la primera, vuelve el vacio silencioso que el campo
    `aviso` vino a impedir."""
    if not mensaje:
        return
    previo = registro.get("aviso") or ""
    registro["aviso"] = (previo + " | " + mensaje) if previo else mensaje


@dataclass
class Mejora:
    """Resultado de una reformulacion. `texto` SIEMPRE es enviable: si ok es
    False vale exactamente lo mismo que `original`."""
    ok: bool
    texto: str
    original: str
    motivo: str
    ms: int
    modelo: str
    # Fallo INTERNO que no impidio reformular (no se pudo registrar la llamada
    # en el audit, no se pudo leer el perfil del modelo). El modulo es puro y
    # no imprime; quien lo cablea lo sube a _aviso_degradado. Sin este campo
    # esos fallos eran un `except: pass` y desaparecian.
    aviso: str = ""


# ---------------------------------------------------------------- utilidades

def _mapa_tildes() -> dict:
    """Mapa 1:1 de letra acentuada -> letra ASCII. Se usa para MATCHEAR sin
    tildes conservando los indices del texto original (NFD no vale aqui:
    cambia el largo y desalinea los cortes de re.match)."""
    mapa = {}
    for cp in range(0x80, 0x250):
        ch = chr(cp)
        base = "".join(c for c in unicodedata.normalize("NFD", ch)
                       if not unicodedata.combining(c))
        if len(base) == 1 and base.isascii() and base != ch:
            mapa[cp] = base
    return mapa


_TILDES = _mapa_tildes()


def _norm(texto: str) -> str:
    """Version en minusculas y sin tildes, del MISMO largo que la entrada."""
    return texto.translate(_TILDES).lower()


def _colapsar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


# Puntuacion que NO aporta contenido a un pedido: cierre de frase, comas y
# comillas/parentesis (rectas y tipograficas, por codepoint para que el fichero
# siga en ASCII). Quedan FUERA a proposito '@' (abre una @-mencion del REPL) y
# el guion (parte palabras compuestas): borrar esos si cambiaria el
# significado de la comparacion.
_PUNTUACION_COSMETICA = (".,;:?!()[]{}" + chr(34) + chr(39) + chr(96)
                         + chr(0x00a1) + chr(0x00bf) + chr(0x00ab)
                         + chr(0x00bb) + chr(0x201c) + chr(0x201d)
                         + chr(0x2018) + chr(0x2019) + chr(0x2026))
_RE_COSMETICO = re.compile("[" + re.escape(_PUNTUACION_COSMETICA) + "]")
# En el PRIMER caracter, '/' y '!' no son puntuacion: marcan la CLASE de la
# linea (el REPL los despacha como comando, no como chat). Ahi se conservan; en
# cualquier otra posicion '!' es cierre de frase y si es cosmetico.
_CLASE_LINEA = "/!"


def _esqueleto(texto: str) -> str:
    """El texto reducido a su CONTENIDO: minusculas, sin tildes, sin puntuacion
    cosmetica y con los espacios colapsados.

    POR QUE existe: el guardia de "identico al original" solo normalizaba
    minusculas y tildes, asi que "arregla el bug del login" ->
    "Arregla el bug del login." pasaba como mejora valida. Ese cambio es CERO
    contenido y sin embargo le cobra al usuario dos selectores (la confirmacion
    y la lectura del diff) por una mayuscula y un punto. Medido en las 5 tareas
    del diagnostico: 3 de 5 "mejoras" eran exactamente esto.
    """
    plano = _norm(texto).strip()
    cabeza = plano[:1] if plano[:1] in _CLASE_LINEA else ""
    return _colapsar(cabeza + _RE_COSMETICO.sub(" ", plano[len(cabeza):]))


# Comillas que el modelo suele poner alrededor de la respuesta (rectas y
# tipograficas; se escriben por codepoint para que el fichero siga en ASCII).
_COMILLAS = (chr(34), chr(39), chr(0x201c), chr(0x201d), chr(0x2018),
             chr(0x2019), chr(0x00ab), chr(0x00bb), chr(96))
# Pares tipograficos: la de apertura solo desenvuelve si cierra su pareja.
_PARES_COMILLAS = {chr(0x201c): chr(0x201d), chr(0x2018): chr(0x2019),
                   chr(0x00ab): chr(0x00bb)}

# Etiquetas que se filtran cuando la plantilla del GGUF no cierra bien.
_ETIQUETAS = re.compile(r"<\|[^|>]*\|>")
_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.S | re.I)
_PENSAMIENTO_ABIERTO = re.compile(r"^\s*<think>.*$", re.S | re.I)
_MARCAS_PROMPT = re.compile(r"</?(?:prompt|output|salida)>", re.I)

# Valla de bloque de codigo que envuelve TODA la respuesta.
_VALLA_ENTERA = re.compile(r"^```[a-z0-9_+-]*[ \t]*\n(.*?)\n?```$", re.S | re.I)
_VALLA_SUELTA = re.compile(r"^\s*```[a-z0-9_+-]*\s*$", re.I)

# Preambulos: cortesia inicial y anuncios del tipo "Prompt mejorado:". Se exige
# que el anuncio termine en ':' y sea corto, para no decapitar un prompt
# legitimo que empiece con una palabra parecida.
_PREAMBULOS = (
    re.compile(r"^(?:claro|por supuesto|desde luego|sure|of course|"
               r"certainly)[,.!:]*[ \t]*", re.I),
    re.compile(r"^(?:aqui (?:tienes|te dejo|va|esta)|here (?:is|you go))"
               r"[^:\n]{0,60}:[ \t]*\n?", re.I),
    re.compile(r"^(?:prompt|version|reformulacion|reformulado|salida|"
               r"resultado|respuesta)[^:\n]{0,40}:[ \t]*\n?", re.I),
)

# Heuristica de "el modelo CONTESTO en vez de reformular". Un prompt es una
# instruccion dirigida al asistente; una respuesta habla en primera persona
# ("voy a", "he creado") o trae ya el resultado hecho (codigo). Cada marca sale
# de fallos reales de razonadores chicos; ninguna aparece de forma natural en
# un pedido reformulado, que se escribe en imperativo hacia el asistente.
_MARCAS_RESPUESTA = (
    re.compile(r"^(?:claro|por supuesto|desde luego|sure|of course)\b"),
    re.compile(r"\bvoy a (?:hacer|crear|escribir|explicar|generar|mostrar)\b"),
    re.compile(r"\bhe (?:creado|escrito|generado|hecho|preparado|anadido)\b"),
    re.compile(r"\bte (?:he |lo )?(?:dejo|explico|muestro|paso|adjunto)\b"),
    re.compile(r"\baqui (?:tienes|esta|te dejo|va)\b"),
    re.compile(r"\bespero que (?:te )?(?:sirva|ayude|funcione)\b"),
    re.compile(r"\bpuedes (?:usar|copiar|pegar) (?:este|el|ese)\b"),
    re.compile(r"\b(?:lo siento|no puedo ayudarte|no puedo hacer eso)\b"),
    re.compile(r"\bcomo (?:modelo|asistente) de (?:lenguaje|ia)\b"),
)

# Codigo al principio de una linea: el modelo entrego la solucion, no el prompt.
_MARCAS_CODIGO = re.compile(
    r"(?m)^[ \t]*(?:def |class |import |from \w+ import |function |"
    r"public |#include|SELECT )")


def _parece_respuesta(texto: str) -> bool:
    """True si el texto parece la RESPUESTA a la peticion en vez de la
    peticion reformulada."""
    plano = _norm(texto)
    if any(marca.search(plano) for marca in _MARCAS_RESPUESTA):
        return True
    return bool(_MARCAS_CODIGO.search(texto))


# ------------------------------------------------- ordenes de accion (2026-08-25)
# POR QUE existe esta seccion: transcript real del dueno (2026-08-25, 11:52).
# Teclea "bueno quiero que limpies todas las capturas de pantalla en mi
# computador porfavor" con mejorar_prompt=preguntar y la "mejora" se la
# devuelve como "Arma un plan de limpieza para que yo elimine... Antes de
# ejecutar nada, preguntame en que directorio... que formato de respuesta
# prefieres": una ORDEN (que Cognia lo haga) convertida en un plan con
# preguntas para que lo haga el usuario. El dueno la ignoro y la retecleo.
# Dos defensas, en capas:
#   1) es_candidato devuelve False para ordenes cortas de accion: la mejora
#      existe para peticiones AMBIGUAS o largas (/hacer, /crear), no para
#      ordenes que ya dicen que hacer -- reformularlas solo mete un menu entre
#      el dueno y la accion.
#   2) `cambio_de_intencion` (post-check determinista en sanear_salida) tira
#      la salida cuando el original ordenaba al asistente y la mejora le
#      devuelve la accion al usuario -- vale para F3 y '/mejorar <texto>',
#      que aceptan ordenes a proposito.

# Tope de palabras para los MARCADORES de orden en es_candidato ("quiero que",
# "puedes", verbo imperativo). Una peticion larga (> 25 palabras) ya trae
# contexto y matices: ahi reformular si puede aportar, y el dueno la revisa en
# el menu. El transcript entero cabe holgado (12 palabras la linea mas larga).
_MAX_PALABRAS_ORDEN = 25

# Muletillas de apertura que no cambian la clase de la linea ("bueno quiero
# que..." es la misma orden que "quiero que..."). intent._PREFIJOS_DESEO no
# pela "bueno", y justo asi empezo la linea del transcript.
_RE_MULETILLAS = re.compile(
    r"^(?:bueno|ok|okay|vale|dale|che|oye|hey|hola|mira|pues|entonces|"
    r"a ver|por ?favor|porfa|porfavor)[\s,.:;!]+")

# "quiero/necesito que <verbo>": el usuario le esta ORDENANDO al asistente.
# Admite cliticos en medio ("quiero que ME limpies").
_RE_PIDE_QUE = re.compile(
    r"^(?:yo\s+)?(?:quiero|quisiera|necesito|deseo|me gustaria|espero|"
    r"te pido)\s+que\b")
# Cortesia que envuelve una orden ("puedes limpiar...", "podrias borrar...").
_RE_CORTESIA_ORDEN = re.compile(
    r"^(?:puedes|podes|podrias|podria|puede|hazme el favor|haceme el favor)\b")
# "hazlo (tu)": la unidad de accion es el ASISTENTE, dicho con todas las letras.
_RE_HAZLO = re.compile(r"\b(?:hazlo|hacelo|encargate|hazte cargo|ocupate)\b")
# Reclamo por una accion no ejecutada ("no los ejecutaste", "no lo hiciste"):
# es la continuacion de una orden, no una peticion nueva que reformular.
_RE_RECLAMO = re.compile(
    r"^no\s+(?:lo|los|la|las|me|te|nos)\s+\S+"
    r"|^no\s+\S+(?:aste|iste|aron|ieron)\b")
# "que (tu|cognia) lo hagas": orden con el ejecutor nombrado.
_RE_QUE_TU = re.compile(
    r"\bque\s+(?:tu|vos|usted|cognia)\s+(?:lo|la|los|las|me)?\s*\w+")

# Copia LOCAL minima de los imperativos que abren una orden. La lista completa
# vive en cognia.agent.intent (_ACTION_VERBS / _ACTION_VERBS_EXTRA) y se suma
# en runtime; esta copia es el paracaidas para que un intent roto no deje las
# ordenes del transcript pasando otra vez (cubre sus 4 lineas + "borra ...").
_VERBOS_ORDEN_LOCAL = frozenset((
    "haz", "hazme", "hace", "haceme", "crea", "borra", "elimina", "limpia",
    "mueve", "copia", "renombra", "instala", "descarga", "ejecuta", "corre",
    "abre", "cierra", "apaga", "arranca", "captura",
))

_VERBOS_ACCION_CACHE = [None]


def _verbos_accion() -> frozenset:
    """Imperativos/subjuntivos de accion: los de intent + la copia local."""
    if _VERBOS_ACCION_CACHE[0] is None:
        verbos = set(_VERBOS_ORDEN_LOCAL)
        try:
            from cognia.agent import intent as _intent
            verbos |= set(_intent._ACTION_VERBS)
            verbos |= set(_intent._ACTION_VERBS_EXTRA)
        except Exception:
            # Degradacion DOCUMENTADA, no silencio: sin intent queda la copia
            # local de arriba, que cubre los casos del transcript. El fallo de
            # import de intent se grita donde importa (el enrutador del CLI lo
            # importa en su propio camino), no aca.
            pass
        _VERBOS_ACCION_CACHE[0] = frozenset(verbos)
    return _VERBOS_ACCION_CACHE[0]


def orden_al_asistente(texto: str,
                       tope_palabras: Optional[int] = None) -> str:
    """Motivo ('' si no) por el que `texto` es una ORDEN de accion dirigida al
    asistente. Con `tope_palabras`, los MARCADORES ("quiero que", cortesia,
    verbo imperativo) solo cuentan hasta ese largo; la via de intent.detect
    (needs_agent) no tiene tope: si el enrutador la mandaria al agente, la
    linea es una orden mida lo que mida."""
    plano = _colapsar(_norm(texto if isinstance(texto, str) else ""))
    if not plano:
        return ""
    # (a) el clasificador del agente ya la reconoce como accion: es la misma
    # senal que decide needs_agent en el enrutador, sin duplicar sus reglas.
    try:
        from cognia.agent.intent import detect as _detect
        it = _detect(plano)
        if it.needs_agent:
            return "el clasificador del agente la marca accion ({})".format(
                it.reason)
    except Exception:
        # Mismo criterio que _verbos_accion: sin intent siguen los marcadores
        # de abajo, que cazan las 4 lineas del transcript por si solos.
        pass
    if tope_palabras is not None and len(plano.split()) > tope_palabras:
        return ""
    pelado = _RE_MULETILLAS.sub("", plano).strip() or plano
    if _RE_PIDE_QUE.match(pelado):
        return "empieza por 'quiero/necesito que <verbo>'"
    if _RE_CORTESIA_ORDEN.match(pelado):
        return "cortesia que envuelve una orden ('puedes/podrias...')"
    if _RE_HAZLO.search(pelado):
        return "contiene 'hazlo/encargate'"
    if _RE_RECLAMO.match(pelado):
        return "reclama por una accion no ejecutada"
    if _RE_QUE_TU.search(pelado):
        return "nombra al asistente como ejecutor ('que tu/cognia ...')"
    primera = pelado.split()[0] if pelado.split() else ""
    if primera in _verbos_accion():
        return "empieza por el imperativo '{}'".format(primera)
    return ""


# Marcas de que la reformulacion le DEVOLVIO la accion al usuario. Todas
# salieron literales del transcript ("para que yo elimine", "que formato de
# respuesta prefieres", "Antes de ejecutar nada"). Solo se miran cuando el
# ORIGINAL era una orden al asistente: en una peticion ambigua son fraseo
# normal de v2.
_MARCAS_DEVOLUCION = (
    ("para que yo", re.compile(r"\bpara que yo\b")),
    ("que formato prefieres", re.compile(
        r"\bque formato(?:\s+de\s+\w+)?\s+(?:prefieres|preferis|quieres)\b")),
    ("antes de ejecutar/hacer nada", re.compile(
        r"\bantes de (?:ejecutar|hacer) nada\b")),
    ("instrucciones para el usuario", re.compile(
        r"\bpara que (?:el usuario|tu) lo (?:haga|hagas|ejecute|ejecutes)\b")),
)

# 'preguntame' a secas NO delata nada: una reformulacion legitima de una orden
# puede pedir datos y seguir ejecutando el asistente ("Organiza mi escritorio.
# Antes de mover nada, preguntame que hay encima" -- el EJEMPLO 3 de v3, y el
# caso 'organizame' medido del A/B). Lo que delata es la COMBINACION: preguntas
# + el entregable convertido en un PLAN que el original no pidio ("Arma un plan
# de limpieza... preguntame en que directorio", transcript 2026-08-25).
_RE_PREGUNTAME = re.compile(r"\bpreguntame\b")
_RE_PLAN_NUEVO = re.compile(
    r"\b(?:arma|armar|prepara|preparar|redacta|redactar|escribe|escribir"
    r"|elabora|elaborar|disena|disenar|crea|crear)\b[^.]{0,40}\bplan\b")


def cambio_de_intencion(original: str, mejora: str) -> str:
    """Motivo ('' si no) por el que `mejora` cambia la INTENCION de `original`:
    el original le ordenaba una accion al asistente y la mejora se la devuelve
    al usuario (plan "para que yo", preguntas en vez de accion). Determinista a
    proposito: es la red que aguanta aunque el modelo ignore la regla del
    system prompt. Sin tope de palabras: una orden larga devuelta al usuario
    cambia la intencion igual que una corta."""
    motivo_orden = orden_al_asistente(original)
    if not motivo_orden:
        return ""
    plano = _norm(mejora if isinstance(mejora, str) else "")
    for nombre, patron in _MARCAS_DEVOLUCION:
        if patron.search(plano):
            return ("el original ordenaba al asistente ({}) y la mejora se la "
                    "devuelve al usuario ('{}')".format(motivo_orden, nombre))
    if (_RE_PREGUNTAME.search(plano) and _RE_PLAN_NUEVO.search(plano)
            and "plan" not in _norm(original)):
        return ("el original ordenaba al asistente ({}) y la mejora lo "
                "convierte en un plan con preguntas ('arma un plan' + "
                "'preguntame')".format(motivo_orden))
    return ""


# ---------------------------------------------------------------- API publica

def es_candidato(texto: str, *, minimo_chars: int = 12,
                 rechazar_ordenes: bool = True) -> bool:
    """True si vale la pena reformular esta linea.

    Se descartan los casos donde reformular no aporta o rompe algo: comandos
    slash y '!' (los interpreta el CLI, no el modelo), lineas cortisimas (no
    hay nada que precisar), documentos pegados (> MAX_CHARS: caro, y quien
    pega 4000 chars ya escribio su prompt), las lineas de la cola de
    inyeccion del REPL, que llevan un centinela NUL y NO son texto tecleado,
    y -- con `rechazar_ordenes`, el default -- las ORDENES cortas de accion
    (ver orden_al_asistente). `rechazar_ordenes=False` es para los caminos
    donde reformular fue un pedido EXPLICITO del usuario (F3): ahi la orden
    se acepta y quien protege la intencion es el post-check de sanear_salida.
    """
    if not isinstance(texto, str):
        return False
    if "\x00" in texto:
        # Centinela de la cola de inyeccion (p.ej. "\x00@f2@..."): no es una
        # peticion del usuario, es una senal interna del bucle del REPL.
        return False
    limpio = texto.strip()
    if not limpio:
        return False
    if limpio[0] in "/!":
        return False
    if len(limpio) < minimo_chars:
        return False
    if len(limpio) > MAX_CHARS:
        return False
    if rechazar_ordenes and orden_al_asistente(
            limpio, tope_palabras=_MAX_PALABRAS_ORDEN):
        # Una ORDEN corta de accion ("quiero que limpies...", "borra...",
        # "hazlo") no se reformula: ya dice que hacer y quien (el asistente).
        # La mejora es para peticiones ambiguas o largas; meterse aqui solo
        # pone un menu -- o peor, una reescritura que cambia la intencion --
        # entre el dueno y la accion (transcript 2026-08-25).
        return False
    return True


def sanear_salida(bruto: str, original: str) -> tuple:
    """Limpia la salida cruda del modelo y decide si es USABLE.

    Devuelve (texto, motivo). motivo == "ok" significa aceptada; cualquier otro
    valor es un rechazo y el caller debe quedarse con el original.
    """
    if not isinstance(bruto, str):
        return "", "salida no textual"
    texto = bruto

    # 1) Basura de plantilla: razonamiento (cerrado o sin cerrar) y tokens
    #    especiales que se filtran cuando el GGUF se sirve con --jinja.
    texto = _PENSAMIENTO.sub(" ", texto)
    texto = _PENSAMIENTO_ABIERTO.sub("", texto)
    texto = _ETIQUETAS.sub("", texto)
    texto = _MARCAS_PROMPT.sub("", texto)
    texto = texto.strip()

    # 2) Valla de bloque de codigo que envuelve toda la respuesta.
    valla = _VALLA_ENTERA.match(texto)
    if valla:
        texto = valla.group(1).strip()
    else:
        # Vallas sueltas (abre y no cierra, o al reves): se borran las lineas
        # de valla y se conserva el contenido.
        lineas = [l for l in texto.splitlines() if not _VALLA_SUELTA.match(l)]
        texto = "\n".join(lineas).strip()

    # 3) Preambulos. Dos pasadas porque "Claro, aqui tienes el prompt
    #    mejorado:" son dos capas. Nunca se consume el texto entero: si el
    #    patron abarca todo, se deja como esta y lo rechaza el chequeo de
    #    vacio o el de "respondio en vez de reformular".
    for _ in range(2):
        antes = texto
        for patron in _PREAMBULOS:
            m = patron.match(_norm(texto))
            if m and 0 < m.end() < len(texto):
                texto = texto[m.end():].lstrip()
        if texto == antes:
            break

    # 4) Comillas envolventes (a veces anidadas: 'texto' dentro de "texto").
    for _ in range(3):
        if len(texto) < 2:
            break
        ini, fin = texto[0], texto[-1]
        if ini in _COMILLAS and fin == _PARES_COMILLAS.get(ini, ini):
            texto = texto[1:-1].strip()
        else:
            break

    texto = texto.strip()

    # ------------------------------------------------------------- rechazos
    if not texto:
        return "", "salida vacia"

    base = (original or "").strip()
    if _esqueleto(texto) == _esqueleto(base):
        # No es un fallo: el modelo decidio que el texto ya estaba bien. Se
        # rechaza igual para que el caller no muestre un diff vacio ni gaste
        # una confirmacion del usuario en un cambio de cero.
        return texto, "identico al original"

    if _parece_respuesta(texto):
        # Contesto la peticion en lugar de reformularla. Enviar esto haria que
        # el cerebro respondiera a una respuesta: el turno se pierde entero.
        return texto, "el modelo respondio en vez de reformular"

    motivo_intencion = cambio_de_intencion(base, texto)
    if motivo_intencion:
        # La orden al asistente volvio como plan/preguntas PARA EL USUARIO
        # (transcript 2026-08-25). Enviar esto invierte quien ejecuta: el
        # dueno pidio que Cognia lo haga y recibe tarea para el. Se descarta
        # entero; el motivo arranca con "mejora descartada" para que el CLI
        # lo grite via _aviso_degradado.
        return texto, "mejora descartada: cambiaba la intencion ({})".format(
            motivo_intencion)

    if base:
        # Encoger mucho = perdio datos del usuario. Crecer por encima del tope
        # = se salio del presupuesto previsto para una linea de chat (lo que
        # eso indique -- invencion o una frase de mas -- el largo no lo sabe;
        # ver la CALIBRACION de arriba). El tope es ADAPTATIVO (ver
        # tope_salida): ratio para los textos largos, piso absoluto para los
        # cortos, que son el caso principal y los que el ratio ahogaba.
        if len(texto) < RATIO_MIN_SALIDA * len(base):
            return texto, "demasiado corto (perdio contenido)"
        tope = tope_salida(base)
        if len(texto) > tope:
            # Rechazo por PRESUPUESTO, con las cifras: un tope por largo no
            # sabe si el exceso es invencion o una frase de mas, y decirle al
            # usuario "probable invencion" sobre una salida que no invento nada
            # es una acusacion que el chequeo no puede sostener.
            return texto, "mas largo del tope previsto ({} chars > {})".format(
                len(texto), tope)

    # La linea CAMBIO DE CLASE: el original era chat y la reformulacion empieza
    # por '/' o '!', que el REPL despacha como comando. es_candidato rechaza
    # esas lineas a la entrada justamente porque no las lee el modelo; dejarlas
    # entrar por la salida seria peor (con suerte "Comando desconocido", con
    # mala suerte EJECUTAR un comando que el usuario no escribio).
    if texto[:1] in "/!" and base[:1] not in "/!":
        return texto, "cambio la clase de linea (empieza por / o !)"

    # Las @-menciones son un sigilo del REPL que se expande DESPUES de este
    # modulo: si el modelo las convierte en prosa ("el fichero cli.py"), el
    # fichero deja de adjuntarse y el cerebro contesta sobre algo que nunca
    # vio, en silencio. Mejor no mejorar que perder el adjunto.
    for token in _RE_ARROBA.findall(base):
        nucleo = token.rstrip(_FIN_TOKEN)
        if len(nucleo) > 1 and nucleo not in texto:
            return texto, "perdio una @-mencion ({})".format(nucleo)

    return texto, "ok"


def _detectar_url(url: Optional[str] = None) -> Optional[str]:
    """URL base del backend local, o None si no hay ninguno vivo. Aislado en su
    propia funcion para poder simular 'sin backend' en los tests."""
    if url:
        return url.rstrip("/")
    try:
        from cognia.llm_local import detectar_backend
        backend = detectar_backend()
    except Exception:
        return None
    if not backend or backend.get("tipo") != "llama":
        # Solo llama-server: es el unico que acepta chat_template_kwargs, y sin
        # eso el razonador se come el presupuesto pensando y devuelve vacio.
        return None
    return str(backend.get("url") or _URL_DEFECTO).rstrip("/")


def _motivo_backend(url: Optional[str] = None) -> str:
    """POR QUE no hay backend usable, en palabras que distinguen los casos.

    "no lo cablearon" y "se rompio" no pueden verse igual: con Ollama vivo el
    motivo generico ("sin backend local") manda al usuario a levantar un
    llama-server que ya no le hace falta levantar, sino que el mejorador no
    soporta ese backend. Devuelve "" si NO hay nada que explicar."""
    if url:
        return "sin backend local"
    try:
        from cognia.llm_local import detectar_backend
        backend = detectar_backend()
    except Exception as exc:
        # Un ImportError aqui se veia como "sin backend local" con el
        # llama-server vivo en :8080: el diagnostico enteramente al reves.
        return "sin backend local: {}: {}".format(type(exc).__name__, exc)
    if not backend:
        return "sin backend local (no hay ninguno vivo)"
    tipo = str(backend.get("tipo") or "?")
    if tipo != "llama":
        return ("backend '{}' no soportado por el mejorador "
                "(necesita llama-server)".format(tipo))
    return "sin backend local"


def _kwargs_plantilla(registro: Optional[dict] = None) -> dict:
    """chat_template_kwargs para APAGAR el pensamiento. No es cosmetico: con un
    razonador y n_predict corto el CoT se come el presupuesto y `content` vuelve
    VACIO la mayoria de las veces (medido: 3 de 4)."""
    try:
        from cognia.agent.model_profiles import perfil_del_agente
        kw = dict(perfil_del_agente().get("kwargs_plantilla") or {})
    except Exception as exc:
        # Sin el perfil se pierde enable_thinking=False y el razonador devuelve
        # `content` vacio (3 de 4 medido): el sintoma llega como "salida vacia"
        # sin una pista de la causa. Se reporta, no se traga.
        if registro is not None:
            _sumar_aviso(registro, "no se pudo leer el perfil del modelo "
                                   "({}: {})".format(type(exc).__name__, exc))
        return {}
    if "enable_thinking" in kw:
        kw["enable_thinking"] = False
    return kw


def _construir_generar(url: str, timeout_s: float, registro: dict) -> Callable:
    """Devuelve un generar_fn(prompt, system) -> str contra llama-server. El
    nombre del modelo se deja en `registro` porque la firma inyectable no tiene
    donde devolverlo."""

    def _generar(prompt: str, system: str) -> str:
        payload = {
            "model": "local",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "temperature": TEMPERATURA,
            "max_tokens": N_PREDICT,
        }
        kw = _kwargs_plantilla(registro)
        if kw:
            payload["chat_template_kwargs"] = kw
        req = urllib.request.Request(
            url + "/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            # Un POST crudo no deja rastro en el audit del backend; se registra
            # a mano para que un fallo aqui no parezca "nadie lo llamo".
            from cognia import backend_activo
            backend_activo.registrar("harness.mejorar_prompt", url)
        except Exception as exc:
            # No se traga: si el audit no recibe la llamada, este mismo POST
            # vuelve a parecer "nadie lo llamo" -- que es lo que el registro
            # venia a impedir. Sube por `aviso`.
            _sumar_aviso(registro, "no se pudo registrar la llamada en el "
                                   "audit ({}: {})".format(
                                       type(exc).__name__, exc))
        # El timeout es DURO porque esto corre entre el Enter del usuario y el
        # envio real: un backend colgado no puede congelar el turno.
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            datos = json.loads(resp.read().decode("utf-8", errors="replace"))
        # llama-server devuelve la RUTA del gguf; para la UI vale el nombre.
        registro["modelo"] = os.path.basename(str(datos.get("model") or ""))
        eleccion = datos["choices"][0]
        # finish_reason separa "el modelo termino" de "se acabo el presupuesto
        # de tokens". Sin mirarlo, una generacion cortada en el token N_PREDICT
        # cae DENTRO de la banda de largo y `sanear_salida` la acepta: en estado
        # 'auto' ese fragmento a media frase se envia al cerebro sin que nadie
        # lo apruebe. Y cuando el CoT se come el presupuesto (medido: 3 de 4 sin
        # enable_thinking=False) el sintoma llegaba como "salida vacia", que se
        # lee como fallo del backend en vez de falta de tokens.
        registro["finish_reason"] = str(eleccion.get("finish_reason") or "")
        return (eleccion["message"]["content"] or "")

    return _generar


def mejorar(texto: str, *, contexto: str = "", timeout_s: float = TIMEOUT_DEFECTO,
            url: Optional[str] = None, generar_fn=None,
            version: Optional[str] = None) -> Mejora:
    """Reformula `texto` con el modelo local. NUNCA lanza.

    contexto: pistas de la sesion para desambiguar (nunca requisitos nuevos).
    generar_fn: inyectable, firma generar_fn(prompt, system) -> str.
    version: "v1" | "v2"; sin valor manda COGNIA_MEJORA_PROMPT y luego el
    default. Un valor desconocido cae al default y lo dice por `aviso`.
    """
    inicio = time.monotonic()
    original = texto if isinstance(texto, str) else ""
    registro = {"modelo": ""}

    nombre_version, aviso_version = _resolver_version(version)
    _sumar_aviso(registro, aviso_version)

    def _fallo(motivo: str) -> Mejora:
        # Todo camino de fallo sale por aqui: texto == original SIEMPRE.
        ms = int((time.monotonic() - inicio) * 1000)
        return Mejora(ok=False, texto=original, original=original,
                      motivo=motivo, ms=ms, modelo=registro.get("modelo", ""),
                      aviso=registro.get("aviso", ""))

    if not original.strip():
        return _fallo("texto vacio")

    if generar_fn is None:
        destino = _detectar_url(url)
        if not destino:
            # El motivo REAL (no hay ninguno / es un backend no soportado /
            # el detector reviento), no un generico que manda a levantar un
            # servidor que ya esta vivo.
            return _fallo(_motivo_backend(url) or "sin backend local")
        generar_fn = _construir_generar(destino, timeout_s, registro)

    partes = []
    if contexto and contexto.strip():
        # El contexto entra ACOTADO y marcado como no-requisito: si viaja crudo
        # el modelo lo confunde con parte del pedido y lo cuela como condicion,
        # que es exactamente la invencion que este modulo tiene que evitar.
        partes.append(
            "Contexto de la sesion (solo para desambiguar; NO lo conviertas en "
            "requisitos):\n" + contexto.strip()[:1200])
    partes.append("Texto del usuario a reformular:\n<<<\n"
                  + original.strip() + "\n>>>")
    prompt = "\n\n".join(partes)

    try:
        bruto = generar_fn(prompt, VERSIONES_SYSTEM[nombre_version])
    except (TimeoutError, OSError) as exc:
        # socket.timeout ES OSError: es el caso comun del backend saturado y
        # merece un motivo propio, distinto de un bug del cableado.
        return _fallo("timeout o red: {}: {}".format(type(exc).__name__, exc))
    except Exception as exc:
        # Ninguna excepcion escapa: peor que no mejorar es perder el turno.
        return _fallo("error: {}: {}".format(type(exc).__name__, exc))

    if bruto is None:
        return _fallo("el backend no devolvio texto")

    if str(registro.get("finish_reason") or "") == "length":
        # Va ANTES del saneador a proposito: un fragmento truncado puede pasar
        # todos sus guardias (largo dentro de banda, sin marcas de respuesta) y
        # colarse como reformulacion completa. Y si ademas `content` vino vacio,
        # este motivo dice la causa real en vez de "salida vacia".
        return _fallo("cortado por presupuesto de tokens "
                      "(max_tokens={})".format(N_PREDICT))

    limpio, motivo = sanear_salida(bruto, original)
    if motivo != "ok":
        return _fallo(motivo)

    ms = int((time.monotonic() - inicio) * 1000)
    return Mejora(ok=True, texto=limpio, original=original, motivo="ok",
                  ms=ms, modelo=registro.get("modelo", ""),
                  aviso=registro.get("aviso", ""))
