# -*- coding: utf-8 -*-
"""Tests de la linea de estado VIVA del turno (F2, cognia/ux/spinner_vivo).

La composicion es PURA (verbo + segundos + ~tokens + hint) y se testea sin
terminal; el cableado al renderer (contador de chars, ticker sobre el rich
status) se testea con dobles minimos. Regresion: sin el fix el Renderer no
tiene _chars_stream/_ticker y estos tests revientan con AttributeError.
"""
import sys
import time
import types

import pytest

from cognia.ux import events, spinner_vivo
from cognia.ux.renderer import Renderer


# ---------------------------------------------------------------------------
# componer_linea: las tres preguntas, y el truncado elegante
# ---------------------------------------------------------------------------

def test_linea_completa_responde_las_tres_preguntas():
    linea = spinner_vivo.componer_linea("Maullando ideas", 12, tokens=340,
                                        ancho=100)
    assert "Maullando ideas…" in linea      # ¿esta vivo? (verbo)
    assert "12s" in linea                    # ¿cuanto lleva?
    assert "~340 tok" in linea               # ¿que llega?
    assert "ctrl+c corta" in linea           # ¿como lo paro? (el gesto REAL)


def test_sin_tokens_no_inventa_conteo():
    linea = spinner_vivo.componer_linea("Cazando el bug", 3, tokens=0)
    assert "tok" not in linea
    assert "3s" in linea and "ctrl+c corta" in linea


def test_ancho_estrecho_caen_los_tokens_primero():
    # entra verbo + segundos + hint pero no los tokens
    linea = spinner_vivo.componer_linea("Atando cabos", 9, tokens=1200,
                                        ancho=40)
    assert len(linea) <= 40
    assert "tok" not in linea
    assert "ctrl+c corta" in linea and "9s" in linea


def test_ancho_mas_estrecho_cae_el_hint_y_queda_el_latido():
    linea = spinner_vivo.componer_linea("Atando cabos", 9, tokens=1200,
                                        ancho=22)
    assert len(linea) <= 22
    assert "ctrl+c" not in linea and "tok" not in linea
    assert "9s" in linea                     # los segundos no caen nunca


def test_ancho_minusculo_trunca_el_verbo_sin_romper_linea():
    linea = spinner_vivo.componer_linea("Desenredando el ovillo", 125,
                                        tokens=9999, ancho=16)
    assert len(linea) <= 16
    assert "\n" not in linea
    assert "…" in linea                      # el recorte se declara


@pytest.mark.parametrize("ancho", [5, 8, 12, 16, 24, 40, 60, 120])
def test_nunca_desborda_ni_envuelve(ancho):
    # anti-jitter: a CUALQUIER ancho la linea cabe y es UNA linea
    linea = spinner_vivo.componer_linea("Merodeando la solucion", 3661,
                                        tokens=123456, ancho=ancho)
    assert len(linea) <= ancho
    assert "\n" not in linea


def test_verbo_none_y_segundos_negativos_no_revientan():
    linea = spinner_vivo.componer_linea(None, -5)
    assert "Trabajando…" in linea and "0s" in linea


# ---------------------------------------------------------------------------
# verbo_rotante: determinista, rota, y da la vuelta
# ---------------------------------------------------------------------------

def test_verbo_rotante_determinista_y_rota():
    verbos = ["Uno", "Dos", "Tres"]
    t0 = 1000.0
    v_a = spinner_vivo.verbo_rotante(t0, t0 + 1.0, verbos)
    v_b = spinner_vivo.verbo_rotante(t0, t0 + 1.0, verbos)
    assert v_a == v_b                        # mismo instante, mismo verbo
    siguiente = spinner_vivo.verbo_rotante(
        t0, t0 + spinner_vivo.PERIODO_ROTACION + 0.5, verbos)
    assert siguiente != v_a                  # paso el periodo: rota
    vuelta = spinner_vivo.verbo_rotante(
        t0, t0 + spinner_vivo.PERIODO_ROTACION * 3 + 0.5, verbos)
    assert vuelta == v_a                     # modulo: da la vuelta entera


def test_verbo_rotante_lista_vacia_no_revienta():
    # vacia -> cae a los verbos gato; None explicito tambien
    assert spinner_vivo.verbo_rotante(0.0, 5.0, []) in spinner_vivo.VERBOS_GATO
    assert spinner_vivo.verbo_rotante(0.0, 5.0, None) in spinner_vivo.VERBOS_GATO


def test_verbos_gato_son_unos_veinte_y_ascii():
    assert len(spinner_vivo.VERBOS_GATO) >= 15
    for v in spinner_vivo.VERBOS_GATO:
        assert "[" not in v and "]" not in v and "\n" not in v


# ---------------------------------------------------------------------------
# estimacion y config
# ---------------------------------------------------------------------------

def test_estimar_tokens():
    assert spinner_vivo.estimar_tokens(0) == 0
    assert spinner_vivo.estimar_tokens(3) == 0
    assert spinner_vivo.estimar_tokens(400) == 100


def test_verbos_config_acepta_comas_y_sanea_corchetes():
    verbos = spinner_vivo.verbos_config("Tramando [algo], Bostezando ,, ")
    assert verbos == ["Tramando algo", "Bostezando"]
    # vacio o invalido -> los verbos gato
    assert spinner_vivo.verbos_config("") == list(spinner_vivo.VERBOS_GATO)
    assert spinner_vivo.verbos_config(None) == list(spinner_vivo.VERBOS_GATO)
    assert spinner_vivo.verbos_config(["  "]) == list(spinner_vivo.VERBOS_GATO)


