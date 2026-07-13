# -*- coding: utf-8 -*-
"""Computer-use con gate de seguridad (screen_tools.py). Fake de pyautogui:
NUNCA mueve el mouse real. El foco es la POLICY del gate (opt-in,
confirmación, tope, auditoría), no el backend."""
import pytest

import cognia.agent.screen_tools as st


class _FakeGui:
    FAILSAFE = True
    PAUSE = 0.0

    def __init__(self):
        self.clicks = []
        self.typed = []
        self.hotkeys = []

    def size(self):
        return (1920, 1080)

    def click(self, x, y, button="left"):
        self.clicks.append((x, y, button))

    def typewrite(self, texto, interval=0):
        self.typed.append(texto)

    def hotkey(self, *teclas):
        self.hotkeys.append(teclas)


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    st.reset_contador()
    monkeypatch.setattr(st, "_AUDIT", tmp_path / "audit.jsonl")
    monkeypatch.delenv("COGNIA_SCREEN", raising=False)
    monkeypatch.delenv("COGNIA_SCREEN_AUTO", raising=False)
    yield


def test_deshabilitado_por_defecto(monkeypatch):
    # sin COGNIA_SCREEN=1 nada toca la maquina
    fake = _FakeGui()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    r = st.click({}, 100, 100)
    assert "DESHABILITADO" in r
    assert fake.clicks == []              # jamas se ejecuto


def test_click_requiere_confirmacion(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    fake = _FakeGui()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    # sin confirm ni auto -> rechazada
    r = st.click({}, 100, 100)
    assert "requiere confirmación" in r
    assert fake.clicks == []


def test_click_con_confirmacion_procede(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    fake = _FakeGui()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    ctx = {"confirm": lambda accion, detalle: True}
    r = st.click(ctx, 100, 200)
    assert "click: left en (100, 200)" in r
    assert fake.clicks == [(100, 200, "left")]


def test_click_modo_autonomo(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    monkeypatch.setenv("COGNIA_SCREEN_AUTO", "1")
    fake = _FakeGui()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    r = st.click({}, 50, 60)
    assert fake.clicks == [(50, 60, "left")]


def test_click_fuera_de_pantalla(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    monkeypatch.setenv("COGNIA_SCREEN_AUTO", "1")
    fake = _FakeGui()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    r = st.click({}, 5000, 5000)
    assert "fuera de" in r
    assert fake.clicks == []


def test_escribir_y_tecla_confirmadas(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    monkeypatch.setenv("COGNIA_SCREEN_AUTO", "1")
    fake = _FakeGui()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    assert "6 chars" in st.escribir({}, "holaaa")
    assert fake.typed == ["holaaa"]
    assert "ctrl+s" in st.tecla({}, "ctrl", "s")
    assert fake.hotkeys == [("ctrl", "s")]


def test_tope_de_acciones(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    monkeypatch.setenv("COGNIA_SCREEN_AUTO", "1")
    monkeypatch.setenv("COGNIA_SCREEN_MAX", "2")
    monkeypatch.setattr(st, "_MAX_ACCIONES", 2)
    fake = _FakeGui()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    st.click({}, 1, 1)
    st.click({}, 2, 2)
    r = st.click({}, 3, 3)               # la 3ra excede el tope
    assert "tope de" in r
    assert len(fake.clicks) == 2


def test_auditoria_registra(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    monkeypatch.setenv("COGNIA_SCREEN_AUTO", "1")
    fake = _FakeGui()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    st.click({}, 10, 20)
    assert st._AUDIT.exists()
    import json
    linea = json.loads(st._AUDIT.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert linea["accion"] == "click" and linea["resultado"] == "OK"


def test_captura_es_readonly(monkeypatch, tmp_path):
    # captura NO requiere confirmación (read-only) pero sí el opt-in
    monkeypatch.setenv("COGNIA_SCREEN", "1")

    class _Img:
        width, height = 800, 600
        def save(self, p): open(p, "wb").close()

    fake = _FakeGui()
    fake.screenshot = lambda region=None: _Img()
    monkeypatch.setattr(st, "_gui", lambda: fake)
    import cognia.agents.workers.dev_tools as dev
    monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    r = st.captura({})
    assert "800x600" in r                # procedió sin confirmación
