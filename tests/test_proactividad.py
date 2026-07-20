"""
El rol de proactividad: proponer lo no pedido, NUNCA ejecutarlo.

La regla de oro viene de un bug real del 2026-07-20: el pipeline entrego una
pagina HTML que nadie pidio, con confianza, por decidir el solo. Proponer sin
consentimiento debe quedar en sugerencia — por eso la API devuelve una lista
de textos y no toca nada.
"""

from unittest.mock import patch

from cognia.proactividad import proponer_extras


def _con_llm(respuesta):
    return (
        patch("cognia.proactividad.disponible", return_value=True),
        patch("cognia.proactividad.generar", return_value=respuesta),
    )


def _correr(respuesta_llm, **kw):
    d, g = _con_llm(respuesta_llm)
    with d, g:
        return proponer_extras("una tarea", "una respuesta", **kw)


def test_parsea_lineas_con_guion():
    extras = _correr("- anadir tests unitarios del caso vacio\n"
                     "- documentar el parametro timeout con un ejemplo")
    assert len(extras) == 2
    assert extras[0].startswith("anadir tests")


def test_parsea_lineas_numeradas():
    """El contrato pide '- ' pero el modelo a veces numera igual."""
    extras = _correr("1. anadir manejo de errores para entrada no valida\n"
                     "2. escribir un ejemplo de uso en el docstring")
    assert len(extras) == 2


def test_nada_significa_ninguna_propuesta():
    assert _correr("NADA") == []
    assert _correr("NADA.") == []
    assert _correr("nada") == []


def test_nada_dentro_de_una_propuesta_no_descarta_todo():
    """Regresion: `'NADA' in respuesta` descartaba todas las propuestas si la
    palabra aparecia en cualquier parte."""
    extras = _correr("- anadir un test para que no falte NADA importante")
    assert len(extras) == 1


def test_respeta_max_propuestas():
    extras = _correr("- primera propuesta concreta y valida\n"
                     "- segunda propuesta concreta y valida\n"
                     "- tercera propuesta concreta y valida\n"
                     "- cuarta propuesta concreta y valida",
                     max_propuestas=2)
    assert len(extras) == 2


def test_descarta_ruido_y_parrafadas():
    extras = _correr("- si\n- " + "x" * 300 + "\n- propuesta valida de longitud normal")
    assert extras == ["propuesta valida de longitud normal"]


def test_sin_llm_lista_vacia():
    with patch("cognia.proactividad.disponible", return_value=False):
        assert proponer_extras("t", "r") == []


def test_llm_caido_no_lanza():
    d, g = (patch("cognia.proactividad.disponible", return_value=True),
            patch("cognia.proactividad.generar", return_value=None))
    with d, g:
        assert proponer_extras("t", "r") == []


def test_llm_que_lanza_no_propaga():
    d, g = (patch("cognia.proactividad.disponible", return_value=True),
            patch("cognia.proactividad.generar", side_effect=OSError("boom")))
    with d, g:
        assert proponer_extras("t", "r") == []


def test_solo_propone_no_ejecuta():
    """La API es de solo lectura: devuelve textos, no toca ficheros ni corre
    nada. Este test fija la firma del contrato."""
    extras = _correr("- crear el fichero config.json con los defaults")
    assert all(isinstance(e, str) for e in extras)
