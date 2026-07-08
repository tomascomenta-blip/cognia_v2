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
