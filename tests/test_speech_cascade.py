"""Regresión F-SPEED (CYCLE 9) + PORTERO fase 2 (PREREG_PORTERO_FASE2):
classify_turn() enruta social→fast / sustancia→deep (e identidad→fast SOLO con
portero), CascadeBackend.try_load() está OFF por defecto, y fast_speech_backend()
prioriza el portero por presencia con fallback total al 3B."""
import pytest

from node.speech_cascade import classify_turn, portero_system, CascadeBackend


@pytest.fixture
def sin_portero(monkeypatch):
    """Aísla del portero REAL instalado en ~/.cognia de la máquina de dev:
    sin esto, cualquier test de fast_speech_backend/prewarm levantaría un
    llama-server de verdad durante pytest."""
    import node.speech_cascade as sc
    monkeypatch.setenv("COGNIA_PORTERO", "0")
    monkeypatch.delenv("COGNIA_SPEECH_CASCADE", raising=False)
    monkeypatch.setattr(sc, "_FAST_SINGLETON", None)
    monkeypatch.setattr(sc, "_FAST_FAILED", False)
    return sc


def test_routing_social_fast():
    for t in ["Hola, ¿cómo estás?", "Gracias", "sí", "ok", "Buenas noches, hasta mañana"]:
        assert classify_turn(t) == "fast", t


def test_routing_sustantivo_deep():
    for t in ["¿Por qué el cielo es azul?", "Explícame la fotosíntesis",
              "Escribe una función en Python", "Cuéntame la historia de Roma en detalle"]:
        assert classify_turn(t) == "deep", t


def test_cortos_sustantivos_no_van_a_fast():
    # Regresión: antes 'words<=4 → fast' mandaba estas cortas-pero-sustantivas al 0.5B
    # (poco fiable en hechos). Ahora SOLO social explícito va a fast → estas van al 3B.
    for t in ["Resume esto", "Capital de Francia?", "Cuentame algo", "Dame un dato",
              "Lista los pasos", "Quien gano"]:
        assert classify_turn(t) == "deep", t


def test_acks_sociales_van_a_fast():
    for t in ["De acuerdo", "Me alegro", "Qué bueno", "Buenísimo", "Buenas tardes"]:
        assert classify_turn(t) == "fast", t


def test_acks_debiles_solo_como_turno_completo():
    # FP dormido cazado en fase 2: \bno\b (y sí/ok/vale) matcheaba CUALQUIER
    # prompt que contuviera la palabra → un pedido sustantivo iba al 0.5B.
    for t in ["escribí un poema que no rime", "eso no me gusta, probá otra vez",
              "dale vale como variable al bucle", "el resultado es ok pero mejoralo"]:
        assert classify_turn(t) == "deep", t
    for t in ["no", "ok", "vale", "dale", "listo", "perfecto"]:
        assert classify_turn(t) == "fast", t


def test_identidad_solo_con_portero():
    # Sin portero: identidad va al 3B (el fleet la cubre con el experto accion).
    # Con portero (identidad=True): va al 0.5B+LoRA (G3 0→95 medido, ~4× vel).
    for t in ["¿quién sos?", "¿cómo te llamás?", "what's your name",
              "¿eres ChatGPT?", "presentate"]:
        assert classify_turn(t) == "deep", t
        assert classify_turn(t, identidad=True) == "fast", t


def test_identidad_va_antes_de_los_vetos():
    # identidades largas o con señales tipo-deep NO deben caer en los vetos
    t = "¿con qué modelo de inteligencia artificial estoy hablando en este momento?"
    assert classify_turn(t, identidad=True) == "fast"
    # ...pero un deep genuino sigue siendo deep aunque identidad esté ON
    assert classify_turn("¿qué es la fotosíntesis?", identidad=True) == "deep"


def test_portero_system_por_idioma():
    assert portero_system("¿quién sos?") == "Eres un asistente útil."
    assert portero_system("who are you") == "You are a helpful assistant."
    assert portero_system("introduce yourself") == "You are a helpful assistant."


def test_try_load_off_por_defecto(monkeypatch):
    monkeypatch.delenv("COGNIA_SPEECH_CASCADE", raising=False)
    assert CascadeBackend.try_load() is None


def test_fast_speech_backend_off_por_defecto(sin_portero):
    sc = sin_portero
    assert sc.fast_speech_backend() is None   # OFF por defecto → el chat usa el 3B normal


