"""
tests/test_llama_backend.py
Tests for node/llama_backend.py — LlamaBackend public facade.

All tests use mocking; llama.cpp is optional and not required in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_backend(impl):
    """Return a LlamaBackend wrapping a mock impl."""
    from node.llama_backend import LlamaBackend
    return LlamaBackend(impl)


# ---------------------------------------------------------------------------
# try_load: returns None when no GGUF found
# ---------------------------------------------------------------------------

class TestTryLoadNoGguf:
    def test_returns_none_when_no_gguf(self):
        """try_load returns None immediately if _find_gguf returns None."""
        from node.llama_backend import LlamaBackend
        with patch("node.llama_backend._find_gguf", return_value=None):
            result = LlamaBackend.try_load()
        assert result is None


# ---------------------------------------------------------------------------
# try_load: returns None when GGUF exists but no runtime available
# ---------------------------------------------------------------------------

class TestTryLoadNoRuntime:
    def test_returns_none_when_neither_backend_available(self, tmp_path):
        """try_load returns None when GGUF found but both backends unavailable."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend
        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=False),
            patch("node.llama_backend._LlamaServerBackend.available", return_value=False),
        ):
            result = LlamaBackend.try_load()
        assert result is None

    def test_returns_none_when_cpp_init_raises_and_server_unavailable(self, tmp_path):
        """try_load returns None when llama-cpp-python is present but init errors and server absent."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend
        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=True),
            patch("node.llama_backend._LlamaCppBackend.__init__", side_effect=RuntimeError("boom")),
            patch("node.llama_backend._LlamaServerBackend.available", return_value=False),
        ):
            result = LlamaBackend.try_load()
        assert result is None

    def test_returns_none_when_server_init_raises(self, tmp_path):
        """try_load returns None when llama-server binary exists but server startup fails."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend
        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=False),
            patch("node.llama_backend._LlamaServerBackend.available", return_value=True),
            patch("node.llama_backend._LlamaServerBackend.__init__", side_effect=FileNotFoundError("no binary")),
        ):
            result = LlamaBackend.try_load()
        assert result is None


# ---------------------------------------------------------------------------
# try_load: returns LlamaBackend when a backend succeeds
# ---------------------------------------------------------------------------

class TestTryLoadSuccess:
    def test_returns_backend_via_cpp_python(self, tmp_path):
        """try_load returns a LlamaBackend wrapping _LlamaCppBackend when available."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend, _LlamaCppBackend
        mock_impl = MagicMock(spec=_LlamaCppBackend)

        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=True),
            patch("node.llama_backend._LlamaCppBackend.__init__", return_value=None),
            patch.object(LlamaBackend, "__init__", lambda self, impl: setattr(self, "_impl", impl) or None),
        ):
            # Patch the class so instantiation returns our mock
            with patch("node.llama_backend._LlamaCppBackend", return_value=mock_impl) as MockCpp:
                MockCpp.available.return_value = True
                result = LlamaBackend.try_load()
        assert result is not None
        assert isinstance(result, LlamaBackend)

    def test_returns_backend_via_server(self, tmp_path):
        """try_load returns a LlamaBackend wrapping _LlamaServerBackend when cpp unavailable."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend, _LlamaServerBackend
        mock_impl = MagicMock(spec=_LlamaServerBackend)

        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=False),
        ):
            with patch("node.llama_backend._LlamaServerBackend") as MockServer:
                MockServer.available.return_value = True
                MockServer.return_value = mock_impl
                result = LlamaBackend.try_load()

        assert result is not None
        assert isinstance(result, LlamaBackend)


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_generate_returns_string_on_success(self):
        """generate() returns a string when impl.generate succeeds."""
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "Hello world"

        backend = _make_backend(mock_impl)
        result = backend.generate("Say hi", max_tokens=16, temperature=0.5)

        assert result == "Hello world"
        mock_impl.generate.assert_called_once_with("Say hi", 16, 0.5)

    def test_generate_returns_none_on_impl_exception(self):
        """generate() returns None when impl.generate raises (impl handles internally)."""
        mock_impl = MagicMock()
        mock_impl.generate.return_value = None  # impl already swallows and returns None

        backend = _make_backend(mock_impl)
        result = backend.generate("trigger error")

        assert result is None

    def test_generate_passes_default_params(self):
        """generate() passes correct defaults when called without kwargs."""
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "ok"

        backend = _make_backend(mock_impl)
        backend.generate("prompt")

        mock_impl.generate.assert_called_once_with("prompt", 256, 0.7)


# ---------------------------------------------------------------------------
# generate_long()
# ---------------------------------------------------------------------------

class _FakeLongImpl:
    """Scripted impl: each round pops (text, tokens, stop_reason)."""

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.last_tokens_predicted: Optional[int] = None
        self.last_stop_reason: Optional[str] = None
        self.prompts: list = []

    def generate(self, prompt, max_tokens=256, temperature=0.7):
        self.prompts.append((prompt, max_tokens))
        if not self._rounds:
            return None
        text, toks, reason = self._rounds.pop(0)
        self.last_tokens_predicted = toks
        self.last_stop_reason = reason
        return text


