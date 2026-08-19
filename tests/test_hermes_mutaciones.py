# -*- coding: utf-8 -*-
"""Tests del registro de mutaciones de fichero y su footer (cognia/hermes/mutaciones.py).

Unitarios puros: no piden modelo, red ni disco. El objeto medido es el HECHO
(que se escribio y que no), que es justamente lo que el resumen del modelo
no puede acreditar solo.
"""
import os

from cognia.hermes.mutaciones import (
    MAX_CHARS_FOOTER,
    MAX_RUTAS_FOOTER,
    RegistroMutaciones,
    clasificar_resultado,
    es_operacion_de_fichero,
    ruta_de_args,
)


def _registro_5_de_los_cuales_3_fallan():
    """2 escrituras OK y 3 fallidas: el caso que motiva el modulo."""
    reg = RegistroMutaciones()
    for ruta in ("ok_uno.py", "ok_dos.py"):
        reg.resultado(reg.intento(ruta, "escribir_archivo"), True)
    for ruta, err in (
        ("falla_a.py", "no se encontro el bloque SEARCH"),
        ("falla_b.py", "no existe (usa escribir_archivo)"),
        ("falla_c.py", "no se pudo decodificar"),
    ):
        reg.resultado(reg.intento(ruta, "editar_archivo"), False, err)
    return reg


# -- footer -----------------------------------------------------------------

def test_footer_es_none_cuando_todo_salio_bien():
    reg = RegistroMutaciones()
    for ruta in ("a.py", "b.py", "c.py"):
        reg.resultado(reg.intento(ruta, "escribir_archivo"), True, "OK (10 chars)")
    assert reg.footer() is None


def test_footer_es_none_sin_ningun_intento():
    assert RegistroMutaciones().footer() is None


def test_footer_es_none_con_intentos_abiertos_sin_veredicto():
    # Un intento sin resultado no es un fallo MEDIDO: no se denuncia nada.
    reg = RegistroMutaciones()
    reg.intento("a.py", "editar_archivo")
    assert reg.footer() is None
    assert reg.resumen()["pendientes"] == 1


def test_footer_lista_los_3_fallos_y_no_los_acusa_de_exitos():
    reg = _registro_5_de_los_cuales_3_fallan()
    pie = reg.footer()
    assert pie is not None
    lineas_fallo = [ln for ln in pie.split("\n") if ln.startswith("  - ")]
    assert len(lineas_fallo) == 3
    texto_fallos = "\n".join(lineas_fallo)
    for ruta in ("falla_a.py", "falla_b.py", "falla_c.py"):
        assert ruta in texto_fallos
    for ruta in ("ok_uno.py", "ok_dos.py"):
        assert ruta not in texto_fallos
    # La cabecera declara el conteo real de ficheros no escritos.
    assert "3 fichero(s) NO quedaron" in pie.split("\n")[0]
    # El detalle textual del fallo viaja (es la causa accionable).
    assert "no se encontro el bloque SEARCH" in pie


def test_footer_deja_claro_cuales_si_se_escribieron():
    reg = _registro_5_de_los_cuales_3_fallan()
    pie = reg.footer()
    assert "SI se escribieron (2)" in pie
    assert "ok_uno.py" in pie and "ok_dos.py" in pie


def test_footer_marca_el_fichero_escrito_a_medias():
    # Mismo fichero: un bloque aplico y otro fallo -> quedo a medias.
    reg = RegistroMutaciones()
    reg.resultado(reg.intento("medias.py", "editar_archivo"), True)
    reg.resultado(reg.intento("medias.py", "editar_archivo"), False, "bloque no encontrado")
    pie = reg.footer()
    assert "medias.py" in pie
    assert "SI se aplico" in pie


# -- dedupe -----------------------------------------------------------------

def test_dedupe_por_ruta_un_solo_bullet_con_el_conteo():
    reg = RegistroMutaciones()
    for err in ("primer error", "segundo error", "tercer error"):
        reg.resultado(reg.intento("mismo.py", "editar_archivo"), False, err)
    pie = reg.footer()
    assert len([ln for ln in pie.split("\n") if ln.startswith("  - ")]) == 1
    assert "fallo 3 veces" in pie
    # Se conserva el PRIMER error (como Hermes): el segundo no tapa la causa.
    assert "primer error" in pie
    assert "segundo error" not in pie
    assert reg.resumen()["rutas_fallidas"] == ["mismo.py"]
    assert reg.resumen()["fallos"] == 3


def test_dedupe_normaliza_separadores_y_puntos():
    reg = RegistroMutaciones()
    reg.resultado(reg.intento("dir/sub/a.py", "editar_archivo"), False, "x")
    reg.resultado(reg.intento("dir/./sub/a.py", "editar_archivo"), False, "y")
    if os.sep == "\\":
        reg.resultado(reg.intento("dir\\sub\\a.py", "editar_archivo"), False, "z")
    assert len(reg.resumen()["rutas_fallidas"]) == 1
    # Se muestra la ruta TAL COMO la escribio el agente, no la normalizada.
    assert reg.resumen()["rutas_fallidas"][0] == "dir/sub/a.py"


