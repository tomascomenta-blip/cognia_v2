# -*- coding: utf-8 -*-
"""
cognia/clases/refinado.py
=========================
EL REFINADO QUE SE HACE SOLO MIENTRAS LA CLASE PASA.

Lo pidio el duenio asi: "que lo vaya realizando conforme va extendiendo la
conversacion... que no guarde todo el contexto, solo lo que importa para ese
momento". Esto es eso: cada pocos minutos, el hilo vigia de la jornada viva
coge SOLO EL TRAMO NUEVO de transcripcion, se lo pasa al modelo y funde el
resultado con lo que ya hay en apuntes.json. Al cerrar la jornada los apuntes
ya estan hechos.

POR QUE ES BARATO (esta es la decision que sostiene todo lo demas)

  `ap["chars_entrada"]` es una MARCA DE AGUA que `apuntes.py` ya persiste: los
  chars de `texto_dicho()` que entraron en esos apuntes. Cada vuelta se corta
  `texto_dicho()[chars_entrada:]`, se trocea SOLO ese tramo con `_ventanas`,
  se parsea con `_parsear` y se funde con `_fundir` sobre lo que hay en disco
  (que ya deduplica por texto normalizado). Regenerar una sesion entera cuesta
  13 llamadas al modelo (12 ventanas + el resumen, medido en apuntes.py); una
  vuelta de esto cuesta 1 o 2. No se inventa estructura nueva: el prompt, el
  troceo, el parseo y la fusion son los de `apuntes.py`.

  Todo lo que NO necesita modelo (titulo, resumen, la garantia de lo marcado
  importante) se calcula por el camino deterministico de `apuntes.py`, que es
  gratis.

LAS OCHO DECISIONES QUE MANDAN

1. SE HABLA POR `llm_local.generar`, NUNCA POR `orch.infer`. Motivo duro y
   medido: `orch.infer` con el puerto 8080 caido cae en el Popen del
   llama-server y ESPERA HASTA 240 s (llama_backend.py:884-898). Un hilo de
   fondo cada pocos minutos intentaria levantar un modelo de 27B y congelaria
   el widget del duenio. `llm_local.generar` devuelve None en milisegundos.

2. RE-SONDEO CADA _CADA_CUANTAS_VUELTAS_RESONDEO VUELTAS. `llm_local._backend`
   es una cache PEGAJOSA de proceso (llm_local.py:76,124): si el widget
   arranca con la flota apagada, el sondeo cachea {} y no se entera nunca de
   que el duenio la levanto a media manana. Se fuerza
   `detectar_backend(forzar=True)` cada 4 vueltas -- ver la constante para el
   por que del 4.

3. DEGRADACION LIMPIA. Con el modelo caido: no se avanza la marca de agua (o
   sea, no se pierde ni un char), se anota UNA vez y se reintenta mas tarde. Y
   sobre todo el duenio puede ver POR QUE no hay apuntes (`estado()`, y los
   avisos que suben a `JornadaViva.avisos`) en vez de un vacio mudo.
   "Caido" son DOS estados y aqui se distinguen: que no responda nadie (lo
   dice el sondeo, y entonces ni se llama) y que responda /health pero no
   genere -- que es lo que hace HOY el 8080 de esta maquina, medido el
   2026-08-31. El segundo es el caro, y por eso existe TIMEOUT_VENTANA.

4. DISYUNTOR. Tras dos vueltas ESTERILES seguidas con el mismo sintoma, el
   refinado de esa jornada se apaga y lo deja escrito. Reintentar en bucle
   contra un modelo que no responde es exactamente lo que prohibe la regla 11
   de CLAUDE.md; el umbral es el del propio repo
   (`reparacion.HUELLA_REPETIDA_CORTA`), no uno inventado aqui. Se vuelve a
   encender con `encender()`, que es intervencion humana.

5. EL CICLO LEER-FUNDIR-ESCRIBIR VA BAJO DOS LOCKS, Y EL MODELO FUERA DE
   ELLOS. `_LOCK_CICLO` serializa las vueltas entre si; `apuntes._LOCK_MAPA`
   es el que ya protege apuntes.json de los escritores de `apuntes.py` (el
   guardado de `generar_jornada` al cerrar). Sin el segundo, el vigia y el
   hilo principal se pisan el fichero: `guardar_json` es atomico, pero la
   secuencia leer-modificar-escribir no lo es. Se toman SIEMPRE en ese orden
   (nadie mas toma `_LOCK_CICLO`, asi que no hay ciclo de espera). Las
   llamadas al modelo son minutos: se hacen FUERA de los locks y el mapa se
   RELEE despues, igual que hace `apuntes.generar_jornada`.

6. UN AVISO NUNCA CREA UNA ENTRADA EN apuntes.json, Y NUNCA PISA OTRO AVISO.
   `olvido._hay_apuntes` decide si comprimir la transcripcion con
   `any(bool(v) for v in mapa.values())`: una entrada que solo lleve
   {'aviso': 'el modelo no esta arriba'} convertiria un apuntes.json vacio en
   un producto y el olvido comprimiria la FUENTE de una clase que no tiene
   apuntes. Es la misma regla que ya cumple `apuntes._persistir_avisos`. Asi
   que el aviso se escribe en el fichero solo si esa entrada YA tenia
   contenido; si no, vive en `estado()`, en los avisos que se devuelven (y que
   la jornada engancha) y en el log.
   Y se CONCATENA, no se sustituye: el campo 'aviso' de una entrada refinada
   es el unico sitio donde pone cuantos chars quedan por refinar, y machacarlo
   con el de una vuelta esteril (o con el del apagado) dejaba al duenio con la
   mitad de la noticia -- y con la mitad que menos le sirve.

7. AL DOCUMENTO SOLO SE VUELCA LO QUE YA TIENE MATERIA. `documento.desde_
   apuntes` es idempotente por `ref` y respeta lo fijado, pero la carpeta del
   documento la elige la MATERIA: volcar mientras la deteccion todavia dice
   'Sin clasificar' dejaria bloques huerfanos en un documento que nadie va a
   abrir. En cuanto la deteccion pone nombre a la clase, el volcado sube de
   golpe todo lo acumulado (por eso es idempotente).

8. LA CADENA CON `olvido.py`, DECLARADA. Unos apuntes escritos por esta pieza
   pueden cubrir SOLO el principio de la clase, y `olvido._hay_apuntes` solo
   mira si hay algo escrito: sin nada mas, el olvido comprimia -- de forma
   IRREVERSIBLE -- la transcripcion de la que nadie habia resumido el ultimo
   tramo. Por eso esta pieza publica `cobertura(jornada)`, que dice cuanto de
   lo dicho esta DE VERDAD dentro de los apuntes, y `olvido.plan` la consulta
   antes de compactar. El dato que la sostiene es `chars_entrada`, y se eligio
   porque es lo unico que SOBREVIVE a `apuntes._normalizar`: un campo nuevo
   ('completo', 'pendiente'...) lo tiraria el primer `generar_jornada` del
   cierre y la proteccion se evaporaria en silencio justo cuando hace falta.

PUERTA EN EL CLI (lo que exige CLAUDE.md y todavia falta cablear)
    El subcomando que la pieza del CLI tiene que registrar en
    `_CMD_DESCRIPTIONS` es exactamente `SUBCOMANDO_CLI`, o sea:

        /grabar-clase refinado [estado|on|off|ahora]

    'estado' imprime `estado()`, 'on'/'off' escriben la config ('on' pasa por
    `encender`, que es lo unico que deshace un apagado del disyuntor) y
    'ahora' llama a `tick(jornada, forzar=True)`. Hasta que eso exista, la
    unica puerta es esta API y el log.

    'on' NO ES COSMETICO Y ES LO MAS URGENTE DE LA LISTA: cuando el disyuntor
    apaga el refinado de una jornada (dos vueltas esteriles), `encender()` es
    la UNICA forma de reabrirlo -- ni `tick(forzar=True)` ni `cerrar()` lo
    hacen, a proposito (regla 11 de CLAUDE.md). Sin esa linea en el CLI, un
    refinado apagado a las 9:10 sigue apagado el resto del dia y el duenio no
    tiene ninguna tecla que lo devuelva. Las dos lineas son literalmente:

        _jv = jor.viva()                     # jornada.viva() -> JornadaViva|None
        ref.encender(_jv.nombre if _jv else jor.nombre_de_hoy())

API publica:
    tick(jornada, generar=None, ahora=None, forzar=False) -> dict
        una vuelta SI toca por periodo (lo que llama el vigia cada 90 s)
    ciclo(jornada, generar=None) -> dict     una vuelta, toque o no
    cerrar(jornada, generar=None) -> dict    vacia la cola antes del cierre
        (lo llama `JornadaViva.parar()` ANTES de `generar_apuntes()`)
    cobertura(jornada) -> dict               cuanto esta refinado de verdad
        (lo consulta `olvido.plan` antes de comprimir la transcripcion)
    estado(jornada="") -> dict               la puerta de diagnostico
    activo() -> bool / periodo() -> float    la config
    encender(jornada) / apagar(jornada, motivo)
    ultimo_fallo() -> dict
"""

