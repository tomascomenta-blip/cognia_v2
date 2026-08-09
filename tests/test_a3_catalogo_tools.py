# -*- coding: utf-8 -*-
"""Regresion del AREA A3 (worklist F2, 2026-08-01): catalogo de tools.

- pantalla_* solo se registran con COGNIA_SCREEN activo (el A/B 2026-07-25
  midio que el catalogo grande degrada al 3B: camino feliz 4.25/5 -> 2.5/5).
- visible_tools() no oculta una tool cuyo flag de opt-in esta activo.
- `buscar` salta archivos grandes/binarios/venvs y respeta un deadline global.
- escribir_archivo avisa si un test_*.py colectaria 0 tests.
- _record_usage cablea UsageAnalytics (y NO escribe bajo pytest).

Cada test fallaba sin su fix (verificado escribiendolos contra el codigo previo).
"""
import os
from pathlib import Path

import pytest

import cognia.agents.workers.dev_tools as dev_tools
from cognia.agent import tools as T


def _ctx(**over):
    c = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    c.update(over)
    return c


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


# ── pantalla_* fuera del catalogo default ──────────────────────────────────

def _tools_en_proceso_limpio(env_extra):
    """Nombres del catalogo en un proceso NUEVO con env_extra aplicado.

    En SUBPROCESO y no con importlib.reload(T): recargar el modulo crea un
    TOOLS nuevo y VACIA las tools que otros modulos ya habian registrado en
    el dict viejo (lcd/escena_* se registran al importarse, y Python no las
    re-importa). Eso tumbaba 24 tests de tests/test_lcd_*.py cuando este
    archivo corria antes que ellos en la suite completa — verde en
    aislamiento, rojo en conjunto: contaminacion de test, no bug de
    producto. El registro es import-time, asi que la unica forma honesta de
    probarlo es un proceso limpio."""
    import json
    import subprocess
    import sys
    env = {**os.environ, "PYTHONUTF8": "1"}
    for k, v in env_extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    r = subprocess.run(
        [sys.executable, "-c",
         "import json;from cognia.agent import tools as T;"
         "print(json.dumps(sorted(T.TOOLS)))"],
        capture_output=True, text=True, timeout=180, env=env,
        cwd=str(Path(__file__).resolve().parents[1]))
    assert r.returncode == 0, r.stderr[-500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_pantalla_solo_se_registra_con_flag():
    """Sin COGNIA_SCREEN el catalogo NO trae las pantalla_*; con el flag vuelven."""
    con = _tools_en_proceso_limpio({"COGNIA_SCREEN": "1"})
    assert "pantalla_captura" in con
    assert "pantalla_click" in con

    sin = _tools_en_proceso_limpio({"COGNIA_SCREEN": None})
    assert not [n for n in sin if n.startswith("pantalla_")], \
        [n for n in sin if n.startswith("pantalla_")]


# ── visible_tools respeta el opt-in explicito ──────────────────────────────

def test_visible_tools_no_oculta_con_flag_activo(monkeypatch):
    from cognia.simple_mode import visible_tools
    todas = {"buscar", "web_buscar", "web_abrir", "repo_a_prompt", "git_diff"}
    # sin flag: en sencillo se ocultan (defensa doble de siempre)
    monkeypatch.delenv("COGNIA_BROWSER", raising=False)
    monkeypatch.delenv("COGNIA_REPO_REVERSE", raising=False)
    vis = visible_tools(todas, override="sencillo")
    assert "web_buscar" not in vis and "repo_a_prompt" not in vis
    # con flag: el opt-in explicito gana al recorte de UX
    monkeypatch.setenv("COGNIA_BROWSER", "1")
    vis = visible_tools(todas, override="sencillo")
    assert "web_buscar" in vis and "web_abrir" in vis
    assert "repo_a_prompt" not in vis      # su flag sigue apagado
    assert "git_diff" not in vis           # el resto del recorte no cambia


# ── buscar: skip de grandes/binarios/venvs + deadline ──────────────────────
# Estos tests fijan las garantias del scanner de FALLBACK (skip de grandes/
# binarios/venvs + deadline). Se escribieron cuando `rg` no estaba instalado;
# hoy SI esta en el PATH y contesta el, asi que hay que sacarlo de juego
# explicitamente (mismo patron que test_buscar_declara_el_corte...) — si no,
# los 4 fallaban por el ambiente, no por el producto (verificado 2026-08-09
# corriendo el checkout intacto: fallan igual sin ningun cambio).

@pytest.fixture
def sin_rg(monkeypatch):
    monkeypatch.setattr(T.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("sin rg")))


