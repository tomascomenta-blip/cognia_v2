# -*- coding: utf-8 -*-
"""El enrutado de /ayuda: comando vs categoria vs busqueda.

`/ayuda X` tiene tres destinos y comparten espacio de nombres, que es donde se
rompio dos veces al cablearlo (2026-08-12):
  - '/ayuda buscar tokens'  ->  buscaba la ficha del comando /buscar y
                                contestaba "Comando no encontrado".
  - '/ayuda grafo de conocimiento' -> casaba el primer token con /grafo y
                                contestaba lo mismo.
La regla que fija este fichero: con barra manda el comando; sin barra tiene que
casar el texto ENTERO, y las ordenes de la propia ayuda nunca son comandos.
"""

from __future__ import annotations

import pytest

from cognia.cli import _CMD_DESCRIPTIONS, _es_comando_conocido
from cognia.harness import ayuda


# ── el enrutado ────────────────────────────────────────────────────────
@pytest.mark.parametrize("entrada", ["/hacer", "hacer", "/grafo html", "/memoria"])
def test_un_comando_va_a_su_ficha(entrada):
    assert _es_comando_conocido(entrada) is True


@pytest.mark.parametrize("entrada", [
    "buscar tokens",          # 'buscar' es orden de la ayuda, no el /buscar
    "buscar",
    "todo",
    "grafo de conocimiento",  # nombre de categoria que empieza por un comando
    "memoria y notas",
    "",
    "   ",
])
def test_lo_demas_va_a_la_ayuda_navegable(entrada):
    assert _es_comando_conocido(entrada) is False


def test_la_barra_explicita_desempata_a_favor_del_comando():
    """'/ayuda /buscar' tiene que dar la ficha, no la busqueda."""
    assert _es_comando_conocido("/buscar") is True
    assert _es_comando_conocido("buscar") is False


def test_un_comando_inventado_no_se_confunde_con_categoria():
    assert _es_comando_conocido("/no_existe_este_comando") is False


# ── que los destinos existan de verdad ─────────────────────────────────
def test_la_portada_no_vuelca_los_240_comandos():
    texto = ayuda.portada(_CMD_DESCRIPTIONS, 100)
    lineas = texto.split("\n")
    assert len(lineas) <= 40, (
        f"la portada de la ayuda son {len(lineas)} lineas: volvio a ser una pared")
    assert "/ayuda buscar" in texto, "la portada tiene que decir como buscar"


def test_las_categorias_de_la_portada_se_pueden_abrir():
    """Cada categoria anunciada tiene que responder a /ayuda <categoria>."""
    for categoria, comandos in ayuda.indice(_CMD_DESCRIPTIONS, 100):
        assert comandos, f"la categoria {categoria!r} se anuncia vacia"
        texto = ayuda.seccion(_CMD_DESCRIPTIONS, categoria, 100)
        assert categoria.split()[0].lower() in texto.lower(), (
            f"/ayuda {categoria} no devuelve su propia seccion")


def test_la_busqueda_encuentra_por_descripcion():
    hits = [c for c, _, _ in ayuda.buscar(_CMD_DESCRIPTIONS, "tokens")]
    assert hits, "buscar 'tokens' no devolvio nada"
    assert any("costo" in c for c in hits), hits
