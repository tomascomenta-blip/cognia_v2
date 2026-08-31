# -*- coding: utf-8 -*-
"""Tests de los dos modulos que cierran el agujero de la traza del 2026-08-31:

  - `harness/entrega.py`     el turno nunca cierra sin decir QUE quedo en disco.
  - `harness/razonamiento.py` recordatorios cuando el modelo piensa en bucle.

Sin red y sin modelo.
"""

import os

import pytest

from cognia.harness import entrega as E
from cognia.harness import razonamiento as R


# ══════════════════════════════════════════════════════════════════════
# ENTREGA
# ══════════════════════════════════════════════════════════════════════

HTML_CORTADO = ("<!DOCTYPE html>\n<html><body>\n<script>\nclass R {\n"
                "  draw(){\n    this.gl.clear();\n")
HTML_ENTERO = ("<!DOCTYPE html>\n<html><body>\n<script>\nconsole.log(1);\n"
               "</script>\n</body>\n</html>\n")


def test_sin_ficheros_lo_dice_en_vez_de_callar():
    """El cierre mas util de una tarea que no entrego es "no escribi nada".

    En la traza del dueno, dos tareas seguidas cerraron con
    "(cerrada sin progreso verificado: sin_arranque)" y el stdout de la ultima
    tool. Ninguna de las dos habia escrito un byte, y eso no se dijo.
    """
    inf = E.informe([])
    assert inf["nada"] is True
    txt = E.bloque(inf)
    assert "ningun fichero escrito" in txt


def test_html_cortado_sale_marcado_ROTO_con_la_linea_del_corte(tmp_path):
    p = tmp_path / "index.html"
    p.write_text(HTML_CORTADO, encoding="utf-8")
    inf = E.informe([str(p)])
    assert inf["rotos"] == 1 and inf["enteros"] == 0
    txt = E.bloque(inf)
    assert "ROTO index.html" in txt
    assert "INCOMPLETO" in txt
    assert "se corta en la linea" in txt
    assert "INCOMPLETOS" in txt          # la linea de que hacer


def test_html_entero_sale_OK_pero_sin_prometer_que_funciona(tmp_path):
    p = tmp_path / "index.html"
    p.write_text(HTML_ENTERO, encoding="utf-8")
    txt = E.bloque(E.informe([str(p)]))
    assert "OK  index.html" in txt
    assert "no dice que hagan lo que pediste" in txt


def test_fichero_borrado_tras_escribirlo_se_reporta(tmp_path):
    p = tmp_path / "se_fue.py"
    inf = E.informe([str(p)])
    assert inf["escritos"][0]["existe"] is False
    assert "no existe en disco" in E.bloque(inf)


def test_anexar_es_idempotente_y_nunca_lanza(tmp_path):
    p = tmp_path / "a.py"
    p.write_text("x = 1\n", encoding="utf-8")
    uno = E.anexar("respuesta", [str(p)])
    assert E.MARCA in uno
    assert E.anexar(uno, [str(p)]) == uno          # no se pega dos veces
    assert E.anexar("respuesta", [object()])       # basura: no revienta


def test_escritura_fallida_aparece_en_la_entrega(tmp_path):
    txt = E.bloque(E.informe([], fallidos=[str(tmp_path / "no_pude.py")]))
    assert "la escritura fallo" in txt


# ══════════════════════════════════════════════════════════════════════
# RAZONAMIENTO EN BUCLE
# ══════════════════════════════════════════════════════════════════════

