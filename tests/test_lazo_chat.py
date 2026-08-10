"""
tests/test_lazo_chat.py
=======================
Lazo de verificacion de respuestas de chat (cognia/agent/lazo_chat.py).

Incluye el CONTRAFACTUAL OBLIGATORIO de la casa (memoria del repo: 17 veces
un numero parecio verificado sin estarlo): el test 1 mete el defecto
('2+2=5') y exige que el lazo lo cace y lo corrija; el test 2 QUITA el
defecto ('2+2=4') y exige que el efecto se APAGUE (sello_ok, 0 rondas, cero
llamadas de revision). Un lazo que revisa lo sano es el bug medido de la
nocturna 27/28 (neto -7).

Sin GPU: chat_fn es un fake con contador; las tools reales usadas (calcular,
py_validar) son deterministas y locales.
"""
from __future__ import annotations

import pytest

from cognia.agent import lazo_chat
from cognia.agent.lazo_chat import (MAX_CLAIMS, Claim, ResultadoLazo,
                                    Veredicto, extraer_claims, lazo_respuesta,
                                    verificar_claim)


class ChatFake:
    """chat_fn falso con contador de invocaciones (para exigir CERO llamadas
    donde el lazo no debe abrir revision)."""

    def __init__(self, respuesta: str):
        self.respuesta = respuesta
        self.llamadas = 0
        self.prompts = []

    def __call__(self, prompt: str) -> str:
        self.llamadas += 1
        self.prompts.append(prompt)
        return self.respuesta


# ── (1) contrafactual, mitad CON defecto: el lazo caza '2+2=5' ─────────
def test_claim_falso_se_caza_y_la_revision_lo_arregla():
    original = "La suma da 2+2=5, asi que compra 5 unidades."
    chat = ChatFake("La suma da 2+2=4, asi que compra 4 unidades.")
    eventos = []
    res = lazo_respuesta("cuanto es 2+2?", original, chat, {},
                         on_evento=eventos.append)
    assert res.motivo == "revisado_ok"
    assert res.rondas == 1
    assert "2+2=4" in res.final
    assert chat.llamadas == 1
    # el prompt de revision lleva la evidencia CRUDA del tool (P8), no critica
    assert "RESULTADO calcular" in chat.prompts[0]
    # el veredicto reprobado y el de la re-verificacion salieron por on_evento
    assert any(v.ok is False for v in eventos)
    assert any(v.ok is True for v in eventos)


# ── (2) contrafactual, mitad SIN defecto: el efecto se APAGA ───────────
def test_mismo_caso_correcto_sello_ok_cero_rondas():
    original = "La suma da 2+2=4, asi que compra 4 unidades."
    chat = ChatFake("no deberia llamarse")
    res = lazo_respuesta("cuanto es 2+2?", original, chat, {})
    assert res.motivo == "sello_ok"
    assert res.rondas == 0
    assert res.final == original          # byte a byte, intacta
    assert chat.llamadas == 0             # cero revisiones sobre lo sano


# ── (3) sin claims verificables: respuesta directa, intacta ────────────
def test_sin_claims_sin_sello_intacto():
    original = "Hola! Gracias por escribir. Contame mas del proyecto."
    chat = ChatFake("no deberia llamarse")
    res = lazo_respuesta("hola", original, chat, {})
    assert res.motivo == "sin_sello"
    assert res.rondas == 0
    assert res.final == original
    assert res.veredictos == []
    assert chat.llamadas == 0


# ── (4) revision peor: keep-best devuelve el ORIGINAL ──────────────────
def test_revision_peor_keep_best_original():
    original = "El resultado es 2+2=5."
    chat = ChatFake("Perdon, en realidad 2+2=6.")   # sigue mal
    res = lazo_respuesta("cuanto es 2+2?", original, chat, {})
    assert res.motivo == "revision_peor_keep_best"
    assert res.rondas == 1
    assert res.final == original


