# -*- coding: utf-8 -*-
"""
tests/test_autopsia_causal.py
=============================
Tests de cognia/autopsia/causal.py — atribucion causal por replay contrafactual.

Ni modelo ni red: `veredicto_fn` y `reproducir_fn` se INYECTAN, que es
exactamente la razon por la que el modulo los recibe como callables.

Lo que se protege aca (cada test nacio de un modo de fallo concreto):
  - la atribucion exacta en un caso construido a mano (si esto se rompe, el
    modulo no sirve para nada);
  - el presupuesto es un tope DURO: se cuentan las llamadas reales a
    veredicto_fn, no las que el informe dice haber hecho;
  - el caso SIN culpable no inventa uno (el error mas caro de un atribuidor);
  - el banco de inyeccion es reproducible con semilla (sin esto, ninguna
    medicion del banco es comparable entre corridas).
"""
from __future__ import annotations

import pytest

from cognia.autopsia.causal import (
    MOTIVO_IMPOSIBLE,
    MOTIVO_NO_FALLA,
    MOTIVO_TRUNCADO,
    MOTIVO_VACIA,
    ablacionar,
    atribuir,
    banco_inyeccion,
    explicar,
    linea_base_ultimo_fallido,
    linea_base_ultimo_paso,
    medir_precision,
)


# ---------------------------------------------------------------------------
# Utilidades del caso construido a mano
# ---------------------------------------------------------------------------
def _paso(accion, ok=True, **args):
    return {"action": accion, "args": args, "ok": ok, "result_head": "ok"}


def _tray_manual():
    """8 pasos; el #3 borra el fichero requerido y nadie lo vuelve a escribir.

    El invariante (propiedad de SEGURIDAD, monotona en el prefijo): si un
    fichero se llego a escribir, tiene que seguir existiendo.
    """
    return [
        _paso("leer", q="spec"),                     # 0
        _paso("guardar", path="a.txt", texto="A"),   # 1
        _paso("leer", ok=False, q="url"),            # 2  ruido: fallo recuperado
        _paso("borrar", path="a.txt"),               # 3  <-- CULPABLE (ok=True)
        _paso("pensar", q="siguiente"),              # 4
        _paso("guardar", path="b.txt", texto="B"),   # 5
        _paso("leer", ok=False, q="otra"),           # 6  ruido posterior
        _paso("pensar", q="cierre"),                 # 7
    ]


def _reproducir(sub):
    est = {"ficheros": {}, "escritos": []}
    for p in sub:
        if p["action"] == "guardar":
            est["ficheros"][p["args"]["path"]] = p["args"]["texto"]
            if p["args"]["path"] not in est["escritos"]:
                est["escritos"].append(p["args"]["path"])
        elif p["action"] == "borrar":
            est["ficheros"].pop(p["args"]["path"], None)
    return est


def _veredicto(est):
    return all(r in est["ficheros"] for r in est["escritos"])


# ---------------------------------------------------------------------------
# 1. Atribucion exacta en un caso construido a mano
# ---------------------------------------------------------------------------
def test_atribucion_exacta_caso_manual():
    tray = _tray_manual()
    inf = atribuir(tray, _veredicto, reproducir_fn=_reproducir)
    assert inf["paso_culpable"] == 3, inf
    # El contrafactual se corrio y confirmo: sin el paso 3 la tarea pasa.
    assert inf["confianza"] >= 0.9
    assert any(e["tipo"] == "ablacion" for e in inf["evidencia"])
    assert inf["truncado"] is False


def test_las_dos_lineas_base_fallan_en_el_mismo_caso():
    """El caso manual es exactamente donde las heuristicas se equivocan.

    (a) ultimo paso -> #7 (un 'pensar' inofensivo);
    (b) ultimo paso fallido -> #6 (ruido recuperado).
    Ninguna es el #3. Sin este test, el modulo podria "acertar" por casualidad
    en un caso donde las bases tambien aciertan y nadie lo notaria.
    """
    tray = _tray_manual()
    assert linea_base_ultimo_paso(tray) == 7
    assert linea_base_ultimo_fallido(tray) == 6
    assert atribuir(tray, _veredicto, reproducir_fn=_reproducir)["paso_culpable"] == 3


