"""
cognia/agent/salida_continua.py
==============================
SALIDA CONTINUA: la respuesta sale ENTERA aunque no quepa en un turno.

POR QUE EXISTE (medido en las sesiones reales del dueno, ~/.cognia/cognia_memory.db):

  id 1071 (2026-08-31 08:00, cwd .../Ark) — el turno de chat entrego 500 chars
  que son razonamiento PURO ("<think> ... Let me create a complete, functional
  game. The name \"") y ahi se corto. Dentro de ese mismo texto el modelo cita
  sus propias memorias: *"5 memorias dicen: No se logro completar la tarea de
  crear un juego completo en un unico archivo HTML. La tarea se corto antes de
  finalizar."* El fallo lleva CINCO intentos repitiendose.

  id 1061 (2026-08-30 22:23) — el mismo corte por el otro lado: 253 fragmentos
  de respuesta y 77.907 chars de razonamiento, y el server devolvio HTTP 500
  ("Failed to parse tool call arguments as JSON ... missing closing quote;
  last read: '\"<!DOCTYPE html>...'"): el argumento se corto a media cadena.

QUE HACIA EL CLI HASTA AHORA (cli.py, fast-path del chat). Ante un
``finish_reason='limit'`` reintentaba UNA vez con el doble de max_tokens y
—esto es lo grave— hacia ``_tokens_buf = []``: **tiraba a la basura todo lo ya
generado** y volvia a empezar de cero. Con un razonador que gasta el
presupuesto pensando, el segundo intento piensa OTRA VEZ lo mismo y muere en
la misma columna; a la segunda se entregaba el truncado. Es la rampa inutil
que ``presupuesto_salida`` ya documento para el bucle del agente, aqui en el
chat: subir el numero no cura un corte que llega igual.

QUE HACE ESTE MODULO. En vez de reintentar, CONTINUA: cuando el turno para por
tope, se pide otro tramo que arranca donde murio el anterior y se pega al
texto que ya salio. El tope de tokens deja de ser el techo de la RESPUESTA y
pasa a ser el tamano de cada TRAMO. Para el que mira, la respuesta sale de un
solo tiron.

Y no desborda la ventana: al pedir la continuacion no se reenvia la respuesta
entera, solo su COLA (``cola_de()``). El prompt de cada tramo tiene tamano
ACOTADO, asi que el numero de tramos no esta limitado por n_ctx — esa es la
"compactacion" que hace posible una salida arbitrariamente larga con una
ventana fija. El texto completo se conserva siempre en el lado del CLI: la
cola es solo lo que el modelo necesita para re-anclarse.

LA COSTURA. Un modelo al continuar tiende a volver sobre lo ultimo que dijo, y
lo hace de dos maneras que hay que cazar por separado (medido contra
llama3.2:3b, 7 tramos):
  - repite LITERAL el final -> ``solape()``, prefijo del tramo == sufijo de lo
    acumulado;
  - lo REESCRIBE y vuelve a pasar por el mismo punto ("...y las antenas de" +
    "11. Instala la conexion a Internet y las antenas de radio") -> ahi no hay
    prefijo comun, pero el final de lo acumulado REAPARECE dentro de la cabeza
    del tramo: ``reencuentro()``.
``recorte()`` aplica las dos. Para poder recortar hay que retener los primeros
chars del tramo antes de pintarlos; esa retencion es la unica latencia que
anade la costura, y solo en tramos >= 2. Lo que no se puede cazar por
aritmetica es la repeticion PARAFRASEADA (texto distinto que dice lo mismo):
contra eso juega la instruccion de continuar, no la costura.

FRENOS (un bucle que genera para siempre es peor que un truncado):
  - tramo que no aporta texto nuevo -> se para,
  - tramo identico al anterior (modelo en bucle de repeticion) -> se para,
  - ``rondas_max`` (default 64) y ``tope_total`` en tokens (default 0 = sin
    tope) -> configurables desde ``/ventana continuo``.
El Ctrl-C del usuario sube tal cual: el generador no lo captura.

Todo lo de aqui es aritmetica de strings + un callback: se testea sin red
(``tests/test_salida_continua.py``).
"""

from __future__ import annotations

import os

