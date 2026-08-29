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


# ---------------------------------------------------------------------------
# P8: aspecto por elemento (spinner.tool / spinner.pensar / spinner.comando)
# ---------------------------------------------------------------------------

from cognia.ux import aspecto as A, glow   # noqa: E402


@pytest.fixture(autouse=True)
def _aspecto_y_motor_limpios(monkeypatch):
    """Sin overrides, sin capacidades forzadas, sin env de animacion: cada
    test decide lo que enciende (y lo deja apagado al salir)."""
    for k in ("COGNIA_ANIMACION", "COGNIA_ASCII", "COGNIA_REMOTO", "COGNIA_THEME"):
        monkeypatch.delenv(k, raising=False)
    A.reset()
    glow.forzar_capacidades(None)
    glow.vaciar_memo()
    yield
    A.reset()
    glow.forzar_capacidades(None)
    glow.vaciar_memo()


def _poner(id, prop, valor):
    avisos = A.poner(id, prop, valor)
    assert not A.errores(avisos), avisos


def test_componer_linea_sep_y_tok_editables():
    linea = spinner_vivo.componer_linea("Maullando ideas", 12, tokens=340,
                                        sep=" | ", tok="tokens", ancho=100)
    assert linea == "Maullando ideas… (12s | ~340 tokens | ctrl+c corta)"
    # None = los literales de hoy (byte-identico con el golden 'spinner')
    assert spinner_vivo.componer_linea("Maullando ideas", 12, tokens=340, sep=None, tok=None) \
        == "Maullando ideas… (12s · ~340 tok · ctrl+c corta)"


def test_aspecto_spinner_defaults_son_los_literales_de_hoy():
    for id in ("spinner.tool", "spinner.pensar"):
        asp = spinner_vivo.aspecto_spinner(id)
        assert asp.id == id
        assert (asp.marca, asp.spinner_rich, asp.hint, asp.tok, asp.sep) == \
            ("·", "dots", spinner_vivo.HINT_CORTE, "tok", " · ")
        assert asp.animar is False
    assert spinner_vivo.aspecto_spinner("spinner.pensar").pensando == "pensando…"
    # y linea_estado con id da EXACTAMENTE lo mismo que sin id
    con = spinner_vivo.linea_estado("Leyendo motor.py…", 0.0, 12.0, 1360, ancho=94,
                                    id="spinner.tool")
    sin = spinner_vivo.linea_estado("Leyendo motor.py…", 0.0, 12.0, 1360, ancho=94)
    assert con == sin == "Leyendo motor.py… (12s · ~340 tok · ctrl+c corta)"


def test_aspecto_spinner_lee_los_overrides_del_registro():
    _poner("spinner.tool", "texto.hint", "esc corta")
    _poner("spinner.tool", "texto.tok", "tokens")
    _poner("spinner.tool", "separador", " | ")
    _poner("spinner.tool", "texto.spinner_rich", "line")
    _poner("spinner.pensar", "texto.pensando", "cavilando…")
    asp = spinner_vivo.aspecto_spinner("spinner.tool")
    assert (asp.hint, asp.tok, asp.sep, asp.spinner_rich) == ("esc corta", "tokens", " | ", "line")
    linea = spinner_vivo.linea_estado("Leyendo motor.py…", 0.0, 12.0, 1360, ancho=94,
                                      id="spinner.tool")
    assert linea == "Leyendo motor.py… (12s | ~340 tokens | esc corta)"
    assert spinner_vivo.aspecto_spinner("spinner.pensar").pensando == "cavilando…"
    # el override NO se filtra al otro elemento
    assert spinner_vivo.aspecto_spinner("spinner.pensar").hint == spinner_vivo.HINT_CORTE


def _cli_con_avisos(monkeypatch):
    avisos = []
    mod = types.SimpleNamespace(_load_config=lambda: {},
                                _aviso_degradado=lambda donde, motivo: avisos.append((donde, motivo)))
    monkeypatch.setitem(sys.modules, "cognia.cli", mod)
    return avisos


