# -*- coding: utf-8 -*-
"""
tests/test_harness_limites.py
=============================
Regresion de los LIMITES TRIPLES + CONTABILIDAD (2026-08-12).

Falla sin cognia/harness/limites.py (ImportError en la coleccion) y pasa con el.
Todo contra el modulo REAL: sin mocks y sin dobles del reloj — el unico "tiempo
falso" que se usa es retrasar `Contador.inicio`, que es aritmetica sobre un
`time.monotonic()` autentico, no un parche del reloj.

Lo que se protege, en orden de importancia:
 1. El corte es una EXCEPCION TIPADA (eje/valor/limite), no un return silencioso.
 2. Los CUATRO ejes cortan de verdad, y `None` en un eje = no corta nunca.
 3. El mensaje del corte esta en espanol y ORDENA cerrar (es el prompt siguiente).
 4. El aviso preventivo lleva NUMEROS literales y es cadena vacia mientras holgado.
 5. Los umbrales de apremio (70% / 90%) caen donde dice el contrato.
 6. El coste sale de precios por millon, y en LOCAL es exactamente 0.0.
 7. Los defectos se leen del ENTORNO al construir, no al importar.
"""
from __future__ import annotations

import copy
import math
import pickle
import time

import pytest

from cognia.harness.limites import (DEF_PASOS, EJES, PRECIOS_LOCAL, Contador,
                                    LimiteExcedido, Presupuesto,
                                    aviso_para_prompt, comprobar,
                                    coste_de_uso, restante)


def _pres(**kw) -> Presupuesto:
    """Presupuesto con TODO apagado salvo lo que pida el test (aisla el eje)."""
    base = dict(pasos_max=None, segundos_max=None, tokens_max=None, coste_max_usd=None)
    base.update(kw)
    return Presupuesto(**base)


# ── 1-2. El corte: excepcion tipada, por cada eje ──────────────────────────

def test_hay_margen_devuelve_none():
    assert comprobar(Contador(), _pres(pasos_max=5)) is None


def test_corta_por_pasos():
    c = Contador()
    p = _pres(pasos_max=3)
    for _ in range(3):
        assert comprobar(c, p) is None   # se comprueba ANTES de gastar el paso
        c.paso()
    with pytest.raises(LimiteExcedido) as e:
        comprobar(c, p)
    assert e.value.eje == "pasos"
    assert e.value.valor == 3 and e.value.limite == 3


def test_corta_por_tiempo():
    c = Contador()
    p = _pres(segundos_max=0.05)
    assert comprobar(c, p) is None
    time.sleep(0.08)                     # reloj REAL, sin parchear time
    with pytest.raises(LimiteExcedido) as e:
        comprobar(c, p)
    assert e.value.eje == "segundos"
    assert e.value.valor >= 0.05


def test_corta_por_tokens_sumando_entrada_y_salida():
    c = Contador()
    c.sumar_tokens(600, 0)
    p = _pres(tokens_max=1000)
    assert comprobar(c, p) is None
    assert c.sumar_tokens(0, 400) == 1000   # el tope es sobre el TOTAL
    with pytest.raises(LimiteExcedido) as e:
        comprobar(c, p)
    assert e.value.eje == "tokens" and e.value.valor == 1000


def test_corta_por_dinero():
    c = Contador()
    c.sumar_coste(2.0)
    p = _pres(coste_max_usd=3.0)
    assert comprobar(c, p) is None
    c.sumar_coste(1.5)
    with pytest.raises(LimiteExcedido) as e:
        comprobar(c, p)
    assert e.value.eje == "usd"


def test_none_es_sin_limite_en_cada_eje():
    c = Contador(pasos=10_000, tokens_entrada=10**9, usd=999.0)
    c.inicio -= 10_000
    assert comprobar(c, _pres()) is None      # los cuatro apagados: nunca corta


def test_con_varios_ejes_pasados_reporta_el_mas_excedido():
    c = Contador(pasos=11, tokens_entrada=5000)
    # pasos al 110%, tokens al 500% -> manda tokens aunque 'pasos' va antes en EJES
    with pytest.raises(LimiteExcedido) as e:
        comprobar(c, _pres(pasos_max=10, tokens_max=1000))
    assert e.value.eje == "tokens"


# ── 3. El mensaje es para el MODELO ────────────────────────────────────────

def test_el_mensaje_lleva_numeros_y_ordena_cerrar():
    c = Contador(pasos=40)
    with pytest.raises(LimiteExcedido) as e:
        comprobar(c, _pres(pasos_max=40))
    msg = str(e.value)
    assert "sin pasos" in msg and "40" in msg
    assert "CIERRA AHORA" in msg and "falto" in msg
    assert "herramientas" in msg          # le prohibe seguir llamando tools


def test_es_una_excepcion_de_verdad_no_un_return():
    assert issubclass(LimiteExcedido, Exception)


# ── 4-5. Margen, apremio y aviso ───────────────────────────────────────────

