# -*- coding: utf-8 -*-
"""Tests de cognia.knowledge.extractores (sin red).

Los fixtures reproducen las claves REALES vistas con curl el 2026-08-24 en
la página del canal https://www.youtube.com/@theacuaboy170 (4,63 mil
suscriptores) y en /results con el filtro de canales: subscriberCountText,
channelRenderer/canonicalBaseUrl, '"content":"@handle • N suscriptores"',
<title>... - YouTube y las marcas bidi invisibles alrededor de la cifra.
"""
import pytest

from cognia.knowledge import extractores as ex

FSI, PDI, LRM = chr(0x2068), chr(0x2069), chr(0x200E)   # aislamiento bidi
CANAL_URL = "https://www.youtube.com/@theacuaboy170"

# Página de canal: maqueta vieja (subscriberCountText con accessibility) +
# cabecera nueva (content con "•"), como convive hoy en el HTML real.
CANAL_HTML = (
    "<html><head><title>the acua boy - YouTube</title>"
    "<script>var ytInitialData = {\"metadata\":{\"channelMetadataRenderer\":"
    "{\"title\":\"the acua boy\",\"description\":\"Acuarios y peces\","
    "\"externalId\":\"UCEJpbL2vo8uuPJqVBuUffGQ\","
    "\"vanityChannelUrl\":\"http://www.youtube.com/@theacuaboy170\"}},"
    "\"header\":{\"pageHeaderRenderer\":{\"pageTitle\":\"the acua boy\","
    "\"content\":{\"metadataRows\":[{\"text\":{\"content\":\"@theacuaboy170"
    " • " + FSI + "4.63 K" + PDI + " suscriptores\"}},"
    "{\"text\":{\"content\":\"" + FSI + "1.2 K" + PDI + " vídeos\"}}]}}},"
    "\"subscriberCountText\":{\"accessibility\":{\"accessibilityData\":"
    "{\"label\":\"4.63 K suscriptores\"}},\"simpleText\":\"" + LRM + "4.63 K"
    " suscriptores\"}};</script></head>"
    "<body><div>Saltar navegación Iniciar sesión</div></body></html>")

# Solo cabecera nueva, en español con "mil" y escapes JSON de los invisibles.
CANAL_HTML_NUEVO = (
    "<html><head><title>the acua boy - YouTube</title></head><body><script>"
    "{\"content\":\"@theacuaboy170 \\u2022 \\u20684.63 mil\\u2069 suscriptores\"}"
    ",{\"channelId\":\"UCEJpbL2vo8uuPJqVBuUffGQ\"}</script></body></html>")

# Render REAL sin JS del 2026-08-24: sin subscriberCountText; la única
# fuente es una lista de canales con uno AJENO delante; y las plantillas
# i18n traen "1 video" que no es la cuenta del canal.
CANAL_HTML_LISTA = (
    "<html><head><title>the acua boy - YouTube</title></head><body><script>"
    "{\"VIDEO_COUNT\":{\"case1\":\"1 video\",\"other\":\"# videos\"},"
    "\"subtitle\":{\"content\":\"@SukhMehra65 • 120 k suscriptores\"},"
    "\"label\":\"Sukh Mehra @SukhMehra65 120 k suscriptores. Ir al canal\","
    "\"subtitle\":{\"content\":\"@theacuaboy170 • 4.63 K suscriptores\"},"
    "\"text\":{\"content\":\"138 vídeos\"},"
    "\"channelMetadataRenderer\":{\"title\":\"the acua boy\",\"description\":\"d\","
    "\"externalId\":\"UCEJpbL2vo8uuPJqVBuUffGQ\"}}</script></body></html>")