def test_spinner_rich_desconocido_avisa_y_cae_a_dots(monkeypatch):
    avisos = _cli_con_avisos(monkeypatch)
    _poner("spinner.tool", "texto.spinner_rich", "noexiste")
    asp = spinner_vivo.aspecto_spinner("spinner.tool")
    assert asp.spinner_rich == "dots"
    assert avisos and avisos[-1][0] == "spinner" and "noexiste" in avisos[-1][1]


def test_id_que_no_es_spinner_avisa_y_usa_tool(monkeypatch):
    avisos = _cli_con_avisos(monkeypatch)
    assert spinner_vivo.aspecto_spinner("prompt.etiqueta").id == "spinner.tool"
    assert avisos and "prompt.etiqueta" in avisos[-1][1]


def test_animar_exige_animacion_del_elemento_Y_capacidades():
    glow.forzar_capacidades(glow.Caps("truecolor", True, ""))
    assert spinner_vivo.aspecto_spinner("spinner.pensar").animar is False   # elemento apagado
    _poner("spinner.pensar", "animacion.activa", "on")
    assert spinner_vivo.aspecto_spinner("spinner.pensar").animar is True
    assert spinner_vivo.aspecto_spinner("spinner.tool").animar is False     # solo pensar
    glow.forzar_capacidades(glow.Caps("truecolor", False, "sin tty"))
    assert spinner_vivo.aspecto_spinner("spinner.pensar").animar is False   # sin tty: no


def test_animacion_global_apagada_gana_al_elemento(monkeypatch):
    _poner("spinner.pensar", "animacion.activa", "on")
    monkeypatch.setenv("COGNIA_ANIMACION", "0")
    glow.forzar_capacidades(None)
    assert spinner_vivo.aspecto_spinner("spinner.pensar").animar is False


def test_estilo_spinner_pone_el_color_base_solo_cuando_anima():
    # sin animacion: color '' -> el motor devuelve el TOKEN (byte-identico)
    e = spinner_vivo.estilo_spinner("spinner.pensar")
    assert e.token == "pensar" and e.color == "" and not e.anim_activa
    assert glow.estilo_rich(e) == "pensar"
    # con animacion: hace falta un color base que mezclar (sin el, el
    # barrido salia como bold/dim sin color: 0 escapes 38;2; en la captura)
    _poner("spinner.pensar", "animacion.activa", "on")
    e = spinner_vivo.estilo_spinner("spinner.pensar")
    assert e.anim_activa and e.color == A.color_rich(A.estilo_resuelto("spinner.pensar").color)
    assert e.color.startswith("#")
    glow.forzar_capacidades(glow.Caps("truecolor", True, ""))
    a = glow.estilizar(e, "· pensando…", t=0.5)
    b = glow.estilizar(e, "· pensando…", t=0.8)
    assert a.spans != b.spans and len(a.spans) > 1


def test_comando_default_byte_identico_y_override():
    assert spinner_vivo.comando("procesando") == ("[spinner]Procesando...[/spinner]", "dots")
    assert spinner_vivo.comando("mejorando") == ("[spinner]Mejorando el prompt...[/spinner]", "dots")
    _poner("spinner.comando", "texto.procesando", "Rumiando...")
    _poner("spinner.comando", "glifo", "arc")
    assert spinner_vivo.comando("procesando") == ("[spinner]Rumiando...[/spinner]", "arc")


def test_spinner_tool_y_pensar_quedan_enganchados_en_el_registro():
    # E8: /estilo no dice "se aplica en la proxima version" para estos
    assert A.elemento("spinner.tool").enganchado is True
    assert A.elemento("spinner.pensar").enganchado is True
    # spinner.comando: cli.py usa spinner_vivo.comando() en sus tres status
    # (gancho P8, ver test_los_tres_status_de_cli_usan_comando)
    assert A.elemento("spinner.comando").enganchado is True


# ---------------------------------------------------------------------------
# Gancho P8 en cli.py: los TRES console.status de spinner.comando
# ---------------------------------------------------------------------------

