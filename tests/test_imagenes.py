"""
/imagenes — gestion de las capturas que Cognia toma de sus paginas.

Las input images son temporales por definicion: son la evidencia que Cognia
miro en el navegador para validarse. Se pueden tirar sin perder trabajo, y
conviene poder hacerlo porque se acumulan (unos 56 KB por captura, 2 por
pagina generada).
"""

import pytest

from cognia.program_creator.vista_navegador import (
    DIR_INPUT,
    DIR_OUTPUT,
    borrar_imagenes,
    formatear_imagenes,
    listar_imagenes,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 400


def _biblioteca(base, programas):
    """Crea una biblioteca falsa: {nombre: (n_input, n_output)}."""
    for nombre, (n_in, n_out) in programas.items():
        d = base / nombre
        d.mkdir(parents=True)
        (d / "index.html").write_text("<html></html>", encoding="utf-8")
        for i in range(n_in):
            (d / DIR_INPUT).mkdir(exist_ok=True)
            (d / DIR_INPUT / f"validacion_{i}.png").write_bytes(PNG)
        for i in range(n_out):
            (d / DIR_OUTPUT).mkdir(exist_ok=True)
            (d / DIR_OUTPUT / f"resultado_{i}.png").write_bytes(PNG)
    return base


class TestListado:

    def test_lista_vacia_sin_imagenes(self, tmp_path):
        _biblioteca(tmp_path, {"solo_codigo": (0, 0)})
        assert listar_imagenes(tmp_path) == []

    def test_agrupa_por_programa(self, tmp_path):
        _biblioteca(tmp_path, {"dash": (2, 1), "landing": (2, 1)})
        lotes = listar_imagenes(tmp_path)

        assert len(lotes) == 2
        assert {l.programa for l in lotes} == {"dash", "landing"}
        for l in lotes:
            assert len(l.entrada) == 2
            assert len(l.salida) == 1
            assert l.total == 3
            assert l.bytes > 0

    def test_ignora_directorios_sin_capturas(self, tmp_path):
        _biblioteca(tmp_path, {"con": (1, 1), "sin": (0, 0)})
        assert [l.programa for l in listar_imagenes(tmp_path)] == ["con"]


class TestBorrado:

    def test_borrar_input_deja_los_resultados(self, tmp_path):
        """El caso normal: liberar las temporales sin perder el resultado."""
        _biblioteca(tmp_path, {"dash": (2, 1)})

        n, liberado = borrar_imagenes(tmp_path, solo="input")

        assert n == 2
        assert liberado > 0
        lotes = listar_imagenes(tmp_path)
        assert len(lotes) == 1
        assert lotes[0].entrada == []
        assert len(lotes[0].salida) == 1
        # La carpeta vacia tambien se va: si no, queda ruido en el disco.
        assert not (tmp_path / "dash" / DIR_INPUT).exists()

    def test_borrar_output(self, tmp_path):
        _biblioteca(tmp_path, {"dash": (2, 1)})
        n, _ = borrar_imagenes(tmp_path, solo="output")

        assert n == 1
        assert listar_imagenes(tmp_path)[0].salida == []

    def test_borrar_todo(self, tmp_path):
        _biblioteca(tmp_path, {"dash": (2, 1), "landing": (2, 2)})
        n, _ = borrar_imagenes(tmp_path, solo="todo")

        assert n == 7
        assert listar_imagenes(tmp_path) == []

    def test_borrar_solo_un_programa(self, tmp_path):
        _biblioteca(tmp_path, {"dash": (2, 1), "landing": (2, 1)})
        n, _ = borrar_imagenes(tmp_path, programa="dash", solo="todo")

        assert n == 3
        restantes = listar_imagenes(tmp_path)
        assert [l.programa for l in restantes] == ["landing"]

    def test_no_toca_el_codigo_generado(self, tmp_path):
        """Borrar capturas no puede llevarse por delante la pagina."""
        _biblioteca(tmp_path, {"dash": (2, 1)})
        borrar_imagenes(tmp_path, solo="todo")

        assert (tmp_path / "dash" / "index.html").exists()

    def test_borrar_dos_veces_no_falla(self, tmp_path):
        _biblioteca(tmp_path, {"dash": (1, 1)})
        borrar_imagenes(tmp_path, solo="todo")
        n, liberado = borrar_imagenes(tmp_path, solo="todo")

        assert (n, liberado) == (0, 0)


class TestFormato:

    def test_mensaje_cuando_no_hay_nada(self, tmp_path):
        assert "No hay imagenes" in formatear_imagenes(tmp_path)

    def test_listado_numerado_y_con_tamano(self, tmp_path):
        _biblioteca(tmp_path, {"dash": (2, 1)})
        texto = formatear_imagenes(tmp_path)

        assert "dash" in texto
        assert "input: 2" in texto
        assert "output: 1" in texto
        assert "borrar input" in texto
        assert "temporales" in texto