# Render REAL de @ThatBoyAqua (2026-08-24): el PRIMER subscriberCountText
# del documento es de un canal relacionado (gridChannelRenderer, 27.8 k) y
# un badge de playlist trae "47 videos"; la cabecera dice 305 k y 183.
CANAL_HTML_RELACIONADO = (
    "<html><head><title>That Boy Aqua - YouTube</title></head><body><script>"
    "{\"contents\":{\"twoColumnBrowseResultsRenderer\":{\"tabs\":[{\"gridChannelRenderer\":"
    "{\"channelId\":\"UCotroCanal000000000000\",\"navigationEndpoint\":{\"browseEndpoint\":"
    "{\"canonicalBaseUrl\":\"/@thatguyaqua\"}},"
    "\"videoCountText\":{\"runs\":[{\"text\":\"130\"},{\"text\":\" videos\"}]},"
    "\"subscriberCountText\":{\"accessibility\":{\"accessibilityData\":{\"label\":"
    "\"27.8 mil suscriptores\"}},\"simpleText\":\"27.8 k suscriptores\"}},"
    "{\"thumbnailBadgeViewModel\":{\"text\":\"47 videos\"}}]}},"
    "\"header\":{\"pageHeaderRenderer\":{\"pageTitle\":\"That Boy Aqua\",\"content\":"
    "{\"metadataRows\":[{\"metadataParts\":[{\"text\":{\"content\":\"@ThatBoyAqua\"}}]},"
    "{\"metadataParts\":[{\"text\":{\"content\":\"305 k suscriptores\"},"
    "\"accessibilityLabel\":\"305 mil suscriptores\"},{\"text\":{\"content\":\"183 videos\"}}]}]}}},"
    "\"metadata\":{\"channelMetadataRenderer\":{\"title\":\"That Boy Aqua\","
    "\"externalId\":\"UCwKY6YKl0-amtFsfYEDpMkA\","
    "\"vanityChannelUrl\":\"http://www.youtube.com/@ThatBoyAqua\"}}}"
    "</script></body></html>")

# Maqueta vieja (c4TabbedHeaderRenderer) en inglés, con runs.
CANAL_HTML_EN = (
    "<html><head><title>Some Channel - YouTube</title></head><body><script>"
    "{\"header\":{\"c4TabbedHeaderRenderer\":{\"channelId\":\"UCabc123\","
    "\"title\":\"Some Channel\","
    "\"subscriberCountText\":{\"simpleText\":\"1.2M subscribers\"},"
    "\"videosCountText\":{\"runs\":[{\"text\":\"340\"},{\"text\":\" videos\"}]}}},"
    "\"metadata\":{\"channelMetadataRenderer\":{\"title\":\"Some Channel\","
    "\"externalId\":\"UCabc123\"}}}</script></body></html>")

RESULTS_URL = ("https://www.youtube.com/results?search_query=the+acua+boy"
               "&sp=EgIQAg%253D%253D")
RESULTS_HTML = (
    "<html><head><title>the acua boy - YouTube</title></head><body><script>"
    "var ytInitialData = {\"contents\":[{\"channelRenderer\":{"
    "\"channelId\":\"UCEJpbL2vo8uuPJqVBuUffGQ\","
    "\"title\":{\"simpleText\":\"the acua boy\"},"
    "\"navigationEndpoint\":{\"browseEndpoint\":{\"browseId\":\"UCEJpbL2vo8uuPJqVBuUffGQ\","
    "\"canonicalBaseUrl\":\"/@theacuaboy170\"}},"
    # maqueta 2024+: la cifra va en videoCountText y el handle en subscriberCountText
    "\"videoCountText\":{\"simpleText\":\"" + FSI + "4.63 K" + PDI + " suscriptores\"},"
    "\"subscriberCountText\":{\"simpleText\":\"@theacuaboy170\"}}},"
    "{\"channelRenderer\":{\"channelId\":\"UCotroCanal000000000000\","
    "\"title\":{\"simpleText\":\"Acua Boy Fan\"},"
    "\"navigationEndpoint\":{\"browseEndpoint\":{\"canonicalBaseUrl\":\"/@acuaboyfan\"}},"
    "\"subscriberCountText\":{\"simpleText\":\"305 k suscriptores\"}}},"
    # duplicado del primero: se deduplica por channelId
    "{\"channelRenderer\":{\"channelId\":\"UCEJpbL2vo8uuPJqVBuUffGQ\","
    "\"title\":{\"simpleText\":\"the acua boy\"}}}]};</script></body></html>")


# ── normalizar_cifra ───────────────────────────────────────────────────

@pytest.mark.parametrize("texto, esperado", [
    ("4.63 K", 4630), ("305 k", 305000), ("1.2M", 1200000), ("5", 5),
    ("4.63 mil", 4630), ("4.630", 4630), ("4,63 mil", 4630),
    ("4.63 K suscriptores", 4630), ("1,2 M de suscriptores", 1200000),
    ("1.234.567", 1234567), ("1,234 subscribers", 1234), ("0", 0),
    (FSI + "4.63" + PDI + " K", 4630),      # invisibles alrededor
])
def test_normalizar_cifra(texto, esperado):
    assert ex.normalizar_cifra(texto) == esperado


