# -*- coding: utf-8 -*-
"""Regresion: /crear, el researcher y las hipotesis usan el backend REAL.

Deuda tecnica cazada 2026-07-16: program_creator/generator.py y
research_engine/researcher.py generaban SOLO via Ollama con URL/modelo
hardcodeados — en la instalacion recomendada (cognia install-model, sin
Ollama) /crear y la investigacion de /dormir no podian funcionar nunca, y
el mensaje al usuario ocultaba la causa. Ahora el camino primario es el
backend real (inyectado por el caller u orquestador lazy) y Ollama es
fallback que respeta OLLAMA_URL. hypothesis.py ademas construia un
ShatteringOrchestrator NUEVO por hipotesis y aceptaba texto de modo
"simulation" como hipotesis real.
"""
import pytest

from cognia.program_creator import generator as gen
from cognia.program_creator.program_creator import _llm_de_cognia
from cognia.research_engine import researcher as res


_PROGRAMA_VALIDO = """Title: Contador demo
Description: Cuenta hasta tres.
Python Code:
```python
for i in range(1, 4):
    print("cuenta", i)
print("listo")
```"""

_RESPUESTA_RESEARCH = """ANSWER: El sol es una estrella de secuencia principal que fusiona hidrogeno.
KEY_CONCEPTS: sol, estrella, fusion
RELATIONS:
sol | es | estrella
CONFIDENCE: 0.7"""


def _prohibir_ollama(monkeypatch, modulo):
    def _boom(*a, **kw):
        raise AssertionError("no debe llamarse a Ollama cuando hay backend real")
    monkeypatch.setattr(modulo, "_call_ollama", _boom)


def test_generate_program_usa_llm_inyectado(monkeypatch):
    _prohibir_ollama(monkeypatch, gen)
    llamadas = []

    def llm(prompt, system, max_tokens, temperature):
        llamadas.append((system[:20], max_tokens))
        return _PROGRAMA_VALIDO

    p = gen.generate_program(forced_idea="contador demo", llm=llm)
    assert p is not None
    assert p.title == "Contador demo"
    assert "print" in p.code
    assert llamadas, "el llm inyectado no se uso"


def test_generate_program_sin_backend_devuelve_none(monkeypatch, capsys):
    monkeypatch.setattr(gen, "_call_ollama", lambda *a, **kw: None)
    p = gen.generate_program(forced_idea="contador demo", llm=None)
    assert p is None
    out = capsys.readouterr().out
    assert "install-model" in out  # causa honesta, no "umbral de calidad"


class _FakeInfer:
    def __init__(self, mode):
        self.text = "texto generado por el backend"
        self.mode = mode


class _FakeOrch:
    def __init__(self, mode="local"):
        self._mode = mode

    def infer(self, prompt, max_tokens=None, temperature=None):
        return _FakeInfer(self._mode)


class _FakeCognia:
    def __init__(self, mode="local"):
        self._orchestrator = _FakeOrch(mode)


def test_llm_de_cognia_usa_orquestador_real():
    llm = _llm_de_cognia(_FakeCognia(mode="local"))
    assert llm("hola", "sys", 100, 0.5) == "texto generado por el backend"


def test_llm_de_cognia_rechaza_simulation():
    """Texto de modo simulacion = placeholder; jamas alimenta la generacion."""
    llm = _llm_de_cognia(_FakeCognia(mode="simulation"))
    assert llm("hola", "sys", 100, 0.5) is None


def test_llm_de_cognia_sin_orquestador():
    assert _llm_de_cognia(object()) is None


def test_research_question_usa_llm_inyectado(monkeypatch):
    _prohibir_ollama(monkeypatch, res)
    monkeypatch.setattr(res, "_llm_local", lambda: None)

    r = res.research_question(
        {"id": 1, "question": "que es el sol?", "topic": "astronomia",
         "type": "uncertainty"},
        llm=lambda p, s, m, t: _RESPUESTA_RESEARCH)
    assert r is not None and r.success
    assert "estrella" in r.answer
    assert ("sol", "es", "estrella") in r.relations


def test_research_question_sin_backend_honesto(monkeypatch, capsys):
    monkeypatch.setattr(res, "_call_ollama", lambda *a, **kw: None)
    monkeypatch.setattr(res, "_llm_local", lambda: None)
    r = res.research_question(
        {"id": 1, "question": "que es el sol?", "type": "uncertainty"}, llm=None)
    assert r is None
    assert "install-model" in capsys.readouterr().out


def test_hypothesis_orquestador_cacheado(monkeypatch):
    """Antes: un ShatteringOrchestrator NUEVO por hipotesis."""
    import shattering.orchestrator as so
    from cognia.reasoning import hypothesis as hyp

    construcciones = []

    class _Contador:
        def __init__(self, *a, **kw):
            construcciones.append(1)

    monkeypatch.setattr(so, "ShatteringOrchestrator", _Contador)
    monkeypatch.setattr(hyp, "_ORCH", None)
    a = hyp._get_orch()
    b = hyp._get_orch()
    assert a is b
    assert len(construcciones) == 1