from __future__ import annotations

import logging
import os
import threading
import time

from cognia import llm_local as llm
from cognia.clases import almacen as alm
from cognia.clases import apuntes as ap
from cognia.clases import cuaderno as cua
from cognia.disciplina import reparacion as rep

_log = logging.getLogger(__name__)

# El valor que se escribe en el campo 'via' de los apuntes refinados. No es
# ninguna de las de apuntes.py (modelo/extractivo/vacio) a proposito: unos
# apuntes que se estan haciendo solos MIENTRAS la clase pasa no son lo mismo
# que unos generados de una vez al cerrar, y el duenio tiene que poder
# distinguirlo. La vista no mira este campo, asi que aniadir un valor no rompe
# nada.
VIA_REFINADO = "refinado"

# Con quien se identifica este modulo en la auditoria de backend
# (~/.cognia/backend_audit.jsonl). Sin el, una degradacion del refinado se
# leeria como una del chat.
VIA_LLM = "clases.refinado"

# La puerta que falta en el CLI. Vive aqui para que la pieza que la cablee no
# tenga que inventarse el nombre (ver el encabezado).
SUBCOMANDO_CLI = "/grabar-clase refinado"

# Config. Los nombres de las dos variables de entorno, para poder decirlos en
# los avisos sin repetir literales.
ENV_ACTIVO = "COGNIA_CLASES_REFINADO"
ENV_PERIODO = "COGNIA_CLASES_REFINADO_PERIODO"

# 300 s = 5 minutos. El vigia de la jornada tiene su propio ritmo
# (jornada.PERIODO_DETECCION = 90 s) y este periodo se cuenta ENCIMA de el: el
# refinado corre en la primera vuelta del vigia que caiga pasados los 5
# minutos. Por que 5 y no 90 s: cada vuelta cuesta 1-2 llamadas al modelo de
# ~13 s cada una (medido en apuntes.py con el modelo local del duenio), y en 90
# s de clase entran ~1500 chars, que es media ventana -- pagar una llamada por
# media ventana es tirar la mitad del presupuesto en peaje de razonamiento. En
# 5 minutos entran ~5000 chars, que son las 2 ventanas del lote.
PERIODO_DEFECTO = 300.0
# Suelo del periodo configurable. No es cosmetico: por debajo, dos vueltas se
# solaparian con el propio modelo respondiendo y el segundo lote pediria un
# tramo que el primero ya esta procesando (la marca de agua todavia no avanzo).
PERIODO_MINIMO = 30.0

# Chars nuevos por debajo de los cuales NO se molesta al modelo. 400 chars son
# ~65 palabras, ~30 s de habla: pagar 13 s de razonamiento por una frase y
# media es peor negocio que esperar a la vuelta siguiente, y el tramo no se
# pierde (la marca de agua no avanza).
MIN_TRAMO_CHARS = 400
# Lo mismo, pero AL CERRAR la jornada (`cerrar`): ahi ya no hay vuelta
# siguiente donde procesar el resto, asi que el liston baja a media frase. Por
# debajo de 80 chars no queda una idea entera y la llamada no compra nada.
MIN_TRAMO_CIERRE = 80
# Vueltas como mucho en `cerrar`. SEIS por dos ventanas son 12 llamadas, que
# es EXACTAMENTE el tope de `apuntes._MAX_VENTANAS`: vaciar la cola al cerrar
# nunca puede costar mas que haber generado la sesion de una vez, que es la
# alternativa que esta pieza sustituye.
MAX_VUELTAS_CIERRE = 6

# Llamadas al modelo por vuelta. DOS: es lo que hace que "refinar cada pocos
# minutos" no sea "regenerar la clase cada pocos minutos" (13 llamadas). Dos
# ventanas cubren ~4800 chars, o sea mas de los ~5000 que entran en el periodo
# por defecto; si un dia el duenio alarga el periodo, el sobrante no se pierde:
# se procesa en las vueltas siguientes.
MAX_VENTANAS_VUELTA = 2

# Cada cuantas vueltas se fuerza `detectar_backend(forzar=True)`. CUATRO, y el
# numero sale de las dos cosas que cuesta equivocarse:
#   - Corto de mas: un sondeo fallido cuesta hasta TIMEOUT_SONDEO (2 s) por
#     cada backend candidato (llama y ollama), o sea ~4 s de hilo vigia
#     bloqueado. Cada vuelta seria pagarlo cada 5 minutos.
#   - Largo de mas: es el tiempo que el refinado sigue CIEGO despues de que el
#     duenio levante la flota a mitad de clase.
# Con el periodo por defecto, 4 vueltas son 20 minutos de ceguera maxima (menos
# de media clase) por ~4 s de sondeo, o sea el 0,3% del tiempo del vigia. La
# vuelta 0 tambien sondea (0 % 4 == 0): arrancar con la cache de OTRO
# subsistema, hecha antes de que el duenio abriera el REPL, es justo el caso
# que esto existe para no heredar.
CADA_CUANTAS_VUELTAS_RESONDEO = 4

