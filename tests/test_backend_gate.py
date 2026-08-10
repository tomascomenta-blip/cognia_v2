# -*- coding: utf-8 -*-
"""Tests de cognia/agent/_backend_gate.py y cognia/gpu_env.py (agente A3).

Sin GPU: el summoner es un modulo falso inyectado en sys.modules y
nvidia-smi se mockea via subprocess.run. POR QUE asi: la ola 1 corre en
paralelo (cognia/summoner.py puede no existir aun) y hay una medicion GPU
en curso - estos tests tienen que dar el mismo veredicto en una maquina
sin CUDA.
"""

import sys
import types

import pytest

import cognia
from cognia import gpu_env
from cognia.agent import _backend_gate


# ---------------------------------------------------------------- helpers

def _summoner_falso(monkeypatch, ensure_fn=None, liberar_fn=None):
    """Instala un cognia.summoner falso (sys.modules + atributo del paquete).

    POR QUE ambos: 'from cognia import summoner' resuelve primero por
    atributo del paquete y despues por sys.modules; parchear uno solo deja
    el test a merced del orden de imports de la suite."""
    mod = types.ModuleType("cognia.summoner")

    class SummonerError(RuntimeError):
        pass

    mod.SummonerError = SummonerError
    mod.ensure = ensure_fn or (lambda rol: {"ok": True, "url": "http://falso"})
    mod.liberar = liberar_fn or (lambda rol: True)
    monkeypatch.setitem(sys.modules, "cognia.summoner", mod)
    monkeypatch.setattr(cognia, "summoner", mod, raising=False)
    return mod


def _sin_summoner(monkeypatch):
    """Simula que cognia/summoner.py NO existe (ImportError garantizado):
    None en sys.modules hace que el import levante ImportError."""
    monkeypatch.setitem(sys.modules, "cognia.summoner", None)
    monkeypatch.delattr(cognia, "summoner", raising=False)


def _nvidia_smi(monkeypatch, *, free_mib=None, rc=0, exc=None, stdout=None):
    """Mockea subprocess.run para la consulta memory.free."""
    import subprocess

    def fake_run(cmd, **kw):
        assert cmd[0] == "nvidia-smi", f"comando inesperado: {cmd}"
        if exc is not None:
            raise exc
        out = stdout if stdout is not None else f"{free_mib}\n"
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="err")

    monkeypatch.setattr(subprocess, "run", fake_run)


@pytest.fixture(autouse=True)
def _env_limpio(monkeypatch):
    """Cada test parte sin flags heredados de la maquina."""
    monkeypatch.delenv("COGNIA_SUMMONER", raising=False)
    monkeypatch.delenv("COGNIA_GPU_PYTHON", raising=False)


# ------------------------------------------------- pedir_backend + summoner

def test_ensure_ok_devuelve_url(monkeypatch):
    _summoner_falso(monkeypatch,
                    ensure_fn=lambda rol: {"ok": True, "url": "http://127.0.0.1:8081"})
    ok, url, motivo = _backend_gate.pedir_backend("vlm", 3300)
    assert (ok, url, motivo) == (True, "http://127.0.0.1:8081", "")


def test_ensure_ok_sin_url_devuelve_vacio(monkeypatch):
    # Roles tipo presupuesto: ensure ok pero url=None -> url debe ser "".
    _summoner_falso(monkeypatch,
                    ensure_fn=lambda rol: {"ok": True, "url": None})
    ok, url, motivo = _backend_gate.pedir_backend("voces", 3000)
    assert (ok, url, motivo) == (True, "", "")


def test_summoner_error_se_traduce_a_motivo(monkeypatch):
    mod = _summoner_falso(monkeypatch)

    def ensure_explota(rol):
        raise mod.SummonerError("no cabe: VRAM 100 MiB libres")

    mod.ensure = ensure_explota
    ok, url, motivo = _backend_gate.pedir_backend("musica", 2500)
    assert ok is False and url == ""
    assert "no cabe" in motivo


def test_excepcion_ajena_del_summoner_se_propaga(monkeypatch):
    # Solo SummonerError se traduce; un bug (TypeError) debe VERSE.
    mod = _summoner_falso(monkeypatch)

    def ensure_bug(rol):
        raise TypeError("bug interno")

    mod.ensure = ensure_bug
    with pytest.raises(TypeError):
        _backend_gate.pedir_backend("musica", 2500)


def test_flag_cero_salta_al_fallback_sin_tocar_summoner(monkeypatch):
    def ensure_prohibido(rol):
        raise AssertionError("COGNIA_SUMMONER=0 no debe llamar ensure()")

    _summoner_falso(monkeypatch, ensure_fn=ensure_prohibido)
    monkeypatch.setenv("COGNIA_SUMMONER", "0")
    _nvidia_smi(monkeypatch, free_mib=8000)
    ok, url, motivo = _backend_gate.pedir_backend("musica", 2500)
    assert (ok, url, motivo) == (True, "", "")


# ------------------------------------------- fallback local (sin summoner)

