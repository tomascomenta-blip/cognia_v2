"""
tests/test_preview.py
=====================
Preview bat-style (cognia/console/preview.py): rich.Syntax desde el
archivo real, con numeros de linea, rango acotado y resaltado.

POR QUE Console(record=True): el renderable se verifica por su TEXTO
exportado (numeros de linea, contenido, recorte), sin tty — el mismo
truco que usa la suite para todo render rich.
"""

import pytest

pytest.importorskip("rich")

from rich.console import Console

from cognia.console.preview import contar_lineas, preview_archivo, preview_texto


def _exportar(renderable) -> str:
    con = Console(record=True, width=100, force_terminal=False)
    con.print(renderable)
    return con.export_text()


@pytest.fixture()
def archivo_py(tmp_path):
    ruta = tmp_path / "ejemplo.py"
    ruta.write_text(
        "def sumar(a, b):\n"
        "    # comentario\n"
        "    return a + b\n"
        "\n"
        "x = sumar(1, 2)\n",
        encoding="utf-8",
    )
    return str(ruta)


def test_archivo_python_da_renderable_con_numeros(archivo_py):
    rend = preview_archivo(archivo_py)
    assert rend is not None
    texto = _exportar(rend)
    assert "def sumar" in texto
    # numeros de linea: el gutter contiene el 1 y el 5
    assert "1" in texto and "5" in texto


def test_ruta_inexistente_devuelve_none_sin_lanzar(tmp_path):
    assert preview_archivo(str(tmp_path / "no_existe.py")) is None
    # un directorio tampoco es un archivo legible
    assert preview_archivo(str(tmp_path)) is None


def test_resaltado_de_lineas(archivo_py):
    rend = preview_archivo(archivo_py, resaltar=(3,))
    assert rend is not None
    # rich.Syntax guarda el set de lineas resaltadas; el estilo visual
    # (fondo) no sobrevive a export_text, el atributo si
    assert rend.highlight_lines == {3}
    assert "return a + b" in _exportar(rend)


def test_texto_directo(tmp_path):
    rend = preview_texto("def f():\n    return 42\n")
    assert rend is not None
    assert "return 42" in _exportar(rend)
    # lenguaje explicito distinto tambien renderiza
    rend_json = preview_texto('{"clave": 1}', lenguaje="json")
    assert rend_json is not None
    assert "clave" in _exportar(rend_json)


def test_archivo_enorme_queda_acotado(tmp_path):
    ruta = tmp_path / "enorme.py"
    ruta.write_text(
        "".join(f"linea_{i} = {i}\n" for i in range(1, 5001)),
        encoding="utf-8",
    )
    rend = preview_archivo(str(ruta), max_lineas=24)
    assert rend is not None
    texto = _exportar(rend)
    assert "linea_1 " in texto
    assert "linea_5000" not in texto
    # el render pinta ~24 lineas, no 5000
    assert len(texto.splitlines()) < 30


def test_ventana_desde(tmp_path):
    ruta = tmp_path / "ventana.py"
    ruta.write_text(
        "".join(f"linea_{i} = {i}\n" for i in range(1, 201)),
        encoding="utf-8",
    )
    rend = preview_archivo(str(ruta), max_lineas=5, desde=100)
    texto = _exportar(rend)
    assert "linea_100" in texto
    assert "linea_1 " not in texto and "linea_106" not in texto


def test_binario_devuelve_none(tmp_path):
    ruta = tmp_path / "binario.bin"
    ruta.write_bytes(b"MZ\x00\x01\x02cabecera binaria\x00")
    assert preview_archivo(str(ruta)) is None
    assert contar_lineas(str(ruta)) is None


def test_latin1_no_explota(tmp_path):
    # leccion Latin-1 del repo: bytes no-utf8 se muestran igual (solo
    # para mostrar, jamas re-escribir)
    ruta = tmp_path / "acentos.py"
    ruta.write_bytes("# configuraci\xf3n\nx = 1\n".encode("latin-1"))
    rend = preview_archivo(str(ruta))
    assert rend is not None
    assert "x = 1" in _exportar(rend)


def test_contar_lineas(archivo_py, tmp_path):
    assert contar_lineas(archivo_py) == 5
    sin_nl = tmp_path / "sin_nl.txt"
    sin_nl.write_text("una linea sin salto", encoding="utf-8")
    assert contar_lineas(str(sin_nl)) == 1
    assert contar_lineas(str(tmp_path / "nada.txt")) is None
