"""
Tests del estado durable por tarea (cognia/agent/estado_tarea.py).

Aislamiento: COGNIA_TAREAS_DIR apunta a tmp_path (override a call-time, mismo
patron que COGNIA_TASKS_FILE en tasks_board). Los acentos se verifican en
BYTES (leccion Latin-1 de la memoria del repo).
"""

import json

import pytest

from cognia.agent import estado_tarea as et
from cognia.agents.goal_contract import GoalContract


@pytest.fixture
def tareas_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_TAREAS_DIR", str(tmp_path))
    return tmp_path


def _criterios(*paths):
    return [{"kind": "file_exists", "path": str(p),
             "description": f"debe existir {p}"} for p in paths]


def test_nuevo_persiste_y_carga(tareas_tmp):
    est = et.nuevo("20260809-000000-t", "hacer algo", _criterios("a.py"))
    leido = et.cargar("20260809-000000-t")
    assert leido is not None
    assert leido["tarea"] == "hacer algo"
    assert leido["status"] == "en_curso"
    assert leido["faltan"] == ["debe existir a.py"]
    assert est["criterios"] == leido["criterios"]


def test_guardar_atomico_sin_tmp_residual(tareas_tmp):
    est = et.nuevo("20260809-000001-t", "x", [])
    et.guardar(est)
    carpeta = tareas_tmp / "20260809-000001-t"
    assert not list(carpeta.glob("*.tmp")), "quedo un .tmp residual"
    assert (carpeta / "estado.json").exists()


def test_guardar_acentos_en_bytes(tareas_tmp):
    est = et.nuevo("20260809-000002-t", "análisis con acentos: sí", [])
    crudo = (tareas_tmp / "20260809-000002-t" / "estado.json").read_bytes()
    # UTF-8 real, no mojibake: 'á' = 0xC3 0xA1, jamas 0xC3 0x83 (doble encode).
    assert "análisis".encode("utf-8") in crudo
    assert b"\xc3\x83" not in crudo


def test_cargar_corrupto_degrada_a_none(tareas_tmp):
    d = tareas_tmp / "20260809-000003-t"
    d.mkdir(parents=True)
    (d / "estado.json").write_text("{esto no es json", encoding="utf-8")
    assert et.cargar("20260809-000003-t") is None
    assert et.cargar("no-existe") is None


def test_registrar_ciclo_desde_contrato_real(tareas_tmp, tmp_path):
    objetivo = tmp_path / "obj.py"
    objetivo.write_text("x = 1\n", encoding="utf-8")
    faltante = tmp_path / "faltante.py"
    criterios = _criterios(objetivo, faltante)
    est = et.nuevo("20260809-000004-t", "t", criterios)
    st = GoalContract.from_spec("t", criterios).check()
    trace = [
        {"action": "escribir_archivo", "args": f"{objetivo} | x = 1",
         "ok": True, "result_head": "RESULTADO escribir_archivo: ok"},
        {"action": "ejecutar", "args": "python roto.py", "ok": False,
         "result_head": "RESULTADO ejecutar: ERROR (exit 1) boom"},
    ]
    nat = {"texto": "hice parte", "pasos": 5, "tokens": 100, "finish": "stop"}
    et.registrar_ciclo(est, 1, nat, st, trace, motivo_relevo="")
    assert [h["criterio"] for h in est["hitos"]] == [f"debe existir {objetivo}"]
    assert est["hitos"][0]["evidencia"].startswith("exists:")
    assert est["faltan"] == [f"debe existir {faltante}"]
    assert est["archivos_tocados"] == [str(objetivo)]
    assert "boom" in est["ultimo_error"]
    assert est["ciclos"][0]["finish"] == "stop"
    # y persistio de verdad
    assert et.cargar("20260809-000004-t")["ciclos"][0]["pasos"] == 5


def test_registrar_ciclo_sin_contrato(tareas_tmp):
    est = et.nuevo("20260809-000005-t", "t", [])
    et.registrar_ciclo(est, 1, {"texto": "", "pasos": 1, "tokens": 0,
                                "finish": "stop"}, None, [], "")
    assert est["hitos"] == [] and est["faltan"] == []
    assert len(est["ciclos"]) == 1