class _StatusGrabador:
    """Console falsa: graba (markup, spinner) de cada status y nada mas."""

    def __init__(self):
        self.llamadas = []
        self.width = 100

    def status(self, markup, spinner="dots", **kw):
        import contextlib
        self.llamadas.append((markup, spinner))
        return contextlib.nullcontext()

    def print(self, *a, **k):
        pass


def _fuente_cli() -> str:
    import inspect
    import cognia.cli as cli
    return inspect.getsource(cli)


def test_los_tres_status_de_cli_usan_comando():
    """Regresion del gancho P8: ningun status de 'Procesando...' /
    'Mejorando el prompt...' queda con el literal; todos pasan por
    spinner_vivo.comando() (que sin override devuelve EXACTAMENTE el literal
    de antes, ver test_comando_default_byte_identico_y_override).

    Los conteos son MINIMOS y no igualdades exactas (2026-08-28). Lo que este
    test defiende es que no queden literales sueltos; el numero de sitios que
    usan el helper es una consecuencia, no la propiedad. Con `== 2`, cada
    comando nuevo que hiciera lo correcto —pasar por el helper— rompia el
    test, que es el incentivo exactamente al reves: castigaba justo la
    conducta que el test existe para fomentar. Paso al anadir /flujoteca
    editar y /session-to-workflow, que suman dos 'procesando' legitimos.
    """
    src = _fuente_cli()
    assert 'status("[spinner]Procesando...[/spinner]"' not in src
    assert 'status("[spinner]Mejorando el prompt...[/spinner]"' not in src
    assert src.count('_sv.comando("procesando")') >= 2, "al menos _run y el camino articulado del repl"
    assert src.count('_sv.comando("mejorando")') >= 1, "al menos el 'Mejorando el prompt...' de _mejora_generar"
    # Y la propiedad de verdad: toda clave que se le pase al helper tiene que
    # ser una que el helper conozca. 'pensando' NO lo es, y usarla hacia que
    # el CLI gritara una degradacion en cada turno (cazado tecleandolo).
    import re
    from cognia.ux import spinner_vivo
    claves = set(re.findall(r'_sv\.comando\("([a-z_]+)"\)', src))
    conocidas = {"procesando", "mejorando"}
    assert claves <= conocidas, (
        f"claves de spinner.comando que el helper no conoce: "
        f"{sorted(claves - conocidas)} (cada una grita una degradacion)")


def test_run_y_mejora_generar_pasan_el_texto_del_registro(monkeypatch):
    import cognia.cli as cli
    grab = _StatusGrabador()
    monkeypatch.setattr(cli, "_console", grab)
    monkeypatch.setattr(cli, "_HAS_RICH", True)
    monkeypatch.setattr(cli, "_show_response", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_show_footer", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_session_log", [])
    # _run: default byte-identico
    cli._run("hola", lambda: "resultado")
    assert grab.llamadas[-1] == ("[spinner]Procesando...[/spinner]", "dots")
    # _mejora_generar: el mismo camino con la clave 'mejorando'
    mejora = types.SimpleNamespace(ok=True, motivo="ok", ms=1, modelo="x", aviso="", texto="t")
    monkeypatch.setattr(cli, "_mod_mejorar",
                        lambda: types.SimpleNamespace(mejorar=lambda *a, **k: mejora))
    monkeypatch.setattr(cli, "_parar_status_mejora", lambda: None)
    monkeypatch.setattr(cli, "_estilo_mejorar", lambda: ("", "", None))
    assert cli._mejora_generar("texto", "mejorar") is mejora
    assert grab.llamadas[-1] == ("[spinner]Mejorando el prompt...[/spinner]", "dots")
    # con override del registro los DOS cambian sin tocar cli.py
    _poner("spinner.comando", "texto.procesando", "Rumiando...")
    _poner("spinner.comando", "texto.mejorando", "Puliendo...")
    _poner("spinner.comando", "glifo", "arc")
    cli._run("hola", lambda: "resultado")
    assert grab.llamadas[-1] == ("[spinner]Rumiando...[/spinner]", "arc")
    cli._mejora_generar("texto", "mejorar")
    assert grab.llamadas[-1] == ("[spinner]Puliendo...[/spinner]", "arc")
