# -*- coding: utf-8 -*-
"""
DSH · las capacidades del agente, visibles y encendibles (2026-08-18).

EL PROBLEMA: ~111 herramientas registrables, 13 anunciadas, y las otras detrás
de nueve variables de entorno que ningún comando encendía. El recorte está
MEDIDO y es correcto (un catálogo de 46 tools baja el camino feliz de 4,25/5 a
2,5/5); lo que faltaba era poder deshacerlo desde dentro. Subsistemas enteros
verificados en GPU — imágenes, música, 3D, escena LCD — eran inalcanzables en
la práctica.

Estos tests usan el registro REAL (nada de mocks): la pregunta que contestan es
"¿de verdad quedan disponibles?", y con un registro falso no significaría nada.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.harness import familias as F


@pytest.fixture(autouse=True)
def _flags_limpios():
    """Deja los flags Y EL REGISTRO como estaban.

    Restaurar solo os.environ no bastaba: activar() registra las tools de
    verdad en el TOOLS global, que es de proceso, y ahi se quedaban. La suite
    lo cazo -- test_firmas_tipadas empezo a fallar por unas imagen_* que este
    fichero habia dejado puestas. Un test que activa capacidades reales tiene
    que devolver el proceso a como lo encontro.
    """
    from cognia.agent.tools import TOOLS
    previos = {f["flag"]: os.environ.get(f["flag"]) for f in F.FAMILIAS.values()}
    tools_previas = set(TOOLS)
    yield
    for flag, valor in previos.items():
        if valor is None:
            os.environ.pop(flag, None)
        else:
            os.environ[flag] = valor
    for nueva in set(TOOLS) - tools_previas:
        TOOLS.pop(nueva, None)


class TestElInventarioEsHonesto:

    def test_estado_describe_todas_las_familias(self):
        filas = F.estado()
        assert len(filas) == len(F.FAMILIAS)
        for f in filas:
            assert f["familia"] and f["que"] and f["flag"]
            assert isinstance(f["encendida"], bool)
            assert isinstance(f["n_tools"], int)

    def test_cada_familia_dice_QUE_la_enciende(self):
        # Sin esto el usuario tiene que leer el código fuente para saber el
        # nombre del flag, que es exactamente el problema que arregla esto.
        for f in F.estado():
            assert f["flag"].startswith("COGNIA_")

    def test_las_que_tocan_la_maquina_estan_marcadas(self):
        peligrosas = {f["familia"] for f in F.estado() if f["peligrosa"]}
        assert "pantalla" in peligrosas and "navegador" in peligrosas
        assert "musica" not in peligrosas

    def test_el_inventario_cubre_los_subsistemas_huerfanos(self):
        # Los que el mapa encontró SIN puerta de entrada: música, imágenes, 3D.
        nombres = {f["familia"] for f in F.estado()}
        for huerfano in ("musica", "imagen", "3d", "voz", "escena"):
            assert huerfano in nombres, huerfano


class TestEncenderDeVerdad:

    def test_activar_registra_tools_nuevas_en_caliente(self):
        from cognia.agent.tools import TOOLS
        antes = len(TOOLS)
        r = F.activar("imagen")
        assert r["ok"] is True
        # Lo que importa no es el flag: es que las tools SEAN alcanzables.
        assert len(TOOLS) >= antes
        assert any(t.startswith("imagen_") for t in TOOLS), \
            "el flag se puso pero las tools no quedaron en el registro"

    def test_lo_que_activa_queda_listado(self):
        F.activar("imagen")
        fila = next(f for f in F.estado() if f["familia"] == "imagen")
        assert fila["encendida"] is True
        assert fila["n_tools"] >= 1
        assert all(t.startswith("imagen_") for t in fila["tools"])

    def test_activar_dos_veces_no_duplica(self):
        F.activar("imagen")
        primera = len(F._tools_de("imagen"))
        r = F.activar("imagen")
        assert r["ok"] is True
        assert len(F._tools_de("imagen")) == primera

    def test_familia_desconocida_lo_dice_y_ofrece_las_que_hay(self):
        r = F.activar("teletransporte")
        assert r["ok"] is False
        assert "no conozco" in r["detalle"]
        assert "imagen" in r["detalle"]      # dice cuáles SÍ existen

    def test_un_modulo_roto_NO_se_traga_en_silencio(self, monkeypatch):
        # El modo de fallo de la casa: flag puesto, import roto, silencio, y
        # una capacidad "activada" que no existe. Tiene que decirlo.
        def _explota():
            raise ImportError("falta una dependencia")

        monkeypatch.setitem(F.FAMILIAS["musica"], "cargar", _explota)
        r = F.activar("musica")
        assert r["ok"] is False
        assert "no cargó" in r["detalle"] or "no cargo" in r["detalle"]
        assert "ImportError" in r["detalle"]

    def test_desactivar_no_finge_una_descarga_que_no_ocurre(self):
        F.activar("imagen")
        r = F.desactivar("imagen")
        assert r["ok"] is True
        assert os.environ["COGNIA_IMG_TOOLS"] == "0"
        # Honestidad: las ya cargadas siguen en memoria y se dice.
        assert "reiniciar" in r["detalle"]


class TestLosComandosExistenParaElUsuario:
    """Un comando que no sale en la ayuda no existe: el repo ya tiene 13
    huérfanos así, y este mismo mapa los encontró."""

    def _cli(self):
        return (Path(__file__).resolve().parent.parent / "cognia" /
                "cli.py").read_text(encoding="utf-8")

    def test_capacidades_esta_en_la_ayuda_y_en_el_despacho(self):
        fuente = self._cli()
        assert '"/capacidades":' in fuente
        assert 'raw == "/capacidades"' in fuente
        assert "def _slash_capacidades" in fuente

    def test_activar_esta_en_la_ayuda_y_en_el_despacho(self):
        fuente = self._cli()
        assert '"/activar":' in fuente
        assert 'raw == "/activar"' in fuente
        assert "def _slash_activar" in fuente

    def test_vram_esta_en_la_ayuda_y_en_el_despacho(self):
        fuente = self._cli()
        assert '"/vram":' in fuente
        assert 'raw == "/vram"' in fuente
        assert "def _slash_vram" in fuente

    def test_activar_todo_avisa_en_vez_de_degradar_al_modelo(self):
        # Encender las 14 familias mete ~100 tools en el catálogo, y el A/B del
        # propio repo midió que eso hunde al agente. No puede ser un camino
        # cómodo sin aviso.
        fuente = self._cli()
        assert '"todo", "todas"' in fuente
        assert "4,25/5" in fuente or "degrada" in fuente
