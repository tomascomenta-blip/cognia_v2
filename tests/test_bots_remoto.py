# -*- coding: utf-8 -*-
"""
tests/test_bots_remoto.py
=========================
El modo BOTS en el control remoto (cognia/remoto/bots_api.py + bots.html):
token, 404 de bot inexistente, roster, canon, inbox, rutinas y POST mensaje
con ejecutor falso. Sin modelo; RAIZ_DATOS y COGNIA_BOTS_DIR en tmp_path
(nada en ~/.cognia).
"""

import pytest
from starlette.testclient import TestClient

from cognia.bots import registro as R, mensajeria as M
from cognia.remoto import bots_api, servidor as _srv


@pytest.fixture(autouse=True)
def aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_BOTS_DIR", str(tmp_path / "bots"))
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COGNIA_DB_PATH", str(tmp_path / "db"))
    monkeypatch.setenv("COGNIA_BOTS_NOTIF", "0")
    monkeypatch.delenv("COGNIA_RUTINAS_DIR", raising=False)
    monkeypatch.setattr(_srv, "RAIZ_DATOS", tmp_path / "remoto")
    (tmp_path / "remoto").mkdir()
    monkeypatch.setattr(bots_api, "correr_turno_fn", None)
    bots_api._EN_CURSO.clear()
    return tmp_path


def _cliente():
    app = _srv.crear_app()
    c = TestClient(app)
    c.headers.update({"X-Cognia-Token": _srv.asegurar_token(_srv.RAIZ_DATOS)})
    return c


def test_api_bots_exige_token():
    c = TestClient(_srv.crear_app())
    assert c.get("/api/bots").status_code == 401
    # la pagina, como "/", se sirve sin token (el front lleva el suyo)
    r = c.get("/bots")
    assert r.status_code == 200 and "Cognia Bots" in r.text
    assert "X-Cognia-Token" in r.text and "/api/bots/" in r.text


def test_roster_vacio_y_con_bots():
    c = _cliente()
    assert c.get("/api/bots").json() == []
    R.crear("ana", titulo="Analista", descripcion="mira numeros")
    R.crear("oculto"); b = R.obtener("oculto"); b.oculto = True; R.guardar(b)
    filas = c.get("/api/bots").json()
    assert [f["nombre"] for f in filas] == ["ana"]           # el oculto no sale
    f = filas[0]
    assert f["titulo"] == "Analista" and f["activo"] is False
    assert f["inbox_pendientes"] == 0 and f["rutinas"] == 0
    assert f["glifo"] and f["color"]


def test_bot_inexistente_404():
    c = _cliente()
    for ruta in ("/api/bots/nadie/canon", "/api/bots/nadie/inbox", "/api/bots/nadie/rutinas"):
        r = c.get(ruta)
        assert r.status_code == 404 and "nadie" in r.json()["error"]
    r = c.post("/api/bots/nadie/mensaje", json={"texto": "hola"})
    assert r.status_code == 404


def test_post_mensaje_anota_en_canon_con_ejecutor_falso(monkeypatch):
    R.crear("ana")
    llamadas = []

    def _falso(bot, texto):
        llamadas.append((bot.nombre, texto))
        M.anotar_canon(bot, "usuario", texto)
        M.anotar_canon(bot, "cognia", "respuesta falsa")
        return "respuesta falsa"
    monkeypatch.setattr(bots_api, "correr_turno_fn", _falso)
    c = _cliente()
    r = c.post("/api/bots/ana/mensaje", json={"texto": "hola ana", "esperar": True}).json()
    assert r == {"ok": True, "bot": "ana", "respuesta": "respuesta falsa"}
    assert llamadas == [("ana", "hola ana")]
    canon = c.get("/api/bots/ana/canon").json()
    assert [(e["quien"], e["texto"]) for e in canon] == [
        ("usuario", "hola ana"), ("cognia", "respuesta falsa")]
    assert c.get("/api/bots").json()[0]["activo"] is True
    # texto vacio = 400, no un turno vacio
    assert c.post("/api/bots/ana/mensaje", json={"texto": "  "}).status_code == 400


def test_post_mensaje_encolado_por_defecto(monkeypatch):
    """Sin esperar: responde al instante y el turno corre en un hilo."""
    import threading
    R.crear("ana")
    hecho = threading.Event()

    def _falso(bot, texto):
        M.anotar_canon(bot, "cognia", "hilo: " + texto)
        hecho.set()
        return "ok"
    monkeypatch.setattr(bots_api, "correr_turno_fn", _falso)
    c = _cliente()
    r = c.post("/api/bots/ana/mensaje", json={"texto": "hola"}).json()
    assert r.get("encolado") is True
    assert hecho.wait(5)
    assert c.get("/api/bots/ana/canon").json()[-1]["texto"] == "hilo: hola"


def test_post_mensaje_409_si_ya_responde(monkeypatch):
    R.crear("ana")
    monkeypatch.setattr(bots_api, "correr_turno_fn", lambda b, t: "x")
    bots_api._EN_CURSO.add("ana")
    c = _cliente()
    assert c.post("/api/bots/ana/mensaje", json={"texto": "hola", "esperar": True}).status_code == 409


def test_inbox_y_rutinas_del_bot():
    from cognia.hermes import rutinas
    R.crear("ana"); R.crear("beto")
    M.enviar(de="beto", para="ana", texto="ping")
    bot = R.obtener("ana")
    with R.contexto(bot, canon=False):
        rutinas.crear("conteo", "30m", "cuenta", bot="ana", entregar="inbox")
    c = _cliente()
    inbox = c.get("/api/bots/ana/inbox").json()
    assert inbox["total_pendientes"] == 1 and inbox["pendientes"][0]["de"] == "beto"
    rr = c.get("/api/bots/ana/rutinas").json()
    assert [r["nombre"] for r in rr["rutinas"]] == ["conteo"]
    assert rr["rutinas"][0]["bot"] == "ana" and rr["rutinas"][0]["entregar"] == "inbox"
    fila = c.get("/api/bots").json()[0]
    assert fila["inbox_pendientes"] == 1 and fila["rutinas"] == 1 and fila["proxima_rutina"]
    # beto no tiene rutinas: su almacen esta vacio, no el de ana
    assert c.get("/api/bots/beto/rutinas").json()["rutinas"] == []
