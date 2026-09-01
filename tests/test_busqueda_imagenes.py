# -*- coding: utf-8 -*-
r"""
tests/test_busqueda_imagenes.py
===============================
cognia/busqueda_imagenes.py contra respuestas REALES de las dos APIs.

POR QUE EL JSON VA EMBEBIDO Y NO INVENTADO. Los dos bloques de abajo se
capturaron el 2026-08-31 con consultas de verdad ("mitocondria") a
commons.wikimedia.org/w/api.php y api.openverse.org/v1/images/, y se recortaron
(menos resultados, y en Commons el campo Credit, que llega a traer una TABLA
HTML entera y que el parser no usa). El resto esta tal cual llego, escapado a
ASCII por json.dumps. Un JSON inventado a mano probaria que el parser sabe leer
lo que yo creo que devuelve la API; contra el real se cae solo cuando Wikimedia
cambie el formato, que es justo el aviso que hace falta.

Va embebido en el .py en vez de en tests/fixtures/ porque esta pieza tenia
asignados exactamente dos ficheros; el papel es el mismo.

LO UNICO TOCADO A MANO son las dos entradas marcadas SIN_ATRIBUCION: son copias
de resultados reales con la licencia quitada. Commons casi siempre trae
licencia, asi que el camino de descarte no se puede ejercitar con lo que
devuelve la API un dia cualquiera -- y ese camino es el que impide que una
imagen sin creditos acabe en un PDF exportado.

RED: los unicos tests que salen a internet estan en TestContraLasApisDeVerdad,
y NO corren en la suite normal -- llevan @pytest.mark.red Y un skipif por
COGNIA_TESTS_RED, porque el marcador solo protege si quien corre pytest escribe
-m "not red" y el pytest.ini de este repo no lo pone en addopts. Para correrlos
a proposito, el comando esta en el docstring de esa clase. Todo lo demas es
offline, incluidos los fallos de red, que se provocan sustituyendo urlopen por
el error exacto que lanza urllib.

LO QUE UN TEST DE RED PUEDE Y NO PUEDE AFIRMAR. El 2026-08-31 el assert
`url_imagen.startswith("https://upload.wikimedia.org/")` se puso rojo porque
Commons empezo a servir las miniaturas escaladas desde thumb.wikimedia.org.
Era ruido: las urls nuevas se bajan sin problema con almacen.descargar_adjunto.
Pero el mismo cambio destapo un fallo de PRODUCTO -- la deduplicacion entre
fuentes metia el host en la clave del fichero y dejo de deduplicar -- que
ningun test offline cazaba porque los fixtures traen el host viejo por los dos
caminos. De ahi TestDeduplicacionEntreHosts, que es offline y no depende de por
que maquina sirva Wikimedia manana.
"""

import json
import os
import urllib.error
import urllib.parse
from unittest.mock import patch

import pytest

from cognia import busqueda_imagenes as bi
from cognia.busqueda_imagenes import (
    ErrorBusquedaImagenes,
    buscar,
    buscar_con_avisos,
    parsear_commons,
    parsear_openverse,
)


# ── respuestas reales capturadas ─────────────────────────────────────────────

COMMONS_MITOCONDRIA = r"""
{
    "batchcomplete": true,
    "continue": {"gsroffset": 3, "continue": "gsroffset||"},
    "query": {
        "pages": [
            {
                "pageid": 1248089,
                "ns": 6,
                "title": "File:Mitochondria, mammalian lung - TEM.jpg",
                "index": 1,
                "imageinfo": [
                    {
                        "size": 98422,
                        "width": 640,
                        "height": 480,
                        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/0/0c/Mitochondria%2C_mammalian_lung_-_TEM.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail_unscaled",
                        "thumbwidth": 800,
                        "thumbheight": 600,
                        "url": "https://upload.wikimedia.org/wikipedia/commons/0/0c/Mitochondria%2C_mammalian_lung_-_TEM.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Mitochondria,_mammalian_lung_-_TEM.jpg",
                        "extmetadata": {
                            "Artist": {"value": "Louisa Howard", "source": "commons-desc-page"},
                            "LicenseShortName": {"value": "Public domain", "source": "commons-desc-page", "hidden": ""}
                        }
                    }
                ]
            },
            {
                "pageid": 73576832,
                "ns": 6,
                "title": "File:Mitoc\u00f4ndria 11.jpg",
                "index": 2,
                "imageinfo": [
                    {
                        "size": 1444799,
                        "width": 3967,
                        "height": 2688,
                        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/95/Mitoc%C3%B4ndria_11.jpg/960px-Mitoc%C3%B4ndria_11.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
                        "thumbwidth": 800,
                        "thumbheight": 542,
                        "url": "https://upload.wikimedia.org/wikipedia/commons/9/95/Mitoc%C3%B4ndria_11.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Mitoc%C3%B4ndria_11.jpg",
                        "extmetadata": {
                            "Artist": {"value": "<a href=\"//commons.wikimedia.org/w/index.php?title=User:Beatrizhnobrega&amp;action=edit&amp;redlink=1\" class=\"new\" title=\"User:Beatrizhnobrega (page does not exist)\">Beatrizhnobrega</a>", "source": "commons-desc-page"},
                            "LicenseShortName": {"value": "CC BY-SA 4.0", "source": "commons-desc-page", "hidden": ""},
                            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0", "source": "commons-desc-page"}
                        }
                    }
                ]
            },
            {
                "pageid": 124005455,
                "ns": 6,
                "title": "File:Mitochondria 9 -- Smart-Servier.png",
                "index": 3,
                "imageinfo": [
                    {
                        "size": 233151,
                        "width": 600,
                        "height": 1414,
                        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/4/4b/Mitochondria_9_--_Smart-Servier.png?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail_unscaled",
                        "thumbwidth": 800,
                        "thumbheight": 1885,
                        "url": "https://upload.wikimedia.org/wikipedia/commons/4/4b/Mitochondria_9_--_Smart-Servier.png?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Mitochondria_9_--_Smart-Servier.png",
                        "extmetadata": {}
                    }
                ]
            }
        ]
    }
}
"""
# La tercera pagina (Smart-Servier) es real, pero su extmetadata se vacio a
# mano: SIN_ATRIBUCION.

