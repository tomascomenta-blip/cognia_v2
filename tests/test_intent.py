"""
Tests for auto-routing intent detection (cognia/agent/intent.py).

Pins precision (chat must NOT be routed to the agent) and that clear actions are
detected with a sensible tool hint -- so natural language triggers tools without
a command.
"""

import pytest

from cognia.agent.intent import detect


@pytest.mark.parametrize("text,tool", [
    ("leé el archivo config.py", "leer_archivo"),
    ("que contiene el archivo main.py", "leer_archivo"),
    ("creá un archivo hola.py", "escribir_archivo"),
    ("escribí una funcion que sume", "escribir_archivo"),
    ("buscá TODO en el repo", "buscar"),
    ("listá los archivos de la carpeta", "listar"),
    ("cuánto es 25 * 13", "calcular"),
    ("resumí este texto", "resumir"),
    ("descargá de https://example.com", "http_get"),
    ("qué recordás sobre el parser", "recordar"),
])
def test_actions_route_to_agent_with_tool(text, tool):
    r = detect(text)
    assert r.needs_agent
    assert r.suggested_tool == tool


@pytest.mark.parametrize("text", [
    "hola, como estas?",
    "que es la fotosintesis",
    "explicame los embeddings",
    "por que el cielo es azul",
    "me gusta el color azul",
    "cual es la capital de Francia",
    "gracias por todo",
])
def test_chat_is_not_routed(text):
    assert not detect(text).needs_agent


def test_imperative_verb_fallback_without_specific_tool():
    r = detect("refactorizá este modulo entero")
    assert r.needs_agent
    assert r.suggested_tool == ""  # action, but let the agent pick the tool


def test_polite_filler_is_stripped():
    assert detect("por favor creá un script de prueba").needs_agent


def test_empty_is_chat():
    assert not detect("").needs_agent
    assert not detect("   ").needs_agent


def test_chat_guard_beats_a_noun_that_looks_actiony():
    # "que es" is a question, even though it contains an actiony word later.
    assert not detect("que es crear un indice invertido").needs_agent


# ── deseo/subjuntivo (reporte del dueño 2026-07-21) ─────────────────────
# "quiero que me abras una pestaña en YouTube" caia al chat y el modelo solo
# daba el comando en texto en vez de ABRIR la pestaña.

def test_deseo_subjuntivo_abre_pestana():
    r = detect("quiero que me abras una pestaña en YouTube de Google Chrome")
    assert r.needs_agent and r.suggested_tool == "abrir"


def test_deseo_subjuntivo_haz_pagina():
    r = detect("Quiero que me hagas una página web de un dashboard detallado")
    assert r.needs_agent


def test_cortesia_podrias_abrirme():
    r = detect("podrias abrirme powershell")
    assert r.needs_agent and r.suggested_tool == "abrir"


def test_clitico_abreme():
    assert detect("ábreme spotify").needs_agent


def test_deseo_NO_accion_sigue_en_chat():
    # "quiero que sepas / quiero aprender" no son ordenes de accion
    assert not detect("quiero que sepas que me gusta el proyecto").needs_agent
    assert not detect("quiero aprender python").needs_agent


# ── Regresion 2026-07-25 (sesion real del dueno) ──────────────────────────
# "Hola podrias crear una carpeta que se llame..." casaba el guard de "hola"
# -> reason="conversacional" -> ni agente ni enrutador (cli.py veta el
# enrutador con ese reason) -> el chat respondio "```mkdir nueva_carpeta```
# la carpeta ha sido creada" SIN crear nada, y lo repitio al reclamarle.

def test_saludo_no_anula_la_peticion():
    r = detect("Hola podrías crear una carpeta que se llame pruebas")
    assert r.needs_agent, "la cortesia no puede desactivar la ejecucion"
    assert r.reason != "conversacional"


def test_saludo_solo_sigue_siendo_chat():
    for saludo in ("hola", "buenas", "buenas noches", "hey", "qué tal"):
        assert not detect(saludo).needs_agent, saludo


def test_saludo_mas_pregunta_sigue_siendo_chat():
    assert not detect("Hola, ¿cómo estás?").needs_agent
    assert not detect("hola que es un transformer").needs_agent


