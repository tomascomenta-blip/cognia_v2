"""
WP3 — Presentacion (obra 2026-08-09): renderer de eventos, logger silencioso
en consola, arranque compacto y footer honesto.

Cada test falla sin su fix:
- el renderer y su de-dup no existian (los eventos se imprimian crudos),
- la consola del logger arrancaba en INFO con formato de 6 columnas,
- `import cognia.config` imprimia lineas [OK]/[WARN] a stdout,
- sin_backend/registrar imprimian a stderr aunque el CLI estuviera escuchando,
- _show_footer inventaba tokens con len//4,
- el arranque animado dormia ~0.7s y el banner media ~55 lineas.
"""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cognia.ux import events
from cognia.ux import renderer as ux_renderer

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable


@pytest.fixture()
def bus_limpio():
    """Renderer fresco suscrito al bus; se desuscribe al salir para no
    contaminar otros tests del mismo proceso."""
    ux_renderer.desactivar()
    r = ux_renderer.activar(console=None)   # sin rich: print plano, capturable
    yield r
    ux_renderer.desactivar()


# ---------------------------------------------------------------------------
# Renderer: eventos sinteticos -> lineas estilo SOTA
# ---------------------------------------------------------------------------

def test_tool_fin_ok_linea_compacta(bus_limpio, capsys):
    events.emitir(events.ToolInicio(tool="leer_archivo", args="motor.py", paso=1))
    events.emitir(events.ToolFin(tool="leer_archivo", args="motor.py",
                                 ok=True, resumen="42 lineas", paso=1))
    out = capsys.readouterr().out
    assert "⏺ Leyendo motor.py — 42 lineas" in out


def test_tool_fin_error_visible(bus_limpio, capsys):
    events.emitir(events.ToolFin(tool="ejecutar", args="pytest -q", ok=False,
                                 resumen="exit 1\nFAILED test_x.py::test_y"))
    out = capsys.readouterr().out
    assert "✗" in out and "fallo" in out
    assert "exit 1" in out
    assert "FAILED test_x.py::test_y" in out     # el detalle del error se ve


def test_degradado_ambar_una_sola_vez(bus_limpio, capsys):
    ev = events.Degradado(donde="fast-path", motivo="sin backend",
                          accion_sugerida="python scripts/servir_flota.py pensar")
    events.emitir(ev)
    events.emitir(events.Degradado(donde="fast-path", motivo="sin backend"))
    out = capsys.readouterr().out
    assert out.count("degradado — fast-path") == 1
    assert "python scripts/servir_flota.py pensar" in out


def test_aviso_deduplicado(bus_limpio, capsys):
    for _ in range(5):
        events.emitir(events.Aviso(texto="backend: gpt-oss :8080 via chat",
                                   origen="backend_activo"))
    out = capsys.readouterr().out
    assert out.count("backend: gpt-oss :8080 via chat") == 1


def test_tarea_inicio_resetea_dedup(bus_limpio, capsys):
    events.emitir(events.Degradado(donde="x", motivo="m"))
    events.emitir(events.TareaInicio(tarea="otra"))
    events.emitir(events.Degradado(donde="x", motivo="m"))
    out = capsys.readouterr().out
    assert out.count("degradado — x") == 2       # una por tarea


def test_streaming_y_footer_con_tokens_reales(bus_limpio, capsys):
    events.emitir(events.TareaInicio(tarea="t"))
    for tok in ["Hola ", "mundo ", "desde ", "el ", "stream."]:
        events.emitir(events.TokenTexto(texto=tok))
    events.emitir(events.TareaFin(ok=True, resumen="", pasos=3,
                                  tokens_predichos=87, duracion_s=3.2))
    out = capsys.readouterr().out
    assert "Hola mundo desde el stream." in out
    assert "87 tokens" in out                    # usage real del evento
    assert "3 pasos" in out
    assert "~" not in out                        # nada de tokens inventados


def test_footer_sin_tokens_no_inventa(bus_limpio, capsys):
    events.emitir(events.TareaFin(ok=True, resumen="listo", pasos=0,
                                  tokens_predichos=0, duracion_s=2.0))
    out = capsys.readouterr().out
    assert "2.0s" in out
    assert "tokens" not in out


def test_remoto_no_streamea_la_prosa(bus_limpio, capsys, monkeypatch):
    # Bajo COGNIA_REMOTO=1 la respuesta final llega ENTERA y plana via
    # _show_response (contrato con el clasificador del movil); streamearla
    # ademas la pegaba duplicada en el chat (e2e de WP5, 2026-08-09).
    from cognia.ux.renderer import Renderer
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    r = Renderer(console=None)
    events.suscribir(r)
    try:
        events.emitir(events.TokenTexto(texto="hola "))
        events.emitir(events.TokenTexto(texto="mundo"))
        assert "hola" not in capsys.readouterr().out
    finally:
        events.desuscribir(r)


