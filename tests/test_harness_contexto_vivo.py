# -*- coding: utf-8 -*-
"""
Tests del contador de contexto/coste en vivo (cognia/harness/contexto_vivo.py).

Fija lo que el CLI necesita para dejar de mentir en /costo: que la ENTRADA se
cuente (no solo la salida), que los tokens cacheados no se cuenten dos veces,
que la ocupacion de ventana salga en porcentaje real, que la barra quepa en 80
columnas degradando modelo-antes-que-ctx, que el aviso de compactar tenga
histeresis y que todo numero estimado quede MARCADO como estimado.
"""

import io
import sys
import threading

import pytest

from cognia.harness import contexto_vivo as CV


@pytest.fixture(autouse=True)
def acumulador_limpio():
    """El acumulador es de proceso: cada test arranca en cero."""
    CV.reiniciar()
    yield
    CV.reiniciar()


@pytest.fixture(autouse=True)
def consola_utf8(monkeypatch):
    """Pin del encoding de consola: el separador no depende de quien corre pytest."""
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))


# -- Acumulacion --------------------------------------------------------------

def test_cuenta_entrada_y_salida_del_usage_real():
    CV.registrar_uso(1000, 200, modelo="flota/modelo-x")
    CV.registrar_uso(1500, 300)
    est = CV.estado()
    assert est["entrada"] == 2500
    assert est["salida"] == 500
    assert est["total"] == 3000          # el /costo viejo solo veia la salida
    assert est["turnos"] == 2
    assert est["modelo"] == "flota/modelo-x"
    assert est["estimado"] is False


def test_cacheados_no_se_suman_al_total():
    # cached ya viene DENTRO de prompt_tokens: sumarlo lo contaria dos veces.
    CV.registrar_uso(1000, 100, cached=800)
    est = CV.estado()
    assert est["cacheados"] == 800
    assert est["total"] == 1100


def test_usage_sucio_no_rompe():
    CV.registrar_uso(None, "250", cached=None)
    CV.registrar_uso(-5, 10)
    est = CV.estado()
    assert est["entrada"] == 0
    assert est["salida"] == 260
    assert est["turnos"] == 2


def test_usage_infinito_o_nan_no_revienta_el_turno():
    # json.loads acepta Infinity/NaN por DEFECTO: si el backend los manda,
    # int(inf) tira OverflowError (que no es TypeError ni ValueError).
    CV.registrar_uso(float("inf"), float("nan"))
    CV.registrar_uso(float("-inf"), 100)
    est = CV.estado()
    assert est["entrada"] == 0
    assert est["salida"] == 100
    assert est["turnos"] == 2


def test_usage_float_en_texto_no_se_pierde_en_silencio():
    # Un backend que serializa el usage como float contaba 0 tokens sin chistar:
    # el peor fallo posible en un contador cuya razon de ser es no mentir.
    CV.registrar_uso("1000.0", "200.0")
    est = CV.estado()
    assert (est["entrada"], est["salida"], est["total"]) == (1000, 200, 1200)


def test_registrar_uso_fija_la_ocupacion_del_proximo_prompt():
    # Sin cablear registrar_contexto, la barra ya sabe cuanta ventana se usa.
    CV.registrar_contexto(0, 32000)
    CV.registrar_uso(12000, 800)
    est = CV.estado()
    assert est["ocupacion"] == 12800
    assert est["porcentaje"] == 40
    assert est["restante"] == 32000 - 12800


def test_registrar_contexto_pisa_la_ocupacion():
    CV.registrar_uso(12000, 800)
    CV.registrar_contexto(4000, 8000)   # p.ej. tras recortar el historial
    est = CV.estado()
    assert est["ocupacion"] == 4000
    assert est["n_ctx"] == 8000
    assert est["porcentaje"] == 50
    assert est["restante"] == 4000
    assert est["total"] == 12800        # el acumulado de sesion no se toca


def test_sin_n_ctx_no_se_inventa_porcentaje():
    CV.registrar_uso(5000, 100)
    est = CV.estado()
    assert est["n_ctx"] == 0
    assert est["porcentaje"] == 0
    assert est["restante"] == 0
    assert est["ocupacion"] == 5100


def test_estado_es_copia():
    CV.registrar_uso(100, 10)
    est = CV.estado()
    est["total"] = 999999
    assert CV.estado()["total"] == 110


