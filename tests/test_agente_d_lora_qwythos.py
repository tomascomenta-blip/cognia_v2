# -*- coding: utf-8 -*-
"""Tests CPU (sin GPU, sin red) del subsistema LoRA-Qwythos del agente D:
scripts/descargar_qwythos_hf.py, scripts/entrenar_lora_qwythos.py y
scripts/b4_lora_qwythos_e2e_ab.py.

POR QUE se testean las funciones PURAS: las corridas reales son [GPU-EXCL]
de la ola 3; lo que se puede verificar hoy sin GPU es el plan de descarga,
el masking por spans (el corazon del trainer: un masking corrido entrena
basura en silencio) y la lectura pre-registrada del gate F1 (la regla KILL
congelada debe estar cableada EXACTA al prereg, no en prosa).
"""
from __future__ import annotations

import importlib.util
import json
import struct
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = RAIZ / "scripts"


def _cargar(nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, SCRIPTS / (nombre + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dq = _cargar("descargar_qwythos_hf")
et = _cargar("entrenar_lora_qwythos")
ab = _cargar("b4_lora_qwythos_e2e_ab")


# ---------------------------------------------------------------------------
# descargar_qwythos_hf
# ---------------------------------------------------------------------------

def test_plan_para_idempotente():
    assert dq.plan_para(100, 100) == "saltar"       # completo -> no re-baja
    assert dq.plan_para(0, 100) == "bajar"
    assert dq.plan_para(40, 100) == "reanudar"      # parcial -> curl -C -
    assert dq.plan_para(150, 100) == "conflicto"    # jamas pisar en silencio
    # tamano remoto desconocido: se degrada visible, no se re-baja lo presente
    assert dq.plan_para(100, -1) == "saltar"
    assert dq.plan_para(0, -1) == "bajar"


def test_archivos_criticos_en_lista():
    # chat_template.jinja es la plantilla del masking y de --jinja: sin ella
    # el entrenamiento queda contra otro instrumento. model.safetensors es
    # el archivo gordo reanudable.
    assert "chat_template.jinja" in dq.ARCHIVOS
    assert "model.safetensors" in dq.ARCHIVOS
    assert "model.safetensors.index.json" in dq.ARCHIVOS
    assert dq.REPO == "huihui-ai/Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated"
    # NO se bajan los preprocessor de video/vision (diseno (c))
    assert not any("preprocessor" in a for a in dq.ARCHIVOS)


def test_incomplete_de(tmp_path):
    carpeta = tmp_path / ".cache" / "huggingface" / "download"
    carpeta.mkdir(parents=True)
    chico = carpeta / "aaa.incomplete"
    gordo = carpeta / "bbb.incomplete"
    chico.write_bytes(b"x" * 10)
    gordo.write_bytes(b"x" * 1000)
    assert dq.incomplete_de(tmp_path) == gordo      # el mas grande
    chico.unlink(); gordo.unlink()
    assert dq.incomplete_de(tmp_path) is None
    assert dq.incomplete_de(tmp_path / "no_existe") is None


def test_cabecera_safetensors(tmp_path):
    bueno = tmp_path / "ok.safetensors"
    header = json.dumps({"__metadata__": {}}).encode("utf-8")
    bueno.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00" * 8)
    ok, motivo = dq.cabecera_safetensors_ok(bueno)
    assert ok, motivo
    roto = tmp_path / "roto.safetensors"
    roto.write_bytes(b"\xff" * 32)                  # largo absurdo
    ok, motivo = dq.cabecera_safetensors_ok(roto)
    assert not ok and motivo


def test_creciendo_archivo_estatico(tmp_path):
    f = tmp_path / "quieto.bin"
    f.write_bytes(b"x" * 100)
    assert dq.creciendo(f, espera_s=0.05) is False
    assert dq.creciendo(tmp_path / "no_existe", espera_s=0.05) is False


# ---------------------------------------------------------------------------
# entrenar_lora_qwythos — tokenizer fake prefijo-consistente (sin descargas)
# ---------------------------------------------------------------------------

class TokFake:
    """apply_chat_template minimo: cada mensaje rinde [rol, contenido..., 9]
    y el generation prompt agrega el token de rol assistant (3). Es
    prefijo-consistente a proposito (como una plantilla append-only)."""
    chat_template = "plantilla-fake"
    _ROL = {"system": 1, "user": 2, "assistant": 3, "tool": 4}

    def apply_chat_template(self, msgs, tools=None, tokenize=True,
                            add_generation_prompt=False):
        ids = [100]
        if tools:
            ids += [90] * len(tools)
        for m in msgs:
            ids.append(self._ROL[m["role"]])
            ids += [200 + (ord(c) % 20) for c in str(m.get("content") or "")]
            for _ in (m.get("tool_calls") or []):
                ids += [77, 78]
            ids.append(9)
        if add_generation_prompt:
            ids.append(3)
        return ids


class TokInconsistente(TokFake):
    """Simula una plantilla que REESCRIBE turnos assistant viejos (poda de
    <think>): el render de un prefijo deja de ser prefijo del completo."""

    def apply_chat_template(self, msgs, tools=None, tokenize=True,
                            add_generation_prompt=False):
        podados = []
        for i, m in enumerate(msgs):
            if m["role"] == "assistant" and i < len(msgs) - 1:
                podados.append({**m, "content": ""})
            else:
                podados.append(m)
        return super().apply_chat_template(
            podados, tools=tools, tokenize=tokenize,
            add_generation_prompt=add_generation_prompt)


_CONVERSACION = [
    {"role": "system", "content": "sos cognia"},
    {"role": "user", "content": "crea nota.txt"},
    {"role": "assistant", "content": "uso la tool",
     "tool_calls": [{"id": "c1", "function": {"name": "escribir_archivo",
                                              "arguments": "{}"}}]},
    {"role": "tool", "content": "OK"},
    {"role": "assistant", "content": "listo"},
]
_TOOLS = [{"type": "function", "function": {"name": "escribir_archivo"}}]


def test_masking_por_spans():
    tok = TokFake()
    par, motivo = et.codificar_ejemplo(tok, _CONVERSACION, _TOOLS, 8192)
    assert par is not None, motivo
    ids, labels = par
    assert len(ids) == len(labels)
    # los spans entrenados son EXACTAMENTE los turnos assistant
    entrenados = [i for i, l in enumerate(labels) if l != -100]
    assert entrenados, "sin tokens entrenables"
    for i in entrenados:
        assert labels[i] == ids[i]
    # el render del prefijo hasta el primer assistant (con gen prompt)
    # queda TODO en -100: el modelo no se entrena a repetir el prompt
    pre = tok.apply_chat_template(_CONVERSACION[:2], tools=_TOOLS,
                                  add_generation_prompt=True)
    assert all(l == -100 for l in labels[:len(pre)])
    # los DOS turnos assistant aportan spans (tool_call y prosa final)
    post1 = tok.apply_chat_template(_CONVERSACION[:3], tools=_TOOLS)
    assert any(l != -100 for l in labels[len(pre):len(post1)])
    assert any(l != -100 for l in labels[len(post1):])
    # el turno tool (entre ambos) NO se entrena
    pre2 = tok.apply_chat_template(_CONVERSACION[:4], tools=_TOOLS,
                                   add_generation_prompt=True)
    assert all(l == -100 for l in labels[len(post1):len(pre2) - 1])


def test_descarte_por_largo():
    par, motivo = et.codificar_ejemplo(TokFake(), _CONVERSACION, _TOOLS, 10)
    assert par is None and motivo == "largo"


def test_descarte_plantilla_inconsistente():
    par, motivo = et.codificar_ejemplo(TokInconsistente(), _CONVERSACION,
                                       _TOOLS, 8192)
    assert par is None and motivo == "plantilla_inconsistente"


def test_descarte_sin_labels():
    solo_user = [{"role": "user", "content": "hola"}]
    par, motivo = et.codificar_ejemplo(TokFake(), solo_user, [], 8192)
    assert par is None and motivo == "sin_labels"


def test_codificar_dataset_cuenta_descartes():
    ejemplos = [
        {"messages": _CONVERSACION, "tools": _TOOLS},
        {"messages": [{"role": "user", "content": "x"}], "tools": []},
    ]
    codificados, descartes = et.codificar_dataset(TokFake(), ejemplos, 8192)
    assert len(codificados) == 1
    assert descartes["sin_labels"] == 1 and descartes["largo"] == 0


def test_cargar_dataset(tmp_path):
    ruta = tmp_path / "d.jsonl"
    lineas = [
        json.dumps({"messages": [{"role": "user", "content": "a"}], "tools": []}),
        "",                       # vacia: se ignora sin contar
        "esto no es json",        # rota: se cuenta
        json.dumps({"messages": []}),   # sin messages: rota
        json.dumps({"messages": [{"role": "user", "content": "b"}]}),
    ]
    ruta.write_text("\n".join(lineas), encoding="utf-8")
    ejemplos, rotas = et.cargar_dataset(ruta)
    assert len(ejemplos) == 2 and rotas == 2


def test_verificar_chat_template(tmp_path):
    class T:
        chat_template = None

    # sin plantilla y sin archivo -> NO se entrena (abort visible)
    ok, motivo = et.verificar_chat_template(T(), tmp_path)
    assert not ok and "chat_template" in motivo
    # con chat_template.jinja en el dir base -> se inyecta desde el archivo
    (tmp_path / "chat_template.jinja").write_text("{{ messages }}",
                                                  encoding="utf-8")
    t = T()
    ok, motivo = et.verificar_chat_template(t, tmp_path)
    assert ok and t.chat_template == "{{ messages }}"
    # ya presente en el tokenizer -> ok directo
    t2 = T(); t2.chat_template = "x"
    ok, _ = et.verificar_chat_template(t2, tmp_path)
    assert ok


def test_factor_lr_warmup_y_cosine():
    total = 100
    warmup = 10   # 10% de 100
    # sube durante el warmup y llega a 1.0 exacto al final del warmup
    assert et.factor_lr(0, total) < et.factor_lr(5, total) < 1.0
    assert abs(et.factor_lr(warmup - 1, total) - 1.0) < 1e-9
    # decae monotono despues del warmup y termina ~0
    valores = [et.factor_lr(p, total) for p in range(warmup, total + 1)]
    assert all(a >= b for a, b in zip(valores, valores[1:]))
    assert valores[-1] < 0.01


def test_indice_p95():
    largos = list(range(1, 101))          # 1..100
    assert largos[et.indice_p95(largos)] == 95
    assert et.indice_p95([7]) == 0


def test_targets_y_receta_congelados():
    # la regla dura del conversor b10066: SOLO atencion
    assert et.TARGETS == ["q_proj", "k_proj", "v_proj", "o_proj"]
    assert et.SEED == 20260809
    assert et.SMOKE_LIMITE_GIB == 15.0    # PASS de F-2 congelado en el prereg


# ---------------------------------------------------------------------------
# b4_lora_qwythos_e2e_ab — plan y lectura pre-registrada
# ---------------------------------------------------------------------------

def test_orden_pares_determinista_y_completo():
    a = ab.orden_pares(20260809, 6, 2)
    b = ab.orden_pares(20260809, 6, 2)
    assert a == b                                     # pre-sorteado, no vivo
    assert sum(1 for p in a if p["tipo"] == "AB") == 6
    assert sum(1 for p in a if p["tipo"] == "NULO") == 2
    for p in a:
        if p["tipo"] == "NULO":
            assert p["orden"] == ("OFF", "OFF")
        else:
            assert p["orden"] in (("ON", "OFF"), ("OFF", "ON"))
    assert [p["idx"] for p in a] == list(range(8))
    assert ab.orden_pares(1, 6, 2) != ab.orden_pares(2, 6, 2)


def test_orden_pares_intercala_ambos_ordenes():
    # a lo largo de semillas, ambos ordenes internos aparecen (el intercalado
    # existe de verdad, no es ON-primero siempre)
    ordenes = set()
    for semilla in range(1, 11):
        for p in ab.orden_pares(semilla, 6, 2):
            if p["tipo"] == "AB":
                ordenes.add(p["orden"])
    assert ordenes == {("ON", "OFF"), ("OFF", "ON")}


def test_primaria_pass():
    res = ab.evaluar_primaria([1, 2, 0, 1, 3, 2], [0, 1], 20)
    assert res["veredicto"] == "PASS"
    assert res["mediana"] >= 0 and res["suma"] > 0
    # el MDE se reporta SIEMPRE junto al resultado
    assert res["mde_tareas"] == 3 and res["mde_pp"] == 15.0


def test_primaria_nulo_sucio_se_lee_primero():
    # aunque la primaria fuera gloriosa, el nulo sucio anula la corrida
    res = ab.evaluar_primaria([5, 5, 5, 5, 5, 5], [2, 0], 20)
    assert res["veredicto"] == "INSTRUMENTO_SUCIO"
    assert "mediana" not in res            # la primaria NO se computa


def test_primaria_kill_por_mediana():
    res = ab.evaluar_primaria([-1, -2, -1, 0, -1, 0], [0, 0], 20)
    assert res["veredicto"] == "KILL"


def test_primaria_kill_por_par_hundido():
    # mediana positiva pero UN par con d <= -3: regresion concentrada
    res = ab.evaluar_primaria([2, 2, 2, 2, 2, -3], [0, 0], 20)
    assert res["veredicto"] == "KILL"


def test_primaria_no_determinado():
    res = ab.evaluar_primaria([0, 0, 0, 0, 0, 0], [0, 0], 20)
    assert res["veredicto"] == "NO_DETERMINADO"      # suma == 0: sin efecto
    res = ab.evaluar_primaria([2, 2, 2, 2, -1, -1], [0, 0], 20)
    assert res["veredicto"] == "NO_DETERMINADO"      # solo 4/6 no negativos


def test_primaria_5_de_6_alcanza():
    res = ab.evaluar_primaria([2, 2, 2, 2, 2, -1], [1, -1], 20)
    assert res["veredicto"] == "PASS"


def test_tareas_e2e_forma():
    tareas = ab.tareas_e2e()
    assert len(tareas) == 5
    for nombre, tarea, verificar, setup in tareas:
        assert isinstance(nombre, str) and isinstance(tarea, str)
        assert verificar is None or callable(verificar)
        assert setup is None or callable(setup)


def test_cargar_heldout_tolerante(tmp_path, monkeypatch):
    # sin banco_trazas.py: degrada con motivo visible, jamas revienta
    monkeypatch.setattr(ab, "RAIZ", tmp_path)
    tareas, motivo = ab.cargar_heldout(15, 20260809)
    assert tareas == [] and motivo
    # con un banco_trazas que expone tareas_heldout(): las devuelve
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "banco_trazas.py").write_text(
        "def tareas_heldout(n=15, semilla=0):\n"
        "    return [('t%d' % i, 'tarea %d' % i, None, None)"
        " for i in range(n)]\n", encoding="utf-8")
    tareas, motivo = ab.cargar_heldout(3, 20260809)
    assert len(tareas) == 3 and motivo == ""


def test_solo_plan_corre_sin_gpu():
    # el plan pre-sorteado se imprime y sale con exit 0 sin tocar red ni GPU
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "b4_lora_qwythos_e2e_ab.py"),
         "--solo-plan"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-500:]
    assert "plan pre-sorteado" in r.stdout
    assert r.stdout.count("NULO") == 2
