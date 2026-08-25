# -*- coding: utf-8 -*-
"""
tests/test_cli_remoto_paridad.py
================================
Paridad remota del REPL (2026-08-24), lado CLI, SIN modelo:

(A) interrumpir desde el movil: handler de SIGBREAK/SIGINT bajo COGNIA_REMOTO
    que lanza KeyboardInterrupt (y NO cuando el REPL esta ocioso en el prompt,
    porque se comeria la linea), con un subproceso REAL que recibe
    CTRL_BREAK_EVENT y sobrevive; y _run() que no muere por la interrupcion.
(B) multilinea por pipe: la continuacion ' \\' en el modo input() pelado.
(C) el sink stdout deja pasar TokenTexto por defecto y COGNIA_REMOTO_STREAM=0
    lo apaga.
(D) eventos Confianza y FooterTurno: tipos, emision desde _show_footer y
    _confianza_veredicto, y la prosa que bajo remoto va como Aviso.
(E) el resultado de los slash llega al chat: _run() con respuesta_final bajo
    remoto y la captura de los slash informativos.
(H) /remoto, /decirle y /cancelar: argumentos, mensajes y efectos, con la raiz
    remota en tmp_path (nada toca ~/.cognia/remoto).
"""
from __future__ import annotations

import io
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

import cognia.cli as cli
from cognia.ux import events

PY = Path(sys.executable)
RAIZ = Path(__file__).resolve().parents[1]
ES_WINDOWS = os.name == "nt"