def test_dir_saltable_cubre_venvs_y_datos():
    assert T._dir_saltable(("x", "venv312gpu", "y"))
    assert T._dir_saltable(("datos_bancos",))
    assert T._dir_saltable(("venv_lo_que_sea",))
    assert not T._dir_saltable(("cognia", "agent"))


def test_buscar_salta_archivos_grandes_y_binarios(sin_rg, tmp_path):
    (tmp_path / "chico.txt").write_text("aca esta AGUJA123\n", encoding="utf-8")
    grande = tmp_path / "grande.jsonl"
    grande.write_text("AGUJA123 relleno\n" * 150_000, encoding="utf-8")  # >2MB
    (tmp_path / "binario.dat").write_bytes(b"\0\0AGUJA123\0\0")
    out = T.run_tool("buscar", f"AGUJA123 | {tmp_path}", _ctx())
    assert "chico.txt" in out
    assert "grande.jsonl" not in out
    assert "binario.dat" not in out


def test_buscar_deadline_corta_y_lo_declara(sin_rg, tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("AGUJA123\n", encoding="utf-8")
    # deadline ya vencido al entrar: el scan corta sin leer nada
    monkeypatch.setattr(T, "_SCAN_DEADLINE_S", -1.0)
    out = T.run_tool("buscar", f"AGUJA123 | {tmp_path}", _ctx())
    assert "sin coincidencias" in out
    assert "cortado" in out     # honesto: cortado por tiempo != "no esta"


def test_buscar_fallback_web_usa_navegador_con_flag(tmp_path, monkeypatch):
    """Con COGNIA_BROWSER=1 la pregunta del mundo va por navegador.buscar_en_web
    (texto completo saneado), no por los snippets de 180 chars."""
    monkeypatch.setenv("COGNIA_BROWSER", "1")
    import cognia.knowledge.navegador as nav

    def _fake(consulta, max_resultados=2, **kw):
        return {"resultados": [{"titulo": "Undertale", "via": "chromium",
                                "url": "https://x", "texto": "RPG de Toby Fox " * 30}],
                "descartados": [], "aviso": ""}

    monkeypatch.setattr(nav, "buscar_en_web", _fake)
    out = T.run_tool("buscar", f"que es undertale | {tmp_path}", _ctx())
    assert "chromium" in out and "Toby Fox" in out


# ── buscar: el falso 'no esta' (revision adversarial 2026-08-01) ───────────

def test_buscar_avisa_si_el_ambito_pedido_esta_en_skip_dirs(sin_rg, tmp_path):
    """Pedir explicitamente un ambito de _SKIP_DIRS devolvia 'sin coincidencias'
    SIN decir que se salto el directorio ENTERO: el falso negativo del que no
    se puede sospechar (modo de fallo historico de esta tool)."""
    venv = tmp_path / "venv312"
    venv.mkdir()
    (venv / "x.txt").write_text("aca esta AGUJA123\n", encoding="utf-8")
    out = T.run_tool("buscar", f"AGUJA123 | {venv}", _ctx())
    assert "sin coincidencias" in out          # el scan sigue saltandolo
    assert "NO escaneados" in out and "ENTERO" in out
    assert "NO prueba" in out                  # y lo dice explicitamente


def test_buscar_no_avisa_de_ambito_normal(tmp_path):
    """El aviso NO puede aparecer en un directorio corriente (seria ruido)."""
    (tmp_path / "x.txt").write_text("nada\n", encoding="utf-8")
    out = T.run_tool("buscar", f"AGUJA123 | {tmp_path}", _ctx())
    assert "NO escaneados" not in out


class _Reloj:
    """Reloj falso: devuelve los valores en orden y se queda en el ultimo."""
    def __init__(self, valores):
        self.valores, self.i = list(valores), 0

    def time(self):
        v = self.valores[min(self.i, len(self.valores) - 1)]
        self.i += 1
        return v


def test_buscar_declara_el_corte_aunque_haya_matches_parciales(tmp_path, monkeypatch):
    """La nota de 'scan cortado' solo se emitia si NO hubo resultados: un scan
    cortado con matches PARCIALES se presentaba como busqueda completa y el
    agente concluia que solo habia esos."""
    for n in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / n).write_text("aca esta AGUJA123\n", encoding="utf-8")
    # rg fuera de juego: se prueba el camino de fallback (el unico en esta maq.)
    monkeypatch.setattr(T.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("sin rg")))
    # t=0 al fijar el deadline y en el primer candidato; t=1000 (vencido) en el
    # segundo -> hay 1 match Y el scan se corto.
    monkeypatch.setattr(T, "_time", _Reloj([0, 0, 1000]))
    out = T.run_tool("buscar", f"AGUJA123 | {tmp_path}", _ctx())
    assert "AGUJA123" in out and ".txt" in out   # hubo match parcial
    assert "sin coincidencias" not in out
    assert "cortado" in out                      # y se declara igual


