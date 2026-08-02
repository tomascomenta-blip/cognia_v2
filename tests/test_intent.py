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
