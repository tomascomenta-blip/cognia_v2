# -*- coding: utf-8 -*-
"""Mesa redonda entre modelos (deliberation.py): oráculo duro, keep-best,
early-exit, sin-oráculo. Ejecución REAL en sandbox (run_task_tests), pero
con gen_fns FAKE: ningún llama-server."""
from cognia.agent.deliberation import (build_repair_prompt, deliberate,
                                       execution_feedback, feedback_score)


def _extract(raw):
    # extractor mínimo: bloque ```python ...```
    import re
    m = re.search(r"```python\n(.*?)```", raw, re.DOTALL)
    return m.group(1) if m else raw


ASSERTS = ["assert doble(2) == 4", "assert doble(-3) == -6"]
CODE_MALO = "def doble(n):\n    return n + n + 1\n"
CODE_BUENO = "def doble(n):\n    return n * 2\n"


def test_execution_feedback_reporta_error_real():
    fb = execution_feedback(CODE_MALO, ASSERTS, "doble")
    assert feedback_score(fb) == (0, 2)
    assert all(f["error_type"] == "assert" for f in fb)
    fb2 = execution_feedback(CODE_BUENO, ASSERTS, "doble")
    assert feedback_score(fb2) == (2, 2)


def test_repair_prompt_incluye_fallas_y_codigo():
    fb = execution_feedback(CODE_MALO, ASSERTS, "doble")
    p = build_repair_prompt("Haz doble(n)", "doble", CODE_MALO, fb)
    assert "FALLA" in p and "doble(2) == 4" in p
    assert "return n + n + 1" in p
    assert "```python" in p


def test_sin_oraculo_no_delibera():
    llamado = {"c": 0}

    def gen(prompt, temperature=0.0, seed=None):
        llamado["c"] += 1
        return ""

    out = deliberate("t", "doble", [("m", gen)], _extract, [],
                     initial_code=CODE_MALO)
    assert out["motivo"] == "sin_oraculo"
    assert out["code"] == CODE_MALO
    assert llamado["c"] == 0


def test_inicial_perfecto_no_gasta_computo():
    llamado = {"c": 0}

    def gen(prompt, temperature=0.0, seed=None):
        llamado["c"] += 1
        return ""

    out = deliberate("t", "doble", [("m", gen)], _extract, ASSERTS,
                     initial_code=CODE_BUENO)
    assert out["motivo"] == "inicial_perfecto"
    assert llamado["c"] == 0


def test_mesa_redonda_repara_con_feedback_y_corta():
    # El "modelo B" repara usando el reporte de fallas del prompt.
    def modelo_b(prompt, temperature=0.0, seed=None):
        assert "FALLA" in prompt          # recibio feedback real
        return "```python\n" + CODE_BUENO + "```"

    out = deliberate("Haz doble(n)", "doble", [("b", modelo_b)], _extract,
                     ASSERTS, initial_code=CODE_MALO, rounds=2)
    assert out["motivo"] == "tests_perfectos"
    assert out["mejorado"] is True
    assert out["score"] == 2 and out["total"] == 2
    assert out["rounds_run"] == 1         # early-exit: no segunda ronda


def test_keep_best_nunca_empeora():
    # Participante que devuelve algo PEOR (sin la funcion): el code inicial queda.
    def peor(prompt, temperature=0.0, seed=None):
        return "```python\ndef otra(n):\n    return 0\n```"

    parcial = "def doble(n):\n    return n * 2 if n > 0 else 0\n"  # pasa 1/2
    out = deliberate("t", "doble", [("p", peor)], _extract, ASSERTS,
                     initial_code=parcial, rounds=1)
    assert out["code"] == parcial
    assert out["score"] == 1 and out["mejorado"] is False


def test_alterna_participantes_en_orden():
    orden = []

    def gen_a(prompt, temperature=0.0, seed=None):
        orden.append("a")
        return ""

    def gen_b(prompt, temperature=0.0, seed=None):
        orden.append("b")
        return ""

    deliberate("t", "doble", [("a", gen_a), ("b", gen_b)], _extract,
               ASSERTS, initial_code=CODE_MALO, rounds=2)
    assert orden == ["a", "b", "a", "b"]


def test_excepcion_de_un_participante_no_rompe_la_mesa():
    def explota(prompt, temperature=0.0, seed=None):
        raise RuntimeError("server caido")

    def repara(prompt, temperature=0.0, seed=None):
        return "```python\n" + CODE_BUENO + "```"

    out = deliberate("t", "doble", [("x", explota), ("ok", repara)],
                     _extract, ASSERTS, initial_code=CODE_MALO, rounds=1)
    assert out["motivo"] == "tests_perfectos"
    assert any("error" in h for h in out["historial"])
