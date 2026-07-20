"""
Regresion: el REPL reventaba con la entrada redirigida.

`prompt_toolkit` necesita una consola de verdad. Con `cognia < guion.txt`,
`cognia | tee log.txt` o un runner de CI, `PromptSession(...)` lanza
`NoConsoleScreenBufferError` y el usuario se lleva un traceback crudo de 20
lineas. Medido el 2026-07-20 al intentar guionizar el REPL para verificarlo:

    prompt_toolkit.output.win32.NoConsoleScreenBufferError:
    No Windows console found. Are you running cmd.exe?

La rama simple con `input()` ya existia para cuando la libreria FALTA; ahora
sirve tambien para cuando esta pero no hay consola. Con eso el REPL se puede
guionizar, que es como se verifica de verdad (regla 4 del repo: no basta
pytest, hay que arrancar el CLI).
"""

import inspect

import pytest

import cognia.cli as C


class TestElReplSobreviveSinConsola:

    def test_la_creacion_del_prompt_va_protegida(self):
        fuente = inspect.getsource(C.repl)
        i_try = fuente.find("try:")
        i_sess = fuente.find("session = PromptSession")
        assert i_try != -1 and i_sess != -1
        assert i_try < i_sess, "PromptSession debe crearse dentro de un try"

    def test_hay_camino_alternativo_con_input(self):
        fuente = inspect.getsource(C.repl)
        assert "session = None" in fuente
        assert 'input("cognia> ")' in fuente

    def test_avisa_de_que_pierde_el_autocompletado(self):
        """Degradar en silencio confunde: hay que decir que modo se uso."""
        fuente = inspect.getsource(C.repl)
        assert "Sin consola interactiva" in fuente
        assert "autocompletado" in fuente


class TestNoSeRompioElCaminoNormal:

    def test_sigue_usando_PromptSession_cuando_hay_consola(self):
        fuente = inspect.getsource(C.repl)
        assert "session.prompt(" in fuente, "el camino interactivo debe seguir"

    def test_la_continuacion_con_barra_sigue_existiendo(self):
        """Las lineas que acaban en \\ se siguen concatenando."""
        fuente = inspect.getsource(C.repl)
        assert 'line.endswith("\\\\")' in fuente