class TestGenerateLong:
    def test_continues_on_limit_until_eos(self):
        """Rounds cut by 'limit' are continued with prompt + accumulated text."""
        impl = _FakeLongImpl([
            ("AAA ", 100, "limit"),
            ("BBB ", 100, "limit"),
            ("CCC.", 50,  "eos"),
        ])
        backend = _make_backend(impl)
        result = backend.generate_long("P: ", max_total_tokens=1000, chunk_tokens=100)

        assert result["text"] == "AAA BBB CCC."
        assert result["total_tokens"] == 250
        assert result["stop_reason"] == "eos"
        assert result["rounds"] == 3
        # Continuation prompt must carry the accumulated text (KV prefix reuse)
        assert impl.prompts[1][0] == "P: AAA "
        assert impl.prompts[2][0] == "P: AAA BBB "

    def test_stops_at_max_total_tokens(self):
        """Loop never exceeds max_total_tokens; last chunk asks the remainder."""
        impl = _FakeLongImpl([
            ("X" * 40, 100, "limit"),
            ("Y" * 40, 100, "limit"),
            ("Z" * 20, 50,  "limit"),
        ])
        backend = _make_backend(impl)
        result = backend.generate_long("P", max_total_tokens=250, chunk_tokens=100)

        assert result["total_tokens"] == 250
        assert result["rounds"] == 3
        assert result["stop_reason"] == "limit"
        # Third round must only ask the 50 remaining tokens
        assert impl.prompts[2][1] == 50

    def test_natural_stop_first_round(self):
        """eos on the first round -> single round, no continuation."""
        impl = _FakeLongImpl([("Hola.", 12, "eos")])
        backend = _make_backend(impl)
        result = backend.generate_long("P", max_total_tokens=5000, chunk_tokens=2048)

        assert result == {"text": "Hola.", "total_tokens": 12,
                          "stop_reason": "eos", "rounds": 1}

    def test_returns_none_when_first_round_fails(self):
        """First generate() returning None -> None (same contract as generate)."""
        impl = _FakeLongImpl([])   # no scripted rounds -> generate returns None
        backend = _make_backend(impl)
        assert backend.generate_long("P") is None

    def test_partial_result_on_mid_loop_failure(self):
        """Failure after a successful round -> partial text with stop_reason error."""
        impl = _FakeLongImpl([("AAA", 100, "limit")])
        backend = _make_backend(impl)
        result = backend.generate_long("P", max_total_tokens=1000, chunk_tokens=100)

        assert result["text"] == "AAA"
        assert result["stop_reason"] == "error"
        assert result["rounds"] == 1

    def test_on_chunk_callback_invoked_per_round(self):
        """on_chunk recibe tambien el TEXTO del chunk (5to arg, para escritura
        incremental de /largo -- cambio de contrato, unico caller real es cli.py)."""
        calls = []
        impl = _FakeLongImpl([
            ("A", 100, "limit"),
            ("B", 60,  "eos"),
        ])
        backend = _make_backend(impl)
        backend.generate_long(
            "P", max_total_tokens=500, chunk_tokens=100,
            on_chunk=lambda r, ct, tt, sr, txt: calls.append((r, ct, tt, sr, txt)))

        assert calls == [(1, 100, 100, "limit", "A"), (2, 60, 160, "eos", "B")]

    def test_resume_text_default_none_preserves_behavior(self):
        """resume_text=None (default) -> identico al comportamiento previo (regresion)."""
        impl = _FakeLongImpl([
            ("AAA ", 100, "limit"),
            ("BBB.", 50,  "eos"),
        ])
        backend = _make_backend(impl)
        result = backend.generate_long("P: ", max_total_tokens=1000, chunk_tokens=100)

        assert result["text"] == "AAA BBB."
        assert impl.prompts[1][0] == "P: AAA "   # sin cola previa, igual que siempre

    def test_resume_text_used_as_reanchor_context(self):
        """resume_text antepone una cola YA ESCRITA (p.ej. /largo --continuar) como
        contexto de re-anclaje; NO se re-emite en el texto devuelto (el caller ya la
        tiene persistida en el archivo)."""
        impl = _FakeLongImpl([("nuevo texto.", 20, "eos")])
        backend = _make_backend(impl)
        result = backend.generate_long("P: ", max_total_tokens=1000, chunk_tokens=100,
                                       resume_text="cola previa ")

        assert impl.prompts[0][0] == "P: cola previa "
        assert result["text"] == "nuevo texto."   # solo lo NUEVO, no la cola

    def test_ctx_guard_caps_resent_prefix(self):
        """FASE 1b: al acercarse a _CTX_SIZE deja de reenviar TODO y manda
        prompt + cola; el prefill queda acotado y el output sigue completo."""
        import node.llama_backend as lb
        impl = _FakeLongImpl([("X" * 50, 50, "limit")] * 5 + [("END", 3, "eos")])
        backend = _make_backend(impl)
        with patch.object(lb, "_CTX_SIZE", 100):   # ctx chico para disparar la guarda
            result = backend.generate_long("P:", max_total_tokens=10000, chunk_tokens=10)

        # Output completo: la guarda recorta el INPUT al modelo, nunca el resultado
        assert result["text"] == "X" * 250 + "END"
        assert result["rounds"] == 6
        sent = [p for (p, _mt) in impl.prompts]
        # Sin guarda la ultima ronda reenviaria prompt+250 chars; con guarda <= ~prompt+budget
        # budget = min(0.75*100, 100-10-64)=26 tok -> ~104 chars + prompt(2) + holgura
        assert max(len(s) for s in sent) <= 2 + 104 + 4
        assert sent[-1].startswith("P:")   # el prompt original se conserva siempre


# ---------------------------------------------------------------------------
# generate_hierarchical()  (FASE 7a)
# ---------------------------------------------------------------------------