@pytest.mark.parametrize("texto", ["", None, "muchos", "4.63", "K 4"])
def test_normalizar_cifra_no_entiende(texto):
    assert ex.normalizar_cifra(texto) is None


# ── extractor de YouTube: canal ────────────────────────────────────────

def test_youtube_canal_pagina_completa():
    d = ex.extraer_datos(CANAL_URL, CANAL_HTML)
    assert d["sitio"] == "youtube"
    assert d["titulo"] == "the acua boy"
    c = d["campos"]
    assert c["handle"] == "@theacuaboy170"
    assert c["canal_id"] == "UCEJpbL2vo8uuPJqVBuUffGQ"
    assert c["suscriptores"] == "4.63 K"
    assert c["suscriptores_n"] == 4630
    assert c["videos"] == "1.2 K"
    assert c["descripcion"] == "Acuarios y peces"
    assert d["resumen"] == "the acua boy (@theacuaboy170): 4.63 K suscriptores, 1.2 K vídeos"
    # ningún invisible se cuela (el centinela bloquea con >5)
    assert FSI not in str(d) and PDI not in str(d) and LRM not in str(d)


def test_youtube_canal_cabecera_nueva_mil_y_escapes():
    d = ex.extraer_datos(CANAL_URL, CANAL_HTML_NUEVO)
    assert d["campos"]["suscriptores"] == "4.63 mil"
    assert d["campos"]["suscriptores_n"] == 4630
    assert d["titulo"] == "the acua boy"


def test_youtube_canal_la_cabecera_manda_sobre_relacionados_y_playlists():
    d = ex.extraer_datos("https://www.youtube.com/@ThatBoyAqua", CANAL_HTML_RELACIONADO)
    assert d["campos"]["suscriptores"] == "305 k"          # no "27.8 k" (relacionado)
    assert d["campos"]["suscriptores_n"] == 305000
    assert d["campos"]["videos"] == "183"                  # no "47" (playlist) ni "130"
    assert d["campos"]["handle"] == "@ThatBoyAqua"
    # por /channel/ID el handle sale del vanityChannelUrl, no del primer
    # canonicalBaseUrl (que es del canal relacionado)
    d = ex.extraer_datos("https://www.youtube.com/channel/UCwKY6YKl0-amtFsfYEDpMkA",
                         CANAL_HTML_RELACIONADO)
    assert d["campos"]["handle"] == "@ThatBoyAqua"
    assert d["campos"]["suscriptores"] == "305 k"


def test_youtube_canal_prefiere_la_cifra_con_el_handle_propio():
    d = ex.extraer_datos(CANAL_URL, CANAL_HTML_LISTA)
    assert d["campos"]["suscriptores"] == "4.63 K"        # no "120 k" (ajeno)
    assert "videos" not in d["campos"]     # sin cabecera no se adivina ("1 video" i18n)
    # sin handle en la URL ni en el HTML y con cifras distintas: NINGUNA
    sin_handle = CANAL_HTML_LISTA.replace("@theacuaboy170", "@otro")
    d = ex.extraer_datos("https://www.youtube.com/channel/UCEJpbL2vo8uuPJqVBuUffGQ",
                         sin_handle)
    assert "suscriptores" not in d["campos"]
    assert d["campos"]["canal_id"] == "UCEJpbL2vo8uuPJqVBuUffGQ"
    # ...pero si todas las candidatas coinciden, vale
    coinciden = sin_handle.replace("120 k", "4.63 K")
    d = ex.extraer_datos("https://www.youtube.com/channel/UCEJpbL2vo8uuPJqVBuUffGQ",
                         coinciden)
    assert d["campos"]["suscriptores"] == "4.63 K"


def test_youtube_canal_ingles_y_runs():
    d = ex.extraer_datos("https://www.youtube.com/channel/UCabc123", CANAL_HTML_EN)
    assert d["campos"]["suscriptores"] == "1.2M"
    assert d["campos"]["suscriptores_n"] == 1200000
    assert d["campos"]["videos"] == "340"
    assert d["titulo"] == "Some Channel"


