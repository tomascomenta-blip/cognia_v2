# -*- coding: utf-8 -*-
"""
Regresion (2026-08-24): una tool colgada congelaba el turno sin senal y el
proceso que lanzo seguia vivo ('matar el shell no mata el proceso'). Estos
tests fijan el contrato de `cognia/harness/timeout_tool.py` (timeout-policy
de deepseek-harness): precedencia del deadline (spec > global, 0 = sin
limite, el interno de ejecutar/tests manda, las tools LLM sin deadline), el
resultado TIPADO (TOOL_TIMEOUT) que baja por el pipeline normal de run_tool
sin excepcion, la quiescencia (el hijo registrado muere DE VERDAD) y la
config invalida que grita.

Sin el modulo, el fichero entero falla en el import.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from cognia.harness import timeout_tool as tt


@pytest.fixture(autouse=True)
def aislado(monkeypatch):
    monkeypatch.delenv(tt.ENV_TIMEOUT, raising=False)
    monkeypatch.delenv(tt.ENV_GRACIA, raising=False)
    monkeypatch.setattr(tt, "_AVISADOR", None)
    tt._ULTIMO.clear()
    tt._ULTIMO_ERROR.clear()
    tt._TOTAL[0] = 0
    from cognia.agent import tools as T
    T._TIMEOUT_AVISADO.clear()


def _ctx():
    return {"working_memory": {}, "agent_state": {},
            "print_fn": lambda *a, **k: None}


def _spec(fn, **extra):
    s = {"fn": fn, "doc": "p", "danger": False, "desc": "", "params": [],
         "timeout_s": None, "timeout_interno": None}
    s.update(extra)
    return s


# ── Precedencia ──────────────────────────────────────────────────────────────

def test_default_global_120_y_env_lo_mueve(monkeypatch):
    assert tt.timeout_efectivo("x", _spec(None), "") == 120
    monkeypatch.setenv(tt.ENV_TIMEOUT, "7")
    assert tt.timeout_efectivo("x", _spec(None), "") == 7
    monkeypatch.setenv(tt.ENV_TIMEOUT, "0")
    assert tt.timeout_efectivo("x", _spec(None), "") == 0


def test_spec_manda_sobre_el_global(monkeypatch):
    monkeypatch.setenv(tt.ENV_TIMEOUT, "7")
    assert tt.timeout_efectivo("x", _spec(None, timeout_s=30), "") == 30
    assert tt.timeout_efectivo("x", _spec(None, timeout_s=0), "") == 0


def test_tools_que_llaman_al_modelo_sin_deadline():
    assert tt.timeout_efectivo("delegar_subtarea", _spec(None), "") == 0
    assert tt.timeout_efectivo("rlm_llamar", _spec(None), "") == 0


def test_el_interno_de_ejecutar_manda_sobre_el_externo(monkeypatch):
    """`ejecutar ... | timeout=300` con global 120: el externo se estira a
    305 y NUNCA corta antes que el subprocess."""
    from cognia.agent.tools import TOOLS
    spec = TOOLS["ejecutar"]
    assert callable(spec.get("timeout_interno"))
    assert tt.timeout_efectivo("ejecutar", spec, "sleep 1 | timeout=300") == 305
    # con interno chico, el global (mayor) se queda
    assert tt.timeout_efectivo("ejecutar", spec, "echo hola") == 120
    assert tt.timeout_efectivo("tests", TOOLS["tests"], "tests/x.py") == 185


@pytest.mark.parametrize("basura", ["abc", "-5"])
def test_global_invalido_lanza_al_cargar(basura, monkeypatch):
    monkeypatch.setenv(tt.ENV_TIMEOUT, basura)
    with pytest.raises(tt.ConfigInvalida):
        tt.timeout_global()
    with pytest.raises(tt.ConfigInvalida):
        tt.timeout_efectivo("x", _spec(None), "")
    assert tt.estado()["config_error"]


# ── El ejecutor ──────────────────────────────────────────────────────────────

def test_vuelve_a_tiempo_y_limpia_el_ctx():
    ctx = _ctx()
    out, agotada, info = tt.correr_con_deadline(
        lambda a, c: f"ok {a}", "t", "arg", ctx, 5)
    assert out == "ok arg" and agotada is False
    assert "_cancelar_tool" not in ctx and "_deadline" not in ctx


def test_la_excepcion_de_la_tool_se_relanza():
    def _rota(a, c):
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        tt.correr_con_deadline(_rota, "t", "", _ctx(), 5)


def test_vence_y_devuelve_resultado_tipado(monkeypatch):
    monkeypatch.setenv(tt.ENV_GRACIA, "1")
    avisos = []
    tt.registrar_avisador(lambda o, m: avisos.append((o, m)))

    def _cuelga(a, ctx):
        ev = ctx.get("_cancelar_tool")
        ev.wait(30)                      # coopera: sale al cancelarse
        return "tarde"

    ctx = _ctx()
    t0 = time.time()
    out, agotada, info = tt.correr_con_deadline(_cuelga, "lenta", "", ctx, 1)
    assert agotada is True
    assert time.time() - t0 < 5
    assert out.startswith("RESULTADO lenta ERROR: tool agotada tras 1s (TOOL_TIMEOUT)")
    assert info["hilo_vivo"] is False    # coopero: quiescente
    assert avisos == []                  # nada que avisar
    assert tt._ULTIMO["quiescente"] is True


def test_no_quiescente_se_dice(monkeypatch):
    monkeypatch.setenv(tt.ENV_GRACIA, "1")
    avisos = []
    tt.registrar_avisador(lambda o, m: avisos.append((o, m)))
    out, agotada, info = tt.correr_con_deadline(
        lambda a, c: time.sleep(4), "terca", "", _ctx(), 1)
    assert agotada and info["hilo_vivo"] is True
    assert "NO termino en la gracia" in out
    assert avisos and avisos[0][0] == "timeout_tool"


# ── Quiescencia: el hijo muere DE VERDAD ─────────────────────────────────────

def test_el_hijo_registrado_muere_de_verdad(monkeypatch):
    monkeypatch.setenv(tt.ENV_GRACIA, "5")
    pids = []

    def _lanza(a, ctx):
        p = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(60)"])
        pids.append(p)
        ctx["_procesos_tool"].append(p)
        p.wait()                          # bloquea hasta que lo maten
        return "nunca"

    ctx = _ctx()
    out, agotada, info = tt.correr_con_deadline(_lanza, "hijo", "", ctx, 1)
    assert agotada
    p = pids[0]
    assert p.poll() is not None           # el Popen lo vio morir
    assert tt.pid_vivo(p.pid) is False    # y la sonda de PID tambien
    assert info["matados"] == 1 and info["vivos"] == []
    assert info["hilo_vivo"] is False     # p.wait() volvio: el hilo quiescio


# ── Por el pipeline real de run_tool ─────────────────────────────────────────

@pytest.fixture
def tool_lenta(monkeypatch):
    from cognia.agent import tools as T

    def _fn(args, ctx):
        ctx["_exit"] = 0                  # un exit rancio que NO debe salir
        ctx.get("_cancelar_tool").wait(30)
        return "RESULTADO lenta: tarde"

    monkeypatch.setitem(T.TOOLS, "lenta", {
        "fn": _fn, "doc": "lenta", "danger": False, "desc": "", "params": [],
        "timeout_s": 1, "timeout_interno": None})


def test_run_tool_timeout_baja_por_el_pipeline_sin_excepcion(tool_lenta, monkeypatch):
    """El test que falla sin el cableado en run_tool: resultado tipado, ok
    False, exit None (no 0) y el interceptor.despues SI corrio encima."""
    monkeypatch.setenv(tt.ENV_GRACIA, "1")
    from cognia.agent.tools import run_tool
    from cognia.harness import interceptor
    vistos = []
    original = interceptor.despues

    def _despues(name, args, ctx, out, ok, exit_code=None):
        vistos.append((name, ok, exit_code))
        return original(name, args, ctx, out, ok, exit_code=exit_code) + "\n[despues]"

    monkeypatch.setattr(interceptor, "despues", _despues)
    ctx = _ctx()
    out = run_tool("lenta", "x", ctx)
    assert isinstance(out, str)
    assert "TOOL_TIMEOUT" in out and out.startswith("RESULTADO lenta ERROR")
    assert out.rstrip().endswith("[despues]")
    assert vistos == [("lenta", False, None)]
    assert ctx["_ultimo_ok"] is False and ctx["_ultimo_exit"] is None
    assert tt._TOTAL[0] == 1


def test_run_tool_sin_deadline_corre_en_linea(monkeypatch):
    from cognia.agent import tools as T
    monkeypatch.setitem(T.TOOLS, "rapida", {
        "fn": lambda a, c: "RESULTADO rapida: ok", "doc": "r", "danger": False,
        "desc": "", "params": [], "timeout_s": 0, "timeout_interno": None})
    assert T.run_tool("rapida", "", _ctx()).startswith("RESULTADO rapida: ok")


def test_config_basura_avisa_y_corre_sin_deadline(tool_lenta, monkeypatch):
    """Global invalido: se grita UNA vez y la tool corre sin limite (aqui la
    tool declara 1 s, pero el spec numerico es lo que se evalua primero, asi
    que se usa una tool sin spec)."""
    monkeypatch.setenv(tt.ENV_TIMEOUT, "rapido")
    from cognia.agent import tools as T
    avisos = []
    monkeypatch.setattr(T, "_avisar_timeout_degradado",
                        lambda exc: avisos.append(str(exc)))
    monkeypatch.setitem(T.TOOLS, "sin_spec", {
        "fn": lambda a, c: "RESULTADO sin_spec: ok", "doc": "s", "danger": False,
        "desc": "", "params": [], "timeout_s": None, "timeout_interno": None})
    assert T.run_tool("sin_spec", "", _ctx()).startswith("RESULTADO sin_spec: ok")
    assert avisos and "rapido" in avisos[0]