def test_tarea_fin_no_imprime_el_resumen(bus_limpio, capsys):
    # Contrato desde 2026-08-09 (fix del e2e): TareaFin se emite ANTES del
    # post-procesado de cli.py (adjuntos, 2a pasada), asi que su resumen esta
    # incompleto y el handler de /hacer ya muestra la respuesta enriquecida.
    # El renderer imprime SOLO el footer; el resumen viaja en el evento para
    # el sink JSONL/remoto. Imprimirlo aqui duplicaba la respuesta final.
    events.emitir(events.TareaFin(ok=True, resumen="# Titulo\n- item",
                                  duracion_s=2.0, pasos=2))
    out = capsys.readouterr().out
    assert "Titulo" not in out and "item" not in out
    assert "2.0s" in out                         # el footer si sale


def test_evento_malformado_no_rompe(bus_limpio, capsys):
    # emitir() es no-lanzante y el renderer se guarda a si mismo: un evento
    # con campos raros no puede tumbar el turno (el footer del TareaFin
    # posterior debe seguir saliendo).
    events.emitir(events.ToolFin(tool=None, args=None, ok=True, resumen=None))
    events.emitir(events.TokenTexto(texto=None))
    events.emitir(events.TareaFin(ok=True, resumen="sigo vivo",
                                  duracion_s=3.0, pasos=1))
    assert "3.0s" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Logger: consola WARNING con formato corto; INFO al archivo
# ---------------------------------------------------------------------------

def test_consola_arranca_en_warning():
    from cognia import logger_config
    # sin COGNIA_LOG_LEVEL el handler de consola no deja pasar INFO
    if os.environ.get("COGNIA_LOG_LEVEL"):
        pytest.skip("COGNIA_LOG_LEVEL seteado en el entorno")
    assert logger_config._CONSOLE_HANDLER is not None
    assert logger_config._CONSOLE_HANDLER.level >= logging.WARNING


def test_poner_nivel_consola_en_caliente():
    from cognia import logger_config
    original = logger_config._CONSOLE_HANDLER.level
    try:
        logger_config.poner_nivel_consola("DEBUG")
        assert logger_config._CONSOLE_HANDLER.level == logging.DEBUG
        assert logging.getLogger("cognia").level == logging.DEBUG
    finally:
        logger_config._CONSOLE_HANDLER.setLevel(original)
        logging.getLogger("cognia").setLevel(logging.INFO)