# Chars de la respuesta que se reenvian como re-anclaje al pedir el siguiente
# tramo. ~4 chars/token: 4000 chars son ~1000 tokens de prompt, constantes por
# tramo. Es lo que hace que la salida no tenga techo de ventana.
COLA_REANCLAJE = 4000

# Ventana donde se busca la costura. Mas alla de 400 chars un "solape" ya no es
# el modelo repitiendo el final: es texto legitimo que casualmente se parece.
SOLAPE_MAX = 400

# Por debajo de esto un solape no se cree: un espacio, una coma o un "\n" al
# final de lo acumulado coinciden con el principio de casi cualquier tramo, y
# recortar por ahi se come texto bueno.
SOLAPE_MIN = 12

# Chars finales del acumulado que se usan como ANCLA para el reencuentro.
# Medido contra llama3.2:3b (2026-08-31, 7 tramos de 120 tok): la repeticion
# tipica no es un solape sufijo-prefijo sino una REESCRITURA — lo acumulado
# acaba en "...y las antenas de" y el tramo nuevo arranca "11. Instala la
# conexion a Internet y las antenas de radio". No hay prefijo comun, asi que
# solape() no la ve; pero el final del acumulado REAPARECE dentro de la cabeza
# del tramo, y ahi es donde hay que cortar. 40 chars son un ancla lo bastante
# larga para que no coincida por casualidad en prosa.
ANCLA_REENCUENTRO = 40

# Tope duro de tramos. No es un presupuesto de respuesta (64 tramos de 12k son
# ~768k tokens, muy por encima de cualquier respuesta real): es el freno para
# el caso patologico del modelo que entra en bucle y nunca emite su fin.
RONDAS_MAX = 64

# Tramos SEGUIDOS que pueden irse enteros en razonamiento (cero chars de
# respuesta) antes de rendirse. Este caso lo destapo la prueba contra el server
# real (2026-08-31, Qwen3.8-27B en :8080): con el tope pequenio, un tramo
# devolvio finish_reason='limit' con 0 chars de content — todo el presupuesto
# se fue pensando. Es el fallo de chat_history id 1071 tal cual. Pararse ahi
# seria pararse justo cuando MAS falta seguir; pero repetir sin freno tampoco
# vale, porque sin texto que re-anclar el modelo vuelve a pensar lo mismo (la
# rampa inutil que documenta presupuesto_salida). Por eso: se insiste, con la
# instruccion de dejar de pensar y responder YA, y solo un par de veces.
SIN_TEXTO_MAX = 2

# Tope total en tokens de salida. 0 = SIN TOPE (default): el que manda es el
# modelo cuando decide que termino.
TOPE_TOTAL = 0

# Deteccion de BUCLE. Medido contra llama3.2:3b (2026-08-31): pedidos 12 pasos,
# la continuacion llego al paso 39 y empezo a reemitir bloques enteros ya
# escritos. Un modelo debil, al continuar, puede no parar nunca — y "sin tope"
# sin este freno es una GPU quemando horas para reescribir lo mismo. La huella
# son los ultimos HUELLA chars: si ya aparecieron antes (dentro de la ventana
# reciente) el texto esta dando vueltas y se cierra ahi. 300 chars identicos y
# contiguos no se repiten por casualidad en prosa; en codigo muy repetitivo
# podrian, y por eso el freno solo mira a partir del tercer tramo.
BUCLE_HUELLA = 300
BUCLE_VENTANA = 12000
BUCLE_DESDE_TRAMO = 3

ENV_ACTIVA = "COGNIA_SALIDA_CONTINUA"
ENV_RONDAS = "COGNIA_SALIDA_RONDAS"
ENV_TOPE = "COGNIA_SALIDA_TOPE"
ENV_TRAMO = "COGNIA_SALIDA_TRAMO"

# Piso del tramo. Por debajo de esto un razonador gasta el tramo entero
# pensando y devuelve cero chars de respuesta (medido contra Qwen3.8-27B con
# 220 tokens: finish='limit', content vacio) — es el MINIMO_UTIL que
# presupuesto_salida ya tenia documentado para el bucle del agente. El override
# se respeta igual si el dueno lo pide a proposito (probar la costura necesita
# tramos pequenios): el piso solo se aplica al valor por defecto.
TRAMO_MIN = 64

