"""
Compresion de salidas antes de gastarlas en contexto.

El llama-server local corre con n_ctx=8192, asi que cada traceback y cada
listado que se le manda al modelo compite por esa ventana. La idea sale de la
investigacion que hizo Cognia sola el 2026-07-20 (headroom, 60k estrellas) y el
algoritmo de colapsar repeticiones lo escribio ella misma en
generated_programs/text_compressor_01.

Lo que se le anadio al integrarlo, y es lo que fijan estos tests: conservar el
FINAL. El repo recortaba con `error[:600]`, que en un traceback se queda la
cabecera y tira la ultima linea — justo donde dice que fallo.
"""

import pytest

from cognia.compresion_salidas import (
    ahorro,
    comprimir,
    comprimir_error,
)

TRACEBACK = """\
Traceback (most recent call last):
  File "/tmp/workspace/program.py", line 12, in <module>
    total = sum(d["cuadrdo"] for d in datos)
  File "/tmp/workspace/program.py", line 12, in <genexpr>
    total = sum(d["cuadrdo"] for d in datos)
KeyError: 'cuadrdo'
"""


class TestColapsarRepeticiones:

    def test_lineas_repetidas_se_colapsan_con_contador(self):
        texto = "\n".join(["ERROR: fallo de red"] * 40)
        out = comprimir(texto)

        assert out.count("ERROR: fallo de red") == 1
        assert "(x40)" in out
        assert ahorro(texto, out) > 0.9

    def test_lineas_distintas_no_se_tocan(self):
        texto = "uno\ndos\ntres"
        assert comprimir(texto) == texto

    def test_solo_colapsa_consecutivas(self):
        """a b a no es una repeticion: son tres lineas distintas."""
        out = comprimir("a\nb\na")
        assert out == "a\nb\na"


class TestRecorteDelMedio:

    def test_texto_corto_pasa_entero(self):
        texto = "\n".join(f"linea {i}" for i in range(10))
        assert comprimir(texto, max_lineas=40) == texto

    def test_texto_largo_conserva_principio_y_final(self):
        texto = "\n".join(f"linea {i}" for i in range(200))
        out = comprimir(texto, max_lineas=20)

        assert "linea 0" in out, "falta el principio"
        assert "linea 199" in out, "falta el final, que es lo mas informativo"
        assert "recortadas" in out
        assert len(out.splitlines()) <= 21

    def test_guarda_mas_del_final_que_del_principio(self):
        """En logs y tracebacks la conclusion esta al final."""
        texto = "\n".join(f"linea {i}" for i in range(200))
        out = comprimir(texto, max_lineas=20).splitlines()

        marca = next(i for i, l in enumerate(out) if "recortadas" in l)
        assert len(out) - marca - 1 > marca


class TestComprimirError:
    """El caso que motivo el modulo."""

    def test_conserva_el_mensaje_de_la_excepcion(self):
        out = comprimir_error(TRACEBACK)
        assert "KeyError: 'cuadrdo'" in out, (
            "sin la ultima linea el modelo no sabe que arreglar")

    def test_recorte_bruto_pierde_lo_importante(self):
        """Documenta por que no vale con error[:600]."""
        largo = "Traceback (most recent call last):\n" + \
                "\n".join(f'  File "f{i}.py", line {i}' for i in range(200)) + \
                "\nKeyError: 'cuadrdo'\n"

        assert "KeyError" not in largo[:600], "asi se perdia el mensaje"
        assert "KeyError: 'cuadrdo'" in comprimir_error(largo)

    def test_respeta_el_limite_de_tamano(self):
        largo = "\n".join(f"linea distinta numero {i}" for i in range(500))
        out = comprimir_error(largo, max_chars=800)
        assert len(out) <= 1000     # margen por la marca y la cola

    def test_error_vacio_no_rompe(self):
        assert comprimir_error("") == ""
        assert comprimir("") == ""


def test_ahorro_se_calcula_bien():
    assert ahorro("a" * 100, "a" * 25) == pytest.approx(0.75)
    assert ahorro("", "") == 0.0


class TestEnElBucleDelAgente:
    """
    Donde de verdad hacia falta: cada paso del agente mete el resultado de la
    herramienta en `history`, y el prompt lleva los ultimos 6. Con n_ctx=8192
    eso son ~3000 tokens solo de historial, y un `leer_archivo` grande se lo
    come entero.
    """

    def _salidas_tipicas(self):
        return [
            "RESULTADO listar: " + "\n".join(f"fichero_{i}.py" for i in range(120)),
            "RESULTADO buscar: " + "\n".join(["coincidencia identica"] * 80),
            "RESULTADO leer_archivo: " + "\n".join(f"linea {i}" for i in range(200)),
        ]

    def test_recorta_el_historial_a_una_fraccion(self):
        salidas = self._salidas_tipicas()
        antes = "\n".join(salidas)
        despues = "\n".join(comprimir(s, max_lineas=25) for s in salidas)

        assert ahorro(antes, despues) > 0.7, "sin ahorro no sirve de nada"

    def test_cada_salida_conserva_su_final(self):
        """El veredicto de una herramienta esta al final, no al principio."""
        salidas = self._salidas_tipicas()
        despues = "\n".join(comprimir(s, max_lineas=25) for s in salidas)

        assert "linea 199" in despues
        assert "fichero_119.py" in despues

    def test_una_salida_corta_no_se_toca(self):
        """Comprimir lo que ya cabe solo anadiria ruido."""
        corta = "RESULTADO tests: 12 passed"
        assert comprimir(corta, max_lineas=25) == corta