OPENVERSE_MITOCONDRIA = r"""
{
    "result_count": 115,
    "page_count": 58,
    "page_size": 3,
    "page": 1,
    "results": [
        {
            "id": "0e75aa68-da47-410d-a9c4-5cbf52ddea3c",
            "title": "Mitocondria Cresta Membrana",
            "foreign_landing_url": "https://commons.wikimedia.org/w/index.php?curid=177353910",
            "url": "https://upload.wikimedia.org/wikipedia/commons/d/db/Mitocondria_Cresta_Membrana.jpg",
            "creator": "Ziyun Yang ; Liang Wang ; Cheng Yang ; Shiming Pu ; Ziqi Guo ; Qiong Wu ; Zuping Zhou ; Hongxia Zhao",
            "creator_url": null,
            "license": "by",
            "license_version": "4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "provider": "wikimedia",
            "source": "wikimedia",
            "attribution": "\"Mitocondria Cresta Membrana\" by Ziyun Yang ; Liang Wang ; Cheng Yang ; Shiming Pu ; Ziqi Guo ; Qiong Wu ; Zuping Zhou ; Hongxia Zhao is licensed under CC BY 4.0. To view a copy of this license, visit https://creativecommons.org/licenses/by/4.0/.",
            "height": 363,
            "width": 471,
            "thumbnail": "https://api.openverse.org/v1/images/0e75aa68-da47-410d-a9c4-5cbf52ddea3c/thumb/?format=json"
        },
        {
            "id": "0ee89e89-69f4-4b0f-a620-f17590080f2e",
            "title": "Mitocondrias Crestas",
            "foreign_landing_url": "https://commons.wikimedia.org/w/index.php?curid=177372903",
            "url": "https://upload.wikimedia.org/wikipedia/commons/9/97/Mitocondrias_Crestas.jpg",
            "creator": "Mannella, Carmen A. ; Lederer, W. Jonathan ; Jafri, M Saleet",
            "creator_url": null,
            "license": "by",
            "license_version": "4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "provider": "wikimedia",
            "source": "wikimedia",
            "attribution": "\"Mitocondrias Crestas\" by Mannella, Carmen A. ; Lederer, W. Jonathan ; Jafri, M Saleet is licensed under CC BY 4.0. To view a copy of this license, visit https://creativecommons.org/licenses/by/4.0/.",
            "height": 274,
            "width": 586,
            "thumbnail": "https://api.openverse.org/v1/images/0ee89e89-69f4-4b0f-a620-f17590080f2e/thumb/?format=json"
        },
        {
            "id": "0ee89e89-69f4-4b0f-a620-f17590080f2f",
            "title": "Mitocondrias sin licencia",
            "foreign_landing_url": "https://commons.wikimedia.org/w/index.php?curid=177372904",
            "url": "https://upload.wikimedia.org/wikipedia/commons/9/97/Sin_licencia.jpg",
            "creator": "Alguien",
            "creator_url": null,
            "license": "",
            "license_version": "",
            "license_url": null,
            "provider": "wikimedia",
            "source": "wikimedia",
            "attribution": null,
            "height": 274,
            "width": 586,
            "thumbnail": null
        }
    ]
}
"""
# El tercer resultado es una copia del segundo con la licencia quitada:
# SIN_ATRIBUCION.


@pytest.fixture
def commons():
    return parsear_commons(json.loads(COMMONS_MITOCONDRIA))


@pytest.fixture
def openverse():
    return parsear_openverse(json.loads(OPENVERSE_MITOCONDRIA))


# ── utilidades para simular la red sin tocarla ───────────────────────────────

class _Respuesta:
    """Lo minimo que json.load necesita de un objeto de urlopen."""

    def __init__(self, texto):
        self._texto = texto.encode("utf-8")

    def read(self, *a):
        return self._texto

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(codigo, razon="Too Many Requests"):
    return urllib.error.HTTPError("https://ejemplo", codigo, razon, {}, None)


# ── parseo de Commons ────────────────────────────────────────────────────────

class TestParseoCommons:

    def test_parsea_las_paginas_con_licencia(self, commons):
        # 3 paginas en la respuesta, 1 sin atribucion: quedan 2.
        assert len(commons) == 2

    def test_todos_los_campos_del_contrato_estan(self, commons):
        for r in commons:
            for campo in ("titulo", "url_imagen", "url_pagina", "autor",
                          "licencia", "ancho", "alto"):
                assert campo in r, campo

    def test_la_url_es_LA_THUMBURL_QUE_DEVUELVE_LA_API(self, commons):
        """
        Dato medido: fabricar la miniatura a mano da HTTP 400.

        La primera imagen lo ensena sola: el original mide 640 px, menos que
        los 800 pedidos, asi que la API devuelve el fichero SIN escalar
        (utm_content=thumbnail_unscaled) en vez de una url .../800px-...
        Un parser que construyera el nombre de la miniatura pediria una url
        que no existe.
        """
        primera = commons[0]
        assert primera["url_imagen"].endswith("thumbnail_unscaled")
        assert "/thumb/" not in primera["url_imagen"]
        assert "800px-" not in primera["url_imagen"]
        # La segunda si tiene miniatura de verdad, y tampoco se inventa: se
        # pidieron 800 px, la API contesta thumbwidth=800 y una url que dice
        # 960px- (Wikimedia redondea a sus anchos de siempre). Ahi se ve que el
        # nombre de la miniatura NO se puede deducir del ancho pedido.
        segunda = commons[1]
        assert "/thumb/" in segunda["url_imagen"]
        assert "960px-" in segunda["url_imagen"]
        assert segunda["ancho"] == 800
        assert segunda["url_imagen"].startswith("https://upload.wikimedia.org/")

    def test_el_autor_llega_sin_etiquetas_html(self, commons):
        """El Artist de Commons es HTML; en un pie de foto seria ilegible."""
        autor = commons[1]["autor"]
        assert autor == "Beatrizhnobrega"
        assert "<" not in autor and "href" not in autor

    def test_el_titulo_pierde_el_prefijo_File(self, commons):
        assert commons[0]["titulo"] == "Mitochondria, mammalian lung - TEM.jpg"

    def test_el_tamanio_es_el_de_la_MINIATURA(self, commons):
        """
        Lo que se pega en el cuaderno es la miniatura: dar el tamanio del
        original (3967x2688 en la segunda) descuadraria la maqueta.
        """
        assert (commons[1]["ancho"], commons[1]["alto"]) == (800, 542)

    def test_licencia_y_pagina_de_origen_reales(self, commons):
        assert commons[0]["licencia"] == "Public domain"
        assert commons[1]["licencia"] == "CC BY-SA 4.0"
        assert commons[1]["licencia_url"].startswith("https://creativecommons.org/")
        for r in commons:
            assert r["url_pagina"].startswith("https://commons.wikimedia.org/wiki/File:")

    def test_la_atribucion_viene_redactada(self, commons):
        credito = commons[1]["atribucion"]
        assert "Beatrizhnobrega" in credito
        assert "CC BY-SA 4.0" in credito
        assert commons[1]["url_pagina"] in credito

    def test_la_pagina_sin_licencia_NO_pasa(self, commons):
        """Sin licencia no se puede pegar en un cuaderno que se exporta."""
        titulos = [r["titulo"] for r in commons]
        assert not any("Smart-Servier" in t for t in titulos)

    def test_una_respuesta_vacia_no_revienta(self):
        assert parsear_commons({"batchcomplete": True}) == []
        assert parsear_commons({"query": {"pages": []}}) == []


