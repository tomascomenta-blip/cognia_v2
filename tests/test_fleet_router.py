# -*- coding: utf-8 -*-
"""Router léxico del fleet: identidad -> experto accion; todo lo demás -> base."""
import pytest

from cognia.agent.fleet_router import expert_for_chat_turn, is_identity_turn


@pytest.mark.parametrize("texto", [
    "¿Quién sos?",
    "quien eres tu",
    "¿Cómo te llamás?",
    "cual es tu nombre?",
    "¿Qué eres exactamente?",
    "¿Quién te creó?",
    "quien te entrenó",
    "¿Eres ChatGPT?",
    "sos una IA?",
    "who are you?",
    "what is your name",
    "presentate",
    "¿Qué asistente de inteligencia artificial sos?",
    "Si tuvieras que presentarte a un amigo mío, ¿qué dirías?",
    "¿En qué proyecto fuiste desarrollado?",
    "che, ¿con qué IA estoy hablando?",
    "What AI assistant are you?",
    "Introduce yourself in one sentence, including your name.",
    "which AI am I talking to?",
    "Are you ChatGPT, Gemini, or something else?",
])
def test_identidad_va_al_experto(texto):
    assert is_identity_turn(texto)
    assert expert_for_chat_turn(texto) == "accion"


@pytest.mark.parametrize("texto", [
    "hola, ¿cómo estás?",
    "¿cuál es la capital de Francia?",
    "escribí una función que sume dos números",
    "¿quién es el presidente de Argentina?",   # quién de TERCEROS, no identidad
    "¿cómo te fue con el informe?",            # 'como te' sin 'llam'
    "resumí este texto",
    "what's the weather like",
    "¿qué modelo de auto me conviene comprar?",   # 'modelo' sin contexto de IA
    "¿cómo se llama la novia de Messi?",          # nombre de TERCEROS
    "",
])
def test_chat_general_queda_en_base(texto):
    assert not is_identity_turn(texto)
    assert expert_for_chat_turn(texto) is None


def test_member_for_chat_turn_razonamiento_va_al_4b(monkeypatch):
    from cognia.agent.fleet_router import member_for_chat_turn
    from cognia.agent.stepwise import needs_stepwise
    monkeypatch.delenv("COGNIA_RAZONA_4B", raising=False)
    ejemplo = ("Si Ana tiene 3 manzanas y compra el doble de las que tenia, "
               "cuantas manzanas tiene ahora? Razona paso a paso.")
    assert needs_stepwise(ejemplo)          # el detector compartido dispara
    assert member_for_chat_turn(ejemplo) == "qwen3_4b"
    assert member_for_chat_turn("hola, como estas?") is None


def test_member_for_chat_turn_kill_switch(monkeypatch):
    from cognia.agent.fleet_router import member_for_chat_turn
    monkeypatch.setenv("COGNIA_RAZONA_4B", "0")
    assert member_for_chat_turn(
        "Si un tren sale a 60 km/h y otro a 80 km/h en sentido contrario, "
        "cuanto tardan en cruzarse? Explica paso a paso.") is None
