"""
Regresion: `buscar` devolvia vacio en silencio y el agente concluia en falso.

Medido el 2026-07-20 con una tarea real ("que clases define cognia/mcp_libre.py").
El agente respondio **"No se encontraron resultados"** sobre un fichero que
define tres clases. Tres fallos encadenados, cada uno tapando al siguiente:

  1. La sintaxis documentada es `buscar <patron> | <directorio>`, pero el
     modelo escribe `buscar class cognia/mcp_libre.py`. La frase entera pasaba
     a ser el patron.
  2. El modelo entrecomilla: `buscar "class" | ruta`. Se buscaba el literal
     `"class"` — comillas incluidas — que no casa nunca.
  3. Y lo de fondo: acotar a un FICHERO no funcionaba jamas.
     `Path(fichero).rglob("*")` devuelve 0 elementos, y ese camino es el unico
     que hay porque `rg` no esta instalado en esta maquina, con lo que el
     subprocess de arriba siempre falla.

Un vacio silencioso que produce una conclusion falsa es peor que un error: el
agente no tiene forma de sospechar. Tras los tres arreglos responde bien:
"define las siguientes clases: ErrorMCP, Herramienta y ClienteMCP".
"""

import pytest

from cognia.agent.tools import run_tool

FICHERO = "cognia/mcp_libre.py"


def _buscar(args):
    return run_tool("buscar", args, {})


class TestFormasDeInvocar:
    """Las cuatro formas que el modelo escribe de verdad tienen que funcionar."""

    @pytest.mark.parametrize("args", [
        f'class {FICHERO}',            # espacio, como lo escribe el modelo
        f'class | {FICHERO}',          # la sintaxis documentada
        f'"class" | {FICHERO}',        # entrecomillado con dobles
        f"'class' | {FICHERO}",        # entrecomillado con simples
    ])
    def test_encuentra_las_clases(self, args):
        salida = _buscar(args)
        assert "mcp_libre" in salida, f"no encontro nada con: {args}"
        assert "sin coincidencias" not in salida


class TestAmbitoFichero:

    def test_un_fichero_es_un_ambito_valido(self):
        """rglob sobre un fichero da 0 elementos: por eso no funcionaba nunca."""
        salida = _buscar(f"ClienteMCP | {FICHERO}")
        assert "ClienteMCP" in salida

    def test_un_directorio_sigue_funcionando(self):
        salida = _buscar("ClienteMCP | cognia")
        assert "mcp_libre" in salida

    def test_sin_ambito_busca_en_todo(self):
        salida = _buscar("ClienteMCP")
        assert "sin coincidencias" not in salida


class TestElVacioExplicaDonde:
    """
    "sin resultados" a secas hacia que el agente concluyera cosas falsas sobre
    el codigo sin poder sospechar del ambito.
    """

    def test_dice_donde_busco(self):
        salida = _buscar(f"xyzzyqwerty | {FICHERO}")
        assert "sin coincidencias" in salida
        assert FICHERO in salida

    def test_recuerda_como_acotar(self):
        salida = _buscar("xyzzyqwerty | cognia")
        assert "buscar <patron> | <ruta>" in salida


class TestNoRompeLoQueYaIba:
    """
    Acotados a `cognia/disciplina` a proposito: lo que se comprueba aqui es el
    PARSEO, no la amplitud de la busqueda. Sin acotar tardaban 94 s y 66 s
    recorriendo el repo entero y alargaban la suite completa de 3 a 5 minutos.
    """

    AMBITO = "cognia/disciplina"

    def test_un_patron_con_espacios_sigue_valiendo(self):
        """Solo se separa la cola si es una ruta que EXISTE."""
        salida = _buscar(f"def motivo_corte | {self.AMBITO}")
        assert "sin coincidencias" not in salida

    def test_una_cola_que_no_es_ruta_no_se_separa(self):
        salida = _buscar(f"patron inventado_que_no_existe_xyz | {self.AMBITO}")
        # El patron llega entero: la cola no era una ruta, no se separo.
        assert "inventado_que_no_existe_xyz" in salida