# ── parseo de Openverse ──────────────────────────────────────────────────────

class TestParseoOpenverse:

    def test_descarta_el_resultado_sin_licencia(self, openverse):
        assert len(openverse) == 2
        assert not any("sin licencia" in r["titulo"] for r in openverse)

    def test_la_licencia_se_arma_legible(self, openverse):
        """'by' + '4.0' pegado tal cual no identifica ninguna licencia."""
        assert openverse[0]["licencia"] == "CC BY 4.0"

    def test_usa_la_url_del_fichero_no_el_proxy_de_openverse(self, openverse):
        """
        El campo thumbnail es un proxy de la propia API, con cupo por hora: si
        acaba en el cuaderno, la imagen deja de cargar cuando el cupo se agota.
        """
        assert openverse[0]["url_imagen"].startswith("https://upload.wikimedia.org/")
        assert "api.openverse.org" not in openverse[0]["url_imagen"]

    def test_respeta_la_atribucion_que_redacta_openverse(self, openverse):
        assert openverse[0]["atribucion"].startswith('"Mitocondria Cresta Membrana" by')
        assert "CC BY 4.0" in openverse[0]["atribucion"]

    def test_campos_del_contrato_y_tamanio(self, openverse):
        assert (openverse[0]["ancho"], openverse[0]["alto"]) == (471, 363)
        assert openverse[0]["fuente"] == "openverse"



# ── HTML crudo: el bug que _limpiar existe para evitar ───────────────────────

OPENVERSE_CON_HTML = r"""
{
    "result_count": 1,
    "results": [
        {
            "id": "aa11bb22-0000-4000-8000-000000000001",
            "title": "<b>Mitocondria</b> &amp; membrana",
            "foreign_landing_url": "https://www.flickr.com/photos/alguien/12345",
            "url": "https://live.staticflickr.com/65535/12345_abc_b.jpg",
            "creator": "<a href=\"https://www.flickr.com/photos/alguien\">Alguien &amp; Cia</a>",
            "creator_url": "https://www.flickr.com/photos/alguien",
            "license": "by-sa",
            "license_version": "2.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/2.0/",
            "provider": "flickr",
            "source": "flickr",
            "attribution": "<a href=\"https://www.flickr.com/photos/alguien/12345\">Mitocondria</a> by <span>Alguien &amp; Cia</span> is licensed under CC BY-SA 2.0.",
            "height": 480,
            "width": 640,
            "thumbnail": null
        }
    ]
}
"""
# Los proveedores que indexa Openverse (Flickr, museos) meten HTML en title,
# creator y attribution; Openverse lo reenvia tal cual. Este bloque es esa
# forma, con las tres etiquetas que se han visto de verdad.


class TestHtmlCrudo:
    """
    Ningun campo de texto puede llevar marcado hasta el cuaderno.

    Es el bug que el docstring de _limpiar dice existir para evitar, y estaba
    tapado porque la limpieza vivia SOLO en la rama de Commons: por Openverse
    entraba el HTML entero al titulo, al autor y al pie de foto, que es lo que
    se exporta al PDF.
    """

    def test_openverse_no_mete_etiquetas_en_titulo_autor_ni_atribucion(self):
        r = parsear_openverse(json.loads(OPENVERSE_CON_HTML))
        assert len(r) == 1
        for campo in ("titulo", "autor", "atribucion"):
            valor = r[0][campo]
            assert "<" not in valor and ">" not in valor, (campo, valor)
            assert "href" not in valor, (campo, valor)
            assert "&amp;" not in valor, (campo, valor)

    def test_el_texto_sigue_siendo_legible_despues_de_limpiar(self):
        """Limpiar no puede significar vaciar: el pie de foto tiene que servir."""
        r = parsear_openverse(json.loads(OPENVERSE_CON_HTML))[0]
        assert r["titulo"] == "Mitocondria & membrana"
        assert r["autor"] == "Alguien & Cia"
        assert r["atribucion"].startswith("Mitocondria by Alguien & Cia")
        assert "CC BY-SA 2.0" in r["atribucion"]

    def test_la_marca_no_se_cuela_por_ninguna_fuente_nueva(self):
        """
        La limpieza esta en _resultado (el cuello de botella de TODAS las
        fuentes) y no en cada parser: una fuente anadida a FUENTES manana no
        depende de que su autor se acuerde de llamar a _limpiar.
        """
        r = bi._resultado(
            titulo="<h1>T</h1>",
            url_imagen="https://ejemplo/x.jpg",
            url_pagina="https://ejemplo/pagina",
            autor="<i>A</i>",
            licencia="<em>CC BY 4.0</em>",
            ancho=1, alto=1, fuente="inventada",
        )
        assert r["titulo"] == "T"
        assert r["autor"] == "A"
        assert r["licencia"] == "CC BY 4.0"
        assert "<" not in r["atribucion"]