def test_prewarm_off_es_noop(sin_portero):
    sc = sin_portero
    sc.prewarm_fast_speech()          # OFF → no arranca nada ni crashea
    assert sc._FAST_SINGLETON is None


def test_try_load_con_flag_no_crashea(monkeypatch):
    # con flag ON devuelve instancia si los GGUF existen, o None si no — NUNCA crashea,
    # y NO arranca servers (son lazy en _backend, no en __init__/try_load).
    monkeypatch.setenv("COGNIA_SPEECH_CASCADE", "1")
    res = CascadeBackend.try_load()
    assert res is None or isinstance(res, CascadeBackend)


# ── portero: descubrimiento, kill-switch, arranque y falla cacheada ──────────

def _archivos_portero(tmp_path):
    g = tmp_path / "qwen05b.gguf"
    lo = tmp_path / "portero.gguf"
    g.write_bytes(b"x")
    lo.write_bytes(b"x")
    return g, lo


def test_portero_paths_por_env(tmp_path, monkeypatch, sin_portero):
    sc = sin_portero
    g, lo = _archivos_portero(tmp_path)
    monkeypatch.delenv("COGNIA_PORTERO", raising=False)
    monkeypatch.setenv("PORTERO_GGUF_PATH", str(g))
    monkeypatch.setenv("PORTERO_LORA_PATH", str(lo))
    assert sc._portero_paths() == (g, lo)
    assert sc.portero_activo() is True


def test_portero_kill_switch(tmp_path, monkeypatch, sin_portero):
    sc = sin_portero
    g, lo = _archivos_portero(tmp_path)
    monkeypatch.setenv("PORTERO_GGUF_PATH", str(g))
    monkeypatch.setenv("PORTERO_LORA_PATH", str(lo))
    monkeypatch.setenv("COGNIA_PORTERO", "0")
    assert sc._portero_paths() == (None, None)
    assert sc.portero_activo() is False


def test_portero_sin_lora_no_sirve_a_medias(tmp_path, monkeypatch, sin_portero):
    # base presente pero SIN LoRA → (None, None): la base pelada contestaría
    # como Qwen y rompería identidad silenciosamente.
    sc = sin_portero
    g = tmp_path / "qwen05b.gguf"
    g.write_bytes(b"x")
    monkeypatch.delenv("COGNIA_PORTERO", raising=False)
    monkeypatch.setenv("PORTERO_GGUF_PATH", str(g))
    monkeypatch.delenv("PORTERO_LORA_PATH", raising=False)
    assert sc._portero_paths() == (None, None)


def test_fast_backend_arranca_portero_con_lora_y_ctx(tmp_path, monkeypatch, sin_portero):
    sc = sin_portero
    g, lo = _archivos_portero(tmp_path)
    monkeypatch.delenv("COGNIA_PORTERO", raising=False)
    monkeypatch.setenv("PORTERO_GGUF_PATH", str(g))
    monkeypatch.setenv("PORTERO_LORA_PATH", str(lo))
    capturado = {}

    class _FakeBackend:
        def __init__(self, gguf, port=0, lora_path=None, ctx_size=None):
            capturado.update(gguf=gguf, port=port, lora_path=lora_path,
                             ctx_size=ctx_size)

    monkeypatch.setattr(sc, "_LlamaServerBackend", _FakeBackend)
    fb = sc.fast_speech_backend()
    assert isinstance(fb, _FakeBackend)
    assert capturado["gguf"] == g
    assert capturado["lora_path"] == lo
    assert capturado["ctx_size"] == 4096


def test_fast_backend_falla_cacheada_no_reintenta(tmp_path, monkeypatch, sin_portero):
    sc = sin_portero
    g, lo = _archivos_portero(tmp_path)
    monkeypatch.delenv("COGNIA_PORTERO", raising=False)
    monkeypatch.setenv("PORTERO_GGUF_PATH", str(g))
    monkeypatch.setenv("PORTERO_LORA_PATH", str(lo))
    intentos = {"n": 0}

    class _Explota:
        def __init__(self, *a, **kw):
            intentos["n"] += 1
            raise RuntimeError("no arranca")

    monkeypatch.setattr(sc, "_LlamaServerBackend", _Explota)
    assert sc.fast_speech_backend() is None
    assert sc.fast_speech_backend() is None    # 2da llamada: sin reintento
    assert intentos["n"] == 1
    assert sc.portero_activo() is False        # con falla, identidad vuelve al 3B