# Techo de espera por ventana, en segundos. `llm_local.timeout_para(700)` da
# 120 s, que es el tope pensado para una generacion que el duenio esta
# ESPERANDO delante de la pantalla. Aqui no hay nadie esperando y el que
# espera es el hilo vigia, que ademas tiene que volver a detectar materias.
#
# MEDIDO EN ESTA MAQUINA EL 2026-08-31: el puerto 8080 responde /health (o
# sea, `detectar_backend` dice que SI hay backend) pero /v1/chat/completions
# no contesta y la llamada muere en el timeout. Con los 120 s por defecto, una
# vuelta del refinado dejaba el vigia bloqueado 4 minutos (dos ventanas) sin
# detectar materias, y "hay backend" era indistinguible de "hay algo colgado
# en ese puerto". 60 s son 4,6 veces los 13,0 s que mide apuntes.py para una
# ventana de este tamanio con el modelo local del duenio: lo que tarde mas que
# eso no esta en condiciones de atender un trabajo de fondo, y esperarlo solo
# hace danio a lo demas que corre en ese hilo.
TIMEOUT_VENTANA = 60

# Tope de seguridad por seccion en el acumulado. NO es el tope de apuntes.py
# (_MAX_CLAVES = 8 y compania) y no puede serlo: alli el tope acota UNA
# generacion que ve la clase entera, y aqui la lista se va llenando a lo largo
# de la clase -- con 8, los apuntes de una clase de 50 minutos serian los de
# los primeros 15 y el resto se perderia en silencio, que es lo contrario de
# lo que el duenio pidio. 40 lineas por seccion es mas de lo que cabe en una
# hoja de cuaderno y a la vez acota el fichero: existe para que un modelo que
# repita la misma idea con redacciones distintas (el dedup de `_fundir` es por
# texto normalizado) no haga crecer apuntes.json sin fin. Al llegar al tope se
# deja de ANIADIR y se dice; no se borra nada de lo que ya hay.
MAX_ACUMULADO = 40

# Materia que significa "todavia no lo se". Ver la decision 7.
MATERIA_SIN_CLASIFICAR = "Sin clasificar"

# Con que se pegan dos avisos dentro del mismo campo 'aviso' de una entrada.
# En constante porque lo que separa tiene que verse en la hoja del duenio (la
# vista pinta el campo tal cual) y porque `_escribir_aviso` dedupe por
# subcadena contra el texto ya pegado.
SEPARADOR_AVISOS = " | "

# Chars que pueden quedar sin refinar y aun asi contar la jornada como
# COMPLETA (ver `cobertura` y la decision 8). Es MIN_TRAMO_CIERRE y no un
# numero nuevo: por debajo de eso el propio refinado ya decide que no queda
# una idea entera que resumir, asi que exigir cero seria protegerse de un
# tramo que esta pieza nunca va a procesar -- y dejaria la transcripcion de
# todas las clases sin compactar para siempre, que es el fallo contrario.
TOLERANCIA_COBERTURA = MIN_TRAMO_CIERRE


# ── Degradacion visible ──────────────────────────────────────────────────────
# Mismo patron que `clases/documento.py`: un ultimo fallo consultable y un log
# que no se repite. `_aviso_degradado` vive en cli.py y este modulo no puede
# importarlo (seria una dependencia del CLI dentro de una libreria); la puerta
# del CLI lee `ultimo_fallo()` y `estado()`.

_avisos_dados: set = set()
_ultimo_fallo: dict = {}


def ultimo_fallo() -> dict:
    """La ultima degradacion del refinado: {donde, motivo, accion, t}.

    Vacio = no ha degradado en este proceso. Lo lee la puerta del CLI para que
    "no lo cablearon" y "se rompio" no se vean igual desde fuera.
    """
    return dict(_ultimo_fallo)


def _degradar(donde: str, motivo: str, accion: str = "") -> None:
    """Deja constancia de un fallo del subsistema. Nunca `except: pass`."""
    global _ultimo_fallo
    _ultimo_fallo = {"donde": donde, "motivo": motivo, "accion": accion,
                     "t": time.time()}
    clave = "%s|%s" % (donde, motivo)
    if clave not in _avisos_dados:
        _avisos_dados.add(clave)
        _log.warning("refinado: %s: %s%s", donde, motivo,
                     (" -- " + accion) if accion else "")


# ── Config: on/off y periodo ─────────────────────────────────────────────────

_SI = ("1", "si", "sí", "on", "true", "yes", "y")
_NO = ("0", "no", "off", "false", "n")


def activo() -> bool:
    """Si el refinado en caliente esta encendido. Por defecto SI.

    El default es "encendido" y no "apagado" porque el subsistema ya trae su
    propio freno: sin backend, el disyuntor lo apaga solo tras dos vueltas
    esteriles (unos 10 minutos) y no vuelve a molestar. O sea que el coste de
    equivocarse con el default es dos sondeos y un aviso; el coste del default
    contrario es que la capacidad no existe para el duenio hasta que lea la
    documentacion, y "lo que no se puede teclear, para el duenio no existe".
    """
    crudo = os.environ.get(ENV_ACTIVO, "").strip().lower()
    if not crudo:
        return True
    if crudo in _SI:
        return True
    if crudo in _NO:
        return False
    _degradar("clases.refinado.knob",
              "%s=%r no es un si/no: se usa el valor por defecto (encendido)"
              % (ENV_ACTIVO, crudo),
              accion="poner 1/0 (o on/off) o quitar la variable")
    return True


def periodo() -> float:
    """Segundos entre vueltas del refinado. Ver PERIODO_DEFECTO.

    Se acota por abajo a PERIODO_MINIMO: un 0 (o un negativo) significaria
    "en cada vuelta del vigia" y pondria dos lotes del mismo tramo en vuelo a
    la vez, porque la marca de agua no avanza hasta que el modelo contesta.
    """
    crudo = os.environ.get(ENV_PERIODO, "").strip()
    if not crudo:
        return PERIODO_DEFECTO
    try:
        valor = float(crudo)
    except ValueError:
        _degradar("clases.refinado.knob",
                  "%s=%r no es un numero de segundos: se usa el defecto (%.0f)"
                  % (ENV_PERIODO, crudo, PERIODO_DEFECTO),
                  accion="poner los segundos o quitar la variable")
        return PERIODO_DEFECTO
    if valor < PERIODO_MINIMO:
        _degradar("clases.refinado.knob",
                  "%s=%s esta por debajo del minimo (%.0f s): se usa el minimo"
                  % (ENV_PERIODO, crudo, PERIODO_MINIMO),
                  accion="subirlo a %.0f s o mas" % PERIODO_MINIMO)
        return PERIODO_MINIMO
    return valor


# ── Estado por jornada ───────────────────────────────────────────────────────
# Un dict de modulo porque el refinado vive en el hilo vigia de un proceso
# vivo, igual que la jornada. Lo unico que cruza corridas es apuntes.json.

_LOCK_ESTADO = threading.RLock()
# Serializa las vueltas entre si. Ver la decision 5: se toma SIEMPRE antes que
# `apuntes._LOCK_MAPA` y nadie mas lo toma, asi que no puede haber abrazo.
_LOCK_CICLO = threading.RLock()

