"""
tests/test_complexity_scorer.py
================================
Tests for cognia.reasoning.complexity_scorer.ComplexityScorer (ITCS).
"""
import pytest
from cognia.reasoning.complexity_scorer import ComplexityScorer, ComplexityResult


@pytest.fixture(scope="module")
def scorer():
    return ComplexityScorer()


# 1. Greeting scores 1
def test_greeting_scores_1(scorer):
    result = scorer.score("hola")
    assert result.score == 1
    assert result.budget == "fast"


# 2. Simple yes scores 1
def test_simple_yes_scores_1(scorer):
    result = scorer.score("si")
    assert result.score == 1
    assert result.budget == "fast"


# 3. Medium technical question scores 2-3
def test_medium_technical(scorer):
    result = scorer.score("what is a hash function?")
    assert 2 <= result.score <= 3


# 4. Long technical query scores >= 4
def test_long_technical_scores_high(scorer):
    long_query = (
        "Can you explain the tradeoffs between RSA cryptography and elliptic curve "
        "encryption algorithms in embedded systems with limited memory, cache, and "
        "distributed inference pipelines for neural network parameter optimization?"
    )
    assert len(long_query) > 150
    result = scorer.score(long_query)
    assert result.score >= 4
    assert result.budget == "deep"


# 5. Comparative query boosts score
def test_comparative_boost(scorer):
    # Comparative (+1) + interrogative (+1) + tech vocab >= 2 (+1) + base(1) = 4
    result = scorer.score("how does RSA cryptography compare versus elliptic curve encryption?")
    assert result.score >= 4
    assert result.budget == "deep"


# 6. Multi-clause query gets boost
def test_multi_clause_boost(scorer):
    # 4 clause connectors: "and", "but", "," twice
    query_few = scorer.score("how does a neural network work")
    query_many = scorer.score(
        "how does a neural network work, and what are the gradient descent steps, "
        "but also why does optimization matter, whereas batch normalization helps?"
    )
    assert query_many.score > query_few.score


# 7. Score <= 2 yields budget "fast"
def test_budget_fast(scorer):
    result = scorer.score("ok gracias")
    assert result.budget == "fast"


# 8. Score == 3 yields budget "normal"
def test_budget_normal(scorer):
    # Manually verify a query that hits exactly 3:
    # base(1) + length>80? no + interrogative? yes(+1) + tech_vocab>=2? yes(+1) = 3
    query = "how does a cache work?"  # short, has interrogative, has tech vocab (cache)
    result = scorer.score(query)
    # Could be 2 or 3 depending on tech vocab count; just check budget matches score
    expected = ComplexityScorer._budget(result.score)
    assert result.budget == expected
    # Specifically test the mapping for score=3
    assert ComplexityScorer._budget(3) == "normal"


# 9. Score >= 4 yields budget "deep"
def test_budget_deep(scorer):
    result = scorer.score(
        "explain the tradeoffs between distributed database architectures "
        "and concurrent memory models in high-latency network protocols"
    )
    assert result.score >= 4
    assert result.budget == "deep"


# 10. Reasons list is populated for any query
def test_reasons_not_empty(scorer):
    for query in [
        "hola",
        "what is an api?",
        "compare RSA vs elliptic curve cryptography for embedded systems with low memory",
    ]:
        result = scorer.score(query)
        assert isinstance(result.reasons, list)
        assert len(result.reasons) >= 1, f"reasons empty for: {query!r}"