# -- aislamiento ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def _aislado(monkeypatch, tmp_path):
    for var in ("COGNIA_REMOTO", "COGNIA_REMOTO_STREAM", "COGNIA_REMOTO_PORT",
                "COGNIA_REMOTO_HOST", "COGNIA_EVENTS_JSONL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(events, "_suscriptores", [])
    monkeypatch.setattr(events, "_sink_jsonl", None)
    cli._EN_PROMPT[0] = False
    cli._CAPTURA_SLASH.update({"activa": False, "raw": ""})
    # La raiz del remoto en tmp_path: /remoto jamas lee ni escribe en la real.
    monkeypatch.setattr(cli, "_remoto_raiz", lambda: tmp_path / "remoto")
    (tmp_path / "remoto").mkdir()
    yield


def _consola(width=100):
    from rich.console import Console
    from rich.theme import Theme
    from cognia.ux import paleta
    buf = io.StringIO()
    con = Console(file=buf, highlight=False, width=width, legacy_windows=False,
                  force_terminal=False, theme=Theme(paleta.tema_cli("oscuro")))
    return con, buf


@pytest.fixture
def consola(monkeypatch):
    con, buf = _consola()
    monkeypatch.setattr(cli, "_console", con)
    monkeypatch.setattr(cli, "_HAS_RICH", True)
    return con, buf


@pytest.fixture
def lineas(monkeypatch):
    """Captura lo que el comando pinta con _print_line (markup crudo)."""
    out = []
    monkeypatch.setattr(cli, "_print_line", lambda t: out.append(str(t)))
    return out


@pytest.fixture
def bus():
    got = []
    events.suscribir(got.append)
    return got


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ===========================================================================
# (A) interrumpir desde el remoto
# ===========================================================================

def test_handler_ocioso_no_lanza_y_avisa(bus):
    cli._EN_PROMPT[0] = True
    cli._interrupcion_remota_handler(0, None)          # no lanza
    avisos = [e for e in bus if isinstance(e, events.Aviso)]
    assert avisos and "ignorada" in avisos[-1].texto and avisos[-1].origen == "remoto"


def test_handler_generando_lanza_keyboardinterrupt_y_avisa(bus):
    cli._EN_PROMPT[0] = False
    with pytest.raises(KeyboardInterrupt):
        cli._interrupcion_remota_handler(0, None)
    avisos = [e for e in bus if isinstance(e, events.Aviso)]
    assert avisos and avisos[-1].texto == "generacion interrumpida desde el remoto"


def test_instalar_fuera_del_remoto_no_toca_nada():
    nombre = "SIGBREAK" if hasattr(signal, "SIGBREAK") else "SIGINT"
    antes = signal.getsignal(getattr(signal, nombre))
    assert cli._instalar_interrupcion_remota() == ""
    assert signal.getsignal(getattr(signal, nombre)) is antes


def test_instalar_bajo_remoto_instala_la_senal_de_la_plataforma(monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    nombre = "SIGBREAK" if hasattr(signal, "SIGBREAK") else "SIGINT"
    sig = getattr(signal, nombre)
    antes = signal.getsignal(sig)
    try:
        assert cli._instalar_interrupcion_remota() == nombre
        assert signal.getsignal(sig) is cli._interrupcion_remota_handler
    finally:
        signal.signal(sig, antes)


def test_instalar_fuera_del_hilo_principal_avisa_degradado(monkeypatch):
    import threading
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado", lambda v, d="": avisos.append((v, d)))
    res = []
    t = threading.Thread(target=lambda: res.append(cli._instalar_interrupcion_remota()))
    t.start(); t.join(5)
    assert res == [""]
    assert avisos and avisos[0][0] == "remoto.interrupcion"


_HIJO = r'''
import os, sys, time
os.environ["COGNIA_REMOTO"] = "1"
os.environ["COGNIA_EVENTS_JSONL"] = "1"
from cognia.ux import events
events.activar_sink_jsonl()
from cognia.cli import _instalar_interrupcion_remota
print("SENAL:" + _instalar_interrupcion_remota(), flush=True)
try:
    for _ in range(600):
        time.sleep(0.05)
    print("SIN_MARCA", flush=True)
except KeyboardInterrupt:
    print("MARCA", flush=True)
print("VIVO", flush=True)
'''


@pytest.mark.skipif(not ES_WINDOWS, reason="CTRL_BREAK_EVENT es de Windows")
def test_ctrl_break_real_interrumpe_y_el_proceso_sigue_vivo(tmp_path):
    """El contrato de (A) de punta a punta: un hijo en su propio grupo de
    procesos instala el handler, recibe CTRL_BREAK_EVENT y (1) cae en su
    except KeyboardInterrupt, (2) sigue vivo, (3) emitio el Aviso por el sink
    stdout. Importa cognia.cli de verdad (0,4 s medidos)."""
    script = tmp_path / "hijo.py"
    script.write_text(_HIJO, encoding="utf-8")
    # PYTHONPATH=RAIZ: sys.path[0] de un script es SU carpeta (tmp_path), no
    # el cwd, y sin esto el hijo importaba el cognia INSTALADO en vez del
    # worktree (cazado en la primera corrida: ImportError del simbolo nuevo).
    env = dict(os.environ, PYTHONUTF8="1", COGNIA_SPINNER="0",
               COGNIA_ANIMACION="0", NO_COLOR="1",
               PYTHONPATH=str(RAIZ) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    p = subprocess.Popen([str(PY), str(script)], cwd=str(RAIZ), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, encoding="utf-8",
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        primera = ""
        t0 = time.time()
        while time.time() - t0 < 60:
            primera = p.stdout.readline().strip()
            if primera.startswith("SENAL:"):
                break
        assert primera == "SENAL:SIGBREAK", primera
        time.sleep(0.3)
        p.send_signal(signal.CTRL_BREAK_EVENT)
        resto = ""
        try:
            resto, _ = p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            pytest.fail("el hijo no termino tras CTRL_BREAK: " + resto)
    finally:
        if p.poll() is None:
            p.kill()
    assert "MARCA" in resto and "VIVO" in resto and "SIN_MARCA" not in resto, resto
    assert "generacion interrumpida desde el remoto" in resto, resto
    assert '"tipo": "Aviso"' in resto, resto
    # (4) el handler NATIVO avisa en el acto y CEDE: sale 'recibida' ANTES de
    # 'interrumpida' y la senal llego igual al handler de Python (MARCA).
    assert "interrupcion recibida; se aplica al terminar la llamada en curso" in resto, resto
    assert resto.index("interrupcion recibida") < resto.index("generacion interrumpida"), resto


def test_run_no_muere_por_keyboardinterrupt(consola, lineas):
    def _fn():
        raise KeyboardInterrupt
    cli._run("/lento", _fn)                      # no propaga
    assert any("interrumpido" in l for l in lineas), lineas


def test_agente_inline_y_hacer_atrapan_keyboardinterrupt():
    """Los dos caminos inline del agente (accion inferida y /hacer sin carril
    de fondo) mataban el REPL con la senal: ahora tienen su except."""
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    i = fuente.index("_resp = _run_agent_task(ai, raw, _print_line, hint=_hint)")
    assert "except KeyboardInterrupt:" in fuente[i:i + 400]
    j = fuente.index('if not _lanzar_en_fondo("hacer", _turno_hacer):')
    assert "except KeyboardInterrupt:" in fuente[j:j + 400]


# ===========================================================================
# (B) multilinea: continuacion ' \' en el modo input() pelado
# ===========================================================================

def _lector(lineas):
    it = iter(lineas)

    def leer():
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return leer


def test_continuacion_local_une_con_espacio_como_el_prompt_rico():
    primera = "hola \\".strip()
    assert cli._leer_con_continuacion(primera, _lector(["mundo \\", "  fin  "]), " ") == "hola mundo fin"


def test_continuacion_remota_conserva_saltos_y_sangria(monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    sep = cli._separador_continuacion_simple()
    assert sep == "\n"
    got = cli._leer_con_continuacion("def f(): \\", _lector(["    return 1 \\", "print(f())"]), sep)
    assert got == "def f():\n    return 1\nprint(f())"


def test_continuacion_eof_a_mitad_devuelve_lo_acumulado():
    assert cli._leer_con_continuacion("a \\", _lector(["b \\"]), "\n") == "a\nb"
    assert cli._leer_con_continuacion("a \\", _lector([]), " ") == "a"


def test_sin_barra_no_lee_mas():
    leidas = []

    def leer():
        leidas.append(1)
        return "x"
    assert cli._leer_con_continuacion("hola", leer, " ") == "hola"
    assert leidas == []


def test_separador_fuera_del_remoto_es_espacio():
    assert cli._separador_continuacion_simple() == " "


def test_modo_input_pelado_usa_la_continuacion():
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    # Con modo-bots (fusion 2026-08-25) el rotulo lo pone _etiqueta_prompt():
    # "cognia" o "<glifo> <bot>" con un canon abierto.
    i = fuente.index('linea = input(_g() + _etiqueta_prompt() + "> " + _R).strip() or _pre')
    assert "_leer_con_continuacion(" in fuente[i:i + 900]
    assert "_EN_PROMPT[0] = True" in fuente[i - 400:i]


# ===========================================================================
# (C) streaming por el sink stdout
# ===========================================================================

def test_sink_stdout_deja_pasar_tokentexto_por_defecto(capfd):
    events.activar_sink_jsonl("1")
    events.emitir(events.TokenTexto(texto="hola"))
    out = capfd.readouterr().out
    assert out.startswith(events.PREFIJO_STDOUT) and '"tipo": "TokenTexto"' in out
    events.emitir(events.RazonamientoTick(chars=3))
    assert capfd.readouterr().out == ""


def test_sink_stdout_palanca_stream_0_apaga_tokentexto(capfd, monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO_STREAM", "0")
    events.activar_sink_jsonl("1")
    events.emitir(events.TokenTexto(texto="hola"))
    assert capfd.readouterr().out == ""
    events.emitir(events.Aviso(texto="si", origen="t"))
    assert "@EV" in capfd.readouterr().out


def test_remoto_stream_vivo_decide_por_env(monkeypatch):
    assert cli._remoto_stream_vivo() is False
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    assert cli._remoto_stream_vivo() is True
    monkeypatch.setenv("COGNIA_REMOTO_STREAM", "0")
    assert cli._remoto_stream_vivo() is False


def test_fast_path_no_pinta_bajo_remoto_con_deltas_y_entrega_entera():
    """La segunda pieza del POR QUE es seguro dejar pasar TokenTexto: el
    fast-path (que tiene su PROPIO FlujoSuave, ajeno al renderer) no pinta
    bajo remoto con deltas y entrega la respuesta entera al final. Medido
    2026-08-25: sin esto el entrelazado '@EV' a media frase volvio tal cual."""
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    i = fuente.index("_pintar_stream = not _remoto_stream_vivo()")
    j = fuente.index("for _tok in _stream_src(_mt_turno):", i)
    assert "if not _pintar_stream:" in fuente[j:j + 300]
    k = fuente.index('_full_response = "".join(_tokens_buf).strip()', j)
    bloque = fuente[k:k + 1500]
    assert "if not _pintar_stream:" in bloque and "respuesta_final=True" in bloque
    m = fuente.index('_n_int = len("".join(_tokens_buf))', k)
    assert "(interrumpido)" in fuente[m:m + 700]


def test_renderer_no_escribe_prosa_bajo_remoto(monkeypatch):
    """El POR QUE ahora es seguro dejar pasar TokenTexto: el renderer bajo
    COGNIA_REMOTO arranca con _sin_stream y su handler de TokenTexto no pinta."""
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    from cognia.ux import renderer
    con, buf = _consola()
    r = renderer.Renderer(console=con)
    assert r._sin_stream is True
    r(events.TokenTexto(texto="hola "))
    r(events.TokenTexto(texto="mundo"))
    assert buf.getvalue() == ""


# ===========================================================================
# (D) Confianza y FooterTurno
# ===========================================================================

def test_tipos_nuevos_serializan_con_su_tipo():
    c = events.a_dict(events.Confianza(nivel="alta", glifo="●", valor=0.9,
                                       fuentes=["youtube.com"], texto="● confianza ALTA"))
    assert c["tipo"] == "Confianza" and c["fuentes"] == ["youtube.com"] and c["valor"] == 0.9
    f = events.a_dict(events.FooterTurno(ok=True, segundos=14.6, tokens=312,
                                         ctx_libre_pct=95.0, motivo=""))
    assert f["tipo"] == "FooterTurno" and f["ctx_libre_pct"] == 95.0 and f["tokens"] == 312
    assert events.FooterTurno().ctx_libre_pct is None


def test_show_footer_remoto_emite_footerturno_y_sigue_plano(consola, bus, monkeypatch):
    from cognia.remoto.sesiones import _RE_FOOTER_RENDERER
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    monkeypatch.setattr(cli, "_datos_barra_estado",
                        lambda: {"ctx_usado": 3_000, "ctx_total": 60_000, "ctx_estimado": False})
    cli._show_footer(14.6, "respuesta", tokens=312)
    ev = [e for e in bus if isinstance(e, events.FooterTurno)]
    assert len(ev) == 1
    assert ev[0].ok and ev[0].segundos == 14.6 and ev[0].tokens == 312
    assert ev[0].ctx_libre_pct == 95.0 and ev[0].motivo == ""
    linea = consola[1].getvalue().strip()
    assert _RE_FOOTER_RENDERER.match(linea), linea


def test_show_footer_emite_aunque_dure_menos_de_1s_y_no_pinta(consola, bus, monkeypatch):
    monkeypatch.setattr(cli, "_datos_barra_estado", lambda: {})
    cli._show_footer(0.3, "r", tokens=5)
    assert [e for e in bus if isinstance(e, events.FooterTurno)][0].ctx_libre_pct is None
    assert consola[1].getvalue() == ""


def test_show_footer_local_pinta_con_glifo_y_emite(consola, bus, monkeypatch):
    monkeypatch.setattr(cli, "_datos_barra_estado",
                        lambda: {"ctx_usado": 3_000, "ctx_total": 60_000, "ctx_estimado": False})
    cli._show_footer(30.4, "r", tokens=412)
    assert consola[1].getvalue().strip().startswith("✓ 30.4s · 412 tokens · ctx 95% libre")
    assert len([e for e in bus if isinstance(e, events.FooterTurno)]) == 1


def _veredicto(conf, fuentes):
    from cognia.search.confianza import Veredicto
    return Veredicto(valor="4,63 mil", confianza=conf, razones=["r"], fuentes=list(fuentes))


def test_confianza_veredicto_remoto_emite_evento_sin_prosa(bus, lineas, monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    from cognia.agent import confianza_chat as cc
    monkeypatch.setattr(cc, "evaluar_respuesta", lambda r, inv: _veredicto(0.9, ["youtube.com"]))
    ver = cli._confianza_veredicto("4,63 mil suscriptores", None)
    assert ver.confianza == 0.9
    assert lineas == []                                    # nada de prosa en remoto
    ev = [e for e in bus if isinstance(e, events.Confianza)]
    assert len(ev) == 1
    assert ev[0].nivel == "alta" and ev[0].glifo == "●" and ev[0].valor == 0.9
    assert ev[0].fuentes == ["youtube.com"]
    assert ev[0].texto.startswith("● confianza ALTA (0,90)")
    assert cli._CONFIANZA_ULTIMO["linea"] == ev[0].texto


def test_confianza_veredicto_local_pinta_y_emite(bus, lineas, monkeypatch):
    from cognia.agent import confianza_chat as cc
    monkeypatch.setattr(cc, "evaluar_respuesta", lambda r, inv: _veredicto(0.3, []))
    cli._confianza_veredicto("no se", None)
    assert len(lineas) == 1 and "confianza BAJA" in lineas[0]
    ev = [e for e in bus if isinstance(e, events.Confianza)]
    assert len(ev) == 1 and ev[0].nivel == "baja" and ev[0].fuentes == []


def test_linea_o_aviso_remoto_va_por_el_bus_y_local_por_print(bus, lineas, monkeypatch):
    cli._linea_o_aviso("[detail]x[/detail]", "x plano", "confianza")
    assert lineas == ["[detail]x[/detail]"] and bus == []
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    cli._linea_o_aviso("[detail]y[/detail]", "y plano", "lazo")
    assert lineas == ["[detail]x[/detail]"]
    assert [e for e in bus if isinstance(e, events.Aviso)][0].texto == "y plano"
    assert bus[-1].origen == "lazo"


def test_guards_remotos_de_confianza_y_lazo_quitados():
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    assert "and not _confianza_remoto()" not in fuente
    assert 'if _streamed and _LAZO["on"]:' in fuente
    assert 'os.environ.get("COGNIA_REMOTO", "").strip() != "1"' not in fuente[
        fuente.index("# LAZO (/lazo, opt-in)"):fuente.index("# LAZO (/lazo, opt-in)") + 800]


# ===========================================================================
# (E) los slash llegan al chat del movil
# ===========================================================================

def test_run_remoto_imprime_el_resultado_como_respuesta_final(consola, capsys, monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    monkeypatch.setattr(cli, "_datos_barra_estado", lambda: {})
    cli._run("/ver algo", lambda: "RESULTADO X")
    out = capsys.readouterr().out
    assert "\nRESULTADO X\n" in out                    # print plano con flush
    assert "│" not in consola[1].getvalue()             # sin Panel


def test_run_remoto_usa_lo_capturado_si_el_comando_no_devuelve(consola, capsys, monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    monkeypatch.setattr(cli, "_datos_barra_estado", lambda: {})

    def _fn():
        print("hola por print")
    cli._run("/x", _fn)
    assert "hola por print" in capsys.readouterr().out


def test_run_local_sigue_con_marco(consola, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_datos_barra_estado", lambda: {})
    cli._run("/ver algo", lambda: "RESULTADO Y")
    assert "RESULTADO Y" in consola[1].getvalue()
    assert "RESULTADO Y" not in capsys.readouterr().out


def test_desenmarcar_quita_los_bordes_de_panel():
    texto = "╭────╮\n│ hola │\n│ mundo│\n╰────╯\nsuelto"
    assert cli._desenmarcar(texto) == "hola\nmundo\nsuelto"


def test_captura_slash_remoto_entrega_lo_pintado_sin_marco(consola, capsys, monkeypatch):
    from rich.panel import Panel
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    assert cli._captura_slash_remoto_inicio("/estado") is True
    consola[0].print(Panel("estado: ok"))
    assert capsys.readouterr().out == ""                # aun capturado
    assert cli._captura_slash_remoto_fin() == "estado: ok"
    out = capsys.readouterr().out
    assert "estado: ok" in out and "│" not in out and "╭" not in out
    assert cli._captura_slash_remoto_fin() == ""        # idempotente


def test_captura_slash_solo_en_remoto_y_solo_allowlist(consola, monkeypatch):
    assert cli._captura_slash_remoto_inicio("/estado") is False
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    assert cli._captura_slash_remoto_inicio("/hacer algo") is False   # pregunta s/n: nunca
    assert cli._captura_slash_remoto_inicio("hola") is False
    assert cli._captura_slash_remoto_inicio("/ayuda todo") is True
    cli._captura_slash_remoto_fin()
    for c in ("/ayuda", "/estado", "/confianza", "/estilo", "/remoto", "/decirle", "/cancelar"):
        assert c in cli._SLASH_AL_CHAT_REMOTO


def test_bucle_del_repl_abre_y_cierra_la_captura():
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    assert fuente.count("_captura_slash_remoto_fin()") >= 3        # tope del bucle, salida, inicio
    assert "_captura_slash_remoto_inicio(raw)" in fuente
    i = fuente.index("_captura_slash_remoto_inicio(raw)")
    assert "_aplicar_recarga_estilo()" in fuente[i - 400:i]


def test_ayuda_remota_va_como_respuesta_final():
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    i = fuente.index("_salida_ayuda = _texto_ayuda if _texto_ayuda is not None else HELP_TEXT")
    assert '_show_response(_salida_ayuda, "respuesta", respuesta_final=True)' in fuente[i:i + 700]


# ===========================================================================
# (H) /remoto
# ===========================================================================

def test_remoto_registrado_y_despachado():
    for c in ("/remoto", "/decirle", "/cancelar"):
        assert c in cli._CMD_DESCRIPTIONS and c in cli._CMD_DETAILS
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    for c in ("remoto", "decirle", "cancelar"):
        assert f'elif raw == "/{c}" or raw.startswith("/{c} "):' in fuente


def test_remoto_puerto_env_y_default(monkeypatch):
    assert cli._remoto_puerto() == 8777
    monkeypatch.setenv("COGNIA_REMOTO_PORT", "9001")
    assert cli._remoto_puerto() == 9001
    assert cli._remoto_puerto("9002") == 9002
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado", lambda v, d="": avisos.append(d))
    monkeypatch.setenv("COGNIA_REMOTO_PORT", "abc")
    assert cli._remoto_puerto() == 8777 and avisos and "abc" in avisos[0]
    assert cli._remoto_puerto("70000") == 8777


def test_remoto_estado_apagado(lineas, monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(_puerto_libre()))
    cli._slash_remoto("")
    texto = "\n".join(lineas)
    assert "control remoto" in texto and "off" in texto
    assert "nadie escucha" in texto and "/remoto arrancar" in texto
    assert "sin servidor.pid" in texto


def test_remoto_estado_escuchando_con_api(lineas, monkeypatch, tmp_path):
    (tmp_path / "remoto" / "token.txt").write_text("tok123", encoding="utf-8")
    puerto = _puerto_libre()
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(puerto))
    pedidas = []

    def _api(ruta, p, token, timeout=3.0):
        pedidas.append((ruta, p, token))
        if ruta == "/api/version":
            return True, {"version": "4.10.1"}
        return True, [{"pid": "p1", "sid": "20260824-1", "estado": "viva"},
                      {"pid": "p1", "sid": "20260824-2"}]
    monkeypatch.setattr(cli, "_remoto_api_get", _api)
    monkeypatch.setattr(cli, "_remoto_ip_lan", lambda: "192.168.1.5")
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", puerto)); srv.listen(1)
        cli._slash_remoto("estado")
    texto = "\n".join(lineas)
    assert "on" in texto and "escucha" in texto
    assert "4.10.1" in texto and "sesiones vivas" in texto and "2" in texto
    assert "20260824-1" in texto
    assert f"https://192.168.1.5:{puerto}/?token=tok123" in texto
    assert {r for r, _, t in pedidas} == {"/api/version", "/api/monitores"}
    assert all(t == "tok123" and p == puerto for _, p, t in pedidas)


def test_remoto_estado_escuchando_sin_token_avisa(lineas, monkeypatch):
    puerto = _puerto_libre()
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(puerto))
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", puerto)); srv.listen(1)
        cli._slash_remoto("estado")
    assert "no hay token.txt" in "\n".join(lineas)


def test_remoto_estado_api_caida_lo_dice(lineas, monkeypatch, tmp_path):
    (tmp_path / "remoto" / "token.txt").write_text("tok", encoding="utf-8")
    puerto = _puerto_libre()
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(puerto))
    monkeypatch.setattr(cli, "_remoto_api_get",
                        lambda ruta, p, t, timeout=3.0: (False, "ConnectError: rechazada"))
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", puerto)); srv.listen(1)
        cli._slash_remoto("estado")
    texto = "\n".join(lineas)
    assert "/api/version: ConnectError" in texto and "/api/monitores: ConnectError" in texto


def test_remoto_url(lineas, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_remoto_ip_lan", lambda: "10.0.0.7")
    puerto = _puerto_libre()
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(puerto))
    cli._slash_remoto("url")
    texto = "\n".join(lineas)
    assert lineas[0].strip() == f"https://10.0.0.7:{puerto}/"     # sin ?token=
    assert "sin token.txt" in texto and "no escucha" in texto
    lineas.clear()
    (tmp_path / "remoto" / "token.txt").write_text("abc\n", encoding="utf-8")
    cli._slash_remoto("url")
    assert f"https://10.0.0.7:{puerto}/?token=abc" in "\n".join(lineas)


def test_remoto_uso_invalido(lineas):
    cli._slash_remoto("bailar")
    assert lineas and "Uso: /remoto" in lineas[0]


def test_remoto_parar_sin_pid(lineas, monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(_puerto_libre()))
    cli._slash_remoto("parar")
    assert "no esta arrancado" in "\n".join(lineas)


def test_remoto_parar_pid_muerto_borra_el_fichero(lineas, monkeypatch, tmp_path):
    """Formato viejo (int) o PID muerto: el lector del servidor
    (sesiones.leer_pid_servidor) lo juzga rancio y lo retira; el CLI lo
    dice en pantalla y no mata nada."""
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(_puerto_libre()))
    pid_f = tmp_path / "remoto" / "servidor.pid"
    pid_f.write_text("999999991", encoding="utf-8")
    cli._slash_remoto("parar")
    texto = "\n".join(lineas)
    assert "rancio" in texto and "no esta arrancado" in texto and not pid_f.exists()
    _pid_json(tmp_path, 999999991)
    lineas.clear()
    cli._slash_remoto("parar")
    assert "rancio" in "\n".join(lineas) and not pid_f.exists()


def test_remoto_parar_pid_muerto_avisa_si_el_cli_no_puede_borrar(lineas, monkeypatch, tmp_path):
    """(3) los unlink de _remoto_parar ya no callan."""
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(_puerto_libre()))
    monkeypatch.setattr(cli, "_remoto_pid_servidor", lambda: 999999991)
    monkeypatch.setattr(cli, "_remoto_proceso_vivo", lambda pid: False)
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado", lambda v, d="": avisos.append((v, d)))
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(PermissionError("ocupado")))
    cli._slash_remoto("parar")
    assert "ya no existe" in "\n".join(lineas)
    assert avisos and avisos[0][0] == "remoto" and "ocupado" in avisos[0][1]


def test_proceso_vivo_consulta_sin_matar():
    p = subprocess.Popen([str(PY), "-c", "import time; time.sleep(30)"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert cli._remoto_proceso_vivo(p.pid) is True
        assert p.poll() is None                          # preguntar NO mato
    finally:
        p.kill(); p.wait(5)
    assert cli._remoto_proceso_vivo(p.pid) is False
    assert cli._remoto_proceso_vivo(None) is False


def test_remoto_parar_no_mata_otro_python_con_el_pid(lineas, monkeypatch, tmp_path):
    """Un PID vivo que NO es un servidor de Cognia (PID reciclado por
    Windows, revisores 2026-08-25): ni con formato viejo ni con JSON se
    mata; el fichero rancio se retira."""
    puerto = _puerto_libre()
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(puerto))
    p = subprocess.Popen([str(PY), "-c", "import time; time.sleep(60)"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid_f = tmp_path / "remoto" / "servidor.pid"
    try:
        pid_f.write_text(str(p.pid), encoding="utf-8")
        cli._slash_remoto("parar")
        assert "rancio" in "\n".join(lineas) and not pid_f.exists()
        _pid_json(tmp_path, p.pid, port=puerto)
        cli._slash_remoto("parar")
        assert not pid_f.exists()
        time.sleep(0.5)
        assert p.poll() is None                        # sigue vivo
    finally:
        if p.poll() is None:
            p.kill()
    assert "Remoto parado" not in "\n".join(lineas)


def test_remoto_arrancar_si_ya_escucha_no_lanza(lineas, monkeypatch):
    puerto = _puerto_libre()
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(puerto))
    lanzados = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: lanzados.append(a))
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", puerto)); srv.listen(1)
        cli._slash_remoto("arrancar")
    assert lanzados == [] and "ya escucha" in "\n".join(lineas)


def test_remoto_arrancar_lanza_desacoplado_y_reporta_si_muere(lineas, monkeypatch, tmp_path):
    puerto = _puerto_libre()
    lanzados = []

    class _Proc:
        pid = 4242
        returncode = 3

        def poll(self):
            return 3
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: (lanzados.append((cmd, kw)), _Proc())[1])
    cli._slash_remoto(f"arrancar --host 10.0.0.5 --port {puerto}")
    assert len(lanzados) == 1
    cmd, kw = lanzados[0]
    assert cmd[:3] == [sys.executable, "-m", "cognia.remoto"]
    assert cmd[3:] == ["--host", "10.0.0.5", "--port", str(puerto)]
    if ES_WINDOWS:
        assert kw["creationflags"] & subprocess.DETACHED_PROCESS
        assert kw["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert kw["start_new_session"] is True
    assert kw["stdin"] is subprocess.DEVNULL and kw["env"]["PYTHONUTF8"] == "1"
    # servidor.pid lo escribe el SERVIDOR (JSON), no el CLI: escribirlo aqui
    # era la carrera de dos formatos (revisores 2026-08-25).
    assert not (tmp_path / "remoto" / "servidor.pid").exists()
    texto = "\n".join(lineas)
    assert "termino solo (exit 3)" in texto and "servidor.log" in texto


def test_remoto_arrancar_sin_port_explicito_no_lo_pasa(monkeypatch, lineas):
    lanzados = []

    class _Proc:
        pid = 1
        returncode = 1

        def poll(self):
            return 1
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: (lanzados.append(cmd), _Proc())[1])
    monkeypatch.setattr(cli, "_remoto_escucha", lambda *a, **k: False)
    cli._slash_remoto("arrancar")
    assert lanzados[0] == [sys.executable, "-m", "cognia.remoto"]


def test_remoto_limpiar_delega_en_el_subcomando(lineas, monkeypatch):
    corridas = []

    def _run(cmd, **kw):
        corridas.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="borrado: proy-x\n", stderr="")
    monkeypatch.setattr(subprocess, "run", _run)
    cli._slash_remoto("limpiar --dry-run")
    assert corridas[0][:4] == [sys.executable, "-m", "cognia.remoto", "--limpiar"]
    assert corridas[0][4:] == ["--dry-run"]
    assert "borrado: proy-x" in "\n".join(lineas)


def test_remoto_limpiar_reporta_fallo(lineas, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 2, stdout="", stderr="unrecognized arguments: --limpiar"))
    cli._slash_remoto("limpiar")
    texto = "\n".join(lineas)
    assert "salio con 2" in texto and "unrecognized" in texto


# ===========================================================================
# /decirle y /cancelar
# ===========================================================================

def test_decirle_sin_args_uso_y_lista(lineas):
    cli._slash_decirle("")
    assert "Uso: /decirle" in lineas[0]
    assert any("ninguna corrida" in l for l in lineas)
    lineas.clear()
    cli._slash_decirle("solo-id")
    assert "Uso: /decirle" in lineas[0]


def test_decirle_agente_desconocido_lo_dice(lineas, bus):
    cli._slash_decirle("nada-20990101#pasos.1@1 hola")
    texto = "\n".join(lineas)
    assert "NO entregado" in texto and "desconocido_corrida" in texto
    # decirle() emite MensajeAlAgente tambien al rechazar
    assert any(isinstance(e, events.MensajeAlAgente) and not e.aceptado for e in bus)


def test_decirle_aceptado(lineas, monkeypatch):
    from cognia.agent import workflows
    monkeypatch.setattr(workflows, "decirle", lambda aid, t: {
        "ok": True, "estado": "aceptado", "pendientes": 1, "detalle": "",
        "agente_id": aid, "run_id": "r", "agentes": 1, "corridas": 0})
    cli._slash_decirle("r#pasos.1@1 usa la otra ruta")
    assert "Mensaje entregado a r#pasos.1@1" in lineas[0] and "1 en cola" in lineas[0]


def test_cancelar_sin_args_uso(lineas):
    cli._slash_cancelar("")
    assert "Uso: /cancelar" in lineas[0]


def test_cancelar_desconocido(lineas):
    cli._slash_cancelar("nada-20990101#pasos.1@1")
    texto = "\n".join(lineas)
    assert "No se cancelo" in texto and "desconocido_corrida" in texto


def test_cancelar_aceptado_y_ya_termino(lineas, monkeypatch):
    from cognia.agent import workflows
    monkeypatch.setattr(workflows, "cancelar_agente", lambda aid, motivo="": {
        "ok": True, "estado": "aceptado", "pendientes": 0, "detalle": "",
        "agente_id": aid, "run_id": "r", "agentes": 1, "corridas": 0})
    cli._slash_cancelar("r#pasos.1@1")
    assert "Cancelado r#pasos.1@1" in lineas[0]
    lineas.clear()
    monkeypatch.setattr(workflows, "cancelar_agente", lambda aid, motivo="": {
        "ok": False, "estado": "ya_termino", "pendientes": 0,
        "detalle": "el agente ya entrego su resultado; no se cancelo nada",
        "agente_id": aid, "run_id": "r", "agentes": 0, "corridas": 0})
    cli._slash_cancelar("r#pasos.1@1")
    assert "ya_termino" in lineas[0] and "no se cancelo nada" in lineas[0]


def test_cancelar_todo(lineas, monkeypatch):
    from cognia.agent import workflows
    monkeypatch.setattr(workflows, "cancelar_corrida", lambda rid="", motivo="": {
        "ok": True, "estado": "aceptado", "pendientes": 0, "detalle": "",
        "agente_id": "", "run_id": "", "agentes": 2, "corridas": 1})
    cli._slash_cancelar("todo")
    assert "1 corrida(s), 2 agente(s)" in lineas[0]


def test_cancelar_todo_sin_corridas_lo_declara(lineas):
    cli._slash_cancelar("todo")            # workflows real, sin corridas vivas
    assert lineas and ("Nada que cancelar" in lineas[0] or "0 corrida(s)" in lineas[0])


# ===========================================================================
# (A2) revisores 2026-08-25: la interrupcion ANTES del stream mataba el REPL
# ===========================================================================

def test_bucle_del_repl_protege_la_iteracion_entera():
    """El KeyboardInterrupt del handler salia del bucle (que solo protegia
    _get_input) cuando llegaba entre el input() y el primer token
    (_confianza_previa, enrutador por inferencia): el REPL moria con exit
    3221225786. Ahora el cuerpo entero del `while True:` va bajo un
    `except KeyboardInterrupt` que llama a _repl_iteracion_interrumpida."""
    import inspect
    src = inspect.getsource(cli._repl_sesion)
    i = src.index("\n    while True:\n")
    j = src.rindex("_captura_slash_remoto_fin()")       # el de despues del bucle
    cuerpo = src[i:j]
    assert "        try:\n" in cuerpo[:1500]
    k = cuerpo.rindex("        except KeyboardInterrupt:")
    assert "_repl_iteracion_interrumpida()" in cuerpo[k:k + 200]
    # los puntos sin guard fino que mataban el REPL quedan DENTRO del try
    for marca in ("_confianza_previa(raw, _conf_cfg)", "_ruta, _extra = decidir("):
        assert cuerpo.index(marca) < k, marca


def test_repl_iteracion_interrumpida_remoto_y_local(lineas, monkeypatch):
    cli._INTERRUPCION_PENDIENTE[0] = True
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    assert cli._repl_iteracion_interrumpida() is True       # -> continue
    assert cli._INTERRUPCION_PENDIENTE[0] is False          # bandera consumida
    assert any("interrumpida desde el remoto" in l and "sigue vivo" in l for l in lineas)
    lineas.clear()
    monkeypatch.delenv("COGNIA_REMOTO")
    assert cli._repl_iteracion_interrumpida() is True
    assert any("Ctrl-C: turno cortado" in l for l in lineas)


def test_repl_reentra_tras_ki_residual_bajo_remoto(lineas, monkeypatch, capsys):
    """Un KeyboardInterrupt que escapa de _repl_sesion (senal durante el
    arranque, ya con el handler puesto) no mata el proceso bajo remoto: se
    reentra (tope 3). En local sale limpio, sin traceback."""
    llamadas = []

    def _sesion():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(cli, "_repl_sesion", _sesion)
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    cli.repl()                                      # no propaga
    assert len(llamadas) == 3
    assert sum("reentrada" in l for l in lineas) == 2
    # tope: 4 KI seguidos -> sale con 'Hasta luego.' en vez de ciclar
    llamadas.clear(); lineas.clear()
    monkeypatch.setattr(cli, "_repl_sesion", lambda: (llamadas.append(1), (_ for _ in ()).throw(KeyboardInterrupt())))
    cli.repl()
    assert len(llamadas) == 4 and "Hasta luego." in capsys.readouterr().out
    # local: un solo intento, salida limpia
    llamadas.clear(); lineas.clear()
    monkeypatch.delenv("COGNIA_REMOTO")
    cli.repl()
    assert len(llamadas) == 1 and not lineas


def test_handler_levanta_la_bandera_y_corte_pedido_la_ve(bus):
    """(4) cancelacion cooperativa: la senal deja la bandera puesta y
    _corte_pedido() (ctx['_cancelado'] del agente) la ve entre pasos."""
    cli._INTERRUPCION_PENDIENTE[0] = False
    assert cli._corte_pedido() is False
    with pytest.raises(KeyboardInterrupt):
        cli._interrupcion_remota_handler()
    assert cli._INTERRUPCION_PENDIENTE[0] is True
    assert cli._corte_pedido() is True
    cli._repl_iteracion_interrumpida()               # el bucle la consume
    assert cli._corte_pedido() is False


def test_handler_avisa_degradado_si_el_bus_falla(monkeypatch):
    """(3) el `except Exception: pass` del handler ya no calla."""
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado", lambda v, d="": avisos.append((v, d)))
    monkeypatch.setattr(events, "emitir", lambda ev: (_ for _ in ()).throw(RuntimeError("bus roto")))
    with pytest.raises(KeyboardInterrupt):
        cli._interrupcion_remota_handler()
    assert avisos and avisos[0][0] == "remoto.interrupcion" and "bus roto" in avisos[0][1]


def test_handler_nativo_avisa_en_el_acto_y_cede(bus):
    """(4) el handler de consola (hilo del sistema) emite el Aviso 'recibida'
    EN EL ACTO, levanta la bandera y devuelve False para que el del CRT
    convierta el evento en SIGBREAK (si devolviera True se comeria la senal).
    Ocioso en el prompt: no avisa ni marca (el de Python dira 'ignorada')."""
    cli._INTERRUPCION_PENDIENTE[0] = False
    assert cli._interrupcion_recibida_nativa(1) is False
    assert cli._INTERRUPCION_PENDIENTE[0] is True
    assert [e for e in bus if isinstance(e, events.Aviso) and
            "interrupcion recibida" in e.texto and "llamada en curso" in e.texto]
    bus.clear(); cli._INTERRUPCION_PENDIENTE[0] = False
    assert cli._interrupcion_recibida_nativa(2) is False     # CLOSE: no es nuestro
    assert not bus and cli._INTERRUPCION_PENDIENTE[0] is False
    cli._EN_PROMPT[0] = True
    assert cli._interrupcion_recibida_nativa(1) is False
    assert not bus and cli._INTERRUPCION_PENDIENTE[0] is False


def _backend_ok() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3) as r:
            return b'"ok"' in r.read()
    except Exception:
        return False


def _repl_remoto_real(tmp_path):
    # COGNIA_HOME fresco SIN la marca del primer arranque: __main__ lanza el
    # asistente ("Cognia -- Bienvenido ... Elegi una opcion (1/2/3)") y se
    # queda esperando una opcion; nunca sale "cognia>" y el test moria a los
    # 180 s (2 rojos deterministas, verificador e2e 2026-08-25). La marca es
    # la misma que deja run_wizard (first_run.FIRST_RUN_OK = ~/.cognia/.setup_done).
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / ".setup_done").touch()
    env = dict(os.environ, PYTHONUTF8="1", COGNIA_SPINNER="0", COGNIA_ANIMACION="0",
               NO_COLOR="1", COGNIA_REMOTO="1", COGNIA_EVENTS_JSONL="1",
               COGNIA_HOME=str(home),
               PYTHONPATH=str(RAIZ) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return subprocess.Popen([str(PY), "-m", "cognia"], cwd=str(RAIZ), env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)


@pytest.mark.skipif(not ES_WINDOWS, reason="CTRL_BREAK_EVENT es de Windows")
@pytest.mark.skipif(not _backend_ok(), reason="sin backend en :8080 (GET /health != ok)")
@pytest.mark.parametrize("retraso", [0.5, 2.5])
def test_interrumpir_antes_del_stream_no_mata_el_repl(tmp_path, retraso):
    """El repro de los revisores, de punta a punta y con modelo: REPL real por
    stdin bajo COGNIA_REMOTO=1 en su grupo de procesos, pregunta VOLATIL (la
    investigacion previa de confianza tarda segundos sin guard fino) y
    CTRL_BREAK a los 0,5 s / 2,5 s. Antes: rc 3221225786 y traceback en
    _confianza_previa. Ahora: el REPL sigue vivo, contesta 'hola' y sale por
    /salir con rc 0. El slot de :8080 es compartido: timeouts generosos."""
    import threading
    p = _repl_remoto_real(tmp_path)
    salida = bytearray()
    lock = threading.Lock()

    def _leer():
        for trozo in iter(lambda: p.stdout.read(1), b""):
            with lock:
                salida.extend(trozo)
    threading.Thread(target=_leer, daemon=True).start()

    def _esperar(marca: bytes, limite: float, desde: int = 0) -> int:
        t0 = time.time()
        while time.time() - t0 < limite:
            with lock:
                k = bytes(salida).find(marca, desde)
            if k >= 0:
                return k
            if p.poll() is not None:
                break
            time.sleep(0.1)
        return -1

    try:
        assert _esperar(b"cognia>", 180) >= 0, bytes(salida).decode("utf-8", "replace")[-800:]
        p.stdin.write("cuantos suscriptores tiene The Acua Boy en YouTube?\n".encode("utf-8"))
        p.stdin.flush()
        time.sleep(retraso)
        p.send_signal(signal.CTRL_BREAK_EVENT)
        # el KI se procesa al volver de la llamada bloqueada: hasta 10 min con
        # el slot compartido; lo que se exige es que el proceso SIGA vivo
        k = _esperar(b"interrumpid", 600)
        assert k >= 0 and p.poll() is None, (p.poll(), bytes(salida).decode("utf-8", "replace")[-1500:])
        p.stdin.write(b"hola\n/salir\n")
        p.stdin.flush()
        try:
            p.wait(timeout=600)
        except subprocess.TimeoutExpired:
            p.kill()
            pytest.fail("el REPL no salio tras /salir: " + bytes(salida).decode("utf-8", "replace")[-1500:])
        time.sleep(0.3)
        texto = bytes(salida).decode("utf-8", "replace")
        assert p.returncode == 0, (p.returncode, texto[-2000:])
        assert "Traceback" not in texto, texto[-2000:]
        assert "Hasta luego" in texto, texto[-1500:]
        # respondio DESPUES de la interrupcion: un FooterTurno posterior.
        # `k` es un offset en BYTES (el banner trae Braille multibyte) y
        # `texto` ya esta decodificado: texto[k:] caia mas alla del final y
        # daba '' (rojo falso cazado 2026-08-25); se busca en el str.
        desde = texto.find("interrumpid")
        assert desde >= 0
        assert '"tipo": "FooterTurno"' in texto[desde:], texto[desde:][-1500:]
    finally:
        if p.poll() is None:
            p.kill()


# ===========================================================================
# (H2) revisores 2026-08-25: servidor.pid es JSON del servidor, el CLI leia int
# ===========================================================================

def _pid_json(tmp_path, pid, port=8791) -> Path:
    import json
    f = tmp_path / "remoto" / "servidor.pid"
    f.write_text(json.dumps({"pid": pid, "host": "127.0.0.1", "port": port}),
                 encoding="utf-8")
    return f


@pytest.fixture
def servidor_falso(monkeypatch):
    """Un python vivo que el lector del servidor acepta como servidor de
    Cognia. La verificacion real (cmdline `-m cognia` o LISTEN en el puerto
    del fichero) es de sesiones.py y la cubre test_remoto_flujo_real con un
    servidor de verdad; aqui se prueba lo que hace el CLI con lo leido.
    (Medido 2026-08-25: psutil.Process.net_connections() devuelve [] para
    un hijo que escucha en 127.0.0.1 en esta maquina, asi que un listener
    falso NO pasa la segunda prueba del lector.)"""
    from cognia.remoto import sesiones as ses
    monkeypatch.setattr(ses, "es_servidor_cognia", lambda pr, info: (True, "test"))
    p = subprocess.Popen([str(PY), "-c", "import time; time.sleep(120)"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    yield p
    if p.poll() is None:
        p.kill(); p.wait(5)


def _servidor_falso(puerto: int):
    """Compat: el fixture ya tiene el proceso; esto solo devuelve otro
    sleep (para tests que necesitan dos). Ver `servidor_falso`."""
    return subprocess.Popen([str(PY), "-c", "import time; time.sleep(120)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_pid_servidor_json_del_servidor_se_lee(tmp_path, lineas, servidor_falso):
    """El fichero REAL que deja servidor.main(): {"pid","host","port"}. Con
    int() daba ValueError -> None (revisores, contra ~/.cognia/remoto)."""
    puerto = _puerto_libre()
    p = servidor_falso
    try:
        _pid_json(tmp_path, p.pid, port=puerto)
        assert cli._remoto_pid_servidor() == p.pid
        d = cli._remoto_leer_pid_servidor(tmp_path / "remoto")
        assert d["pid"] == p.pid and d["port"] == puerto and d["host"] == "127.0.0.1"
        assert not lineas
    finally:
        p.kill(); p.wait(5)
    # muerto -> None, fichero retirado y dicho en pantalla
    assert cli._remoto_pid_servidor() is None
    assert not (tmp_path / "remoto" / "servidor.pid").exists()
    assert any("rancio" in l for l in lineas)
    lineas.clear()
    assert cli._remoto_pid_servidor() is None and not lineas   # sin fichero: silencio


def test_parseo_local_sin_el_lector_del_servidor(tmp_path, monkeypatch):
    """Sin el paquete del servidor importable (psutil/fastapi ausentes) el
    CLI parsea el JSON el mismo, con fallback al int viejo, y lo avisa."""
    import builtins
    real_import = builtins.__import__

    def _imp(name, *a, **k):
        if name.startswith("cognia.remoto"):
            raise ImportError("sin psutil")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _imp)
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado", lambda v, d="": avisos.append((v, d)))
    _pid_json(tmp_path, 4243, port=8791)
    assert cli._remoto_leer_pid_servidor(tmp_path / "remoto") == {
        "pid": 4243, "host": "127.0.0.1", "port": 8791}
    (tmp_path / "remoto" / "servidor.pid").write_text("4242", encoding="utf-8")
    assert cli._remoto_pid_servidor() == 4242
    (tmp_path / "remoto" / "servidor.pid").write_text("{}", encoding="utf-8")
    assert cli._remoto_pid_servidor() is None
    (tmp_path / "remoto" / "servidor.pid").write_text("basura", encoding="utf-8")
    assert cli._remoto_pid_servidor() is None
    assert avisos and all(v == "remoto" for v, _ in avisos)
    assert any("ilegible" in d for _, d in avisos)


def test_pid_servidor_usa_el_lector_del_servidor_si_existe(tmp_path, monkeypatch):
    """Si sesiones.py (agente servidor) publica leer_pid_servidor, manda el."""
    from cognia.remoto import sesiones as ses
    vistos = []
    monkeypatch.setattr(ses, "leer_pid_servidor",
                        lambda raiz: (vistos.append(raiz), {"pid": 777, "host": "h", "port": 1})[1],
                        raising=False)
    assert cli._remoto_pid_servidor() == 777
    assert vistos == [tmp_path / "remoto"]


def test_remoto_estado_ve_el_pid_json(lineas, monkeypatch, tmp_path, servidor_falso):
    puerto = _puerto_libre()
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(_puerto_libre()))
    p = servidor_falso
    try:
        _pid_json(tmp_path, p.pid, port=puerto)
        cli._slash_remoto("")
    finally:
        p.kill(); p.wait(5)
    texto = "\n".join(lineas)
    assert f"{p.pid}" in texto
    assert "sin servidor.pid" not in texto and "muerto" not in texto


def test_remoto_parar_mata_por_pid_json_real(lineas, monkeypatch, tmp_path, servidor_falso):
    """/remoto parar con el JSON del servidor: lo encuentra, lo mata y borra
    el fichero (antes: 'no esta arrancado' con el servidor vivo)."""
    puerto = _puerto_libre()
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(puerto))
    p = servidor_falso
    pid_f = _pid_json(tmp_path, p.pid, port=puerto)
    try:
        cli._slash_remoto("parar")
        assert p.wait(timeout=10) is not None
    finally:
        if p.poll() is None:
            p.kill()
    assert "Remoto parado" in "\n".join(lineas) and not pid_f.exists()


def _hay_servidor_remoto() -> bool:
    try:
        import fastapi, uvicorn, psutil   # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _hay_servidor_remoto(), reason="sin fastapi/uvicorn/psutil")
def test_remoto_flujo_real_arrancar_estado_parar(lineas, monkeypatch, tmp_path):
    """El flujo de la puerta H de punta a punta con un servidor REAL
    (python -m cognia.remoto), con su RAIZ_DATOS en tmp_path (Path.home()
    lee USERPROFILE/HOME): /remoto arrancar NO escribe servidor.pid, el
    servidor escribe su JSON, /remoto estado lo ve vivo y /remoto parar lo
    mata y retira el fichero. Antes del arreglo: estado decia 'sin
    servidor.pid' y parar 'se arranco a mano' con el servidor vivo."""
    puerto = _puerto_libre()
    home = tmp_path / "home"
    raiz = home / ".cognia" / "remoto"
    raiz.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("COGNIA_REMOTO_PORT", str(puerto))
    monkeypatch.setenv("PYTHONPATH", str(RAIZ) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setattr(cli, "_remoto_raiz", lambda: raiz)
    pid_f = raiz / "servidor.pid"
    pid = None
    try:
        cli._slash_remoto("arrancar --host 127.0.0.1")
        texto = "\n".join(lineas)
        assert "Remoto arrancado" in texto, texto
        # lo escribio el SERVIDOR, en JSON, con su puerto
        import json
        dato = json.loads(pid_f.read_text(encoding="utf-8"))
        pid = dato["pid"]
        assert dato["port"] == puerto and cli._remoto_proceso_vivo(pid)
        assert cli._remoto_pid_servidor() == pid
        lineas.clear()
        cli._slash_remoto("")
        texto = "\n".join(lineas)
        assert str(pid) in texto and "muerto" not in texto and "sin servidor.pid" not in texto, texto
        lineas.clear()
        cli._slash_remoto("parar")
        texto = "\n".join(lineas)
        assert "Remoto parado" in texto, texto
        assert not pid_f.exists() and not cli._remoto_proceso_vivo(pid)
    finally:
        if pid and cli._remoto_proceso_vivo(pid):
            import psutil
            psutil.Process(pid).kill()