def _cli_falso(monkeypatch, cfg):
    """Un cognia.cli de mentira en sys.modules: config() lo mira a call-time
    sin importar el real (el patron de renderer._config_colapso)."""
    mod = types.SimpleNamespace(_load_config=lambda: cfg)
    monkeypatch.setitem(sys.modules, "cognia.cli", mod)
    return mod


def test_config_lee_la_config_del_cli(monkeypatch):
    monkeypatch.delenv("COGNIA_SPINNER_INFO", raising=False)
    _cli_falso(monkeypatch, {"spinner_info": "off",
                             "spinner_verbos": "Solo uno"})
    activo, verbos = spinner_vivo.config()
    assert activo is False
    assert verbos == ["Solo uno"]


def test_env_gana_a_la_config(monkeypatch):
    _cli_falso(monkeypatch, {"spinner_info": "on", "spinner_verbos": ""})
    monkeypatch.setenv("COGNIA_SPINNER_INFO", "0")
    assert spinner_vivo.activo() is False
    monkeypatch.setenv("COGNIA_SPINNER_INFO", "1")
    _cli_falso(monkeypatch, {"spinner_info": "off", "spinner_verbos": ""})
    assert spinner_vivo.activo() is True


# ---------------------------------------------------------------------------
# cableado al renderer: contador de chars + ticker (regresion del F2)
# ---------------------------------------------------------------------------

class _StatusFalso:
    def __init__(self, revienta=False):
        self.textos = []
        self.revienta = revienta

    def update(self, texto):
        if self.revienta:
            raise RuntimeError("status roto a proposito")
        self.textos.append(texto)

    def stop(self):
        pass


class _ConsolaFalsa:
    size = types.SimpleNamespace(width=100)


def test_renderer_cuenta_chars_del_stream(monkeypatch):
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    r = Renderer(None)
    r._stream_externo = True    # contar sin abrir FlujoSuave en el test
    r(events.TareaInicio(tarea="x"))
    assert r._chars_stream == 0
    r(events.TokenTexto(texto="hola mundo"))          # 10 chars de prosa
    r(events.RazonamientoTick(chars=4, fragmento="mmm…"))   # 4 del razonar
    assert r._chars_stream == 14
    r(events.TareaInicio(tarea="otra"))
    assert r._chars_stream == 0                        # resetea por tarea


def test_tick_spinner_compone_sobre_el_status(monkeypatch):
    monkeypatch.delenv("COGNIA_SPINNER_INFO", raising=False)
    r = Renderer(_ConsolaFalsa())
    r._status = _StatusFalso()
    r._status_base = None                    # fase pensar: verbo gato rotante
    r._status_estilo = "pensar"
    r._status_t0 = time.time() - 5
    r._chars_stream = 400
    assert r._tick_spinner() is True
    texto = r._status.textos[-1]
    assert "5s" in texto and "~100 tok" in texto and "ctrl+c corta" in texto
    assert texto.startswith("[pensar]")     # conserva el estilo del tema


def test_tick_spinner_con_tool_conserva_la_etiqueta(monkeypatch):
    r = Renderer(_ConsolaFalsa())
    r._status = _StatusFalso()
    r._status_base = "Leyendo motor.py…"     # tool en curso: nada de gatos
    r._status_t0 = time.time() - 2
    r._chars_stream = 0
    assert r._tick_spinner() is True
    assert "Leyendo motor.py…" in r._status.textos[-1]
    assert "tok" not in r._status.textos[-1]


def test_tick_spinner_degrada_sin_romper(monkeypatch):
    # el status revienta -> False (el ticker se corta) y NADA se propaga
    r = Renderer(_ConsolaFalsa())
    r._status = _StatusFalso(revienta=True)
    r._status_base = None
    r._status_t0 = time.time()
    assert r._tick_spinner() is False


def test_arrancar_status_levanta_ticker_y_parar_lo_corta(monkeypatch):
    monkeypatch.setenv("COGNIA_SPINNER", "1")      # forzar interactivo
    monkeypatch.delenv("COGNIA_SPINNER_INFO", raising=False)
    import io
    from rich.console import Console
    r = Renderer(Console(file=io.StringIO(), force_terminal=True, width=80))
    r._arrancar_status("Leyendo x…")
    try:
        assert r._status is not None
        assert r._ticker is not None and r._ticker.is_alive()
        stop = r._ticker_stop
    finally:
        r._parar_status()
    assert stop.is_set()                     # el ticker quedo cortado
    assert r._ticker is None and r._ticker_stop is None


def test_spinner_info_off_no_levanta_ticker(monkeypatch):
    monkeypatch.setenv("COGNIA_SPINNER", "1")
    monkeypatch.setenv("COGNIA_SPINNER_INFO", "0")   # apagado de emergencia
    import io
    from rich.console import Console
    r = Renderer(Console(file=io.StringIO(), force_terminal=True, width=80))
    r._arrancar_status("Leyendo x…")
    try:
        assert r._status is not None         # el spinner clasico sigue
        assert r._ticker is None             # la linea viva no
    finally:
        r._parar_status()