class TestGenerateHierarchical:
    def test_outline_then_sections_assembled_with_bounded_prefill(self):
        """outline -> N secciones con prompt fresco. El output trae todo el texto, pero el
        prefill de cada seccion solo incluye un RESUMEN corto de la previa (no el texto
        completo) -> generacion cuasi-infinita con ctx fijo."""
        impl = _FakeLongImpl([
            ("1. Alpha\n2. Beta\n3. Gamma", 12, "eos"),  # outline
            ("X" * 500, 120, "eos"),                       # seccion Alpha
            ("Y" * 500, 120, "eos"),                       # seccion Beta
            ("Z" * 100, 30,  "eos"),                       # seccion Gamma
        ])
        backend = _make_backend(impl)
        result = backend.generate_hierarchical("Escribe sobre asyncio",
                                               target_tokens=900, n_sections=3)

        assert result["outline"] == ["Alpha", "Beta", "Gamma"]
        assert result["sections"] == 3
        assert result["total_tokens"] == 270
        # Output completo: las 3 secciones con su texto integro
        for header, body in [("## Alpha", "X" * 500), ("## Beta", "Y" * 500),
                             ("## Gamma", "Z" * 100)]:
            assert header in result["text"] and body in result["text"]

        prompts = [p for (p, _mt) in impl.prompts]
        assert len(prompts) == 4   # 1 outline + 3 secciones
        assert "Escribe SOLO la seccion 1: Alpha" in prompts[1]
        # Prefill acotado: el prompt de Beta trae el RESUMEN de Alpha (200 chars), NO los 500
        assert ("X" * 200) in prompts[2] and ("X" * 500) not in prompts[2]
        assert ("Y" * 200) in prompts[3] and ("Y" * 500) not in prompts[3]

    def test_parse_outline_handles_inline_numbered_markers(self):
        """El 3B a veces no respeta 'uno por linea' y mete '(1. ... 2. ...' inline;
        _parse_outline debe extraer >=2 secciones igual."""
        from node.llama_backend import LlamaBackend
        text = "Intro (1. Definicion de asyncio 2. Funcionalidades 3. Ejemplo de uso"
        items = LlamaBackend._parse_outline(text, 5)
        assert len(items) >= 2
        assert all(len(it) <= 120 for it in items)

    def test_unparseable_outline_falls_back_to_single_section(self):
        """Si el outline no se puede parsear en items, genera una sola seccion (=prompt)."""
        impl = _FakeLongImpl([
            ("", 1, "eos"),                    # outline vacio -> fallback a [prompt]
            ("contenido unico", 40, "eos"),
        ])
        backend = _make_backend(impl)
        result = backend.generate_hierarchical("tema X", target_tokens=300, n_sections=3)
        assert result["sections"] == 1
        assert "contenido unico" in result["text"]

    def test_on_outline_called_once_before_any_section(self):
        """on_outline(sections) se llama UNA vez, apenas se parsea el esquema -- permite
        persistir el plan completo (checkpoint de /largo) antes de la 1ra seccion."""
        impl = _FakeLongImpl([
            ("1. Alpha\n2. Beta", 12, "eos"),
            ("texto alpha", 40, "eos"),
            ("texto beta", 40, "eos"),
        ])
        backend = _make_backend(impl)
        outlines_seen = []
        backend.generate_hierarchical(
            "tema X", target_tokens=300, n_sections=2,
            on_outline=lambda secs: outlines_seen.append(list(secs)))
        assert outlines_seen == [["Alpha", "Beta"]]

    def test_on_section_receives_text_and_stop_reason(self):
        """on_section trae ademas el TEXTO de la seccion y su stop_reason interno
        (para escritura incremental + deteccion de corte por presupuesto). Beta pega
        EXACTO en su per_section cap (256, el piso de generate_hierarchical) con
        stop_reason='limit' -> el generate_long interno de esa seccion cierra en 1
        ronda sin pedir mas (total_tokens == max_total_tokens)."""
        impl = _FakeLongImpl([
            ("1. Alpha\n2. Beta", 12, "eos"),
            ("texto alpha", 40, "eos"),
            ("texto beta", 256, "limit"),
        ])
        backend = _make_backend(impl)
        calls = []
        backend.generate_hierarchical(
            "tema X", target_tokens=512, n_sections=2,
            on_section=lambda idx, tot, tit, toks, txt, sr: calls.append((idx, tot, tit, toks, txt, sr)))
        assert calls == [
            (1, 2, "Alpha", 40, "texto alpha", "eos"),
            (2, 2, "Beta",  256, "texto beta", "limit"),
        ]


# ---------------------------------------------------------------------------
# _LlamaCppBackend: stop_reason / token count (regresion de generate_long in-process)
# ---------------------------------------------------------------------------

