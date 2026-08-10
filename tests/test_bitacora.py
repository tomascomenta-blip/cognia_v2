"""
Tests de la bitacora append-only por tarea (cognia/agent/bitacora.py).

La bitacora es un SINK del bus tipado (cognia/ux/events.py): los eventos del
turno aterrizan como lineas JSONL en <dir>/<task_id>/bitacora.jsonl y la
consulta es un grep del arnes (el modelo pregunta, jamas escribe).
"""

import json

import pytest

from cognia.agent import bitacora
from cognia.ux import events as ev


@pytest.fixture
def bit_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_TAREAS_DIR", str(tmp_path))
    yield tmp_path
    bitacora.cerrar()          # jamas dejar el sink suscrito entre tests


def _lineas(tmp, task_id):
    ruta = tmp / task_id / "bitacora.jsonl"
    return [json.loads(l) for l in
            ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_iniciar_escribe_config_y_devuelve_id(bit_tmp):
    tid = bitacora.iniciar("tarea de prueba", {"modelo": "qwythos",
                                               "budget": 8})
    lineas = _lineas(bit_tmp, tid)
    assert lineas[0]["tipo"] == "config_efectiva"
    assert lineas[0]["modelo"] == "qwythos"
    assert lineas[0]["task_id"] == tid


def test_eventos_del_bus_aterrizan(bit_tmp):
    tid = bitacora.iniciar("t", {})
    ev.emitir(ev.ToolInicio(tool="leer_archivo", args="a.py", paso=1))
    ev.emitir(ev.ToolFin(tool="leer_archivo", args="a.py", ok=True,
                         resumen="42 lineas", paso=1))
    lineas = _lineas(bit_tmp, tid)
    tipos = [l["tipo"] for l in lineas]
    assert "ToolInicio" in tipos and "ToolFin" in tipos
    assert all(l["task_id"] == tid for l in lineas)


def test_streaming_se_salta(bit_tmp):
    tid = bitacora.iniciar("t", {})
    ev.emitir(ev.TokenTexto(texto="hola"))
    ev.emitir(ev.RazonamientoTick(chars=100))
    tipos = [l["tipo"] for l in _lineas(bit_tmp, tid)]
    assert "TokenTexto" not in tipos and "RazonamientoTick" not in tipos


def test_cerrar_desuscribe(bit_tmp):
    tid = bitacora.iniciar("t", {})
    bitacora.cerrar()
    ev.emitir(ev.ToolFin(tool="tarde", ok=True))
    tipos = [l["tipo"] for l in _lineas(bit_tmp, tid)]
    assert "ToolFin" not in tipos
    bitacora.cerrar()          # idempotente: segunda vez no lanza


def test_anotar_linea_propia_y_noop_sin_activa(bit_tmp):
    bitacora.anotar({"tipo": "ciclo_fin"})     # sin bitacora activa: no-op
    tid = bitacora.iniciar("t", {})
    bitacora.anotar({"tipo": "ciclo_fin", "ciclo": 1, "contrato": "1/2",
                     "motivo_relevo": "stop_con_faltantes"})
    lineas = _lineas(bit_tmp, tid)
    fin = [l for l in lineas if l["tipo"] == "ciclo_fin"]
    assert fin and fin[0]["contrato"] == "1/2" and "ts" in fin[0]


def test_iniciar_dos_veces_cierra_la_anterior(bit_tmp):
    t1 = bitacora.iniciar("una", {})
    t2 = bitacora.iniciar("otra", {})
    ev.emitir(ev.ToolFin(tool="x", ok=True))
    assert all(l["tipo"] != "ToolFin" for l in _lineas(bit_tmp, t1))
    assert any(l["tipo"] == "ToolFin" for l in _lineas(bit_tmp, t2))


def test_buscar_formato_y_ultimas_n(bit_tmp):
    tid = bitacora.iniciar("t", {})
    for i in range(30):
        ev.emitir(ev.ToolFin(tool="ejecutar", args=f"cmd{i}", ok=(i % 2 == 0),
                             resumen=f"salida {i}", paso=i))
    out = bitacora.buscar("ejecutar", ultimas_n=5, task_id=tid)
    filas = out.splitlines()
    assert len(filas) == 5
    assert "salida 29" in filas[-1]
    assert filas[-1].startswith("paso 29 | ejecutar")
    # cmd1 fue impar -> ok=False -> la fila formateada dice ERROR
    assert "ERROR" in bitacora.buscar(r"cmd1\b", ultimas_n=1, task_id=tid)


def test_buscar_sin_coincidencias_y_sin_bitacora(bit_tmp):
    assert "sin bitacora" in bitacora.buscar("x", task_id="no-existe") or \
           "(sin" in bitacora.buscar("x", task_id="no-existe")
    tid = bitacora.iniciar("t", {})
    assert "sin coincidencias" in bitacora.buscar("zzzz_nada", task_id=tid)


def test_buscar_patron_invalido_no_lanza(bit_tmp):
    tid = bitacora.iniciar("t", {})
    assert "patron invalido" in bitacora.buscar("[malo", task_id=tid)


def test_payload_raro_no_rompe(bit_tmp):
    tid = bitacora.iniciar("t", {})
    bitacora.anotar({"tipo": "raro", "obj": {"anidado": [1, 2]}})
    ev.emitir(ev.Degradado(donde="x", motivo="y"))
    assert len(_lineas(bit_tmp, tid)) >= 3


def test_iniciar_poda_viejas(bit_tmp):
    from cognia.agent import estado_tarea as et
    for i in range(25):
        et.nuevo(f"20260808-{i:06d}-t", "t", [])
    bitacora.iniciar("nueva tarea", {})
    # 20 retenidas por podar_viejas + la nueva que acaba de abrir
    assert len(list(bit_tmp.iterdir())) <= 21
