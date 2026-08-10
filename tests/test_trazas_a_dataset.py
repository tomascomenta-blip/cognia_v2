# -*- coding: utf-8 -*-
"""Tests de scripts/trazas_a_dataset.py — filtro/dedupe/reporte (CPU puro).

POR QUE: el filtro es la mitad del metodo — el sello de evidencia REAL separa
dataset de ruido (el 'status: completa' de estado.json marco completa una
tarea con analiza.py muerto por exit 9009). Y el dedupe por plantilla evita
que el eco del molde del banco domine el entrenamiento.
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    """scripts/ no es paquete: import por path, como el resto de la suite."""
    ruta = REPO_ROOT / "scripts" / "trazas_a_dataset.py"
    spec = importlib.util.spec_from_file_location("trazas_a_dataset", ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _traza(user="escribi nota.txt con hola", tools=None, calidad=None,
           finish="stop", ok=True, texto="listo", version=1,
           task_id="t-001", extra_msgs=None):
    tools = tools if tools is not None else [("escribir_archivo",
                                              '{"path":"nota.txt"}')]
    mensajes = [{"role": "system", "content": "agente"},
                {"role": "user", "content": user}]
    for i, (nombre, args) in enumerate(tools):
        mensajes.append({"role": "assistant", "content": "",
                         "reasoning_content": "pienso",
                         "tool_calls": [{"type": "function", "id": f"c{i}",
                                         "function": {"name": nombre,
                                                      "arguments": args}}]})
        mensajes.append({"role": "tool", "tool_call_id": f"c{i}",
                         "content": f"RESULTADO {nombre}: OK"})
    if extra_msgs:
        mensajes.extend(extra_msgs)
    mensajes.append({"role": "assistant", "content": texto})
    return {"version": version, "task_id": task_id, "ts": "2026-08-09T12:00:00",
            "modelo": "qwythos", "perfil": "razonador_nativo",
            "sampling": {"temperature": 0.7},
            "schemas": [{"type": "function",
                         "function": {"name": "escribir_archivo"}},
                        {"type": "function",
                         "function": {"name": "leer_archivo"}}],
            "mensajes": mensajes,
            "resultado": {"texto": texto, "pasos": len(tools) + 1, "ok": ok,
                          "tokens": 100, "finish": finish},
            "calidad": calidad}


SELLO = {"verificar_ws": True, "banco": "banco_trazas"}


def test_sello_rechaza_status_completa_sin_verificar(mod):
    # El caso real 202316: 'completa' con la postcondicion jamas mirada.
    ejemplos, rep = mod.construir_dataset(
        [_traza(calidad={"status": "completa"})])
    assert ejemplos == []
    assert rep["descartes"] == {"sin_sello": 1}


def test_sello_acepta_las_tres_evidencias(mod):
    trazas = [_traza(user="tarea uno con a", calidad={"verificar_ws": True}),
              _traza(user="tarea dos con b", calidad={"contrato_ok": True}),
              _traza(user="tarea tres con c", calidad={"gate": "e2e_ok"})]
    ejemplos, rep = mod.construir_dataset(trazas)
    assert len(ejemplos) == 3 and rep["descartes"] == {}


def test_incluir_sin_sello_solo_para_inspeccion(mod):
    ejemplos, _ = mod.construir_dataset([_traza(calidad=None)],
                                        exigir_sello=False)
    assert len(ejemplos) == 1


def test_finish_no_stop_y_no_ok_fuera(mod):
    trazas = [_traza(calidad=SELLO, finish="length"),
              _traza(user="otra tarea distinta z", calidad=SELLO, ok=False)]
    ejemplos, rep = mod.construir_dataset(trazas)
    assert ejemplos == []
    assert rep["descartes"] == {"finish_no_stop": 1, "resultado_no_ok": 1}


def test_estructura_version_y_tool_calls(mod):
    sin_tools = _traza(calidad=SELLO, tools=[])
    version_mala = _traza(user="otra cosa bien distinta", calidad=SELLO,
                          version=2)
    ejemplos, rep = mod.construir_dataset([sin_tools, version_mala])
    assert ejemplos == []
    assert rep["descartes"] == {"sin_tool_calls": 1, "version": 1}


def test_recuperacion_de_error_se_conserva(mod):
    # editar_archivo fallo -> escribir_archivo corrigio: la traza ENTRA si el
    # sello final esta OK (la autocorreccion es senal valiosa).
    t = _traza(calidad=SELLO,
               tools=[("editar_archivo", '{"path":"x"}'),
                      ("escribir_archivo", '{"path":"x","contenido":"y"}')])
    t["mensajes"][3]["content"] = "ERROR editar_archivo: bloque no encontrado"
    ejemplos, rep = mod.construir_dataset([t])
    assert len(ejemplos) == 1 and rep["descartes"] == {}


def test_dedupe_exacto(mod):
    ejemplos, rep = mod.construir_dataset(
        [_traza(calidad=SELLO), _traza(calidad=SELLO)])
    assert len(ejemplos) == 1
    assert rep["descartes"]["dup_exacto"] == 1


def test_dedupe_plantilla_con_tope(mod):
    # 7 corridas del mismo molde con solo digitos/rutas cambiados -> tope 5.
    trazas = [_traza(user=f"escribi el archivo c:/tmp/nota{i}.txt con {i}00",
                     tools=[("escribir_archivo", f'{{"path":"nota{i}.txt"}}')],
                     texto=f"listo {i}", calidad=SELLO)
              for i in range(7)]
    ejemplos, rep = mod.construir_dataset(trazas, max_por_plantilla=5)
    assert len(ejemplos) == 5
    assert rep["descartes"]["dup_plantilla"] == 2


def test_reporte_conteos_histograma_y_cobertura(mod):
    trazas = [_traza(calidad=SELLO),
              _traza(user="tarea distinta con letras", calidad=SELLO,
                     tools=[("escribir_archivo", '{"path":"b.txt"}'),
                            ("ejecutar", '{"comando":"dir"}')]),
              _traza(calidad={"status": "completa"},
                     user="rechazada sin sello")]
    ejemplos, rep = mod.construir_dataset(trazas)
    assert rep["trazas_leidas"] == 3
    assert rep["ejemplos"] == len(ejemplos) == 2
    assert rep["histograma_tools"]["escribir_archivo"] == 2
    assert rep["histograma_tools"]["ejecutar"] == 1
    # leer_archivo esta en los schemas pero jamas se llamo:
    assert "leer_archivo" in rep["tools_sin_cobertura"]
    assert rep["tokens_p50"] >= 1 and rep["tokens_p95"] >= rep["tokens_p50"]


def test_sin_reasoning_dropea(mod):
    ejemplos, _ = mod.construir_dataset([_traza(calidad=SELLO)],
                                        sin_reasoning=True)
    asistentes = [m for m in ejemplos[0]["messages"]
                  if m.get("role") == "assistant"]
    assert asistentes and all("reasoning_content" not in m
                              for m in asistentes)


def test_formato_ejemplo_sin_render(mod):
    # mensajes ESTRUCTURADOS + schemas + meta — el render lo hace el trainer
    # con el chat_template.jinja de la base (jamas ChatML a mano).
    ejemplos, _ = mod.construir_dataset([_traza(calidad=SELLO)])
    ej = ejemplos[0]
    assert set(ej) == {"messages", "tools", "meta"}
    assert ej["meta"]["task_id"] == "t-001"
    assert ej["meta"]["banco"] == "banco_trazas"
    tc = next(m for m in ej["messages"] if m.get("tool_calls"))
    assert isinstance(tc["tool_calls"][0]["function"]["arguments"], str)


def test_main_escribe_jsonl_y_reporte(mod, tmp_path):
    dir_trazas = tmp_path / "trazas"
    dir_trazas.mkdir()
    (dir_trazas / "t1.json").write_text(
        json.dumps(_traza(calidad=SELLO)), encoding="utf-8")
    (dir_trazas / "rota.json").write_text("{no es json", encoding="utf-8")
    out = tmp_path / "ds" / "dataset.jsonl"
    rep = tmp_path / "rep" / "reporte.json"
    rc = mod.main(["--dir", str(dir_trazas), "--out", str(out),
                   "--reporte", str(rep)])
    assert rc == 0
    lineas = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 1
    fila = json.loads(lineas[0])
    assert set(fila) == {"messages", "tools", "meta"}
    reporte = json.loads(rep.read_text(encoding="utf-8"))
    assert reporte["ejemplos"] == 1 and reporte["trazas_leidas"] == 1