_ESTADO: dict = {}
# Vueltas contadas para el re-sondeo. Es de PROCESO y no por jornada: lo que
# se sondea es el backend, que es uno solo.
_vueltas_totales = 0


def _clave_jornada(jornada) -> str:
    """El nombre saneado, que es el que nombra la carpeta y las claves de
    apuntes.json. Dos nombres crudos distintos que sanean igual son la MISMA
    jornada en disco: llevarles dos estados separados seria mentir."""
    return ap._nombre_jornada(str(jornada or ""))


def _estado_de(jornada: str) -> dict:
    with _LOCK_ESTADO:
        st = _ESTADO.get(jornada)
        if st is None:
            st = {
                "vueltas": 0, "llamadas": 0, "aniadidos": 0,
                "ultimo": 0.0, "ultimo_ok": 0.0, "apagado": "",
                "avisos": [], "dichos": set(),
                "resumenes": {},   # clave de sesion -> el resumen que escribimos
                "disyuntor": rep.Disyuntor("clases.refinado %s" % jornada),
            }
            _ESTADO[jornada] = st
        return st


def _anotar(st: dict, aviso: str) -> bool:
    """Guarda un aviso y dice si es NUEVO.

    Solo los nuevos suben a `JornadaViva.avisos`: el vigia corre cada 90 s y
    repetir el mismo "el modelo no esta arriba" 200 veces en una manana
    entierra el aviso de al lado. El canal duradero es `estado()`.
    """
    if aviso in st["dichos"]:
        return False
    st["dichos"].add(aviso)
    st["avisos"].append(aviso)
    _log.warning("refinado: %s", aviso)
    return True


def apagar(jornada: str, motivo: str) -> dict:
    """Apaga el refinado de esa jornada (lo hace el disyuntor). No toca la
    config: es una decision de ESTA corrida, no del duenio."""
    j = _clave_jornada(jornada)
    st = _estado_de(j)
    st["apagado"] = motivo
    _anotar(st, motivo)
    return {"jornada": j, "apagado": motivo}


def encender(jornada: str) -> dict:
    """Vuelve a encender el refinado de una jornada apagada por el disyuntor.

    Es INTERVENCION HUMANA (la teclea el duenio en `/grabar-clase refinado
    on`), que es lo unico que puede resetear la ventana del disyuntor segun
    la regla 11 de CLAUDE.md. Por eso no se llama solo desde ningun reintento
    automatico.
    """
    j = _clave_jornada(jornada)
    st = _estado_de(j)
    antes = st["apagado"]
    st["apagado"] = ""
    st["disyuntor"].reset_por_intervencion()
    st["dichos"].clear()
    return {"jornada": j, "encendido": True, "venia_apagado": antes}


def estado(jornada: str = "") -> dict:
    """QUE HAY Y COMO ESTA. La puerta de diagnostico que exige CLAUDE.md para
    una capa sin uso directo: dice si esta activo, con que config, cuantas
    vueltas y llamadas lleva, si el disyuntor lo apago y cual fue la ultima
    degradacion. No genera nada ni toca el disco.
    """
    base = {
        "activo": activo(),
        "periodo": periodo(),
        "subcomando": SUBCOMANDO_CLI,
        "env": {"activo": ENV_ACTIVO, "periodo": ENV_PERIODO},
        "min_tramo_chars": MIN_TRAMO_CHARS,
        "ventanas_por_vuelta": MAX_VENTANAS_VUELTA,
        "backend": llm.describir(),
        "ultimo_fallo": ultimo_fallo(),
        "jornadas": {},
    }
    with _LOCK_ESTADO:
        nombres = [_clave_jornada(jornada)] if jornada else list(_ESTADO)
        for n in nombres:
            st = _ESTADO.get(n)
            if st is None:
                base["jornadas"][n] = {"vueltas": 0, "llamadas": 0,
                                       "aniadidos": 0, "apagado": "",
                                       "avisos": [], "esteriles": 0}
                continue
            base["jornadas"][n] = {
                "vueltas": st["vueltas"], "llamadas": st["llamadas"],
                "aniadidos": st["aniadidos"], "ultimo": st["ultimo"],
                "ultimo_ok": st["ultimo_ok"], "apagado": st["apagado"],
                "avisos": list(st["avisos"])[-5:],
                "esteriles": len(st["disyuntor"]._esteriles()),
            }
    return base


# ── Cuanto esta refinado DE VERDAD (lo que pregunta olvido.py) ───────────────

def _marca_de(entrada: dict, dichos: int) -> int:
    """Los chars de la sesion que esos apuntes declaran haber leido.

    Los tres casos que hay que distinguir, y por que se resuelven asi:
      - la entrada NO existe: nadie resumio nada de esa sesion -> 0.
      - la entrada existe y NO trae `chars_entrada`: son unos apuntes de otra
        version (o escritos a mano) que no dicen hasta donde llegaron. Se
        cuentan como completos: no se les puede acusar de estar a medias sin
        prueba, y suponer lo contrario dejaria sin compactar transcripciones
        que llevan anios con sus apuntes hechos.
      - la marca es corrupta: se cuenta como 0 (proteger), y se DICE.
    """
    if not entrada:
        return 0
    crudo = entrada.get("chars_entrada")
    if crudo is None:
        return dichos
    try:
        return max(0, int(crudo))
    except (TypeError, ValueError):
        _degradar("clases.refinado.cobertura",
                  "chars_entrada=%r no es un entero: esa sesion cuenta como "
                  "SIN refinar" % (crudo,),
                  accion="no se compacta su transcripcion hasta arreglarlo")
        return 0


def cobertura(jornada: str) -> dict:
    """Cuanto de lo que se dijo esta DE VERDAD dentro de los apuntes.

    ES LA CADENA DECLARADA CON `olvido.py` (decision 8 del encabezado). El
    olvido comprime la transcripcion literal -- irreversible -- en cuanto
    `_hay_apuntes` ve algo escrito, y esta pieza escribe apuntes que cubren
    SOLO el principio de la clase: sin esta consulta, la fuente del tramo que
    nadie resumio desaparecia.

    Devuelve {'jornada', 'toco_el_refinado', 'completo', 'chars_dichos',
    'chars_refinados', 'pendiente', 'sesiones': [{clave, dichos, refinados,
    pendiente}]}.

    'toco_el_refinado' se mira por el campo 'via' (que tambien sobrevive a
    `apuntes._normalizar`) y va aparte de 'completo' A PROPOSITO: esta pieza
    solo puede JUZGAR lo que ella misma escribio. Una jornada que el refinado
    nunca toco se comporta exactamente como antes de que este modulo
    existiera, que es lo que hace que anadir la proteccion no pueda romper
    nada de lo que ya funcionaba.

    NO ESCRIBE NI UN BYTE, y cuesta dos decisiones que parecen detalles:
    se lee el fichero CRUDO con `almacen.leer_json` (y no con
    `apuntes.cargar_mapa`) y las sesiones salen de `cuaderno._sesiones_crudas`
    (y no de `sesiones_de`). Las dos rutas normales MIGRAN las claves viejas
    de apuntes.json y reescriben el fichero al leerlo; esto lo llama
    `olvido.plan()`, que promete enseniar el plan sin tocar nada -- y el duenio
    mira ese plan justo antes de dejar borrar 40 GB.
    """
    nombre = _clave_jornada(jornada)
    sesiones = cua._sesiones_crudas(nombre)
    claves = ap.claves_de_jornada(nombre, sesiones)[0]
    crudo = alm.leer_json(alm.dir_jornada(nombre) / alm.APUNTES, {}) or {}
    if not isinstance(crudo, dict):
        _log.warning("refinado: %s no es un objeto JSON (%s): esa jornada "
                     "cuenta como sin refinar", alm.APUNTES, type(crudo).__name__)
        crudo = {}

    detalle, toco = [], False
    for i, s in enumerate(sesiones):
        texto = (s.texto_dicho() or "").strip()
        entrada = crudo.get(claves[i])
        entrada = entrada if isinstance(entrada, dict) else {}
        if str(entrada.get("via") or "") == VIA_REFINADO:
            toco = True
        marca = _marca_de(entrada, len(texto))
        detalle.append({"clave": claves[i], "dichos": len(texto),
                        "refinados": marca,
                        "pendiente": max(0, len(texto) - marca)})
    pendiente = sum(d["pendiente"] for d in detalle)
    return {
        "jornada": nombre,
        "toco_el_refinado": toco,
        "completo": pendiente <= TOLERANCIA_COBERTURA,
        "chars_dichos": sum(d["dichos"] for d in detalle),
        "chars_refinados": sum(min(d["refinados"], d["dichos"])
                               for d in detalle),
        "pendiente": pendiente,
        "sesiones": detalle,
    }


