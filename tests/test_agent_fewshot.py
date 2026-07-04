"""Regresion de cognia/agent/fewshot.py (banco de ejemplos ACCION, wire +62pp)."""
from cognia.agent.fewshot import _EXAMPLES, fewshot_for


def test_fewshot_devuelve_bloque_con_formato_exacto():
    b = fewshot_for("generar_codigo")
    assert b.startswith("EJEMPLOS (formato exacto):")
    assert "ACCION: generar_codigo" in b
    assert " | " in b                      # el separador real de args


def test_fewshot_tool_desconocida_es_vacio():
    assert fewshot_for("inexistente") == ""
    assert fewshot_for("") == ""
    assert fewshot_for(None) == ""


def test_fewshot_normaliza_nombre():
    assert fewshot_for("  Tests ") == fewshot_for("tests")


def test_fewshot_respeta_max_examples():
    for tool in _EXAMPLES:
        b = fewshot_for(tool, max_examples=1)
        assert b.count("ACCION:") == 1


def test_ejemplos_arrancan_con_accion():
    # cada ejemplo del banco ES una linea ACCION valida (el 3B copia formato)
    for tool, exs in _EXAMPLES.items():
        for e in exs:
            assert e.startswith("ACCION: " + tool), (tool, e)
