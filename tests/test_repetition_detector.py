"""
tests/test_repetition_detector.py
=================================
Tests del detector de repeticion (pieza 6, mision creatividad). Todo
DETERMINISTICO y SIN modelo real: similarity/diversity/find_repeats no tocan el
LLM; force_alternatives usa un orchestrator FAKE que devuelve una lista numerada
fija. Verifica el contrato del filtro (solo deja las genuinamente nuevas).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cognia.reasoning import repetition_detector as rd


# ── dobles de test (NO mocks de produccion) ──────────────────────────────────

class _FakeInferResult:
    def __init__(self, text):
        self.text = text


class _FakeOrchestrator:
    """Devuelve textos fijos en orden por cada infer()."""
    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = []

    def infer(self, prompt, max_tokens=None, temperature=None):
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens,
                           "temperature": temperature})
        text = self._texts.pop(0) if self._texts else ""
        return _FakeInferResult(text)


# ── _tokens ──────────────────────────────────────────────────────────────────

class TestTokens:
    def test_strips_accents(self):
        # 'energia' y 'energía' deben colapsar al mismo token.
        assert rd._tokens("energía") == rd._tokens("energia")

    def test_drops_stopwords_and_short(self):
        toks = rd._tokens("el agua de la red")
        # 'el','de','la' son stopwords; 'agua'/'red' quedan (>=3 chars, no stopwords).
        assert "agua" in toks
        assert "red" in toks
        assert "el" not in toks
        assert "de" not in toks
        assert "la" not in toks

    def test_lowercases_and_splits_nonalnum(self):
        toks = rd._tokens("Riego-Urbano, sensores!")
        assert toks == {"riego", "urbano", "sensores"}

    def test_empty_and_none(self):
        assert rd._tokens("") == set()
        assert rd._tokens(None) == set()


# ── similarity ────────────────────────────────────────────────────────────────

class TestSimilarity:
    def test_identical_is_one(self):
        assert rd.similarity("recolectar agua de lluvia",
                             "recolectar agua de lluvia") == 1.0

    def test_disjoint_is_zero(self):
        assert rd.similarity("sensores de humedad",
                             "plantas nativas resistentes") == 0.0

    def test_partial_between_zero_and_one(self):
        # Comparten 'agua' y 'lluvia'; difieren en el resto.
        sim = rd.similarity("recolectar agua de lluvia en azoteas",
                            "juntar agua de lluvia en tanques")
        assert 0.0 < sim < 1.0

    def test_empty_pair_is_zero(self):
        # Union vacia -> 0.0 (no division por cero).
        assert rd.similarity("", "") == 0.0
        assert rd.similarity("de la el", "un una que") == 0.0  # solo stopwords

    def test_symmetric(self):
        a, b = "riego por goteo automatico", "goteo automatico para el riego"
        assert rd.similarity(a, b) == rd.similarity(b, a)


# ── diversity ─────────────────────────────────────────────────────────────────

class TestDiversity:
    def test_empty_or_single_is_one(self):
        assert rd.diversity([]) == 1.0
        assert rd.diversity(["una sola idea"]) == 1.0

    def test_varied_set_is_high(self):
        ideas = [
            "recolectar agua de lluvia en azoteas",
            "sensores de humedad para riego por goteo",
            "plantas nativas de bajo consumo hidrico",
            "reuso de aguas grises tratadas",
        ]
        assert rd.diversity(ideas) > 0.7

    def test_near_identical_set_is_low(self):
        ideas = [
            "recolectar agua de lluvia en azoteas",
            "recolectar agua de lluvia en los techos",
            "recolectar agua de lluvia con canaletas",
        ]
        assert rd.diversity(ideas) < 0.5


# ── find_repeats ──────────────────────────────────────────────────────────────

class TestFindRepeats:
    def test_detects_duplicate_pair(self):
        ideas = [
            "recolectar agua de lluvia en azoteas",   # 0
            "sensores de humedad para riego",          # 1
            "recolectar agua de lluvia en azoteas",   # 2 == 0
        ]
        repeats = rd.find_repeats(ideas, threshold=0.6)
        pares = {(i, j) for i, j, _ in repeats}
        assert (0, 2) in pares
        # El sensor no repite con ninguno.
        assert (0, 1) not in pares
        assert (1, 2) not in pares

    def test_no_repeats_in_varied_set(self):
        ideas = [
            "sensores de humedad para riego",
            "plantas nativas de bajo consumo",
            "reuso de aguas grises tratadas",
        ]
        assert rd.find_repeats(ideas, threshold=0.6) == []

    def test_returns_sim_value(self):
        ideas = ["agua de lluvia limpia", "agua de lluvia limpia"]
        repeats = rd.find_repeats(ideas)
        assert len(repeats) == 1
        i, j, sim = repeats[0]
        assert (i, j) == (0, 1)
        assert sim == 1.0


# ── force_alternatives ────────────────────────────────────────────────────────

class TestForceAlternatives:
    def test_none_orchestrator_returns_empty(self):
        assert rd.force_alternatives(None, "problema", ["idea"]) == []

    def test_empty_problem_returns_empty(self):
        orch = _FakeOrchestrator(["1. algo distinto y nuevo aqui\n"])
        assert rd.force_alternatives(orch, "  ", ["idea"]) == []

    def test_filters_similar_keeps_only_new(self):
        existing = [
            "recolectar agua de lluvia en azoteas",
            "sensores de humedad para riego por goteo",
        ]
        # El modelo devuelve 3 candidatas: la 1 repite 'existing[0]' (se descarta),
        # las otras 2 son enfoques genuinamente nuevos (se conservan).
        gen = ("1. recolectar agua de lluvia en azoteas otra vez\n"
               "2. construir un acueducto subterraneo presurizado\n"
               "3. desalinizar mediante membranas de osmosis inversa\n")
        orch = _FakeOrchestrator([gen])
        nuevas = rd.force_alternatives(orch, "abastecer agua urbana", existing, n=3)
        # Solo 1 llamada LLM (alta temperatura).
        assert len(orch.calls) == 1
        assert orch.calls[0]["temperature"] == 0.97
        assert orch.calls[0]["max_tokens"] == 420
        # La candidata 1 (casi-duplicada de existing[0]) NO debe estar.
        assert not any("azoteas" in nv for nv in nuevas)
        # Las dos genuinamente nuevas SI.
        assert any("acueducto" in nv for nv in nuevas)
        assert any("osmosis" in nv for nv in nuevas)

    def test_all_similar_returns_empty(self):
        existing = ["recolectar agua de lluvia en azoteas"]
        gen = ("1. recolectar agua de lluvia en los techos\n"
               "2. recolectar agua de lluvia desde azoteas con canaletas\n")
        orch = _FakeOrchestrator([gen])
        nuevas = rd.force_alternatives(orch, "agua urbana", existing, n=2)
        assert nuevas == []

    def test_no_two_near_duplicate_new_ideas(self):
        # Si el modelo devuelve dos alternativas casi-iguales entre si, solo entra
        # una (dedup contra las nuevas ya aceptadas).
        existing = ["sensores de humedad para riego"]
        gen = ("1. construir un acueducto subterraneo presurizado\n"
               "2. construir un acueducto subterraneo a presion\n")
        orch = _FakeOrchestrator([gen])
        nuevas = rd.force_alternatives(orch, "agua urbana", existing, n=2)
        assert len(nuevas) == 1
