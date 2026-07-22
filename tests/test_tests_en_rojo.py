"""
G2 — la nota sale de los tests, no de heuristicas de stdout.

Hasta ahora "funciona" era `exit_code == 0 and stdout no vacio`. unittest NO
propaga el fallo al codigo de salida, asi que un programa con la suite en rojo
salia con exit=0 y se archivaba como bueno.

Medido el 2026-07-20 sobre un programa que genero Cognia: gestor de tareas de
101 lineas con 4 tests reales, imprimia

    UnboundLocalError: cannot access local variable 'tasks'
    Ran 4 tests in 0.001s
    FAILED (errors=1)

salia con exit=0 y se guardo con 6.7/10 y nota de programa que corre. Peor: el
lazo de reparacion (G1) ni se enteraba, porque para el el programa iba bien.
Con la deteccion, el mismo caso se repara o se descarta con 4.2.
"""

import pytest

from cognia.program_creator.sandbox_runner import detectar_tests_fallando

UNITTEST_ROJO = """\
UnboundLocalError: cannot access local variable 'tasks'

----------------------------------------------------------------------
Ran 4 tests in 0.001s

FAILED (errors=1)
"""

UNITTEST_VERDE = """\
----------------------------------------------------------------------
Ran 4 tests in 0.000s

OK
"""


class TestDetectaRojo:

    def test_unittest_con_errores(self):
        assert detectar_tests_fallando(UNITTEST_ROJO, "") == "FAILED (errors=1)"

    def test_unittest_con_fallos(self):
        salida = "Ran 2 tests in 0.001s\n\nFAILED (failures=2)"
        assert "FAILED (failures=2)" in detectar_tests_fallando(salida, "")

    def test_pytest_con_fallos(self):
        salida = "=== FAILURES ===\ntest_algo\n"
        assert detectar_tests_fallando(salida, "") is not None

    def test_tambien_mira_stderr(self):
        """unittest escribe su resumen en stderr, no en stdout."""
        assert detectar_tests_fallando("", UNITTEST_ROJO) is not None


class TestSuiteVaciaNoEsSuiteVerde:
    """
    Segundo agujero, medido el 2026-07-20: un compresor de 88 lineas declaraba
    tests, no ejecuto ninguno ("Ran 0 tests" / "NO TESTS RAN") y se guardo con
    7.8/10 porque salia con exit=0 y escribia en pantalla. Decir que traes
    tests y no traerlos es peor que no traerlos.
    """

    def test_ran_0_tests_dispara(self):
        salida = "Ran 0 tests in 0.000s\n\nNO TESTS RAN"
        assert detectar_tests_fallando(salida, "") is not None

    def test_no_tests_ran_dispara(self):
        assert detectar_tests_fallando("NO TESTS RAN", "") is not None

    def test_un_programa_sin_tests_no_se_castiga(self):
        """Estas firmas solo salen si unittest ARRANCA y no encuentra nada."""
        salida = "Calculando...\nResultado final: 42\nHecho."
        assert detectar_tests_fallando(salida, "") is None


class TestRechazoDuro:
    """
    Tercer agujero, medido el 2026-07-20: un mapa de proyecto con
    FAILED (failures=2) se archivo con 6.0/10. G2 lo marcaba como fallido,
    pero los bonus de "Rich output" y "substantial length" se concedian igual
    y, sumados a la creatividad, pasaban el umbral de 5.0. Salida abundante de
    un programa que revienta no es una virtud.
    """

    def _evaluar(self, salida_stderr, success=False):
        from cognia.program_creator.evaluator import evaluate_program
        from cognia.program_creator.generator import GeneratedProgram
        from cognia.program_creator.sandbox_runner import ExecutionResult

        prog = GeneratedProgram(
            title="Mapa De Proyecto Elaborado",
            description="Un programa largo, estructurado y muy creativo.",
            code="class A:\n" + "\n".join(f"    def m{i}(self): return {i}"
                                          for i in range(40)),
            category="demo")
        res = ExecutionResult(
            success=success, execution_output="x" * 900,
            execution_errors=salida_stderr, exit_code=0, timed_out=False,
            code_length=1200)
        return evaluate_program(prog, res)

    def test_tests_en_rojo_no_se_guarda_aunque_puntue(self):
        ev = self._evaluar("Tests en rojo: FAILED (failures=2)")
        assert ev.should_store is False
        assert any("Rechazo duro" in n for n in ev.notes)

    def test_sin_tests_en_rojo_decide_la_nota(self):
        """Sin tests rojos Y con ejecucion sana, decide la nota. (El helper
        simula success=False, que desde la campana 2026-07-21 tambien es
        rechazo duro — aqui se fuerza el caso sano.)"""
        ev = self._evaluar("", success=True)
        assert ev.should_store == (ev.total_score >= 5.0)

    def test_crash_no_se_guarda_aunque_puntue(self):
        """Compuerta de la campana 2026-07-21: un python que REVIENTA no entra
        a la biblioteca aunque el output previo al crash le sume nota (cazado:
        motor de regex guardado con IndexError en runtime)."""
        ev = self._evaluar("IndexError: string index out of range")
        assert ev.should_store is False
        assert any("ejecucion termino en error" in n for n in ev.notes)


class TestNoDaFalsosPositivos:
    """Castigar programas sanos es peor que dejar pasar alguno roto."""

    def test_suite_en_verde_no_dispara(self):
        assert detectar_tests_fallando(UNITTEST_VERDE, "") is None

    @pytest.mark.parametrize("salida", [
        "Procesados 10 items, 0 failed",
        "El experimento FAILED en la simulacion narrativa",
        "status: failure_rate=0.0",
        "",
    ])
    def test_texto_normal_no_dispara(self, salida):
        assert detectar_tests_fallando(salida, "") is None


class TestIntegracionConElSandbox:

    def test_tests_rojos_marcan_fallo_aunque_exit_sea_cero(self):
        """El caso exacto que se archivaba como bueno."""
        from cognia.program_creator.sandbox_runner import run_in_sandbox

        code = (
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_falla(self):\n"
            "        self.assertEqual(1, 2)\n"
            "print('el programa imprime algo')\n"
            "unittest.main(exit=False)\n"
        )
        r = run_in_sandbox(code)

        assert r.exit_code == 0, "unittest no propaga: por eso hacia falta G2"
        assert r.success is False, "una suite en rojo no puede contar como exito"
        assert "Tests en rojo" in r.execution_errors

    def test_programa_con_tests_verdes_sigue_pasando(self):
        from cognia.program_creator.sandbox_runner import run_in_sandbox

        code = (
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_pasa(self):\n"
            "        self.assertEqual(1, 1)\n"
            "print('resultado visible')\n"
            "unittest.main(exit=False)\n"
        )
        r = run_in_sandbox(code)

        assert r.success is True
        assert "Tests en rojo" not in (r.execution_errors or "")
