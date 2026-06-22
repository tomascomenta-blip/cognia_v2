"""Regresión F-SPEED (CYCLE 9): classify_turn() enruta social→fast / sustancia→deep,
y CascadeBackend.try_load() está OFF por defecto (no cambia el flujo normal del 3B)."""
from node.speech_cascade import classify_turn, CascadeBackend


def test_routing_social_fast():
    for t in ["Hola, ¿cómo estás?", "Gracias", "sí", "ok", "Buenas noches, hasta mañana"]:
        assert classify_turn(t) == "fast", t


def test_routing_sustantivo_deep():
    for t in ["¿Por qué el cielo es azul?", "Explícame la fotosíntesis",
              "Escribe una función en Python", "Cuéntame la historia de Roma en detalle"]:
        assert classify_turn(t) == "deep", t


def test_try_load_off_por_defecto(monkeypatch):
    monkeypatch.delenv("COGNIA_SPEECH_CASCADE", raising=False)
    assert CascadeBackend.try_load() is None


def test_fast_speech_backend_off_por_defecto(monkeypatch):
    import node.speech_cascade as sc
    monkeypatch.delenv("COGNIA_SPEECH_CASCADE", raising=False)
    sc._FAST_SINGLETON = None
    assert sc.fast_speech_backend() is None   # OFF por defecto → el chat usa el 3B normal


def test_prewarm_off_es_noop(monkeypatch):
    import node.speech_cascade as sc
    monkeypatch.delenv("COGNIA_SPEECH_CASCADE", raising=False)
    sc._FAST_SINGLETON = None
    sc.prewarm_fast_speech()          # OFF → no arranca nada ni crashea
    assert sc._FAST_SINGLETON is None


def test_try_load_con_flag_no_crashea(monkeypatch):
    # con flag ON devuelve instancia si los GGUF existen, o None si no — NUNCA crashea,
    # y NO arranca servers (son lazy en _backend, no en __init__/try_load).
    monkeypatch.setenv("COGNIA_SPEECH_CASCADE", "1")
    res = CascadeBackend.try_load()
    assert res is None or isinstance(res, CascadeBackend)
