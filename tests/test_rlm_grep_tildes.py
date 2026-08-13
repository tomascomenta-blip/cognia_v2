# -*- coding: utf-8 -*-
"""ctx_grep no puede devolver 0 matches en silencio por culpa de una tilde.

MEDIDO el 2026-08-13 con scripts/rlm_integracion.py: ante un corpus que dice
"REGISTRO CRITICO", el modelo escribe el patron "REGISTRO CRÍTICO" —corrige la
ortografia al construir la busqueda— y se lleva 0 matches. Como 0 matches es un
resultado LEGITIMO y no un ERROR, el modelo reintenta identico hasta que el
detector de estancamiento mata la tarea: 2 de 6 corridas del banco murieron asi,
y el resultado no era monotono (64 agujas pasaban y 32 fallaban), que es la
firma de un fallo de instrumento.

No es un caso de laboratorio: este repo esta escrito entero sin acentos
('funcion', 'codigo', 'parametro'), asi que el modelo va a buscar 'función' de
forma natural y no encontrar nada.

El contrato: cuando la busqueda literal no encuentra NADA y el patron lleva
tildes, se reintenta sin ellas y se le DICE al modelo, con el patron corregido.
Una busqueda que ya funcionaba no cambia.
"""

from __future__ import annotations

import pytest

from cognia.agent.rlm import _sin_diacriticos


class _Contexto:
    def __init__(self, lineas):
        self.lineas = lineas
        self.chars = sum(len(l) + 1 for l in lineas)

    def offset_linea(self, i):
        return sum(len(l) + 1 for l in self.lineas[:i - 1])


class _Medidor:
    def ver_raiz(self, ini, fin):
        pass


class _Estado:
    def __init__(self, lineas):
        self.contexto = _Contexto(lineas)
        self.medidor = _Medidor()


@pytest.fixture
def ctx_sin_tildes(monkeypatch):
    """Un contexto cuyo texto NO lleva acentos, como el codigo de este repo."""
    lineas = ["El parametro de la funcion quedo sin documentar.",
              "REGISTRO CRITICO numero 1: el contador marco 314 unidades.",
              "La medicion 7 se archivo con su comprobante."]
    estado = _Estado(lineas)
    from cognia.agent import rlm
    monkeypatch.setattr(rlm, "_estado_de", lambda ctx, tool: (estado, ""))
    return {}


# ── la normalizacion ───────────────────────────────────────────────────
@pytest.mark.parametrize("con,sin", [
    ("CRÍTICO", "CRITICO"),
    ("función", "funcion"),
    ("parámetro", "parametro"),
    ("ñandú", "ñandu"),          # la enye NO es un diacritico separable
])
def test_sin_diacriticos_quita_tildes_pero_respeta_la_enye(con, sin):
    assert _sin_diacriticos(con) == sin


def test_texto_sin_tildes_no_cambia():
    assert _sin_diacriticos("REGISTRO CRITICO") == "REGISTRO CRITICO"


# ── el comportamiento de la tool ───────────────────────────────────────
def test_avisa_cuando_la_tilde_es_la_culpable(ctx_sin_tildes):
    from cognia.agent.rlm import _ctx_grep
    salida = _ctx_grep("REGISTRO CRÍTICO", ctx_sin_tildes)
    assert "0 matches" in salida
    assert "ignorando tildes" in salida, (
        "el modelo recibe un 0 mudo y reintenta identico hasta agotar la tarea")
    assert "REGISTRO CRITICO" in salida, "hay que darle el patron que SI funciona"


def test_una_busqueda_que_ya_funcionaba_no_cambia(ctx_sin_tildes):
    from cognia.agent.rlm import _ctx_grep
    salida = _ctx_grep("REGISTRO CRITICO", ctx_sin_tildes)
    assert "1 de 1 matches" in salida
    assert "tildes" not in salida, "no se avisa de nada cuando la busqueda va bien"
    assert "314" in salida


def test_cero_matches_de_verdad_sigue_siendo_cero(ctx_sin_tildes):
    """Sin tildes de por medio, un 0 legitimo no se disfraza de aviso."""
    from cognia.agent.rlm import _ctx_grep
    salida = _ctx_grep("NO_EXISTE_ESTE_PATRON", ctx_sin_tildes)
    assert salida == "RESULTADO ctx_grep: 0 matches de ese patron en el contexto"


def test_patron_con_tildes_que_tampoco_casa_sin_ellas(ctx_sin_tildes):
    from cognia.agent.rlm import _ctx_grep
    salida = _ctx_grep("NÓMINA", ctx_sin_tildes)
    assert "ignorando tildes" not in salida, (
        "avisar de tildes cuando el problema es otro manda al modelo por mal camino")