# ── El modelo ────────────────────────────────────────────────────────────────

def _resondear_si_toca() -> bool:
    """Fuerza el re-sondeo del backend cada CADA_CUANTAS_VUELTAS_RESONDEO
    vueltas. Devuelve si sondeo. Ver la decision 2 del encabezado."""
    global _vueltas_totales
    toca = (_vueltas_totales % CADA_CUANTAS_VUELTAS_RESONDEO) == 0
    _vueltas_totales += 1
    if toca:
        llm.detectar_backend(forzar=True)
    return toca


def _generar_por_llm(prompt: str) -> str:
    """Una llamada al modelo local. '' si no hay backend o si no dijo nada.

    NO se llama a `llm.generar` cuando no hay backend, y no es por ahorrar
    milisegundos: `llm_local.generar` sin backend escribe una fila en
    ~/.cognia/backend_audit.jsonl Y grita por stderr en CADA llamada. Con dos
    ventanas por vuelta y una vuelta cada 5 minutos, una manana de clase con
    la flota apagada serian cientos de filas y cientos de gritos por una sola
    noticia. Se sondea antes, se dice UNA vez (por la auditoria, para que la
    degradacion quede donde se miran las degradaciones) y despues se calla.
    """
    if llm.detectar_backend() is None:
        if "sin-backend" not in _avisos_dados:
            _avisos_dados.add("sin-backend")
            try:
                from cognia import backend_activo
                backend_activo.sin_backend(
                    VIA_LLM, "ni llama-server (:8080) ni Ollama (:11434) "
                             "responden: el refinado en caliente espera")
            except Exception as exc:      # la auditoria no puede costar la clase
                _log.warning("refinado: no pude anotar la degradacion en la "
                             "auditoria de backend (%s: %s)",
                             type(exc).__name__, exc)
        return ""
    salida = llm.generar(prompt, temperature=ap._TEMP,
                         max_tokens=ap._TOK_VENTANA, via=VIA_LLM,
                         timeout=TIMEOUT_VENTANA)
    return salida or ""


# ── El tramo nuevo ───────────────────────────────────────────────────────────

def _lote_de_vuelta(tramo: str, ventanas_max: int) -> tuple:
    """(ventanas a pedirle al modelo, chars de `tramo` que quedan procesados).

    Devuelve las dos cosas juntas A PROPOSITO: la marca de agua tiene que
    avanzar EXACTAMENTE sobre lo que se proceso. Si avanzara sobre el tramo
    entero se perderia en silencio lo que no cupo en el lote, y si no avanzara
    nada se reprocesaria (y se volveria a pagar) lo mismo cada vuelta.

    `_ventanas` empieza por `texto.strip()`, asi que el desplazamiento de la
    izquierda se descuenta aparte para que los indices sigan siendo los del
    tramo ORIGINAL.
    """
    limpio = tramo.strip()
    desplaz = len(tramo) - len(tramo.lstrip())
    if not limpio:
        return [], len(tramo)
    # El presupuesto en chars: la primera ventana cuesta _VENTANA_CHARS y cada
    # una de las siguientes solo AVANZA (_VENTANA_CHARS - _SOLAPE_CHARS). Es
    # la misma cuenta de `apuntes._presupuesto_troceo`, con otro tope.
    tope = ventanas_max * (ap._VENTANA_CHARS - ap._SOLAPE_CHARS) + ap._SOLAPE_CHARS
    recorte = limpio if len(limpio) <= tope else ap._cortar(limpio, tope)
    ventanas = ap._ventanas(recorte, ap._VENTANA_CHARS, ap._SOLAPE_CHARS)
    if len(ventanas) <= ventanas_max:
        return ventanas, desplaz + len(recorte)
    # El corte por espacio puede acortar una ventana y colar una de mas (lo
    # midio apuntes.py con una clase de 45 000 chars). Se recorta la lista y
    # la marca avanza solo hasta el final de la ultima ventana pedida.
    ventanas = ventanas[:ventanas_max]
    pos = recorte.find(ventanas[-1])
    if pos < 0:                    # una ventana es un trozo de `recorte`: no puede
        _log.warning("refinado: no encuentro la ventana dentro del tramo; la "
                     "marca avanza sobre el recorte entero (%d chars)",
                     len(recorte))
        return ventanas, desplaz + len(recorte)
    return ventanas, desplaz + pos + len(ventanas[-1])


def _pendiente(sesion, previo: dict) -> tuple:
    """(marca de agua, tramo nuevo) de una sesion. Tramo vacio = nada que
    hacer en esta vuelta."""
    marca = 0
    crudo = previo.get("chars_entrada") if isinstance(previo, dict) else 0
    try:
        marca = max(0, int(crudo or 0))
    except (TypeError, ValueError):
        # Unos apuntes con la marca corrupta se refinarian desde cero, que es
        # caro pero no pierde nada. Se dice, no se calla.
        _degradar("clases.refinado.marca",
                  "chars_entrada=%r no es un entero: ese tramo se reprocesa "
                  "desde el principio" % (crudo,))
    texto = (sesion.texto_dicho() or "")
    if marca >= len(texto):
        return marca, ""
    return marca, texto[marca:]


# ── Fusion sobre lo que ya hay en disco ──────────────────────────────────────

_SECCIONES = tuple(ap._ETIQUETAS.values())


def _secciones_de(previo: dict) -> dict:
    """Las seis listas del contrato, COPIADAS. Una clave que no sea lista
    (unos apuntes de otra version, o algo escrito a mano) no se toca: se
    empieza de vacio para esa seccion y lo que habia se conserva porque la
    entrada se construye con `dict(previo)`."""
    fuera = {}
    for s in _SECCIONES:
        v = previo.get(s)
        fuera[s] = list(v) if isinstance(v, list) else []
    return fuera


