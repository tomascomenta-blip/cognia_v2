# -*- coding: utf-8 -*-
"""Tests de cognia/estado/presupuesto_progreso.py.

Sin modelo y sin red: todo el coste y todos los resultados de verificacion se
INYECTAN. El unico toque de disco es `tmp_path` en los tests de fichero, que es
justamente lo que ese observador tiene que comprobar de verdad.
"""

import json

import pytest

from cognia.estado.presupuesto_progreso import (
    FACTOR_MESETA_COSTE,
    PASOS_SIN_AVANCE_ESTANCADO,
    PASOS_SIN_AVANCE_SIN_ARRANQUE,
    TIPOS_AVANCE,
    TIPO_ERROR,
    TIPO_FICHERO,
    TIPO_PENDIENTE,
    TIPO_POSTCONDICION,
    TIPO_TEST,
    Progreso,
    comparar,
)


# -- Los seis tipos de avance -----------------------------------------------

def test_los_tipos_existen_y_son_los_esperados():
    # 'artefacto_crecio_valido' se anadio el 2026-08-30: un fichero que crece
    # y sigue siendo valido es la unica forma de progreso observable de una
    # tarea que construye UN artefacto grande por partes.
    assert set(TIPOS_AVANCE) == {
        "fichero_nuevo_valido",
        "test_en_verde",
        "postcondicion_cumplida",
        "error_resuelto",
        "pendiente_resuelto",
        "artefacto_crecio_valido",
    }


def test_tipo_fichero_nuevo_valido_py_que_compila(tmp_path):
    p = Progreso()
    f = tmp_path / "modulo.py"
    f.write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    r = p.observar_fichero(f)
    assert r["avance"]["tipo"] == TIPO_FICHERO
    assert "compila" in r["motivo"]


def test_tipo_fichero_no_cuenta_si_no_compila(tmp_path):
    p = Progreso()
    f = tmp_path / "roto.py"
    f.write_text("def suma(a, b\n    return a + b\n", encoding="utf-8")
    r = p.observar_fichero(f)
    assert r["avance"] is None
    assert p.avances == []


def test_tipo_fichero_no_cuenta_si_esta_vacio(tmp_path):
    p = Progreso()
    f = tmp_path / "vacio.py"
    f.write_text("   \n", encoding="utf-8")
    assert p.observar_fichero(f)["avance"] is None


def test_tipo_fichero_cuenta_una_sola_vez_por_ruta(tmp_path):
    # Reescribir el mismo fichero no es progreso nuevo: si lo fuera, un bucle que
    # regraba el mismo modulo pareceria avanzar para siempre.
    p = Progreso()
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert p.observar_fichero(f)["avance"] is not None
    f.write_text("x = 2\n", encoding="utf-8")
    assert p.observar_fichero(f)["avance"] is None
    assert len(p.avances) == 1


def test_tipo_test_en_verde_solo_en_la_transicion_rojo_verde():
    p = Progreso()
    assert p.observar_verificacion("pytest tests/t.py", False)["avance"] is None
    r = p.observar_verificacion("pytest tests/t.py", True, evidencia="1 passed in 0.2s")
    assert r["avance"]["tipo"] == TIPO_TEST
    assert r["transicion"] == "rojo->verde"
    # verde -> verde: correr el mismo test otra vez NO suma
    assert p.observar_verificacion("pytest tests/t.py", True)["avance"] is None
    assert len(p.avances) == 1


def test_test_en_verde_sin_haber_estado_rojo_no_cuenta():
    # Un test que ya estaba verde al empezar no es merito de esta corrida.
    p = Progreso()
    r = p.observar_verificacion("pytest ya_verde", True, evidencia="1 passed")
    assert r["avance"] is None
    assert r["transicion"] == "primera_observacion"


def test_verde_a_rojo_se_registra_como_regresion_y_no_como_avance():
    p = Progreso()
    p.observar_verificacion("t", False)
    p.observar_verificacion("t", True, evidencia="ok")
    r = p.observar_verificacion("t", False, evidencia="1 failed")
    assert r["avance"] is None
    assert r["transicion"] == "verde->rojo"
    assert len(p.regresiones) == 1
    assert len(p.avances) == 1


