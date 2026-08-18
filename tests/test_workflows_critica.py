# -*- coding: utf-8 -*-
"""
tests/test_workflows_critica.py — critica adversarial del motor (2026-08-15)
============================================================================
Sin red y sin GPU: `completar_fn` siempre inyectado como stub.

Lo que se fija aca es la REGLA DE DECISION, que es la parte que puede mentir
en silencio. Un recuento que solo mire a los criticos que CONTESTARON lee
"2 de 3 revientan y el superviviente aprueba" como consenso, cuando es una
muestra de tamano 1. Por eso `contar_votos` recibe los dos numeros (lanzados
y respondidos) y por eso es una funcion PURA: la regla se verifica sin
encender un modelo.
"""
from __future__ import annotations

import pytest

from cognia.agent.workflows import (LENTES_POR_DEFECTO, contar_votos, corrida,
                                    criticar)


# --- stub de backend --------------------------------------------------------

class _Resp:
    def __init__(self, texto="", finish_reason="stop"):
        self.texto = texto
        self.error = None
        self.finish_reason = finish_reason
        # PresupuestoTokens.registrar() suma prompt_tokens + completion_tokens;
        # un usage con solo 'total_tokens' cuenta CERO y el techo nunca corta.
        self.usage = {"prompt_tokens": 5, "completion_tokens": 5}


class _StubFijo:
    """Devuelve SIEMPRE el mismo JSON: los tres criticos corren en paralelo y
    el orden de llegada no esta garantizado, asi que una cola por indice haria
    el test flaky por construccion."""

    def __init__(self, payload):
        self.payload = payload
        self.llamadas = 0

    def __call__(self, mensajes, **kw):
        self.llamadas += 1
        return _Resp(texto=self.payload)


@pytest.fixture(autouse=True)
def _dir_wf(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path))


def _corrida(**kw):
    return corrida("critica", print_fn=lambda *a, **k: None, **kw)


# --- 1) el quorum: no contestar NO es aprobar --------------------------------

def test_sin_quorum_es_indeterminado_no_sobrevive():
    """UN critico de tres aprobando no es 'sobrevive': es una muestra de 1.

    Es el fallo silencioso del fan-out entrando por la puerta de atras: si el
    recuento mirase solo a los que respondieron, dos criticos caidos se leerian
    como 'no encontraron nada'.
    """
    r = contar_votos([{"refutado": False, "motivo": "todo bien"}], n_lanzados=3)
    assert r["veredicto"] == "INDETERMINADO"
    assert r["lanzados"] == 3 and r["respondieron"] == 1


def test_con_quorum_justo_ya_decide():
    votos = [{"refutado": False, "motivo": "ok"},
             {"refutado": False, "motivo": "ok"}]
    r = contar_votos(votos, n_lanzados=3)
    assert r["veredicto"] == "SOBREVIVE"


# --- 2) la mayoria y el defecto mortal ---------------------------------------

def test_mayoria_que_refuta_gana():
    votos = [{"refutado": True, "motivo": "la cuenta no da"},
             {"refutado": True, "motivo": "sin evidencia"},
             {"refutado": False, "motivo": "a mi me cuadra"}]
    r = contar_votos(votos, n_lanzados=3)
    assert r["veredicto"] == "REFUTADO" and r["refutan"] == 2


def test_un_defecto_MATA_refuta_aunque_nadie_marque_refutado():
    """La gravedad manda sobre el booleano: un critico puede describir un
    defecto que invalida la entrega y aun asi poner refutado=false por
    prudencia. El que decide es el defecto, no el adjetivo."""
    votos = [{"refutado": False, "motivo": "casi todo bien",
              "defectos": [{"defecto": "el paso 9 no cabe en VRAM",
                            "gravedad": "MATA"}]},
             {"refutado": False, "motivo": "ok"},
             {"refutado": False, "motivo": "ok"}]
    r = contar_votos(votos, n_lanzados=3)
    assert r["veredicto"] == "REFUTADO"
    assert len(r["mortales"]) == 1


def test_empate_no_refuta():
    """1 de 2 no es mayoria: sin mayoria la entrega sobrevive. Elegido a
    proposito para que la critica no se convierta en un veto de uno solo."""
    votos = [{"refutado": True, "motivo": "no me convence"},
             {"refutado": False, "motivo": "esta bien"}]
    assert contar_votos(votos, n_lanzados=2)["veredicto"] == "SOBREVIVE"


def test_cero_lentes_no_es_aprobacion():
    assert contar_votos([], 0)["veredicto"] == "INDETERMINADO"


# --- 3) criticar() de punta a punta, con stub --------------------------------

def test_criticar_lanza_una_llamada_por_lente_y_vota():
    c = _corrida()
    stub = _StubFijo('{"refutado": true, "motivo": "la cuenta no da", '
                     '"defectos": [{"defecto": "x", "gravedad": "MATA"}]}')
    r = criticar(c, "2 + 2 = 5", contexto="Objetivo: sumar",
                 completar_fn=stub, cap=2)
    c.cerrar()

    assert stub.llamadas == len(LENTES_POR_DEFECTO)
    assert r["veredicto"] == "REFUTADO"
    assert r["lentes"] == ["aritmetica", "evidencia", "encargo"]
    assert r["respondieron"] == len(LENTES_POR_DEFECTO)


def test_un_agente_con_error_no_cuenta_como_voto():
    """`agente()` devuelve {"_error": ...} en vez de lanzar. Ese dict NO es un
    juicio: si se colase en el recuento, un backend caido aprobaria la entrega
    por unanimidad de cero.
    """
    from cognia.agent.workflows import agente

    # El presupuesto no corta en la PRIMERA llamada (a cero gastado no hay nada
    # que agotar): se gasta con una llamada previa y recien entonces critica.
    c = _corrida(presupuesto_tokens=5)
    gasto = _StubFijo('{"refutado": false, "motivo": "gasta 10 tokens"}')
    agente(c, "quemo el presupuesto", completar_fn=gasto)

    stub = _StubFijo('{"refutado": false, "motivo": "no deberia correr"}')
    r = criticar(c, "cualquier cosa", completar_fn=stub, cap=2)
    c.cerrar()

    assert stub.llamadas == 0, "el presupuesto agotado no debe llamar al stub"
    assert r["respondieron"] == 0
    assert r["veredicto"] == "INDETERMINADO", \
        "sin votos reales el veredicto NO puede ser SOBREVIVE"


def test_lentes_a_medida_se_respetan():
    c = _corrida()
    stub = _StubFijo('{"refutado": false, "motivo": "ok"}')
    r = criticar(c, "entrega", lentes=[("seguridad", "busca fugas de datos")],
                 completar_fn=stub)
    c.cerrar()
    assert r["lentes"] == ["seguridad"] and stub.llamadas == 1
    assert r["veredicto"] == "SOBREVIVE"


def test_la_critica_queda_en_el_journal():
    """Sin rastro en disco no hay forma de auditar por que se aprobo algo."""
    import json
    c = _corrida()
    stub = _StubFijo('{"refutado": false, "motivo": "ok"}')
    criticar(c, "entrega", completar_fn=stub)
    c.cerrar()

    lineas = [json.loads(l) for l in
              (c.dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
              if l.strip()]
    criticas = [l for l in lineas if l.get("tipo") == "critica"]
    assert len(criticas) == 1
    assert criticas[0]["veredicto"] == "SOBREVIVE"
    assert criticas[0]["respondieron"] == 3
