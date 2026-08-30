"""
El CAMINO DETERMINISTA del enrutador (PLAN2, PEDIDO 2) — agente D.

Por que este fichero existe, medido en el dossier f2_enrutador-chat-agente
contra el backend real: el enrutador ACIERTA 10/10 pero cobra 1.841-27.121 ms
por decision, con varianza de 3x sobre el MISMO mensaje, y 2 de cada 10
mensajes del dueno son PEAJE INUTIL (segundos de modelo para confirmar un chat
que la capa de reglas ya sabia).

La prueba de que el camino barato existe NO es leer el fuente: es que
`decidir()` resuelva sin TOCAR el modelo. Por eso el infer_fn de casi todos
los tests de aqui **levanta AssertionError si se la llama**: si el camino
determinista se rompe, el test no falla por una asercion cosmetica, falla
porque el enrutador fue a pedirle permiso al modelo.
"""
import time

import pytest

import cognia.backend_activo as backend_activo
import cognia.enrutador as enr
from cognia.enrutador import decidir


CATALOGO = "\n".join([
    "/pensar — Razonamiento PROFUNDO con modelo thinking <pregunta>",
    "/investigar — Investigar en GitHub <query>",
    "/crear — Crear programa ahora <idea>",
    "/stats — Estadisticas de la sesion",
])


def _no_llamar(prompt):
    raise AssertionError(
        "el enrutador pidio el MODELO para un caso que tenia que resolver "
        "en 0 ms (camino determinista roto)")


@pytest.fixture(autouse=True)
def _limpio(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_activo, "AUDIT", tmp_path / "audit.jsonl")
    enr.invalidar_cache()
    enr.reset_contadores()
    yield
    enr.invalidar_cache()
    enr.reset_contadores()


# ── 1. los que NO pagan modelo ────────────────────────────────────────────

CHAT_OBVIO = [
    "cuentame un chiste",                      # fuga medida: 1.854 ms de peaje
    "que opinas de la inteligencia artificial",  # fuga medida: 2.954 ms
    "que es un DAG",
    "como estas hoy",
    "explicame la diferencia entre un hilo y un proceso",
    "por que el cielo es azul",
]

ACCION_OBVIA = [
    "crea un juego de flappy bird",
    "abre chrome y busca gatos",
    "hazme un script que ordene mis descargas",
    "lee el archivo config.py",
]


@pytest.mark.parametrize("mensaje", CHAT_OBVIO)
def test_chat_obvio_no_toca_el_modelo(mensaje):
    assert decidir(mensaje, _no_llamar, CATALOGO) == ("chat", "")


@pytest.mark.parametrize("mensaje", ACCION_OBVIA)
def test_accion_obvia_no_toca_el_modelo(mensaje):
    assert decidir(mensaje, _no_llamar, CATALOGO) == ("agente", "")


