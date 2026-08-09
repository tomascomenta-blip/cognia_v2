"""
tests/test_cli_a2_fixes.py
==========================
Regresiones del AREA A2 (auditoria F2 2026-08-01), todas sobre cognia/cli.py:

  1. El turno del camino articulado NUNCA termina mudo: si responder_articulado
     devuelve texto vacio / error / lanza, el REPL imprime igual una respuesta
     minima explicita (y no solo el banner degradado).
  2. Bajo COGNIA_REMOTO=1 la respuesta articulada sale SIN panel (plana, con
     flush) para que el clasificador del movil la trate como chat, no como
     actividad (respuesta_final=True en cli.py ~8315).
  3. ReminderManager es singleton del proceso, con NotificationCenter cableado
     (los disparos llegan a /notif) y UN solo hilo checker.
  4. El ctx del loop del agente incluye 'confirm' (sentinel/pantalla_* lo leen;
     sin el, toda accion destructiva moria salvo COGNIA_SCREEN_AUTO=1).
  5. /skill explicito registra uso en .skill_usage.json (applied_skill llega a
     _run_agent_task -> record_skill_use).
  6. Skill que declara verificacion => el GoalContract exige pytest en verde
     sobre los tests escritos en la corrida.
  7. "Comando desconocido" se imprime en DOS lineas: el aviso ya no desaparece
     entero en modo sencillo por venir pegado a un '[detail]'.

Los tests del REPL usan un harness in-process: Cognia y los dos bordes del
turno (orquestador de streaming y responder_articulado) se stubbean en
sys.modules — el codigo del REPL que se ejercita es el REAL.
"""
from __future__ import annotations

import builtins
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import cognia.cli as cli


@pytest.fixture(autouse=True)
def _marco_accion_legacy(monkeypatch):
    """WP1 2026-08-09: los tests de _run_agent_task ejercitan el marco ACCION
    (perfil texto). Sin el env, con la flota real encendida el loop iria por
    bucle_nativo contra el server DE VERDAD (test no hermetico)."""
    monkeypatch.setenv("COGNIA_AGENT_LEGACY", "1")


# ---------------------------------------------------------------------------
# Harness del REPL
# ---------------------------------------------------------------------------

class _FakeChatHistory:
    def set_session(self, *a, **k):
        pass

    def get_recent_turns(self, *a, **k):
        return []


class _FakeCognia:
    """Minimo que el arranque del REPL y un turno de chat tocan de verdad."""

    def __init__(self):
        self.chat_history = _FakeChatHistory()

    def observe(self, *a, **k):
        pass


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _run_repl(monkeypatch, entradas, respuesta_articulada):
    """Corre cli.repl() con stdin scripteado y los bordes stubbeados.

    - shattering.orchestrator: constructor que LANZA -> fast-path degradado
      (es el escenario "sin backend" sin tocar el llama-server vivo).
    - respuestas_articuladas.responder_articulado: devuelve lo pedido.
    Devuelve todo lo impreso (stdout via capsys lo junta el caller).
    """
    class _OrchMuerto:
        def __init__(self, *a, **k):
            raise RuntimeError("sin backend (harness)")

    monkeypatch.setitem(
        sys.modules, "shattering.orchestrator",
        _mod("shattering.orchestrator", ShatteringOrchestrator=_OrchMuerto))
    monkeypatch.setitem(
        sys.modules, "cognia_v3.interfaces.respuestas_articuladas",
        _mod("cognia_v3.interfaces.respuestas_articuladas",
             responder_articulado=lambda ai, raw: respuesta_articulada))
    # bordes de arranque que no queremos ejercitar (bbrain regenera un .md del
    # repo; speech_cascade puede precalentar un server 0.5B)
    monkeypatch.setitem(sys.modules, "cognia.bbrain",
                        _mod("cognia.bbrain", write_bbrain=lambda *a, **k: None))
    monkeypatch.setitem(
        sys.modules, "node.speech_cascade",
        _mod("node.speech_cascade",
             prewarm_fast_speech=lambda *a, **k: None,
             classify_turn=lambda *a, **k: "slow",
             fast_speech_backend=lambda *a, **k: None,
             portero_activo=lambda *a, **k: False,
             portero_system=lambda *a, **k: ""))
    monkeypatch.setattr(cli, "Cognia", _FakeCognia)

    cola = list(entradas) + ["/salir"]

    def _input_fake(prompt=""):
        if not cola:
            raise EOFError
        return cola.pop(0)

    monkeypatch.setattr(builtins, "input", _input_fake)
    # sin animaciones ni panel: solo el flujo del turno
    monkeypatch.setattr(cli, "_print_startup_panel", lambda: None)
    monkeypatch.setattr(cli, "_animate_startup", lambda lines: None)
    cli.repl()


