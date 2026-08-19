"""
tests/test_doctor_avisos.py
===========================
Regresion del defecto de AGREGACION del doctor (2026-08-13).

El sintoma llevaba tres auditorias: `python -m cognia.doctor` imprimia cuatro
[WARN] (flota parcial, 83 eventos DEGRADADO en 24h, fleet30 sin GGUF, numba)
y cerraba con "Todo en orden. Cognia esta lista.". Las auditorias anteriores
pelearon el mensaje caso por caso subiendo checks concretos de _warn a _fail;
la causa era otra: `_warn` devuelve True y `run_all` solo contaba
`if not fn(): fails += 1`, o sea que era estructuralmente CIEGO a los avisos.

Aca se prueba la agregacion con checks de mentira (stubs de test, no mocks de
produccion) para que el test no dependa del backend vivo de la maquina.
"""

from __future__ import annotations

import os
import sys

import pytest

from cognia import doctor


# Los nombres tal como run_all los busca en el modulo. Si se agrega una
# seccion nueva y no se lista aca, el test la corre DE VERDAD y se nota.
_CHECKS = [
    "check_python", "check_instalacion", "check_packages", "check_gguf",
    "check_ollama", "check_llm_backend", "check_flota", "check_backend_audit",
    "check_sentinel", "check_fleet30", "check_env", "check_db",
    "check_shards", "check_inference_speed",
    # 2026-08-18: seccion nueva ("Capacidades degradadas"). Sin listarla aqui,
    # el test la corria de verdad y sumaba los degradados REALES de la maquina
    # a la cuenta de avisos -- justo lo que este comentario avisaba.
    "check_degradados",
]


def _neutralizar(monkeypatch, **overrides):
    """Deja todas las secciones en [OK] salvo las que se pasen por nombre."""
    for nombre in _CHECKS:
        monkeypatch.setattr(doctor, nombre, overrides.get(nombre, lambda: True))
    # run_all hace `from cognia.first_run import apply_config` en cada
    # llamada: se parchea en first_run para que el test no toque os.environ
    # real de la maquina.
    from cognia import first_run
    monkeypatch.setattr(first_run, "apply_config", lambda: None)


def test_warn_devuelve_true_y_registra_el_aviso():
    doctor._AVISOS.clear()
    assert doctor._warn("flota parcial", "el :8081 no responde") is True
    assert doctor._AVISOS == ["flota parcial"]
    doctor._AVISOS.clear()


def test_run_all_no_dice_todo_en_orden_con_avisos(monkeypatch, capsys):
    """EL BUG: cero [FAIL] + varios [WARN] cerraba en "Todo en orden"."""
    _neutralizar(
        monkeypatch,
        check_flota=lambda: doctor._warn("flota parcial (:8081 sin VLM)"),
        check_backend_audit=lambda: doctor._warn(
            "backend_audit: 33 evento(s) DEGRADADO en 24h"),
        check_fleet30=lambda: doctor._warn("fleet30: 1/6 miembros SIN GGUF"),
    )
    rc = doctor.run_all()
    salida = capsys.readouterr().out
    lineas = [l for l in salida.splitlines() if l.strip()]

    assert "Todo en orden" not in salida
    assert "Sin fallos, pero 3 aviso(s):" in salida
    # La ULTIMA linea util enumera avisos, que es lo que el usuario lee.
    assert lineas[-1].strip().startswith("- ")
    for titulo in ("flota parcial (:8081 sin VLM)",
                   "backend_audit: 33 evento(s) DEGRADADO en 24h",
                   "fleet30: 1/6 miembros SIN GGUF"):
        assert f"  - {titulo}" in salida
    # Un aviso no es un fallo: el exit code sigue siendo 0.
    assert rc == 0


def test_run_all_sin_avisos_si_dice_todo_en_orden(monkeypatch, capsys):
    _neutralizar(monkeypatch)
    rc = doctor.run_all()
    salida = capsys.readouterr().out
    assert "Todo en orden. Cognia esta lista." in salida
    assert "aviso(s)" not in salida
    assert rc == 0


