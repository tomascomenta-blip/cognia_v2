# -*- coding: utf-8 -*-
"""La búsqueda web del agente SIN dependencias opcionales (sin red).

Cubre lo que se rompía en el venv instalado del producto (2026-08-24: sin
ddgs, sin playwright, sin lxml): la vía lite de DuckDuckGo con urllib +
html.parser, la caída ddgs -> lite con AMBOS motivos si las dos fallan, el
parser de bs4 elegido por importabilidad, el reintento de UA ante 403, el
bloque DATOS EXTRAIDOS de un cascarón JS y la marca "texto insuficiente"
en buscar_en_web. ddgs y httpx se sustituyen con monkeypatch; el POST al
lite se inyecta con `abrir`.
"""
import sys
import types

import pytest

from cognia.agent import sentinel as s
from cognia.knowledge import navegador as nav
from tests.test_extractores import CANAL_HTML, CANAL_URL


@pytest.fixture(autouse=True)
def _audit_aislado(monkeypatch, tmp_path):
    # El centinela audita en ~/.cognia/sentinel_audit.jsonl: aislado como
    # en test_research_centinela.py.
    monkeypatch.setattr(s, "_AUDIT", tmp_path / "audit.jsonl")


# Maqueta del endpoint lite: filas <tr> con el enlace y la siguiente con el
# resumen; controles del buscador mezclados; un enlace de redirección propia.
LITE_HTML = """
<html><body><form><table>
<tr><td><a href="/lite/?q=x&s=10">Next Page &gt;</a></td></tr>
<tr><td><a class="result-link" href="https://www.youtube.com/@theacuaboy170">the acua boy - YouTube</a></td></tr>
<tr><td class="result-snippet">Canal de acuarios: 4.63 K suscriptores y 1.2 K vídeos.</td></tr>
<tr><td><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fejemplo.org%2Fpeces&amp;rut=abc">Peces de acuario - Ejemplo</a></td></tr>
<tr><td class="result-snippet">Guía de peces.</td></tr>
<tr><td><a href="https://duckduckgo.com/settings">Settings</a></td></tr>
</table></form></body></html>
"""


# ── _buscar_lite ───────────────────────────────────────────────────────

def test_buscar_lite_parsea_html_del_endpoint():
    consultas = []

    def abrir(consulta):
        consultas.append(consulta)
        return LITE_HTML

    out = nav._buscar_lite("the acua boy youtube", abrir=abrir)
    assert consultas == ["the acua boy youtube"]
    assert [r["url"] for r in out] == ["https://www.youtube.com/@theacuaboy170",
                                       "https://ejemplo.org/peces"]
    assert out[0]["titulo"] == "the acua boy - YouTube"
    assert "4.63 K suscriptores" in out[0]["resumen"]
    assert all(r["via"] == "lite" for r in out)
    assert len(nav._buscar_lite("q", max_candidatos=1, abrir=abrir)) == 1


def test_buscar_lite_reintenta_con_espera_y_lanza_con_motivo(monkeypatch):
    esperas = []
    monkeypatch.setattr(nav.time, "sleep", esperas.append)
    llamadas = {"n": 0}

    def abrir_flaky(consulta):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return "<html><body>limitado</body></html>"    # página sin resultados
        return LITE_HTML

    out = nav._buscar_lite("q", abrir=abrir_flaky)
    assert len(out) == 2 and esperas == [2.0]

    def abrir_roto(consulta):
        raise OSError("sin red")
    with pytest.raises(RuntimeError, match="lite.*OSError: sin red"):
        nav._buscar_lite("q", abrir=abrir_roto, intentos=1)
    with pytest.raises(RuntimeError, match="página sin resultados"):
        nav._buscar_lite("q", abrir=lambda c: "<html></html>", intentos=1)


# ── _buscar_ddg: ddgs -> lite -> error con ambos motivos ───────────────

