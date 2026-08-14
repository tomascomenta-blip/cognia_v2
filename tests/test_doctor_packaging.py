"""
tests/test_doctor_packaging.py
==============================
Regression for bug #3: `/doctor` crashed on a pip-installed wheel because it
subprocessed scripts/cognia_doctor.py, which is not shipped in the package.

Fix: diagnostics live in the package module cognia/doctor.py (ships with the
wheel) and `/doctor` calls it in-process.
"""

from __future__ import annotations

import inspect


def test_doctor_module_importable_and_callable():
    from cognia.doctor import run_all, main, check_python
    assert callable(run_all) and callable(main)
    # A basic check must run without raising and return a bool.
    assert check_python() in (True, False)


def test_cli_doctor_uses_package_module_not_missing_script():
    from cognia import cli
    src = inspect.getsource(cli)
    # The brittle subprocess-to-scripts path must be gone...
    assert "cognia_doctor.py" not in src
    # ...and /doctor must run the packaged module in-process.
    assert "from cognia.doctor import" in src


def test_doctor_no_manda_a_scripts_que_no_viajan_en_el_wheel(monkeypatch, capsys):
    """Misma familia que el bug #3: sin backend, el doctor le decia al usuario
    `python scripts/servir_modelo.py`, y scripts/ NO va en el wheel — el
    usuario instalado por pip leia una orden imposible de ejecutar. Se prueba
    el MENSAJE que se imprime, no el texto del fuente (los comentarios pueden
    nombrar la ruta vieja para explicar el bug)."""
    from cognia import doctor, llm_local
    monkeypatch.setattr(llm_local, "detectar_backend", lambda **k: None)
    assert doctor.check_llm_backend() is False
    salida = capsys.readouterr().out
    assert "scripts/servir_modelo.py" not in salida
    assert doctor._ORDEN_ARRANCAR in salida
    assert doctor._ORDEN_ARRANCAR == "python -m cognia flota arrancar pensar"


def test_doctor_sin_root_por_cwd():
    """_ROOT = os.getcwd() era codigo muerto y una trampa: un "repo root"
    calculado desde el directorio donde el usuario ejecuto el comando."""
    from cognia import doctor
    assert not hasattr(doctor, "_ROOT")
