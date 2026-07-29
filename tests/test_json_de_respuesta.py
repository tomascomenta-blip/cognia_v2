"""El extractor de contratos frente a pensadores con razonamiento INLINE.

Regresion de 2026-07-28: OpenReasoning-Nemotron-14B devuelve
<think>...</think> en el contenido y el extractor agarraba llaves/fences del
pensamiento ('Expecting value: line 1'). gpt-oss no pasa por ahi (su canal de
razonamiento lo separa el template del server) y su camino no cambia.
"""

from cognia.program_creator.juez_ejecutable import _json_de_respuesta


def test_think_con_fence_y_llaves_dentro_no_confunde():
    crudo = (
        "<think>primero {esbozo} un ejemplo ```json\n{\"no\": 1}\n``` "
        "y sigo pensando</think>\n"
        "```json\n{\"nombre\": \"x\", \"pasos\": [{\"accion\": \"existe\", "
        "\"selector\": \"#a\", \"critico\": true}]}\n```")
    c = _json_de_respuesta(crudo)
    assert c is not None and c["nombre"] == "x"
    assert c["pasos"][0]["selector"] == "#a"


def test_sin_think_camino_clasico_intacto():
    crudo = "```json\n{\"nombre\": \"y\", \"pasos\": []}\n```"
    assert _json_de_respuesta(crudo) == {"nombre": "y", "pasos": []}


def test_json_pelado_sin_fence():
    assert _json_de_respuesta('{"nombre": "z", "pasos": []}') == {
        "nombre": "z", "pasos": []}


def test_basura_devuelve_none():
    assert _json_de_respuesta("no hay contrato aqui") is None


def test_contrato_completo_con_repeticion_detras_se_rescata():
    # Nemotron a veces cierra el contrato y luego repite basura: raw_decode
    # toma el primer objeto balanceado e ignora el resto.
    crudo = ('{"nombre": "w", "pasos": []}\n'
             '{"accion": "tecla"}\n{"accion": "tecla"}')
    assert _json_de_respuesta(crudo) == {"nombre": "w", "pasos": []}


def test_contrato_truncado_sin_cerrar_devuelve_none():
    crudo = '{"nombre": "v", "pasos": [{"accion": "tecla"}, {"accion": '
    assert _json_de_respuesta(crudo) is None


def test_think_sin_nada_despues_devuelve_none():
    assert _json_de_respuesta("<think>puro pensamiento</think>") is None