class _FakeCppModel:
    """Stub minimo de llama-cpp-python __call__: rondas (text, completion_tokens, finish_reason)."""

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls: list = []

    def __call__(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        text, toks, fr = self._rounds.pop(0)
        return {"choices": [{"text": text, "finish_reason": fr}],
                "usage": {"completion_tokens": toks}}


def _make_cpp_backend(rounds):
    """_LlamaCppBackend sin tocar llama_cpp real: bypass __init__ + fake _model."""
    from node.llama_backend import _LlamaCppBackend
    be = object.__new__(_LlamaCppBackend)
    be._gguf_path = None
    be.last_tokens_predicted = None
    be.last_stop_reason = None
    be._model = _FakeCppModel(rounds)
    return be


class TestLlamaCppBackendStopReason:
    def test_generate_sets_token_count_and_maps_length_to_limit(self):
        be = _make_cpp_backend([("hola", 7, "length")])
        out = be.generate("P", max_tokens=100, temperature=0.0)
        assert out == "hola"
        assert be.last_tokens_predicted == 7
        assert be.last_stop_reason == "limit"
        # Debe enviar los stop strings de fin de turno, igual que el server backend
        assert be._model.calls[0][1].get("stop") == ["<|im_end|>", "<|endoftext|>"]

    def test_generate_maps_stop_to_eos(self):
        be = _make_cpp_backend([("fin.", 3, "stop")])
        be.generate("P")
        assert be.last_stop_reason == "eos"

    def test_generate_long_continues_in_process(self):
        """Regresion: in-process debe continuar mas alla de la ronda 1.
        Antes last_stop_reason era None -> generate_long cortaba tras 1 ronda."""
        from node.llama_backend import LlamaBackend
        impl = _make_cpp_backend([
            ("AAA ", 100, "length"),
            ("BBB ", 100, "length"),
            ("CCC.", 50,  "stop"),
        ])
        result = LlamaBackend(impl).generate_long("P: ", max_total_tokens=1000, chunk_tokens=100)
        assert result["rounds"] == 3
        assert result["text"] == "AAA BBB CCC."
        assert result["stop_reason"] == "eos"
        assert result["total_tokens"] == 250


# ---------------------------------------------------------------------------
# stream_generate()
# ---------------------------------------------------------------------------

class TestStreamGenerate:
    def test_stream_generate_yields_tokens_from_impl(self):
        """stream_generate yields tokens when impl has stream_generate."""
        mock_impl = MagicMock()
        mock_impl.stream_generate.return_value = iter(["Hello", " ", "world"])

        backend = _make_backend(mock_impl)
        tokens = list(backend.stream_generate("hi", max_tokens=8, temperature=0.3))

        assert tokens == ["Hello", " ", "world"]
        mock_impl.stream_generate.assert_called_once_with("hi", 8, 0.3)

    def test_stream_generate_falls_back_to_generate_when_no_stream(self):
        """stream_generate yields single result when impl lacks stream_generate."""
        mock_impl = MagicMock(spec=["generate"])  # no stream_generate attr
        mock_impl.generate.return_value = "full response"

        backend = _make_backend(mock_impl)
        tokens = list(backend.stream_generate("hi"))

        assert tokens == ["full response"]

    def test_stream_generate_yields_nothing_when_generate_returns_none(self):
        """stream_generate yields nothing when impl.generate returns None."""
        mock_impl = MagicMock(spec=["generate"])
        mock_impl.generate.return_value = None

        backend = _make_backend(mock_impl)
        tokens = list(backend.stream_generate("hi"))

        assert tokens == []

    def test_stream_generate_empty_from_impl(self):
        """stream_generate yields nothing when impl.stream_generate is exhausted immediately."""
        mock_impl = MagicMock()
        mock_impl.stream_generate.return_value = iter([])

        backend = _make_backend(mock_impl)
        tokens = list(backend.stream_generate("hi"))

        assert tokens == []


# ---------------------------------------------------------------------------
# stream_chat()
# ---------------------------------------------------------------------------

class TestStreamChat:
    def test_stream_chat_yields_tokens_from_impl(self):
        """stream_chat delegates to impl.stream_chat when available."""
        mock_impl = MagicMock()
        mock_impl.stream_chat.return_value = iter(["A", "B"])

        backend = _make_backend(mock_impl)
        messages = [{"role": "user", "content": "Hello"}]
        tokens = list(backend.stream_chat(messages, max_tokens=64, temperature=0.5))

        assert tokens == ["A", "B"]
        mock_impl.stream_chat.assert_called_once_with(messages, 64, 0.5)

    def test_stream_chat_falls_back_to_stream_generate_when_no_method(self):
        """stream_chat falls back to stream_generate when impl lacks stream_chat."""
        mock_impl = MagicMock(spec=["generate"])
        mock_impl.generate.return_value = "fallback"

        backend = _make_backend(mock_impl)
        messages = [{"role": "user", "content": "hi"}]
        tokens = list(backend.stream_chat(messages))

        assert tokens == ["fallback"]


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

class TestStop:
    def test_stop_calls_impl_stop_when_available(self):
        mock_impl = MagicMock()
        backend = _make_backend(mock_impl)
        backend.stop()
        mock_impl.stop.assert_called_once()

    def test_stop_is_noop_when_impl_lacks_stop(self):
        mock_impl = MagicMock(spec=["generate"])
        backend = _make_backend(mock_impl)
        backend.stop()  # must not raise


# ---------------------------------------------------------------------------
# _stop_reason()
# ---------------------------------------------------------------------------

class TestStopReason:
    """Dicts mirror REAL b9391 /completion responses captured on 2026-06-10."""

    def test_limit(self):
        """n_predict cap reached -> 'limit' (real b9391 response shape)."""
        from node.llama_backend import _stop_reason
        data = {"content": "The ocean", "stop": True, "stop_type": "limit",
                "stopping_word": "", "tokens_predicted": 8, "truncated": False}
        assert _stop_reason(data) == "limit"

    def test_eos(self):
        """Natural end (eos token) -> 'eos'."""
        from node.llama_backend import _stop_reason
        data = {"content": "Hi! How can I assist you today?", "stop": True,
                "stop_type": "eos", "stopping_word": "", "tokens_predicted": 10}
        assert _stop_reason(data) == "eos"

    def test_word(self):
        """Stop string hit -> 'word'."""
        from node.llama_backend import _stop_reason
        data = {"content": "done", "stop": True, "stop_type": "word",
                "stopping_word": "<|im_end|>", "tokens_predicted": 5}
        assert _stop_reason(data) == "word"

    def test_none_when_no_fields(self):
        """Empty/unknown dict -> None (e.g. mid-stream chunk)."""
        from node.llama_backend import _stop_reason
        assert _stop_reason({}) is None
        assert _stop_reason({"content": "tok", "stop": False}) is None
        assert _stop_reason({"stop_type": "none"}) is None

    def test_legacy_boolean_flags(self):
        """Older llama-server builds report stopped_* booleans."""
        from node.llama_backend import _stop_reason
        assert _stop_reason({"stopped_eos": True}) == "eos"
        assert _stop_reason({"stopped_limit": True}) == "limit"
        assert _stop_reason({"stopped_word": True}) == "word"

    def test_openai_chat_finish_reason(self):
        """/v1/chat/completions final chunk: finish_reason length/stop (real b9391 shape)."""
        from node.llama_backend import _stop_reason
        length_chunk = {"choices": [{"finish_reason": "length", "index": 0, "delta": {}}],
                        "object": "chat.completion.chunk",
                        "timings": {"predicted_n": 8}}
        stop_chunk = {"choices": [{"finish_reason": "stop", "index": 0, "delta": {}}],
                      "object": "chat.completion.chunk"}
        mid_chunk = {"choices": [{"finish_reason": None, "index": 0,
                                  "delta": {"content": "tok"}}]}
        assert _stop_reason(length_chunk) == "limit"
        assert _stop_reason(stop_chunk) == "eos"
        assert _stop_reason(mid_chunk) is None


# ---------------------------------------------------------------------------
# last_stop_reason facade property
# ---------------------------------------------------------------------------

class TestLastStopReason:
    def test_facade_exposes_impl_attribute(self):
        mock_impl = MagicMock()
        mock_impl.last_stop_reason = "limit"
        backend = _make_backend(mock_impl)
        assert backend.last_stop_reason == "limit"

    def test_facade_returns_none_when_impl_lacks_attribute(self):
        mock_impl = MagicMock(spec=["generate"])
        backend = _make_backend(mock_impl)
        assert backend.last_stop_reason is None


# ---------------------------------------------------------------------------
# _sampling_payload() — sampling params solo cuando no son None
# ---------------------------------------------------------------------------

class TestSamplingPayload:
    def test_empty_when_all_none(self):
        from node.llama_backend import _sampling_payload
        assert _sampling_payload() == {}

    def test_includes_only_non_none(self):
        from node.llama_backend import _sampling_payload
        assert _sampling_payload(seed=42) == {"seed": 42}
        assert _sampling_payload(top_p=0.9, top_k=40) == {"top_p": 0.9, "top_k": 40}

    def test_all_params(self):
        from node.llama_backend import _sampling_payload
        out = _sampling_payload(top_p=0.95, top_k=20, min_p=0.05,
                                repeat_penalty=1.1, seed=7)
        assert out == {"top_p": 0.95, "top_k": 20, "min_p": 0.05,
                       "repeat_penalty": 1.1, "seed": 7}

    def test_zero_values_are_kept(self):
        """0 / 0.0 son valores validos (p.ej. seed=0), no se filtran."""
        from node.llama_backend import _sampling_payload
        assert _sampling_payload(seed=0, top_k=0) == {"seed": 0, "top_k": 0}


# ---------------------------------------------------------------------------
# _LlamaServerBackend payloads — fakes, sin server real
# ---------------------------------------------------------------------------

class _FakeResp:
    """Respuesta HTTP fake con read() incremental (compatible con el loop SSE)."""

    def __init__(self, payload: bytes):
        self._buf = payload

    def read(self, n=-1):
        if n is None or n < 0:
            out, self._buf = self._buf, b""
        else:
            out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeUrlReq:
    """Reemplazo de urllib.request: captura los Request y sirve bytes fijos."""

    def __init__(self, resp_bytes: bytes):
        self.requests = []
        self._resp_bytes = resp_bytes

    def Request(self, url, data=None, headers=None):
        self.requests.append({"url": url, "data": data, "headers": headers})
        return ("REQ", url)

    def urlopen(self, req, timeout=None):
        return _FakeResp(self._resp_bytes)


def _make_server_backend(resp_bytes: bytes):
    """_LlamaServerBackend sin __init__ (no arranca proceso ni pinguea)."""
    import json as _json
    from node.llama_backend import _LlamaServerBackend
    b = object.__new__(_LlamaServerBackend)
    b._port = 8088
    b._base = "http://127.0.0.1:8088"
    b._proc = None
    b._json = _json
    b._urlreq = _FakeUrlReq(resp_bytes)
    b.last_tokens_predicted = None
    b.last_stop_reason = None
    return b


_COMPLETION_RESP = (b'{"content": "ok", "stop": true, "stop_type": "eos", '
                    b'"tokens_predicted": 2}')
_SSE_COMPLETION_RESP = (b'data: {"content": "ok", "stop": true, '
                        b'"stop_type": "eos", "tokens_predicted": 2}\n')
_SSE_CHAT_RESP = (b'data: {"choices": [{"delta": {"content": "ok"}, '
                  b'"finish_reason": "stop", "index": 0}]}\n'
                  b'data: [DONE]\n')


def _sent_payload(backend) -> dict:
    import json as _json
    return _json.loads(backend._urlreq.requests[0]["data"])


_SAMPLING_KEYS = ("top_p", "top_k", "min_p", "repeat_penalty", "seed")


class TestServerPayloadSampling:
    """Los 3 endpoints incluyen sampling params SOLO cuando no son None."""

    def test_generate_default_payload_has_no_sampling_keys(self):
        b = _make_server_backend(_COMPLETION_RESP)
        b.generate("hola", max_tokens=8)
        payload = _sent_payload(b)
        for key in _SAMPLING_KEYS:
            assert key not in payload
        assert payload["n_predict"] == 8

    def test_generate_includes_given_sampling_params(self):
        b = _make_server_backend(_COMPLETION_RESP)
        b.generate("hola", max_tokens=8, seed=42, top_p=0.9)
        payload = _sent_payload(b)
        assert payload["seed"] == 42
        assert payload["top_p"] == 0.9
        assert "top_k" not in payload
        assert "min_p" not in payload
        assert "repeat_penalty" not in payload

    def test_stream_generate_default_payload_has_no_sampling_keys(self):
        b = _make_server_backend(_SSE_COMPLETION_RESP)
        list(b.stream_generate("hola", max_tokens=8))
        payload = _sent_payload(b)
        for key in _SAMPLING_KEYS:
            assert key not in payload
        assert payload["stream"] is True

    def test_stream_generate_includes_given_sampling_params(self):
        b = _make_server_backend(_SSE_COMPLETION_RESP)
        list(b.stream_generate("hola", max_tokens=8, top_k=40,
                               repeat_penalty=1.1))
        payload = _sent_payload(b)
        assert payload["top_k"] == 40
        assert payload["repeat_penalty"] == 1.1
        assert "seed" not in payload

    def test_stream_chat_default_payload_has_no_sampling_keys(self):
        b = _make_server_backend(_SSE_CHAT_RESP)
        list(b.stream_chat([{"role": "user", "content": "hola"}], max_tokens=8))
        payload = _sent_payload(b)
        for key in _SAMPLING_KEYS:
            assert key not in payload
        assert payload["max_tokens"] == 8

    def test_stream_chat_includes_given_sampling_params(self):
        b = _make_server_backend(_SSE_CHAT_RESP)
        list(b.stream_chat([{"role": "user", "content": "hola"}],
                           max_tokens=8, seed=7, min_p=0.05))
        payload = _sent_payload(b)
        assert payload["seed"] == 7
        assert payload["min_p"] == 0.05
        assert "top_p" not in payload


class TestServerPayloadCachePrompt:
    """cache_prompt=True por default; False cuando se pasa (3 endpoints).

    El KV-cache reusado cambia el camino numerico de los logits (experimento
    2026-06-11): cache_prompt=False es la unica forma de output determinista.
    """

    def test_generate_default_cache_prompt_true(self):
        b = _make_server_backend(_COMPLETION_RESP)
        b.generate("hola", max_tokens=8)
        assert _sent_payload(b)["cache_prompt"] is True

    def test_generate_cache_prompt_false(self):
        b = _make_server_backend(_COMPLETION_RESP)
        b.generate("hola", max_tokens=8, cache_prompt=False)
        assert _sent_payload(b)["cache_prompt"] is False

    def test_stream_generate_default_cache_prompt_true(self):
        b = _make_server_backend(_SSE_COMPLETION_RESP)
        list(b.stream_generate("hola", max_tokens=8))
        assert _sent_payload(b)["cache_prompt"] is True

    def test_stream_generate_cache_prompt_false(self):
        b = _make_server_backend(_SSE_COMPLETION_RESP)
        list(b.stream_generate("hola", max_tokens=8, cache_prompt=False))
        assert _sent_payload(b)["cache_prompt"] is False

    def test_stream_chat_default_cache_prompt_true(self):
        b = _make_server_backend(_SSE_CHAT_RESP)
        list(b.stream_chat([{"role": "user", "content": "hola"}], max_tokens=8))
        assert _sent_payload(b)["cache_prompt"] is True

    def test_stream_chat_cache_prompt_false(self):
        b = _make_server_backend(_SSE_CHAT_RESP)
        list(b.stream_chat([{"role": "user", "content": "hola"}],
                           max_tokens=8, cache_prompt=False))
        assert _sent_payload(b)["cache_prompt"] is False


class TestServerPayloadGrammar:
    """El payload incluye "grammar" (string GBNF) SOLO cuando se pasa."""

    def test_generate_default_payload_has_no_grammar(self):
        b = _make_server_backend(_COMPLETION_RESP)
        b.generate("hola", max_tokens=8)
        assert "grammar" not in _sent_payload(b)

    def test_generate_includes_grammar_when_given(self):
        b = _make_server_backend(_COMPLETION_RESP)
        b.generate("hola", max_tokens=8, grammar='root ::= "x"')
        assert _sent_payload(b)["grammar"] == 'root ::= "x"'

    def test_stream_generate_default_payload_has_no_grammar(self):
        b = _make_server_backend(_SSE_COMPLETION_RESP)
        list(b.stream_generate("hola", max_tokens=8))
        assert "grammar" not in _sent_payload(b)

    def test_stream_generate_includes_grammar_when_given(self):
        b = _make_server_backend(_SSE_COMPLETION_RESP)
        list(b.stream_generate("hola", max_tokens=8, grammar='root ::= "x"'))
        assert _sent_payload(b)["grammar"] == 'root ::= "x"'


class TestFacadeGrammarForwarding:
    """La fachada reenvia grammar SOLO si no es None (impls viejos OK)."""

    def test_generate_default_keeps_positional_call(self):
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "ok"
        backend = _make_backend(mock_impl)
        backend.generate("p", max_tokens=16, temperature=0.5)
        mock_impl.generate.assert_called_once_with("p", 16, 0.5)

    def test_generate_forwards_grammar(self):
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "ok"
        backend = _make_backend(mock_impl)
        backend.generate("p", max_tokens=16, temperature=0.0,
                         grammar='root ::= "x"')
        mock_impl.generate.assert_called_once_with("p", 16, 0.0,
                                                   grammar='root ::= "x"')

    def test_stream_generate_forwards_grammar(self):
        mock_impl = MagicMock()
        mock_impl.stream_generate.return_value = iter(["A"])
        backend = _make_backend(mock_impl)
        list(backend.stream_generate("p", max_tokens=8, temperature=0.3,
                                     grammar='root ::= "x"'))
        mock_impl.stream_generate.assert_called_once_with("p", 8, 0.3,
                                                          grammar='root ::= "x"')


class TestFacadeCachePromptForwarding:
    """La fachada reenvia cache_prompt SOLO cuando es False (impls viejos OK)."""

    def test_generate_default_keeps_positional_call(self):
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "ok"
        backend = _make_backend(mock_impl)
        backend.generate("p", max_tokens=16, temperature=0.5)
        mock_impl.generate.assert_called_once_with("p", 16, 0.5)

    def test_generate_forwards_cache_prompt_false(self):
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "ok"
        backend = _make_backend(mock_impl)
        backend.generate("p", max_tokens=16, temperature=0.0,
                         seed=42, cache_prompt=False)
        mock_impl.generate.assert_called_once_with("p", 16, 0.0, seed=42,
                                                   cache_prompt=False)

    def test_stream_generate_forwards_cache_prompt_false(self):
        mock_impl = MagicMock()
        mock_impl.stream_generate.return_value = iter(["A"])
        backend = _make_backend(mock_impl)
        list(backend.stream_generate("p", max_tokens=8, temperature=0.3,
                                     cache_prompt=False))
        mock_impl.stream_generate.assert_called_once_with("p", 8, 0.3,
                                                          cache_prompt=False)

    def test_stream_chat_forwards_cache_prompt_false(self):
        mock_impl = MagicMock()
        mock_impl.stream_chat.return_value = iter(["A"])
        backend = _make_backend(mock_impl)
        msgs = [{"role": "user", "content": "hola"}]
        list(backend.stream_chat(msgs, max_tokens=64, temperature=0.7,
                                 cache_prompt=False))
        mock_impl.stream_chat.assert_called_once_with(msgs, 64, 0.7,
                                                      cache_prompt=False)


class TestFacadeSamplingForwarding:
    """La fachada reenvia sampling params SOLO si no son None (impls viejos OK)."""

    def test_generate_without_params_keeps_positional_call(self):
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "ok"
        backend = _make_backend(mock_impl)
        backend.generate("p", max_tokens=16, temperature=0.5)
        mock_impl.generate.assert_called_once_with("p", 16, 0.5)

    def test_generate_forwards_only_given_params(self):
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "ok"
        backend = _make_backend(mock_impl)
        backend.generate("p", max_tokens=16, temperature=0.0, seed=42)
        mock_impl.generate.assert_called_once_with("p", 16, 0.0, seed=42)

    def test_stream_chat_forwards_only_given_params(self):
        mock_impl = MagicMock()
        mock_impl.stream_chat.return_value = iter(["A"])
        backend = _make_backend(mock_impl)
        msgs = [{"role": "user", "content": "hola"}]
        list(backend.stream_chat(msgs, max_tokens=64, temperature=0.7,
                                 top_p=0.9))
        mock_impl.stream_chat.assert_called_once_with(msgs, 64, 0.7, top_p=0.9)

    def test_stream_generate_forwards_only_given_params(self):
        mock_impl = MagicMock()
        mock_impl.stream_generate.return_value = iter(["A"])
        backend = _make_backend(mock_impl)
        list(backend.stream_generate("p", max_tokens=8, temperature=0.3,
                                     top_k=40))
        mock_impl.stream_generate.assert_called_once_with("p", 8, 0.3, top_k=40)


# ---------------------------------------------------------------------------
# _server_props_summary()
# ---------------------------------------------------------------------------

class TestServerPropsSummary:
    def test_representative_props(self):
        """Forma representativa de GET /props en builds recientes de llama-server."""
        from node.llama_backend import _server_props_summary
        data = {
            "default_generation_settings": {
                "id": 0, "id_task": -1, "n_ctx": 16384,
                "params": {"n_predict": -1, "temperature": 0.8},
            },
            "total_slots": 1,
            "model_path": "D:/models/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
            "build_info": "b9391-7fb1e70b5",
            "chat_template": "{%- if tools %}...",
        }
        out = _server_props_summary(data)
        assert out == {
            "n_ctx": 16384,
            "model_path": "D:/models/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
            "build_info": "b9391-7fb1e70b5",
            "total_slots": 1,
        }

    def test_missing_fields_give_none(self):
        from node.llama_backend import _server_props_summary
        out = _server_props_summary({})
        assert out == {"n_ctx": None, "model_path": None,
                       "build_info": None, "total_slots": None}

    def test_facade_server_props_none_for_inprocess_impl(self):
        """Impl sin metodo props() (in-process) -> server_props() devuelve None."""
        mock_impl = MagicMock(spec=["generate"])
        backend = _make_backend(mock_impl)
        assert backend.server_props() is None


# ---------------------------------------------------------------------------
# _find_gguf()
# ---------------------------------------------------------------------------

class TestFindGguf:
    def test_returns_none_when_env_not_set_and_no_files(self, tmp_path, monkeypatch):
        """_find_gguf returns None when LLAMA_GGUF_PATH unset and shard dir has no gguf.

        We point SHARD_WEIGHTS_DIR to a subdirectory so the rglob on its parent
        only sees our controlled tree and does not escape into sibling pytest tmp dirs.
        """
        shard_dir = tmp_path / "shards" / "model"
        shard_dir.mkdir(parents=True)
        monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(shard_dir))

        from node.llama_backend import _find_gguf
        assert _find_gguf() is None

    def test_returns_path_from_env_var(self, tmp_path, monkeypatch):
        """_find_gguf returns the file pointed to by LLAMA_GGUF_PATH."""
        gguf = tmp_path / "my_model.gguf"
        gguf.touch()
        monkeypatch.setenv("LLAMA_GGUF_PATH", str(gguf))

        from node.llama_backend import _find_gguf
        result = _find_gguf()
        assert result == gguf

    def test_returns_none_when_env_path_missing(self, tmp_path, monkeypatch):
        """_find_gguf returns None (warning) when LLAMA_GGUF_PATH points to nonexistent file."""
        shard_dir = tmp_path / "shards" / "model"
        shard_dir.mkdir(parents=True)
        monkeypatch.setenv("LLAMA_GGUF_PATH", str(tmp_path / "ghost.gguf"))
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(shard_dir))

        from node.llama_backend import _find_gguf
        assert _find_gguf() is None

    def test_finds_candidate_in_shard_dir(self, tmp_path, monkeypatch):
        """_find_gguf finds a known candidate filename inside SHARD_WEIGHTS_DIR."""
        monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        candidate = tmp_path / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"
        candidate.touch()

        from node.llama_backend import _find_gguf
        result = _find_gguf()
        assert result == candidate