def test_explicar_cita_el_paso_sus_args_y_el_contrafactual():
    tray = _tray_manual()
    inf = atribuir(tray, _veredicto, reproducir_fn=_reproducir)
    txt = explicar(inf, tray)
    assert "#3" in txt
    assert "borrar" in txt
    assert "a.txt" in txt                 # los args, no solo el nombre de tool
    assert "CONTRAFACTUAL" in txt
    assert "PASA" in txt and "FALLA" in txt


# ---------------------------------------------------------------------------
# 2. La busqueda binaria respeta el presupuesto (tope DURO)
# ---------------------------------------------------------------------------
def _tray_larga(n=200, culpable=137):
    tray = [_paso("pensar", q=str(i)) for i in range(n)]
    tray[culpable] = _paso("veneno")
    return tray


def _rep_larga(sub):
    return {"veneno": any(p["action"] == "veneno" for p in sub)}


def _ver_larga(est):
    return not est["veneno"]


@pytest.mark.parametrize("presupuesto", [1, 2, 3, 4, 6, 8, 11, 12, 40])
def test_presupuesto_es_tope_duro_de_llamadas_reales(presupuesto):
    """Se cuentan las llamadas REALES a veredicto_fn, no lo que reporte el dict.

    Un informe puede mentir sobre su propio contador; el contador de fuera no.
    """
    tray = _tray_larga()
    llamadas = {"n": 0}

    def ver(est):
        llamadas["n"] += 1
        return _ver_larga(est)

    inf = atribuir(tray, ver, reproducir_fn=_rep_larga, presupuesto=presupuesto)
    assert llamadas["n"] <= presupuesto, (llamadas, inf)
    assert inf["reproducciones"] == llamadas["n"]
    assert inf["reproducciones"] <= presupuesto


def test_con_presupuesto_suficiente_acierta_una_traza_de_200_en_log2():
    """200 pasos: el punto entero del modulo es no pagar 200 reproducciones."""
    tray = _tray_larga(200, 137)
    inf = atribuir(tray, _ver_larga, reproducir_fn=_rep_larga, presupuesto=12)
    assert inf["paso_culpable"] == 137
    # 2 fronteras + ceil(log2(200))=8 + 1 ablacion = 11. Se deja margen de 1.
    assert inf["reproducciones"] <= 12
    assert inf["reproducciones"] < 200 // 4


def test_presupuesto_insuficiente_declara_truncado_y_no_finge_confianza():
    """Truncar es un resultado honesto: ventana abierta + confianza baja."""
    tray = _tray_larga(200, 137)
    inf = atribuir(tray, _ver_larga, reproducir_fn=_rep_larga, presupuesto=5)
    assert inf["truncado"] is True
    assert inf["motivo"] == MOTIVO_TRUNCADO
    assert inf["confianza"] <= 0.3
    # No se aisló: tiene que quedar constancia de la ventana sin cerrar.
    assert inf["alternativas"], inf


def test_presupuesto_uno_no_alcanza_ni_para_la_frontera():
    tray = _tray_manual()
    inf = atribuir(tray, _veredicto, reproducir_fn=_reproducir, presupuesto=1)
    assert inf["paso_culpable"] is None
    assert inf["truncado"] is True
    assert inf["confianza"] == 0.0


