"""
El modo `validado`: filtro de aserciones contra el ENUNCIADO (séptima
enmienda de PREREG_SENAL_CONTRATO_20260727.md).

El FN residual del contrato autogenerado son expectativas INVENTADAS que
acusan a páginas sanas (medido: existe/existencia 62% FN por literales de
selector supuestos; ambos modos previos clavados en FN 14/19). El
validador ve SOLO idea+pasos y descarta los no exigidos; por plomería
NUNCA puede ser peor que el contrato sin filtrar (fallback al original).
"""

import json
from unittest.mock import patch

from cognia.program_creator import juez_ejecutable as je

_CONTRATO = json.dumps({
    "nombre": "t",
    "pasos": [
        {"accion": "contar", "selector": ".x", "esperado": 3,
         "nombre": "hay tres", "critico": True},
        {"accion": "texto", "selector": "#total", "contiene": "CIRC",
         "nombre": "literal inventado", "critico": True},
        {"accion": "existe", "selector": ".x", "nombre": "existe x",
         "critico": False}]})

_INV = {"clases": {".x": 3}, "ids": ["total"]}


def _llamar(respuestas):
    with patch.object(je, "inventario_dom", return_value=_INV), \
         patch("cognia.llm_local.generar", side_effect=respuestas) as gen:
        c = je.generar_contrato("una idea", "no_importa.html",
                                modo="validado")
    return c, gen


def test_validado_filtra_los_pasos_no_exigidos():
    c, gen = _llamar([_CONTRATO, '{"conservar": [1, 3]}'])
    assert gen.call_count == 2
    assert len(c["pasos"]) == 2
    assert c["pasos"][0]["nombre"] == "hay tres"
    assert c["pasos"][1]["nombre"] == "existe x"
    assert c["_validado"] == {"antes": 3, "despues": 2}
    # el validador ve idea+pasos, nunca el inventario del DOM
    prompt_validador = gen.call_args_list[1].args[0]
    assert "literal inventado" in prompt_validador
    assert ".x  x3" not in prompt_validador


def test_fallback_si_el_filtro_deja_menos_de_dos_pasos():
    c, _ = _llamar([_CONTRATO, '{"conservar": [2]}'])
    assert len(c["pasos"]) == 3          # original intacto
    assert "_validado" not in c


def test_fallback_si_el_filtro_mata_todos_los_criticos():
    # conservar solo el paso 3 (no critico) mas otro invalido: quedarian
    # pasos sin ningun critico -> vacuidad; se devuelve el original.
    c, _ = _llamar([_CONTRATO, '{"conservar": [3, 99]}'])
    assert len(c["pasos"]) == 3
    assert "_validado" not in c


def test_fallback_si_el_validador_no_devuelve_json():
    c, _ = _llamar([_CONTRATO, "no soy json"])
    assert len(c["pasos"]) == 3
    c2, _ = _llamar([_CONTRATO, None])
    assert len(c2["pasos"]) == 3


def test_clasico_no_paga_la_segunda_llamada():
    with patch.object(je, "inventario_dom", return_value=_INV), \
         patch("cognia.llm_local.generar",
               side_effect=[_CONTRATO]) as gen:
        c = je.generar_contrato("una idea", "no_importa.html")
    assert c is not None and gen.call_count == 1
