# -*- coding: utf-8 -*-
"""M4 -- los dos bugs que destapo cablear E0, y el drill de E1 en la suite.

Los dos bugs eran del MISMO tipo, el que este repo llama vacio silencioso: el
subsistema seguia corriendo, no lanzaba nada, y lo que producia era una medida
constante y falsa. Ninguno lo cazaba la suite (137 en verde con los dos vivos);
los cazo correr el brazo TX del experimento contra el modelo de verdad.

  1. `driver.responder_por_defecto` leia `r.content`, y `RespuestaChat` no tiene
     ese atributo: el `getattr(..., "")` devolvia "" SIEMPRE. Con eso, el turno
     de control tras el reset llegaba vacio, Q salia 0/3 y G2 suspendia por
     "respuesta VACIA" en cada commit -> todo reset caia a MODO ANCHO.
  2. `commit._enunciado` no PEDIA los trazadores, y G2 se mide justo sobre esa
     respuesta (ESPEC 6.5). Las 3 preguntas se iban en objetivo + restricciones,
     el modelo contestaba eso y nada mas, y G2 suspendia siempre -> mismo
     efecto, por otro camino.
"""

import os
import sys

import pytest

from cognia.tx import commit, driver, gates


EXP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "planes", "agente_largo", "exp")


# ------------------------------------------------------------------- bug 1

class _Resp(object):
    """Lo minimo de RespuestaChat que mira el driver. `content` NO existe, que
    es exactamente el punto: si alguien vuelve a leer `.content`, este doble
    tampoco lo tiene y el test cae."""

    def __init__(self, texto):
        self.texto = texto
        self.error = ""
        self.finish_reason = "stop"
        self.usage = {"completion_tokens": 7}


def test_responder_por_defecto_devuelve_el_texto_del_modelo(monkeypatch):
    import cognia.agent.chat_client as cc
    monkeypatch.setattr(cc, "completar",
                        lambda *a, **k: _Resp("P-000: el objetivo literal"))
    salida = driver.responder_por_defecto(max_tokens=64)("preguntas")
    assert salida == "P-000: el objetivo literal", (
        "el canal de respuesta de c3 devolvio %r: con eso Q mide 0/3 siempre "
        "y ningun commit puede salir HECHO" % salida)


def test_responder_por_defecto_avisa_cuando_el_modelo_calla(monkeypatch, capsys):
    """Un vacio REAL tiene que verse. 'no contesto' y 'contesto vacio' piden
    decisiones distintas y no pueden verse igual desde fuera."""
    import cognia.agent.chat_client as cc
    monkeypatch.setattr(cc, "completar", lambda *a, **k: _Resp("   "))
    assert driver.responder_por_defecto()("preguntas") == "   "
    assert "VACIO" in capsys.readouterr().err


# ------------------------------------------------------------------- bug 2

def test_el_enunciado_de_q_pide_los_trazadores():
    """G2 se mide sobre la respuesta a ESTE enunciado. Si no los pide, G2 no
    puede aprobar nunca y el 2PC se queda en ANCHO perpetuo."""
    texto = commit._enunciado([{"id": "Q1", "pregunta": "Cita el objetivo."}])
    assert "trazador" in texto.lower()
    assert "banda t" in texto.lower()


def test_una_respuesta_que_contesta_el_enunciado_entero_aprueba_g2():
    """El circuito completo: enunciado -> respuesta plausible -> G2 verde.
    Sin la linea de trazadores, una respuesta que solo contesta Q1..Q3 deja
    G2 en rojo, y eso es lo que se media antes."""
    estado = {"trazadores": [
        {"id": "TRZ-AA0001", "tipo": "valor", "texto": "TRZ-AA0001: umbral 612"},
        {"id": "TRZ-BB0002", "tipo": "valor", "texto": "TRZ-BB0002: umbral 77"}]}
    preguntas = [{"id": "Q1", "pregunta": "Cita el objetivo.",
                  "esperado": "cablear el canal"}]
    enunciado = commit._enunciado(preguntas)
    assert "T." in enunciado
    solo_q = "Q1: cablear el canal"
    con_t = solo_q + "\nT: TRZ-AA0001\nTRZ-BB0002"
    assert not gates.g2_trazadores(estado, solo_q)["ok"]
    assert gates.g2_trazadores(estado, con_t)["ok"]


# ------------------------------------------------------- E1 dentro de la suite

@pytest.mark.parametrize("n", [2])
def test_e1_el_gate_caza_las_mutaciones_y_no_condena_sanos(n, monkeypatch):
    """E1 reducido: el drill de mutacion corre en la suite, no solo a mano.

    Un gate que nunca aborta es una AVERIA y desde fuera se ve igual que uno
    sano. Aqui se exige lo mismo que el experimento: deteccion 1,000 Y cero
    falsos positivos sobre proyecciones sanas.
    """
    if EXP not in sys.path:
        sys.path.insert(0, EXP)
    monkeypatch.setenv("COGNIA_TX", "1")
    import e1
    monkeypatch.setattr(e1, "N_TAREAS", n)
    res = e1.resumir(e1.corrida())
    assert res["deteccion"] == 1.0, res
    assert res["falsos_positivos"] == 0, res
    assert res["mutaciones"] == 5 * n


def test_respuestachat_no_tiene_content_y_por_eso_el_getattr_mentia():
    """La trampa, cristalizada: `RespuestaChat` expone `.texto`, no `.content`.
    Un `getattr(r, "content", "")` no revienta -- devuelve "" y el subsistema
    sigue como si el modelo hubiera callado. Ese es el vacio silencioso, y es
    el motivo de que 137 tests estuvieran en verde con el bug vivo."""
    from cognia.agent.chat_client import RespuestaChat
    r = RespuestaChat(texto="algo que el modelo si dijo")
    assert not hasattr(r, "content")
    assert getattr(r, "content", "") == ""
    assert r.texto == "algo que el modelo si dijo"