def test_reiniciar_borra_todo_incluida_la_histeresis():
    CV.registrar_uso(1000, 100, modelo="modelo-x")
    CV.registrar_contexto(95, 100)
    assert CV.aviso_umbral() == "critico"
    CV.reiniciar()
    est = CV.estado()
    assert (est["total"], est["turnos"], est["modelo"]) == (0, 0, "")
    assert (est["ocupacion"], est["n_ctx"], est["porcentaje"]) == (0, 0, 0)
    assert est["estimado"] is False
    CV.registrar_contexto(95, 100)
    assert CV.aviso_umbral() == "critico"   # el aviso vuelve a estar armado


# -- Estimacion marcada -------------------------------------------------------

def test_estimar_tokens():
    assert CV.estimar_tokens("") == 0
    assert CV.estimar_tokens(None) == 0
    assert CV.estimar_tokens("abcd") == 1
    assert CV.estimar_tokens("a" * 400) == 100
    # CJK: la regla de 4 chars/token subestimaba 4x.
    assert CV.estimar_tokens("漢字漢字") == 4


def test_lo_estimado_queda_marcado_como_estimado():
    CV.registrar_uso_estimado("hola " * 100, "respuesta " * 50, modelo="modelo-x")
    est = CV.estado()
    assert est["estimado"] is True
    assert est["total"] > 0
    assert est["turnos"] == 1
    assert "~" in CV.barra(ancho=80, con_color=False)


def test_la_marca_de_estimado_es_pegajosa():
    CV.registrar_uso_estimado("texto", "otro")
    CV.registrar_uso(1000, 100)          # un usage real despues no lava la mezcla
    assert CV.estado()["estimado"] is True


# -- Barra de estado ----------------------------------------------------------

def _sesion_barra(modelo="modelo-x"):
    CV.registrar_uso(1000, 200, modelo=modelo)
    CV.registrar_contexto(12800, 32000)


def test_barra_formato_completo():
    _sesion_barra()
    linea = CV.barra(ancho=80, con_color=False)
    assert linea == "modelo-x · ctx 12.8k/32k (40%) · 1.2k tok"


def test_barra_cabe_en_80_columnas():
    CV.registrar_uso(900000, 120000, modelo="proveedor/un-modelo-con-nombre-larguisimo")
    CV.registrar_contexto(998000, 1048576)
    linea = CV.barra(con_color=False)
    assert len(linea) <= 80


def test_barra_no_mezcla_unidades_al_redondear():
    # 999_999 caia en el rango de 'k' y salia '1000k': la misma barra mostraba
    # "ctx 1000k/1M", dos unidades distintas en un campo de un vistazo.
    CV.registrar_uso(999000, 999, modelo="modelo-x")
    CV.registrar_contexto(999999, 1048576)
    linea = CV.barra(ancho=80, con_color=False)
    assert "1000k" not in linea
    assert linea == "modelo-x · ctx 1M/1M (95%) · 1M tok"


def test_barra_no_reusa_la_marca_de_estimado_como_elipsis(monkeypatch):
    # En consola cp1252/pipe el modelo recortado terminaba en '~', el mismo
    # caracter que significa "este numero es estimado". Una marca, un sentido.
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="ascii"))
    CV.registrar_uso(1000, 200, modelo="modelo-larguisimo-de-prueba")
    CV.registrar_contexto(12800, 32000)
    linea = CV.barra(ancho=50, con_color=False)
    assert linea.count("~") == 0                 # nada estimado aca
    assert "modelo-larguisimo-de-prueba" not in linea
    assert linea.startswith("modelo-larg")       # pero SI se recorto

    CV.registrar_uso_estimado("hola " * 100, "chau " * 20)
    estimada = CV.barra(ancho=50, con_color=False)
    assert estimada.count("~") == 1              # el unico '~' es el del total
    assert estimada.split("|")[-1].strip().startswith("~")


def test_barra_sin_emojis():
    _sesion_barra()
    linea = CV.barra(ancho=80, con_color=False)
    assert all(ord(ch) < 128 or ch == "·" for ch in linea)


