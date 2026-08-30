# -*- coding: utf-8 -*-
"""
tests/test_arnes_tareas_largas.py
=================================
Regresion de la corrida REAL del 2026-08-30 (minecraft.html): cuatro cortes
independientes del arnes, todos del mismo signo, mataban las tareas cuyo
objeto es un fichero grande. Medido antes de tocar nada:

  * presupuesto de la tarea: 8 pasos (dificultad 0,351 sobre 267 caracteres)
  * umbral de arranque: 6 pasos sin avance verificado
  * coste de LEER el fichero de 32.585 bytes que habia que editar:
    1 `listar` + 1 `leer_archivo` + 5 `recuperar` = SIETE pasos
  * `observar_fichero` solo contaba la transicion inexistente->valido, asi que
    construir el fichero por partes (1 escritura + N apendices) registraba UN
    avance y despues parecia parado
  * el nudge por fichero (umbral 3) obligaba a releerlo entero cada 3 partes

Resultado real: tres corridas seguidas cerradas por 'sin_arranque' en el paso
6 sin escribir NADA, y una cuarta por 'meseta' en el paso 8 con el fichero a
medias. Cada test de aqui fija uno de los cuatro arreglos, y el ultimo replica
la corrida entera con su CONTRAFACTUAL (la configuracion vieja).
"""
from __future__ import annotations

import random

import pytest

from cognia.estado.presupuesto_progreso import (
    CREDITO_EXPLORACION,
    MIN_CRECIMIENTO_BYTES,
    TIPO_CRECIMIENTO,
    TIPO_FICHERO,
    Progreso,
)
from cognia.harness import offloading as off
from cognia.harness import repeticion as rep
from cognia.hermes.presupuesto_turno import PresupuestoTurno

NL = chr(10)


def _texto(n_lineas):
    return NL.join("linea %05d de contenido del artefacto" % i
                   for i in range(n_lineas))


@pytest.fixture(autouse=True)
def _entorno_limpio(tmp_path, monkeypatch):
    """El offload nunca es el ~/.cognia real y ningun knob viene heredado."""
    monkeypatch.setenv("COGNIA_OFFLOAD_DIR", str(tmp_path / "off"))
    for var in ("COGNIA_TOOL_RESULT_MAX", "COGNIA_TOOL_RESULT_MAX_LECTURA",
                "COGNIA_OFFLOAD_CABEZA", "COGNIA_OFFLOAD_COLA",
                "COGNIA_REPETICION_UMBRAL_FICHERO",
                "COGNIA_REPETICION_UMBRAL_APENDICE"):
        monkeypatch.delenv(var, raising=False)


# -- 1. Un artefacto que CRECE es progreso -----------------------------------

def test_el_fichero_que_crece_por_partes_suma_avances(tmp_path):
    p = Progreso()
    f = tmp_path / "juego.html"
    f.write_text(_texto(50), encoding="utf-8")
    assert p.observar_fichero(f)["avance"]["tipo"] == TIPO_FICHERO
    # cada apendice real es un avance NUEVO, del tipo crecimiento
    for i in range(4):
        f.write_text(f.read_text(encoding="utf-8") + NL + _texto(50),
                     encoding="utf-8")
        r = p.observar_fichero(f)
        assert r["avance"] is not None, "el apendice %d no conto" % i
        assert r["avance"]["tipo"] == TIPO_CRECIMIENTO
    assert len(p.avances) == 5


def test_el_churn_que_reescribe_lo_mismo_no_es_crecimiento(tmp_path):
    """A -> B -> A no crece nunca: es la propiedad anti-gaming del modulo."""
    p = Progreso()
    f = tmp_path / "a.txt"
    a = _texto(200)
    b = a.replace("contenido", "CONTENIDO")
    f.write_text(a, encoding="utf-8")
    p.observar_fichero(f)
    for _ in range(6):
        f.write_text(b, encoding="utf-8")
        assert p.observar_fichero(f)["avance"] is None
        f.write_text(a, encoding="utf-8")
        assert p.observar_fichero(f)["avance"] is None
    assert len(p.avances) == 1


def test_un_retoque_minusculo_no_cuenta_como_crecimiento(tmp_path):
    p = Progreso()
    f = tmp_path / "a.txt"
    f.write_text("x" * 1000, encoding="utf-8")
    p.observar_fichero(f)
    f.write_text("x" * (1000 + MIN_CRECIMIENTO_BYTES - 1), encoding="utf-8")
    assert p.observar_fichero(f)["avance"] is None
    f.write_text("x" * (1000 + MIN_CRECIMIENTO_BYTES), encoding="utf-8")
    assert p.observar_fichero(f)["avance"] is not None


def test_un_fichero_que_deja_de_compilar_sigue_siendo_regresion(tmp_path):
    """El crecimiento no puede tapar una rotura: mas grande y roto es peor."""
    p = Progreso()
    f = tmp_path / "m.py"
    f.write_text("a = 1" + NL, encoding="utf-8")
    p.observar_fichero(f)
    f.write_text("a = 1" + NL + "def roto(" + NL + "x" * 500, encoding="utf-8")
    r = p.observar_fichero(f)
    assert r["avance"] is None and r["valido"] is False
    assert p.regresiones


