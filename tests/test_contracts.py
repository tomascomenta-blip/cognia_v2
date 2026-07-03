"""
Regresion de cognia/agent/contracts.py (CP3, base de AG-ARB).

Fija la semantica de la atribucion por etapa con control: los contratos
localizan design-fault y code-fault (etapas con oraculo ejecutable) y
declaran su limite en plan-propagado y test-corrupto (no distinguibles sin
2da referencia). Ejecucion de tests REAL (run_task_tests), no mock.
"""
from cognia.agent.contracts import (
    attribute_failure, contract_code_test, contract_design_code,
    contract_plan_design,
)

CORRECT = {
    "plan": {"text": "Doblar n.", "required_entities": ["double"]},
    "design": {"text": "Funcion double sobre n.", "signatures": ["double(n)"]},
    "code": {"code": "def double(n):\n    return n * 2\n"},
    "test": {"tests": "assert double(2) == 4\nassert double(0) == 0\n",
             "entry_point": "double"},
}


def test_pipeline_correcto_sin_falla():
    r = attribute_failure(CORRECT)
    assert r["stage"] is None


def test_design_fault_atribuido_a_design():
    """Firma inflada en design, code correcto -> control (code pasa tests)
    localiza el outlier en design."""
    p = {**CORRECT, "design": {**CORRECT["design"],
                               "signatures": ["double(a, b, c)"]}}
    r = attribute_failure(p)
    assert r["stage"] == "design"
    assert "control" in r["contract"]


def test_code_fault_atribuido_a_code():
    p = {**CORRECT, "code": {"code": "def double(n):\n    return n + 2\n"}}
    r = attribute_failure(p)
    assert r["stage"] == "code"


def test_plan_propagado_se_manifiesta_como_code():
    """Limite declarado: un stub que ignora la tarea (raiz en plan) se
    atribuye a code — la raiz upstream NO es recuperable por contratos."""
    p = {**CORRECT, "code": {"code": "def double(n):\n    return None\n"}}
    r = attribute_failure(p)
    assert r["stage"] == "code"        # NO 'plan' — el limite es real


def test_test_corrupto_se_atribuye_a_code():
    """Limite declarado: un test con valor esperado malo, code correcto ->
    se atribuye a code (indistinguible sin 2da referencia)."""
    p = {**CORRECT, "test": {"tests": "assert double(2) == 999\n",
                             "entry_point": "double"}}
    r = attribute_failure(p)
    assert r["stage"] == "code"


def test_contract_plan_design_detecta_faltante():
    plan = {"required_entities": ["foo", "bar"]}
    design = {"text": "solo menciona foo", "signatures": ["foo(x)"]}
    assert contract_plan_design(plan, design) is not None
    assert contract_plan_design({"required_entities": ["foo"]},
                                {"text": "foo aca", "signatures": []}) is None


def test_contract_design_code_arity():
    design = {"signatures": ["f(a, b)"]}
    assert contract_design_code(design, {"code": "def f(a, b):\n    return a\n"}) is None
    assert contract_design_code(design, {"code": "def f(a):\n    return a\n"}) is not None
    assert contract_design_code(design, {"code": "def g(a, b):\n    return a\n"}) is not None


def test_contract_code_test_ejecucion_real():
    ok_code = {"code": "def f(x):\n    return x + 1\n", "entry_point": "f"}
    assert contract_code_test(ok_code, {"tests": "assert f(1) == 2\n",
                                        "entry_point": "f"}) is None
    assert contract_code_test(ok_code, {"tests": "assert f(1) == 5\n",
                                        "entry_point": "f"}) is not None
