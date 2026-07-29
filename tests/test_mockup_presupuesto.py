"""imaginar_vision con un razonador: el presupuesto debe cubrir el PENSAMIENTO.

Regresion de 2026-07-28 (7o caso de presupuesto-tokens-razonamiento): con
max_tokens=400, gpt-oss gastaba los 400 integros pensando y el contenido
llegaba vacio -> la vision degradaba a idea cruda en toda corrida con el
fallback de Ollama neutralizado. El fix: presupuesto 2500 (margen 2-3x sobre
los ~150-300 utiles) + reasoning_effort='low' (el kwarg, no la prosa).
"""

import cognia.program_creator.mockup as mk


def test_imaginar_vision_presupuesto_y_effort(monkeypatch):
    capturado = {}

    def fake_generar(prompt, system="", temperature=0.4, max_tokens=600,
                     via="llm_local", timeout=None, reasoning_effort=None):
        capturado.update(max_tokens=max_tokens,
                         reasoning_effort=reasoning_effort)
        return "BRIEF: dos columnas claras\nIMAGEN: ui azul, limpia"

    monkeypatch.setattr(mk, "generar", fake_generar)
    v = mk.imaginar_vision("un contador simple")
    assert v["degradado"] is False
    assert v["brief"] == "dos columnas claras"
    assert capturado["max_tokens"] >= 2000, "400 no cubre el pensamiento"
    assert capturado["reasoning_effort"] == "low"


def test_backend_inyectado_recibe_presupuesto_amplio():
    visto = {}

    def llm(prompt, system, max_tokens, temperature):
        visto["max_tokens"] = max_tokens
        return "BRIEF: b\nIMAGEN: i"

    v = mk.imaginar_vision("otra idea", llm=llm)
    assert v["degradado"] is False
    assert visto["max_tokens"] >= 2000
