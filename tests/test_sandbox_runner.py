"""
test_sandbox_runner.py — Tests de regresion del sandbox de programas generados.

Contexto: antes de G0 (plan planes/AUTOPROGRAMACION_COGNIA.md) NO existia UN SOLO
test que tocara run_in_sandbox, pese a ser una frontera de contencion para codigo
generado por un LLM. Eso violaba las reglas 5 y 9 del CLAUDE.md del repo. Cada
test de aca corresponde a un bug o vector medido en esta maquina:

  - Los cuatro pilares (pathlib/dataclasses/unittest/tempfile) eran inimportables
    porque el guard de __import__ era global y atrapaba los imports internos de la
    stdlib. -> TestPilaresStdlib
  - RCE por getattr(os,'sys'+'tem') evadia el scan AST. -> TestEjecucionComandos
  - El cwd del sandbox era la raiz del repo; se podia sobrescribir el fuente.
    -> TestConfinamientoEscritura
  - Un timeout con >10 chars de stdout contaba como exito. -> TestExitoHonesto

Todos usan solo modulos benignos como carga; los ataques usan comandos inocuos
(echo) para no depender de efectos peligrosos reales.
"""

import os
import tempfile

import pytest

from cognia.program_creator.sandbox_runner import run_in_sandbox


class TestPilaresStdlib:
    """Los cuatro modulos que un programa complejo necesita, antes rotos."""

    @pytest.mark.parametrize("modulo", ["pathlib", "dataclasses", "unittest", "tempfile"])
    def test_pilar_importable(self, modulo):
        # Regresion dura: sin el fix del guard, cada uno moria por su cadena
        # transitiva (pathlib->urllib.parse, dataclasses/unittest->importlib.machinery,
        # tempfile->shutil) con ImportError '[sandbox] blocked'.
        r = run_in_sandbox(f"import {modulo}\nprint('OK')")
        assert r.success is True, f"{modulo} deberia importar: {r.execution_errors}"
        assert r.exit_code == 0
        assert "OK" in r.execution_output

    @pytest.mark.parametrize(
        "modulo",
        ["json", "sqlite3", "collections", "random", "re", "math", "typing",
         "argparse", "csv", "datetime", "itertools", "functools"],
    )
    def test_benigno_sigue_importable(self, modulo):
        r = run_in_sandbox(f"import {modulo}\nprint('OK')")
        assert r.success is True, f"{modulo}: {r.execution_errors}"

    def test_programa_con_los_cuatro_pilares(self):
        # El caso real: estado + archivos + tests + workspace en un solo programa.
        code = (
            "import sqlite3, unittest, tempfile\n"
            "from dataclasses import dataclass\n"
            "from pathlib import Path\n"
            "@dataclass\n"
            "class Item:\n"
            "    nombre: str\n"
            "class T(unittest.TestCase):\n"
            "    def test_db(self):\n"
            "        d = tempfile.mkdtemp()\n"
            "        con = sqlite3.connect(str(Path(d) / 'x.db'))\n"
            "        con.execute('CREATE TABLE t (n TEXT)')\n"
            "        con.execute('INSERT INTO t VALUES (?)', (Item('a').nombre,))\n"
            "        self.assertEqual(con.execute('SELECT n FROM t').fetchone()[0], 'a')\n"
            "r = unittest.TextTestRunner().run(unittest.TestLoader().loadTestsFromTestCase(T))\n"
            "print('TESTS_OK' if r.wasSuccessful() else 'FALLO')\n"
        )
        r = run_in_sandbox(code)
        assert r.success is True, r.execution_errors
        assert "TESTS_OK" in r.execution_output


class TestModulosPeligrososBloqueados:
    """La contencion de imports peligrosos debe seguir intacta tras el fix."""

    @pytest.mark.parametrize(
        "modulo",
        ["socket", "subprocess", "ctypes", "urllib", "importlib", "shutil",
         "pickle", "multiprocessing", "requests"],
    )
    def test_import_directo_bloqueado(self, modulo):
        r = run_in_sandbox(f"import {modulo}\nprint('OK')")
        assert r.success is False, f"{modulo} NO deberia importar"
        assert "OK" not in r.execution_output

    def test_import_dinamico_por_string_bloqueado(self):
        # Evasion clasica: partir el nombre para esquivar el scan AST. El guard de
        # runtime debe atraparlo aunque el AST no vea el literal.
        r = run_in_sandbox("m = __import__('sock' + 'et')\nprint(m)")
        assert r.success is False
        assert "OK" not in r.execution_output


