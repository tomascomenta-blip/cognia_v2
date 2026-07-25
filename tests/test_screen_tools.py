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


# ── Regresion 2026-07-25 (sesion real del dueno) ──────────────────────────
# Tres tareas seguidas murieron con "pantalla localizar ERROR: The confidence
# keyword argument is only available if OpenCV is installed" -> el agente las
# conto como acciones fallidas y se apago ("sin progreso"). Dos causas:
# el fallback capturaba TypeError y pyscreeze lanza NotImplementedError, y
# "no encontrada" llegaba como excepcion (pyscreeze>=1.0) y salia como ERROR.

class _GuiSinOpenCV:
    """locateOnScreen que exige el fallback: con confidence explota."""
    def __init__(self, encuentra=True):
        self.encuentra = encuentra
        self.sin_confidence = False

    def locateOnScreen(self, path, confidence=None):
        if confidence is not None:
            raise NotImplementedError(
                "The confidence keyword argument is only available if "
                "OpenCV is installed.")
        self.sin_confidence = True
        if not self.encuentra:
            import pyautogui
            raise pyautogui.ImageNotFoundException("")
        return (10, 20, 30, 40)

    def center(self, box):
        class _P:
            x, y = 25, 40
        return _P()


def test_localizar_sin_opencv_usa_el_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")
    gui = _GuiSinOpenCV(encuentra=True)
    monkeypatch.setattr(st, "_gui", lambda: gui)
    r = st.localizar({}, str(img))
    assert "ERROR" not in r and "centro" in r
    assert gui.sin_confidence, "debio reintentar sin el keyword confidence"


def test_localizar_no_encontrada_no_es_error(monkeypatch, tmp_path):
    """Para el agente un ERROR es una accion fallida y tres lo apagan;
    'no esta en pantalla' es un resultado normal."""
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")
    monkeypatch.setattr(st, "_gui", lambda: _GuiSinOpenCV(encuentra=False))
    r = st.localizar({}, str(img))
    assert r == "RESULTADO pantalla localizar: no encontrada"
    assert "ERROR" not in r


def test_localizar_archivo_inexistente_si_es_error(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    r = st.localizar({}, r"C:\no\existe\jamas.png")
    assert "ERROR" in r and "no existe" in r


def test_hay_tool_de_ventanas(monkeypatch):
    """Faltaba la capacidad entera: el dueno pidio "pone Chrome al frente" y
    el agente solo tenia buscar-imagen-en-pantalla."""
    registradas = {}

    def _tool(nombre, desc, danger=False):
        def _wrap(fn):
            registradas[nombre] = fn
            return fn
        return _wrap

    st.register(_tool)
    assert "pantalla_ventanas" in registradas
    assert "pantalla_activar_ventana" in registradas


def test_activar_ventana_sin_titulo_no_toca_la_maquina(monkeypatch):
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    monkeypatch.setenv("COGNIA_SCREEN_AUTO", "1")
    r = st.activar_ventana({}, "   ")
    assert "ERROR" in r and "titulo" in r


# ── Regresion 2026-07-25 (sesion 20260725-112753) ─────────────────────────
# Cognia TOMO la captura (el PNG estaba en disco) y contesto "Aqui tienes la
# foto" sin decir DONDE. Sin ruta en el texto, el control remoto no tiene nada
# que insertar: el dueno pidio la foto y no recibio nada.

def test_la_respuesta_adjunta_los_archivos_producidos(tmp_path):
    from cognia.cli import _adjuntar_archivos
    png = tmp_path / "captura_112804.png"
    png.write_bytes(b"\x89PNG fake")
    history = [f"RESULTADO pantalla captura: {png} (1920x1080)"]
    salida = _adjuntar_archivos("Aquí tienes la foto de la pantalla.", history)
    assert str(png) in salida
    assert salida.startswith("Aquí tienes la foto")


def test_no_adjunta_archivos_de_un_error_ni_inexistentes(tmp_path):
    from cognia.cli import _adjuntar_archivos
    fantasma = tmp_path / "no_existe.png"
    history = [f"RESULTADO pantalla captura ERROR: fallo {fantasma}",
               r"RESULTADO ejecutar (exit 0): listo"]
    assert _adjuntar_archivos("Listo.", history) == "Listo."


def test_no_repite_la_ruta_si_la_respuesta_ya_la_dice(tmp_path):
    from cognia.cli import _adjuntar_archivos
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG fake")
    texto = f"La dejé en {png}"
    assert _adjuntar_archivos(texto, [f"RESULTADO pantalla captura: {png}"]) == texto
