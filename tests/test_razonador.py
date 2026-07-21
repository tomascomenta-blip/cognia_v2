"""
Razonador (razonamiento profundo /pensar): unidades sin modelo.

El E2E real (con los modelos thinking de verdad, GPU y CPU) vive en
scripts/e2e_razonamiento.py — 12 preguntas complejas con postcondicion.
Aqui se fija el contrato barato: separacion pensamiento/respuesta y la
eleccion de GGUF por perfil.
"""
import pytest

from cognia.razonador import separar_pensamiento, gguf_razonador


def test_separar_con_tags_completos():
    p, r = separar_pensamiento("<think>hmm, 2+2</think>La respuesta es 4.")
    assert p == "hmm, 2+2"
    assert r == "La respuesta es 4."


def test_separar_solo_cierre():
    """Qwen3-Thinking-2507 NO emite <think> de apertura, solo </think>."""
    p, r = separar_pensamiento("primero pienso...\nmucho\n</think>\nRespuesta: 42")
    assert "primero pienso" in p and "42" not in p
    assert r == "Respuesta: 42"


def test_separar_sin_pensamiento():
    p, r = separar_pensamiento("Respuesta directa.")
    assert p == "" and r == "Respuesta directa."


def test_gguf_por_perfil(monkeypatch, tmp_path):
    """GPU -> 4B thinking; CPU -> 1.7B; env COGNIA_RAZONADOR_GGUF manda."""
    import cognia.razonador as rz
    fake_gpu = tmp_path / "gpu.gguf"; fake_gpu.write_bytes(b"x")
    fake_cpu = tmp_path / "cpu.gguf"; fake_cpu.write_bytes(b"x")
    monkeypatch.setattr(rz, "_GPU_GGUF", fake_gpu)
    monkeypatch.setattr(rz, "_CPU_GGUF", fake_cpu)
    monkeypatch.delenv("COGNIA_RAZONADOR_GGUF", raising=False)
    monkeypatch.setenv("LLAMA_N_GPU_LAYERS", "99")
    assert gguf_razonador() == fake_gpu
    monkeypatch.setenv("LLAMA_N_GPU_LAYERS", "0")
    assert gguf_razonador() == fake_cpu
    # override explicito
    otro = tmp_path / "otro.gguf"; otro.write_bytes(b"x")
    monkeypatch.setenv("COGNIA_RAZONADOR_GGUF", str(otro))
    assert gguf_razonador() == otro
    # override roto -> error accionable, no silencio
    monkeypatch.setenv("COGNIA_RAZONADOR_GGUF", str(tmp_path / "no_existe.gguf"))
    with pytest.raises(FileNotFoundError):
        gguf_razonador()
