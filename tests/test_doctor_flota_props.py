"""
Regresion WP6 (2026-08-09): el doctor sondeaba la flota por /health y decia
"flota apagada" como WARN — es decir, terminaba "Todo en orden. Cognia esta
lista." con la flota muerta, y un server rancio sirviendo OTRO modelo (la
averia historica del :8088 con el 7B RETIRADO) era invisible porque /health
responde 200 sirva lo que sirva.

Ahora check_flota consulta /props (via backend_activo), reporta el GGUF REAL
de cada puerto, y flota apagada / modelo retirado / modelo ajeno = FAIL con
la orden exacta para arreglarlo.
"""

import pytest

import cognia.backend_activo as BA
import cognia.doctor as D


@pytest.fixture
def props(monkeypatch):
    """Fija que responde cada puerto sin tocar la red: {puerto: props_dict}."""
    tabla = {}

    def fake_props(url, forzar=False):
        puerto = int(url.rsplit(":", 1)[1].split("/")[0])
        return tabla.get(puerto, {})

    monkeypatch.setattr(BA, "props", fake_props)
    return tabla


class TestFlotaApagadaEsFallo:

    def test_apagada_devuelve_False(self, props):
        # Antes: _warn -> True -> "Todo en orden" con la flota muerta.
        assert D.check_flota() is False

    def test_apagada_da_la_orden_exacta(self, props, capsys):
        D.check_flota()
        out = capsys.readouterr().out
        assert "[FAIL]" in out
        assert "python -m cognia flota arrancar pensar" in out

    def test_solo_vlm_vivo_sigue_siendo_fallo(self, props):
        # :8081 arriba sin cerebro en :8080 no es una flota que piense.
        props[8081] = {"modelo": "Qwen2.5-VL-3B.gguf", "puerto": 8081}
        assert D.check_flota() is False


class TestModeloRancio:

    def test_modelo_retirado_en_8080_es_FALLO(self, props, capsys):
        # La averia historica: el 7B retirado por la auditoria de flota del
        # 2026-07-24 atendiendo el chat. /health lo daba por sano.
        props[8080] = {"modelo": "qwen2.5-7b-instruct-q4_k_m.gguf",
                       "n_ctx": 8192, "puerto": 8080}
        assert D.check_flota() is False
        assert "RETIRADO" in capsys.readouterr().out

    def test_modelo_ajeno_a_la_flota_es_FALLO(self, props, capsys):
        # Un GGUF que no es el cerebro de ningun combo: alguien sirvio otra
        # cosa en el puerto de Cognia. Decirlo, no aprobarlo.
        props[8080] = {"modelo": "mistral-7b-v0.3-q4.gguf",
                       "n_ctx": 8192, "puerto": 8080}
        assert D.check_flota() is False
        assert "ningun combo" in capsys.readouterr().out


class TestFlotaSana:

    def test_pensador_solo_es_OK_con_warn_de_vlm(self, props, capsys):
        # gpt-oss-20b corre SOLO (GPU entera): :8081 caido es WARN, no FAIL.
        props[8080] = {"modelo": "gpt-oss-20b-mxfp4.gguf",
                       "n_ctx": 16384, "puerto": 8080}
        assert D.check_flota() is True
        out = capsys.readouterr().out
        assert "[WARN]" in out
        assert "gpt-oss-20b-mxfp4.gguf" in out   # el GGUF real, visible

    def test_flota_completa_reporta_ambos_gguf(self, props, capsys):
        props[8080] = {"modelo": "qwen2.5-coder-14b-instruct-q4_k_m.gguf",
                       "n_ctx": 8192, "puerto": 8080}
        props[8081] = {"modelo": "Qwen2.5-VL-3B-Instruct-q4.gguf",
                       "n_ctx": 4096, "puerto": 8081}
        assert D.check_flota() is True
        out = capsys.readouterr().out
        assert "[OK]" in out
        assert "coder-14b" in out
        assert "VL-3B" in out
        assert "combo 'construir'" in out   # comparado con la flota esperada
