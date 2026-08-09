# -*- coding: utf-8 -*-
"""Guards del fast-path de chat (obra 2026-08-09, WP4 / A8).

repl() es un loop interactivo que lee stdin: no se puede invocar de punta a
punta en un test unitario, asi que — mismo criterio que
test_effort_levels.test_chat_streaming_uses_active_effort_max_tokens_not_hardcoded
— estos son tests de regresion A NIVEL DE FUENTE: fallan si se revierte el
guard. La logica pura (clasificacion por nombre, presupuesto) tiene tests
funcionales en test_llm_local_perfil.py; el camino vivo se verifico contra
gpt-oss-20b real en :8080 (ver commit).
"""
import inspect

import cognia.cli as cli_mod


def _repl_src() -> str:
    return inspect.getsource(cli_mod.repl)


def test_desvios_gated_por_razonador_grande():
    """El desvio al 0.5B (speech_cascade) queda DETRAS del guard: con un
    razonador grande servido no se clasifica el turno para desviarlo."""
    src = _repl_src()
    i_guard = src.find("if not _srv_grande:")
    # el import del CLASIFICADOR de desvio (no el prewarm de arranque, que
    # tambien vive en repl() y es anterior)
    i_cascade = src.find("classify_turn, fast_speech_backend")
    assert i_guard != -1, "el guard del razonador grande desaparecio"
    assert i_cascade != -1
    assert i_guard < i_cascade, "speech_cascade quedo FUERA del guard"
    # y el fleet_router tambien esta gated
    assert "_llama_turn is _llama and not _srv_grande" in src


def test_desvio_nunca_silencioso():
    """Si el turno lo atiende otro modelo, hay linea visible + evento Aviso."""
    src = _repl_src()
    assert "respondio" in src
    assert "Aviso" in src


def test_presupuesto_cubre_pensamiento():
    """max_tokens del chat pasa por presupuesto_chat con razonador grande
    (la leccion de los 9 bugs identicos: pensar consume presupuesto)."""
    src = _repl_src()
    assert "presupuesto_chat" in src


def test_reintento_por_finish_length():
    """finish_reason REAL ('limit') dispara UN reintento con presupuesto x2."""
    src = _repl_src()
    assert 'last_stop_reason' in src
    assert '== "limit"' in src
    assert "_mt_turno *= 2" in src


def test_stepwise_solo_perfiles_chicos():
    """El CoT dirigido de 3B no se pega a modelos >4B (guard _srv_chico)."""
    src = _repl_src()
    assert "not _srv_chico" in src