def test_tipo_error_resuelto():
    p = Progreso()
    p.observar_error("ModuleNotFoundError: cognia.x", True, evidencia="traceback")
    r = p.observar_error("ModuleNotFoundError: cognia.x", False, evidencia="import OK")
    assert r["avance"]["tipo"] == TIPO_ERROR
    assert r["transicion"] == "presente->ausente"


def test_tipo_postcondicion_cumplida():
    p = Progreso()
    p.observar_postcondicion("el CLI arranca", False)
    r = p.observar_postcondicion("el CLI arranca", True, evidencia="exit 0")
    assert r["avance"]["tipo"] == TIPO_POSTCONDICION


def test_tipo_pendiente_resuelto():
    p = Progreso()
    r = p.observar_pendiente("P-3 documentar limites", True, evidencia="commit abc123")
    assert r["avance"]["tipo"] == TIPO_PENDIENTE
    # cerrarlo dos veces sigue siendo un solo avance
    assert p.observar_pendiente("P-3 documentar limites", True, evidencia="x")["avance"] is None
    assert len(p.avances) == 1


def test_los_tipos_se_pueden_acumular_en_una_corrida(tmp_path):
    p = Progreso(nombre="todos")
    f = tmp_path / "a.py"
    f.write_text("y = 1\n", encoding="utf-8")
    p.gastar(tokens=10)
    p.observar_fichero(f)
    # y el sexto tipo: el MISMO fichero, mas grande y todavia valido
    f.write_text("y = 1\n" + "z = 2\n" * 100, encoding="utf-8")
    p.observar_fichero(f)
    p.observar_verificacion("t", False)
    p.observar_verificacion("t", True, evidencia="1 passed")
    p.observar_postcondicion("pc", False)
    p.observar_postcondicion("pc", True, evidencia="ok")
    p.observar_error("E", True)
    p.observar_error("E", False, evidencia="ya no sale")
    p.observar_pendiente("P1", True, evidencia="hecho")
    assert p.informe()["avances_por_tipo"] == {t: 1 for t in TIPOS_AVANCE}


# -- Un avance sin evidencia no es un avance --------------------------------

def test_avanzar_exige_tipo_conocido():
    p = Progreso()
    with pytest.raises(ValueError):
        p.avanzar("progreso_conceptual", "entendi el bug", "confio en mi")


def test_avanzar_exige_evidencia_no_vacia():
    p = Progreso()
    with pytest.raises(ValueError):
        p.avanzar(TIPO_TEST, "tests/t.py", "   ")


def test_gastar_rechaza_coste_negativo():
    p = Progreso()
    with pytest.raises(ValueError):
        p.gastar(tokens=-1)


# -- El estancamiento se detecta en el PASO esperado -----------------------

def test_sin_arranque_se_declara_exactamente_en_el_paso_del_umbral():
    # Corrida que no arranca: gasta y nunca verifica nada.
    p = Progreso(nombre="no_arranca")
    vistos = []
    for i in range(1, PASOS_SIN_AVANCE_SIN_ARRANQUE + 1):
        p.gastar(tokens=1000, segundos=30.0)
        vistos.append(p.veredicto()["estado"])
    # ni uno antes del umbral
    assert vistos[:-1] == ["avanza"] * (PASOS_SIN_AVANCE_SIN_ARRANQUE - 1)
    assert vistos[-1] == "estancado"
    v = p.veredicto()
    assert v["motivo"] == "sin_arranque"
    assert v["evidencia"]["pasos_sin_avance"] == PASOS_SIN_AVANCE_SIN_ARRANQUE
    assert v["evidencia"]["tokens_sin_avance"] == 1000 * PASOS_SIN_AVANCE_SIN_ARRANQUE
    assert "cierra" in v["sugerencia"]


def test_meseta_se_declara_en_el_paso_del_umbral_tras_un_avance():
    p = Progreso(nombre="se_atasca")
    p.gastar(tokens=1000)
    p.observar_verificacion("t1", False)
    p.gastar(tokens=1000)
    p.observar_verificacion("t1", True, evidencia="1 passed")   # avance en el paso 2
    estados = []
    for _ in range(PASOS_SIN_AVANCE_ESTANCADO):
        p.gastar(tokens=1000)
        estados.append(p.veredicto()["estado"])
    assert estados[:-1] == ["avanza"] * (PASOS_SIN_AVANCE_ESTANCADO - 1)
    assert estados[-1] == "estancado"
    v = p.veredicto()
    assert v["motivo"] == "meseta"
    assert v["evidencia"]["pasos"] == 2 + PASOS_SIN_AVANCE_ESTANCADO
    assert v["evidencia"]["avances"] == 1


