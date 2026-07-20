"""
tests/test_explorer.py
======================
Tests del modo explorador 70/30 (cognia/reasoning/explorer.py, pieza 4).

allocate es DETERMINISTICO y sin LLM: se prueba el invariante explore_n>=1 y la
suma exacta. explore_exploit usa un orchestrator FAKE (doble de test, NO mock de
produccion): _deepen llama por creative_generate (.infer().text) y _explore_new
por repetition_detector.force_alternatives, asi que el FAKE solo necesita
devolver textos por .infer().
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cognia.reasoning import explorer as ex


# ── allocate ──────────────────────────────────────────────────────────────────

class TestAllocate:
    def test_invariante_explore_siempre_mayor_igual_1(self):
        # La exploracion NUNCA se elimina (regla del GOAL): explore_n>=1 para
        # cualquier total, incluso 0 o 1.
        for total in (0, 1, 2, 3, 5, 10):
            exploit_n, explore_n = ex.allocate(total)
            assert explore_n >= 1, f"explore_n debe ser >=1 para total={total}"

    def test_suma_igual_total_para_total_mayor_igual_1(self):
        for total in (1, 2, 3, 5, 10):
            exploit_n, explore_n = ex.allocate(total)
            assert exploit_n + explore_n == total, f"suma != total para total={total}"

    def test_total_cero_o_uno_devuelve_0_1(self):
        # total<=1 -> (0, 1): al menos exploramos una idea nueva.
        assert ex.allocate(0) == (0, 1)
        assert ex.allocate(1) == (0, 1)

    def test_ratio_07_total_5_da_3_2(self):
        # round(5*0.3)=round(1.5)=2 (redondeo bancario de Python) -> explore_n=2,
        # exploit_n=3. Numero exacto que produce la formula, documentado.
        exploit_n, explore_n = ex.allocate(5, exploit_ratio=0.7)
        assert (exploit_n, explore_n) == (3, 2)

    def test_ratio_07_total_10_da_7_3(self):
        # round(10*0.3)=3 -> (7, 3).
        assert ex.allocate(10, exploit_ratio=0.7) == (7, 3)

    def test_ratio_extremo_no_deja_exploit_negativo(self):
        # ratio 0 -> explore_n capeado a total, exploit_n=0 (nunca negativo).
        exploit_n, explore_n = ex.allocate(5, exploit_ratio=0.0)
        assert exploit_n >= 0
        assert exploit_n + explore_n == 5


# ── doble de test (NO mock de produccion) ─────────────────────────────────────

class _FakeInferResult:
    def __init__(self, text):
        self.text = text


class _FakeOrchestrator:
    """Doble de test: clasifica el prompt para devolver el texto correcto.

    _deepen pide 'Profundiza y refina', _explore_new (via force_alternatives)
    pide 'hipotesis FUNDAMENTALMENTE DISTINTAS'. Asi una sola clase sirve para
    ambas ramas sin acoplarse al orden de llamada.
    """
    def __init__(self, deepen_text, alternatives_text):
        self._deepen = deepen_text
        self._alts = alternatives_text
        self.calls = []

    def infer(self, prompt, max_tokens=None, temperature=None):
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens,
                           "temperature": temperature})
        if "DISTINTAS" in prompt:
            return _FakeInferResult(self._alts)
        return _FakeInferResult(self._deepen)


# ── explore_exploit ───────────────────────────────────────────────────────────

class TestExploreExploit:
    def test_sin_orchestrator_reason(self):
        res = ex.explore_exploit(None, "un problema", ["idea a"])
        assert res["reason"] == "sin backend o problema vacio"
        assert res["exploited"] == []
        assert res["explored"] == []

    def test_problema_vacio_reason(self):
        orch = _FakeOrchestrator("profundizado", "1. nueva idea distinta aqui\n")
        res = ex.explore_exploit(orch, "   ", ["idea a"])
        assert res["reason"] == "sin backend o problema vacio"
        # Cortocircuito: no debe haber tocado el backend.
        assert orch.calls == []

    def test_explota_y_explora(self):
        # 5 conocidas pre-rankeadas; ratio 0.7 -> exploit_n=3, explore_n=2.
        # _deepen devuelve un texto >=15 chars; force_alternatives devuelve dos
        # enfoques genuinamente nuevos (distintos de las conocidas).
        known = [
            "recolectar agua de lluvia en azoteas",
            "sensores de humedad para riego por goteo",
            "plantas nativas de bajo consumo hidrico",
            "reuso de aguas grises tratadas",
            "tarifas escalonadas por consumo",
        ]
        alts = ("1. construir un acueducto subterraneo presurizado\n"
                "2. desalinizar mediante membranas de osmosis inversa\n")
        orch = _FakeOrchestrator(
            "Detalle concreto de como implementar esta idea paso a paso.", alts)
        res = ex.explore_exploit(orch, "abastecer agua urbana", known, total=5)

        assert res["exploit_n"] == 3
        assert res["explore_n"] == 2
        # exploited acotado a <= exploit_n.
        assert len(res["exploited"]) <= res["exploit_n"]
        assert len(res["exploited"]) == 3
        for e in res["exploited"]:
            assert e["base"] in known
            assert e["profundizada"]  # texto no vacio
        # explored trae los enfoques nuevos parseados.
        assert any("acueducto" in idea for idea in res["explored"])
        assert any("osmosis" in idea for idea in res["explored"])

    def test_known_vacio_explora_igual(self):
        # Sin ideas conocidas no hay nada que explotar, pero la exploracion sigue
        # (explore_n>=1 por el invariante de allocate).
        alts = "1. un enfoque completamente nuevo y distinto para esto\n"
        orch = _FakeOrchestrator("no se usa", alts)
        res = ex.explore_exploit(orch, "un problema sin ideas previas", [], total=5)
        assert res["exploited"] == []          # nada que explotar
        assert res["explore_n"] >= 1           # pero explora igual
        assert len(res["explored"]) >= 1

    def test_acota_llamadas_llm(self):
        # Total de llamadas LLM <= total+1 (exploit_n _deepen + 1 force_alternatives).
        known = [f"idea conocida numero {i}" for i in range(5)]
        alts = "1. enfoque radicalmente distinto y nuevo aqui\n"
        orch = _FakeOrchestrator(
            "Profundizacion concreta de la idea con pasos.", alts)
        res = ex.explore_exploit(orch, "problema con muchas ideas", known, total=5)
        # exploit_n=3 -> 3 _deepen + 1 force_alternatives = 4 <= total+1 = 6.
        assert len(orch.calls) <= 5 + 1
        assert len(orch.calls) == res["exploit_n"] + 1