def _largo(n=6000, sal="analizo el problema desde otro angulo "):
    return sal * (n // len(sal) + 1)


def test_pensar_mucho_y_AVANZAR_no_dispara_nada():
    """El objetivo no es que piense poco: es que no de vueltas."""
    v = R.Vigilante()
    for _ in range(5):
        out = v.turno(20000, avanzo=True, texto=_largo())
        assert out["nudge"] == ""
        assert out["racha"] == 0
    assert v.informe()["pensamiento_apagado"] is False


def test_pensar_poco_sin_avanzar_tampoco_dispara():
    v = R.Vigilante()
    for _ in range(5):
        assert v.turno(50, avanzo=False, texto="ok")["nudge"] == ""


def test_racha_de_pensamiento_sin_avance_escala_y_apaga_el_pensamiento():
    v = R.Vigilante(umbral=1000, racha=3)
    a = v.turno(5000, avanzo=False, texto="primero pienso una cosa distinta " * 40)
    assert R.MARCA in a["nudge"] and a["apagar_pensamiento"] is False
    b = v.turno(5000, avanzo=False, texto="ahora pienso otra cosa distinta " * 40)
    assert "PARA DE PLANEAR" in b["nudge"] and b["racha"] == 2
    c = v.turno(5000, avanzo=False, texto="y ahora una tercera diferente " * 40)
    assert c["apagar_pensamiento"] is True
    assert "por partes" in c["nudge"].lower()
    # Se pide UNA sola vez: el bucle ya lo apago.
    d = v.turno(5000, avanzo=False, texto="una cuarta cosa mas " * 40)
    assert d["apagar_pensamiento"] is False


def test_un_avance_rompe_la_racha():
    v = R.Vigilante(umbral=1000, racha=3)
    v.turno(5000, avanzo=False, texto="uno " * 400)
    v.turno(5000, avanzo=False, texto="dos " * 400)
    assert v.turno(5000, avanzo=True, texto="tres " * 400)["racha"] == 0
    assert v.racha == 0


def test_razonamiento_REPETIDO_se_nombra_dentro_del_nudge():
    """El caso real: el modelo llama a herramientas en casi todos los pasos
    (relee el mismo fichero), piensa lo mismo una y otra vez y no avanza."""
    v = R.Vigilante(umbral=1000)
    texto = "reviso el fichero para entender donde esta el fallo de los botones " * 30
    v.turno(5000, avanzo=False, texto=texto)
    out = v.turno(5000, avanzo=False, texto=texto)
    assert out["repetido"] is True
    assert "EL MISMO razonamiento" in out["nudge"]


def test_repetirse_MIENTRAS_SE_AVANZA_no_molesta():
    """Avanzar es la verdad de terreno: ahi un aviso seria ruido."""
    v = R.Vigilante(umbral=1000)
    texto = "sigo el mismo plan de siempre para construir la pagina paso a paso " * 30
    v.turno(9000, avanzo=True, texto=texto)
    out = v.turno(9000, avanzo=True, texto=texto)
    assert out["repetido"] is True and out["nudge"] == ""


def test_solapamiento_distingue_lo_mismo_de_lo_distinto():
    a = "voy a leer el index.html para ver que le falta a la funcion de dibujo " * 10
    b = "voy a leer el index.html para ver que le falta a la funcion de dibujo " * 10
    c = "escribo el modulo de fisica con colisiones y gravedad para el jugador " * 10
    assert R.solapamiento(a, b) > 0.9
    assert R.solapamiento(a, c) < R.UMBRAL_REPETICION


def test_aviso_en_vivo_dice_cada_hito_una_sola_vez():
    v = R.Vigilante()
    assert v.vivo(100) == ""
    primero = v.vivo(9000)
    assert "9.000" in primero or "9000" in primero.replace(".", "")
    assert v.vivo(9500) == ""            # mismo hito: no se repite
    assert v.vivo(21000) != ""           # hito siguiente
    v.nuevo_turno()
    assert v.vivo(9000) != ""            # turno nuevo, hitos limpios


def test_se_puede_apagar_por_entorno(monkeypatch):
    monkeypatch.setenv(R.ENV_ACTIVO, "0")
    v = R.Vigilante(umbral=10, racha=2)
    for _ in range(5):
        out = v.turno(99999, avanzo=False, texto="x " * 500)
        assert out["nudge"] == "" and out["apagar_pensamiento"] is False
    assert v.vivo(999999) == ""


def test_config_basura_no_rompe_y_cae_al_defecto(monkeypatch):
    monkeypatch.setenv(R.ENV_UMBRAL, "no-soy-un-numero")
    monkeypatch.setenv(R.ENV_RACHA, "-4")
    assert R.umbral_chars() == R.UMBRAL_CHARS_DEFECTO
    assert R.racha_dura() == R.RACHA_DURA_DEFECTO


def test_turno_nunca_lanza_con_basura():
    v = R.Vigilante()
    assert v.turno(None, avanzo=False, texto=None)["nudge"] == ""
    assert v.turno("x", avanzo=False, texto=None)["nudge"] == ""