# Lo que se le dice al modelo para que siga en vez de volver a empezar. Es la
# pieza fragil de la continuacion por CHAT (el camino de completado crudo no la
# necesita: ahi el texto se pega literalmente al turno del asistente).
INSTRUCCION_CONTINUAR = (
    "Continua tu respuesta anterior EXACTAMENTE donde se corto. "
    "Se corto por un limite de longitud, no porque hubieras terminado. "
    "No saludes, no te disculpes, no resumas lo dicho, no vuelvas a empezar "
    "y no repitas ninguna linea ya escrita: emite solo lo que sigue, "
    "arrancando en el caracter siguiente al ultimo (aunque quede a mitad de "
    "una palabra, de una linea de codigo o de una etiqueta). "
    "Cuando de verdad termines, para."
)

# Para el tramo que se fue ENTERO en razonamiento: no hay texto que continuar,
# lo que hay que pedirle es que deje de pensar y escriba.
#
# LIMITE MEDIDO (2026-08-31, Qwen3-4B-Thinking-2507 en :8080). Con un razonador
# PURO esta instruccion no rescata nada: la plantilla abre <think> en cada
# turno y el tramo se va otra vez en pensar. Comprobado tambien que el switch
# `/no_think` de las Qwen3 hibridas NO le hace efecto a esta variante — pedir
# "di en una frase que es una mudanza" con 400 tokens devolvio 1.552 chars de
# razonamiento y CERO de content, con y sin el switch. Contra eso las dos
# palancas que si funcionan viven fuera de este modulo: subir el tramo por
# encima del minimo util (presupuesto_salida.MINIMO_UTIL = 4096) o apagar el
# pensamiento en el perfil (/ventana pensamiento off), que es justo lo que hace
# el bucle del agente. Por eso el aviso del CLI nombra las dos.
INSTRUCCION_RESPONDER_YA = (
    "Te has quedado sin espacio razonando y no has escrito nada de la "
    "respuesta. No razones mas: escribe AHORA la respuesta final directamente, "
    "empezando por la primera linea de contenido util."
)


def activa(config=None, entorno=None) -> bool:
    """True si la continuacion esta encendida. Default: SI.

    Orden: la env manda sobre el fichero de config (misma regla que el resto
    de puertas del CLI). Cualquier valor raro se lee como el default.
    """
    entorno = os.environ if entorno is None else entorno
    val = (entorno.get(ENV_ACTIVA) or "").strip().lower()
    if val in ("0", "off", "no", "false"):
        return False
    if val in ("1", "on", "si", "true"):
        return True
    if isinstance(config, dict) and "salida_continua" in config:
        return str(config.get("salida_continua")).strip().lower() not in (
            "0", "off", "no", "false")
    return True


def _entero(fuentes, clave_env, clave_cfg, defecto: int) -> int:
    entorno, config = fuentes
    val = (entorno.get(clave_env) or "").strip()
    if not val and isinstance(config, dict):
        val = str(config.get(clave_cfg, "")).strip()
    if not val:
        return defecto
    try:
        n = int(val)
    except (TypeError, ValueError):
        return defecto
    return n if n >= 0 else defecto


def limites(config=None, entorno=None):
    """``(rondas_max, tope_total)`` leidos de env/config. 0 = sin tope."""
    entorno = os.environ if entorno is None else entorno
    fuentes = (entorno, config)
    return (_entero(fuentes, ENV_RONDAS, "salida_continua_rondas", RONDAS_MAX),
            _entero(fuentes, ENV_TOPE, "salida_continua_tope", TOPE_TOTAL))


def tramo(base: int, config=None, entorno=None) -> int:
    """Tokens por TRAMO. ``base`` es el max_tokens del nivel /esfuerzo activo.

    Existe un override (env/config) porque el tamano del tramo ya no es el
    techo de la respuesta sino el grano con el que se pide: bajarlo hace la
    costura visible y comprobable, subirlo reduce el numero de cortes.
    """
    entorno = os.environ if entorno is None else entorno
    val = _entero((entorno, config), ENV_TRAMO, "salida_continua_tramo", 0)
    if val:
        return max(TRAMO_MIN, val)
    try:
        return int(base)
    except (TypeError, ValueError):
        return TRAMO_MIN


