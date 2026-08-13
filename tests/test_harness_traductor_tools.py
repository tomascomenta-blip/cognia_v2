# -*- coding: utf-8 -*-
"""Un nombre de herramienta inventado se traduce, no se castiga con 54 nombres.

EVIDENCIA REAL (tabla wanted_tools del repo, leida el 2026-08-13): 41 nombres
inventados, y el campeon es `crear_archivo` con **42 hits**, llamado asi:

    crear_archivo   "nota1.txt | Contenido del archivo 1 sobre planetas..."

El modelo sabia la tarea, los argumentos y el formato del protocolo; solo erro el
nombre. Y recibia el catalogo ENTERO volcado encima — lo contrario de lo que dice
el A/B del propio repo sobre catalogos grandes.
"""

from __future__ import annotations

import pytest

from cognia.harness.traductor_tools import mensaje_error, parecidas, traducir

# El catalogo CORE real, que es lo que ve el modelo por defecto.
CORE = {"leer_archivo", "escribir_archivo", "editar_archivo", "apendar_archivo",
        "borrar_archivo", "listar", "buscar", "ejecutar", "tests",
        "generar_codigo", "delegar_subtarea", "recordar", "calcular"}


# ── los casos MEDIDOS en produccion ────────────────────────────────────
@pytest.mark.parametrize("inventado,real", [
    ("crear_archivo", "escribir_archivo"),      # 42 hits reales
    ("crear_fichero", "escribir_archivo"),
    ("guardar_archivo", "escribir_archivo"),
    ("eliminar_archivo", "borrar_archivo"),
    ("modificar_archivo", "editar_archivo"),
    ("ejecutar_tests", "tests"),
    ("bash", "ejecutar"),
    ("shell", "ejecutar"),
])
def test_traduce_los_nombres_que_el_modelo_inventa_de_verdad(inventado, real):
    assert traducir(inventado, CORE) == real


def test_un_typo_se_caza_por_parecido_literal():
    assert traducir("leer_archivos", CORE) == "leer_archivo"
    assert traducir("escrbir_archivo", CORE) == "escribir_archivo"


def test_una_tool_que_existe_no_se_traduce():
    assert traducir("escribir_archivo", CORE) == ""
    assert traducir("tests", CORE) == ""


def test_no_sugiere_una_tool_que_esta_apagada():
    """Mandarlo a una tool fuera de su catalogo es mandarlo a otro error."""
    sin_tests = CORE - {"tests"}
    assert traducir("ejecutar_tests", sin_tests) != "tests"


def test_nombre_sin_nada_parecido_no_inventa_traduccion():
    assert traducir("teletransportar_gato", CORE) == ""


# ── el mensaje que ve el modelo ────────────────────────────────────────
def test_el_error_da_el_nombre_bueno_y_no_el_catalogo():
    msg = mensaje_error("crear_archivo", CORE)
    assert "escribir_archivo" in msg
    assert "mismos argumentos" in msg, "hay que decirle que NO reescriba los args"
    # Lo que se arregla: el volcado del catalogo entero.
    assert msg.count(",") <= 2, f"sigue volcando la lista: {msg}"
    assert "delegar_subtarea" not in msg


def test_sin_traduccion_clara_da_3_candidatas_no_54():
    msg = mensaje_error("archivo_nuevo_raro", CORE)
    nombradas = [t for t in CORE if t in msg]
    assert len(nombradas) <= 3, f"nombro {len(nombradas)}: {msg}"


def test_sin_nada_parecido_no_lista_nada():
    msg = mensaje_error("teletransportar_gato", CORE)
    assert "no existe" in msg
    nombradas = [t for t in CORE if t in msg]
    assert not nombradas, f"no habia nada parecido pero nombro {nombradas}"


def test_parecidas_respeta_el_limite():
    assert len(parecidas("archivo", CORE, limite=3)) <= 3


# ── el cableado en run_tool ────────────────────────────────────────────
def test_run_tool_no_vuelca_el_catalogo_entero(tmp_path, monkeypatch):
    from cognia.agent.tools import TOOLS, run_tool
    monkeypatch.chdir(tmp_path)
    salida = run_tool("crear_archivo", "nota.txt | hola", {"working_memory": {}})
    assert "escribir_archivo" in salida
    # El sintoma exacto que se arreglo: 54 nombres en el mensaje de error.
    nombradas = sum(1 for t in TOOLS if t in salida)
    assert nombradas <= 4, f"el error nombra {nombradas} herramientas"