def test_barra_degrada_recortando_modelo_antes_que_ctx():
    _sesion_barra(modelo="modelo-larguisimo-de-prueba")

    ancha = CV.barra(ancho=80, con_color=False)
    assert ancha.startswith("modelo-larguisimo-de-prueba")

    # 1er recorte: el modelo se abrevia, el ctx sigue entero.
    media = CV.barra(ancho=50, con_color=False)
    assert len(media) <= 50
    assert "modelo-larguisimo-de-prueba" not in media
    assert media.startswith("modelo-larg")
    assert "ctx 12.8k/32k (40%)" in media

    # 2o recorte: cae el modelo, el ctx aguanta.
    angosta = CV.barra(ancho=40, con_color=False)
    assert len(angosta) <= 40
    assert "modelo" not in angosta
    assert angosta.startswith("ctx 12.8k/32k (40%)")

    # 3er recorte: del ctx sobrevive el porcentaje.
    minima = CV.barra(ancho=20, con_color=False)
    assert len(minima) <= 20
    assert "ctx 40%" in minima
    assert "12.8k" not in minima

    # 4o recorte: solo el gasto.
    ultima = CV.barra(ancho=10, con_color=False)
    assert ultima == "1.2k tok"

    assert len(CV.barra(ancho=5, con_color=False)) <= 5


def test_barra_ascii_si_la_consola_no_codifica_el_separador(monkeypatch):
    _sesion_barra()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="ascii"))
    linea = CV.barra(ancho=80, con_color=False)
    assert "·" not in linea
    assert "|" in linea
    linea.encode("ascii")       # no revienta la consola cp1252/pipe de Windows


def test_barra_colorea_solo_a_partir_del_umbral():
    _sesion_barra()                      # 40%: por debajo del aviso
    assert "\x1b[" not in CV.barra(ancho=80, con_color=True)

    CV.registrar_contexto(30000, 32000)  # 94%: critico
    con_color = CV.barra(ancho=80, con_color=True)
    assert "\x1b[31m" in con_color and "\x1b[0m" in con_color
    assert "\x1b[" not in CV.barra(ancho=80, con_color=False)


def test_barra_arranca_sin_datos():
    assert CV.barra(ancho=80, con_color=False) == "0 tok"


# -- Aviso con histeresis -----------------------------------------------------

def test_aviso_umbral_con_histeresis():
    # n_ctx=100 => ocupacion == porcentaje, la histeresis se lee directa.
    CV.registrar_contexto(60, 100)
    assert CV.aviso_umbral() == ""

    CV.registrar_contexto(80, 100)
    assert CV.aviso_umbral() == "aviso"
    CV.registrar_contexto(82, 100)
    assert CV.aviso_umbral() == ""        # no repite el mismo aviso
    CV.registrar_contexto(88, 100)
    assert CV.aviso_umbral() == ""

    CV.registrar_contexto(92, 100)
    assert CV.aviso_umbral() == "critico"
    CV.registrar_contexto(95, 100)
    assert CV.aviso_umbral() == ""

    # Bajar de critico a aviso no vuelve a hablar (solo se avisa al ESCALAR).
    CV.registrar_contexto(86, 100)
    assert CV.aviso_umbral() == ""
    CV.registrar_contexto(80, 100)
    assert CV.aviso_umbral() == ""
    # Pero el critico ya se re-armo al bajar de 85: si vuelve a subir, avisa.
    CV.registrar_contexto(92, 100)
    assert CV.aviso_umbral() == "critico"

    # Compactar de verdad desarma todo.
    CV.registrar_contexto(30, 100)
    assert CV.aviso_umbral() == ""
    CV.registrar_contexto(78, 100)
    assert CV.aviso_umbral() == "aviso"


def test_nivel_del_estado_no_consume_el_aviso():
    CV.registrar_contexto(95, 100)
    assert CV.estado()["nivel"] == "critico"
    assert CV.estado()["nivel"] == "critico"
    assert CV.aviso_umbral() == "critico"   # estado() no armo nada


def test_sin_n_ctx_no_hay_aviso():
    CV.registrar_uso(100000, 5000)
    assert CV.aviso_umbral() == ""


# -- Concurrencia -------------------------------------------------------------

def test_acumulador_no_pierde_cuentas_entre_hilos():
    def registrar():
        for _ in range(50):
            CV.registrar_uso(10, 5, modelo="modelo-x")

    hilos = [threading.Thread(target=registrar) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    est = CV.estado()
    assert est["turnos"] == 400
    assert est["entrada"] == 4000
    assert est["salida"] == 2000