class TestEjecucionComandos:
    """RCE: el scan AST solo veia el literal os.system; la indireccion lo evadia."""

    def test_os_system_directo_bloqueado(self):
        r = run_in_sandbox("import os\nos.system('echo PWNED')")
        assert r.success is False
        assert "PWNED" not in r.execution_output

    def test_os_system_por_getattr_bloqueado(self):
        # El bug estrella del mapeo: success=True, stdout='RCE_CONFIRMADO'.
        # Ahora la neutralizacion en runtime lo ataja aunque el AST no lo vea.
        r = run_in_sandbox("import os\ngetattr(os, 'sys' + 'tem')('echo PWNED')")
        assert "PWNED" not in r.execution_output, "RCE por getattr NO contenido"

    def test_os_popen_bloqueado(self):
        r = run_in_sandbox("import os\ngetattr(os, 'pop' + 'en')('echo PWNED').read()")
        assert "PWNED" not in r.execution_output


class TestConfinamientoEscritura:
    """El cwd era la raiz del repo; se podia sobrescribir el fuente de Cognia."""

    def test_escritura_absoluta_fuera_bloqueada(self, tmp_path):
        victima = tmp_path / "victima.txt"
        victima.write_text("ORIGINAL")
        code = f"open(r'{victima}', 'w').write('PWNED')\nprint('escrito')"
        r = run_in_sandbox(code)
        assert victima.read_text() == "ORIGINAL", "escritura fuera del workspace NO contenida"
        assert r.success is False

    def test_escritura_relativa_arriba_bloqueada(self):
        r = run_in_sandbox("open('../../../fuga_cognia.txt', 'w').write('PWNED')\nprint('x')")
        assert r.success is False
        # Y confirmar que no quedo el archivo por ninguna ruta plausible.
        assert not os.path.exists(os.path.join(os.getcwd(), "..", "fuga_cognia.txt"))

    def test_borrado_fuera_bloqueado(self, tmp_path):
        victima = tmp_path / "no_borrar.txt"
        victima.write_text("ORIGINAL")
        code = f"import os\nos.remove(r'{victima}')\nprint('borrado')"
        r = run_in_sandbox(code)
        assert victima.exists(), "os.remove fuera del workspace NO contenido"

    def test_escritura_dentro_del_workspace_si_funciona(self):
        # El confinamiento no debe romper el caso legitimo: un programa con estado
        # crea y lee su propio archivo de datos.
        code = (
            "with open('datos.txt', 'w') as f:\n"
            "    f.write('hola')\n"
            "with open('datos.txt') as f:\n"
            "    print('LEIDO:', f.read())\n"
        )
        r = run_in_sandbox(code)
        assert r.success is True, r.execution_errors
        assert "LEIDO: hola" in r.execution_output


class TestExitoHonesto:
    """Un timeout no puede contar como exito por tener algo en stdout."""

    def test_timeout_no_es_exito(self):
        # Antes: si habia >10 chars de stdout y hubo timeout, success=True. Un
        # programa que imprime un menu y se cuelga en input() pasaba como bueno.
        code = "print('menu largo que supera diez caracteres')\nwhile True:\n    pass\n"
        r = run_in_sandbox(code, timeout_sec=3)
        assert r.timed_out is True
        assert r.success is False, "un timeout NO debe contar como exito"

    def test_input_colgado_no_es_exito(self):
        # input() sin stdin: el sandbox pasa stdin=DEVNULL, asi que da EOFError y
        # sale != 0. Regresion contra los 9 EOFError heredados de la biblioteca.
        code = "print('bienvenido al programa interactivo')\nx = input('nombre: ')\nprint(x)"
        r = run_in_sandbox(code, timeout_sec=5)
        assert r.success is False


class TestMultiArchivo:
    """Prerrequisito de G3: proyectos de varios modulos que se importan entre si."""

    def test_imports_entre_modulos_propios(self):
        extra = {
            "modelo.py": "VALOR = 42\n",
            "paquete/__init__.py": "",
            "paquete/logica.py": "from modelo import VALOR\ndef doble():\n    return VALOR * 2\n",
        }
        principal = "from paquete.logica import doble\nprint('RESULTADO:', doble())\n"
        r = run_in_sandbox(principal, extra_files=extra)
        assert r.success is True, r.execution_errors
        assert "RESULTADO: 84" in r.execution_output

    def test_extra_file_no_puede_escapar_del_workspace(self):
        # Un path traversal en extra_files debe rechazarse al armar el workspace.
        r = run_in_sandbox("print('x')", extra_files={"../fuga.py": "PWNED = 1"})
        assert r.success is False
        assert r.exit_code == -4  # Sandbox error al armar el workspace


class TestEntradasDegeneradas:
    def test_codigo_vacio(self):
        assert run_in_sandbox("").success is False

    def test_syntax_error(self):
        r = run_in_sandbox("def roto(:\n    pass")
        assert r.success is False
        assert "SyntaxError" in r.execution_errors

    def test_traceback_conserva_numero_de_linea(self):
        # El guard va como modulo aparte justamente para esto: el error debe
        # apuntar a la linea real del usuario, no correrse por un prefijo. Lo
        # necesita el lazo de reparacion de G1.
        code = "a = 1\nb = 2\nraise ValueError('explota en la linea 3')\n"
        r = run_in_sandbox(code)
        assert r.success is False
        assert "line 3" in r.execution_errors or "explota en la linea 3" in r.execution_errors
