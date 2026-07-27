"""
El contrato interno CORREGIDO (PREREG_SENAL_CONTRATO_20260727, resultado 1a).

Medido 2026-07-27 re-ejecutando 48 contratos en disco sub-acción por
sub-acción: la aserción de texto sobre un <input> falla SIEMPRE en páginas
sanas (55/55) porque inner_text de un campo es vacío, y el pensador la usa
porque la plantilla no documenta `escribir` (0/48 contratos la usan). Además
7/24 contratos clásicos no marcan ningún paso critico y aprueban por
vacuidad. El modo `corregido` = clásico + F1 (escribir+Tab) + F2 (inputs por
js .value) + F5 (criticidad); NO reemplaza al clásico hasta que su A/B pase.
"""

import json
from unittest.mock import patch

from cognia.program_creator import juez_ejecutable as je

_CONTRATO_OK = json.dumps({
    "nombre": "t",
    "pasos": [{"accion": "contar", "selector": ".x", "esperado": 1,
               "nombre": "hay uno", "critico": True}]})

_INV = {"clases": {".x": 1}, "ids": ["total"]}


def _llamar(modo=None):
    kwargs = {"modo": modo} if modo else {}
    with patch.object(je, "inventario_dom", return_value=_INV), \
         patch("cognia.llm_local.generar",
               return_value=_CONTRATO_OK) as gen:
        c = je.generar_contrato("una idea", "no_importa.html", **kwargs)
    return c, gen.call_args


def test_corregido_documenta_escribir_y_lectura_de_inputs():
    c, llamada = _llamar(modo="corregido")
    assert c is not None
    prompt = llamada.args[0]
    # F1: la accion escribir existe para el pensador, con el patron Tab
    assert '"accion":"escribir"' in prompt
    assert '"key":"Tab"' in prompt
    assert '"texto" NO escribe' in prompt
    # F2: el valor de un campo se lee con js .value, nunca con texto
    assert ".value" in prompt
    assert "SIEMPRE vacio" in prompt
    # F5: la regla de criticidad
    assert "ningun paso es critico no verifica nada" in prompt


def test_corregido_conserva_el_tope_y_las_guardas_del_clasico():
    c, llamada = _llamar(modo="corregido")
    prompt = llamada.args[0]
    # sigue siendo el examen corto: la palanca es correccion, no cantidad
    # (el modo amplio ya dio GRIS por disparar el FN a 75%)
    assert "COMO MUCHO 8 PASOS" in prompt
    assert "COBERTURA OBLIGATORIA" not in prompt
    assert "NUNCA inventes el valor literal" in prompt
    assert "EXCEPCION unica" in prompt
    assert llamada.kwargs["max_tokens"] == 9000


def test_clasico_no_cambia_con_el_modo_nuevo():
    c, llamada = _llamar()          # default
    prompt = llamada.args[0]
    assert '"accion":"escribir"' not in prompt
    assert "SIEMPRE vacio" not in prompt
    assert "COMO MUCHO 8 PASOS" in prompt


def test_los_replace_del_corregido_sustituyeron_de_verdad():
    # Si el texto ancla del .replace deriva, el replace se vuelve un no-op
    # silencioso (la clase de bug de este repo: degradar sin excepcion).
    assert '"accion":"escribir"' in je._PLANTILLA_CONTRATO_CORREGIDO
    assert ("ningun paso es critico no verifica nada"
            in je._PLANTILLA_CONTRATO_CORREGIDO)
    assert je._PLANTILLA_CONTRATO_CORREGIDO != je._PLANTILLA_CONTRATO