def test_turno_articulado_nunca_mudo(monkeypatch, capsys):
    """responder_articulado devuelve texto VACIO -> antes el turno terminaba
    sin ninguna respuesta visible (solo el banner degradado); ahora el REPL
    imprime una respuesta minima explicita."""
    _run_repl(monkeypatch, ["hola"], {"response": ""})
    out = capsys.readouterr().out
    assert "No pude generar una respuesta" in out


def test_turno_articulado_error_no_muda(monkeypatch, capsys):
    """Un dict {'error': ...} tampoco deja el turno mudo."""
    _run_repl(monkeypatch, ["hola"], {"error": "backend caido (harness)"})
    out = capsys.readouterr().out
    assert "No pude generar una respuesta" in out


def test_respuesta_articulada_final_en_remoto(monkeypatch, capsys):
    """Bajo COGNIA_REMOTO=1 la respuesta articulada tiene que salir PLANA
    (sin marco de panel): el clasificador del movil manda lo enmarcado a
    'actividad' y el chat quedaba mudo (cli.py ~8315 sin respuesta_final)."""
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    _run_repl(monkeypatch, ["hola"], {"response": "LISTO-HARNESS"})
    out = capsys.readouterr().out
    linea = next(ln for ln in out.splitlines() if "LISTO-HARNESS" in ln)
    assert "│" not in linea and "|" not in linea, (
        f"la respuesta salio enmarcada: {linea!r}")


# ---------------------------------------------------------------------------
# ReminderManager singleton + notificaciones
# ---------------------------------------------------------------------------

def test_reminder_singleton_notifica_y_un_solo_hilo(monkeypatch, tmp_path):
    import cognia.notifications.notification_center as nc_mod
    import cognia.reminders.reminder_manager as rm_mod

    db = str(tmp_path / "recordatorios.db")
    real_rm, real_nc = rm_mod.ReminderManager, nc_mod.NotificationCenter
    monkeypatch.setattr(rm_mod, "ReminderManager",
                        lambda: real_rm(db_path=db))
    monkeypatch.setattr(nc_mod, "NotificationCenter",
                        lambda: real_nc(db_path=db))
    monkeypatch.setattr(cli, "_REMINDER_MANAGER", None)

    antes = sum(1 for t in threading.enumerate()
                if t.name == "reminder-checker")
    rm1 = cli._get_reminder_manager()
    rm2 = cli._get_reminder_manager()
    try:
        # singleton: mismo objeto, UN hilo nuevo (antes: uno por slash command)
        assert rm1 is rm2
        despues = sum(1 for t in threading.enumerate()
                      if t.name == "reminder-checker")
        assert despues == antes + 1
        # el centro de notificaciones esta CABLEADO: un disparo llega a /notif
        assert rm1._notification_center is not None
        rm1.create(user_id="cli_user", title="prueba-a2",
                   fire_at=time.time() - 1)
        rm1._check_and_fire()
        items = rm1._notification_center.get_all("cli_user", include_read=False)
        assert len(items) == 1 and items[0]["title"] == "prueba-a2"
    finally:
        rm1.stop()


# ---------------------------------------------------------------------------
# Agente: ctx['confirm'], applied_skill y skill con verificacion
# ---------------------------------------------------------------------------

class _InferRes:
    def __init__(self, text):
        self.text = text