def test_una_corrida_que_avanza_nunca_se_declara_estancada():
    # 40 pasos, un avance verificado cada 3 pasos (por debajo de los umbrales).
    p = Progreso(nombre="avanza")
    for paso in range(1, 41):
        p.gastar(tokens=1500, segundos=20.0)
        if paso % 3 == 0:
            clave = "check_%d" % paso
            p.observar_verificacion(clave, False)
            p.observar_verificacion(clave, True, evidencia="verde en el paso %d" % paso)
        assert p.veredicto()["estado"] == "avanza", "paso %d" % paso
    assert len(p.avances) == 13


def test_meseta_de_coste_usa_la_mediana_de_la_propia_corrida():
    # Dos avances baratos fijan la mediana; luego un tramo caro sin avance.
    p = Progreso(nombre="cara", umbral_estancado=10_000)  # se apaga la regla de pasos
    for clave in ("a", "b"):
        p.gastar(tokens=1000)
        p.observar_verificacion(clave, False)
        p.observar_verificacion(clave, True, evidencia="ok")
    mediana = p._mediana_coste_por_avance()
    assert mediana == 1000
    p.gastar(tokens=int(FACTOR_MESETA_COSTE * mediana))
    assert p.veredicto()["estado"] == "avanza"          # justo en el limite, no corta
    p.gastar(tokens=1)
    v = p.veredicto()
    assert v["estado"] == "estancado"
    assert v["motivo"] == "meseta_de_coste"


def test_un_solo_avance_no_dispara_la_regla_de_coste():
    # Con un unico avance la "mediana" seria ese dato: cortar ahi es cortar por ruido.
    p = Progreso(umbral_estancado=10_000)
    p.gastar(tokens=100)
    p.observar_verificacion("a", False)
    p.observar_verificacion("a", True, evidencia="ok")
    p.gastar(tokens=100_000)
    assert p.veredicto()["estado"] == "avanza"


def test_agotado_manda_sobre_el_resto_y_dice_el_eje():
    p = Progreso(nombre="tope", tope_tokens=5000)
    p.gastar(tokens=5000)
    v = p.veredicto()
    assert v["estado"] == "agotado"
    assert v["motivo"] == "tope_tokens"
    assert v["evidencia"]["valor"] == 5000 and v["evidencia"]["limite"] == 5000


def test_agotado_por_pasos_y_por_segundos():
    a = Progreso(tope_pasos=3)
    for _ in range(3):
        a.gastar(tokens=1)
    assert a.veredicto()["motivo"] == "tope_pasos"

    b = Progreso(tope_segundos=10.0)
    b.gastar(tokens=1, segundos=10.0)
    assert b.veredicto()["motivo"] == "tope_segundos"


# -- tasa() y curva() -------------------------------------------------------

def test_tasa_por_1k_tokens_y_por_minuto():
    p = Progreso()
    p.gastar(tokens=2000, segundos=120.0)
    p.observar_verificacion("t", False)
    p.observar_verificacion("t", True, evidencia="ok")
    t = p.tasa()
    assert t["por_1k_tokens"] == 0.5      # 1 avance / 2k tokens
    assert t["por_minuto"] == 0.5         # 1 avance / 2 min
    assert t["tokens_por_avance"] == 2000.0


def test_tasa_sin_avances_no_miente_con_ceros():
    p = Progreso()
    p.gastar(tokens=1000)
    t = p.tasa()
    assert t["avances"] == 0
    assert t["por_1k_tokens"] == 0.0
    assert t["tokens_por_avance"] is None   # None, no 0: no hay division que hacer


def test_tasa_no_reporta_coste_por_avance_si_nadie_conto_tokens():
    # Un arnes que solo mide segundos (backend sin `usage`) no debe leer
    # "0.0 tokens por avance", que se lee como "salio gratis".
    p = Progreso()
    p.gastar(tokens=0, segundos=60.0)
    p.observar_verificacion("t", False)
    p.observar_verificacion("t", True, evidencia="ok")
    t = p.tasa()
    assert t["tokens_por_avance"] is None
    assert t["por_1k_tokens"] is None
    assert t["segundos_por_avance"] == 60.0