def test_run_all_con_fallo_tambien_enumera_los_avisos(monkeypatch, capsys):
    _neutralizar(
        monkeypatch,
        check_llm_backend=lambda: doctor._fail("Backend LLM no disponible"),
        check_fleet30=lambda: doctor._warn("fleet30: 1/6 miembros SIN GGUF"),
    )
    rc = doctor.run_all()
    salida = capsys.readouterr().out
    assert "1 chequeo(s) con problemas" in salida
    assert "Ademas hay 1 aviso(s): fleet30: 1/6 miembros SIN GGUF" in salida
    assert rc == 1


def test_avisos_no_se_acumulan_entre_corridas(monkeypatch, capsys):
    """run_all se llama varias veces por proceso (/doctor del CLI, tests)."""
    _neutralizar(monkeypatch,
                 check_fleet30=lambda: doctor._warn("fleet30: 1/6 SIN GGUF"))
    doctor.run_all()
    capsys.readouterr()
    doctor.run_all()
    salida = capsys.readouterr().out
    assert "Sin fallos, pero 1 aviso(s):" in salida


# ── check_env: existir != estar bien ──────────────────────────────────────────

@pytest.fixture()
def _config_aislado(tmp_path, monkeypatch):
    """Apunta first_run a un ~/.cognia de mentira dentro de tmp_path."""
    from cognia import first_run
    cfg = tmp_path / "config.env"
    monkeypatch.setattr(first_run, "CONFIG_FILE", cfg)
    monkeypatch.setattr(first_run, "ENV_FILE_INSTALADOR", tmp_path / ".env")
    return cfg


def test_check_env_avisa_si_config_esta_vacia(_config_aislado, capsys):
    _config_aislado.write_text("", encoding="utf-8")
    doctor._AVISOS.clear()
    assert doctor.check_env() is True          # aviso, no fallo
    salida = capsys.readouterr().out
    assert "[WARN]" in salida and "config vacia" in salida
    assert doctor._AVISOS == ["config vacia"]


def test_check_env_avisa_si_un_gguf_del_config_no_existe(_config_aislado, capsys):
    """EL BUG: os.path.isfile(config.env) daba [OK] con el GGUF borrado."""
    _config_aislado.write_text(
        "LLAMA_GGUF_PATH=C:/no/existe/modelo.gguf\n"
        "COGNIA_LANG=espanol\n", encoding="utf-8")
    doctor._AVISOS.clear()
    assert doctor.check_env() is True
    salida = capsys.readouterr().out
    assert "[WARN]" in salida
    assert "NO existen" in salida
    assert "C:/no/existe/modelo.gguf" in salida


def test_check_env_ok_con_rutas_reales(_config_aislado, tmp_path, capsys):
    gguf = tmp_path / "modelo.gguf"
    gguf.write_bytes(b"gguf")
    _config_aislado.write_text(
        f"LLAMA_GGUF_PATH={gguf}\nCOGNIA_LANG=espanol\n", encoding="utf-8")
    doctor._AVISOS.clear()
    assert doctor.check_env() is True
    salida = capsys.readouterr().out
    assert "[OK]" in salida and "[WARN]" not in salida
    assert doctor._AVISOS == []


# ── check_instalacion ─────────────────────────────────────────────────────────

def test_check_instalacion_avisa_si_cognia_no_esta_en_path(monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda _n: None)
    doctor._AVISOS.clear()
    assert doctor.check_instalacion() is True   # avisos, nunca fallo
    salida = capsys.readouterr().out
    assert "comando 'cognia' no esta en PATH" in salida
    # La orden tiene que nombrar el Scripts/ de ESTE interprete, no una receta.
    scripts = os.path.join(sys.prefix, "Scripts" if os.name == "nt" else "bin")
    assert scripts in salida
    assert any("PATH" in a for a in doctor._AVISOS)


def test_check_instalacion_avisa_si_falta_setup_done(monkeypatch, tmp_path, capsys):
    from cognia import first_run
    monkeypatch.setattr(first_run, "FIRST_RUN_OK", tmp_path / ".setup_done")
    doctor._AVISOS.clear()
    doctor.check_instalacion()
    salida = capsys.readouterr().out
    assert "setup NO completado" in salida


def test_check_instalacion_ok_con_setup_done(monkeypatch, tmp_path, capsys):
    from cognia import first_run
    marca = tmp_path / ".setup_done"
    marca.touch()
    monkeypatch.setattr(first_run, "FIRST_RUN_OK", marca)
    doctor.check_instalacion()
    salida = capsys.readouterr().out
    assert "setup completado" in salida