# ── la atribucion, que es el punto de todo esto ──────────────────────────────

class TestAtribucion:

    def test_ningun_resultado_sale_sin_licencia_ni_origen(self, commons, openverse):
        for r in commons + openverse:
            assert r["licencia"], r["titulo"]
            assert r["url_pagina"], r["titulo"]
            assert r["url_imagen"], r["titulo"]

    def test_sin_autor_se_MARCA_en_vez_de_descartarse(self):
        """
        El dominio publico a menudo no trae autor. Descartarlo seria tirar
        imagenes usables; colarlo sin marca dejaria al llamador sin saber que
        el pie de foto va cojo.
        """
        data = json.loads(COMMONS_MITOCONDRIA)
        pagina = data["query"]["pages"][0]
        pagina["imageinfo"][0]["extmetadata"].pop("Artist")
        r = parsear_commons({"query": {"pages": [pagina]}})
        assert len(r) == 1
        assert r[0]["autor"] == ""
        assert r[0]["atribucion_completa"] is False
        # Y la etiqueta se ve en el listado de la consola.
        assert "SIN AUTOR" in bi.formatear(r)

    def test_con_autor_y_licencia_se_marca_completa(self, commons):
        assert commons[1]["atribucion_completa"] is True


# ── la peticion que se arma ──────────────────────────────────────────────────

class TestPeticion:

    def test_la_url_de_commons_pide_la_miniatura_y_solo_bitmaps(self):
        url = bi._url_commons("mitocondria", 8)
        assert "iiurlwidth=800" in url
        assert "generator=search" in url
        assert "filetype%3Abitmap" in url
        assert "gsrnamespace=6" in url
        assert "formatversion=2" in url
        assert "gsrlimit=8" in url

    def test_el_user_agent_es_identificable_con_contacto(self):
        assert "python-urllib" not in bi.USER_AGENT.lower()
        assert "Cognia" in bi.USER_AGENT
        assert "https://" in bi.USER_AGENT      # sin contacto, Wikimedia da 429

    def test_el_timeout_no_es_el_de_busqueda_web(self):
        """10 s falla en frio contra Commons; medido."""
        from cognia import busqueda_web
        assert bi.TIMEOUT >= 25
        assert bi.TIMEOUT > busqueda_web.TIMEOUT

    def test_el_user_agent_viaja_en_la_peticion(self):
        capturada = {}

        def falso_urlopen(req, timeout=None):
            capturada.update(req.headers)
            capturada["timeout"] = timeout
            return _Respuesta(COMMONS_MITOCONDRIA)

        with patch("urllib.request.urlopen", side_effect=falso_urlopen):
            bi.buscar_commons("mitocondria", 3)

        cabeceras = {k.lower(): v for k, v in capturada.items()}
        assert cabeceras["user-agent"] == bi.USER_AGENT
        assert capturada["timeout"] == bi.TIMEOUT


# ── errores legibles ─────────────────────────────────────────────────────────