# ---------------------------------------------------------------------------
# 3. El caso SIN culpable: no se inventa nada
# ---------------------------------------------------------------------------
def test_tarea_imposible_no_inventa_culpable():
    """El veredicto falla ya con CERO pasos -> ningun paso puede ser la causa.

    Es el modo de fallo mas caro de un atribuidor: senalar a un paso cuando la
    tarea venia rota de fabrica (spec imposible, verificador mal configurado).
    """
    tray = _tray_manual()
    inf = atribuir(tray, lambda est: False, reproducir_fn=_reproducir)
    assert inf["paso_culpable"] is None
    assert inf["motivo"] == MOTIVO_IMPOSIBLE
    assert inf["confianza"] <= 0.1
    # Y el texto humano tiene que decirlo, no dejar un hueco ambiguo.
    txt = explicar(inf, tray)
    assert "SIN CULPABLE" in txt
    assert "inventar" in txt


def test_trayectoria_que_no_falla_no_atribuye():
    tray = _tray_manual()
    inf = atribuir(tray, lambda est: True, reproducir_fn=_reproducir)
    assert inf["paso_culpable"] is None
    assert inf["motivo"] == MOTIVO_NO_FALLA
    assert inf["confianza"] == 0.0


def test_trayectoria_vacia():
    inf = atribuir([], lambda est: False)
    assert inf["paso_culpable"] is None
    assert inf["motivo"] == MOTIVO_VACIA


def test_veredicto_none_es_error_explicito_no_un_fallo_silencioso():
    """None NO se lee como 'falla': un verificador roto y una tarea reprobada
    piden decisiones opuestas (leccion 'un fallo que devuelve None es invisible')."""
    with pytest.raises(ValueError, match="None"):
        atribuir(_tray_manual(), lambda est: None, reproducir_fn=_reproducir)


def test_veredicto_dict_con_ok_se_acepta():
    tray = _tray_manual()
    inf = atribuir(tray, lambda est: {"ok": _veredicto(est), "detalle": "x"},
                   reproducir_fn=_reproducir)
    assert inf["paso_culpable"] == 3


# ---------------------------------------------------------------------------
# Multi-causa: la confianza BAJA en vez de disimular
# ---------------------------------------------------------------------------
def test_dos_causas_bajan_la_confianza_y_lo_dicen():
    """Con dos borrados independientes, quitar UNO no arregla la tarea.

    El informe tiene que reflejarlo: senala el primero (correcto: es el primero
    que condena) pero con confianza de multi-causa, y `explicar` lo escribe.
    """
    tray = [
        _paso("guardar", path="a.txt", texto="A"),   # 0
        _paso("guardar", path="b.txt", texto="B"),   # 1
        _paso("borrar", path="a.txt"),               # 2  <-- primera causa
        _paso("borrar", path="b.txt"),               # 3  <-- segunda causa
        _paso("pensar", q="fin"),                    # 4
    ]
    inf = atribuir(tray, _veredicto, reproducir_fn=_reproducir)
    assert inf["paso_culpable"] == 2
    assert 0.3 <= inf["confianza"] <= 0.6, inf
    assert "NO confirmado" in inf["motivo"]
    assert "NO es causa suficiente" in explicar(inf, tray)


# ---------------------------------------------------------------------------
# 4. El banco de inyeccion es reproducible con semilla
# ---------------------------------------------------------------------------
def test_banco_reproducible_con_semilla():
    a = banco_inyeccion(12, semilla=3)
    b = banco_inyeccion(12, semilla=3)
    assert [c["trayectoria"] for c in a] == [c["trayectoria"] for c in b]
    assert [c["culpable"] for c in a] == [c["culpable"] for c in b]
    assert [c["tipo"] for c in a] == [c["tipo"] for c in b]


def test_banco_distinto_con_otra_semilla():
    a = banco_inyeccion(12, semilla=3)
    b = banco_inyeccion(12, semilla=4)
    assert [c["trayectoria"] for c in a] != [c["trayectoria"] for c in b]


def test_banco_respeta_el_rango_de_pasos():
    for caso in banco_inyeccion(15, semilla=5, pasos=(30, 40)):
        assert 30 <= len(caso["trayectoria"]) <= 40