def test_restante_da_margen_por_eje():
    c = Contador(pasos=7, tokens_entrada=100, tokens_salida=50, usd=0.25)
    r = restante(c, Presupuesto(pasos_max=10, segundos_max=100.0,
                                tokens_max=1000, coste_max_usd=1.0))
    assert r["pasos"]["margen"] == 3 and r["pasos"]["usado"] == 7
    assert r["tokens"]["margen"] == 850
    assert r["usd"]["margen"] == pytest.approx(0.75)
    # >= 0 y no >0: en Windows monotonic salta de a ~15 ms y puede dar 0.0 exacto
    assert 0 <= r["segundos"]["usado"] < 5
    assert r["segundos"]["margen"] == pytest.approx(100.0 - r["segundos"]["usado"])
    for eje in EJES:
        assert set(r[eje]) == {"usado", "limite", "margen", "fraccion"}


def test_eje_sin_tope_no_apremia():
    r = restante(Contador(pasos=9), _pres(pasos_max=None))
    assert r["pasos"]["limite"] is None and r["pasos"]["margen"] is None
    assert r["apremio"] == "holgado" and r["eje"] is None


def test_umbrales_de_apremio():
    p = _pres(pasos_max=10)
    assert restante(Contador(pasos=6), p)["apremio"] == "holgado"
    assert restante(Contador(pasos=7), p)["apremio"] == "ajustado"   # 70% justo
    assert restante(Contador(pasos=8), p)["apremio"] == "ajustado"
    assert restante(Contador(pasos=9), p)["apremio"] == "critico"    # 90% justo
    assert restante(Contador(pasos=10), p)["eje"] == "pasos"


def test_apremio_lo_manda_el_eje_mas_exigido():
    c = Contador(pasos=1, tokens_entrada=950)
    r = restante(c, _pres(pasos_max=100, tokens_max=1000))
    assert r["eje"] == "tokens" and r["apremio"] == "critico"


def test_aviso_vacio_mientras_holgado():
    assert aviso_para_prompt(restante(Contador(pasos=1), _pres(pasos_max=10))) == ""


def test_aviso_lleva_los_numeros_literales():
    r = restante(Contador(pasos=7), _pres(pasos_max=10))
    aviso = aviso_para_prompt(r)
    assert aviso.startswith("PRESUPUESTO AJUSTADO")
    assert "te quedan 3 pasos" in aviso        # numeros, no adjetivos
    assert "justo" not in aviso and "poco" not in aviso


def test_aviso_critico_singular_y_orden_de_cerrar():
    r = restante(Contador(pasos=9), _pres(pasos_max=10))
    aviso = aviso_para_prompt(r)
    assert aviso.startswith("PRESUPUESTO CRITICO")
    assert "te queda 1 paso." in aviso         # concordancia en singular
    assert "te quedan 1" not in aviso
    assert "respuesta final" in aviso


def test_aviso_nombra_todos_los_ejes_con_tope():
    c = Contador(pasos=8, tokens_entrada=200)
    r = restante(c, _pres(pasos_max=10, tokens_max=1000))
    aviso = aviso_para_prompt(r)
    assert "2 pasos" in aviso and "800 tokens" in aviso
    assert " y " in aviso                      # se enumeran, no se pisan


# ── 6. Coste ───────────────────────────────────────────────────────────────

def test_coste_por_millon():
    # 1M de entrada a $3 + 0.5M de salida a $15 = 3 + 7.5
    assert coste_de_uso(1_000_000, 500_000,
                        {"entrada": 3.0, "salida": 15.0}) == pytest.approx(10.5)


def test_coste_local_es_cero():
    assert coste_de_uso(120_000, 8_000, PRECIOS_LOCAL) == 0.0
    assert coste_de_uso(120_000, 8_000, None) == 0.0
    assert coste_de_uso(120_000, 8_000, {}) == 0.0


def test_coste_alimenta_al_contador_y_corta():
    c = Contador()
    p = _pres(coste_max_usd=0.01)
    for _ in range(4):
        c.sumar_coste(coste_de_uso(1000, 200, {"entrada": 3.0, "salida": 15.0}))
    assert c.usd == pytest.approx(4 * (0.003 + 0.003))
    with pytest.raises(LimiteExcedido):
        comprobar(c, p)


# ── 7. Entorno ─────────────────────────────────────────────────────────────

def test_defectos_de_env_se_leen_al_construir(monkeypatch):
    monkeypatch.delenv("COGNIA_MAX_PASOS", raising=False)
    assert Presupuesto().pasos_max == DEF_PASOS
    monkeypatch.setenv("COGNIA_MAX_PASOS", "7")
    monkeypatch.setenv("COGNIA_MAX_SEGUNDOS", "12.5")
    monkeypatch.setenv("COGNIA_MAX_TOKENS", "1234")
    monkeypatch.setenv("COGNIA_MAX_USD", "0.5")
    p = Presupuesto()
    assert (p.pasos_max, p.segundos_max, p.tokens_max, p.coste_max_usd) \
        == (7, 12.5, 1234, 0.5)


