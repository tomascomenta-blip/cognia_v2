"""
tests/test_presupuesto_dinamico.py
Presupuesto DINAMICO de generacion (cognia/program_creator/generator.py).

Regresion 2026-08-02: el presupuesto era una constante (12000, luego 24000 para
html). Una landing medida pedia 15.472 tokens; con la constante corta la salida
volvia truncada, el intento se perdia y la sesion cerraba 0/2 leyendose como
"el modelo no supo hacerlo".
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from cognia.program_creator import generator as g


@pytest.fixture(autouse=True)
def memoria_aislada(tmp_path, monkeypatch):
    """La memoria de presupuesto vive en tmp_path, no en el ~/.cognia real."""
    monkeypatch.setattr(g, "_memoria_presupuesto",
                        lambda: tmp_path / "presupuesto_generacion.json")
    yield tmp_path


# ---------------------------------------------------------------------------
# techo_generacion(): sale del n_ctx REAL, no de un literal
# ---------------------------------------------------------------------------

class TestTecho:
    def test_escala_con_el_n_ctx_del_server(self):
        """200k de contexto tienen que dar MUCHO mas techo que 8k."""
        def props_con(n):
            return lambda *a, **k: {"n_ctx": n}
        with patch("cognia.llm_local.detectar_backend",
                   return_value={"url": "http://127.0.0.1:8080"}):
            with patch("cognia.backend_activo.props", props_con(200192)):
                grande = g.techo_generacion(2400)
            with patch("cognia.backend_activo.props", props_con(8192)):
                chico = g.techo_generacion(2400)
        assert grande > 100_000
        assert chico < 10_000
        assert grande > chico * 10

    def test_sin_server_no_lanza(self):
        """Un fallo sondeando el backend no puede tumbar la generacion."""
        with patch("cognia.llm_local.detectar_backend",
                   side_effect=RuntimeError("sin red")):
            assert g.techo_generacion(1000) > 0

    def test_reserva_el_prompt(self):
        """Un prompt enorme deja MENOS techo: si no, llega el HTTP 400."""
        with patch("cognia.llm_local.detectar_backend",
                   return_value={"url": "http://127.0.0.1:8080"}), \
             patch("cognia.backend_activo.props", lambda *a, **k: {"n_ctx": 32768}):
            assert g.techo_generacion(300_000) < g.techo_generacion(1000)


# ---------------------------------------------------------------------------
# memoria: lo que hizo falta se recuerda
# ---------------------------------------------------------------------------

class TestMemoria:
    def test_recuerda_y_arranca_mas_alto(self):
        # Techo FIJADO por patch (2026-08-09): con el server real de la flota
        # encendido (ctx 16384) la base YA es el techo y "recordar" no puede
        # subirla — el test dependia del backend vivo de la maquina. Con un
        # n_ctx grande el techo deja de ser la restriccion activa y se prueba
        # la invariante que importa: el recuerdo SUBE el arranque.
        with patch("cognia.llm_local.detectar_backend",
                   return_value={"url": "http://127.0.0.1:8080"}), \
             patch("cognia.backend_activo.props",
                   lambda *a, **k: {"n_ctx": 200192}):
            base = g.presupuesto_inicial("html", 1000)
            g.recordar_presupuesto("html", base * 3)
            assert g.presupuesto_inicial("html", 1000) > base

    def test_no_baja_el_recuerdo(self):
        g.recordar_presupuesto("html", 50_000)
        g.recordar_presupuesto("html", 5_000)
        assert g._presupuesto_recordado("html") == 50_000

    def test_nunca_supera_el_techo(self):
        g.recordar_presupuesto("html", 10_000_000)
        with patch("cognia.llm_local.detectar_backend",
                   return_value={"url": "http://127.0.0.1:8080"}), \
             patch("cognia.backend_activo.props", lambda *a, **k: {"n_ctx": 8192}):
            assert g.presupuesto_inicial("html", 1000) <= g.techo_generacion(1000)

    def test_memoria_corrupta_no_lanza(self, memoria_aislada):
        memoria_aislada.joinpath("presupuesto_generacion.json").write_text(
            "{esto no es json", encoding="utf-8")
        assert g._presupuesto_recordado("html") == 0
        assert g.presupuesto_inicial("html", 1000) > 0


# ---------------------------------------------------------------------------
# _parse_response: distingue TRUNCADO de rechazado
# ---------------------------------------------------------------------------

class TestSenalDeTruncado:
    def test_marca_truncado_con_fence_abierto(self):
        crudo = "Title: X\nDescription: Y\n```html\n<html><body>a medio es"
        detalles: dict = {}
        assert g._parse_response(crudo, "web", "html", detalles) is None
        assert detalles.get("truncado") is True

    def test_no_marca_truncado_si_no_hay_fence(self):
        """Sin bloque no es truncado: mas tokens no lo arreglan."""
        detalles: dict = {}
        assert g._parse_response("no hay codigo aqui", "web", "html", detalles) is None
        assert "truncado" not in detalles

    def test_detalles_es_opcional(self):
        """Los call sites viejos siguen funcionando sin pasarlo."""
        assert g._parse_response("nada", "web", "html") is None


# ---------------------------------------------------------------------------
# ESCALADA: el corazon del asunto
# ---------------------------------------------------------------------------

_PAGINA_OK = (
    "Title: T\nDescription: D\n```html\n"
    "<html><head><title>T</title></head><body><h1>hola</h1>"
    + "<p>relleno</p>" * 5 +
    "</body></html>\n```"
)
_TRUNCADA = "Title: T\nDescription: D\n```html\n<html><body>cortada a mitad"


class TestEscalada:
    def test_dobla_el_presupuesto_y_reintenta(self):
        """Truncado -> dobla -> lo consigue. Un truncado no puede perder el intento."""
        pedidos = []

        def fake_call(prompt, lenguaje="python", **kw):
            pedidos.append(kw.get("max_tokens"))
            return _TRUNCADA if len(pedidos) == 1 else _PAGINA_OK

        with patch.object(g, "_call_llm", fake_call), \
             patch.object(g, "techo_generacion", lambda *a, **k: 200_000), \
             patch.object(g, "presupuesto_inicial", lambda *a, **k: 16_000):
            prog = g.generate_program(forced_idea="una pagina web de prueba",
                                      llm=lambda *a, **k: None)
        assert prog is not None, "tras escalar deberia haber programa"
        assert pedidos == [16_000, 32_000], f"esperaba doblar; pedidos={pedidos}"

    def test_no_escala_por_encima_del_techo(self):
        """En el techo se PARA y lo dice: escalar mas daria HTTP 400."""
        pedidos = []

        def fake_call(prompt, lenguaje="python", **kw):
            pedidos.append(kw.get("max_tokens"))
            return _TRUNCADA

        with patch.object(g, "_call_llm", fake_call), \
             patch.object(g, "techo_generacion", lambda *a, **k: 20_000), \
             patch.object(g, "presupuesto_inicial", lambda *a, **k: 16_000):
            prog = g.generate_program(forced_idea="una pagina web de prueba",
                                      llm=lambda *a, **k: None)
        assert prog is None
        assert pedidos == [16_000, 20_000], f"pedidos={pedidos}"

    def test_no_escala_si_no_es_truncado(self):
        """Basura no se arregla con mas tokens: una sola llamada."""
        pedidos = []

        def fake_call(prompt, lenguaje="python", **kw):
            pedidos.append(kw.get("max_tokens"))
            return "el modelo devolvio prosa sin codigo"

        with patch.object(g, "_call_llm", fake_call), \
             patch.object(g, "techo_generacion", lambda *a, **k: 200_000), \
             patch.object(g, "presupuesto_inicial", lambda *a, **k: 16_000):
            g.generate_program(forced_idea="una pagina web de prueba",
                               llm=lambda *a, **k: None)
        assert len(pedidos) == 1, f"no debia reintentar; pedidos={pedidos}"


# ---------------------------------------------------------------------------
# finish_reason='length': la senal que ANTES se disfrazaba de "sin backend"
# ---------------------------------------------------------------------------

class TestSenalFinishLength:
    def test_length_sin_contenido_no_es_sin_backend(self, capsys):
        """Presupuesto agotado con el server SANO no puede reportarse como
        ausencia de backend: es el diagnostico falso que impedia reintentar."""
        from cognia import llm_local as ll
        ll.ultimo_detalle.clear()
        ll.ultimo_detalle.update({"finish_reason": "length", "pedidos": 2000,
                                  "tokens": 2000})
        with patch.object(g, "generar", return_value=""), \
             patch("cognia.backend_activo.sin_backend") as sin_backend, \
             patch.object(g, "_call_ollama", return_value="NO-DEBERIA-LLAMARSE"):
            out = g._call_llm("prompt", "html")
        assert out is None
        sin_backend.assert_not_called()
        assert "falta presupuesto" in capsys.readouterr().out

    def test_escala_con_length_aunque_raw_sea_none(self):
        """El caso REAL medido: el modelo gasta todo el presupuesto pensando y
        devuelve vacio. Sin fence no hay senal de truncado — tiene que bastar
        finish_reason='length' o la escalada nunca arranca."""
        from cognia import llm_local as ll
        pedidos = []

        def fake_call(prompt, lenguaje="python", **kw):
            mt = kw.get("max_tokens")
            pedidos.append(mt)
            if mt < 8000:
                ll.ultimo_detalle.clear()
                ll.ultimo_detalle.update({"finish_reason": "length", "pedidos": mt})
                return None                      # vacio: todo el budget pensando
            ll.ultimo_detalle.clear()
            ll.ultimo_detalle.update({"finish_reason": "stop", "pedidos": mt})
            return _PAGINA_OK

        with patch.object(g, "_call_llm", fake_call), \
             patch.object(g, "techo_generacion", lambda *a, **k: 200_000), \
             patch.object(g, "presupuesto_inicial", lambda *a, **k: 2_000):
            prog = g.generate_program(forced_idea="una pagina web de prueba",
                                      llm=lambda *a, **k: None)
        assert prog is not None
        assert pedidos == [2_000, 4_000, 8_000], f"pedidos={pedidos}"