def test_sin_summoner_rol_generico_vram_alcanza(monkeypatch):
    _sin_summoner(monkeypatch)
    _nvidia_smi(monkeypatch, free_mib=8000)
    ok, url, motivo = _backend_gate.pedir_backend("tresd", 4000)
    assert (ok, url, motivo) == (True, "", "")


def test_sin_summoner_rol_generico_vram_no_alcanza(monkeypatch):
    _sin_summoner(monkeypatch)
    _nvidia_smi(monkeypatch, free_mib=1000)
    ok, url, motivo = _backend_gate.pedir_backend("tresd", 4000)
    assert ok is False and url == ""
    assert "1000" in motivo and "4000" in motivo and "tresd" in motivo


def test_sin_summoner_sin_nvidia_smi_motivo_visible(monkeypatch):
    _sin_summoner(monkeypatch)
    _nvidia_smi(monkeypatch, exc=FileNotFoundError("no existe nvidia-smi"))
    ok, url, motivo = _backend_gate.pedir_backend("musica", 2500)
    assert ok is False and "nvidia-smi" in motivo


def test_sin_summoner_nvidia_smi_rc_distinto_de_cero(monkeypatch):
    _sin_summoner(monkeypatch)
    _nvidia_smi(monkeypatch, rc=6, stdout="")
    ok, url, motivo = _backend_gate.pedir_backend("musica", 2500)
    assert ok is False and "rc=6" in motivo


def test_sin_summoner_nvidia_smi_salida_ilegible(monkeypatch):
    # 'no pude medir' NO es 'no hay memoria': debe fallar con motivo, no
    # tratar la salida vacia como 0 MiB libres.
    _sin_summoner(monkeypatch)
    _nvidia_smi(monkeypatch, stdout="basura sin cifras")
    ok, url, motivo = _backend_gate.pedir_backend("musica", 2500)
    assert ok is False and "sin cifras" in motivo


def test_sin_summoner_vlm_usa_arbitro_visual_ok(monkeypatch):
    _sin_summoner(monkeypatch)
    from cognia.program_creator import arbitro_visual
    monkeypatch.setattr(arbitro_visual, "vlm_disponible",
                        lambda url=None: (True, "ok"))
    monkeypatch.setattr(arbitro_visual, "url_vlm",
                        lambda: "http://127.0.0.1:8081")
    ok, url, motivo = _backend_gate.pedir_backend("vlm", 3300)
    assert (ok, url, motivo) == (True, "http://127.0.0.1:8081", "")


def test_sin_summoner_vlm_caido_motivo_del_arbitro(monkeypatch):
    _sin_summoner(monkeypatch)
    from cognia.program_creator import arbitro_visual
    monkeypatch.setattr(arbitro_visual, "vlm_disponible",
                        lambda url=None: (False, "sin VLM en :8081"))
    ok, url, motivo = _backend_gate.pedir_backend("vlm", 3300)
    assert ok is False and url == "" and "sin VLM" in motivo


# ------------------------------------------------------------ soltar_backend

def test_soltar_sin_summoner_es_noop(monkeypatch):
    _sin_summoner(monkeypatch)
    assert _backend_gate.soltar_backend("vlm") is None   # no lanza


def test_soltar_llama_liberar(monkeypatch):
    llamadas = []
    _summoner_falso(monkeypatch, liberar_fn=lambda rol: llamadas.append(rol))
    _backend_gate.soltar_backend("musica")
    assert llamadas == ["musica"]


def test_soltar_con_liberar_roto_no_lanza_pero_grita(monkeypatch, capsys):
    def liberar_explota(rol):
        raise RuntimeError("pid fantasma")

    _summoner_falso(monkeypatch, liberar_fn=liberar_explota)
    _backend_gate.soltar_backend("tresd")     # no debe lanzar
    err = capsys.readouterr().err
    assert "soltar_backend" in err and "pid fantasma" in err


# ------------------------------------------------------------------ gpu_env

def test_gpu_python_default_apunta_a_venv312gpu():
    ruta = gpu_env.gpu_python()
    assert isinstance(ruta, str)
    assert ruta.replace("/", "\\").endswith(
        "venv312gpu\\Scripts\\python.exe")


def test_gpu_python_respeta_flag_existente(monkeypatch):
    # El flag es COGNIA_GPU_PYTHON (el de pulidor.py), NO COGNIA_GPU_PY.
    monkeypatch.setenv("COGNIA_GPU_PYTHON", r"C:\otro\python.exe")
    assert gpu_env.gpu_python() == r"C:\otro\python.exe"


def test_gpu_python_disponible_true_con_archivo_real(monkeypatch):
    monkeypatch.setenv("COGNIA_GPU_PYTHON", sys.executable)
    ok, motivo = gpu_env.gpu_python_disponible()
    assert ok is True and motivo == "ok"


def test_gpu_python_disponible_false_con_motivo(monkeypatch):
    monkeypatch.setenv("COGNIA_GPU_PYTHON", r"C:\no\existe\python.exe")
    ok, motivo = gpu_env.gpu_python_disponible()
    assert ok is False
    assert r"C:\no\existe\python.exe" in motivo
    assert "COGNIA_GPU_PYTHON" in motivo