def test_deadline_lee_el_env_en_la_llamada(sin_rg, tmp_path, monkeypatch):
    """_SCAN_DEADLINE_S se leia del env en IMPORT-TIME: embebido (modulo ya
    cargado) el knob no hacia nada. Ahora se lee en cada llamada."""
    (tmp_path / "a.txt").write_text("AGUJA123\n", encoding="utf-8")
    monkeypatch.setenv("COGNIA_BUSCAR_DEADLINE", "-1")   # despues del import
    assert T._deadline_s() == -1.0
    out = T.run_tool("buscar", f"AGUJA123 | {tmp_path}", _ctx())
    assert "cortado" in out
    # basura en el env no revienta la tool: cae al default del modulo
    monkeypatch.setenv("COGNIA_BUSCAR_DEADLINE", "no-un-numero")
    assert T._deadline_s() == T._SCAN_DEADLINE_S


# ── ROLE_TOOLS: las 7 pantalla_*, no 5 ─────────────────────────────────────

def test_role_tools_trae_las_7_pantalla_con_flag():
    """El bloque gateado registraba 7 tools de pantalla y solo metia 5 en el
    rol: pantalla_ventanas y pantalla_activar_ventana quedaban registradas y
    recortadas por delegar_subtarea."""
    # En subproceso limpio por lo mismo que _tools_en_proceso_limpio: un
    # importlib.reload(T) aqui vaciaba el catalogo de las tools lcd/escena_*.
    import json
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, "-c",
         "import json;from cognia.agent import tools as T;"
         "p=sorted(n for n in T.TOOLS if n.startswith('pantalla_'));"
         "print(json.dumps({'reg':p,'rol':sorted(T.ROLE_TOOLS['implementador'])}))"],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, "PYTHONUTF8": "1", "COGNIA_SCREEN": "1"},
        cwd=str(Path(__file__).resolve().parents[1]))
    assert r.returncode == 0, r.stderr[-500:]
    d = json.loads(r.stdout.strip().splitlines()[-1])
    registradas = set(d["reg"])
    assert len(registradas) == 7, sorted(registradas)
    assert registradas <= set(d["rol"]), sorted(registradas - set(d["rol"]))


