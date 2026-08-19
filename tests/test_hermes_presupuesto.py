# -*- coding: utf-8 -*-
"""
tests/test_hermes_presupuesto.py
================================
Regresion del PRESUPUESTO POR TURNO + RAZON DE SALIDA (destilado de Hermes Agent:
agent/iteration_budget.py, agent/conversation_loop.py:1316/1342-1350/1996/6257,
agent/turn_context.py:487 y la alarma de agent/turn_finalizer.py:449).

Falla sin cognia/hermes/presupuesto_turno.py (ImportError en la coleccion).
Todo contra el modulo REAL: sin mocks, sin modelo, sin red. La concurrencia se
prueba con hilos de verdad (threading), no simulandola.

Lo que se protege, en orden de importancia:
 1. El contador es thread-safe: N hilos peleando NUNCA sobrepasan el techo.
 2. Un refund SIN motivo no pasa desapercibido, y todo refund queda registrado
    (es lo unico que permite auditar por que una tarea uso mas vueltas).
 3. La razon de salida es obligatoria: cerrar sin sellar deja 'desconocida' y
    loguea WARNING (contra "Cognia degrada en silencio").
 4. La alarma de Hermes: si el ultimo mensaje del historial es un resultado de
    tool, el cierre avisa por WARNING (el "just stops case").
 5. El envelope es serializable y trae {razon, pasos, refunds, aviso}.
"""
from __future__ import annotations

import json
import logging
import threading

import pytest

from cognia.hermes.presupuesto_turno import (
    AVISO_TOOL_PENDIENTE,
    MOTIVOS_ADMIN,
    MOTIVO_COMPACTACION,
    MOTIVO_LLAMADA_BARATA,
    MOTIVO_SIN_MOTIVO,
    RAZON_DESCONOCIDA,
    RAZON_INTERRUMPIDO,
    RAZON_PRESUPUESTO_AGOTADO,
    RAZON_RESPUESTA_TEXTO,
    PresupuestoTurno,
    RazonSalida,
    resumen_envelope,
    rol_de_mensaje,
    ultimo_es_resultado_de_tool,
)


# ---------------------------------------------------------------- contador ---
def test_consume_corta_en_el_techo():
    pres = PresupuestoTurno(3)
    assert [pres.consume() for _ in range(5)] == [True, True, True, False, False]
    assert pres.gastado == 3
    assert pres.restante == 0
    assert pres.agotado is True


def test_max_total_no_positivo_no_arranca():
    # Un techo 0/negativo no puede significar "sin freno": eso convierte un bug
    # de configuracion en un bucle infinito.
    assert PresupuestoTurno(0).consume() is False
    assert PresupuestoTurno(-7).max_total == 0
    assert PresupuestoTurno("basura").max_total == 0  # no lanza


def test_refund_devuelve_vuelta_y_reabre_presupuesto():
    pres = PresupuestoTurno(2)
    assert pres.consume() and pres.consume()
    assert pres.consume() is False           # agotado
    assert pres.refund(MOTIVO_COMPACTACION) is True
    assert pres.restante == 1
    assert pres.consume() is True            # la compactacion no se comio la tarea


def test_refund_sin_gasto_no_baja_de_cero_ni_se_registra():
    pres = PresupuestoTurno(2)
    assert pres.refund(MOTIVO_COMPACTACION) is False
    assert pres.gastado == 0
    assert pres.refunds() == []              # el registro no inventa vueltas
    assert pres.refunds_ignorados == 1