def _sin_ddgs(monkeypatch):
    # None en sys.modules hace que `from ddgs import DDGS` lance ImportError.
    monkeypatch.setitem(sys.modules, "ddgs", None)


def _ddgs_falso(monkeypatch, text_fn):
    mod = types.ModuleType("ddgs")

    class DDGS:
        def text(self, consulta, max_results=8):
            return text_fn(consulta, max_results)
    mod.DDGS = DDGS
    monkeypatch.setitem(sys.modules, "ddgs", mod)


def test_buscar_ddg_cae_a_lite_si_falta_ddgs(monkeypatch):
    _sin_ddgs(monkeypatch)
    monkeypatch.setattr(nav, "_buscar_lite",
                        lambda c, n, **kw: [{"titulo": "t", "url": "https://a.org",
                                             "resumen": "", "via": "lite"}])
    out = nav._buscar_ddg("q", 3)
    assert out[0]["via"] == "lite"


def test_buscar_ddg_cae_a_lite_si_ddgs_vacio_o_revienta(monkeypatch):
    monkeypatch.setattr(nav, "_buscar_lite",
                        lambda c, n, **kw: [{"titulo": "t", "url": "https://a.org",
                                             "resumen": "", "via": "lite"}])
    _ddgs_falso(monkeypatch, lambda c, n: [])
    assert nav._buscar_ddg("q", 3)[0]["via"] == "lite"
    _ddgs_falso(monkeypatch, lambda c, n: (_ for _ in ()).throw(RuntimeError("ratelimit")))
    assert nav._buscar_ddg("q", 3)[0]["via"] == "lite"


def test_buscar_ddg_prefiere_ddgs_y_marca_via(monkeypatch):
    _ddgs_falso(monkeypatch, lambda c, n: [{"title": "T", "href": "https://b.org",
                                            "body": "cuerpo"}])
    monkeypatch.setattr(nav, "_buscar_lite",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no")))
    out = nav._buscar_ddg("q", 3)
    assert out == [{"titulo": "T", "url": "https://b.org", "resumen": "cuerpo",
                    "via": "ddgs"}]


def test_buscar_ddg_lanza_con_ambos_motivos(monkeypatch):
    _sin_ddgs(monkeypatch)
    monkeypatch.setattr(nav, "_buscar_lite",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("limitado")))
    with pytest.raises(RuntimeError) as ei:
        nav._buscar_ddg("q", 3)
    msg = str(ei.value)
    assert "ddgs: no instalada" in msg and "lite: limitado" in msg


def test_via_busqueda_disponible_sin_red(monkeypatch):
    real = nav.importlib.util.find_spec
    monkeypatch.setattr(nav.importlib.util, "find_spec",
                        lambda n, *a: None if n == "ddgs" else real(n, *a))
    assert nav.via_busqueda_disponible() == "lite"
    monkeypatch.setattr(nav.importlib.util, "find_spec", lambda n, *a: None)
    assert nav.via_busqueda_disponible().startswith("ninguna:")
    monkeypatch.setattr(nav.importlib.util, "find_spec", lambda n, *a: object())
    assert nav.via_busqueda_disponible() == "ddgs"


# ── _extraer_con_http: parser, 403 y DATOS EXTRAIDOS ───────────────────

def test_parser_bs4_sin_lxml(monkeypatch):
    real = nav.importlib.util.find_spec
    monkeypatch.setattr(nav.importlib.util, "find_spec",
                        lambda n, *a: None if n == "lxml" else real(n, *a))
    assert nav._parser_bs4() == "html.parser"


