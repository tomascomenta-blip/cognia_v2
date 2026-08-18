# -*- coding: utf-8 -*-
"""Tests del BANCO de sintesis del RLM (scripts/banco_rlm_sintesis.py).

Por que existe: el banco es el instrumento, y este repo tiene la cicatriz de
cinco fallos seguidos que eran del instrumento y no del modelo. Aca se prueba
el banco antes de creerle un solo numero: que el oraculo saque 100%, que la
verdad del texto y la verdad de los datos coincidan, que el calificador no
regale ni robe aciertos, y que el brazo de azar sea leave-one-out de verdad.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "banco_rlm_sintesis", RAIZ / "scripts" / "banco_rlm_sintesis.py")
b = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(b)


@pytest.fixture(scope="module")
def banco():
    datos = b.generar_datos()
    items = b.construir_preguntas(datos)
    return datos, items, b.renderizar(datos, 0)


# ── el instrumento se aprueba a si mismo o no se usa ───────────────────


def test_oraculo_saca_todo(banco):
    _, items, _ = banco
    r = b.brazo_oraculo(items)
    assert r["aciertos"] == r["n"] == 90


def test_cada_verdad_esta_en_su_espacio(banco):
    """Sin esto el brazo de azar tendria probabilidad 0 por construccion y
    'ganarle al azar' seria ganarle a un espacio que no contiene la
    respuesta."""
    _, items, _ = banco
    for it in items:
        assert str(it["respuesta"]) in [str(v) for v in it["espacio"]], it["id"]


def test_seis_tipos_equilibrados(banco):
    _, items, _ = banco
    conteo = {}
    for it in items:
        conteo[it["tipo"]] = conteo.get(it["tipo"], 0) + 1
    assert sorted(conteo) == ["comparar_campo", "comparar_ndif",
                              "contar_conjuncion", "contar_simple",
                              "cruzar_auditor", "cruzar_contar"]
    assert set(conteo.values()) == {15}


# ── el corpus dice lo mismo que los datos ──────────────────────────────


def test_conteo_del_texto_igual_al_de_los_datos(banco):
    """La verdad se calcula de los datos; aca se comprueba contra el TEXTO
    renderizado, contando ocurrencias a mano. Si el renderizador perdiera o
    duplicara un bloque, el banco mediria una verdad que no esta escrita."""
    datos, items, texto = banco
    for it in items:
        if it["tipo"] != "contar_simple":
            continue
        patron = "%s: %s\n" % (it["meta"]["campo"], it["meta"]["valor"])
        assert texto.count(patron) == it["respuesta"], it["id"]


def test_relleno_no_contamina_los_conteos(banco):
    """El relleno no tiene digitos ni valores de campo: la celda NO_CABE
    (2 M de relleno) tiene que dar EXACTAMENTE los mismos conteos que la
    celda CABE (relleno 0)."""
    datos, items, compacto = banco
    grande = b.renderizar(datos, 200_000)
    assert len(grande) > 5 * len(compacto)
    for it in items:
        if it["tipo"] != "contar_simple":
            continue
        patron = "%s: %s\n" % (it["meta"]["campo"], it["meta"]["valor"])
        assert grande.count(patron) == compacto.count(patron)


def test_render_determinista(banco):
    datos, _, compacto = banco
    assert b.renderizar(b.generar_datos(), 0) == compacto


def test_pares_de_comparar_difieren_en_lo_declarado(banco):
    datos, items, _ = banco
    por_id = {d["id"]: d for d in datos["docs"]}
    for it in items:
        if not it["tipo"].startswith("comparar"):
            continue
        i1, i2 = it["meta"]["par"]
        dif = [c for c in b.CAMPOS if por_id[i1][c] != por_id[i2][c]]
        if it["tipo"] == "comparar_campo":
            assert dif == [it["respuesta"]], it["id"]
        else:
            assert len(dif) == it["respuesta"], it["id"]


def test_cruzar_es_de_dos_saltos(banco):
    """El informe no nombra al auditor: la respuesta SOLO esta en el bloque
    de auditoria del lote. Si el nombre estuviera en el mismo bloque, la
    familia CRUZAR seria localizacion disfrazada."""
    datos, items, _ = banco
    por_id = {d["id"]: d for d in datos["docs"]}
    for it in items:
        if it["tipo"] != "cruzar_auditor":
            continue
        bloque = b._bloque_doc(por_id[it["meta"]["doc"]])
        assert it["respuesta"] not in bloque
        assert it["meta"]["lote"] in bloque


# ── el calificador ─────────────────────────────────────────────────────


def test_califica_entero_exacto():
    it = {"tipo_respuesta": "int", "respuesta": 7}
    assert b.calificar(it, "bla bla\nRESPUESTA: 7")["ok"]
    assert not b.calificar(it, "RESPUESTA: 8")["ok"]


def test_un_error_de_uno_no_es_acierto_pero_se_registra():
    it = {"tipo_respuesta": "int", "respuesta": 7}
    r = b.calificar(it, "RESPUESTA: 8")
    assert not r["ok"] and r["cerca"]


def test_vale_la_ultima_respuesta_no_la_primera():
    """El modelo suele razonar en voz alta y corregirse: la que cuenta es la
    ultima linea RESPUESTA, no un numero suelto de la deliberacion."""
    it = {"tipo_respuesta": "int", "respuesta": 5}
    assert b.calificar(it, "creo RESPUESTA: 3\nme corrijo\nRESPUESTA: 5")["ok"]


def test_nombre_sin_tildes_y_con_ruido():
    it = {"tipo_respuesta": "str", "respuesta": "Melquiades"}
    assert b.calificar(it, "RESPUESTA: **melquiades**.")["ok"]
    assert not b.calificar(it, "RESPUESTA: Jacinto")["ok"]


def test_falta_de_formato_se_marca_aparte():
    """Un fallo de formato es del instrumento hasta que se demuestre lo
    contrario: se cuenta en sin_formato y no se confunde con no saber."""
    it = {"tipo_respuesta": "int", "respuesta": 4}
    r = b.calificar(it, "el resultado es 4")
    assert not r["formato_ok"]
    assert r["ok"]      # el respaldo lo lee igual, pero queda marcado


# ── los brazos de referencia ───────────────────────────────────────────


def test_marginal_es_leave_one_out():
    """Si el marginal viera su propia respuesta, un banco con respuestas
    todas distintas le daria 1/n gratis por item en vez de 0."""
    items = [{"tipo": "t", "respuesta": i, "espacio": list(range(10))}
             for i in range(5)]
    assert b._prob_marginal(items) == [0.0] * 5
    iguales = [{"tipo": "t", "respuesta": 3, "espacio": list(range(10))}
               for _ in range(5)]
    assert b._prob_marginal(iguales) == [1.0] * 5


def test_uniforme_usa_el_espacio_declarado():
    items = [{"tipo": "t", "respuesta": 1, "espacio": [1, 2, 3, 4]}]
    assert b._prob_uniforme(items) == [0.25]


def test_techo_tonto_extremos(banco):
    """Con el corpus entero visible el techo es el oraculo; sin nada visible
    es cero. Entre medio esta la curva que decide si el brazo tonto es un
    rival o un espantapajaros."""
    datos, items, texto = banco
    assert b.techo_tonto(items, datos, texto, len(texto))["aciertos"] == 90
    assert b.techo_tonto(items, datos, texto, 0)["aciertos"] == 0


def test_techo_tonto_cae_al_nivel_del_azar_cuando_ve_la_mitad(banco):
    """El hallazgo que decide el diseno: el camino tonto no pierde exactitud
    de a poco, se DERRUMBA. Con la mitad del corpus su techo de informacion
    ya esta al nivel del azar marginal (~15%)."""
    datos, items, _ = banco
    texto = b.renderizar(datos, 200_000)
    mitad = b.techo_tonto(items, datos, texto, len(texto) // 2)
    assert mitad["exactitud"] < 0.25


def test_mcnemar_extremos():
    assert b.mcnemar_exacto([True] * 5, [True] * 5)["p"] == 1.0
    r = b.mcnemar_exacto([True] * 10, [False] * 10)
    assert r["b"] == 10 and r["c"] == 0 and r["p"] < 0.01


def test_mde_baja_al_crecer_n():
    """La potencia se calcula ANTES de matar una via: este test fija que el
    calculo responde a N y no es una constante decorativa."""
    chico = [{"tipo": "t", "respuesta": 1, "espacio": [1, 2, 3, 4, 5]}
             for _ in range(20)]
    grande = chico * 5
    m_chico = b.mde(b._prob_uniforme(chico),
                    b.simular_azar(chico, b._prob_uniforme(chico),
                                   B=20000)["dist"], B=4000)
    m_grande = b.mde(b._prob_uniforme(grande),
                     b.simular_azar(grande, b._prob_uniforme(grande),
                                    B=20000)["dist"], B=4000)
    assert m_grande < m_chico


def test_el_par_de_comparar_solo_difiere_en_los_campos_declarados(banco):
    """El fix del 2026-08-18: con lote unico por documento el par diferia
    tambien en 'Lote auditado' — un octavo campo que la pregunta no lista — y
    el modelo contestaba 'lote auditado' con razon mientras el banco lo
    puntuaba mal. Aca se fija a nivel de BLOQUE renderizado: quitando la
    linea del encabezado y las lineas de los campos mutados, los dos bloques
    tienen que ser identicos caracter a caracter."""
    datos, items, _ = banco
    por_id = {d["id"]: d for d in datos["docs"]}
    vistos = 0
    for it in items:
        if not it["tipo"].startswith("comparar"):
            continue
        i1, i2 = it["meta"]["par"]
        d1, d2 = por_id[i1], por_id[i2]
        assert d1["Lote"] == d2["Lote"]
        mut = [c for c in b.CAMPOS if d1[c] != d2[c]]

        def resto(d):
            return [ln for ln in b._bloque_doc(d).splitlines()
                    if not ln.startswith("=== INFORME")
                    and not any(ln.startswith(c + ":") for c in mut)]
        assert resto(d1) == resto(d2), it["id"]
        vistos += 1
    assert vistos == 30
