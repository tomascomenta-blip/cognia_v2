"""
Cliente MCP nativo para servidores gratuitos y sin registro.

Pedido del dueno el 2026-07-20: poder usar "MCP gratuitos y sin registro ni
apikey, y que todo venga de forma nativa". Cognia no tenia ningun soporte.

El protocolo se midio contra gitmcp.io ANTES de escribir el modulo, y de ahi
salieron los dos detalles que estos tests fijan y que no estan en ninguna
documentacion obvia:

  1. `tools/list` sin sesion devuelve `Bad Request: Mcp-Session-Id header is
     required`. La sesion NO viene en el JSON del initialize: viene en la
     cabecera `mcp-session-id` de la respuesta.
  2. Sin User-Agent propio, Cloudflare corta con 403 (error 1010). La misma
     peticion pasaba con curl y fallaba con urllib, que es lo que delata que
     el problema es la cabecera y no el protocolo.

Los tests de red van marcados y se saltan solos si no hay conexion: la suite
no puede depender de que un servicio de terceros este arriba.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from cognia.mcp_libre import (
    SERVIDORES_LIBRES,
    USER_AGENT,
    ClienteMCP,
    ErrorMCP,
    Herramienta,
    _parsear_respuesta,
    cliente,
    formatear_servidores,
)

SSE = ('event: message\n'
       'data: {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"GitMCP"}}}\n')


class TestParseoDeRespuesta:
    """Los servidores remotos responden SSE; algunos, JSON pelado."""

    def test_lee_sse(self):
        assert _parsear_respuesta(SSE)["result"]["serverInfo"]["name"] == "GitMCP"

    def test_lee_json_pelado(self):
        assert _parsear_respuesta('{"jsonrpc":"2.0","id":1,"result":{}}')["id"] == 1

    def test_respuesta_vacia_es_error_claro(self):
        with pytest.raises(ErrorMCP, match="vacia"):
            _parsear_respuesta("   ")

    def test_respuesta_sin_json_es_error_claro(self):
        with pytest.raises(ErrorMCP, match="no se encontro JSON"):
            _parsear_respuesta("event: ping\nretry: 1000\n")


class TestSesion:
    """La sesion llega por cabecera, no por el cuerpo. Sin ella no se puede."""

    def _respuesta(self, cuerpo, cabeceras=None):
        r = MagicMock()
        r.read.return_value = cuerpo.encode("utf-8")
        r.headers = cabeceras or {}
        r.__enter__ = lambda s: r
        r.__exit__ = lambda s, *a: False
        return r

    def test_guarda_la_sesion_de_la_cabecera(self):
        c = ClienteMCP("https://ejemplo/mcp")
        with patch("urllib.request.urlopen",
                   return_value=self._respuesta(SSE, {"mcp-session-id": "abc123"})):
            c.conectar()
        assert c.sesion == "abc123"

    def test_manda_la_sesion_en_las_siguientes_llamadas(self):
        c = ClienteMCP("https://ejemplo/mcp")
        c.sesion = "abc123"
        capturada = {}

        def falso_urlopen(req, timeout=None):
            capturada.update(req.headers)
            return self._respuesta(
                'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')

        with patch("urllib.request.urlopen", side_effect=falso_urlopen):
            c.listar_herramientas()

        claves = {k.lower() for k in capturada}
        assert "mcp-session-id" in claves

    def test_siempre_manda_user_agent_propio(self):
        """Sin esto Cloudflare devuelve 403 y parece un fallo de protocolo."""
        c = ClienteMCP("https://ejemplo/mcp")
        capturada = {}

        def falso_urlopen(req, timeout=None):
            capturada.update(req.headers)
            return self._respuesta(SSE, {})

        with patch("urllib.request.urlopen", side_effect=falso_urlopen):
            c.conectar()

        cabeceras = {k.lower(): v for k, v in capturada.items()}
        assert cabeceras.get("User-agent".lower()) == USER_AGENT
        assert "python-urllib" not in cabeceras.get("User-agent".lower(), "").lower()


class TestErrores:

    def test_un_error_rpc_se_convierte_en_ErrorMCP(self):
        c = ClienteMCP("https://ejemplo/mcp")
        c.sesion = "x"
        cuerpo = ('data: {"jsonrpc":"2.0","id":1,"error":'
                  '{"code":-32000,"message":"Mcp-Session-Id header is required"}}')

        r = MagicMock()
        r.read.return_value = cuerpo.encode()
        r.headers = {}
        r.__enter__ = lambda s: r
        r.__exit__ = lambda s, *a: False

        with patch("urllib.request.urlopen", return_value=r):
            with pytest.raises(ErrorMCP, match="Mcp-Session-Id"):
                c.listar_herramientas()

    def test_sin_red_no_revienta_con_traceback_crudo(self):
        c = ClienteMCP("https://ejemplo/mcp")
        with patch("urllib.request.urlopen", side_effect=OSError("sin red")):
            with pytest.raises(ErrorMCP, match="no se pudo hablar"):
                c.conectar()


class TestRegistro:

    def test_solo_hay_servidores_libres(self):
        for nombre, info in SERVIDORES_LIBRES.items():
            assert info["url"].startswith("https://"), nombre
            assert info["que_hace"], nombre
            assert info["verificado"], f"{nombre} sin fecha de verificacion"

    def test_servidor_desconocido_avisa_de_los_que_hay(self):
        with pytest.raises(ErrorMCP, match="desconocido"):
            cliente("no-existe")

    def test_el_listado_dice_que_no_piden_clave(self):
        texto = formatear_servidores()
        assert "gitmcp" in texto
        assert "clave" in texto.lower()


class TestHerramienta:

    def test_el_resumen_se_recorta(self):
        h = Herramienta("buscar", "d" * 400)
        assert len(h.resumen()) < 140


@pytest.mark.red
class TestContraElServidorDeVerdad:
    """
    Se salta solo si no hay red. Existe porque el protocolo se descubrio
    midiendo, y si gitmcp cambia, aqui se ve.
    """

    def _cliente(self):
        try:
            c = cliente("gitmcp")
            c.conectar()
            return c
        except ErrorMCP as exc:
            pytest.skip(f"sin acceso a gitmcp.io: {exc}")

    def test_conecta_y_se_identifica(self):
        c = self._cliente()
        assert c.sesion, "no devolvio sesion"
        assert c.servidor.get("name")

    def test_lista_herramientas_reales(self):
        hs = self._cliente().listar_herramientas()
        assert hs, "un servidor MCP sin herramientas no sirve de nada"
        assert any("documentation" in h.nombre or "search" in h.nombre for h in hs)


class TestHerramientasDelAgente:
    """
    El cliente MCP solo vale si Cognia puede usarlo MIENTRAS trabaja, no solo
    desde la CLI. Eso es lo que hace un agente de coding.
    """

    def test_estan_registradas(self):
        from cognia.agent.tools import TOOLS
        assert "docs_repo" in TOOLS
        assert "buscar_en_repo" in TOOLS

    def test_salen_en_el_prompt_del_agente(self):
        from cognia.agent.tools import build_tools_doc
        doc = build_tools_doc()
        assert "docs_repo" in doc
        assert "buscar_en_repo" in doc

    def test_ninguna_esta_marcada_peligrosa(self):
        """Ambas solo leen: ni escriben ni gastan dinero."""
        from cognia.agent.tools import TOOLS
        assert TOOLS["docs_repo"]["danger"] is False
        assert TOOLS["buscar_en_repo"]["danger"] is False

    @pytest.mark.parametrize("herramienta,args", [
        ("docs_repo",      "solo-owner"),
        ("buscar_en_repo", "owner repo"),
    ])
    def test_argumentos_incompletos_dan_error_util(self, herramienta, args):
        """Un error debe decir como se usa, no soltar un traceback."""
        from cognia.agent.tools import run_tool
        salida = run_tool(herramienta, args, {})
        assert "ERROR" in salida
        assert "uso:" in salida

    def test_un_fallo_de_red_no_tumba_el_bucle(self):
        from cognia.agent.tools import run_tool
        from cognia.mcp_libre import ErrorMCP

        with patch("cognia.mcp_libre.ClienteMCP.llamar",
                   side_effect=ErrorMCP("sin red")):
            salida = run_tool("buscar_en_repo", "a b c", {})

        assert "ERROR" in salida and "sin red" in salida


class TestMasServidoresLibres:
    """
    Los tres se verificaron a mano el 2026-07-20 con este mismo cliente, no
    solo sondeando el puerto: `initialize` + `tools/list` + una llamada real.
    Ninguno pide registro ni clave, que es la condicion que puso el dueno.
    """

    @pytest.mark.parametrize("nombre", ["gitmcp", "context7", "deepwiki"])
    def test_estan_registrados(self, nombre):
        assert nombre in SERVIDORES_LIBRES

    @pytest.mark.parametrize("nombre", ["gitmcp", "context7", "deepwiki"])
    def test_cada_uno_dice_que_aporta(self, nombre):
        info = SERVIDORES_LIBRES[nombre]
        assert len(info["que_hace"]) > 40, "una URL sin contexto no ayuda a elegir"
        assert info["verificado"]

    def test_las_herramientas_nuevas_estan_en_el_agente(self):
        from cognia.agent.tools import TOOLS
        assert "preguntar_repo" in TOOLS
        assert "docs_libreria" in TOOLS

    @pytest.mark.parametrize("herramienta,args", [
        ("preguntar_repo", "sin-barra pregunta"),
        ("docs_libreria",  ""),
    ])
    def test_argumentos_malos_explican_el_uso(self, herramienta, args):
        from cognia.agent.tools import run_tool
        salida = run_tool(herramienta, args, {})
        assert "ERROR" in salida and "uso:" in salida
