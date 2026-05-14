"""
run_tests.py — Script para correr los tests sin conflicto del __init__.py raíz.

Uso: python run_tests.py
"""
import os
import sys
import subprocess
import tempfile
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))

# Renombrar temporalmente __init__.py raíz para que pytest no lo vea
init_src = os.path.join(ROOT, "__init__.py")
init_tmp = os.path.join(ROOT, "__init__.py.bak_pytest")

renamed = False
try:
    if os.path.exists(init_src):
        shutil.move(init_src, init_tmp)
        renamed = True

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": f"{ROOT}{os.pathsep}{os.path.join(ROOT, 'cognia')}"},
    )
    sys.exit(result.returncode)
finally:
    if renamed and os.path.exists(init_tmp):
        shutil.move(init_tmp, init_src)
