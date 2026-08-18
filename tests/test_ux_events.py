"""Tests del bus de eventos (cognia/ux/events.py) — el contrato de la obra
2026-08-09: emitir nunca lanza, los suscriptores reciben los dataclasses, y el
sink JSONL serializa cada evento como una linea JSON con su tipo."""
import json
import threading

import pytest

from cognia.ux import events


@pytest.fixture(autouse=True)
def _bus_limpio():
    """Cada test arranca sin suscriptores heredados (el bus es modulo-global)."""
    with events._lock:
        previos = list(events._suscriptores)
        events._suscriptores.clear()
    yield
    with events._lock:
        events._suscriptores.clear()
        events._suscriptores.extend(previos)


def test_emitir_reparte_a_suscriptores():
    vistos = []
    events.suscribir(vistos.append)
    ev = events.ToolInicio(tool="leer_archivo", args="motor.py", paso=1)
    events.emitir(ev)
    assert vistos == [ev]
    assert vistos[0].tool == "leer_archivo"


def test_suscriptor_roto_no_rompe_el_turno():
    vistos = []

    def roto(_):
        raise RuntimeError("adorno roto")

    events.suscribir(roto)
    events.suscribir(vistos.append)
    events.emitir(events.Aviso(texto="hola", origen="test"))
    assert len(vistos) == 1  # el segundo suscriptor recibio a pesar del roto


def test_desuscribir():
    vistos = []
    events.suscribir(vistos.append)
    events.desuscribir(vistos.append)
    events.emitir(events.TareaFin(ok=True, resumen="listo"))
    assert vistos == []


def test_a_dict_lleva_tipo_y_campos():
    d = events.a_dict(events.Degradado(
        donde="cli.agente", motivo="sin backend",
        accion_sugerida="servir_flota.py pensar"))
    assert d["tipo"] == "Degradado"
    assert d["donde"] == "cli.agente"
    assert d["ts"] > 0


def test_sink_jsonl_escribe_una_linea_por_evento(tmp_path, monkeypatch):
    ruta = tmp_path / "eventos.jsonl"
    monkeypatch.setattr(events, "_sink_jsonl", None)
    events.activar_sink_jsonl(str(ruta))
    events.emitir(events.TareaInicio(tarea="crea hola.txt", modo="agente",
                                     modelo="gpt-oss-20b"))
    events.emitir(events.TareaFin(ok=True, resumen="hecho", pasos=2))
    lineas = ruta.read_text(encoding="utf-8").strip().split("\n")
    assert len(lineas) == 2
    primero = json.loads(lineas[0])
    assert primero["tipo"] == "TareaInicio"
    assert primero["modelo"] == "gpt-oss-20b"


# ---------------------------------------------------------------------------
# Los eventos del motor de workflows (tanda UI 2026-08-17).
# ---------------------------------------------------------------------------

def test_los_eventos_nuevos_serializan_con_su_tipo():
    d = events.a_dict(events.WorkflowInicio(
        run_id="20260817-143012-repl", nombre="repl", total_agentes=6,
        presupuesto_tokens=60000, cache_precargada=2))
    assert d["tipo"] == "WorkflowInicio"
    assert (d["run_id"], d["nombre"], d["total_agentes"]) == (
        "20260817-143012-repl", "repl", 6)

    d = events.a_dict(events.AgenteInicio(
        run_id="r", agente_id="r#pasos.2", indice=2, total=6, fase="pasos",
        etiqueta="resume TLS", rol="worker", clave="ab12"))
    assert d["tipo"] == "AgenteInicio"
    assert d["agente_id"] == "r#pasos.2"

    d = events.a_dict(events.AgenteFin(
        run_id="r", agente_id="r#pasos.2", indice=2, total=6, fase="pasos",
        etiqueta="resume TLS", ok=True, tokens=812, intentos=1,
        duracion_s=4.1, url="http://127.0.0.1:8080", resumen="3 parrafos"))
    assert d["tipo"] == "AgenteFin"
    # la identidad se repite en el Fin: el remoto la lee SIN estado
    assert (d["indice"], d["total"], d["fase"], d["etiqueta"]) == (
        2, 6, "pasos", "resume TLS")
    assert d["cache_hit"] is False and d["motivo"] == ""

    d = events.a_dict(events.WorkflowFin(
        run_id="r", nombre="repl", ok=True, agentes=6, fallidos=1,
        cache_hits=2, tokens=4210, presupuesto_tokens=60000, duracion_s=31.2))
    assert d["tipo"] == "WorkflowFin"
    assert (d["agentes"], d["fallidos"], d["cache_hits"]) == (6, 1, 2)


def test_el_desglose_del_cierre_viaja_al_sink():
    """Los campos que distinguen "no arranco" de "arranco y fallo" tienen que
    llegar al remoto: van por el mismo a_dict() y con nombre propio, porque
    "0 de 4" no dice cual de las dos cosas paso."""
    d = events.a_dict(events.WorkflowFin(
        run_id="r", nombre="repl", ok=False, agentes=4, fallidos=4,
        total_agentes=4, arrancados=1, no_arrancados=3, colgando=1,
        resumen="3 de 4 agentes no llegaron a arrancar"))
    assert (d["total_agentes"], d["arrancados"]) == (4, 1)
    assert (d["no_arrancados"], d["colgando"]) == (3, 1)
    # y el JSON del sink no revienta con los campos nuevos
    assert json.loads(json.dumps(d))["colgando"] == 1


def test_el_evento_tardio_se_declara_en_el_contrato():
    """DEFECTO 3: un AgenteInicio/AgenteFin puede llegar DESPUES del
    WorkflowFin (huerfano de paralelo que sobrevivio al timeout). El campo
    existe en los dos y por defecto es False: un evento normal no se marca."""
    ini = events.AgenteInicio(run_id="r", agente_id="r#pasos.1@1")
    fin = events.AgenteFin(run_id="r", agente_id="r#pasos.1@1")
    assert ini.tardio is False and fin.tardio is False
    d = events.a_dict(events.AgenteFin(
        run_id="r", agente_id="r#pasos.1@1", tardio=True))
    assert d["tardio"] is True


def test_el_agente_id_se_sella_en_todos_los_eventos():
    vistos = []
    events.suscribir(vistos.append)
    tok = events.marcar_agente("r#pasos.2")
    try:
        assert events.agente_actual() == "r#pasos.2"
        events.emitir(events.TokenTexto(texto="hola"))
    finally:
        events.desmarcar_agente(tok)
    events.emitir(events.TokenTexto(texto="adios"))
    assert [e.agente_id for e in vistos] == ["r#pasos.2", ""]
    assert events.a_dict(vistos[0])["agente_id"] == "r#pasos.2"


def test_un_hilo_nuevo_no_hereda_el_agente_id():
    """La propiedad de aislamiento del ContextVar de la que depende el panel:
    un thunk de paralelo(cap=2) corre en un hilo NUEVO con contexto VACIO, asi
    que el id del hilo padre jamas se filtra al agente equivocado."""
    del_hijo = []
    tok = events.marcar_agente("padre")
    try:
        h = threading.Thread(
            target=lambda: del_hijo.append(events.TokenTexto(texto="x")))
        h.start()
        h.join()
    finally:
        events.desmarcar_agente(tok)
    assert del_hijo[0].agente_id == ""