def test_youtube_sin_dato_devuelve_none():
    consent = "<html><head><title>Antes de ir a YouTube</title></head><body>Aceptar</body></html>"
    assert ex.extraer_datos(CANAL_URL, consent) is None
    assert ex.extraer_datos("https://www.youtube.com/watch?v=abc", CANAL_HTML) is None
    assert ex.extraer_datos("https://example.org/@theacuaboy170", CANAL_HTML) is None
    assert ex.extraer_datos(CANAL_URL, "") is None


# ── extractor de YouTube: resultados ───────────────────────────────────

def test_youtube_resultados_agrupa_por_channel_renderer():
    d = ex.extraer_datos(RESULTS_URL, RESULTS_HTML)
    assert d["sitio"] == "youtube"
    assert d["campos"]["canales"] == 2                 # el duplicado no cuenta
    c1, c2 = d["canales"]
    assert c1 == {"titulo": "the acua boy", "handle": "@theacuaboy170",
                  "url": "https://www.youtube.com/@theacuaboy170",
                  "canal_id": "UCEJpbL2vo8uuPJqVBuUffGQ",
                  "suscriptores": "4.63 K", "suscriptores_n": 4630}
    assert c2["handle"] == "@acuaboyfan" and c2["suscriptores_n"] == 305000
    assert d["campos"]["canal_1"] == "the acua boy (@theacuaboy170): 4.63 K suscriptores"
    assert "4.63 K" in d["resumen"]


def test_youtube_canal_con_abrir_inyectado():
    urls = []

    def abrir(url):
        urls.append(url)
        return RESULTS_HTML

    canales = ex.youtube_canal("the acua boy", abrir=abrir)
    assert urls == [RESULTS_URL]           # filtro de canales + nombre citado
    assert canales[0]["handle"] == "@theacuaboy170"
    assert canales[0]["suscriptores"] == "4.63 K"
    assert canales[0]["suscriptores_n"] == 4630
    assert [c["titulo"] for c in canales] == ["the acua boy", "Acua Boy Fan"]


def test_youtube_canal_red_rota_lanza_con_motivo():
    def abrir(url):
        raise OSError("sin red")
    with pytest.raises(RuntimeError, match="youtube_canal.*OSError: sin red"):
        ex.youtube_canal("the acua boy", abrir=abrir)
    with pytest.raises(ValueError):
        ex.youtube_canal("   ", abrir=abrir)
    # página sin canales: lista vacía, NO excepción (son cosas distintas)
    assert ex.youtube_canal("nada", abrir=lambda u: "<html></html>") == []


# ── registry y bloque ──────────────────────────────────────────────────

def test_registrar_extractor_y_fallo_declarado(monkeypatch):
    monkeypatch.setattr(ex, "EXTRACTORES", list(ex.EXTRACTORES))

    def mio(url, html):
        return {"sitio": "mio", "titulo": "T", "campos": {"x": "1"},
                "resumen": "T: x=1"}
    ex.registrar(r"^https://mio\.example/", mio)
    assert ex.extraer_datos("https://mio.example/p", "<html>")["sitio"] == "mio"
    assert ex.extraer_datos("https://otro.example/p", "<html>") is None

    def roto(url, html):
        raise KeyError("boom")
    ex.registrar(r"^https://roto\.example/", roto)
    d = ex.extraer_datos("https://roto.example/p", "<html>")
    assert d["campos"] == {} and "roto falló" in d["aviso"] and "KeyError" in d["aviso"]


def test_bloque_datos_formato():
    d = ex.extraer_datos(CANAL_URL, CANAL_HTML)
    b = ex.bloque_datos(d)
    assert b.startswith("DATOS EXTRAIDOS (youtube): titulo: the acua boy; ")
    assert "handle: @theacuaboy170" in b
    assert "suscriptores: 4.63 K (4630)" in b
    assert "suscriptores_n" not in b           # ya va entre paréntesis
    assert ex.bloque_datos({"sitio": "x", "campos": {}}) == ""
    assert ex.bloque_datos(None) == ""


def test_cabeceras_para_youtube_y_resto():
    yt = ex.cabeceras_para(CANAL_URL)
    assert yt["Cookie"].startswith("CONSENT=YES+1") and "es-ES" in yt["Accept-Language"]
    assert yt["User-Agent"] == ex.UA_CHROME
    otro = ex.cabeceras_para("https://es.wikipedia.org/wiki/X", ua="Cognia/1.0")
    assert "Cookie" not in otro and otro["User-Agent"] == "Cognia/1.0"
