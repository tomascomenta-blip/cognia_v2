"""
tests/test_experiment_lab.py
============================
Tests del laboratorio de experimentacion (cognia/reasoning/experiment_lab.py).

run_experiment se prueba con un orchestrator FAKE (doble de test, NO mock de
produccion). El sandbox NO se mockea: queremos validar la integracion REAL con
run_in_sandbox (la regla 9 vale dentro del test tambien).
"""

import cognia.reasoning.experiment_lab as lab


# ── _extract_code ───────────────────────────────────────────────────────────

def test_extract_code_fenced_python():
    raw = "Aqui va:\n```python\nprint('hola')\nx = 1\n```\nfin"
    assert lab._extract_code(raw) == "print('hola')\nx = 1"


def test_extract_code_fenced_bare():
    raw = "```\nprint('hola')\n```"
    assert lab._extract_code(raw) == "print('hola')"


def test_extract_code_no_fence():
    raw = "El experimento mide tiempos.\nimport time\nprint('ok')"
    code = lab._extract_code(raw)
    assert code.startswith("import time")
    assert "print('ok')" in code


def test_extract_code_empty():
    assert lab._extract_code("") == ""
    assert lab._extract_code("solo prosa sin nada de codigo aqui") == ""


# ── _parse_verdict ──────────────────────────────────────────────────────────

def test_parse_verdict_pass():
    assert lab._parse_verdict("medicion: 3\nVERDICT: PASS") == "PASS"


def test_parse_verdict_fail_case_insensitive_spanish():
    assert lab._parse_verdict("datos...\nveredicto: fail") == "FAIL"


def test_parse_verdict_absent_is_inconcluso():
    assert lab._parse_verdict("solo numeros\n42\n") == "inconcluso"


# ── run_experiment (integracion real con el sandbox) ────────────────────────

class _FakeOrchestrator:
    """Doble de test: cualquier infer() devuelve un objeto con .text fijo."""

    class _R:
        def __init__(self, text):
            self.text = text

    def __init__(self, payload):
        self._payload = payload

    def infer(self, prompt, max_tokens=0, temperature=0.0):
        return self._R(self._payload)


def test_run_experiment_pass_real_sandbox(monkeypatch):
    # Parchea creative_generate (nombre importado en el modulo lab) para
    # inyectar codigo trivial seguro. El sandbox SI corre de verdad.
    safe_code = "```python\nprint('medida = 1')\nprint('VERDICT: PASS')\n```"
    monkeypatch.setattr(lab, "creative_generate",
                        lambda orch, prompt, **kw: safe_code)

    res = lab.run_experiment(_FakeOrchestrator(safe_code), "1 + 1 da 2")
    assert res["executed"] is True
    assert res["success"] is True
    assert res["verdict"] == "PASS"
    assert res["blocked"] == []
    assert res["timed_out"] is False


def test_run_experiment_blocked_import_not_faked_success(monkeypatch):
    # Codigo que importa socket -> el AST scan del sandbox lo bloquea.
    bad_code = "```python\nimport socket\nprint('VERDICT: PASS')\n```"
    monkeypatch.setattr(lab, "creative_generate",
                        lambda orch, prompt, **kw: bad_code)

    res = lab.run_experiment(_FakeOrchestrator(bad_code), "puedo abrir sockets")
    assert res["executed"] is True
    assert res["success"] is False            # NO se finge exito
    assert res["blocked"]                      # hay violaciones reportadas
    assert any("socket" in str(b) for b in res["blocked"])


def test_run_experiment_no_backend():
    res = lab.run_experiment(None, "cualquier afirmacion")
    assert res["executed"] is False
    assert "reason" in res


def test_run_experiment_empty_claim():
    res = lab.run_experiment(_FakeOrchestrator("x"), "   ")
    assert res["executed"] is False
    assert "reason" in res


def test_run_experiment_model_produced_no_code(monkeypatch):
    # El modelo respondio prosa sin codigo -> no se ejecuta nada.
    monkeypatch.setattr(lab, "creative_generate",
                        lambda orch, prompt, **kw: "no se me ocurre nada util")
    res = lab.run_experiment(_FakeOrchestrator("x"), "afirmacion sin codigo")
    assert res["executed"] is False
    assert res["code"] == ""