def test_info_va_al_archivo_no_a_consola(tmp_path):
    """En un proceso limpio: logger.info no toca stderr y SI queda en el
    archivo (COGNIA_LOG_FILE pisa la ruta por defecto)."""
    log = tmp_path / "cognia.log"
    env = dict(os.environ, PYTHONUTF8="1", COGNIA_LOG_FILE=str(log))
    env.pop("COGNIA_LOG_LEVEL", None)
    r = subprocess.run(
        [PY, "-c",
         "from cognia.logger_config import get_logger;"
         "get_logger('prueba').info('hola-archivo')"],
        capture_output=True, text=True, cwd=str(REPO), env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "hola-archivo" not in r.stderr
    assert "hola-archivo" in log.read_text(encoding="utf-8")


def test_import_config_y_fatiga_silencioso(tmp_path):
    """`import cognia.config` imprimia [OK]/[WARN] en cada import (pytest,
    remoto, scripts). Ahora: ni stdout ni stderr."""
    env = dict(os.environ, PYTHONUTF8="1",
               COGNIA_LOG_FILE=str(tmp_path / "l.log"))
    env.pop("COGNIA_LOG_LEVEL", None)
    r = subprocess.run(
        [PY, "-c", "import cognia.config, cognia.fatiga_cognitiva"],
        capture_output=True, text=True, cwd=str(REPO), env=env, timeout=180)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""
    assert "[OK]" not in r.stderr and "[WARN]" not in r.stderr


# ---------------------------------------------------------------------------
# backend_activo: al bus si hay oyentes, a stderr si no
# ---------------------------------------------------------------------------

@pytest.fixture()
def audit_aislado(tmp_path, monkeypatch):
    import cognia.backend_activo as BA
    monkeypatch.setattr(BA, "AUDIT", tmp_path / "audit.jsonl")
    BA._props_cache.clear()
    return BA


def test_sin_backend_emite_degradado_sin_stderr(audit_aislado, capsys):
    recibidos = []
    events.suscribir(recibidos.append)
    try:
        audit_aislado.sin_backend("chat", "prueba wp3")
    finally:
        # los bound methods comparan por igualdad: desuscribir() los encuentra
        events.desuscribir(recibidos.append)
    err = capsys.readouterr().err
    assert "DEGRADADO" not in err            # ya no grita a stderr: hay oyente
    degradados = [e for e in recibidos if isinstance(e, events.Degradado)]
    assert len(degradados) == 1
    assert degradados[0].donde == "chat"
    assert "servir_flota" in degradados[0].accion_sugerida


def test_sin_backend_grita_a_stderr_sin_oyentes(audit_aislado, capsys):
    # sin suscriptores el grito clasico sigue: scripts y tests lo necesitan
    assert not events._suscriptores
    audit_aislado.sin_backend("chat", "prueba wp3")
    assert "DEGRADADO" in capsys.readouterr().err


def test_registrar_emite_aviso_sin_stderr(audit_aislado, capsys):
    recibidos = []
    events.suscribir(recibidos.append)
    try:
        audit_aislado.registrar("chat", "http://127.0.0.1:1", rol="pensar")
    finally:
        events.desuscribir(recibidos.append)
    err = capsys.readouterr().err
    assert "[backend]" not in err
    avisos = [e for e in recibidos if isinstance(e, events.Aviso)]
    assert len(avisos) == 1 and avisos[0].origen == "backend_activo"


# ---------------------------------------------------------------------------
# CLI: footer honesto, arranque compacto y sin teatro
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cli():
    import cognia.cli as cli_mod
    return cli_mod


def test_show_footer_no_inventa_tokens(cli, capsys):
    cli._show_footer(2.5, "una respuesta cualquiera de largo arbitrario")
    out = capsys.readouterr().out
    assert "~" not in out
    assert "tokens" not in out               # sin usage real, sin numero


def test_show_footer_con_tokens_reales(cli, capsys):
    if not cli._HAS_RICH or not cli._console:
        pytest.skip("sin rich no hay footer")
    cli._show_footer(2.5, "resp", tokens=123)
    assert "123 tokens" in capsys.readouterr().out


def test_banner_completo_por_defecto_con_modelo_real(cli, capsys, monkeypatch):
    # El dueño pidio el banner de vuelta (2026-08-09): la identidad va por
    # defecto, el ruido no. Debajo del gato tiene que salir el modelo REAL
    # servido (el banner viejo decia Qwythos mientras :8080 servia gpt-oss).
    monkeypatch.delenv("COGNIA_BANNER", raising=False)
    import cognia.backend_activo as BA
    monkeypatch.setattr(BA, "estado", lambda: {
        "url": "http://127.0.0.1:8080", "modelo": "gpt-oss-20b-MXFP4.gguf",
        "puerto": 8080, "avisos": []})
    cli._print_startup_panel()
    ux_renderer.desactivar()                 # _arranque_ux suscribio: limpiar
    out = capsys.readouterr().out
    assert len(out.split("\n")) > 20         # el gato Braille completo
    assert "gpt-oss-20b" in out              # el modelo REAL servido


def test_banner_min_sigue_disponible(cli, capsys, monkeypatch):
    monkeypatch.setenv("COGNIA_BANNER", "min")
    import cognia.backend_activo as BA
    monkeypatch.setattr(BA, "estado", lambda: {
        "url": "http://127.0.0.1:8080", "modelo": "gpt-oss-20b-MXFP4.gguf",
        "puerto": 8080, "avisos": []})
    cli._print_startup_panel()
    ux_renderer.desactivar()
    out = capsys.readouterr().out
    lineas = [l for l in out.split("\n") if l.strip()]
    assert len(lineas) <= 8, f"banner min no compacto: {len(lineas)} lineas"
    assert "gpt-oss-20b" in out
    assert "/ayuda" in out


def test_animate_startup_sin_sleeps(cli, capsys):
    lineas = [f"[OK] Subsistema {i} activo" for i in range(5)] + ["[WARN] ojo"]
    t0 = time.perf_counter()
    cli._animate_startup(lineas)
    elapsed = time.perf_counter() - t0
    # el viejo dormia 0.045/linea + 0.48 de barra falsa (~0.7s con 5 lineas)
    assert elapsed < 0.3, f"animacion teatral sigue viva: {elapsed:.2f}s"
    out = capsys.readouterr().out
    assert "ojo" in out                      # los WARN siempre se ven