# -- 2. Leer no es estar atascado --------------------------------------------

def test_los_pasos_de_lectura_no_gastan_credito_de_arranque():
    p = Progreso(umbral_arranque=6)
    for _ in range(7):                      # los 7 pasos que costaba leer
        p.gastar(tokens=1000, pasos=1, exploratorio=True)
    assert p.pasos_sin_avance() == 7
    assert p.pasos_efectivos_sin_avance() == 7 - CREDITO_EXPLORACION + 1
    assert p.veredicto()["estado"] == "avanza"


def test_el_credito_de_exploracion_es_finito():
    p = Progreso(umbral_arranque=6)
    for _ in range(CREDITO_EXPLORACION + 6):
        p.gastar(tokens=100, pasos=1, exploratorio=True)
    assert p.veredicto()["motivo"] == "sin_arranque"


def test_los_pasos_efectivos_nunca_superan_a_los_crudos():
    """La propiedad que garantiza CERO falsas alarmas nuevas: esta regla solo
    puede retrasar un corte, jamas adelantarlo."""
    rnd = random.Random(7)
    for _ in range(200):
        p = Progreso()
        for _ in range(rnd.randint(1, 20)):
            p.gastar(tokens=10, pasos=1, exploratorio=rnd.random() < 0.5)
        assert p.pasos_efectivos_sin_avance() <= p.pasos_sin_avance()


def test_marcar_exploratorio_marca_el_ultimo_paso():
    p = Progreso()
    p.gastar(tokens=10)
    assert p.exploratorios_sin_avance() == 0
    assert p.marcar_exploratorio() is True
    assert p.exploratorios_sin_avance() == 1
    assert Progreso().marcar_exploratorio() is False   # sin gasto previo


def test_un_paso_que_escribe_no_es_exploratorio():
    """El integrador solo marca el paso si TODAS sus tools son puras."""
    from cognia.agent.loop import TOOLS_EXPLORATORIAS
    assert "leer_archivo" in TOOLS_EXPLORATORIAS
    assert "recuperar" in TOOLS_EXPLORATORIAS
    assert "escribir_archivo" not in TOOLS_EXPLORATORIAS
    assert "apendar_archivo" not in TOOLS_EXPLORATORIAS
    assert "ejecutar" not in TOOLS_EXPLORATORIAS


# -- 3. Lo que el agente pidio por su nombre no es ruido ----------------------

def test_una_lectura_del_tamano_del_caso_real_llega_entera():
    """32.585 bytes es el minecraft.html que mato tres corridas seguidas."""
    crudo = "x" * 32585
    assert off.resumir_para_modelo(crudo, tool="leer_archivo") == crudo
    assert off.resumir_para_modelo(crudo, tool="recuperar") == crudo


def test_el_ruido_de_un_comando_sigue_recortado():
    crudo = _texto(4000)
    salida = off.resumir_para_modelo(crudo, tool="ejecutar", handle="res:aaa")
    assert salida.startswith("[SALIDA GRANDE de ejecutar")
    assert len(salida) < len(crudo) / 20


def test_lo_que_no_cabe_ni_leyendo_conserva_una_cabeza_util():
    crudo = _texto(20000)
    salida = off.resumir_para_modelo(crudo, tool="leer_archivo",
                                     handle="res:bbb")
    assert "primeras %d lineas" % off.CABEZA_LECTURA in salida


def test_el_knob_explicito_de_cabeza_manda_sobre_el_defecto_de_lectura(
        monkeypatch):
    monkeypatch.setenv("COGNIA_OFFLOAD_CABEZA", "3")
    salida = off.resumir_para_modelo(_texto(20000), tool="leer_archivo",
                                     handle="res:ccc")
    assert "primeras 3 lineas" in salida


def test_el_umbral_de_lectura_nunca_baja_del_general(monkeypatch):
    monkeypatch.setenv("COGNIA_TOOL_RESULT_MAX", "9000")
    monkeypatch.setenv("COGNIA_TOOL_RESULT_MAX_LECTURA", "10")
    assert off.umbral_lectura_bytes() == 9000


# -- 4. Apendar no es reeditar ------------------------------------------------

def test_construir_por_apendices_no_dispara_el_nudge():
    c = rep.ContadorFichero()
    assert c.registrar("juego.html", "escribir_archivo") == ""
    for _ in range(4):
        assert c.registrar("juego.html", "apendar_archivo") == ""
    assert c.nudges == 0


def test_reeditar_el_mismo_fichero_sigue_disparando_el_nudge():
    c = rep.ContadorFichero()
    for _ in range(rep.umbral_fichero() - 1):
        assert c.registrar("a.py", "editar_archivo") == ""
    aviso = c.registrar("a.py", "editar_archivo")
    assert aviso and "ediciones" in aviso