# ---------------------------------------------------------------------------
# _lora_args() — adapter LoRA opcional via LLAMA_LORA_PATH
# ---------------------------------------------------------------------------

class TestLoraArgs:
    # _lora_args devuelve ahora (args, fleet_names); el modo estatico
    # historico (LLAMA_LORA_PATH) conserva sus args y nunca tiene fleet.
    def test_returns_lora_flag_when_env_points_to_existing_file(self, tmp_path, monkeypatch):
        """LLAMA_LORA_PATH a un adapter existente -> (["--lora", path], [])."""
        adapter = tmp_path / "cognia_adapter.gguf"
        adapter.touch()
        monkeypatch.setenv("LLAMA_LORA_PATH", str(adapter))

        from node.llama_backend import _lora_args
        assert _lora_args() == (["--lora", str(adapter)], [])

    def test_returns_empty_when_env_path_missing(self, tmp_path, monkeypatch):
        """Seteada pero el archivo no existe -> ([], []) (warning, server sin adapter)."""
        monkeypatch.setenv("LLAMA_LORA_PATH", str(tmp_path / "ghost_adapter.gguf"))

        from node.llama_backend import _lora_args
        assert _lora_args() == ([], [])

    def test_returns_empty_when_env_not_set(self, monkeypatch):
        """Sin LLAMA_LORA_PATH ni manifiesto -> ([], []) (cmd identico al actual)."""
        monkeypatch.delenv("LLAMA_LORA_PATH", raising=False)

        from node.llama_backend import _lora_args
        assert _lora_args() == ([], [])


