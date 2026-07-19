"""
test_os_sandbox.py — Regresion del ejecutor con contencion a nivel de SO
(Windows AppContainer). Solo Windows; se saltea en otros SO.

A diferencia de test_sandbox_runner.py (que prueba el guard in-process best-effort),
esto verifica la contencion DURA: que el kernel niega escritura fuera del workspace
y la red, sin depender de un guard de Python que el codigo pueda desarmar.

NOTA: correr esto crea (y borra) un perfil de AppContainer, y concede a ALL
APPLICATION PACKAGES lectura sobre el interprete base (setup unico, idempotente,
sin admin). Ambos son benignos y reversibles.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="AppContainer es solo de Windows")

from cognia.program_creator.os_sandbox import run_in_appcontainer, is_available

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_disponible_en_windows():
    assert is_available() is True


class TestEjecucionNormal:
    def test_programa_con_estado_y_stdlib(self):
        code = (
            "import json, sqlite3\n"
            "from dataclasses import dataclass\n"
            "from pathlib import Path\n"
            "@dataclass\n"
            "class N:\n"
            "    t: str\n"
            "con = sqlite3.connect(':memory:')\n"
            "con.execute('CREATE TABLE n (t TEXT)')\n"
            "con.execute('INSERT INTO n VALUES (?)', (N('hola').t,))\n"
            "Path('out.json').write_text(json.dumps([r[0] for r in con.execute('SELECT t FROM n')]))\n"
            "print('OK', Path('out.json').read_text())\n"
        )
        r = run_in_appcontainer(code, timeout_sec=30)
        assert r.success is True, r.execution_errors
        assert 'OK ["hola"]' in r.execution_output

    def test_escribe_en_su_workspace(self):
        r = run_in_appcontainer(
            "open('datos.txt','w').write('hola')\nprint('LEIDO', open('datos.txt').read())",
            timeout_sec=30)
        assert r.success is True, r.execution_errors
        assert "LEIDO hola" in r.execution_output


class TestContencionDura:
    """El kernel niega, no un guard de Python — por eso resiste a un adversario."""

    def test_no_puede_escribir_en_el_repo(self):
        objetivo = os.path.join(REPO_ROOT, "os_sandbox_test_fuga.txt")
        code = (
            f"try:\n"
            f"    open(r'{objetivo}','w').write('PWNED')\n"
            f"    print('FUGA')\n"
            f"except Exception as e:\n"
            f"    print('BLOCKED', type(e).__name__)\n"
        )
        r = run_in_appcontainer(code, timeout_sec=30)
        assert "FUGA" not in (r.execution_output or "")
        assert not os.path.exists(objetivo), "el AppContainer escribio en el repo"

    def test_no_puede_abrir_red(self):
        code = (
            "import socket\n"
            "try:\n"
            "    s = socket.socket(); s.settimeout(3); s.connect(('1.1.1.1', 53))\n"
            "    print('FUGA')\n"
            "except Exception as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        r = run_in_appcontainer(code, timeout_sec=30)
        assert "FUGA" not in (r.execution_output or "")

    def test_rce_no_ayuda_a_escapar(self):
        # Aunque el codigo logre correr lo que quiera (esto NO se bloquea a nivel
        # Python), el AppContainer sigue conteniendo el efecto: no puede escribir
        # fuera ni abrir red. Verificamos que un os.getcwd revela el workspace,
        # no la raiz del repo.
        r = run_in_appcontainer("import os; print('CWD', os.getcwd())", timeout_sec=30)
        assert r.success
        assert REPO_ROOT.lower() not in (r.execution_output or "").lower()


class TestMultiArchivo:
    def test_imports_entre_modulos_propios(self):
        extra = {
            "modelo.py": "VALOR = 21\n",
            "paq/__init__.py": "",
            "paq/logica.py": "from modelo import VALOR\ndef doble():\n    return VALOR * 2\n",
        }
        r = run_in_appcontainer(
            "from paq.logica import doble\nprint('MULTI', doble())\n",
            extra_files=extra, timeout_sec=30)
        assert r.success is True, r.execution_errors
        assert "MULTI 42" in r.execution_output

    def test_extra_file_no_escapa_del_workspace(self):
        with pytest.raises(Exception):
            run_in_appcontainer("print(1)", extra_files={"../fuga.py": "x=1"})


class TestEntornoSaneado:
    """El codigo generado no debe ver secretos que el proceso padre tenga cargados
    (cierra el Vector 3 del equipo rojo de G0-SO)."""

    def test_no_hereda_variables_sensibles(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-FAKE-secreto")
        monkeypatch.setenv("HF_TOKEN", "hf_FAKE-secreto")
        monkeypatch.setenv("MI_PASSPHRASE", "clave-secreta")
        code = (
            "import os\n"
            "print('KEY', os.environ.get('OPENAI_API_KEY'))\n"
            "print('TOKEN', os.environ.get('HF_TOKEN'))\n"
            "print('PASS', os.environ.get('MI_PASSPHRASE'))\n"
        )
        r = run_in_appcontainer(code, timeout_sec=30)
        assert r.success is True, r.execution_errors
        assert "KEY None" in r.execution_output
        assert "TOKEN None" in r.execution_output
        assert "PASS None" in r.execution_output

    def test_si_hereda_config_no_sensible(self, monkeypatch):
        # SYSTEMROOT es necesaria para que python arranque; no debe filtrarse.
        r = run_in_appcontainer(
            "import os; print('ROOT', bool(os.environ.get('SYSTEMROOT')))", timeout_sec=30)
        assert "ROOT True" in r.execution_output


class TestParaElLazoDeReparacion:
    """G1 depende de que el traceback tenga el numero de linea real del programa."""

    def test_traceback_conserva_numero_de_linea(self):
        r = run_in_appcontainer("a = 1\nb = 2\nraise ValueError('boom')\n", timeout_sec=30)
        assert r.success is False
        assert r.exit_code != 0
        assert "line 3" in (r.execution_errors or "")
        assert "boom" in (r.execution_errors or "")


class TestTimeout:
    def test_bucle_infinito_corta_por_timeout(self):
        r = run_in_appcontainer("while True:\n    pass\n", timeout_sec=3)
        assert r.timed_out is True
        assert r.success is False


class TestEntradasDegeneradas:
    def test_codigo_vacio(self):
        assert run_in_appcontainer("").success is False