def test_apendar_sin_parar_sigue_teniendo_un_techo():
    c = rep.ContadorFichero()
    aviso = ""
    for _ in range(rep.umbral_apendice()):
        aviso = c.registrar("a.html", "apendar_archivo") or aviso
    assert aviso and "apendices" in aviso
    assert "relee el fichero entero" not in aviso


# -- 5. El techo se amplia con evidencia, no pidiendolo -----------------------

def test_ampliar_sube_el_techo_y_deja_rastro():
    pres = PresupuestoTurno(8)
    for _ in range(8):
        assert pres.consume() is True
    assert pres.consume() is False
    assert pres.ampliar(4, "progreso_verificado") == 12
    assert pres.consume() is True
    assert pres.ampliaciones[0]["motivo"] == "progreso_verificado"
    assert pres.ampliaciones[0]["extra"] == 4
    assert pres.ampliar(0, "x") == 12 and len(pres.ampliaciones) == 1


# -- 6. La corrida real, con su contrafactual --------------------------------

def _corrida_minecraft(prog, tmp_path, con_crecimiento=True):
    """Replica los pasos REALES: 1 listar + 1 leer + 5 recuperar (la lectura
    del fichero de 32 KB) y luego la construccion por partes."""
    f = tmp_path / "minecraft.html"
    cortes = []
    vistos = set()

    def observar():
        if con_crecimiento:
            prog.observar_fichero(f)
            return
        # El `observar_fichero` de antes del 2026-08-30: solo contaba la
        # transicion inexistente -> valido, una vez por ruta.
        if str(f) not in vistos:
            vistos.add(str(f))
            prog.observar_fichero(f)

    def paso(exploratorio, escribe_bytes=0):
        prog.gastar(tokens=4000, segundos=60.0, pasos=1,
                    exploratorio=exploratorio)
        if escribe_bytes:
            previo = f.read_text(encoding="utf-8") if f.exists() else ""
            f.write_text(previo + "x" * escribe_bytes, encoding="utf-8")
            observar()
        v = prog.veredicto()
        if v["estado"] != "avanza":
            cortes.append((prog.pasos, v["motivo"]))

    for _ in range(7):            # listar + leer_archivo + 5 recuperar
        paso(True)
    paso(False, 12000)            # escribir_archivo
    for _ in range(4):            # 4 apendices
        paso(False, 6000)
    return cortes


def test_la_corrida_real_ya_no_muere_leyendo_ni_construyendo(tmp_path):
    prog = Progreso(umbral_arranque=6, umbral_estancado=6)
    cortes = _corrida_minecraft(prog, tmp_path)
    assert cortes == [], "la corrida se corto en %r" % (cortes,)
    assert len(prog.avances) == 5      # 1 fichero nuevo + 4 crecimientos


def test_contrafactual_la_configuracion_vieja_moria_en_el_paso_6(tmp_path):
    """Sin credito de exploracion y sin crecimiento (el arnes de antes), la
    MISMA corrida cierra por 'sin_arranque' antes de escribir una linea."""
    prog = Progreso(umbral_arranque=6, umbral_estancado=6,
                    credito_exploracion=0)
    cortes = _corrida_minecraft(prog, tmp_path, con_crecimiento=False)
    assert cortes and cortes[0] == (6, "sin_arranque")


def test_diez_apendices_pequenos_acaban_contando(tmp_path):
    """La linea base no se mueve con lo que no llega al minimo: si se moviera,
    diez apendices de 100 bytes serian 1 KB de trabajo y cero avances."""
    p = Progreso()
    f = tmp_path / "a.txt"
    f.write_text("x" * 500, encoding="utf-8")
    p.observar_fichero(f)
    contados = 0
    for i in range(10):
        f.write_text("x" * (500 + 100 * (i + 1)), encoding="utf-8")
        if p.observar_fichero(f)["avance"] is not None:
            contados += 1
    assert contados == 5      # uno cada MIN_CRECIMIENTO_BYTES (200) de verdad


# -- 7. El interruptor unico --------------------------------------------------

def test_el_interruptor_devuelve_el_arnes_de_antes(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_TAREAS_LARGAS", "0")
    # lectura: vuelve al umbral general
    assert off.umbral_lectura_bytes() == off.umbral_bytes()
    crudo = "x" * 32585
    assert off.resumir_para_modelo(crudo, tool="leer_archivo") != crudo
    # apendices: vuelven al umbral de edicion
    assert rep.umbral_apendice() == rep.umbral_fichero()
    c = rep.ContadorFichero()
    avisos = [c.registrar("a.html", "apendar_archivo")
              for _ in range(rep.umbral_fichero())]
    assert avisos[-1]
    # crecimiento: el gobernador vuelve a contar solo la transicion
    p = Progreso(contar_crecimiento=False)
    f = tmp_path / "a.txt"
    f.write_text("x" * 500, encoding="utf-8")
    assert p.observar_fichero(f)["avance"] is not None
    f.write_text("x" * 50000, encoding="utf-8")
    assert p.observar_fichero(f)["avance"] is None


def test_encendido_por_defecto():
    assert off.tareas_largas() is True