def test_el_camino_determinista_es_de_milisegundos():
    """El objetivo del plan es p50 <= 5 ms por turno. Se MIDE, no se declara."""
    tiempos = []
    for mensaje in CHAT_OBVIO + ACCION_OBVIA:
        enr.invalidar_cache()          # el peor caso: sin cache
        t0 = time.perf_counter()
        decidir(mensaje, _no_llamar, CATALOGO)
        tiempos.append((time.perf_counter() - t0) * 1000.0)
    tiempos.sort()
    p50 = tiempos[len(tiempos) // 2]
    assert p50 <= 5.0, f"p50 del camino determinista = {p50:.3f} ms"
    assert enr.ultimo_enrutado()["via"] == "determinista"


# ── 2. la cache (escalon 4) ───────────────────────────────────────────────

def test_segunda_llamada_identica_es_cache_hit():
    """Mismo mensaje + mismo contexto = misma decision, sin volver al modelo."""
    llamadas = []

    def fake(prompt):
        llamadas.append(prompt)
        return "RUTA: AGENTE"

    # un mensaje que el camino determinista NO resuelve (es el rescate real
    # medido: intent lo cree chat y solo el modelo ve la accion)
    msg = "arregla el bug de la funcion de pago"
    assert decidir(msg, fake, CATALOGO) == ("agente", "")
    assert len(llamadas) == 1
    assert enr.contadores()["cache_hits"] == 0

    assert decidir(msg, fake, CATALOGO) == ("agente", "")
    assert len(llamadas) == 1, "la segunda llamada volvio a pagar el modelo"
    assert enr.contadores()["cache_hits"] == 1
    assert enr.ultimo_enrutado()["via"] == "cache"


def test_la_cache_distingue_el_contexto():
    """La clave lleva el contexto: el mismo mensaje en OTRA conversacion no
    puede reusar la decision vieja."""
    llamadas = []

    def fake(prompt):
        llamadas.append(prompt)
        return "RUTA: AGENTE"

    msg = "arregla el bug de la funcion de pago"
    decidir(msg, fake, CATALOGO, contexto="usuario: hola")
    decidir(msg, fake, CATALOGO, contexto="usuario: otra conversacion")
    assert len(llamadas) == 2


def test_la_cache_no_pasa_de_128():
    fake = lambda p: "RUTA: CHAT"
    for i in range(200):
        decidir(f"mensaje numero {i} sobre cosas", fake, CATALOGO)
    assert len(enr._cache_decisiones) == enr._CACHE_MAX == 128


def test_invalidar_cache_obliga_a_volver_a_decidir():
    llamadas = []

    def fake(prompt):
        llamadas.append(prompt)
        return "RUTA: CHAT"

    msg = "arregla el bug de la funcion de pago"
    decidir(msg, fake, CATALOGO)
    enr.invalidar_cache()
    decidir(msg, fake, CATALOGO)
    assert len(llamadas) == 2


# ── 3. el contexto de la conversacion (lo que el dueno pidio y no existia) ──

def test_el_prompt_lleva_el_bloque_de_contexto():
    visto = {}

    def fake(prompt):
        visto["p"] = prompt
        return "RUTA: CHAT"

    decidir("arregla eso de antes", fake, CATALOGO,
            contexto="usuario: borra los logs\ncognia: borrados 3 ficheros")
    assert "Ultimos turnos:" in visto["p"]
    assert "borra los logs" in visto["p"]
    assert "borrados 3 ficheros" in visto["p"]


def test_sin_contexto_no_se_cuela_el_encabezado():
    visto = {}

    def fake(prompt):
        visto["p"] = prompt
        return "RUTA: CHAT"

    decidir("arregla eso de antes", fake, CATALOGO)
    assert "Ultimos turnos:" not in visto["p"]


def test_el_contexto_respeta_el_tope_de_600():
    """El tope es PARTE del cambio: el prefill medido son 219 ms y tres turnos
    largos lo duplican."""
    visto = {}

    def fake(prompt):
        visto["p"] = prompt
        return "RUTA: CHAT"

    largo = "usuario: " + ("x" * 5000)
    decidir("arregla eso de antes", fake, CATALOGO, contexto=largo)
    bloque = visto["p"].split("Ultimos turnos:\n")[1].split("\n\nMensaje")[0]
    assert len(bloque) == 600, len(bloque)
    assert enr._CTX_TOPE == 600


def test_contexto_de_history_acota_turnos_y_chars():
    history = [
        {"role": "user", "content": "el primero, que no entra"},
        {"role": "assistant", "content": "A" * 900},
        {"role": "user", "content": "B" * 900},
    ]
    ctx = enr.contexto_de_history(history)
    assert "el primero" not in ctx          # solo los 2 ultimos turnos
    assert ctx.count("\n") == 1
    assert len(ctx) <= 600
    for linea in ctx.splitlines():
        assert len(linea) <= 200 + len("usuario: ")
    assert ctx.startswith("cognia: ")


def test_contexto_de_history_tolera_basura():
    assert enr.contexto_de_history(None) == ""
    assert enr.contexto_de_history([]) == ""
    assert enr.contexto_de_history(["no soy un dict", {"role": "user"}]) == ""


# ── 4. el caso ADVERSARIO de los guards ensanchados ───────────────────────

def test_cuentame_que_archivos_hay_sigue_siendo_agente():
    """LA CONTRA-REGLA. Ensanchar el veto conversacional es peligroso: un
    'conversacional' falso no manda el turno al chat y ya esta, ademas VETA el
    enrutador entero (el gate de cli.py lo exige), o sea deja la accion sin
    agente Y sin rescate. Este mensaje empieza por 'cuentame' — la palabra que
    acabamos de anadir al guard — y tiene que seguir yendo al AGENTE."""
    assert decidir("cuentame que archivos hay en mi escritorio",
                   _no_llamar, CATALOGO) == ("agente", "")


@pytest.mark.parametrize("mensaje", [
    "cuentame que hay en la carpeta descargas",
    "cuentame el contenido de notas.txt",
    "que opinas de C:/Users/usuario/Desktop/informe.md",
    "cuentame cuantos archivos tengo en el escritorio",
])
def test_los_guards_ensanchados_no_vetan_el_trabajo(mensaje):
    """Con extension, ruta, verbo u objeto del sistema el guard NO dispara:
    o se resuelve como agente, o se deja pasar al modelo — pero nunca se
    marca 'conversacional', que es lo que apagaria tambien el rescate."""
    from cognia.agent.intent import detect
    assert detect(mensaje).reason != "conversacional", mensaje


# ── 5. el presupuesto: el tope corto va ATADO al pensamiento apagado ──────

def test_tope_24_solo_con_el_pensamiento_apagado(monkeypatch):
    """La leccion de la casa: un tope corto con un razonador devuelve content
    VACIO, el enrutador lo lee como fallo y cae a chat EN SILENCIO. Si el
    perfil no sabe apagar el pensamiento, el tope se queda en 400."""
    monkeypatch.setattr(enr, "kwargs_sin_pensar",
                        lambda: {"kwargs_plantilla": {"enable_thinking": False}})
    extra, tope = enr.presupuesto_ruta()
    assert tope == 24 and extra["kwargs_plantilla"]["enable_thinking"] is False

    monkeypatch.setattr(enr, "kwargs_sin_pensar", lambda: {})
    extra, tope = enr.presupuesto_ruta()
    assert (extra, tope) == ({}, 400)


def test_kwargs_sin_pensar_pregunta_al_perfil(monkeypatch):
    """No se manda 'enable_thinking' a ciegas: la clave la dice el PERFIL del
    modelo servido (familias distintas usan claves distintas)."""
    import cognia.agent.flujo_ia as fia
    import cognia.agent.model_profiles as mp
    monkeypatch.setattr(fia, "_kwargs_sin_pensar", lambda: {})
    monkeypatch.setattr(mp, "perfil_del_agente",
                        lambda *a, **k: {"kwargs_plantilla":
                                         {"enable_thinking": True}})
    assert enr.kwargs_sin_pensar() == {
        "kwargs_plantilla": {"enable_thinking": False}}

    monkeypatch.setattr(mp, "perfil_del_agente", lambda *a, **k: {})
    assert enr.kwargs_sin_pensar() == {}


def test_inferir_ruta_pide_el_tope_corto_y_sin_pensar(monkeypatch):
    """El cableado de verdad: `decidir(..., infer_fn=None)` termina en
    chat_client.completar con max_tokens=24 y el pensamiento apagado."""
    import cognia.agent.chat_client as cc
    visto = {}

    class _Resp:
        error = ""
        texto = "RUTA: /stats"

    def fake_completar(mensajes, **kw):
        visto.update(kw)
        visto["mensajes"] = mensajes
        return _Resp()

    monkeypatch.setattr(cc, "completar", fake_completar)
    monkeypatch.setattr(enr, "kwargs_sin_pensar",
                        lambda: {"kwargs_plantilla": {"enable_thinking": False}})

    ruta, extra = decidir("arregla el bug de la funcion de pago", None,
                          CATALOGO)
    assert (ruta, extra) == ("comando", "/stats")
    assert visto["max_tokens"] == 24
    assert visto["kwargs_plantilla"] == {"enable_thinking": False}
    assert visto["via"] == "enrutador"
    assert "RUTA:" in visto["mensajes"][0]["content"]


def test_inferir_ruta_con_backend_caido_cae_a_chat(monkeypatch):
    import cognia.agent.chat_client as cc

    class _Resp:
        error = "connection refused"
        texto = ""

    monkeypatch.setattr(cc, "completar", lambda *a, **k: _Resp())
    assert decidir("arregla el bug de la funcion de pago", None,
                   CATALOGO) == ("chat", "")
    assert enr.contadores()["fallos"] == 1


# ── 6. contadores para /enrutador ─────────────────────────────────────────

def test_los_contadores_cuentan_lo_que_paso():
    decidir("cuentame un chiste", _no_llamar, CATALOGO)          # determinista
    decidir("crea un juego de flappy bird", _no_llamar, CATALOGO)  # determinista
    decidir("arregla el bug de la funcion de pago",
            lambda p: "RUTA: /stats", CATALOGO)                  # modelo
    decidir("cuentame un chiste", _no_llamar, CATALOGO)          # cache
    c = enr.contadores()
    assert c["chat"] == 2 and c["agente"] == 1 and c["comando"] == 1
    assert c["determinista"] == 2 and c["modelo"] == 1 and c["cache_hits"] == 1
    u = enr.ultimo_enrutado()
    assert u["via"] == "cache" and u["ruta"] == "chat" and u["ms"] >= 0.0


def test_reset_contadores_deja_todo_en_cero():
    decidir("cuentame un chiste", _no_llamar, CATALOGO)
    enr.reset_contadores()
    assert set(enr.contadores().values()) == {0}
    assert enr.ultimo_enrutado()["via"] == ""


# ── 7. la continuacion tras un turno de agente (escalon 3) ────────────────

@pytest.mark.parametrize("mensaje", [
    "y ahora borralo", "otra vez", "igual pero en descargas", "hazlo",
    "sigue",
])
def test_continuacion_tras_agente_no_toca_el_modelo(mensaje):
    assert decidir(mensaje, _no_llamar, CATALOGO,
                   turno_previo_agente=True) == ("agente", "")


def test_sin_turno_previo_de_agente_la_continuacion_no_dispara():
    """La regla es CON CONTEXTO: sin un turno de agente detras, 'otra vez' no
    es una orden, y el mensaje sigue su camino normal (aqui, el modelo)."""
    llamadas = []
    decidir("otra vez", lambda p: llamadas.append(p) or "RUTA: CHAT",
            CATALOGO)
    assert len(llamadas) == 1


# ══ REGRESION del escalon 2: el camino barato no puede COMERSE acciones ═══
# Revision adversarial 2026-08-29: los guards ensanchados corrian ANTES de
# _RULES y 9 acciones de una bateria de 42 acabaron en `conversacional`. Aqui
# se ejerce el efecto observable, no el fuente: la ruta que devuelve `decidir`
# y si el modelo llego a ser consultado.

ACCIONES_SIN_FICHERO = [
    "cuentame el resultado de correr los tests",
    "cuentame que error da al ejecutar los tests",
    "cuentame cuanto es 2+2",
    "cuentame lo que devuelve git status",
    "que opinas de correr el benchmark ahora",
]


@pytest.mark.parametrize("mensaje", ACCIONES_SIN_FICHERO)
def test_accion_con_objeto_no_fichero_va_al_agente_sin_modelo(mensaje):
    """Su objeto son los tests, git o un calculo -- no un fichero -- asi que
    la contra-regla de extension/ruta/objeto NO las cubre. Las cubre el ORDEN:
    _RULES corre antes que los guards."""
    assert decidir(mensaje, _no_llamar, CATALOGO) == ("agente", "")


RESCATES = [
    "cuentame si el build paso",
    "cuentame que procesos estan consumiendo cpu",
    "cuentame cuantos commits hice esta semana",
    "que opinas, mata el proceso de python que se colgo",
    "revisa el codigo y dime que opinas",
]


@pytest.mark.parametrize("mensaje", RESCATES)
def test_el_rescate_del_modelo_sigue_vivo(mensaje):
    """EL EFECTO OBSERVABLE del veto: cuando `intent` dice `conversacional`,
    cli.py ni siquiera llama al enrutador. Aqui se comprueba lo contrario --
    que el modelo SI es consultado -- contando llamadas a la infer_fn."""
    llamadas = []

    def fake(prompt):
        llamadas.append(prompt)
        return "RUTA: AGENTE"

    assert decidir(mensaje, fake, CATALOGO) == ("agente", "")
    assert len(llamadas) == 1, (
        f"{mensaje!r} no llego al modelo: el camino barato lo cerro solo")
    from cognia.agent.intent import detect
    assert detect(mensaje).reason != "conversacional", mensaje


# ══ ESCALON 3: el cableado que le falta al CLI, ejercido ══════════════════
# `turno_previo_agente` esta implementado y NO cableado: `cli.py` no lo pasa
# (revision adversarial 2026-08-29), asi que hoy el escalon 3 es codigo muerto
# en produccion. El contrato de lo que falta esta en el docstring de
# `intent.detect`; este test lo EJERCE simulando el bucle del REPL con la
# variable que ahi se nombra, para que el dia que el agente A la cablee ya
# haya una prueba de que hace lo que promete.

def _repl_simulado(mensajes, infer_fn, *, cableado: bool):
    """El bucle del REPL, recortado a lo que decide la ruta.

    `cableado=True` es lo que falta en cli.py: `_ultimo_turno_agente` nace
    False, pasa a True tras `_run_agent_task`, vuelve a False en el turno de
    chat, y alimenta `_detect_intent(...)`.
    """
    from cognia.agent.intent import detect
    _ultimo_turno_agente = False
    rutas = []
    for raw in mensajes:
        it = detect(raw, turno_previo_agente=(_ultimo_turno_agente
                                              if cableado else False))
        if it.needs_agent:
            ruta = "agente"
        elif it.reason == "conversacional" or len(raw.split()) < 3:
            ruta = "chat"
        else:
            ruta, _ = decidir(raw, infer_fn, CATALOGO)
        rutas.append(ruta)
        _ultimo_turno_agente = (ruta == "agente")
    return rutas


def test_escalon3_cableado_encadena_la_continuacion_sin_modelo():
    """El caso del dueno: crea un fichero (agente) y dice 'y ahora borralo'.
    Con el cableado, el segundo turno tambien es AGENTE y sin tocar el modelo.
    """
    rutas = _repl_simulado(
        ["crea un fichero prueba.txt en el escritorio", "y ahora borralo"],
        _no_llamar, cableado=True)
    assert rutas == ["agente", "agente"]


def test_escalon3_SIN_cablear_pierde_la_continuacion():
    """Y este es el estado de HOY, que es por lo que hay que cablearlo: con la
    flota apagada (infer_fn devuelve "") el segundo turno cae a CHAT y no se
    borra nada."""
    rutas = _repl_simulado(
        ["crea un fichero prueba.txt en el escritorio", "y ahora borralo"],
        lambda p: "", cableado=False)
    assert rutas == ["agente", "chat"]


def test_escalon3_no_se_encadena_detras_de_un_turno_de_chat():
    """La variable vuelve a False en el turno de chat: 'y ahora borralo' tras
    charla no puede activar el agente sola."""
    rutas = _repl_simulado(
        ["cuentame un chiste", "y ahora borralo"],
        lambda p: "", cableado=True)
    assert rutas == ["chat", "chat"]