def cola_de(texto: str, limite: int = COLA_REANCLAJE) -> str:
    """La cola de ``texto`` que se reenvia como re-anclaje.

    Cuando hay que cortar se marca con un "[...]" delante: sin la marca el
    modelo lee un texto que empieza a media frase como si fuera el principio de
    su respuesta y arranca de nuevo (medido: sin marca reescribia el <!DOCTYPE>
    a mitad de un HTML). El corte se busca en un salto de linea cercano para no
    partir una linea de codigo por el medio.
    """
    if limite <= 0 or len(texto) <= limite:
        return texto
    cola = texto[-limite:]
    corte = cola.find("\n")
    # Solo se acepta el corte por linea si no se come mas de un 20% de la cola:
    # con lineas muy largas (un HTML minificado) no hay salto y se deja tal cual.
    if 0 <= corte <= limite // 5:
        cola = cola[corte + 1:]
    return "[...]\n" + cola


def solape(acumulado: str, trozo: str, maximo: int = SOLAPE_MAX,
           minimo: int = SOLAPE_MIN) -> int:
    """Chars del principio de ``trozo`` que ya estan al final de ``acumulado``.

    0 cuando no hay costura que recortar. Se busca el solape MAS LARGO (un
    modelo que repite suele repetir la frase entera, no dos letras) y se
    descartan los cortos, que son coincidencias de puntuacion.
    """
    if not acumulado or not trozo:
        return 0
    k = min(len(acumulado), len(trozo), max(0, int(maximo)))
    while k >= max(1, int(minimo)):
        if acumulado.endswith(trozo[:k]):
            return k
        k -= 1
    return 0


def reencuentro(acumulado: str, trozo: str, ancla: int = ANCLA_REENCUENTRO,
                ventana: int = SOLAPE_MAX) -> int:
    """Chars a saltar cuando el modelo REESCRIBE en vez de repetir literal.

    Se busca el final del acumulado (el ancla) dentro de la cabeza del tramo
    nuevo: si reaparece, todo lo que hay por delante es la reescritura y el
    texto util empieza justo despues. 0 si no reaparece.
    """
    if not trozo or len(acumulado) < ancla or ancla <= 0:
        return 0
    marca = acumulado[-ancla:]
    if not marca.strip():
        return 0
    pos = trozo[:max(0, int(ventana))].find(marca)
    return pos + len(marca) if pos >= 0 else 0


def recorte(acumulado: str, trozo: str) -> int:
    """Chars del principio de ``trozo`` que sobran al pegarlo a ``acumulado``.

    Primero la repeticion literal (``solape``), y si no la hay, la reescritura
    (``reencuentro``). Lo que ninguna de las dos caza es la repeticion
    PARAFRASEADA ("despliega la tienda" tras "desplegar la tienda"): eso no es
    texto igual y no se puede recortar por aritmetica sin arriesgar texto bueno
    — contra eso juega la instruccion de continuar, no la costura.
    """
    return solape(acumulado, trozo) or reencuentro(acumulado, trozo)


def en_bucle(acumulado: str, huella: int = BUCLE_HUELLA,
             ventana: int = BUCLE_VENTANA) -> bool:
    """True si el texto esta dando vueltas sobre si mismo.

    Se toma la huella final y se busca en lo escrito ANTES (solo en la ventana
    reciente: un eco a 50.000 chars de distancia no es un bucle, es un texto
    largo que vuelve sobre un tema). Es el unico freno que de verdad protege el
    modo "sin tope": los demas cuentan tramos, este mira lo que sale.
    """
    if huella <= 0 or len(acumulado) < huella * 2:
        return False
    cola = acumulado[-huella:]
    if not cola.strip():
        return False
    return cola in acumulado[:-huella][-max(0, int(ventana)):]


def continuacion_mensajes(messages, cola: str, instruccion: str = ""):
    """Mensajes para pedir el siguiente tramo por el endpoint de CHAT.

    Se anade lo ya dicho como turno del asistente (la COLA, no la respuesta
    entera: por eso el prompt no crece tramo a tramo) y un turno de usuario que
    pide continuar. No muta la lista original.

    Con ``cola`` vacia (el tramo se fue entero en razonamiento) NO se mete un
    turno de asistente vacio — algunas plantillas lo renderizan como un turno
    ya cerrado y el modelo cree que respondio — y se pide responder ya.
    """
    base = list(messages or [])
    if not cola:
        return base + [{"role": "user",
                        "content": instruccion or INSTRUCCION_RESPONDER_YA}]
    return base + [
        {"role": "assistant", "content": cola},
        {"role": "user", "content": instruccion or INSTRUCCION_CONTINUAR},
    ]