def test_banco_el_culpable_es_verdad_verificable():
    """La verdad del banco no es una etiqueta: se COMPRUEBA por replay.

    Con el prefijo hasta culpable-1 el invariante aguanta; incluyendo el
    culpable, ya no. Si esto falla, el banco esta mal generado y toda la
    precision@1 medida sobre el no vale nada.
    """
    for caso in banco_inyeccion(20, semilla=2):
        tray, k = caso["trayectoria"], caso["culpable"]
        rep, ver = caso["reproducir_fn"], caso["veredicto_fn"]
        assert ver(rep(tray[:k])) is True, caso["tipo"]
        assert ver(rep(tray[:k + 1])) is False, caso["tipo"]
        assert ver(rep([])) is True            # precondicion de la biseccion
        assert ver(rep(tray)) is False         # la trayectoria completa falla


def test_banco_es_monotono_en_el_prefijo():
    """La condicion que hace VALIDA la biseccion, comprobada paso a paso."""
    for caso in banco_inyeccion(10, semilla=9):
        tray = caso["trayectoria"]
        rep, ver = caso["reproducir_fn"], caso["veredicto_fn"]
        visto_falla = False
        for k in range(len(tray) + 1):
            pasa = ver(rep(tray[:k]))
            if visto_falla:
                assert pasa is False, f"reparacion en k={k}: no es monotono"
            if not pasa:
                visto_falla = True


# ---------------------------------------------------------------------------
# medir_precision
# ---------------------------------------------------------------------------
def test_medir_precision_bate_a_las_dos_lineas_base():
    res = medir_precision(banco_inyeccion(24, semilla=7))
    assert res["n"] == 24
    assert res["precision_metodo"] > res["precision_base_ultimo_paso"]
    assert res["precision_metodo"] > res["precision_base_ultimo_fallido"]
    # El coste tiene que ser sublineal en los pasos, que es la tesis.
    assert res["reproducciones_media"] < res["pasos_media"] / 1.5


def test_medir_precision_expone_las_tres_columnas_y_el_coste():
    res = medir_precision(banco_inyeccion(8, semilla=1))
    for clave in ("precision_metodo", "precision_base_ultimo_paso",
                  "precision_base_ultimo_fallido", "reproducciones_media",
                  "por_tipo", "detalle", "abstenciones"):
        assert clave in res
    assert len(res["detalle"]) == 8


def test_medir_precision_es_determinista():
    a = medir_precision(banco_inyeccion(10, semilla=6))
    b = medir_precision(banco_inyeccion(10, semilla=6))
    assert a["precision_metodo"] == b["precision_metodo"]
    assert a["reproducciones_total"] == b["reproducciones_total"]


# ---------------------------------------------------------------------------
# ablacionar
# ---------------------------------------------------------------------------
def test_ablacionar_quita_por_indice_sin_tocar_el_resto():
    tray = _tray_manual()
    fuera = ablacionar(tray, [3])
    assert len(fuera) == len(tray) - 1
    assert all(p["action"] != "borrar" for p in fuera)
    assert fuera[0] is tray[0] and fuera[-1] is tray[-1]


def test_ablacionar_varios_indices():
    tray = _tray_manual()
    assert len(ablacionar(tray, [0, 3, 7])) == len(tray) - 3
    assert ablacionar(tray, []) == tray


def test_informe_declara_que_motor_de_ablacion_uso():
    inf = atribuir(_tray_manual(), _veredicto, reproducir_fn=_reproducir)
    assert "ablacion" in inf["motor_ablacion"] or "replay" in inf["motor_ablacion"]


# ---------------------------------------------------------------------------
# reproducir_fn por defecto (identidad): el modulo corre sin sandbox
# ---------------------------------------------------------------------------
def test_reproducir_por_defecto_es_la_identidad():
    tray = _tray_larga(40, 17)
    inf = atribuir(tray, lambda sub: not any(p["action"] == "veneno"
                                             for p in sub))
    assert inf["paso_culpable"] == 17
