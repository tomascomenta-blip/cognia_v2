# -*- coding: utf-8 -*-
"""Tests de cognia/agent/traza_chatml.py — captura de trazas chatml (CPU puro).

POR QUE ESTOS TESTS: la traza es la MATERIA PRIMA del fine-tuning; un volcado
truncado o un valor de flag filtrado envenenan el dataset entero sin que nada
lo grite. Aca se fija el contrato: args crudos SIN truncar, best-effort total,
sufijos -cNN, sellado idempotente y SOLO NOMBRES de flags.
"""
import json
import os

import pytest

from cognia.agent import traza_chatml


ARGS_LARGOS = json.dumps({"path": "nota.txt",
                          "contenido": "x" * 800 + " | con pipe y\nlineas"})

MENSAJES = [
    {"role": "system", "content": "sos el agente"},
    {"role": "user", "content": "escribi un archivo nota.txt"},
    {"role": "assistant", "content": "",
     "reasoning_content": "pienso: uso escribir_archivo",
     "tool_calls": [{"type": "function", "id": "call_1",
                     "function": {"name": "escribir_archivo",
                                  "arguments": ARGS_LARGOS}}]},
    {"role": "tool", "tool_call_id": "call_1",
     "content": "RESULTADO escribir_archivo: OK"},
    {"role": "assistant", "content": "listo, escribi nota.txt"},
]
SCHEMAS = [{"type": "function",
            "function": {"name": "escribir_archivo", "parameters": {}}}]
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "max_tokens": 4096,
            "reasoning_effort": "", "url": "http://127.0.0.1:8080"}
PERFIL = {"nombre": "razonador_nativo", "modelo": "qwythos-q4.gguf",
          "n_ctx": 32768}
RESULTADO = {"texto": "listo", "pasos": 2, "ok": True,
             "tokens": 1830, "finish": "stop"}


@pytest.fixture
def dir_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_TRAZAS", "1")
    monkeypatch.setenv("COGNIA_TRAZAS_DIR", str(tmp_path / "trazas"))
    return tmp_path / "trazas"


def _volcar(task_id="20260809-120000-prueba", mensajes=MENSAJES):
    return traza_chatml.volcar(task_id, mensajes, SCHEMAS, SAMPLING,
                               PERFIL, RESULTADO)


def test_volcar_escribe_json_completo(dir_temporal):
    tid = _volcar()
    assert tid == "20260809-120000-prueba"
    datos = json.loads((dir_temporal / (tid + ".json"))
                       .read_text(encoding="utf-8"))
    assert datos["version"] == 1
    assert datos["task_id"] == tid
    assert datos["modelo"] == "qwythos-q4.gguf"
    assert datos["perfil"] == "razonador_nativo"
    assert datos["calidad"] is None
    assert datos["schemas"] == SCHEMAS
    # Los arguments van CRUDOS y SIN truncar (el bus emite [:120] — por eso
    # la traza sale de la lista viva y no de los eventos).
    tc = datos["mensajes"][2]["tool_calls"][0]
    assert tc["function"]["arguments"] == ARGS_LARGOS
    assert datos["mensajes"][2]["reasoning_content"].startswith("pienso")
    # sampling sin la url de la maquina
    assert "url" not in datos["sampling"]
    assert datos["sampling"]["temperature"] == 0.7


