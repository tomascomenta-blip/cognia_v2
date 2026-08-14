# -*- coding: utf-8 -*-
"""La postcondicion de DISCO del gate obligatorio (scripts/e2e_happy_path.py).

POR QUE este fichero: el gate en si NO se puede correr desde pytest (levanta un
llama-server y tarda ~5 min; CLAUDE.md lo manda correr aparte antes de publicar).
Lo que si se puede fijar aqui es su LOGICA DE VERIFICACION, que es donde estaba
el agujero: hasta el 2026-08-14 la tarea 'python' se daba por buena con
`'350' in resp`, o sea leyendo la RESPUESTA del modelo. Un modelo que contesta
"la suma es 350" sin escribir ni ejecutar nada aprobaba el gate que se corre
justo antes de publicar a PyPI.

El primer test de abajo es la regresion: falla con el chequeo viejo (la
respuesta contiene "350") y pasa con el nuevo (no hay .py en el workspace).

Se importa el script por ruta porque scripts/ no es un paquete importable.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_RUTA = Path(__file__).resolve().parent.parent / "scripts" / "e2e_happy_path.py"


@pytest.fixture(scope="module")
def gate():
    """El modulo del gate, cargado por ruta. Importarlo NO arranca nada: todo
    el trabajo pesado vive dentro de main(), que solo corre bajo __main__."""
    spec = importlib.util.spec_from_file_location("_e2e_happy_path", _RUTA)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_happy_path"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_sin_ningun_py_no_aprueba(gate, tmp_path):
    """LA REGRESION. El modelo "contesto 350" pero el workspace esta vacio:
    el chequeo viejo (`'350' in resp`) aprobaba; el de disco tiene que fallar."""
    assert gate.ejecuta_algun_py(tmp_path, "350") is False


def test_py_que_imprime_el_valor_aprueba(gate, tmp_path):
    (tmp_path / "suma.py").write_text("print(100 + 250)\n", encoding="utf-8")
    assert gate.ejecuta_algun_py(tmp_path, "350") is True


def test_py_que_imprime_otra_cosa_no_aprueba(gate, tmp_path):
    """Existe el fichero y corre limpio, pero la cuenta esta mal."""
    (tmp_path / "suma.py").write_text("print(100 - 250)\n", encoding="utf-8")
    assert gate.ejecuta_algun_py(tmp_path, "350") is False


def test_py_con_el_valor_solo_en_un_comentario_no_aprueba(gate, tmp_path):
    """Que el numero este en el CODIGO no basta: el gate ejecuta, no lee.
    Sin esto bastaria un grep y volveriamos a verificar texto."""
    (tmp_path / "suma.py").write_text("# deberia imprimir 350\npass\n",
                                      encoding="utf-8")
    assert gate.ejecuta_algun_py(tmp_path, "350") is False


def test_py_que_peta_despues_de_imprimir_no_aprueba(gate, tmp_path):
    """Exit != 0 es fallo aunque el numero salga: un script que revienta no
    'funciona', y el enunciado pedia ejecutarlo."""
    (tmp_path / "suma.py").write_text("print(350)\nraise SystemExit(3)\n",
                                      encoding="utf-8")
    assert gate.ejecuta_algun_py(tmp_path, "350") is False


def test_lo_encuentra_en_un_subdirectorio(gate, tmp_path):
    """El agente puede dejarlo en una subcarpeta; rglob lo cubre."""
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "suma.py").write_text("print(350)\n", encoding="utf-8")
    assert gate.ejecuta_algun_py(tmp_path, "350") is True


def test_un_py_roto_no_tapa_al_bueno(gate, tmp_path):
    """Con varios ficheros basta que UNO cumpla: el roto no debe cortar el
    barrido (por eso el bucle sigue en vez de devolver False al primer fallo)."""
    (tmp_path / "aaa_roto.py").write_text("esto no es python(\n", encoding="utf-8")
    (tmp_path / "zzz_bueno.py").write_text("print(350)\n", encoding="utf-8")
    assert gate.ejecuta_algun_py(tmp_path, "350") is True


def test_input_colgado_no_bloquea_el_gate(gate, tmp_path):
    """stdin=DEVNULL: un `input()` colado por el modelo daria EOFError y falla,
    en vez de comerse la consola y colgar la corrida hasta el timeout."""
    (tmp_path / "pide.py").write_text("x = input()\nprint(350)\n", encoding="utf-8")
    assert gate.ejecuta_algun_py(tmp_path, "350") is False


def test_las_cinco_tareas_tienen_postcondicion_de_disco(gate):
    """Ninguna tarea puede volver a verificarse por la respuesta del modelo:
    el codigo que hacia esa excepcion ('if nombre == \"python\"') ya no existe."""
    fuente = _RUTA.read_text(encoding="utf-8")
    assert 'if nombre == "python"' not in fuente
    assert '"350" in resp' not in fuente
