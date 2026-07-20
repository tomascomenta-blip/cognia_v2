"""
tools/clean_install_test.py
===========================
Prueba de INSTALACION LIMPIA de cognia-ai en un venv nuevo y AISLADO, como lo
haria un usuario final. Verifica que el "un solo comando" de verdad deja un
`cognia` funcional, sin depender del repo ni del venv312 de desarrollo.

Fuentes soportadas:
  --wheel PATH   instala desde un .whl local (build recien hecho)
  --pypi         instala `cognia-ai` desde PyPI (lo publicado)
  --pypi-version X.Y.Z   idem, version fija
  --sdist PATH   instala desde un .tar.gz

Smoke checks (NO interactivos -> nunca cuelgan en el wizard de first-run):
  1. `python -c "import cognia"`                        (el paquete importa)
  2. el entry-point `cognia` existe en el venv (Scripts/bin)
  3. `cognia --help` o `cognia status` corre y no crashea (timeout corto)
  4. importa los modulos comerciales clave (agent.prompt_evolution, simple_mode)
  5. (si aplica) verifica que las tools de imagen esten disponibles

Uso (con el python de desarrollo, crea su propio venv aparte):
  venv312\\Scripts\\python.exe tools\\clean_install_test.py --wheel dist\\cognia_ai-X-py3-none-any.whl
  venv312\\Scripts\\python.exe tools\\clean_install_test.py --pypi
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _run(cmd, timeout=None, env=None):
    """(rc, stdout+stderr). Nunca lanza; captura timeout como rc=-9."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return -9, f"TIMEOUT tras {timeout}s\n{(e.stdout or '')}{(e.stderr or '')}"
    except Exception as e:  # noqa: BLE001
        return -1, f"EXC {type(e).__name__}: {e}"


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_script(venv_dir: Path, name: str) -> Path:
    d = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    exe = d / (name + (".exe" if os.name == "nt" else ""))
    return exe


def build_install_spec(args) -> str:
    if args.wheel:
        return str(Path(args.wheel).resolve())
    if args.sdist:
        return str(Path(args.sdist).resolve())
    if args.pypi_version:
        return f"cognia-ai=={args.pypi_version}"
    return "cognia-ai"


def main() -> int:
    # Windows: stdout es cp1252 y un print con texto no-ASCII del modelo/deps crashea
    # el harness entero (UnicodeEncodeError). Forzar utf-8 con replace.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Prueba de instalacion limpia de cognia-ai")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--wheel")
    g.add_argument("--sdist")
    g.add_argument("--pypi", action="store_true")
    ap.add_argument("--pypi-version", default=None)
    ap.add_argument("--keep", action="store_true", help="no borrar el venv temporal")
    args = ap.parse_args()
    # --pypi-version implica instalar desde PyPI (no hace falta pasar --pypi tambien)
    if args.pypi_version:
        args.pypi = True
    if not (args.wheel or args.sdist or args.pypi):
        ap.error("indica una fuente: --wheel / --sdist / --pypi / --pypi-version")

    spec = build_install_spec(args)
    results = {"spec": spec, "checks": [], "ok": False}

    def check(name, ok, detail=""):
        results["checks"].append({"name": name, "ok": bool(ok), "detail": detail[:400]})
        print(f"  [{'PASS' if ok else 'FALLA'}] {name}  {detail[:120]}", flush=True)
        return ok

    tmp = Path(tempfile.mkdtemp(prefix="cognia_cleaninstall_"))
    venv_dir = tmp / "venv"
    print(f"== venv limpio: {venv_dir} ==", flush=True)
    print(f"== instalando: {spec} ==", flush=True)

    # 1) crear venv aislado
    rc, out = _run([sys.executable, "-m", "venv", str(venv_dir)], timeout=180)
    if not check("crear venv", rc == 0, out):
        print(json.dumps(results)); return 1
    vpy = _venv_python(venv_dir)

    # 2) pip install (el "un solo comando"). Upgrade pip primero para wheels modernos.
    _run([str(vpy), "-m", "pip", "install", "-q", "--upgrade", "pip"], timeout=300)
    t0 = time.time()
    rc, out = _run([str(vpy), "-m", "pip", "install", spec], timeout=1800)
    inst_s = round(time.time() - t0, 1)
    if not check(f"pip install ({inst_s}s)", rc == 0, out[-400:]):
        print(json.dumps(results)); return 1

    # 3) el paquete importa
    rc, out = _run([str(vpy), "-c", "import cognia; print('cognia', getattr(cognia,'__version__','?'))"], timeout=120)
    check("import cognia", rc == 0, out)

    # 4) entry-point `cognia` existe
    cognia_exe = _venv_script(venv_dir, "cognia")
    check("entry-point cognia existe", cognia_exe.exists(), str(cognia_exe))

    # 5) `cognia --help`/status corre sin crashear (no interactivo, timeout corto).
    #    Env: marcar setup hecho para evitar el wizard interactivo si el CLI lo checa.
    env = dict(os.environ)
    env["COGNIA_SETUP_DONE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    rc, out = _run([str(cognia_exe), "status"], timeout=90, env=env) if cognia_exe.exists() else (-1, "sin entry-point")
    # status puede salir !=0 si no hay swarm; lo que importa es que NO crashee con traceback
    ok_status = ("Traceback" not in out) and rc != -9
    check("cognia status no crashea", ok_status, out[-200:])

    # 6) modulos comerciales clave importan
    for mod in ("cognia.agent.prompt_evolution", "cognia.simple_mode", "cognia.agent.tools"):
        rc, out = _run([str(vpy), "-c", f"import {mod}"], timeout=120)
        check(f"import {mod}", rc == 0, out[-150:])

    # 7) tools de imagen (creador de imagenes) disponibles Y funcionales: importar
    #    el modulo, cargar las tools, y renderizar un PNG real en el venv limpio.
    _img_probe = (
        "from cognia.lcd.tools_lcd import load_lcd_tools; "
        "from cognia.lcd.tools_modeling import load_modeling_tools; "
        "n=load_lcd_tools()+load_modeling_tools(); "
        "from cognia.agent.tools import run_tool; "
        "ctx={'ai':None,'working_memory':{},'print_fn':lambda *a,**k:None}; "
        "run_tool('escena_crear','una taza roja sobre una mesa azul',ctx); "
        "import tempfile,os; p=os.path.join(tempfile.mkdtemp(),'e2e.png'); "
        "run_tool('render_aprox',p,ctx); "
        "print('img_ok', n, os.path.exists(p), os.path.getsize(p) if os.path.exists(p) else 0)"
    )
    rc, out = _run([str(vpy), "-c", _img_probe], timeout=180)
    check("creador de imagenes empaquetado y funcional (render PNG)",
          "img_ok" in out and "True" in out, out[-200:])

    results["ok"] = all(c["ok"] for c in results["checks"])
    print(f"\n== RESULTADO: {'PASS' if results['ok'] else 'FALLA'} "
          f"({sum(c['ok'] for c in results['checks'])}/{len(results['checks'])} checks) ==")
    print("JSON " + json.dumps(results))

    if not args.keep:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if results["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