def _fundir_con_tope(secciones: dict, nuevo: dict, st: dict, materia: str) -> int:
    """Funde lo del modelo respetando MAX_ACUMULADO. Devuelve cuantos items
    entraron de verdad. Lo que no cabe NO se borra de ningun sitio: es lo que
    el modelo acaba de decir y se queda fuera, con aviso."""
    antes = {s: len(v) for s, v in secciones.items()}
    ap._fundir(secciones, nuevo)
    entraron = 0
    for s, items in secciones.items():
        if len(items) > MAX_ACUMULADO:
            del items[MAX_ACUMULADO:]
            _anotar(st, "la seccion '%s' de %s llego al tope de %d lineas: lo "
                        "nuevo del modelo ya no se aniade ahi (nada se borra)"
                    % (s, materia or "la sesion", MAX_ACUMULADO))
        entraron += max(0, len(items) - antes[s])
    return entraron


def _titulo_y_resumen(entrada: dict, sesion, st: dict, clave: str) -> None:
    """Titulo y resumen SIN modelo. Los dos son deterministicos en
    `apuntes.py` (`_titulo_de_clave`, `_titulo_extractivo`, `compactar`), asi
    que mantenerlos frescos no cuesta ni una llamada.

    EL TITULO SOLO SE PONE SI ESTA VACIO: es lo unico que garantiza que no se
    pisa lo que escribio el duenio (o una generacion anterior).

    EL RESUMEN SI SE REHACE, pero solo si el que hay es EXACTAMENTE el que
    escribimos nosotros la vuelta anterior. Un resumen de los primeros 90 s
    congelado durante toda la clase no sirve de nada; pisar el que corrigio el
    duenio es peor. Recordar lo ultimo que escribimos es lo que distingue los
    dos casos sin tener que adivinar.
    """
    texto = sesion.texto_dicho() or ""
    if not str(entrada.get("titulo") or "").strip():
        entrada["titulo"] = (ap._titulo_de_clave(sesion, entrada.get("claves") or [])
                             or ap._titulo_extractivo(sesion, texto))
    actual = str(entrada.get("resumen") or "")
    mio = st["resumenes"].get(clave)
    if not actual.strip() or actual == mio:
        nuevo = ap.compactar(texto, ap._presupuesto_resumen(texto))
        if nuevo:
            entrada["resumen"] = nuevo
            st["resumenes"][clave] = nuevo


# ── Volcado al documento ─────────────────────────────────────────────────────

def _volcar_a_documento(materia: str, entrada: dict, clave: str, st: dict) -> dict:
    """Sube lo refinado a los bloques del documento de la materia.

    Import PEREZOSO y tolerante: si `documento.py` no esta (o revienta), el
    refinado sigue haciendo su trabajo sobre apuntes.json, que es donde vive
    el cuaderno. Perder el volcado es molesto; perder los apuntes no.
    """
    materia = str(materia or "").strip()
    if not materia or materia == MATERIA_SIN_CLASIFICAR:
        return {}                       # ver la decision 7 del encabezado
    try:
        from cognia.clases import documento as doc
    except ImportError as exc:
        _degradar("clases.refinado.documento",
                  "no se pudo importar clases/documento.py (%s): lo refinado "
                  "se queda en apuntes.json" % exc)
        return {}
    try:
        return doc.desde_apuntes(materia, entrada, clave)
    except Exception as exc:
        aviso = ("el volcado a bloques de %s fallo (%s: %s): los apuntes SI "
                 "estan en apuntes.json" % (materia, type(exc).__name__, exc))
        _degradar("clases.refinado.documento", aviso)
        _anotar(st, aviso)
        return {}


# ── El ciclo ─────────────────────────────────────────────────────────────────

def _resultado(jornada: str, estado_ciclo: str) -> dict:
    return {"jornada": jornada, "estado": estado_ciclo, "sesiones": 0,
            "llamadas": 0, "mudas": 0, "lentas": 0, "aniadidos": 0,
            "avisos": [], "apagado": "", "documento": {}}