def test_llama_server_bind_localhost_only():
    """Seguridad: los servers de inferencia local (fleet 8088, portero 8090, heavy
    8092) deben bindear SOLO a 127.0.0.1, explicito (no depender del default del
    binario). Sin esto, un binario que default-ee a 0.0.0.0 expondria el modelo
    local a la LAN, en contra del core 'IA local, privada'. El cliente ya conecta
    a 127.0.0.1 (self._base)."""
    import inspect
    import re
    from node.llama_backend import _LlamaServerBackend
    src = inspect.getsource(_LlamaServerBackend.__init__)
    # el arg del cmd debe ser --host 127.0.0.1 (no 0.0.0.0). El regex verifica el
    # PAR exacto en el cmd; no assertir 'not "0.0.0.0"' porque el comentario del
    # codigo menciona 0.0.0.0 (y getsource incluye comentarios).
    assert re.search(r'"--host"\s*,\s*"127\.0\.0\.1"', src), \
        "el llama-server no fuerza --host 127.0.0.1 (exposicion a la LAN)"
    assert not re.search(r'"--host"\s*,\s*"0\.0\.0\.0"', src), \
        "el llama-server no debe bindear a 0.0.0.0 en el cmd"


# ── timeout del request: término de prefill (regresión 2026-07-14) ────────
def test_request_timeout_incluye_prefill():
    """Sin el término de prefill, un prompt de feromona de ~8KB con
    max_tokens=700 quedaba en 450s y timeouteaba en máquinas lentas aunque
    el server computara (4+ gens quemadas medidas). Con el fix, el payload
    largo compra tiempo proporcional."""
    from node.llama_backend import _request_timeout_s
    corto = _request_timeout_s(700, 500)
    largo = _request_timeout_s(700, 8000)
    assert corto == 30 + 420 + 500 // 25               # 470s
    assert largo == 30 + 420 + 8000 // 25              # 770s
    assert largo - corto >= 120                        # >=2 min extra de prefill
    # el piso de 120s se mantiene para requests chicos
    assert _request_timeout_s(24, 100) == 120