# ------------------------------------------------------------ concurrencia ---
def test_concurrencia_real_nunca_pasa_del_techo():
    """8 hilos peleando por 50 vueltas: exactamente 50 True y gastado == 50."""
    pres = PresupuestoTurno(50)
    aceptados = []
    lock = threading.Lock()
    arranque = threading.Barrier(8)

    def worker():
        arranque.wait()                      # maximiza el solape real
        propios = 0
        for _ in range(200):
            if pres.consume():
                propios += 1
        with lock:
            aceptados.append(propios)

    hilos = [threading.Thread(target=worker) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert sum(aceptados) == 50
    assert pres.gastado == 50
    assert pres.vueltas == 50
    assert pres.restante == 0


def test_concurrencia_consume_y_refund_cuadran_las_cuentas():
    """Mezcla consume/refund en 6 hilos: neto y registro tienen que cuadrar."""
    pres = PresupuestoTurno(1000)
    arranque = threading.Barrier(6)

    def worker(idx):
        arranque.wait()
        for i in range(150):
            if pres.consume() and i % 3 == 0:
                pres.refund(MOTIVO_LLAMADA_BARATA)

    hilos = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    reg = pres.refunds()
    # Invariante: neto == brutas - refunds aplicados. Si el lock no protegiera
    # el registro, esta igualdad se rompe (lista corrupta o contador perdido).
    assert pres.gastado == pres.vueltas - len(reg)
    assert pres.refunds_por_motivo() == {MOTIVO_LLAMADA_BARATA: len(reg)}
    assert len(reg) == 6 * 50                # 150/3 por hilo, ninguno perdido


# ------------------------------------------------------- registro / motivos ---
def test_refund_contabilizado_por_motivo_y_marcado_administrativo():
    pres = PresupuestoTurno(10)
    for _ in range(5):
        pres.consume()
    pres.refund(MOTIVO_COMPACTACION)
    pres.refund(MOTIVO_COMPACTACION)
    pres.refund(MOTIVO_LLAMADA_BARATA)
    pres.refund("pausa_del_dueno")           # motivo libre: no es administrativo

    assert pres.gastado == 1
    assert pres.vueltas == 5                 # las 5 vueltas SI ocurrieron
    assert pres.refunds_por_motivo() == {
        MOTIVO_COMPACTACION: 2, MOTIVO_LLAMADA_BARATA: 1, "pausa_del_dueno": 1}
    resumen = pres.resumen()
    assert resumen["refunds"] == 4
    assert resumen["refunds_administrativos"] == 3
    assert all(m in MOTIVOS_ADMIN for m in
               (MOTIVO_COMPACTACION, MOTIVO_LLAMADA_BARATA))


def test_refund_sin_motivo_queda_apuntado_y_avisa(caplog):
    pres = PresupuestoTurno(3)
    pres.consume()
    with caplog.at_level(logging.WARNING, logger="cognia.hermes.presupuesto_turno"):
        assert pres.refund("   ") is True
    assert pres.refunds_por_motivo() == {MOTIVO_SIN_MOTIVO: 1}
    assert any("sin motivo" in r.getMessage().lower() for r in caplog.records)


def test_refunds_devuelve_copia_no_el_registro_vivo():
    pres = PresupuestoTurno(3)
    pres.consume()
    pres.refund(MOTIVO_COMPACTACION)
    copia = pres.refunds()
    copia.append({"motivo": "inventado"})
    copia[0]["motivo"] = "pisado"
    assert pres.refunds_por_motivo() == {MOTIVO_COMPACTACION: 1}


# --------------------------------------------------------- razon de salida ---
def test_razon_obligatoria_cerrar_sin_sellar_avisa(caplog):
    salida = RazonSalida(PresupuestoTurno(5))
    with caplog.at_level(logging.WARNING, logger="cognia.hermes.presupuesto_turno"):
        env = salida.cerrar([])
    assert env["razon"] == RAZON_DESCONOCIDA
    assert any("SIN razon" in r.getMessage() for r in caplog.records)


def test_sellar_vacio_no_lanza_y_queda_desconocida(caplog):
    salida = RazonSalida()
    with caplog.at_level(logging.WARNING, logger="cognia.hermes.presupuesto_turno"):
        assert salida.sellar("") == RAZON_DESCONOCIDA
    assert salida.razon == RAZON_DESCONOCIDA


def test_ultimo_sello_manda_pero_se_guardan_todos():
    salida = RazonSalida()
    salida.sellar(RAZON_PRESUPUESTO_AGOTADO)
    salida.sellar(RAZON_RESPUESTA_TEXTO, "cerro con texto")
    assert salida.razon == RAZON_RESPUESTA_TEXTO
    assert [s["razon"] for s in salida.sellos] == [
        RAZON_PRESUPUESTO_AGOTADO, RAZON_RESPUESTA_TEXTO]


def test_cierre_normal_loguea_info_sin_aviso(caplog):
    pres = PresupuestoTurno(4)
    pres.consume()
    salida = RazonSalida(pres, etiqueta="tarea-7")
    salida.sellar(RAZON_RESPUESTA_TEXTO)
    with caplog.at_level(logging.INFO, logger="cognia.hermes.presupuesto_turno"):
        env = salida.cerrar([{"role": "assistant", "content": "listo"}])
    assert env["aviso"] == ""
    assert any(r.levelno == logging.INFO and "tarea-7" in r.getMessage()
               for r in caplog.records)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ------------------------------------- alarma: ultimo mensaje = tool result ---
def test_rol_de_mensaje_entiende_los_tres_formatos():
    assert rol_de_mensaje({"role": "tool", "content": "ok"}) == "tool"
    assert rol_de_mensaje({"rol": "Tool"}) == "tool"
    assert rol_de_mensaje("RESULTADO: 3 ficheros escritos") == "tool"
    assert rol_de_mensaje("Ya termine, aqui va el resumen") == ""
    assert rol_de_mensaje(None) == ""


def test_ultimo_es_resultado_de_tool_detecta_y_no_lanza():
    assert ultimo_es_resultado_de_tool([{"role": "user"}, {"role": "tool"}]) is True
    assert ultimo_es_resultado_de_tool(["ACCION: leer x", "RESULTADO: ok"]) is True
    assert ultimo_es_resultado_de_tool([{"role": "tool"}, {"role": "assistant"}]) is False
    assert ultimo_es_resultado_de_tool([]) is False
    assert ultimo_es_resultado_de_tool(None) is False
    assert ultimo_es_resultado_de_tool(object()) is False   # forma rara: no lanza


def test_warning_cuando_el_turno_acaba_en_resultado_de_tool(caplog):
    """La alarma de turn_finalizer.py:449 — el modelo se fue a medio trabajo."""
    pres = PresupuestoTurno(6)
    for _ in range(6):
        pres.consume()
    salida = RazonSalida(pres)
    salida.sellar(RAZON_PRESUPUESTO_AGOTADO)
    historial = [{"role": "assistant", "tool_calls": [1]},
                 {"role": "tool", "content": "3 tests fallaron"}]
    with caplog.at_level(logging.WARNING, logger="cognia.hermes.presupuesto_turno"):
        env = salida.cerrar(historial)
    assert env["aviso"] == AVISO_TOOL_PENDIENTE
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(avisos) == 1
    assert "tool pendiente" in avisos[0].getMessage()


def test_sin_warning_de_tool_cuando_el_turno_fue_interrumpido(caplog):
    # turn_finalizer.py:449 exige `and not interrupted`: cortar a medias por
    # peticion del usuario es lo esperado, no una patologia.
    salida = RazonSalida(PresupuestoTurno(3))
    salida.sellar(RAZON_INTERRUMPIDO)
    with caplog.at_level(logging.WARNING, logger="cognia.hermes.presupuesto_turno"):
        env = salida.cerrar([{"role": "tool", "content": "a medias"}])
    assert env["aviso"] == ""
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_cerrar_dos_veces_no_duplica_el_log(caplog):
    salida = RazonSalida(PresupuestoTurno(2))
    salida.sellar(RAZON_RESPUESTA_TEXTO)
    with caplog.at_level(logging.INFO, logger="cognia.hermes.presupuesto_turno"):
        salida.cerrar([])
        salida.cerrar([])
    assert len([r for r in caplog.records if "Turno terminado" in r.getMessage()]) == 1


# ------------------------------------------------------------- envelope -----
def test_resumen_envelope_trae_las_cuatro_claves_y_es_serializable():
    pres = PresupuestoTurno(5)
    for _ in range(4):
        pres.consume()
    pres.refund(MOTIVO_COMPACTACION)
    salida = RazonSalida(pres)
    salida.sellar(RAZON_RESPUESTA_TEXTO, "el modelo respondio sin tools")
    env = salida.cerrar([{"role": "tool"}])

    for clave in ("razon", "pasos", "refunds", "aviso"):
        assert clave in env
    assert env["razon"] == RAZON_RESPUESTA_TEXTO
    assert env["pasos"] == 3                 # neto: 4 vueltas - 1 refund
    assert env["vueltas"] == 4               # brutas: lo que de verdad costo
    assert env["restante"] == 2
    assert len(env["refunds"]) == 1
    assert env["refunds"][0]["motivo"] == MOTIVO_COMPACTACION
    assert env["aviso"] == AVISO_TOOL_PENDIENTE
    json.dumps(env)                          # serializable de verdad


def test_resumen_envelope_funciona_suelto_y_sin_presupuesto():
    # Se puede llamar solo con el presupuesto (razon desconocida) o pelado.
    pres = PresupuestoTurno(2)
    pres.consume()
    env = resumen_envelope(presupuesto=pres)
    assert env["razon"] == RAZON_DESCONOCIDA and env["pasos"] == 1
    vacio = resumen_envelope()
    assert vacio["pasos"] == 0 and vacio["refunds"] == [] and vacio["aviso"] == ""
    json.dumps(vacio)


def test_envelope_vivo_no_cierra_ni_loguea(caplog):
    salida = RazonSalida(PresupuestoTurno(3))
    salida.sellar(RAZON_RESPUESTA_TEXTO)
    with caplog.at_level(logging.INFO, logger="cognia.hermes.presupuesto_turno"):
        env = salida.resumen_envelope()
    assert env["razon"] == RAZON_RESPUESTA_TEXTO
    assert salida.cerrada is False
    assert not caplog.records


if __name__ == "__main__":                   # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