def ciclo(jornada: str, generar=None, min_tramo: int = 0) -> dict:
    """UNA vuelta del refinado, toque o no por periodo (eso lo decide `tick`).

    `generar` es la puerta del modelo: una funcion prompt -> texto. Por
    defecto `_generar_por_llm`. Es un parametro para poder probar el ciclo
    entero -- las dos vueltas, el modelo caido, el disyuntor -- sin levantar
    un modelo de 27B, que es lo unico que hace probable que estos caminos se
    prueben de verdad.

    `min_tramo` baja el liston de chars nuevos que merecen una llamada. Solo
    lo usa `cerrar` (con MIN_TRAMO_CIERRE): en el ritmo normal el liston alto
    es lo correcto, porque siempre hay otra vuelta detras.

    Devuelve {'estado', 'sesiones', 'llamadas', 'mudas', 'lentas',
    'aniadidos', 'avisos', 'apagado', 'documento'}. 'avisos' trae SOLO los
    nuevos: es lo que el vigia engancha en `JornadaViva.avisos`.
    """
    nombre = _clave_jornada(jornada)
    st = _estado_de(nombre)
    res = _resultado(nombre, "")

    if st["apagado"]:
        res["estado"] = "apagado"
        res["apagado"] = st["apagado"]
        return res

    st["vueltas"] += 1

    # ── 1. Lectura: que sesiones tienen tramo nuevo ──────────────────────
    with _LOCK_CICLO, ap._LOCK_MAPA:
        sesiones = cua.sesiones_de(nombre)
        claves = ap.claves_de_jornada(nombre, sesiones)[0]
        mapa = ap.cargar_mapa(nombre, sesiones)
    pendientes = []
    for i, s in enumerate(sesiones):
        previo = mapa.get(claves[i])
        marca, tramo = _pendiente(s, previo if isinstance(previo, dict) else {})
        if len(tramo) >= (min_tramo or MIN_TRAMO_CHARS):
            pendientes.append((claves[i], s, marca, tramo))
    if not pendientes:
        res["estado"] = "sin-tramo"
        return res

    # El sondeo va AQUI y no al entrar: un sondeo fallido cuesta hasta 2 s por
    # backend candidato (~4 s de hilo vigia bloqueado), y pagarlos en una
    # vuelta que no tiene ni un char nuevo que refinar -- el caso normal en
    # una jornada recien abierta o ya cerrada -- es tirarlos. Lo que la
    # decision 2 exige es no llamar al modelo con una cache rancia, y eso pasa
    # justo despues de esta linea.
    if generar is None:
        _resondear_si_toca()
        generar = _generar_por_llm

    # ── 2. El modelo, FUERA de los locks (son minutos) ───────────────────
    # Las sesiones se recorren en orden de t0: la que crece es la ultima, y
    # las de delante solo tienen tramo pendiente cuando el refinado se
    # enciende a mitad de jornada. En ese caso se ponen al dia por orden, dos
    # ventanas por vuelta, sin que ninguna se quede sin turno.
    presupuesto = MAX_VENTANAS_VUELTA
    lote, mudas, lentas = [], 0, 0
    for clave, sesion, marca, tramo in pendientes:
        if presupuesto <= 0:
            break
        ventanas, avance = _lote_de_vuelta(tramo, presupuesto)
        if not ventanas:
            continue
        del_modelo: dict = {}
        for v in ventanas:
            presupuesto -= 1
            res["llamadas"] += 1
            st["llamadas"] += 1
            # Se CRONOMETRA para poder decirle al duenio cual de los dos
            # fallos tiene: un modelo que contesta y no dice nada util no se
            # arregla igual que uno que se come el timeout entero.
            t_ini = time.time()
            texto = ap._sin_razonamiento(generar(ap._PROMPT_VENTANA % v) or "")
            tardo = time.time() - t_ini
            trozo = ap._parsear(texto) if texto else {}
            if not any(trozo.values()):
                mudas += 1
                if tardo >= TIMEOUT_VENTANA:
                    lentas += 1
                continue
            ap._fundir(del_modelo, trozo)
        if not del_modelo:
            # NO se avanza la marca: el tramo se vuelve a pedir cuando el
            # modelo este. Con el modelo caido no se pierde ni un char.
            continue
        lote.append((clave, sesion, marca + avance, del_modelo))
    res["mudas"] = mudas
    res["lentas"] = lentas

    if not lote:
        return _esteril(nombre, st, res, pendientes, mudas, lentas)

    # ── 3. Fusion y escritura, releyendo dentro del lock ─────────────────
    volcados = {}
    with _LOCK_CICLO, ap._LOCK_MAPA:
        sesiones = cua.sesiones_de(nombre)
        claves_ahora = set(ap.claves_de_jornada(nombre, sesiones)[0])
        ruta = alm.dir_jornada(nombre) / alm.APUNTES
        mapa = ap.cargar_mapa(nombre, sesiones)
        for clave, sesion, marca_nueva, del_modelo in lote:
            if clave not in claves_ahora:
                # La deteccion movio un corte mientras el modelo respondia.
                # No se escribe en una clave que ya no es de nadie; el tramo
                # sigue pendiente (su marca no avanzo) y entra en la vuelta
                # siguiente con la clave buena.
                _anotar(st, "los cortes de materia cambiaron mientras el "
                            "modelo respondia: el tramo de '%s' se vuelve a "
                            "pedir en la vuelta siguiente" % clave)
                continue
            previo = mapa.get(clave)
            previo = previo if isinstance(previo, dict) else {}
            entrada = dict(previo)          # NADA de lo que hay se pierde
            secciones = _secciones_de(previo)
            entraron = _fundir_con_tope(secciones, del_modelo, st,
                                        getattr(sesion, "materia", ""))
            entrada.update(secciones)
            # La marca no puede RETROCEDER: entre la lectura y esto puede
            # haber corrido un `generar_jornada` que proceso la sesion entera.
            entrada["chars_entrada"] = max(int(previo.get("chars_entrada") or 0),
                                           marca_nueva)
            entrada["via"] = VIA_REFINADO
            _titulo_y_resumen(entrada, sesion, st, clave)
            # La garantia dura de `apuntes.py`: lo que el duenio marco
            # importante esta en 'claves' o en 'examen', literal. Es
            # deterministico y gratis, y hace que se vea YA en el cuaderno
            # vivo en vez de al cerrar la jornada.
            entrada = ap._asegurar_importantes(entrada, sesion.del_usuario())
            entrada["chars_salida"] = ap._chars_salida(ap._normalizar(entrada))
            # EL AVISO DICE LO QUE QUEDA FUERA. `apuntes.generar` devuelve
            # unos apuntes YA ESCRITOS tal cual (no los regenera si no se
            # fuerza), asi que la cola de clase que este refinado todavia no
            # proceso no la va a procesar nadie al cerrar la jornada: eso
            # tiene que poder LEERSE en la hoja, no descubrirse echando de
            # menos el ultimo cuarto de hora. Quien cierre la jornada vacia
            # esa cola con `cerrar()`.
            pendiente = max(0, len(sesion.texto_dicho() or "")
                            - entrada["chars_entrada"])
            entrada["aviso"] = (
                "refinado en caliente: %d lineas nuevas sobre %d chars de "
                "clase%s" % (entraron, entrada["chars_entrada"],
                             ("; quedan %d chars por refinar" % pendiente)
                             if pendiente else ""))
            mapa[clave] = entrada
            res["sesiones"] += 1
            res["aniadidos"] += entraron
            st["aniadidos"] += entraron
            volcados[clave] = (getattr(sesion, "materia", ""), entrada)
        alm.guardar_json(ruta, mapa)

    st["ultimo_ok"] = time.time()
    st["disyuntor"].registrar(rep.huella_de_texto(""), ok=True,
                              nota="vuelta con contenido")
    for clave, (materia, entrada) in volcados.items():
        informe = _volcar_a_documento(materia, entrada, clave, st)
        if informe:
            res["documento"][clave] = informe
    res["estado"] = "refinado"
    res["avisos"] = _nuevos(st)
    return res


def _nuevos(st: dict) -> list:
    """Los avisos que esta vuelta dijo por primera vez.

    Se calculan comparando con lo ya entregado y no con la lista entera:
    `JornadaViva.avisos` es append-only y el vigia corre cada 90 s, asi que
    devolver siempre todo lo dicho llenaria la lista de repeticiones.
    """
    entregados = st.setdefault("entregados", 0)
    nuevos = st["avisos"][entregados:]
    st["entregados"] = len(st["avisos"])
    return list(nuevos)


