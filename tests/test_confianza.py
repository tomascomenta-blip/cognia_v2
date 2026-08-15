# -*- coding: utf-8 -*-
"""Confianza en vez de sí/no (2026-08-14).

Lo que estos tests protegen no es que el número exista, sino que se comporte
como una confianza: que baje sin evidencia, que no suba por repetir la misma
fuente, que una contradicción pese, y que el medidor de calibración detecte a
un sistema sobreconfiado (que es el sesgo por defecto de un LLM).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.search import confianza as CF


def _apoyo(url, ok=True):
    return {"source_url": url, "evidencia_verificada": ok}


class TestElNumeroSeComportaComoConfianza:

    def test_sin_fuentes_manda_a_investigar(self):
        v = CF.evaluar("42", apoyos=[])
        assert v.accion == "investigar"
        assert v.confianza == CF.CONFIANZA_SIN_FUENTE
        assert "memoria del modelo" in v.razones[0]

    def test_tres_dominios_verificados_dan_alta_confianza(self):
        v = CF.evaluar("42", [_apoyo("https://a.org/x"),
                              _apoyo("https://b.io/y"),
                              _apoyo("https://c.dev/z")])
        assert v.confianza >= 0.95 and v.accion == "responder"

    def test_repetir_el_MISMO_dominio_no_es_confirmar(self):
        una = CF.evaluar("42", [_apoyo("https://a.org/1")])
        tres = CF.evaluar("42", [_apoyo("https://a.org/1"),
                                 _apoyo("https://a.org/2"),
                                 _apoyo("https://a.org/3")])
        # Tres páginas del mismo sitio son UNA fuente: así es como un rumor
        # se convierte en hecho si uno cuenta URLs en vez de dominios.
        assert tres.confianza == una.confianza

    def test_sin_una_sola_cita_verificada_no_se_pasa_de_la_mitad(self):
        v = CF.evaluar("42", [_apoyo(f"https://{d}.org/x", ok=False)
                              for d in "abcde"])
        assert v.confianza <= 0.5 and v.accion == "investigar"

    def test_una_contradiccion_baja_la_confianza(self):
        sin = CF.evaluar("42", [_apoyo("https://a.org/x"),
                                _apoyo("https://b.org/y")])
        con = CF.evaluar("42", [_apoyo("https://a.org/x"),
                                _apoyo("https://b.org/y")],
                         contradicciones=[_apoyo("https://c.org/z")])
        assert con.confianza < sin.confianza
        assert any("CONTRADICHA" in r for r in con.razones)

    def test_la_frase_no_finge_precision(self):
        v = CF.evaluar("42", [_apoyo("https://a.org/x")])
        f = v.frase()
        assert "42" in f and "confianza" in f.lower()


class TestElMedidorDeCalibracion:

    def test_un_sistema_perfecto_da_ece_bajo(self):
        # 10 respuestas a 0,9 de las que aciertan 9: eso ES estar calibrado.
        pares = [(0.9, True)] * 9 + [(0.9, False)]
        m = CF.calibracion(pares)
        assert m["ece"] < 0.05 and abs(m["sobreconfianza"]) < 0.05

    def test_detecta_al_sobreconfiado(self):
        # Dice 0,95 y acierta la mitad: es el fallo que el módulo existe
        # para no cometer, y el medidor tiene que verlo.
        pares = [(0.95, True)] * 5 + [(0.95, False)] * 5
        m = CF.calibracion(pares)
        assert m["sobreconfianza"] > 0.4
        assert m["ece"] > 0.4
        assert m["brier"] > 0.4

    def test_sin_datos_no_inventa_un_numero(self):
        m = CF.calibracion([])
        assert m["n"] == 0 and m["ece"] is None

    def test_los_tramos_cubren_todo_el_rango(self):
        pares = [(0.05, False), (0.35, False), (0.55, True), (0.75, True),
                 (1.0, True)]
        m = CF.calibracion(pares, bins=5)
        assert sum(t["n"] for t in m["tramos"]) == 5