def test_curva_es_monotona_y_marca_el_paso_del_avance():
    p = Progreso()
    for paso in range(1, 6):
        p.gastar(tokens=100, segundos=1.0)
        if paso == 3:
            p.observar_verificacion("t", False)
            p.observar_verificacion("t", True, evidencia="ok")
    c = p.curva()
    assert [x["paso"] for x in c] == [1, 2, 3, 4, 5]
    assert [x["tokens"] for x in c] == [100, 200, 300, 400, 500]
    assert [x["avances_acum"] for x in c] == [0, 0, 1, 1, 1]
    assert c[2]["avances"] == 1


# -- comparar() a iso-coste -------------------------------------------------

def _corrida(nombre, tokens_por_paso, pasos_con_avance, pasos):
    p = Progreso(nombre=nombre, umbral_estancado=10_000, umbral_arranque=10_000)
    for i in range(1, pasos + 1):
        p.gastar(tokens=tokens_por_paso)
        if i in pasos_con_avance:
            clave = "%s_%d" % (nombre, i)
            p.observar_verificacion(clave, False)
            p.observar_verificacion(clave, True, evidencia="ok")
    return p


def test_comparar_trunca_al_coste_comun_y_no_premia_al_que_mas_gasto():
    # B logra 3 avances pero gastando el TRIPLE. A iso-coste (10k) B solo tiene 1.
    a = _corrida("a", 1000, {2, 5, 9}, 10)     # 10.000 tokens, 3 avances
    b = _corrida("b", 3000, {3, 6, 9}, 10)     # 30.000 tokens, 3 avances
    r = comparar(a, b)
    assert r["coste_comun_tokens"] == 10_000
    assert r["avances_a"] == 3
    assert r["avances_b"] == 1                  # solo el del paso 3 (9.000 tokens)
    assert r["ganador"] == "a"
    assert r["margen"] == 2
    assert r["por_1k_a"] == 0.3 and r["por_1k_b"] == 0.1
    assert r["tokens_totales_b"] == 30_000


def test_comparar_empate_y_simetria():
    a = _corrida("a", 1000, {2, 4}, 6)
    b = _corrida("b", 1000, {3, 5}, 6)
    r = comparar(a, b)
    assert r["ganador"] == "empate" and r["margen"] == 0
    inv = comparar(b, a)
    assert inv["avances_a"] == r["avances_b"] and inv["avances_b"] == r["avances_a"]


def test_comparar_sin_coste_no_inventa_ganador():
    a = Progreso(nombre="a")
    b = _corrida("b", 1000, {1}, 3)
    r = comparar(a, b)
    assert r["ganador"] == "empate"
    assert r["coste_comun_tokens"] == 0
    assert "iso-coste" in r["nota"]


# -- El informe es json-able ------------------------------------------------

def test_informe_es_json_able_y_reversible(tmp_path):
    p = Progreso(nombre="informe", tope_tokens=50_000, tope_segundos=600.0, tope_pasos=40)
    f = tmp_path / "z.py"
    f.write_text("z = 0\n", encoding="utf-8")
    for paso in range(1, 8):
        p.gastar(tokens=900, segundos=12.5)
        if paso == 2:
            p.observar_fichero(f)
        if paso == 4:
            p.observar_error("KeyError: 'x'", True)
            p.observar_error("KeyError: 'x'", False, evidencia="ya no aparece")
    inf = p.informe()
    crudo = json.dumps(inf, ensure_ascii=False)      # lanza si algo no es serializable
    vuelta = json.loads(crudo)
    assert vuelta == inf
    assert set(inf) == {
        "corrida", "coste", "topes", "umbrales", "avances", "avances_por_tipo",
        "regresiones", "tasa", "curva", "veredicto",
    }
    assert inf["coste"] == {"tokens": 6300, "segundos": 87.5, "pasos": 7}
    assert inf["avances_por_tipo"] == {TIPO_FICHERO: 1, TIPO_ERROR: 1}


def test_informe_de_una_corrida_vacia_tambien_serializa():
    assert json.loads(json.dumps(Progreso().informe()))["veredicto"]["estado"] == "avanza"