class _FakeOrch:
    """Orquestador scripteado: las ACCION salen en orden; las llamadas
    auxiliares (complejidad/decompose/extension) reciben algo inocuo."""

    def __init__(self, acciones):
        self._acciones = list(acciones)

    def infer(self, prompt, **kw):
        if "Siguiente ACCION:" in prompt:
            return _InferRes(self._acciones.pop(0) if self._acciones
                             else "ACCION: responder listo")
        if "COMPLEJIDAD" in prompt:
            return _InferRes("2")
        return _InferRes("0")


class _AiAgente:
    def __init__(self, orch):
        self._orchestrator = orch

    def observe(self, *a, **k):
        pass


def test_ctx_del_loop_incluye_confirm(monkeypatch):
    """sentinel.evaluar_shell y las pantalla_* leen ctx['confirm']; el loop
    nunca lo inyectaba -> default-deny permanente salvo COGNIA_SCREEN_AUTO."""
    import cognia.agent.tools as tools_mod
    visto = {}

    def _run_tool_fake(name, args, ctx):
        visto["confirm"] = ctx.get("confirm")
        return f"RESULTADO {name}: OK"

    monkeypatch.setattr(tools_mod, "run_tool", _run_tool_fake)
    orch = _FakeOrch(["ACCION: fecha_hora ahora", "ACCION: responder listo"])
    cli._run_agent_task(_AiAgente(orch), "di listo", lambda *a, **k: None)
    assert callable(visto.get("confirm"))
    assert visto["confirm"] is cli._confirmar_accion


def test_skill_explicita_registra_uso(monkeypatch, tmp_path):
    """applied_skill (el camino de /skill) tiene que terminar en
    record_skill_use -> .skill_usage.json del directorio de la skill."""
    import cognia.agent.skills as skills_mod
    sk_dir = tmp_path / "skills"
    sk_dir.mkdir()
    (sk_dir / "prueba-a2.md").write_text(
        "---\nname: prueba-a2\ndescription: skill de prueba A2\n---\ncuerpo\n",
        encoding="utf-8")
    monkeypatch.setattr(skills_mod, "SKILL_DIRS", [sk_dir])
    # el estado persistente del agente no debe tocar el HOME real
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    orch = _FakeOrch(["ACCION: responder listo"])
    cli._run_agent_task(_AiAgente(orch), "di listo", lambda *a, **k: None,
                        guidance="guia de la skill", applied_skill="prueba-a2")
    import json
    data = json.loads((sk_dir / ".skill_usage.json").read_text(encoding="utf-8"))
    assert data["prueba-a2"]["uses_ok"] + data["prueba-a2"]["uses_fail"] == 1


def test_skill_con_verificacion_exige_pytest(monkeypatch, tmp_path, capsys):
    """Si la skill declara verificacion ('verifica que pasen' / 'en verde'),
    el contrato agrega pytest sobre los tests ESCRITOS en la corrida y el
    cierre reporta el objetivo verificado con evidencia real."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(tmp_path))

    salida = []
    orch = _FakeOrch([
        "ACCION: escribir_archivo tests/test_a2_skill.py | def test_ok():\n    assert True",
        "ACCION: responder listo",
    ])
    cli._run_agent_task(
        _AiAgente(orch), "deja el modulo preparado", salida.append,
        guidance="Segui estas instrucciones: verifica que pasen los tests, "
                 "no termines hasta verlo en verde.",
        applied_skill="escribir-tests")
    texto = "\n".join(str(s) for s in salida)
    assert "pytest en verde sobre" in texto or "Objetivo verificado" in texto, texto


def test_comando_desconocido_visible_en_modo_sencillo(monkeypatch, capsys):
    """El aviso iba pegado al tip '[detail]' en UNA linea y el modo sencillo
    la suprimia ENTERA: el comando desconocido moria en silencio."""
    import cognia.simple_mode as sm
    monkeypatch.setattr(sm, "get_ui_mode", lambda override=None: "sencillo")
    _run_repl(monkeypatch, ["/comandoinventado"], {"response": "x"})
    out = capsys.readouterr().out
    assert "Comando desconocido" in out
