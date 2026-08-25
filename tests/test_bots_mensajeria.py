# -*- coding: utf-8 -*-
"""
tests/test_bots_mensajeria.py
=============================
Tests de cognia/bots/mensajeria.py (inbox entre bots + chat canonico).

Sin modelo, sin red, sin ~/.cognia: COGNIA_BOTS_DIR/COGNIA_HOME a tmp_path y
COGNIA_BOTS_NOTIF=0 (el NotificationCenter escribe en la db de escritorio
del repo; la rama con notificacion se prueba inyectando un notificador).
"""

import json
import threading

import pytest

from cognia.bots import registro as R
from cognia.bots import mensajeria as M


@pytest.fixture(autouse=True)
def bots_aislados(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_BOTS_DIR", str(tmp_path / "bots"))
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COGNIA_BOTS_NOTIF", "0")
    monkeypatch.delenv("COGNIA_BOT", raising=False)
    R.crear("ana", titulo="Analista", descripcion="mira numeros")
    R.crear("beto", titulo="Redactor", descripcion="escribe")
    return tmp_path


def _inbox(tmp_path, nombre):
    return tmp_path / "bots" / nombre / "inbox.jsonl"


# ── enviar ────────────────────────────────────────────────────────────────

def test_enviar_escribe_envelope(tmp_path):
    r = M.enviar("ana", "beto", "hola beto")
    assert r["ok"] is True and r["id"] and r["motivo"] == "encolado"
    assert "aviso" not in r
    lineas = _inbox(tmp_path, "beto").read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    m = json.loads(lineas[0])
    assert m == {"id": r["id"], "t": m["t"], "de": "ana", "para": "beto",
                 "texto": "hola beto", "hops": 0, "entregado": False}
    assert not _inbox(tmp_path, "ana").exists()


def test_enviar_valida_destino(tmp_path):
    r = M.enviar("ana", "nadie", "hola")
    assert r["ok"] is False and r["id"] == ""
    assert "destino desconocido" in r["motivo"] and "ana, beto" in r["motivo"]
    assert not _inbox(tmp_path, "nadie").exists()
    # por titulo y con @ tambien resuelve
    assert M.enviar("ana", "@Beto", "x")["ok"] is True
    assert M.enviar("ana", "redactor", "x")["ok"] is True
    assert len(M.pendientes("beto")) == 2


def test_enviar_vacio_y_a_si_mismo():
    assert M.enviar("ana", "beto", "   ")["ok"] is False
    r = M.enviar("ana", "ana", "hola yo")
    assert r["ok"] is False and "si mismo" in r["motivo"]


def test_enviar_tope_de_saltos(tmp_path):
    assert M.enviar("ana", "beto", "1", hops=2)["ok"] is True
    r = M.enviar("ana", "beto", "2", hops=3)
    assert r["ok"] is False and "tope de saltos" in r["motivo"]
    assert M.enviar("ana", "beto", "3", hops=1, max_hops=1)["ok"] is False
    assert len(M.pendientes("beto")) == 1
    assert M.pendientes("beto")[0]["hops"] == 2


def test_enviar_de_usuario_sin_emisor():
    r = M.enviar("", "beto", "hola")
    assert r["ok"] and M.pendientes("beto")[0]["de"] == "usuario"


def test_enviar_no_pasa_por_shell(tmp_path):
    texto = "$(rm -rf /) ; `whoami` && echo ${HOME} | cat"
    r = M.enviar("ana", "beto", texto)
    assert r["ok"]
    assert M.pendientes("beto")[0]["texto"] == texto


# ── notificacion opcional ────────────────────────────────────────────────

def test_notificacion_fallida_es_aviso_no_excepcion(monkeypatch):
    monkeypatch.delenv("COGNIA_BOTS_NOTIF", raising=False)
    import cognia.notifications.notification_center as NC

    class _Rota:
        def __init__(self, *a, **k):
            raise RuntimeError("db bloqueada")
    monkeypatch.setattr(NC, "NotificationCenter", _Rota)
    r = M.enviar("ana", "beto", "hola")
    assert r["ok"] is True
    assert "notificacion no creada" in r["aviso"] and "db bloqueada" in r["aviso"]
    assert M.pendientes("beto")[0]["aviso"] == r["aviso"]


def test_notificacion_se_crea_cuando_hay_centro(monkeypatch):
    monkeypatch.delenv("COGNIA_BOTS_NOTIF", raising=False)
    import cognia.notifications.notification_center as NC
    llamadas = []

    class _Falso:
        def __init__(self, *a, **k):
            pass

        def create(self, **kw):
            llamadas.append(kw)
            return kw
    monkeypatch.setattr(NC, "NotificationCenter", _Falso)
    r = M.enviar("ana", "beto", "hola")
    assert r["ok"] and "aviso" not in r
    assert llamadas[0]["user_id"] == "bot:beto"
    assert llamadas[0]["title"] == "Mensaje de @ana"


# ── pendientes / marcar ──────────────────────────────────────────────────

def test_pendientes_y_marcar_entregado(tmp_path):
    a = M.enviar("ana", "beto", "uno")["id"]
    b = M.enviar("ana", "beto", "dos")["id"]
    assert [m["id"] for m in M.pendientes("beto")] == [a, b]
    assert M.marcar_entregado("beto", a) is True
    assert [m["id"] for m in M.pendientes("beto")] == [b]
    assert M.marcar_entregado("beto", a) is False     # ya estaba
    assert M.marcar_entregado("beto", "zzz") is False
    # el fichero conserva los dos (auditoria), uno marcado
    filas = [json.loads(l) for l in _inbox(tmp_path, "beto").read_text(encoding="utf-8").splitlines()]
    assert [f["entregado"] for f in filas] == [True, False]
    assert filas[0]["entregado_t"]
    assert M.pendientes(R.obtener("beto")) == M.pendientes("beto")


def test_pendientes_sin_inbox_y_con_lineas_corruptas(tmp_path, caplog):
    assert M.pendientes("beto") == []
    M.enviar("ana", "beto", "ok")
    with _inbox(tmp_path, "beto").open("a", encoding="utf-8") as f:
        f.write("{esto no es json\n")
    assert len(M.pendientes("beto")) == 1
    assert any("corruptas" in r.message for r in caplog.records)


def test_escrituras_concurrentes_no_entrelazan(tmp_path):
    """Dos daemons escribiendo el mismo inbox: cada linea llega entera."""
    n_hilos, por_hilo = 8, 25

    def _w(k):
        for i in range(por_hilo):
            M.enviar("ana", "beto", f"h{k}-m{i}-" + "x" * 300)
    hilos = [threading.Thread(target=_w, args=(k,)) for k in range(n_hilos)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    lineas = _inbox(tmp_path, "beto").read_text(encoding="utf-8").splitlines()
    assert len(lineas) == n_hilos * por_hilo
    assert len(M.pendientes("beto")) == n_hilos * por_hilo


# ── formato / canon ──────────────────────────────────────────────────────

def test_formatear_entrante_golden():
    m = {"id": "abc", "de": "ana", "para": "beto", "texto": "revisa el informe"}
    assert M.formatear_entrante(m) == "Mensaje de 🤖 ana (@ana): revisa el informe"
    assert M.formatear_entrante({}) == "Mensaje de 🤖 ? (@?): "


def test_anotar_canon_y_transcripcion(tmp_path):
    assert M.transcripcion("ana") == []
    e = M.anotar_canon("ana", "usuario", "hola")
    assert set(e) == {"t", "quien", "texto"}
    M.anotar_canon("ana", "cognia", "que tal")
    tr = M.transcripcion("ana")
    assert [(x["quien"], x["texto"]) for x in tr] == [("usuario", "hola"), ("cognia", "que tal")]
    assert M.transcripcion("ana", limite=1)[0]["texto"] == "que tal"
    assert (tmp_path / "bots" / "ana" / "sesiones" / "canon.jsonl").is_file()
    assert R.activo("ana") is True