def test_env_apagado_y_env_sucio(monkeypatch):
    monkeypatch.setenv("COGNIA_MAX_PASOS", "0")
    assert Presupuesto().pasos_max is None          # 0 = eje apagado
    monkeypatch.setenv("COGNIA_MAX_PASOS", "none")
    assert Presupuesto().pasos_max is None
    monkeypatch.setenv("COGNIA_MAX_PASOS", "abc")
    with pytest.warns(RuntimeWarning):              # basura -> defecto, no crash
        assert Presupuesto().pasos_max == DEF_PASOS


def test_argumento_explicito_gana_al_env(monkeypatch):
    monkeypatch.setenv("COGNIA_MAX_PASOS", "7")
    assert Presupuesto(pasos_max=3).pasos_max == 3
    assert Presupuesto(pasos_max=None).pasos_max is None


# ── Contabilidad basica ────────────────────────────────────────────────────

def test_contador_acumula():
    c = Contador()
    assert c.paso() == 1 and c.paso() == 2
    assert c.sumar_tokens(10, 5) == 15
    assert c.sumar_tokens(1, 1) == 17
    assert c.sumar_coste(0.5) == 0.5
    assert c.transcurrido() >= 0.0


def test_transcurrido_avanza():
    c = Contador()
    t0 = c.transcurrido()
    time.sleep(0.05)
    assert c.transcurrido() > t0


# ── Regresiones de la revision adversarial (2026-08-13) ────────────────────

def test_excepcion_sobrevive_a_pickle_y_deepcopy():
    """Los brazos del motor de workflows cruzan PROCESOS: si la excepcion no se
    puede reconstruir, el corte por presupuesto llega al padre como un fallo
    opaco del arnes. Antes: TypeError 'missing 2 required positional arguments'.
    """
    e = LimiteExcedido("tokens", 1000, 1000)
    for clon in (pickle.loads(pickle.dumps(e)), copy.deepcopy(e)):
        assert isinstance(clon, LimiteExcedido)
        assert (clon.eje, clon.valor, clon.limite) == ("tokens", 1000, 1000)
        assert str(clon) == str(e) and "CIERRA AHORA" in str(clon)


def test_env_no_finito_no_crea_un_limite_fantasma(monkeypatch):
    """'nan' pasaba el filtro y quedaba de tope: `val >= nan` es False, o sea el
    eje NO cortaba nunca y encima `restante` devolvia margen/fraccion NaN.
    """
    for crudo in ("nan", "+inf"):
        monkeypatch.setenv("COGNIA_MAX_SEGUNDOS", crudo)
        with pytest.warns(RuntimeWarning):
            p = Presupuesto()
        assert p.segundos_max == 900.0          # el defecto, no un NaN


def test_tope_no_finito_construido_a_mano_se_trata_como_sin_limite():
    p = _pres(segundos_max=float("nan"))
    assert p.limite("segundos") is None
    c = Contador()
    c.inicio -= 5_000
    assert comprobar(c, p) is None
    d = restante(c, p)["segundos"]
    assert d["limite"] is None and d["margen"] is None
    assert not math.isnan(d["fraccion"])


def test_env_entero_acepta_decimal_y_notacion_cientifica(monkeypatch):
    """Antes '1e3' o '40.5' caian al DEFECTO en silencio: el usuario pedia 1000
    pasos y se llevaba 40 sin enterarse (limite fantasma al reves).
    """
    monkeypatch.setenv("COGNIA_MAX_PASOS", "1e3")
    assert Presupuesto().pasos_max == 1000
    monkeypatch.setenv("COGNIA_MAX_PASOS", "40.5")
    assert Presupuesto().pasos_max == 40
    monkeypatch.setenv("COGNIA_MAX_PASOS", "0.5")
    assert Presupuesto().pasos_max == 1          # positivo -> nunca 0 ni None


def test_env_sucio_avisa_ademas_de_caer_al_defecto(monkeypatch):
    monkeypatch.setenv("COGNIA_MAX_USD", "1,50")   # coma decimal: basura
    with pytest.warns(RuntimeWarning, match="COGNIA_MAX_USD"):
        p = Presupuesto()
    assert p.coste_max_usd == 3.0


def test_tope_no_positivo_es_eje_agotado_no_holgado():
    """`techo - ya_gastado` puede dar negativo al reanudar. `comprobar` cortaba
    y `restante` decia 'holgado' (fraccion -0.0): verdugo y barra de estado
    contaban cosas distintas.
    """
    p = _pres(pasos_max=-5)
    r = restante(Contador(), p)
    assert r["pasos"]["fraccion"] == 1.0 and r["apremio"] == "critico"
    with pytest.raises(LimiteExcedido):
        comprobar(Contador(), p)


def test_aviso_singular_de_tokens():
    r = restante(Contador(tokens_entrada=999), _pres(tokens_max=1000))
    aviso = aviso_para_prompt(r)
    assert "te queda 1 token." in aviso        # antes: "te queda 1 tokens"
    assert "1 tokens" not in aviso