# ── pantalla_* apagada: 'deshabilitada', no 'no existe' ────────────────────

def test_run_tool_pantalla_apagada_dice_como_habilitarla(monkeypatch):
    monkeypatch.delenv("COGNIA_SCREEN", raising=False)
    out = T.run_tool("pantalla_captura", "", _ctx())
    assert "DESHABILITADA" in out and "COGNIA_SCREEN=1" in out
    assert "no existe" not in out


def test_intent_no_sugiere_pantalla_sin_flag(monkeypatch):
    """intent sugeria pantalla_captura siempre; con el registro gateado el
    agente pedia una tool ausente y el usuario leia 'herramienta no existe'."""
    from cognia.agent import intent

    monkeypatch.delenv("COGNIA_SCREEN", raising=False)
    i = intent.detect("mandame la captura de pantalla")
    assert i.needs_agent                      # sigue siendo una accion
    assert i.suggested_tool == ""             # pero no se sugiere la ausente
    assert "COGNIA_SCREEN=1" in i.aviso

    monkeypatch.setenv("COGNIA_SCREEN", "1")
    i = intent.detect("mandame la captura de pantalla")
    assert i.suggested_tool == "pantalla_captura"
    assert i.aviso == ""


def test_intent_gate_tambien_para_activar_ventana(monkeypatch):
    from cognia.agent import intent

    monkeypatch.delenv("COGNIA_SCREEN", raising=False)
    i = intent.detect("pone Chrome al frente que esta detras")
    assert i.needs_agent and i.suggested_tool == ""
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    assert intent.detect("pone Chrome al frente que esta detras"
                         ).suggested_tool == "pantalla_activar_ventana"


# ── escribir_archivo: defensa de test files vacios ─────────────────────────

def test_escribir_test_sin_funciones_avisa(workspace):
    out = T.run_tool("escribir_archivo",
                     str(workspace / "tests" / "test_nada.py") + " | x = 1\n",
                     _ctx())
    assert "OK" in out and "AVISO" in out and "0 tests" in out


def test_escribir_test_con_funcion_no_avisa(workspace):
    out = T.run_tool("escribir_archivo",
                     str(workspace / "tests" / "test_ok.py")
                     + " | def test_a():\n    assert True\n", _ctx())
    assert "OK" in out and "AVISO" not in out


def test_escribir_test_def_dentro_de_string_no_cuenta(workspace):
    # un 'def test_' dentro de un string NO es una funcion colectable
    out = T.run_tool("escribir_archivo",
                     str(workspace / "tests" / "test_str.py")
                     + ' | s = "def test_falso(): pass"\n', _ctx())
    assert "AVISO" in out


def test_escribir_py_normal_no_avisa(workspace):
    out = T.run_tool("escribir_archivo",
                     str(workspace / "util.py") + " | x = 1\n", _ctx())
    assert "OK" in out and "AVISO" not in out


# ── _record_usage cablea UsageAnalytics ────────────────────────────────────

def test_record_usage_llama_analytics(monkeypatch):
    llamadas = []

    class _Fake:
        def record(self, feature, user_id="default"):
            llamadas.append(feature)

    monkeypatch.setattr(T, "_ANALYTICS", _Fake())
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    T._record_usage("fecha", True)
    assert llamadas == ["tool.fecha"]


def test_record_usage_no_escribe_bajo_pytest(monkeypatch):
    llamadas = []

    class _Fake:
        def record(self, feature, user_id="default"):
            llamadas.append(feature)

    monkeypatch.setattr(T, "_ANALYTICS", _Fake())
    # PYTEST_CURRENT_TEST esta puesta por pytest: NO debe registrar
    assert os.environ.get("PYTEST_CURRENT_TEST")
    T._record_usage("fecha", True)
    assert llamadas == []
