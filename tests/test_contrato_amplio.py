"""
El contrato interno AMPLIO (dirección CodeRM, PREREG_CONTRATO_AMPLIO_20260727).

Medido 2026-07-27 sobre 196 corridas en disco: con la plantilla clásica de
≤8 pasos el sello interno queda al nivel del azar contra el examen del banco
en composicionales (FP 32-50%, FN 50%). La variante amplia (10-16 pasos,
cobertura por regla, secuencias largas, check negativo) se selecciona por
parámetro y NO reemplaza a la clásica hasta que su A/B pre-registrado pase.
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


def test_clasico_es_el_default_y_no_cambia():
    c, llamada = _llamar()
    assert c is not None
    assert "COMO MUCHO 8 PASOS" in llamada.args[0]
    assert "COBERTURA OBLIGATORIA" not in llamada.args[0]
    assert llamada.kwargs["max_tokens"] == 9000


def test_amplio_selecciona_plantilla_y_presupuesto():
    c, llamada = _llamar(modo="amplio")
    assert c is not None
    prompt = llamada.args[0]
    assert "ESCRIBE ENTRE 10 Y 16 PASOS" in prompt
    assert "COBERTURA OBLIGATORIA" in prompt
    assert "COMO MUCHO 8 PASOS" not in prompt
    # el presupuesto cubre la respuesta mas larga (10-16 pasos)
    assert llamada.kwargs["max_tokens"] == 12000


def test_amplio_conserva_las_guardas_anti_invencion():
    # Las guardas medidas (esperado exacto vs min, literales inventados,
    # selectores OBLIGATORIOS de la idea) tienen que sobrevivir el replace.
    assert "NUNCA inventes el valor literal" in je._PLANTILLA_CONTRATO_AMPLIO
    assert "EXCEPCION unica" in je._PLANTILLA_CONTRATO_AMPLIO
    assert "min" in je._PLANTILLA_CONTRATO_AMPLIO
    # y el replace realmente sustituyo la linea del tope corto
    assert "COMO MUCHO 8 PASOS" not in je._PLANTILLA_CONTRATO_AMPLIO