def stream_continuo(pedir, parada, chunk_tokens: int,
                    rondas_max: int = RONDAS_MAX,
                    tope_total: int = TOPE_TOTAL,
                    cola: int = COLA_REANCLAJE,
                    sin_texto_max: int = SIN_TEXTO_MAX,
                    on_tramo=None):
    """Generador de tokens de la respuesta COMPLETA, tramo a tramo.

    ``pedir(cola, chunk)`` -> iterable de tokens. ``cola`` es **None** en el
    primer tramo, y en los siguientes la cola de re-anclaje (que puede ser ""
    si el tramo anterior no escribio nada); el llamador decide como se
    convierte en peticion (mensajes de chat o prompt crudo + texto), porque eso
    depende del endpoint y este modulo no habla por red.

    ``parada()`` -> el ``last_stop_reason`` del backend tras agotar el iterable.
    Solo ``'limit'`` (corte por tope) encadena otro tramo; un fin natural, un
    error o un None cierran.

    ``on_tramo(ronda, chars_nuevos, chars_total)`` se llama al cerrar cada
    tramo (best-effort, sus excepciones se tragan): es el gancho del aviso del
    CLI, que no puede imprimir a media respuesta sin romper el markdown vivo.

    KeyboardInterrupt NO se captura: sube al llamador, que ya sabe cerrar el
    turno dejando lo que hubiera salido.
    """
    acumulado = ""
    previo = None
    ronda = 0
    sin_texto = 0
    while True:
        ronda += 1
        # None = arranque (no hay nada previo). "" = hay que continuar pero no
        # hay texto que re-anclar (el tramo anterior se fue en razonar): son
        # peticiones DISTINTAS y el llamador tiene que poder distinguirlas.
        entrada = None if ronda == 1 else cola_de(acumulado, cola)
        # Retencion para la costura: en tramos >= 2 no se puede pintar el
        # principio hasta saber cuanto de el es repeticion.
        buf = []
        buf_len = 0
        reteniendo = ronda > 1 and bool(entrada)
        nuevo = ""
        bruto = 0        # chars que EMITIO el modelo, antes de la costura
        for tok in pedir(entrada, chunk_tokens):
            if not tok:
                continue
            bruto += len(tok)
            if reteniendo:
                buf.append(tok)
                buf_len += len(tok)
                if buf_len < SOLAPE_MAX:
                    continue
                cabeza = "".join(buf)
                buf, buf_len, reteniendo = [], 0, False
                cabeza = cabeza[recorte(acumulado, cabeza):]
                if cabeza:
                    acumulado += cabeza
                    nuevo += cabeza
                    yield cabeza
                continue
            acumulado += tok
            nuevo += tok
            yield tok
        if buf:                      # el tramo entero cupo en la retencion
            cabeza = "".join(buf)
            cabeza = cabeza[recorte(acumulado, cabeza):]
            if cabeza:
                acumulado += cabeza
                nuevo += cabeza
                yield cabeza
        if on_tramo is not None:
            try:
                on_tramo(ronda, len(nuevo), len(acumulado))
            except Exception:
                pass
        if parada() != "limit":
            break                    # fin natural / error: la respuesta esta entera
        if not nuevo.strip():
            if bruto:
                # Emitio texto, pero era repeticion pura de lo ya dicho (la
                # costura se lo comio entero): continuar solo repetiria.
                break
            # Cero chars de respuesta: el tramo se fue en razonar. Se insiste
            # pidiendo que responda ya, unas pocas veces.
            sin_texto += 1
            if sin_texto > max(0, int(sin_texto_max)):
                break
        else:
            sin_texto = 0
        if nuevo and nuevo == previo:
            break                    # el modelo repite el mismo tramo: bucle
        previo = nuevo
        if ronda >= BUCLE_DESDE_TRAMO and en_bucle(acumulado):
            break                    # el texto da vueltas: cerrar aqui
        if rondas_max and ronda >= rondas_max:
            break
        if tope_total and len(acumulado) // 4 >= tope_total:
            break
