"""Regresion exp021/cycle34: _spec_args() arma --spec-type ngram-mod por defecto,
es desactivable, y PROHIBE draft-* (un draft model separado en CPU bandwidth-bound
mide 0.37x en habla — exp021). Falla sin el fix (la funcion no existia)."""
from node.llama_backend import _spec_args


def test_default_es_ngram_mod(monkeypatch):
    monkeypatch.delenv("COGNIA_SPEC_TYPE", raising=False)
    assert _spec_args() == ["--spec-type", "ngram-mod"]


def test_none_desactiva(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "none")
    assert _spec_args() == []


def test_override_ngram_simple(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "ngram-simple")
    assert _spec_args() == ["--spec-type", "ngram-simple"]


def test_draft_separado_prohibido(monkeypatch):
    # draft-* compite por banda/nucleos en CPU (exp021: 0.37x en habla) -> nunca al server
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "draft-simple")
    assert _spec_args() == []
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "draft-eagle3")
    assert _spec_args() == []


def test_basura_ignorada(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "evil; rm -rf /")
    assert _spec_args() == []