def test_crear_carpeta_es_accion():
    # no existe tool de carpetas: se hace con `ejecutar` (mkdir)
    r = detect("crea una carpeta llamada pruebas")
    assert r.needs_agent and r.suggested_tool == "ejecutar"
    assert detect("hazme un directorio para los logs").needs_agent


def test_traer_ventana_al_frente_es_accion(monkeypatch):
    # La sugerencia de una pantalla_* va CONDICIONADA a COGNIA_SCREEN: sin el
    # flag esas tools ni se registran, y sugerirlas hacia que el agente pidiera
    # una tool ausente ("herramienta no existe"). Sigue siendo una accion.
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    r = detect("Puedes poner al frente la pestaña de Chrome "
               "es que está detrás de otras ventanas")
    assert r.needs_agent and r.suggested_tool == "pantalla_activar_ventana"


# ── Regresion 2026-07-25 (sesion 20260725-112753) ─────────────────────────
# "Me envias la foto" fue al CHAT y el modelo contesto "Aqui tienes la foto"
# sin foto, teniendo la captura ya tomada en disco.

def test_pedir_la_foto_es_entrega_no_charla(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    for m in ("Me envías la foto", "mándame la captura",
              "pasame el pantallazo", "muéstrame la imagen",
              "mostrame la foto"):
        r = detect(m)
        assert r.needs_agent, m
        assert r.suggested_tool == "pantalla_captura", m


def test_pedir_la_foto_sin_flag_sigue_siendo_accion(monkeypatch):
    """Sin COGNIA_SCREEN la peticion NO se degrada a chat (eso reintroduciria
    la regresion de 2026-07-25): sigue siendo accion, pero sin sugerir una
    tool que el catalogo no tiene, y con un aviso que dice como habilitarla."""
    monkeypatch.delenv("COGNIA_SCREEN", raising=False)
    r = detect("mándame la captura")
    assert r.needs_agent
    assert r.suggested_tool == ""
    assert "COGNIA_SCREEN=1" in r.aviso


def test_hablar_de_fotos_no_dispara_el_agente():
    assert not detect("gracias por la foto").needs_agent
    assert not detect("que es una foto sintetica").needs_agent


# ── Guards ENSANCHADOS y su CONTRA-REGLA (PLAN2, PEDIDO 2, escalon 2) ──────
# MEDIDO contra el backend real (dossier f2_enrutador-chat-agente): de los 10
# mensajes del dueno, DOS pagan el modelo para confirmar un chat que esta capa
# ya creia — "cuentame un chiste" (1.854 ms) y "que opinas de X" (2.954 ms).
# Son dos fugas concretas: existia "contame" pero no "cuentame", y "opinas"
# solo casaba ANCLADO al inicio del mensaje.

@pytest.mark.parametrize("text", [
    "cuentame un chiste",
    "cuéntame algo interesante",
    "que opinas de la inteligencia artificial",
    "y tu que piensas de eso",
    "te parece bien esa idea",
    "cual es tu opinion sobre el tema",
])
def test_guards_ensanchados_resuelven_la_charla_en_0ms(text):
    r = detect(text)
    assert not r.needs_agent, text
    # "conversacional" es lo que ADEMAS veta el enrutador: es la unica razon
    # que ahorra de verdad la llamada al modelo.
    assert r.reason == "conversacional", text


@pytest.mark.parametrize("text", [
    "cuentame que archivos hay en mi escritorio",
    "cuentame que hay en la carpeta descargas",
    "cuentame el contenido de notas.txt",
    "que opinas de C:/Users/usuario/Desktop/informe.md",
    "cuentame cuantos ficheros tengo en el escritorio",
    "que piensas, borra los logs viejos",
])
def test_contra_regla_los_guards_no_vetan_el_trabajo(text):
    """LA CONTRA-REGLA, que es la parte cara del cambio: un `conversacional`
    falso no solo manda el turno al chat, ademas VETA EL ENRUTADOR ENTERO
    (cli.py exige reason != "conversacional" para preguntarle al modelo), o
    sea deja la accion sin agente Y sin rescate. Con una extension, una ruta,
    un verbo de accion o un objeto del sistema, el guard ensanchado no
    dispara."""
    assert detect(text).reason != "conversacional", text


def test_caso_adversario_cuentame_que_archivos_hay():
    """El caso adversario obligatorio del plan: empieza por la palabra que
    acabamos de meter en el guard y DEBE seguir siendo agente."""
    r = detect("cuentame que archivos hay en mi escritorio")
    assert r.needs_agent
    assert r.suggested_tool == "listar"


# ── CONTINUACION tras un turno de AGENTE (escalon 3) ──────────────────────
# "que entre rapido al agente si hace falta", literal del dueno: si el turno
# anterior activo el agente, un mensaje corto y deictico continua esa accion.

@pytest.mark.parametrize("text", [
    "y ahora borralo", "otra vez", "igual pero en descargas", "hazlo",
    "sigue", "lo mismo pero en el escritorio",
])
def test_continuacion_tras_agente_es_accion(text):
    r = detect(text, turno_previo_agente=True)
    assert r.needs_agent, text


def test_continuacion_exige_el_turno_previo_de_agente():
    """Es una regla CON CONTEXTO: sin el turno de agente detras, 'otra vez' o
    'sigue' son muletillas de charla y no pueden activar el agente solas."""
    assert not detect("otra vez").needs_agent
    assert not detect("sigue").needs_agent
    assert not detect("y ahora borralo").needs_agent


def test_continuacion_no_secuestra_un_mensaje_largo():
    """El tope de 6 palabras evita que cualquier frase con 'sigue' dentro se
    convierta en una orden por el mero hecho de venir tras el agente."""
    r = detect("sigue siendo raro que el color del boton no combine con nada",
               turno_previo_agente=True)
    assert not r.needs_agent


def test_continuacion_no_pisa_la_charla_de_cortesia():
    for m in ("gracias por todo", "como estas", "que tal"):
        assert not detect(m, turno_previo_agente=True).needs_agent, m


# ══ REGRESION: los guards ensanchados MATABAN acciones ════════════════════
# Revision adversarial 2026-08-29. El primer intento del escalon 2 corria un
# veto por PREFIJO ("^cuentame", "opinas" sin anclar) ANTES de _RULES, con una
# contra-regla que solo perdonaba extensiones, rutas, verbos u objetos del
# SISTEMA DE FICHEROS. Una accion cuyo objeto NO es un fichero (los tests, git,
# un calculo, un proceso) no la activaba y moria en "conversacional" -- que
# ademas VETA EL ENRUTADOR (cli.py:22654), o sea deja la accion sin agente Y
# sin rescate.
#
# POR QUE NO LO CAZARON LOS TESTS DE AQUEL DIA: los 8 casos adversarios de
# arriba llevan TODOS una extension o un objeto del sistema de ficheros, asi
# que TODOS disparan la contra-regla. Cero cobertura de una accion cuyo objeto
# no sea un fichero. Estos casos son exactamente esa cobertura: si alguien
# vuelve a poner los guards delante de _RULES, se ponen rojos.

ACCIONES_OBJETO_NO_FICHERO = [
    # (mensaje, tool que la regla tiene que reclamar)
    ("cuentame el resultado de correr los tests", "ejecutar"),
    ("cuentame que error da al ejecutar los tests", "ejecutar"),
    ("cuentame el resultado de ejecutar el script de migracion", "ejecutar"),
    ("que opinas de correr el benchmark ahora", "ejecutar"),
    ("cuentame cuanto es 2+2", "calcular"),
    ("cuentame cuanto es 25 * 13", "calcular"),
    ("cuentame lo que devuelve git status", "git_estado"),
    ("cuentame que devuelve git diff", "git_estado"),
    ("que opinas de resumir el libro", "resumir"),
]


@pytest.mark.parametrize("text,tool", ACCIONES_OBJETO_NO_FICHERO)
def test_regresion_una_accion_sin_fichero_sigue_siendo_accion(text, tool):
    """MEDIDO: estas 9 salian `regla:<tool>` antes del escalon 2 y
    `conversacional` despues. El objeto de la accion son los tests, git o un
    calculo, no un fichero, asi que la contra-regla no las salvaba."""
    r = detect(text)
    assert r.needs_agent, f"{text!r} -> {r.reason}"
    assert r.reason == f"regla:{tool}", f"{text!r} -> {r.reason}"


RESCATES_QUE_NO_SE_PUEDEN_VETAR = [
    # Ninguna regla determinista las reclama, pero TIENEN que llegar al modelo:
    # `conversacional` apagaria tambien el rescate del enrutador.
    "cuentame si el build paso",
    "cuentame el estado de git",
    "cuentame que dice el log",
    "cuentame el diff de git",
    "cuentame el resumen de la reunion",
    "cuentame que procesos estan consumiendo cpu",
    "cuentame que tal va el servidor web",
    "cuentame cuantos commits hice esta semana",
    "que opinas, mata el proceso de python que se colgo",
    "que piensas, borra los logs viejos del proyecto",
    "revisa el codigo y dime que opinas",
]


@pytest.mark.parametrize("text", RESCATES_QUE_NO_SE_PUEDEN_VETAR)
def test_regresion_el_rescate_del_enrutador_no_se_veta(text):
    """El fallo caro no es "se fue al chat": es `conversacional`, que apaga
    ADEMAS el enrutador. Un mensaje que ninguna regla reclama tiene que salir
    con reason="chat" para que el modelo pueda mirarlo."""
    assert detect(text).reason == "chat", text


def test_una_orden_escondida_tras_la_cortesia_no_se_veta():
    """La forma que mas duele: cortesia + coma + orden. El guard no dispara si
    hay separador de clausula, porque ahi es donde vive la segunda oracion."""
    for m in ("que opinas, mata el proceso de python que se colgo",
              "que piensas, borra los logs viejos del proyecto",
              "cuentame algo, y luego revisa los logs"):
        assert detect(m).reason != "conversacional", m


def test_la_opinion_solo_veta_cuando_LIDERA_el_mensaje():
    """Una pregunta de opinion abre con la opinion; una peticion con una
    coletilla ('...y dime que opinas') es una peticion."""
    assert detect("que opinas de la inteligencia artificial").reason == \
        "conversacional"
    assert detect("revisa el codigo y dime que opinas").reason != \
        "conversacional"


# ── LA FUGA DE COSTE DE LA CHARLA CORRIENTE (verificacion de cierre) ──────
# MEDIDO sobre 30 mensajes de charla corriente: 15 (el 50%) salian con
# reason="chat" y, con >=3 palabras, el REPL le preguntaba al modelo. Coste
# con el backend vivo: 784 ms, 801 ms y 3.019 ms ANTES de empezar a contestar
# "que tal estas". La ruta salia BIEN en los tres: fuga de COSTE, no de
# correccion. Estos 15 son los mensajes exactos que se midieron.

CHARLA_QUE_PAGABA_EL_MODELO = [
    "que tal estas",                        # saludo pelado
    "que tal tu dia",
    "jaja muy bueno",                       # risa
    "muchas gracias por todo",              # agradecimiento
    "eres muy util gracias",
    "me siento un poco cansado hoy",        # estado de animo
    "hablame de la segunda guerra mundial",  # tema de conversacion
    "dime algo bonito",
    "no entendi lo anterior",               # no-comprension
    "no se que hacer hoy",
    "de que hablabamos",                    # meta-conversacion
    "tienes razon en eso",                  # asentimiento
    "me encanta como explicas",
    "que raro no?",                         # exclamacion valorativa
    "sabes cocinar paella",                 # conocimiento general
]


@pytest.mark.parametrize("text", CHARLA_QUE_PAGABA_EL_MODELO)
def test_la_charla_corriente_ya_no_paga_el_modelo(text):
    """Los 15 medidos, uno a uno. "conversacional" es la unica razon que
    ahorra la llamada de verdad: es la que ademas veta el enrutador."""
    r = detect(text)
    assert not r.needs_agent, text
    assert r.reason == "conversacional", text


@pytest.mark.parametrize("text", [
    # el mismo arranque de cada familia nueva, pero con trabajo detras: la
    # contra-regla tiene que ganarle al guard en TODAS.
    "muchas gracias, ahora ejecuta el script de migracion",
    "jaja y ahora borra los logs viejos",
    "sabes si el build paso",
    "sabes cuantos commits hice esta semana",
    "hablame del error del servidor",
    "cuentame de git",
    "me gusta el resultado del benchmark",
    "que raro que no arranque el servidor",
    "que curioso el error del log",
    "no entiendo el traceback",
    "no se donde deje el informe",
    "dime algo del repositorio",
    "hola pon musica",
    "buenas necesito ayuda",
])
def test_las_familias_nuevas_no_se_comen_el_rescate(text):
    """La regresion cara, medida una vez y no dos: `conversacional` apaga el
    agente Y el enrutador. Cada familia nueva se prueba con su propio
    arranque MAS un objeto de trabajo o una segunda oracion detras.

    NO se prueba aqui "gracias, ahora corre los tests": ese sale
    `conversacional` desde mucho antes de esta obra, por el guard VIEJO
    `^(gracias|chau|adios|...)` de `_CHAT_GUARDS`, que se ancla al inicio y no
    tiene contra-regla. Se verifico contra `git show HEAD` y contra el estado
    previo: los tres dan `conversacional`. Es un agujero REAL y PREEXISTENTE,
    y arreglarlo obliga a tocar unos guards calibrados desde hace meses que
    corren ANTES de `_RULES`: no es un cambio de vispera de publicacion."""
    assert detect(text).reason != "conversacional", text


def test_el_objeto_de_TRABAJO_es_la_quinta_pata_de_la_contra_regla():
    """Las cuatro patas viejas (extension, ruta, verbo, objeto del sistema de
    ficheros) miran todas al disco: "cuentame el estado de git" no activaba
    ninguna. Se simulo la regla general contra el banco etiquetado ANTES de
    escribir nada y marcaba 'conversacional' 15 de los 42 casos, 11 de ellos
    `rescate`. Por eso hay una quinta pata y no una regla general."""
    from cognia.agent.intent import _veta_guard_ensanchado as veta
    for m in ("el estado de git", "si el build paso", "que dice el log",
              "que procesos consumen cpu", "que tal va el servidor",
              "cuantos commits hice", "el traceback de la excepcion"):
        assert veta(m), m
    # y no veta la charla que no habla de trabajo
    for m in ("cocinar paella", "la segunda guerra mundial", "algo bonito"):
        assert not veta(m), m


def test_el_saludo_pelado_es_un_ALLOWLIST_y_no_un_tope_de_palabras():
    """"que tal estas" queda en "estas" tras pelar el saludo, y ahi no hay
    nada que casar. Se cierra por el resto CONOCIDO de un saludo, no por ser
    corto: con un simple tope de dos palabras, "hola pon musica" se cerraria
    como charla y perderia el rescate del enrutador."""
    from cognia.agent.intent import guard_ensanchado_dispara as dispara
    assert dispara("estas", saludo_pelado=True)
    assert dispara("tu dia", saludo_pelado=True)
    assert dispara("va todo", saludo_pelado=True)
    assert not dispara("estas", saludo_pelado=False)   # sin saludo, no
    assert not dispara("pon musica", saludo_pelado=True)
    assert not dispara("necesito ayuda", saludo_pelado=True)
    assert not dispara("el build", saludo_pelado=True)  # objeto de trabajo


def test_el_guard_ensanchado_es_un_ALLOWLIST_no_una_lista_negra():
    """La carga de la prueba, invertida (leccion de la casa: un allowlist por
    prefijo no es frontera). Lo desconocido NO dispara: paga el modelo, que es
    el fallo barato. Se ejerce la funcion del escalon 2 directamente."""
    from cognia.agent.intent import guard_ensanchado_dispara as dispara
    assert dispara("cuentame un chiste")
    assert dispara("cuentame algo")
    assert dispara("cuentame una historia de miedo")
    # sustantivo que NO esta en la lista de charla -> no se cierra en 0 ms
    assert not dispara("cuentame un error del build")
    assert not dispara("cuentame el resultado de los tests")
    assert not dispara("cuentame cuantos commits hice")
    assert not dispara("")