def test_ficheros_escritos_dedupe_y_orden():
    reg = RegistroMutaciones()
    for ruta in ("b.py", "a.py", "b.py"):
        reg.resultado(reg.intento(ruta, "escribir_archivo"), True)
    assert reg.ficheros_escritos() == ["b.py", "a.py"]


# -- topes ------------------------------------------------------------------

def test_tope_de_longitud_con_200_fallos():
    reg = RegistroMutaciones()
    for i in range(200):
        reg.resultado(reg.intento("f{0}.py".format(i), "editar_archivo"), False,
                      "error largo " * 40)
    pie = reg.footer()
    assert len(pie) <= MAX_CHARS_FOOTER
    bullets = [ln for ln in pie.split("\n") if ln.startswith("  - ")]
    assert len(bullets) <= MAX_RUTAS_FOOTER + 2  # + resto + marca de recorte
    # El hecho sobrevive al recorte aunque el detalle no.
    assert "200 fichero(s) NO quedaron" in pie.split("\n")[0]


def test_tope_de_rutas_reporta_el_resto():
    reg = RegistroMutaciones(max_detalle=20)
    for i in range(MAX_RUTAS_FOOTER + 5):
        reg.resultado(reg.intento("f{0}.py".format(i), "editar_archivo"), False, "err")
    pie = reg.footer()
    assert "y 5 fichero(s) mas" in pie


def test_detalle_se_recorta_y_colapsa_espacios():
    reg = RegistroMutaciones(max_detalle=30)
    reg.resultado(reg.intento("a.py", "editar_archivo"), False, "linea\n\n   con    huecos " * 10)
    pie = reg.footer()
    cuerpo = [ln for ln in pie.split("\n") if ln.startswith("  - ")][0]
    assert "\n" not in cuerpo and "   " not in cuerpo
    assert cuerpo.endswith("...")


# -- resumen ----------------------------------------------------------------

def test_resumen_cuenta_llamadas_y_deduplica_rutas():
    reg = _registro_5_de_los_cuales_3_fallan()
    reg.intento("pendiente.py", "escribir_archivo")  # sin veredicto
    r = reg.resumen()
    assert r["intentos"] == 6
    assert r["ok"] == 2
    assert r["fallos"] == 3
    assert r["pendientes"] == 1
    assert r["rutas_fallidas"] == ["falla_a.py", "falla_b.py", "falla_c.py"]
    assert r["rutas_escritas"] == ["ok_uno.py", "ok_dos.py"]


def test_resultado_con_id_desconocido_o_repetido_no_lanza():
    reg = RegistroMutaciones()
    assert reg.resultado(999, True) is False
    assert reg.resultado(None, False, "x") is False
    idm = reg.intento("a.py", "escribir_archivo")
    assert reg.resultado(idm, True) is True
    assert reg.resultado(idm, False, "tarde") is False  # ya cerrado
    assert reg.footer() is None


def test_intento_sin_ruta_no_rompe_ni_se_confunde_con_otro():
    reg = RegistroMutaciones()
    reg.resultado(reg.intento("", "escribir_archivo"), False, "formato invalido")
    reg.resultado(reg.intento(None, "escribir_archivo"), False, "formato invalido")
    assert reg.resumen()["fallos"] == 2
    assert len(reg.resumen()["rutas_fallidas"]) == 2  # no colapsan entre si


# -- clasificacion del string de resultado (el fallo NO es una excepcion) ----

def test_clasificar_resultado_con_los_strings_reales_del_repo():
    ok, det = clasificar_resultado("RESULTADO escribir_archivo web/index.html: OK (523 chars)")
    assert ok is True and det == ""

    ok, det = clasificar_resultado(
        "RESULTADO editar_archivo motor.py ERROR: no existe (usa escribir_archivo)")
    assert ok is False
    assert det == "no existe (usa escribir_archivo)"

    # 'sin cambios' NO es un fallo: la tool hizo lo pedido.
    ok, _ = clasificar_resultado("RESULTADO editar_archivo a.py: sin cambios (el REPLACE es igual)")
    assert ok is True


def test_clasificar_resultado_no_confunde_un_nombre_con_el_marcador():
    ok, _ = clasificar_resultado("RESULTADO escribir_archivo ERROR_LOG.txt: OK (12 chars)")
    assert ok is True


def test_clasificar_resultado_tolera_none_y_no_lanza():
    assert clasificar_resultado(None) == (True, "")


def test_ayudas_de_cableado():
    assert es_operacion_de_fichero("editar_archivo") is True
    assert es_operacion_de_fichero("leer_archivo") is False
    assert ruta_de_args("web/index.html | <html>...</html>") == "web/index.html"
    assert ruta_de_args("solo/una/ruta.py") == "solo/una/ruta.py"
    assert ruta_de_args("") == ""
