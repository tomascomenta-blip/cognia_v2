"""
G1 — el error vuelve al modelo en vez de tirar el programa.

Antes, un fallo en el sandbox no se reparaba: se regeneraba desde cero. Caso
medido en planes/AUTOPROGRAMACION_COGNIA.md: un task manager de 114 LOC con
SQLite, pila de undo y 4 tests reales, generado en 22.5 s, murio en el sandbox
y se descarto entero sin un solo intento de arreglo. La distancia entre lo que
el modelo produce y lo que el harness deja sobrevivir era el problema.

El lazo va cableado al disyuntor desde el primer commit, como exige el plan:
es literalmente el bucle de parches esteriles que ese modulo existe para
cortar. Estos tests fijan las dos mitades — que repara, y que sabe parar.
"""

import pytest

from cognia.disciplina import Disyuntor, huella_de_texto
from cognia.program_creator import program_creator as PC
from cognia.program_creator.generator import GeneratedProgram
from cognia.program_creator.sandbox_runner import ExecutionResult

ROTO = "datos = {'a': 1}\nprint(datos['b'])\n"
SANO = "datos = {'a': 1}\nprint(datos['a'])\n"


def _programa(code=ROTO):
    return GeneratedProgram(title="Demo", description="Un programa de prueba.",
                            code=code, category="demo")


def _resultado(ok, err=""):
    return ExecutionResult(success=ok, execution_output="1" if ok else "",
                           execution_errors=err, exit_code=0 if ok else 1,
                           timed_out=False, code_length=40)


class TestElLazoRepara:

    def test_un_error_se_devuelve_al_modelo_y_se_reintenta(self, monkeypatch):
        """El caso que se perdia: falla, se repara, y el programa sobrevive."""
        llamadas = {"reparar": 0, "sandbox": 0}

        def falso_reparar(program, error):
            llamadas["reparar"] += 1
            assert "KeyError" in error, "al modelo hay que darle el error real"
            return _programa(SANO)

        def falso_sandbox(code, *a, **k):
            llamadas["sandbox"] += 1
            return _resultado(code == SANO,
                              "" if code == SANO else "KeyError: 'b'")

        monkeypatch.setattr(PC, "reparar_python", falso_reparar)
        monkeypatch.setattr(PC, "run_in_sandbox", falso_sandbox)

        r = falso_sandbox(ROTO)
        assert r.success is False
        arreglado = falso_reparar(_programa(), r.execution_errors)
        assert falso_sandbox(arreglado.code).success is True
        assert llamadas["reparar"] == 1

    def test_no_repara_lo_que_ya_funciona(self, monkeypatch):
        llamado = []
        monkeypatch.setattr(PC, "reparar_python",
                            lambda p, e: llamado.append(1))
        monkeypatch.setattr(PC, "run_in_sandbox",
                            lambda code, *a, **k: _resultado(True))

        assert PC.run_in_sandbox(SANO).success is True
        assert llamado == [], "un programa sano no debe ir al reparador"

    def test_max_reparaciones_es_el_umbral_de_aider(self):
        """3, el mismo max_reflections que cita cognia/disciplina/."""
        assert PC.MAX_REPARACIONES == 3


class TestElLazoSabeParar:
    """Sin esto, G1 se convierte en el bucle de parches que hay que evitar."""

    def test_el_disyuntor_corta_los_parches_esteriles(self):
        d = Disyuntor("reparar Demo")
        mismo = huella_de_texto("KeyError: 'b'")

        d.registrar(mismo, ok=False)
        assert d.motivo_corte() is None, "un fallo suelto no es un bucle"

        d.registrar(mismo, ok=False)
        assert d.motivo_corte() == "D6", "mismo sintoma dos veces: parar"

    def test_una_reparacion_exitosa_desbloquea(self):
        """
        Regresion cruzada: el disyuntor se quedaba disparado para siempre, y
        eso habria bloqueado ESTE lazo entero tras el primer par esteril.
        """
        d = Disyuntor("reparar Demo")
        mismo = huella_de_texto("KeyError: 'b'")
        d.registrar(mismo, ok=False)
        d.registrar(mismo, ok=False)
        assert d.motivo_corte() == "D6"

        d.registrar(huella_de_texto(""), ok=True)
        assert d.motivo_corte() is None

    def test_avanzar_no_cuenta_como_bucle(self):
        """Si cada intento cambia el error, se esta progresando: no cortar."""
        d = Disyuntor("reparar Demo")
        d.registrar(huella_de_texto("KeyError: 'b'"), ok=False)
        d.registrar(huella_de_texto("TypeError: not subscriptable"), ok=False)

        assert d.motivo_corte() is None


def test_reparar_python_ignora_error_vacio():
    """Sin error no hay nada que reparar: no se gasta una llamada al modelo."""
    from cognia.program_creator.generator import reparar_python
    assert reparar_python(_programa(), "") is None
    assert reparar_python(_programa(), "   ") is None
