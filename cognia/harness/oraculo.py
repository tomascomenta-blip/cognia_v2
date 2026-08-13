# -*- coding: utf-8 -*-
"""Modelo por ROL + consulta EXPLICITA al oraculo (el agente barato pide ayuda).

Motivacion (2026-08-12, destilacion de harnesses #6 del ranking): el lazo de
Cognia corre con UN modelo para todo. El barato hace bien lo mecanico (leer,
editar, correr tests) y se estrella justo en los tres momentos caros: elegir el
enfoque, desatascarse de un error que ya intento dos veces, y juzgar si un
diseno se sostiene. La mecanica destilada de Aider (architect/editor), Claude
Code (`model` por subagente), el SDK de Agents de OpenAI (handoffs) y deepagents
es siempre la misma: **la consulta al modelo capaz es una HERRAMIENTA que el
agente invoca cuando SABE que la necesita**, no magia de un router que adivina
por detras. El que pide ayuda es el que esta atascado; nadie lo sabe mejor.

Que hace este modulo y que NO hace:
  - SI: decide A QUIEN preguntar (`elegir_rol`) y COMO formular la consulta
    (`armar_consulta`), lleva la contabilidad anti-abuso (tope por tarea +
    de-duplicacion) y devuelve un veredicto plano (`consultar`).
  - NO: no arranca modelos, no abre puertos, no habla HTTP. El transporte es
    una funcion INYECTADA ``(prompt, rol, timeout) -> texto`` que pone el
    integrador (el que ya sabe hablar con la flota). Reimplementar el arranque
    aca seria la tercera fuente de verdad de que modelo sirve que puerto, que
    es exactamente como :8088 sirvio un modelo retirado durante semanas
    (memoria del repo, 2026-07-25).

FUENTE DE VERDAD de que hay ARRANCADO: la flota (`cognia/flota.py` estado() y
`cognia/summoner.py` ROLES/ensure()). La tabla `ROLES` de aca declara INTENCION
("para esto quiero un razonador"), no disponibilidad. Si el rol pedido no esta
servido, el transporte lo dira (o lo levantara) y la consulta vuelve con
ok=False y el error REAL: el agente tiene que poder seguir sin oraculo.

DEGRADACION HONESTA, NUNCA SILENCIOSA. Tres formas de no tener respuesta y las
tres se declaran con su causa: transporte ausente, transporte que revienta
(error real, con tipo y mensaje) y transporte que se cuelga (tope de reloj
propio: el join no puede matar el hilo, pero el agente deja de esperar). Y una
cuarta que es la mas traicionera en este repo: la respuesta VACIA. Un "" que se
devolviera como ok=True es la degradacion silenciosa que ya cazamos en Cognia;
aca es ok=False con el motivo escrito. La quinta es del INTEGRADOR y no del
oraculo: un transporte que devuelve el JSON crudo (dict) en vez del texto; se
declara con el tipo real en vez de reventar con un AttributeError.

Uso desde el integrador:

    from cognia.harness.oraculo import consultar, reiniciar, spec_tool

    reiniciar()                      # al empezar CADA tarea (resetea tope y cache)
    r = consultar("me conviene un indice invertido o fuerza bruta?",
                  contexto=historial, transporte=mi_transporte)
    if r["ok"]:
        history.append(texto_resultado(r))
    else:
        history.append(texto_resultado(r))   # el fallo tambien se le cuenta

Coste de catalogo (dato MEDIDO en este repo, A/B 2026-07-25 n=4+4): pasar de un
catalogo chico a 46 herramientas baja el camino feliz de 4.25/5 a 2.5/5 — por eso
existe CORE_TOOLS (12 tools). `spec_tool()` deja la herramienta LISTA para
registrar, pero meterla en el catalogo por defecto es una decision que debe
pagarse con su propio A/B: mas herramientas no es mas capacidad, es mas
distraccion. Este modulo no toca el registry.

Limites declarados (a proposito, no son deuda oculta):
  - `elegir_rol` es una cascada LEXICA de reglas legibles, no un clasificador.
    Elige mal cuando el lexico miente ("revisa que no haya ningun error" cae en
    'codigo' por la palabra 'error'); el rol es SIEMPRE forzable a mano y el
    peor caso es preguntarle al modelo equivocado, no perder la respuesta.
  - El tope cuenta INTENTOS REALES al transporte (aciertos y fallos). Con el
    oraculo caido se gastan las 3 y se sigue sin el; es la cota que se quiere.
  - Los fallos NO se cachean (repreguntar tras arreglar el transporte es
    legitimo); solo se cachea la respuesta buena.
  - El watchdog de timeout usa `Thread.join`: si el transporte se cuelga, el
    agente sigue pero el hilo queda vivo en segundo plano (Python no mata
    hilos). Se declara en el propio mensaje de error.
  - Estado en RAM del proceso, sin BD: la unidad es LA TAREA, no la sesion.
  - El registro NO se protege con lock: la unidad es un lazo de UN hilo. Dos
    hilos consultando el mismo registro pueden pasarse del tope por una
    consulta; si algun dia hace falta, se pasa un `registro` por hilo.
  - Nada de esto LANZA: pregunta/contexto no textuales se pasan por `str()`,
    un `timeout` no numerico cae a TIMEOUT_DEF y un transporte que devuelve
    algo que no es texto sale como ok=False con su tipo.

Solo stdlib (hashlib, re, threading, time, unicodedata).
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
import unicodedata

# ── tabla de INTENCION: rol -> criterio de eleccion ─────────────────────
# Que hay ARRANCADO lo sabe la flota, no esta tabla (ver docstring). `prefiere`
# es el orden de preferencia declarado para el integrador que resuelve el rol
# contra la flota real; `combo_flota`/`rol_summoner` son la pista de COMO
# levantarlo (los nombres son los de COMBOS en cognia/flota.py y de ROLES en
# cognia/summoner.py, verificados 2026-08-12). `pide` es lo que se le exige
# devolver: un PLAN corto, jamas el fichero entero — el codigo lo escribe el
# barato, que es el que tiene el fichero delante.
ROLES = {
    "pensar": {
        "para": "decidir el ENFOQUE antes de escribir codigo, o desatascarse "
                "de un problema que no es un error puntual",
        "criterio": "el modelo mas CAPAZ que haya servido, aunque sea lento; "
                    "esta consulta se hace una vez y decide el resto de la tarea",
        "prefiere": ("gpt-oss-20b", "qwythos-9b"),
        "combo_flota": "pensar",
        "rol_summoner": "cerebro",
        "pide": "un plan de 3 a 6 pasos concretos, en orden, cada uno una linea",
        "max_palabras": 250,
    },
    "codigo": {
        "para": "un error concreto: traceback, test que falla, algo que no compila",
        "criterio": "el modelo mas fuerte en CODIGO que haya servido; se le da "
                    "el error exacto y se le pide la causa, no un rediseno",
        "prefiere": ("coder-14b", "qwythos-9b"),
        "combo_flota": "construir",
        "rol_summoner": "cerebro",
        "pide": "la CAUSA mas probable y el cambio minimo que la arregla "
                "(nombra fichero y funcion; NO pegues el fichero entero)",
        "max_palabras": 200,
    },
    "revisar": {
        "para": "juzgar algo YA hecho: un diseno, un parche, una decision",
        "criterio": "un razonador distinto del que escribio la respuesta; "
                    "revisar lo propio con el mismo modelo no agrega informacion",
        "prefiere": ("gpt-oss-20b", "qwythos-9b"),
        "combo_flota": "pensar",
        "rol_summoner": "cerebro",
        "pide": "un veredicto (SIRVE / NO SIRVE / SIRVE CON CAMBIOS) y como "
                "mucho 3 problemas concretos, el mas grave primero",
        "max_palabras": 200,
    },
    "rapido": {
        "para": "todo lo demas: una duda corta que no justifica despertar al grande",
        "criterio": "el modelo CHICO ya servido; si no hay nada mejor a mano, "
                    "responde el mismo cerebro del lazo",
        "prefiere": ("qwen3-4b", "qwythos-9b"),
        "combo_flota": "unico",
        "rol_summoner": "worker",
        "pide": "una respuesta directa de pocas lineas",
        "max_palabras": 120,
    },
}

ROL_DEFECTO = "rapido"

# Anti-abuso. 3 y no 10: la consulta al grande cuesta segundos de GPU y un
# turno del lazo; si el agente necesita mas de 3 empujones, el problema es la
# TAREA, no la falta de oraculo (mismo criterio que el max_reflections=3 de
# Aider que ya cita CLAUDE.md).
MAX_CONSULTAS = 3

# Topes de caracteres del prompt que se le manda al oraculo. El contexto se
# recorta por el MEDIO: la cabeza dice que se intento al principio y la cola
# tiene el error mas reciente; lo que sobra siempre esta en el medio.
MAX_CONTEXTO_CHARS = 4000
MAX_PREGUNTA_CHARS = 1200
MAX_ERROR_CHARS = 400

TIMEOUT_DEF = 180

# Colchon sobre el timeout antes de que el watchdog se rinda: se le da al
# transporte la chance de respetar SU propio timeout y devolver un error mejor
# que el nuestro ("HTTP 503" es mas util que "no respondio").
_MARGEN_TIMEOUT_S = 1.0

# ── deteccion de fallo REAL en el texto (evidencia, no lexico) ──────────
# Firma de un traceback/pytest de verdad: el modelo no escribe esto, lo escribe
# la maquina. Por eso manda sobre cualquier pista lexica en elegir_rol.
_RE_ERROR = re.compile(
    r"^(?:"
    r"\s*E\s{2,}.+"                              # linea 'E   ...' de pytest
    r"|\s*[A-Za-z_][\w.]*(?:Error|Exception)\b.*"  # ValueError: ..., MiException
    r"|FAILED\s+.+"                              # resumen de pytest
    # harness/verificacion.py emite 'ERROR: ...', 'ERROR linea 12: ...' y
    # tambien 'ERROR linea 12 col 3: ...' (rama JSON); las tres formas cuentan.
    r"|ERROR(?:\s+linea\s+\d+(?:\s+col\s+\d+)?)?:.*"
    r")$", re.M)

# OJO con el conteo de pytest: '0 failed' es una tanda VERDE. Sin el lookahead,
# un log limpio ('12 passed, 0 failed') se leia como evidencia de fallo y
# mandaba a 'codigo' una pregunta de revision o de diseno.
_RE_TRACEBACK = re.compile(
    r"Traceback \(most recent call last\)|\b(?!0+\b)\d+ failed\b", re.I)


def _texto(valor) -> str:
    """Todo lo que entra al modulo se trata como texto o no entra. El agente
    manda strings, pero el integrador manda lo que tenga a mano; un `str()` aca
    vale mas que un TypeError que se lleva el turno del lazo."""
    if isinstance(valor, str):
        return valor
    return "" if valor is None else str(valor)


def _sin_acentos(texto: str) -> str:
    """Minusculas sin tildes: asi el lexico de abajo se escribe UNA vez en ASCII
    y 'diseño'/'diseno'/'DISEÑO' entran todos por la misma puerta."""
    plano = unicodedata.normalize("NFD", _texto(texto))
    return "".join(c for c in plano if not unicodedata.combining(c)).lower()


# Lexico de cada regla, en ASCII sin tildes (ver _sin_acentos). Son PISTAS
# escritas por el modelo o por el usuario; se leen en el orden de la cascada de
# elegir_rol y cada lista se puede leer en voz alta, que es el punto.
_LEX_ERROR = (
    "error", "traceback", "excepcion", "falla", "fallo", "fallan", "bug",
    "no compila", "no anda", "no funciona", "rompe", "stack trace", "crashea",
    "se cuelga", "no pasa el test", "test rojo", "peta",
)
_LEX_REVISAR = (
    "revisa", "revisar", "revision", "esta bien", "esta correcto", "te parece",
    "que opinas", "critica", "code review", "auditar", "auditame", "mejorarias",
    "que le ves", "tiene sentido",
)
_LEX_PENSAR = (
    "diseno", "disenar", "arquitectura", "enfoque", "estrategia", "como encaro",
    "por donde empiezo", "por donde arranco", "trade-off", "tradeoff",
    "vale la pena", "conviene", "atascado", "estancado", "no se por donde",
    "plan de ataque", "refactor", "como estructuro", "que approach",
)


def error_exacto(texto: str) -> str:
    """La ULTIMA linea de error real del texto, o "" si no hay ninguna.

    Se devuelve la ultima y no la primera porque en un traceback la linea que
    nombra la excepcion va al final, y en una tanda de pytest el fallo vigente
    es el ultimo. Recortada a MAX_ERROR_CHARS: lo que importa es el tipo y el
    mensaje, no el repr de un dict de 20 KB."""
    texto = _texto(texto)
    if not texto:
        return ""
    hallados = _RE_ERROR.findall(texto)
    if not hallados:
        return ""
    linea = " ".join((hallados[-1] or "").split())
    return linea[:MAX_ERROR_CHARS]


def hay_fallo(texto: str) -> bool:
    """¿El texto trae evidencia DURA de un fallo (traceback, pytest, excepcion)?"""
    texto = _texto(texto)
    if not texto:
        return False
    return bool(_RE_TRACEBACK.search(texto)) or bool(_RE_ERROR.search(texto))


def _tiene(plano: str, lexico) -> bool:
    return any(p in plano for p in lexico)


def elegir_rol(pregunta: str, contexto: str = "") -> str:
    """A QUIEN preguntar. Cascada de reglas explicitas, en este orden:

    R1. Hay evidencia DURA de fallo (traceback / 'N failed' / 'ValueError: ...')
        en la pregunta o en el contexto -> 'codigo'. Va primero porque esa
        evidencia la escribe la MAQUINA; el lexico lo escribe el modelo, que es
        justamente el que esta confundido.
    R2. Lexico de error en la pregunta ('el test falla', 'no compila') -> 'codigo'.
    R3. Lexico de revision ('revisa', 'esta bien', 'que opinas') -> 'revisar'.
        Va antes que R4 porque 'revisa este diseno' es una REVISION de algo ya
        hecho, no la eleccion de un enfoque.
    R4. Lexico de diseno/arquitectura/desatasco -> 'pensar'.
    R5. Cualquier otra cosa -> 'rapido' (el default barato: la duda corta no
        justifica despertar al grande).

    Solo la R1 mira el contexto; las demas leen la PREGUNTA, que es donde el
    agente declara su intencion. Devuelve siempre una clave de ROLES.
    """
    p_plano = _sin_acentos(pregunta)
    if hay_fallo(pregunta) or hay_fallo(contexto):
        return "codigo"
    if _tiene(p_plano, _LEX_ERROR):
        return "codigo"
    if _tiene(p_plano, _LEX_REVISAR):
        return "revisar"
    if _tiene(p_plano, _LEX_PENSAR):
        return "pensar"
    return ROL_DEFECTO


def _recortar_medio(texto: str, tope: int) -> str:
    """Recorta por el MEDIO dejando 1/3 de cabeza y 2/3 de cola, con la marca
    de cuanto se tiro. La cola pesa mas porque ahi esta lo ULTIMO que se
    intento y el error; la cabeza sirve para no perder de que iba todo.

    Con tope <= 0 no entra NADA: devuelve "". Que un tope de 0 significara "no
    recortes" era la trampa al reves — `armar_consulta(max_contexto=0)` mandaba
    el log entero al oraculo justo cuando se le pedia que no mandara nada."""
    texto = _texto(texto)
    if tope <= 0:
        return ""
    if len(texto) <= tope:
        return texto
    tirados = len(texto) - tope
    marca = f"\n...[recortado el medio: {tirados} de {len(texto)} chars]...\n"
    util = tope - len(marca)
    if util <= 0:                      # tope absurdamente chico: cola pelada
        return texto[-tope:]
    cab = util // 3
    cola = util - cab
    return texto[:cab] + marca + texto[-cola:]


def armar_consulta(pregunta: str, contexto: str = "", rol: str = "",
                   max_contexto: int = MAX_CONTEXTO_CHARS) -> str:
    """El prompt que ve el oraculo. Lleva SIEMPRE las tres cosas sin las que la
    respuesta es un consejo generico de internet:

      1. QUE SE INTENTO YA (el contexto recortado por el medio) — sin esto el
         oraculo propone lo mismo que ya fallo dos veces.
      2. EL ERROR EXACTO si lo hay, extraido y puesto aparte — enterrado en 4000
         chars de log no lo lee ni el grande.
      3. QUE TIENE QUE DEVOLVER: el `pide` del rol, un plan corto. Explicito y
         acotado en palabras, porque un oraculo que devuelve el fichero entero
         convierte la consulta en un segundo agente y arruina el ahorro.

    `rol` desconocido o vacio -> se elige con `elegir_rol`.
    """
    rol = rol if rol in ROLES else elegir_rol(pregunta, contexto)
    spec = ROLES[rol]
    crudo = _texto(contexto).strip()
    preg = _recortar_medio(_texto(pregunta).strip(), MAX_PREGUNTA_CHARS)
    ctx = _recortar_medio(crudo, max_contexto)
    err = error_exacto(contexto) or error_exacto(pregunta)
    # Habia contexto y el tope se lo comio entero: decirlo. "(nada todavia: es
    # el primer intento)" ahi seria mentirle al oraculo sobre lo que se probo.
    sin_ctx = ("(contexto omitido: no entra en el tope de caracteres)"
               if crudo else "(nada todavia: es el primer intento)")

    partes = [
        f"Sos el ORACULO en rol '{rol}' ({spec['para']}).",
        "Te consulta un agente mas chico que esta trabajando en una tarea real "
        "y sigue el con el trabajo despues de tu respuesta.",
        "",
        f"PREGUNTA: {preg}" if preg else "PREGUNTA: (vacia)",
        "",
        "LO QUE YA SE INTENTO:",
        ctx if ctx else sin_ctx,
    ]
    if err:
        partes += ["", "ERROR EXACTO:", err]
    partes += [
        "",
        "QUE TENES QUE DEVOLVER:",
        f"- {spec['pide']}.",
        f"- Como mucho {spec['max_palabras']} palabras. Nada de preambulos.",
        "- NO devuelvas el fichero entero ni la solucion completa en codigo: "
        "el agente tiene el fichero delante y escribe el el codigo. Como mucho "
        "una linea suelta para desambiguar.",
        "- Si te falta un dato para responder, decilo en una linea y decidme "
        "que mirar, en vez de inventarlo.",
    ]
    return "\n".join(partes)


# ── estado por TAREA: tope de consultas + cache de de-duplicacion ───────
def nuevo_registro() -> dict:
    """Registro limpio (una TAREA). {'consultas': int, 'cache': {hash: dict}}."""
    return {"consultas": 0, "cache": {}}


_REGISTRO = nuevo_registro()


def reiniciar(registro: dict = None) -> dict:
    """Arranca una tarea nueva: tope a cero y cache vacia. Sin esto, el tope de
    3 se agotaria a mitad de la sesion y las consultas de la tarea 2 comerian
    respuestas cacheadas de la tarea 1."""
    reg = _REGISTRO if registro is None else registro
    reg["consultas"] = 0
    reg["cache"] = {}
    return reg


def estado(registro: dict = None, max_consultas: int = MAX_CONSULTAS) -> dict:
    """Cuanto queda de presupuesto, para que el integrador lo muestre.

    `max_consultas` tiene que ser el MISMO que se le pasa a `consultar`: con el
    tope hardcodeado, un integrador que corre con max_consultas=1 veia
    'restantes: 2' despues de haberse quedado sin presupuesto."""
    reg = _REGISTRO if registro is None else registro
    hechas = int(reg.get("consultas", 0))
    return {"consultas": hechas,
            "restantes": max(0, int(max_consultas) - hechas),
            "cacheadas": len(reg.get("cache", {}))}


def _huella(pregunta: str) -> str:
    """Hash de la pregunta NORMALIZADA: minusculas sin tildes, espacios
    colapsados y sin puntuacion de los bordes. Asi '¿Como lo hago?' y 'como lo
    hago' son la MISMA pregunta — que es como el modelo repregunta cuando no le
    gusto la respuesta."""
    plano = " ".join(_sin_acentos(pregunta or "").split())
    plano = plano.strip(" ?!.,;:¿¡-—\"'()[]")
    return hashlib.sha1(plano.encode("utf-8", "replace")).hexdigest()[:16]


def _segundos(timeout, defecto: float = TIMEOUT_DEF) -> float:
    """Un timeout no numerico (None, "60", un objeto) cae al defecto en vez de
    reventar. `timeout=None` como 'sin limite' es lo primero que escribe un
    integrador, y ahi el float() explotaba DESPUES de arrancar el hilo: se
    perdia el turno con la consulta ya contada."""
    try:
        seg = float(timeout)
    except (TypeError, ValueError):
        return float(defecto)
    if seg != seg or seg in (float("inf"), float("-inf")):   # NaN / infinitos
        return float(defecto)
    return max(0.0, seg)


def _llamar_con_tope(transporte, prompt: str, rol: str, timeout: float) -> tuple:
    """Llama al transporte con un tope de reloj PROPIO. Devuelve
    (texto, error). El hilo es daemon: si el transporte se cuelga, el agente
    sigue igual (no se puede matar un hilo en Python — se declara en el error)."""
    timeout = _segundos(timeout)
    caja = {}

    def _correr():
        try:
            caja["texto"] = transporte(prompt, rol, timeout)
        except BaseException as e:                      # noqa: BLE001
            # El error REAL, con su tipo: 'URLError: [Errno 111] refused' le
            # dice al integrador que el puerto esta cerrado; 'fallo la
            # consulta' no le dice nada a nadie.
            caja["error"] = f"{type(e).__name__}: {e}"

    h = threading.Thread(target=_correr, daemon=True,
                         name="oraculo-transporte")
    h.start()
    h.join(timeout + _MARGEN_TIMEOUT_S)
    if h.is_alive():
        return "", (f"el oraculo no respondio en {timeout:.0f}s (el transporte "
                    f"sigue corriendo en segundo plano; segui sin oraculo)")
    if "error" in caja:
        return "", caja["error"]
    return caja.get("texto"), ""


def consultar(pregunta: str, contexto: str = "", transporte=None,
              rol: str = "", timeout: float = TIMEOUT_DEF,
              registro: dict = None, max_consultas: int = MAX_CONSULTAS) -> dict:
    """Consulta explicita al oraculo. Devuelve SIEMPRE un dict plano y NUNCA
    lanza (un harness que revienta es peor que uno que no corre):

        {rol, respuesta, ok, error, segundos, cacheada, restantes}

    `transporte` es ``(prompt, rol, timeout) -> texto``, lo inyecta el
    integrador (el que habla con la flota). Este modulo no sabe de puertos.

    ok=False sale con `error` REAL y `respuesta` vacia en los seis casos que
    pueden pasar de verdad: sin transporte, tope agotado, transporte que
    revienta, transporte que se cuelga, transporte que devuelve algo que no es
    texto, y respuesta VACIA (el vacio silencioso es el fallo tipico de este
    repo: se declara, no se disfraza de exito).
    """
    reg = _REGISTRO if registro is None else registro
    reg.setdefault("consultas", 0)
    reg.setdefault("cache", {})
    pregunta, contexto = _texto(pregunta), _texto(contexto)
    rol = rol if rol in ROLES else elegir_rol(pregunta, contexto)
    t0 = time.time()

    def _res(ok, respuesta, error, cacheada=False):
        return {"rol": rol, "respuesta": respuesta or "", "ok": bool(ok),
                "error": error or "", "segundos": round(time.time() - t0, 2),
                "cacheada": bool(cacheada),
                "restantes": max(0, max_consultas - int(reg["consultas"]))}

    if not pregunta.strip():
        return _res(False, "", "pregunta vacia: no hay nada que consultar")

    # De-duplicacion ANTES del tope: repreguntar lo mismo no gasta presupuesto,
    # pero tampoco vuelve a molestar al grande.
    huella = _huella(pregunta)
    guardada = reg["cache"].get(huella)
    if guardada:
        aviso = ("[oraculo] esta pregunta ya se hizo en esta tarea: respuesta "
                 f"CACHEADA (rol={guardada['rol']}), no se gasto una consulta. "
                 "Si no te alcanzo, cambia la PREGUNTA (mas datos, otro angulo) "
                 "en vez de repetirla.")
        rol = guardada["rol"]
        return _res(True, aviso + "\n" + guardada["respuesta"], "", cacheada=True)

    if transporte is None:
        return _res(False, "", "no hay transporte de oraculo cableado en esta "
                              "sesion: resolvelo vos con las herramientas que tenes")

    if int(reg["consultas"]) >= max_consultas:
        return _res(False, "", f"tope de consultas al oraculo alcanzado "
                              f"({max_consultas} en esta tarea): a partir de "
                              f"aca resolvelo vos y decilo si no podes")

    prompt = armar_consulta(pregunta, contexto, rol)
    reg["consultas"] = int(reg["consultas"]) + 1      # cuenta el INTENTO, no el exito
    texto, error = _llamar_con_tope(transporte, prompt, rol, timeout)
    if error:
        return _res(False, "", error)
    if texto is not None and not isinstance(texto, str):
        # El transporte se quedo con el JSON crudo. Antes esto era un
        # AttributeError que se llevaba el turno del lazo; ahora se declara con
        # el tipo, que es lo unico que el integrador necesita para arreglarlo.
        return _res(False, "", f"el transporte devolvio {type(texto).__name__} "
                               f"y no texto: tiene que ser (prompt, rol, "
                               f"timeout) -> str (extrae vos el campo de texto)")
    if not (texto or "").strip():
        return _res(False, "", "el oraculo devolvio una respuesta VACIA "
                              "(transporte vivo, contenido nulo)")

    respuesta = texto.strip()
    reg["cache"][huella] = {"rol": rol, "respuesta": respuesta}
    return _res(True, respuesta, "")


def texto_resultado(res: dict) -> str:
    """El bloque RESULTADO que se le devuelve al modelo, en el formato de las
    tools del lazo. El fallo TAMBIEN se le cuenta, con su causa: el agente tiene
    que saber que se quedo sin oraculo para seguir por su cuenta."""
    rol = res.get("rol", "?")
    seg = res.get("segundos", 0)
    if res.get("ok"):
        marca = "CACHE" if res.get("cacheada") else f"{seg}s"
        return (f"RESULTADO consultar_oraculo [rol={rol}, {marca}, "
                f"quedan {res.get('restantes', 0)}]\n{res.get('respuesta', '')}")
    return (f"RESULTADO consultar_oraculo ERROR [rol={rol}, {seg}s]: "
            f"{res.get('error', 'desconocido')}\n"
            "SEGUI SIN ORACULO: no repitas la consulta, usa las herramientas "
            "que tenes y si no podes, decilo.")


# ── registro como herramienta del agente ───────────────────────────────
# Listo para registrar, NO registrado: el catalogo por defecto son 12 tools
# (CORE_TOOLS) por el A/B de 2026-07-25 y meter una 13a exige justificar su
# sitio con su propia medicion. Este modulo no importa ni toca agent/tools.py.
NOMBRE_TOOL = "consultar_oraculo"

DOC_TOOL = ("consultar_oraculo <pregunta> [| <contexto>]  -- preguntarle a un "
            "modelo mas capaz cuando estas atascado (maximo 3 por tarea)")

DESC_TOOL = (
    "Le hace UNA pregunta a un modelo mas capaz que vos y te devuelve su "
    "respuesta como texto. Usala en los tres momentos que lo valen: (1) antes "
    "de empezar, para decidir el ENFOQUE de una tarea que no tenes clara; "
    "(2) cuando el MISMO error te gano dos intentos seguidos; (3) para que "
    "REVISE un diseno o un parche antes de darlo por bueno. No la uses para "
    "cosas que podes mirar vos con leer_archivo, buscar o tests: el oraculo NO "
    "ve tus ficheros, solo lee lo que le pases. Te contesta un PLAN corto, no "
    "el codigo: el codigo lo escribis vos. Tenes 3 consultas por tarea y "
    "repetir la misma pregunta te devuelve la respuesta anterior."
)

PARAMS_TOOL = [
    {"nombre": "pregunta", "tipo": "string", "requerido": True,
     "descripcion": "la pregunta concreta, en una o dos frases (que decision "
                    "tenes que tomar o que error te frena)"},
    {"nombre": "contexto", "tipo": "string", "requerido": False,
     "descripcion": "que intentaste ya y el error exacto que te dio (pegalo "
                    "tal cual: sin esto el oraculo repite lo que ya fallo)"},
    {"nombre": "rol", "tipo": "string", "requerido": False, "clave": True,
     "descripcion": "a quien preguntarle: pensar | codigo | revisar | rapido "
                    "(si no lo pones se elige solo por lo que preguntes)"},
]


def spec_tool() -> dict:
    """La herramienta en la forma que consume `agent/tools.catalogo_schemas()`
    ({nombre, descripcion, params, danger}), para que el integrador la registre
    sin copiar textos a mano. `danger` es False: consultar no toca disco ni
    ejecuta nada, solo gasta tiempo de GPU (y eso ya lo acota MAX_CONSULTAS)."""
    return {"nombre": NOMBRE_TOOL, "descripcion": DESC_TOOL,
            "params": [dict(p) for p in PARAMS_TOOL], "danger": False,
            "doc": DOC_TOOL}