# ── (5) negativa del modelo: keep-best con motivo declarado ────────────
def test_negativa_keep_best_motivo_declarado():
    original = "El resultado es 2+2=5."
    chat = ChatFake("Sorry, I cannot provide a solution to that.")
    res = lazo_respuesta("cuanto es 2+2?", original, chat, {})
    assert res.motivo == "revision_negada_keep_best"
    assert res.rondas == 1
    assert res.final == original


# ── (6) codigo con SyntaxError: py_validar lo reprueba ─────────────────
def test_codigo_syntax_error_reprobado_por_py_validar():
    original = ("Proba con esto:\n"
                "```python\n"
                "def f(:\n"
                "    return 1\n"
                "```\n")
    claims = extraer_claims(original)
    assert [c.tipo for c in claims] == ["codigo"]
    v = verificar_claim(claims[0], {})
    assert v.ok is False
    assert v.tool == "py_validar"
    assert "ERROR" in v.evidencia


# ── (7) cap de claims: presupuesto duro de 5 ───────────────────────────
def test_cap_de_cinco_claims():
    original = ". ".join(f"{i}+{i}={2 * i}" for i in range(1, 8)) + "."
    claims = extraer_claims(original)
    assert len(claims) == MAX_CLAIMS == 5


# ── extras: bordes que el plan declara como contrato ───────────────────
def test_registry_roto_motivo_infra_respuesta_intacta(monkeypatch):
    # Sin tools disponibles el lazo NO inventa veredictos: infra, intacta.
    monkeypatch.setattr(lazo_chat, "_run_tool_real", lambda: None)
    original = "El resultado es 2+2=5."
    chat = ChatFake("no deberia llamarse")
    res = lazo_respuesta("cuanto es 2+2?", original, chat, {})
    assert res.motivo == "infra"
    assert res.final == original
    assert chat.llamadas == 0


def test_incierto_no_dispara_revision():
    # calcular no puede dar veredicto (division por cero) -> ok=None, y un
    # None JAMAS abre revision. Con cero verificados reales tampoco hay
    # sello: el motivo honesto es sin_sello.
    original = "El calculo da 5/0 = 7 en ese limite."
    chat = ChatFake("no deberia llamarse")
    res = lazo_respuesta("?", original, chat, {})
    assert res.motivo == "sin_sello"
    assert res.rondas == 0
    assert res.final == original
    assert chat.llamadas == 0
    assert all(v.ok is None for v in res.veredictos)


def test_keep_best_con_sello_adversarial(monkeypatch):
    # Peor caso del sello al azar (todo reprueba siempre): sobre un
    # mini-banco de 10 respuestas el lazo entrega SIEMPRE el original —
    # cero revisiones aplicadas daninas (la propiedad que falto en la
    # nocturna 27/28 y costo neto -7).
    monkeypatch.setattr(
        lazo_chat, "verificar_claim",
        lambda c, reg: Veredicto(c, False, "RESULTADO x", "calcular"))
    banco = [f"El total es {i}+{i}={2 * i}." for i in range(1, 11)]
    for original in banco:
        chat = ChatFake("Revision cualquiera con 9+9=99.")
        res = lazo_respuesta("p", original, chat, {})
        assert res.final == original
        assert res.motivo == "revision_peor_keep_best"


def test_extraccion_descarta_lo_no_ejecutable():
    # 'en 1999, 2+2=5': el lhs util es solo '2+2' (el regex traga la fecha);
    # y '10 = 10' (sin operador) no es un claim ejecutable.
    claims = extraer_claims("Como dije en 1999, 2+2=5. Ademas 10 = 10.")
    assert len(claims) == 1
    assert claims[0].expr == "2+2 = 5"


def test_motivos_dentro_del_contrato():
    # Los motivos entregados pertenecen SIEMPRE al set declarado (contrato
    # del render de cli.py).
    assert lazo_respuesta("p", "hola", None, {}).motivo in lazo_chat.MOTIVOS
    assert lazo_respuesta("p", "2+2=4", None, {}).motivo in lazo_chat.MOTIVOS
    # reprobado sin chat_fn: no hay con que revisar -> infra declarado
    res = lazo_respuesta("p", "2+2=5", None, {})
    assert res.motivo == "infra"
    assert res.final == "2+2=5"