def test_resumen_para_prompt_respeta_tope(tareas_tmp):
    crits = [{"kind": "file_exists", "path": f"m{i}.py",
              "description": "criterio largo " + "x" * 120} for i in range(20)]
    est = et.nuevo("20260809-000006-t", "t", crits)
    est["hitos"] = [{"criterio": "h" * 150, "ok": True, "ciclo": 1,
                     "evidencia": "e"} for _ in range(10)]
    txt = et.resumen_para_prompt(est, [c["description"] for c in crits])
    assert len(txt) <= 1200
    assert txt.startswith("CONTINUACION")
    assert "SOLO FALTA" in txt
    # La instruccion GOBERNANTE sobrevive siempre (revision 2026-08-09: un
    # truncado plano por la cola la decapitaba).
    assert "respuesta final" in txt


def test_ultima_incompleta_cero_una_varias(tareas_tmp):
    assert et.ultima_incompleta() is None
    e1 = et.nuevo("20260809-000007-a", "vieja", [])
    et.cerrar(e1, "incompleta")
    e2 = et.nuevo("20260809-000008-b", "nueva", [])
    et.cerrar(e2, "incompleta")
    e3 = et.nuevo("20260809-000009-c", "completa", [])
    et.cerrar(e3, "completa")
    ult = et.ultima_incompleta()
    assert ult["task_id"] == "20260809-000008-b"     # la incompleta MAS nueva


def test_en_curso_reciente_no_es_retomable(tareas_tmp):
    et.nuevo("20260809-000020-t", "corriendo ahora", [])
    assert et.ultima_incompleta() is None


def test_en_curso_huerfana_es_retomable(tareas_tmp):
    # Crash del proceso: el estado queda 'en_curso' para siempre — ese es
    # justamente el caso del estado durable (revision 2026-08-09). Se
    # envejece el mtime del estado.json mas alla del umbral de huerfana.
    import os
    import time
    et.nuevo("20260809-000021-t", "crasheada", [])
    ruta = tareas_tmp / "20260809-000021-t" / "estado.json"
    viejo = time.time() - (et._HUERFANA_S + 60)
    os.utime(ruta, (viejo, viejo))
    ult = et.ultima_incompleta()
    assert ult and ult["task_id"] == "20260809-000021-t"


def test_retomada_es_veredicto_valido_y_no_retomable(tareas_tmp):
    est = et.nuevo("20260809-000022-t", "t", [])
    et.cerrar(est, "retomada")
    assert est["status"] == "retomada"
    assert et.ultima_incompleta() is None


def test_cerrar_veredicto_invalido_cae_a_abortada(tareas_tmp):
    est = et.nuevo("20260809-000010-t", "t", [])
    et.cerrar(est, "cualquiercosa")
    assert est["status"] == "abortada"
    assert est["ts_fin"]


def test_podar_viejas_retiene_las_mas_nuevas(tareas_tmp):
    for i in range(25):
        et.nuevo(f"20260809-{i:06d}-t", "t", [])
    et.podar_viejas(max_tareas=20)
    quedan = sorted(d.name for d in tareas_tmp.iterdir())
    assert len(quedan) == 20
    assert quedan[0] == "20260809-000005-t"          # las 5 mas viejas fuera


def test_podar_viejas_excluir_protege_la_activa(tareas_tmp):
    for i in range(25):
        et.nuevo(f"20260809-{i:06d}-t", "t", [])
    et.podar_viejas(max_tareas=20, excluir="20260809-000000-t")
    quedan = {d.name for d in tareas_tmp.iterdir()}
    assert "20260809-000000-t" in quedan             # la activa sobrevive


def test_nuevo_task_id_ordenable_y_con_slug():
    tid = et.nuevo_task_id("Crea el modulo X")
    assert len(tid.split("-", 2)) == 3
    assert tid.endswith("crea-el")   # slug (<=8 chars, sin guion colgante)
