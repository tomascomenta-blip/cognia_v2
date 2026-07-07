"""Tests de la oficina agéntica: estado, control externo y API del server."""
import json
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognia.oficina.estado import Oficina
from cognia.oficina.motor import _parse_numerada, _parse_roles
from cognia.oficina.server import crear_server


def _of(tmp_path):
    return Oficina(str(tmp_path / "estado.json"))


def test_meta_y_jerarquia(tmp_path):
    of = _of(tmp_path)
    mid = of.nueva_meta("armar un informe")
    assert of.meta_pendiente()["id"] == mid
    jefe = of.crear_tarea("jefe", "META", "armar un informe", meta=mid)
    d1 = of.crear_tarea("director", "D1", "parte 1", padre=jefe, meta=mid)
    t1 = of.crear_tarea("trabajador", "T1", "buscar datos", padre=d1,
                        rol="investigador", meta=mid)
    assert [h["id"] for h in of.hijos(jefe)] == [d1]
    assert of.hijos(d1)[0]["id"] == t1
    # persistencia real: releer desde disco
    of2 = Oficina(of.path)
    assert t1 in of2.data["tareas"]


def test_control_detener_pausar_editar(tmp_path):
    of = _of(tmp_path)
    t = of.crear_tarea("trabajador", "T", "hacer algo", rol="investigador")
    # pendiente + pausar -> pausada directa; editar permitido; reanudar -> pendiente
    assert of.solicitar(t, "pausar")
    assert of.snapshot()["tareas"][t]["estado"] == "pausada"
    assert of.editar(t, "hacer OTRA cosa")
    assert of.snapshot()["tareas"][t]["detalle"] == "hacer OTRA cosa"
    assert of.solicitar(t, "reanudar")
    assert of.snapshot()["tareas"][t]["estado"] == "pendiente"
    # en curso: la solicitud queda para que el motor la honre
    of.set_estado(t, "en_curso")
    assert of.solicitar(t, "detener")
    assert of.control(t) == "detener"
    of.consumir_solicitud(t)
    of.set_estado(t, "detenida")
    # tarea terminal: no se puede editar ni controlar
    assert not of.editar(t, "x")
    assert not of.solicitar(t, "pausar")


def test_eventos_acotados(tmp_path):
    of = _of(tmp_path)
    t = of.crear_tarea("trabajador", "T", "x", rol="investigador")
    for i in range(230):
        of.evento(t, f"paso {i}")
    evs = of.snapshot()["tareas"][t]["eventos"]
    assert len(evs) == 200 and evs[-1]["msg"] == "paso 229"


def test_parsers_de_planes():
    assert _parse_numerada("1. investigar el tema a fondo\n2) escribir el informe final") == \
        ["investigar el tema a fondo", "escribir el informe final"]
    roles = _parse_roles("implementador: crear script de conteo\n"
                         "investigador: buscar referencias del tema")
    assert roles[0] == ("implementador", "crear script de conteo")
    assert roles[1][0] == "investigador"
    # rol desconocido degrada a investigador (menor blast-radius)
    assert _parse_roles("hacker: romper todo")[0][0] == "investigador"


def test_server_api(tmp_path):
    of = _of(tmp_path)
    srv = crear_server(of, puerto=0)          # puerto libre del SO
    puerto = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{puerto}"
    try:
        # dashboard
        html = urllib.request.urlopen(base + "/").read().decode("utf-8")
        assert "Oficina Cognia" in html
        # nueva meta por API
        req = urllib.request.Request(base + "/api/meta",
                                     data=json.dumps({"texto": "meta via api"}).encode(),
                                     method="POST")
        r = json.loads(urllib.request.urlopen(req).read())
        assert r["ok"] and of.meta_pendiente()["texto"] == "meta via api"
        # estado refleja la meta
        est = json.loads(urllib.request.urlopen(base + "/api/estado").read())
        assert est["metas"][0]["texto"] == "meta via api"
        # control por API sobre una tarea
        t = of.crear_tarea("trabajador", "T", "x", rol="investigador")
        req = urllib.request.Request(base + "/api/tarea/accion",
                                     data=json.dumps({"id": t, "accion": "pausar"}).encode(),
                                     method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["ok"]
        assert of.snapshot()["tareas"][t]["estado"] == "pausada"
        req = urllib.request.Request(base + "/api/tarea/editar",
                                     data=json.dumps({"id": t, "detalle": "nuevo"}).encode(),
                                     method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["ok"]
        assert of.snapshot()["tareas"][t]["detalle"] == "nuevo"
    finally:
        srv.shutdown()
        srv.server_close()