def _esteril(nombre: str, st: dict, res: dict, pendientes: list,
             mudas: int, lentas: int = 0) -> dict:
    """Una vuelta que llamo al modelo y no saco NADA.

    Aqui es donde entra el disyuntor (regla 11 de CLAUDE.md): el sintoma se
    reduce a una huella ESTABLE -- sin numeros ni horas, que cambiarian entre
    vueltas y dejarian el disyuntor muerto sin que nadie se entere -- y tras
    HUELLA_REPETIDA_CORTA vueltas identicas se apaga el refinado de esta
    jornada.

    El aviso se intenta dejar TAMBIEN en el campo 'aviso' de los apuntes, pero
    solo de las sesiones que YA tienen algo escrito: ver la decision 6 del
    encabezado (una entrada que solo lleve un aviso haria que `olvido`
    comprimiera la transcripcion de una clase sin apuntes).
    """
    hay_backend = llm.detectar_backend() is not None
    if lentas:
        # MEDIDO en esta maquina el 2026-08-31: el 8080 contesta /health y la
        # generacion se come los 60 s enteros. Decir "no emitio nada util"
        # ahi seria mentir sobre lo que hay que arreglar.
        motivo = ("el modelo tarda mas de %d s por ventana: hay algo "
                  "escuchando en el puerto pero no rinde" % TIMEOUT_VENTANA)
    elif mudas and hay_backend:
        motivo = "el modelo no emitio nada util"
    else:
        motivo = "el modelo local no esta arriba (127.0.0.1:8080)"
    aviso = ("%s: el tramo nuevo de la clase queda pendiente y se reintenta "
             "en la vuelta siguiente" % motivo)
    _anotar(st, aviso)
    res["estado"] = "sin-modelo"

    st["disyuntor"].registrar(rep.huella_de_texto(motivo, tipo="refinado"),
                              ok=False, hubo_cambio=True, nota=motivo)
    corte = st["disyuntor"].motivo_corte()
    if corte:
        st["disyuntor"].anotar_corte()
        # EL AVISO DEL APAGADO NO PUEDE MENTIR: es la unica ventana que tiene
        # el duenio a por que no hay apuntes. Lo que decia antes -- "nada se ha
        # perdido" y "los apuntes se generan al cerrar" -- era falso en el
        # unico caso en que este texto se escribe: hay entradas escritas por el
        # refinado, y `apuntes.generar` devuelve unos apuntes que ya existen
        # TAL CUAL (apuntes.py:814), asi que el cierre NO recoge el tramo que
        # falta. Lo que si es cierto es que la transcripcion literal sigue
        # entera y que `olvido` no la comprimira (ver `cobertura`).
        apagado = ("refinado APAGADO en esta jornada (%s: %s). Lo ya refinado "
                   "sigue en los apuntes y la transcripcion literal sigue "
                   "ENTERA en el cuaderno; pero el tramo que quede sin refinar "
                   "NO lo recoge el cierre (apuntes.generar devuelve tal cual "
                   "los apuntes que ya existen). Para reanudarlo: %s on"
                   % (corte, motivo, SUBCOMANDO_CLI))
        apagar(nombre, apagado)
        res["apagado"] = apagado
    _escribir_aviso(nombre, [p[0] for p in pendientes],
                    st["apagado"] or aviso)
    res["avisos"] = _nuevos(st)
    return res


def _escribir_aviso(nombre: str, claves: list, aviso: str) -> None:
    """Deja el aviso en el campo 'aviso' de las entradas que YA existen, SIN
    pisar lo que ese campo ya decia.

    NO crea ninguna: ver la decision 6. Si la jornada no tiene todavia ni una
    entrada con contenido, el aviso vive en `estado()` y en el log, y el
    duenio lo ve por la puerta del CLI -- que es donde iba a mirar de todas
    formas cuando se preguntara por que no hay apuntes.

    Y NO SUSTITUYE, CONCATENA. El 'aviso' que escribe el ciclo bueno es el
    unico sitio donde pone cuantos chars quedan por refinar; sobreescribirlo
    con el de una vuelta esteril (o con el del apagado del disyuntor) borraba
    justo la cifra que dice CUANTO falta, que es la mitad que le sirve al
    duenio. El crecimiento esta acotado porque se dedupe por subcadena y los
    textos posibles son cuatro (tres motivos de esterilidad y el apagado).
    """
    aviso = str(aviso or "").strip()
    if not aviso:
        return
    with _LOCK_CICLO, ap._LOCK_MAPA:
        sesiones = cua.sesiones_de(nombre)
        mapa = ap.cargar_mapa(nombre, sesiones)
        toco = False
        for k in claves:
            previo = mapa.get(k)
            if not isinstance(previo, dict) or not previo:
                continue
            antes = str(previo.get("aviso") or "").strip()
            if aviso in antes:
                continue
            previo = dict(previo)
            previo["aviso"] = (antes + SEPARADOR_AVISOS + aviso) if antes else aviso
            mapa[k] = previo
            toco = True
        if toco:
            alm.guardar_json(alm.dir_jornada(nombre) / alm.APUNTES, mapa)


def cerrar(jornada: str, generar=None) -> dict:
    """Vacia la cola de tramo pendiente antes de que la jornada se cierre.

    POR QUE HACE FALTA, y es la unica arista de esta pieza: `apuntes.generar`
    devuelve unos apuntes ya escritos TAL CUAL cuando existen y no se fuerza
    (apuntes.py:814). En cuanto el refinado escribe la primera entrada, el
    `generar_jornada` del cierre deja de regenerar esa sesion -- que es
    justamente lo que se busca (no pagar 13 llamadas por algo ya hecho) --,
    pero eso significa que lo que el refinado NO haya procesado no lo procesa
    nadie despues. Con el ritmo por defecto la cola es de minutos de clase;
    sin esto, se perderia en silencio.

    Corre vueltas sin mirar el periodo y con el liston de tramo bajado a
    MIN_TRAMO_CIERRE, como mucho MAX_VUELTAS_CIERRE veces. Si el disyuntor
    apago el refinado NO lo reabre (seria un reintento automatico disfrazado):
    lo dice y se va, y lo que quede pendiente esta escrito en el campo 'aviso'
    de esa sesion.

    QUIEN LO LLAMA: `JornadaViva.parar()`, en `_cerrar_refinado()`, DESPUES de
    los cortes definitivos y ANTES de `generar_apuntes()`. Va ahi y no en el
    vigia porque `parar()` hace `self._vigia.join(timeout=5.0)` y una llamada
    al modelo dura mas que eso: tiene que correr en el hilo que cierra, con el
    vigia ya parado.
    """
    nombre = _clave_jornada(jornada)
    st = _estado_de(nombre)
    total = _resultado(nombre, "cerrado")
    if st["apagado"]:
        total["estado"] = "apagado"
        total["apagado"] = st["apagado"]
        return total
    for _ in range(MAX_VUELTAS_CIERRE):
        res = ciclo(nombre, generar=generar, min_tramo=MIN_TRAMO_CIERRE)
        for k in ("sesiones", "llamadas", "mudas", "lentas", "aniadidos"):
            total[k] += res.get(k, 0)
        total["avisos"].extend(res.get("avisos") or [])
        total["documento"].update(res.get("documento") or {})
        total["apagado"] = res.get("apagado") or ""
        if res["estado"] != "refinado":
            break
    return total


def tick(jornada: str, generar=None, ahora=None, forzar: bool = False) -> dict:
    """La puerta del hilo vigia: una vuelta SI toca por periodo.

    Se llama en cada vuelta del vigia (cada 90 s) y decide aqui si toca, en
    vez de tener su propio hilo: un hilo mas por jornada es un hilo mas que
    dejar colgado, y el vigia ya esta despierto y ya sabe cuando la jornada
    murio.

    `forzar` salta el periodo Y el on/off de la config (es lo que teclea el
    duenio en `/grabar-clase refinado ahora`), pero NO enciende un refinado que apago el
    disyuntor: eso solo lo hace `encender()`, porque un reintento automatico
    disfrazado de "forzar" es justo lo que la regla 11 prohibe.
    """
    nombre = _clave_jornada(jornada)
    st = _estado_de(nombre)
    if st["apagado"]:
        res = _resultado(nombre, "apagado")
        res["apagado"] = st["apagado"]
        return res
    if not activo() and not forzar:
        return _resultado(nombre, "off")
    ahora = time.time() if ahora is None else float(ahora)
    if not forzar and (ahora - st["ultimo"]) < periodo():
        return _resultado(nombre, "todavia-no")
    st["ultimo"] = ahora
    return ciclo(nombre, generar=generar)