class _Resp:
    def __init__(self, status, text, url):
        self.status_code, self.text, self.url = status, text, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_extraer_con_http_cascaron_js_entrega_datos(monkeypatch):
    import httpx
    peticiones = []

    def get(url, timeout, follow_redirects, headers):
        peticiones.append(headers)
        return _Resp(200, CANAL_HTML, url)
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(nav, "_parser_bs4", lambda: "html.parser")

    pag = nav._extraer_con_http(CANAL_URL)
    assert pag["via"] == "http" and pag["parser"] == "html.parser"
    assert pag["texto"].startswith("DATOS EXTRAIDOS (youtube): titulo: the acua boy; ")
    assert "suscriptores: 4.63 K (4630)" in pag["texto"]
    assert "Saltar navegación" in pag["texto"]      # el texto visible sigue detrás
    assert pag["datos"]["campos"]["handle"] == "@theacuaboy170"
    assert pag["titulo"] == "the acua boy - YouTube"
    assert peticiones[0]["Cookie"].startswith("CONSENT=YES+1")
    assert "aviso" not in pag


def test_extraer_con_http_reintenta_403_con_ua_cognia(monkeypatch):
    import httpx
    uas = []

    def get(url, timeout, follow_redirects, headers):
        uas.append(headers["User-Agent"])
        if len(uas) == 1:
            return _Resp(403, "", url)
        return _Resp(200, "<html><head><title>Gestión</title></head>"
                          "<body><p>Texto con acentos: más.</p></body></html>", url)
    monkeypatch.setattr(httpx, "get", get)
    pag = nav._extraer_con_http("https://es.wikipedia.org/wiki/X")
    assert uas == [nav._UA_CHROME, nav._UA_RESEARCH]
    assert pag["titulo"] == "Gestión" and "más." in pag["texto"]
    assert "403" in pag["aviso"] and "Cognia/1.0" in pag["aviso"]
    assert "datos" not in pag

    def get_403(url, timeout, follow_redirects, headers):
        return _Resp(403, "", url)
    monkeypatch.setattr(httpx, "get", get_403)
    with pytest.raises(RuntimeError, match="HTTP 403"):
        nav._extraer_con_http("https://es.wikipedia.org/wiki/X")


# ── buscar_en_web: texto insuficiente vs datos extraídos ───────────────

def test_buscar_en_web_marca_insuficiente_pero_acepta_con_datos():
    candidatos = [
        {"titulo": "cascarón", "url": "https://js.example/canal", "resumen": ""},
        {"titulo": "con datos", "url": "https://www.youtube.com/@theacuaboy170",
         "resumen": ""},
        {"titulo": "larga", "url": "https://largo.example/p", "resumen": ""},
    ]
    datos = {"sitio": "youtube", "titulo": "the acua boy",
             "campos": {"handle": "@theacuaboy170", "suscriptores": "4.63 K"},
             "resumen": "the acua boy (@theacuaboy170): 4.63 K suscriptores"}

    def extractor(url, timeout_s=None):
        if url.startswith("https://js.example"):
            return {"titulo": "the acua boy", "url_final": url, "via": "http",
                    "texto": "the acua boy youtube canal (cascarón JS)"}
        if "youtube.com" in url:
            return {"titulo": "the acua boy", "url_final": url, "via": "http",
                    "datos": datos,
                    "texto": "DATOS EXTRAIDOS (youtube): titulo: the acua boy; "
                             "handle: @theacuaboy170; suscriptores: 4.63 K"}
        return {"titulo": "larga", "url_final": url, "via": "http",
                "texto": "the acua boy youtube canal de acuarios. " * 20}

    r = nav.buscar_en_web("the acua boy youtube", max_resultados=3,
                          buscador=lambda c, n: candidatos, extractor=extractor)
    assert [v["url"] for v in r["resultados"]] == [c["url"] for c in candidatos]
    corto, con_datos, largo = r["resultados"]
    assert corto["aviso"] == "texto insuficiente (página JS)"
    assert con_datos["datos"] is datos and "aviso" not in con_datos
    assert "aviso" not in largo
    assert "1 resultado(s) con texto insuficiente" in r["aviso"]
    assert "https://js.example/canal" in r["aviso"]
    assert r["descartados"] == []