def test_flag_apagado_no_escribe(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIA_TRAZAS", raising=False)
    monkeypatch.setenv("COGNIA_TRAZAS_DIR", str(tmp_path / "trazas"))
    assert _volcar() == ""
    base = tmp_path / "trazas"
    assert not (base.exists() and list(base.glob("*.json")))


def test_sufijos_cnn_por_ciclo(dir_temporal):
    for _ in range(3):
        assert _volcar() == "20260809-120000-prueba"
    nombres = sorted(p.name for p in dir_temporal.glob("*.json"))
    assert nombres == ["20260809-120000-prueba-c02.json",
                       "20260809-120000-prueba-c03.json",
                       "20260809-120000-prueba.json"]


def test_task_id_vacio_usa_bitacora_activa(dir_temporal, monkeypatch):
    # El getter task_id_activo() lo agrega la ola 2: aca se mockea sobre el
    # modulo real (raising=False) — mismo id en traza y bitacora.jsonl.
    from cognia.agent import bitacora
    monkeypatch.setattr(bitacora, "task_id_activo",
                        lambda: "20260809-999999-horiz", raising=False)
    tid = _volcar(task_id="")
    assert tid == "20260809-999999-horiz"
    assert (dir_temporal / "20260809-999999-horiz.json").is_file()


def test_task_id_vacio_sin_bitacora_genera(dir_temporal, monkeypatch):
    from cognia.agent import bitacora
    # sin getter (ola 2 aun no corrio) y sin tarea activa: nuevo_task_id
    monkeypatch.delattr(bitacora, "task_id_activo", raising=False)
    tid = _volcar(task_id="")
    assert tid  # generado
    assert "escribi" in tid  # slug del primer mensaje user
    assert (dir_temporal / (tid + ".json")).is_file()


def test_bitacora_vacia_cae_a_nuevo_task_id(dir_temporal, monkeypatch):
    from cognia.agent import bitacora
    monkeypatch.setattr(bitacora, "task_id_activo", lambda: "",
                        raising=False)
    tid = _volcar(task_id="")
    assert tid and tid != ""
    assert "escribi" in tid


def test_best_effort_fallo_de_disco(dir_temporal, monkeypatch):
    # Un disco lleno JAMAS rompe el bucle del agente: volcar devuelve ''.
    monkeypatch.setattr(os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    assert _volcar() == ""


def test_volcar_tolera_mensajes_none(dir_temporal):
    tid = traza_chatml.volcar("20260809-130000-nulo", None, SCHEMAS,
                              SAMPLING, PERFIL, RESULTADO)
    assert tid == "20260809-130000-nulo"
    datos = json.loads((dir_temporal / (tid + ".json"))
                       .read_text(encoding="utf-8"))
    assert datos["mensajes"] == []


def test_atomico_sin_residuos_tmp(dir_temporal):
    _volcar()
    assert not list(dir_temporal.glob("*.tmp"))


def test_sellar_merge_idempotente(dir_temporal):
    tid = _volcar()
    _volcar()  # segundo ciclo -c02: sellar debe tocar los DOS
    assert traza_chatml.sellar(tid, {"verificar_ws": True}) is True
    assert traza_chatml.sellar(tid, {"banco": "banco_trazas"}) is True
    assert traza_chatml.sellar(tid, {"banco": "banco_trazas"}) is True  # idem
    for ruta in dir_temporal.glob(tid + "*.json"):
        calidad = json.loads(ruta.read_text(encoding="utf-8"))["calidad"]
        assert calidad == {"verificar_ws": True, "banco": "banco_trazas"}


def test_sellar_sin_archivos_devuelve_false(dir_temporal):
    assert traza_chatml.sellar("20990101-000000-nada", {"x": 1}) is False


def test_sellar_no_matchea_prefijos_ajenos(dir_temporal):
    # '20260809-1' no debe sellar '20260809-120000-prueba'
    _volcar()
    assert traza_chatml.sellar("20260809-1", {"x": 1}) is False


def test_solo_nombres_de_flags_jamas_valores(dir_temporal, monkeypatch):
    monkeypatch.setenv("COGNIA_SECRETO_TEST", "valor_secreto_123")
    tid = _volcar()
    crudo = (dir_temporal / (tid + ".json")).read_text(encoding="utf-8")
    datos = json.loads(crudo)
    assert "COGNIA_SECRETO_TEST" in datos["flags"]
    assert "valor_secreto_123" not in crudo