class TestErroresLegibles:

    def test_timeout_dice_cuanto_espero_y_quien_fallo(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            with pytest.raises(ErrorBusquedaImagenes) as exc:
                bi.buscar_commons("mitocondria", 3)
        mensaje = str(exc.value)
        assert "Wikimedia Commons" in mensaje
        assert f"{bi.TIMEOUT} s" in mensaje

    def test_timeout_envuelto_en_URLError_tambien(self):
        """urllib tapa el timeout del socket dentro de un URLError."""
        error = urllib.error.URLError(TimeoutError("timed out"))
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(ErrorBusquedaImagenes, match="no respondio en"):
                bi.buscar_openverse("mitocondria", 3)

    def test_429_explica_que_hacer(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(429)):
            with pytest.raises(ErrorBusquedaImagenes) as exc:
                bi.buscar_commons("mitocondria", 3)
        mensaje = str(exc.value)
        assert "429" in mensaje
        assert "esperar" in mensaje

    def test_403_manda_mirar_el_user_agent(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(403, "Forbidden")):
            with pytest.raises(ErrorBusquedaImagenes, match="User-Agent"):
                bi.buscar_commons("mitocondria", 3)

    def test_sin_dns_no_sale_un_traceback_crudo(self):
        error = urllib.error.URLError(OSError(11001, "getaddrinfo failed"))
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(ErrorBusquedaImagenes, match="no se pudo conectar"):
                bi.buscar_commons("mitocondria", 3)

    def test_respuesta_que_no_es_json(self):
        with patch("urllib.request.urlopen", return_value=_Respuesta("<html>502</html>")):
            with pytest.raises(ErrorBusquedaImagenes, match="no es JSON"):
                bi.buscar_commons("mitocondria", 3)

    def test_consulta_vacia_lo_dice(self):
        with pytest.raises(ErrorBusquedaImagenes, match="vacia"):
            buscar("   ")


# ── cascada y degradacion ────────────────────────────────────────────────────

def _fuentes(commons_fn, openverse_fn, monkeypatch):
    monkeypatch.setattr(bi, "FUENTES",
                        {"commons": commons_fn, "openverse": openverse_fn})


class TestCascada:

    def test_commons_manda_y_openverse_solo_completa(self, monkeypatch):
        llamadas = []

        def com(c, n):
            llamadas.append(("commons", n))
            return parsear_commons(json.loads(COMMONS_MITOCONDRIA))

        def ope(c, n):
            llamadas.append(("openverse", n))
            return parsear_openverse(json.loads(OPENVERSE_MITOCONDRIA))

        _fuentes(com, ope, monkeypatch)
        resultados = buscar("mitocondria", 4)
        assert len(resultados) == 4
        # Commons dio 2; a Openverse solo se le piden los 2 que faltan.
        assert llamadas == [("commons", 4), ("openverse", 2)]
        assert [r["fuente"] for r in resultados] == [
            "commons", "commons", "openverse", "openverse"]

    def test_si_commons_llena_el_cupo_no_se_llama_a_openverse(self, monkeypatch):
        llamadas = []

        def com(c, n):
            llamadas.append("commons")
            return parsear_commons(json.loads(COMMONS_MITOCONDRIA))

        def ope(c, n):
            llamadas.append("openverse")
            return []

        _fuentes(com, ope, monkeypatch)
        assert len(buscar("mitocondria", 2)) == 2
        assert llamadas == ["commons"]

    def test_si_una_fuente_cae_se_usa_la_otra_Y_SE_DICE_CUAL_CAYO(self, monkeypatch):
        def com(c, n):
            raise ErrorBusquedaImagenes("Wikimedia Commons: HTTP 503 Service Unavailable")

        def ope(c, n):
            return parsear_openverse(json.loads(OPENVERSE_MITOCONDRIA))

        _fuentes(com, ope, monkeypatch)
        resultados, avisos = buscar_con_avisos("mitocondria", 5)
        assert len(resultados) == 2
        assert any("commons" in a and "503" in a for a in avisos), avisos

    def test_si_caen_las_dos_el_error_nombra_a_las_dos(self, monkeypatch):
        def com(c, n):
            raise ErrorBusquedaImagenes("Wikimedia Commons: no respondio en 28 s")

        def ope(c, n):
            raise ErrorBusquedaImagenes("Openverse: HTTP 429 ...")

        _fuentes(com, ope, monkeypatch)
        with pytest.raises(ErrorBusquedaImagenes) as exc:
            buscar("mitocondria", 5)
        mensaje = str(exc.value)
        assert "Wikimedia Commons" in mensaje
        assert "Openverse" in mensaje

    def test_cero_resultados_con_las_fuentes_VIVAS_no_es_error_pero_no_es_mudo(
            self, monkeypatch):
        """
        Distinguir "no hay imagenes de esto" de "no se pudo preguntar" es todo
        el punto: lo primero devuelve [] con su aviso, lo segundo lanza.
        """
        _fuentes(lambda c, n: [], lambda c, n: [], monkeypatch)
        resultados, avisos = buscar_con_avisos("asdkjhasdkjh", 5)
        assert resultados == []
        assert any("ninguna fuente encontro" in a for a in avisos), avisos

    def test_la_misma_imagen_por_dos_caminos_sale_una_vez(self, monkeypatch):
        """
        Openverse indexa Wikimedia: la MISMA imagen llega con y sin los
        parametros utm que anade la API de Commons. Comparando la url entera
        saldria duplicada en el cuaderno.
        """
        misma = "https://upload.wikimedia.org/wikipedia/commons/d/db/Mitocondria_Cresta_Membrana.jpg"
        pagina = json.loads(COMMONS_MITOCONDRIA)["query"]["pages"][0]
        pagina["imageinfo"][0]["thumburl"] = (
            misma + "?utm_source=commons.wikimedia.org&utm_content=thumbnail")

        def com(c, n):
            return parsear_commons({"query": {"pages": [pagina]}})

        def ope(c, n):
            return parsear_openverse(json.loads(OPENVERSE_MITOCONDRIA))

        _fuentes(com, ope, monkeypatch)
        resultados = buscar("mitocondria", 5)
        assert len(resultados) == 2, [r["url_imagen"] for r in resultados]
        assert resultados[0]["fuente"] == "commons"

    def test_la_MINIATURA_de_commons_y_el_original_de_openverse_son_UNA(
            self, monkeypatch):
        """
        El caso MAYORITARIO, y el que la clave vieja no cazaba.

        Para todo fichero de mas de 800 px, Commons no devuelve la url del
        fichero sino la de una miniatura, con OTRA ruta:
        .../thumb/9/95/X.jpg/960px-X.jpg. Openverse devuelve .../9/95/X.jpg.
        Quitando solo el query string las dos claves salen distintas y la misma
        imagen entra dos veces en el cuaderno. Es exactamente el fichero
        Mitocondria_11 de la respuesta real de arriba, que llega escalado.
        """
        pagina = json.loads(COMMONS_MITOCONDRIA)["query"]["pages"][1]
        assert "/thumb/" in pagina["imageinfo"][0]["thumburl"]  # sigue siendo el caso

        def com(c, n):
            return parsear_commons({"query": {"pages": [pagina]}})

        def ope(c, n):
            # El mismo fichero tal y como lo indexa Openverse: sin /thumb/, sin
            # el segmento 960px- y sin los utm que anade Commons.
            item = json.loads(OPENVERSE_MITOCONDRIA)["results"][0]
            item["url"] = ("https://upload.wikimedia.org/wikipedia/commons/"
                           "9/95/Mitoc%C3%B4ndria_11.jpg")
            return parsear_openverse({"results": [item]})

        _fuentes(com, ope, monkeypatch)
        resultados = buscar("mitocondria", 5)
        assert len(resultados) == 1, [r["url_imagen"] for r in resultados]
        assert resultados[0]["fuente"] == "commons"

    def test_el_mismo_fichero_escapado_distinto_tampoco_se_duplica(self):
        """
        Las dos APIs no codifican igual el mismo nombre: Commons manda
        Mitoc%C3%B4ndria y otra fuente puede mandar el caracter ya decodificado.
        Sin des-escapar, la clave los ve como dos ficheros.
        """
        escapado = {"url_imagen": "https://upload.wikimedia.org/wikipedia/"
                                  "commons/9/95/Mitoc%C3%B4ndria_11.jpg"}
        crudo = {"url_imagen": "https://upload.wikimedia.org/wikipedia/"
                               "commons/9/95/Mitoc\u00f4ndria_11.jpg"}
        assert bi._clave(escapado) == bi._clave(crudo)

    def test_dos_ficheros_DISTINTOS_no_se_confunden(self):
        """
        La clave no puede colapsar de mas: dos miniaturas de ficheros distintos
        siguen siendo dos imagenes.
        """
        uno = {"url_imagen": "https://upload.wikimedia.org/wikipedia/commons/"
                             "thumb/9/95/A.jpg/960px-A.jpg"}
        otro = {"url_imagen": "https://upload.wikimedia.org/wikipedia/commons/"
                              "thumb/9/95/B.jpg/960px-B.jpg"}
        assert bi._clave(uno) != bi._clave(otro)

    def test_una_fuente_desconocida_se_ignora_sin_reventar(self, monkeypatch):
        _fuentes(lambda c, n: parsear_commons(json.loads(COMMONS_MITOCONDRIA)),
                 lambda c, n: [], monkeypatch)
        assert len(buscar("mitocondria", 5, fuentes=("commons", "flickr"))) == 2

    def test_pedir_solo_fuentes_invalidas_lo_dice(self, monkeypatch):
        with pytest.raises(ErrorBusquedaImagenes, match="ninguna fuente valida"):
            buscar("mitocondria", 5, fuentes=("flickr",))



class TestFallosQueNoSonErrorBusquedaImagenes:
    """
    Lo que este modulo dice existir para detectar es un cambio de formato de
    las APIs -- y eso NO llega como ErrorBusquedaImagenes.
    """

    def test_un_AttributeError_del_parser_no_sube_crudo(self, monkeypatch):
        """
        Si Openverse cambia 'results' de lista a dict, el parser revienta con
        AttributeError. Antes eso salia como traceback crudo y se llevaba por
        delante la busqueda entera, incluidos los resultados que Commons YA
        habia dado.
        """
        def com(c, n):
            return parsear_commons(json.loads(COMMONS_MITOCONDRIA))

        def ope(c, n):
            raise AttributeError("'str' object has no attribute 'get'")

        _fuentes(com, ope, monkeypatch)
        resultados, avisos = buscar_con_avisos("mitocondria", 5)
        assert len(resultados) == 2          # lo que dio Commons se salva
        assert any("openverse" in a and "AttributeError" in a
                   for a in avisos), avisos

    def test_el_aviso_dice_donde_mirar(self, monkeypatch):
        def revienta(c, n):
            raise TypeError("string indices must be integers")

        _fuentes(revienta, lambda c, n: [], monkeypatch)
        _, avisos = buscar_con_avisos("mitocondria", 5)
        texto = " ".join(avisos)
        assert "commons" in texto
        assert "TypeError" in texto
        assert "parsear_commons" in texto     # accionable: donde se arregla

    def test_si_las_dos_revientan_por_sorpresa_sigue_siendo_ErrorBusqueda(
            self, monkeypatch):
        """
        Fallan las dos fuentes: el contrato de buscar() no cambia porque el
        fallo sea inesperado.
        """
        def revienta(c, n):
            raise KeyError("results")

        _fuentes(revienta, revienta, monkeypatch)
        with pytest.raises(ErrorBusquedaImagenes) as exc:
            buscar("mitocondria", 5)
        assert "KeyError" in str(exc.value)

    def test_un_KeyboardInterrupt_SI_sube(self, monkeypatch):
        """Capturar lo inesperado no puede significar tragarse un Ctrl-C."""
        def corta(c, n):
            raise KeyboardInterrupt()

        _fuentes(corta, corta, monkeypatch)
        with pytest.raises(KeyboardInterrupt):
            buscar("mitocondria", 5)


class TestErrorDeApiConHttp200:
    """
    MediaWiki contesta 200 con {"error": {...}} cuando la consulta rompe su
    parser. Sin mirar esa clave, parsear_commons devuelve [] y el aviso miente
    diciendo que Commons no tiene imagenes de eso.
    """

    ERROR_MEDIAWIKI = (
        '{"error": {"code": "search-error", "info": "Se produjo un error al '
        'buscar debido a: <a href=\\"//www.mediawiki.org/wiki/Help:CirrusSearch'
        '\\">sintaxis invalida</a>", "*": "ver la doc"}, '
        '"servedby": "mw-api-ext.eqiad.main-6b9"}')

    def test_el_200_con_error_se_convierte_en_ErrorBusquedaImagenes(self):
        with patch("urllib.request.urlopen",
                   return_value=_Respuesta(self.ERROR_MEDIAWIKI)):
            with pytest.raises(ErrorBusquedaImagenes) as exc:
                bi.buscar_commons('mitocondria "', 3)
        mensaje = str(exc.value)
        assert "Wikimedia Commons" in mensaje
        assert "search-error" in mensaje
        assert "sintaxis invalida" in mensaje
        assert "<a href" not in mensaje       # el info de MediaWiki trae HTML

    def test_el_aviso_NO_miente_diciendo_que_no_hay_imagenes(self, monkeypatch):
        """
        El fallo caro: la fuente SI contesto, y lo que dijo fue que la consulta
        esta mal. Confundirlo con "no hay imagenes de esto" manda al duenio a
        cambiar las palabras de la busqueda en vez de a arreglar la consulta.
        """
        def com(c, n):
            with patch("urllib.request.urlopen",
                       return_value=_Respuesta(self.ERROR_MEDIAWIKI)):
                return bi.buscar_commons(c, n)

        _fuentes(com, lambda c, n: [], monkeypatch)
        _, avisos = buscar_con_avisos("mitocondria", 5)
        texto = " ".join(avisos)
        assert "rechazo la consulta" in texto, avisos
        assert "commons no aporto imagenes" not in texto, avisos

    def test_una_respuesta_normal_sigue_pasando(self):
        """La deteccion no puede dispararse con la respuesta buena de siempre."""
        with patch("urllib.request.urlopen",
                   return_value=_Respuesta(COMMONS_MITOCONDRIA)):
            assert len(bi.buscar_commons("mitocondria", 3)) == 2


class TestPuertaDeDiagnostico:

    def test_estado_imprime_la_config(self, capsys):
        assert bi._main(["estado"]) == 0
        salida = capsys.readouterr().out
        assert "commons" in salida and "openverse" in salida
        assert str(bi.TIMEOUT) in salida

    def test_el_error_sale_legible_y_con_codigo_1(self, capsys, monkeypatch):
        def cae(c, n):
            raise ErrorBusquedaImagenes("Wikimedia Commons: HTTP 503 x")

        _fuentes(cae, cae, monkeypatch)
        assert bi._main(["mitocondria", "3"]) == 1
        assert "ERROR" in capsys.readouterr().out


class TestDeduplicacionEntreHosts:
    r"""
    La MISMA imagen servida por DOS HOSTS de Wikimedia sigue siendo UNA.

    Medido el 2026-08-31 llamando a la API de verdad: en una sola respuesta de
    Commons conviven

        thumb.wikimedia.org/wikipedia/commons/thumb/9/95/X.jpg/960px-X.jpg
        upload.wikimedia.org/wikipedia/commons/0/0c/Y.jpg   (sin escalar)

    y Openverse indexa esos mismos ficheros por upload.wikimedia.org. Con el
    netloc crudo dentro de la clave de deduplicacion, la imagen entra DOS VECES
    en el cuaderno -- y el cuaderno se exporta a PDF, asi que el duenio se
    encuentra la misma foto repetida con dos creditos.

    POR QUE NO LO CAZABA NINGUN TEST. Los fixtures de arriba se capturaron
    cuando las miniaturas venian de upload.wikimedia.org, asi que
    test_la_MINIATURA_de_commons_y_el_original_de_openverse_son_UNA compara dos
    urls del MISMO host y pasa igual con la clave rota: pasa por el motivo
    equivocado. Estos tests fijan la url de Commons al host que la API devuelve
    HOY.
    """

    # Un mismo fichero, tal y como lo dan las dos fuentes hoy.
    THUMB = ("https://thumb.wikimedia.org/wikipedia/commons/thumb/9/95/"
             "Mitoc%C3%B4ndria_11.jpg/960px-Mitoc%C3%B4ndria_11.jpg"
             "?utm_source=commons.wikimedia.org&utm_content=thumbnail")
    ORIGINAL = ("https://upload.wikimedia.org/wikipedia/commons/9/95/"
                "Mitoc%C3%B4ndria_11.jpg")

    def test_la_miniatura_de_thumb_y_el_original_de_upload_son_UNA(self):
        assert bi._clave({"url_imagen": self.THUMB}) == \
               bi._clave({"url_imagen": self.ORIGINAL})

    def test_la_imagen_no_se_duplica_en_el_cuaderno(self, monkeypatch):
        """El caso de punta a punta: es lo que ve quien busca en el cuaderno."""
        pagina = json.loads(COMMONS_MITOCONDRIA)["query"]["pages"][1]
        pagina["imageinfo"][0]["thumburl"] = self.THUMB

        def com(c, n):
            return parsear_commons({"query": {"pages": [pagina]}})

        def ope(c, n):
            item = json.loads(OPENVERSE_MITOCONDRIA)["results"][0]
            item["url"] = self.ORIGINAL
            return parsear_openverse({"results": [item]})

        _fuentes(com, ope, monkeypatch)
        resultados = buscar("mitocondria", 5)
        assert len(resultados) == 1, [r["url_imagen"] for r in resultados]
        assert resultados[0]["fuente"] == "commons"

    def test_dos_ficheros_DISTINTOS_de_hosts_distintos_siguen_siendo_dos(self):
        """
        Normalizar el host no puede colapsar de mas.

        Perder una imagen es peor que repetirla: la repetida se ve, la perdida
        no. Dos ficheros distintos de Wikimedia siguen dando dos claves.
        """
        uno = {"url_imagen": "https://thumb.wikimedia.org/wikipedia/commons/"
                             "thumb/9/95/A.jpg/960px-A.jpg"}
        otro = {"url_imagen": "https://upload.wikimedia.org/wikipedia/commons/"
                              "9/95/B.jpg"}
        assert bi._clave(uno) != bi._clave(otro)

    def test_un_dominio_AJENO_no_se_confunde_con_wikimedia(self):
        """
        La normalizacion es por sufijo de dominio, y un sufijo mal comparado es
        una frontera falsa: 'malwikimedia.org' NO es wikimedia.org, y una
        fuente futura (ver FUENTES) que sirva la misma ruta desde su propio CDN
        tampoco puede fundirse con el fichero de Wikimedia.
        """
        wiki = {"url_imagen": "https://upload.wikimedia.org/wikipedia/commons/"
                              "9/95/A.jpg"}
        parecido = {"url_imagen": "https://malwikimedia.org/wikipedia/commons/"
                                  "9/95/A.jpg"}
        ajeno = {"url_imagen": "https://cdn.otrafuente.example/wikipedia/"
                               "commons/9/95/A.jpg"}
        assert bi._clave(wiki) != bi._clave(parecido)
        assert bi._clave(wiki) != bi._clave(ajeno)


class TestLosTestsDeRedNoCorrenSolos:
    """
    Un test que sale a internet en CI es una bomba de relojeria ajena.

    El CI corre en ubuntu con requirements.txt y SIN red garantizada: si un
    test consulta a Wikimedia, el rojo no dice nada de este repo y ademas
    cuesta TIMEOUT segundos por consulta. Este test offline vigila que el
    candado siga puesto, porque el fallo tipico es anadir un cuarto test a esa
    clase... o crear una clase nueva sin acordarse de marcarla.
    """

    def test_la_clase_de_red_lleva_marca_Y_candado(self):
        marcas = getattr(TestContraLasApisDeVerdad, "pytestmark", [])
        nombres = {m.name for m in marcas}
        assert "red" in nombres, nombres
        assert "skipif" in nombres, nombres

    def test_el_candado_va_EN_LOS_DOS_SENTIDOS(self):
        """
        No basta con que el skipif este: tiene que estar bien puesto.

        Se compara la condicion REAL de la marca (evaluada al importar el
        fichero) con el estado de la variable. Sin la variable la condicion
        tiene que ser cierta (el CI se los salta) y con ella puesta tiene que
        ser falsa (el duenio SI puede correrlos). Si alguien invierte el
        skipif, cae por un lado o por el otro; sin este test el fallo seria
        mudo: unos tests que ya no se ejecutan nunca no se quejan.
        """
        skipif = [m for m in TestContraLasApisDeVerdad.pytestmark
                  if m.name == "skipif"][0]
        pedidos = bool(os.environ.get("COGNIA_TESTS_RED"))
        assert bool(skipif.args[0]) is (not pedidos), (
            "COGNIA_TESTS_RED=%r pero la condicion de salto evaluo a %r"
            % (os.environ.get("COGNIA_TESTS_RED"), skipif.args[0]))

@pytest.mark.red
@pytest.mark.skipif(
    not os.environ.get("COGNIA_TESTS_RED"),
    reason="sale a internet: correr a proposito con COGNIA_TESTS_RED=1")
class TestContraLasApisDeVerdad:
    r"""
    Los unicos tests que salen a internet. NO corren en la suite normal.

    POR QUE HAY DOS CANDADOS (marca `red` + variable de entorno). El marcador
    solo sirve si quien corre pytest se acuerda de escribir -m "not red", y el
    pytest.ini de este repo no lo pone en addopts: sin la variable, la suite
    normal SI salia a la red. El CI (ubuntu, requirements.txt) no tiene red
    garantizada, y un test que depende de una API ajena no falla por lo que
    hace este repo -- falla por lo que hizo Wikimedia esa manana. Peor aun:
    cuando no hay red cada consulta se come el TIMEOUT de 28 s antes de
    saltarse.

    CORRERLOS A PROPOSITO (es lo que hay que hacer cuando se sospecha que una
    de las dos APIs cambio de formato):

        COGNIA_TESTS_RED=1 venv312/Scripts/python.exe -m pytest \
            tests/test_busqueda_imagenes.py -m red -q

    o en PowerShell:

        $env:COGNIA_TESTS_RED=1; venv312\Scripts\python.exe -m pytest `
            tests/test_busqueda_imagenes.py -m red -q

    Existen porque el formato de las dos APIs se descubrio midiendo: si
    Wikimedia o Openverse cambian, aqui se ve. Lo que NO pueden hacer es
    afirmar cosas que la API nunca prometio (ver el test de abajo).
    """

    def test_commons_devuelve_imagenes_con_atribucion(self):
        """
        Lo que importa de una url de Commons es que se pueda BAJAR, no el host.

        POR QUE SE CAMBIO EL ASSERT VIEJO. Decia
        `startswith("https://upload.wikimedia.org/")`, y el 2026-08-31 se puso
        rojo: la API empezo a servir las miniaturas escaladas desde
        thumb.wikimedia.org (los originales sin escalar siguen en upload, en la
        MISMA respuesta). Ese assert estaba clavado a un detalle de
        infraestructura que Wikimedia nunca prometio y que el cuaderno no
        necesita: se comprobo bajando las urls nuevas con
        almacen.descargar_adjunto y pasan todas sus guardas (http/https,
        Content-Type de imagen, tope de tamanio). O sea que era ruido de test
        -- y ademas ruido CARO, porque tapaba un fallo de producto de verdad
        que el mismo cambio de host provoco: la deduplicacion entre Commons y
        Openverse metia la clave del host en la clave del fichero y dejo de
        funcionar (ver TestDeduplicacionEntreHosts).

        Lo que se comprueba ahora es lo que de verdad tiene que cumplirse:
        dominio de Wikimedia (no vale que la API nos mande a cualquier sitio) y
        la url ALCANZABLE devolviendo una imagen, que es la condicion exacta
        que descargar_adjunto va a exigir despues.
        """
        import urllib.request

        try:
            resultados = bi.buscar_commons("mitocondria", 3)
        except ErrorBusquedaImagenes as e:
            pytest.skip(f"sin acceso a Commons: {e}")
        assert resultados, "Commons no devolvio nada"
        for r in resultados:
            assert r["licencia"] and r["url_pagina"]
            partes = urllib.parse.urlsplit(r["url_imagen"])
            assert partes.scheme == "https", r["url_imagen"]
            assert (partes.netloc == "wikimedia.org"
                    or partes.netloc.endswith(".wikimedia.org")), r["url_imagen"]

        # Descargable de verdad: se pide UNA (no las tres) porque esto es una
        # peticion a un tercero, y con una basta para cazar el dia en que la
        # API devuelva urls que no responden.
        req = urllib.request.Request(
            resultados[0]["url_imagen"], method="HEAD",
            headers={"User-Agent": bi.USER_AGENT})
        with urllib.request.urlopen(req, timeout=bi.TIMEOUT) as resp:
            assert resp.status == 200
            tipo = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            assert tipo.startswith("image/"), tipo

    def test_la_thumburl_de_la_api_RESPONDE_y_la_fabricada_no(self):
        """
        El dato medido, comprobado: la miniatura que devuelve la API se puede
        pedir, y la que se construye a mano da 400. Solo se piden cabeceras
        (HEAD): descargar es trabajo de almacen.descargar_adjunto.
        """
        import urllib.request

        try:
            resultados = bi.buscar_commons("mitocondria", 3)
        except ErrorBusquedaImagenes as e:
            pytest.skip(f"sin acceso a Commons: {e}")
        buena = None
        for r in resultados:
            if "/thumb/" in r["url_imagen"]:
                buena = r["url_imagen"]
                break
        if not buena:
            pytest.skip("ningun resultado con miniatura escalada esta vez")

        def cabeza(url):
            req = urllib.request.Request(
                url, method="HEAD", headers={"User-Agent": bi.USER_AGENT})
            with urllib.request.urlopen(req, timeout=bi.TIMEOUT) as resp:
                return resp.status

        assert cabeza(buena) == 200
        # La misma url con el ancho cambiado a uno cualquiera: la miniatura no
        # es una funcion del nombre del fichero.
        import re as _re
        inventada = _re.sub(r"/\d+px-", "/797px-", buena)
        if inventada == buena:
            pytest.skip("no se pudo construir la url inventada")
        with pytest.raises(urllib.error.HTTPError):
            cabeza(inventada)

    def test_openverse_devuelve_imagenes_con_atribucion(self):
        try:
            resultados = bi.buscar_openverse("mitocondria", 3)
        except ErrorBusquedaImagenes as e:
            pytest.skip(f"sin acceso a Openverse: {e}")
        assert resultados, "Openverse no devolvio nada"
        for r in resultados:
            assert r["licencia"] and r["url_pagina"] and r["autor"]
