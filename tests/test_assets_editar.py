"""
editar_transparente (img2img): editar una imagen YA HECHA con el modelo de
imagenes. La edicion real necesita GPU (SDXL); aqui se cubre lo que corre en CPU:
que la funcion este exportada y que valide sus argumentos ANTES de tocar la GPU.
"""

import pytest

from cognia import assets


def test_editar_transparente_esta_exportada():
    assert hasattr(assets, "editar_transparente")
    assert callable(assets.editar_transparente)


def test_metodo_invalido_falla_rapido_sin_gpu():
    # El chequeo de metodo ocurre antes de cualquier import de torch/PIL: se
    # puede verificar sin GPU ni pipeline cargado.
    with pytest.raises(assets.AssetsError):
        assets.editar_transparente("no_importa.png", "haz algo", metodo="xxx")
