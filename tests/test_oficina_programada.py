# -*- coding: utf-8 -*-
"""Metas/tareas programadas de la oficina: dormir hasta despierta_ts,
jefe pre-creado dormido, despertar editable (mandato dueño 2026-07-09)."""
import time

import pytest

from cognia.oficina.estado import Oficina


@pytest.fixture()
def of(tmp_path):
    return Oficina(str(tmp_path / "estado.json"))


def test_meta_sin_programar_sale_ya(of):
    of.nueva_meta("hacer algo")
    assert of.meta_pendiente() is not None


def test_meta_programada_futura_no_sale(of):
    of.nueva_meta("tarea nocturna", despierta_ts=time.time() + 3600)
    assert of.meta_pendiente() is None


def test_meta_programada_pasada_sale(of):
    mid = of.nueva_meta("ya vencida", despierta_ts=time.time() + 0.05)
    time.sleep(0.1)
    m = of.meta_pendiente()
    assert m is not None and m["id"] == mid


def test_meta_programada_crea_jefe_dormido(of):
    ts = time.time() + 3600
    mid = of.nueva_meta("workflow de la manana", despierta_ts=ts)
    jid = of.jefe_de_meta(mid)
    assert jid is not None
    t = of.snapshot()["tareas"][jid]
    assert t["nivel"] == "jefe" and t["estado"] == "pendiente"
    assert t["despierta_ts"] == pytest.approx(ts)


def test_despertar_edita_meta_y_jefe(of):
    ts = time.time() + 3600
    mid = of.nueva_meta("m", despierta_ts=ts)
    jid = of.jefe_de_meta(mid)
    ts2 = time.time() + 7200
    assert of.despertar(mid, ts2)
    snap = of.snapshot()
    assert snap["tareas"][jid]["despierta_ts"] == pytest.approx(ts2)
    meta = next(m for m in snap["metas"] if m["id"] == mid)
    assert meta["despierta_ts"] == pytest.approx(ts2)


def test_despertar_ya_desde_el_jefe(of):
    mid = of.nueva_meta("m", despierta_ts=time.time() + 3600)
    jid = of.jefe_de_meta(mid)
    assert of.despertar(jid, None)   # despertar AHORA desde la tarea
    snap = of.snapshot()
    assert snap["tareas"][jid]["despierta_ts"] is None
    meta = next(m for m in snap["metas"] if m["id"] == mid)
    assert "despierta_ts" not in meta
    assert of.meta_pendiente() is not None  # ya esta despierta


def test_despertar_pasado_equivale_a_ahora(of):
    tid = of.crear_tarea("trabajador", "t", "d", despierta_ts=time.time() + 3600)
    assert of.despertar(tid, time.time() - 10)
    assert of.snapshot()["tareas"][tid]["despierta_ts"] is None


def test_despertar_no_aplica_a_terminadas(of):
    tid = of.crear_tarea("trabajador", "t", "d")
    of.set_estado(tid, "hecha")
    assert not of.despertar(tid, time.time() + 60)


def test_motor_reusa_jefe_precreado(of):
    # jefe_de_meta devuelve el pre-creado; una vez en_curso ya no
    mid = of.nueva_meta("m", despierta_ts=time.time() + 0.05)
    jid = of.jefe_de_meta(mid)
    assert jid is not None
    of.set_estado(jid, "en_curso")
    assert of.jefe_de_meta(mid) is None


def test_api_despertar_endpoint(of):
    # server real en puerto efimero: POST /api/tarea/despertar
    import json
    import threading
    import urllib.request
    from cognia.oficina.server import crear_server

    ts = time.time() + 3600
    mid = of.nueva_meta("m", despierta_ts=ts)
    srv = crear_server(of, puerto=0)
    puerto = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{puerto}/api/tarea/despertar",
            data=json.dumps({"id": mid, "despierta_ts": ts + 60}).encode(),
            method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert json.load(r)["ok"] is True
        # y crear meta programada via API
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{puerto}/api/meta",
            data=json.dumps({"texto": "prog", "despierta_ts": ts}).encode(),
            method="POST")
        with urllib.request.urlopen(req2, timeout=5) as r:
            assert json.load(r)["ok"] is True
        snap = of.snapshot()
        assert sum(1 for m in snap["metas"] if m.get("despierta_ts")) == 2
    finally:
        srv.shutdown()
