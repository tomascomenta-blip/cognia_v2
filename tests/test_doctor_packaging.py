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
