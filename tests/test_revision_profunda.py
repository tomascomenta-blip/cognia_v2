# -*- coding: utf-8 -*-
"""Tests de la revision profunda antes de entregar (cognia/harness/revision_profunda.py).

El test que da sentido al modulo es `test_producto_que_revienta_en_runtime_*`: un fichero
que COMPILA, que no tiene ningun test, y que muere de NameError en cuanto se usa. Sintaxis
verde + suite verde + producto roto es exactamente el cierre que este modulo viene a evitar,
y sin arrancarlo de verdad no hay forma de verlo.

Todo corre en tmp_path a proposito: alli no hay pytest.ini ni pyproject, asi que la fase de
tests degrada a "no evaluada" y ningun test puede lanzar pytest dentro de pytest.
"""
import os

import pytest

from cognia.harness import revision_profunda as rp


# -- utilidades ----------------------------------------------------------------

PROGRAMA_SANO = '''\
"""Conversor de temperaturas."""


def c_a_f(c):
    return c * 9 / 5 + 32


def main():
    dato = input("Grados Celsius: ")
    print(f"{float(dato)} C = {c_a_f(float(dato)):.1f} F")


if __name__ == "__main__":
    main()
'''

PROGRAMA_QUE_REVIENTA = '''\
def main():
    datos = [1, 2, 3]
    print("promedio:", sum(datos) / len(datos))
    print("maximo:", maximo(datos))   # NUNCA se definio


if __name__ == "__main__":
    main()
'''


@pytest.fixture(autouse=True)
def _mandos_por_defecto(monkeypatch):
    """Cada test arranca con los mandos limpios: una env del dueno no puede
    volver verde un test que mide la compuerta encendida."""
    for var in ("COGNIA_REVISION", "COGNIA_REVISION_EJECUTAR", "COGNIA_REVISION_RONDAS",
                "COGNIA_REVISION_SEGUNDOS", "COGNIA_REVISION_FICHEROS",
                "COGNIA_REVISION_LINEAS", "COGNIA_REVISION_PASOS"):
        monkeypatch.delenv(var, raising=False)
    # El navegador y el VLM se apagan: esta suite no puede depender de que haya
    # Chrome instalado ni de que la flota este viva.
    monkeypatch.setenv("COGNIA_VERIFICAR_NAVEGADOR", "0")


def _escribir(carpeta, nombre, contenido):
    p = carpeta / nombre
    p.write_text(contenido, encoding="utf-8")
    return str(p)


# -- el filtro de complejidad --------------------------------------------------

def test_un_retoque_chico_no_dispara_la_revision(tmp_path):
    """Un gate que corre siempre acaba apagado: dos lineas sueltas no son un trabajo."""
    f = _escribir(tmp_path, "notas.py", "X = 1\n")
    v = rp.es_compleja([f], pasos=2)
    assert v["compleja"] is False
    assert v["motivo"] == "trabajo_simple"


def test_dos_ficheros_de_codigo_ya_son_un_trabajo(tmp_path):
    a = _escribir(tmp_path, "uno.py", "X = 1\n")
    b = _escribir(tmp_path, "dos.py", "Y = 2\n")
    v = rp.es_compleja([a, b], pasos=1)
    assert v["compleja"] is True
    assert "2 ficheros" in v["motivo"]


def test_un_solo_fichero_arrancable_ya_dispara(tmp_path):
    """Aunque sea corto: si se puede USAR, se prueba usandolo."""
    f = _escribir(tmp_path, "main.py", "print('hola')\n")
    v = rp.es_compleja([f], pasos=1)
    assert v["compleja"] is True
    assert "arrancable" in v["motivo"]


def test_lo_que_no_existe_en_disco_no_cuenta(tmp_path):
    v = rp.es_compleja([str(tmp_path / "fantasma.py")], pasos=99)
    assert v["compleja"] is False
    assert v["motivo"] == "sin_codigo_escrito"


def test_solo_prosa_no_dispara(tmp_path):
    f = _escribir(tmp_path, "LEEME.md", "# Titulo\n" + "texto\n" * 200)
    v = rp.es_compleja([f], pasos=3)
    assert v["compleja"] is False


# -- que se arranca y que NO ---------------------------------------------------

def test_un_modulo_de_paquete_no_se_arranca(tmp_path):
    """LA regresion que hace segura la fase de punta a punta.

    Tocar `paquete/cli.py` no puede significar "lanzame el programa entero del usuario":
    un fichero con `__init__.py` al lado se importa, no se ejecuta.
    """
    paq = tmp_path / "paquete"
    paq.mkdir()
    _escribir(paq, "__init__.py", "")
    f = _escribir(paq, "main.py", PROGRAMA_SANO)
    assert rp.artefacto_ejecutable([f]) is None


def test_un_test_no_se_arranca_como_producto(tmp_path):
    f = _escribir(tmp_path, "test_cosas.py", "def test_x():\n    assert True\n")
    assert rp.artefacto_ejecutable([f]) is None


def test_un_py_sin_guarda_ni_nombre_de_convencion_no_se_arranca(tmp_path):
    f = _escribir(tmp_path, "utilidades.py", "def suma(a, b):\n    return a + b\n")
    assert rp.artefacto_ejecutable([f]) is None


def test_la_guarda_main_hace_arrancable_cualquier_nombre(tmp_path):
    f = _escribir(tmp_path, "conversor.py", PROGRAMA_SANO)
    art = rp.artefacto_ejecutable([f])
    assert art is not None and art["lenguaje"] == "python"
    assert art["entrypoint"] == f


def test_la_pagina_gana_y_index_html_es_el_entrypoint(tmp_path):
    _escribir(tmp_path, "otra.html", "<html><head></head><body>x</body></html>")
    idx = _escribir(tmp_path, "index.html", "<html><head></head><body>x</body></html>")
    art = rp.artefacto_ejecutable([str(tmp_path / "otra.html"), idx])
    assert art is not None and art["lenguaje"] == "html"
    assert art["entrypoint"] == idx


def test_los_hermanos_de_la_carpeta_viajan_para_compilar(tmp_path):
    main = _escribir(tmp_path, "main.py", "import extra\nprint(extra.X)\n")
    extra = _escribir(tmp_path, "extra.py", "X = 1\n")
    art = rp.artefacto_ejecutable([main, extra])
    assert set(art["archivos_py"]) == {main, extra}


# -- fase de sintaxis ----------------------------------------------------------

def test_la_sintaxis_caza_el_py_roto(tmp_path):
    f = _escribir(tmp_path, "roto.py", "def f(:\n    pass\n")
    fase = rp.fase_sintaxis([f])
    assert fase["ok"] is False
    assert "roto.py" in fase["errores"][0]


def test_la_sintaxis_caza_el_json_roto(tmp_path):
    f = _escribir(tmp_path, "config.json", '{"a": 1,}')
    fase = rp.fase_sintaxis([f])
    assert fase["ok"] is False


def test_sin_nada_verificable_la_sintaxis_no_aprueba_dice_que_no_evaluo(tmp_path):
    """Ausencia de examen no es aprobado: ok=None, no ok=True."""
    f = _escribir(tmp_path, "notas.md", "# hola\n")
    assert rp.fase_sintaxis([f])["ok"] is None


# -- la revision entera --------------------------------------------------------

def test_producto_que_revienta_en_runtime_reprueba_y_devuelve_el_traceback(tmp_path):
    """Compila, no tiene tests, y muere al usarlo. Solo arrancarlo lo destapa."""
    f = _escribir(tmp_path, "main.py", PROGRAMA_QUE_REVIENTA)
    inf = rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path), "pasos": 5})

    assert inf["corrida"] is True
    assert inf["fases"]["sintaxis"]["ok"] is True          # compila perfecto
    assert inf["fases"]["producto"]["ok"] is False         # y aun asi esta roto
    assert inf["ok"] is False
    assert inf["nudge"] and "NameError" in inf["nudge"]
    assert "maximo" in inf["nudge"]
    assert "QUEDA ROTO" in inf["footer"]


def test_producto_sano_pasa_y_deja_footer_con_la_evidencia(tmp_path):
    f = _escribir(tmp_path, "main.py", PROGRAMA_SANO)
    inf = rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path), "pasos": 5})

    assert inf["ok"] is True
    assert inf["nudge"] is None
    assert inf["fases"]["producto"]["ok"] is True
    # El footer se pega TAMBIEN cuando pasa: "revisado y arranca" y "nadie lo
    # miro" tienen que verse distinto.
    assert "revision profunda" in inf["footer"]
    assert "main.py OK" in inf["footer"]


def test_agotadas_las_rondas_se_entrega_igual_con_el_footer_que_lo_dice(tmp_path):
    """La compuerta nunca secuestra el trabajo para siempre: reporta y suelta."""
    f = _escribir(tmp_path, "main.py", PROGRAMA_QUE_REVIENTA)
    inf = rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path),
                      "pasos": 5, "rondas_usadas": rp.MAX_RONDAS})
    assert inf["ok"] is False
    assert inf["nudge"] is None                 # ya no se pide otra reparacion
    assert "QUEDA ROTO" in inf["footer"]


def test_la_fase_de_tests_nombra_el_test_que_falta(tmp_path):
    f = _escribir(tmp_path, "main.py", PROGRAMA_SANO)
    inf = rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path), "pasos": 5})
    tests = inf["fases"]["tests"]
    assert tests["ok"] is None                  # no hay examen: no es aprobado
    assert "ningun test cubre" in tests["detalle"]


def test_el_callback_narra_las_fases(tmp_path):
    """Un banco sin callbacks mide cero: si nadie ve la revision, no existe."""
    f = _escribir(tmp_path, "main.py", PROGRAMA_SANO)
    vistos = []
    rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path), "pasos": 5,
                "on_evento": vistos.append})
    assert any("sintaxis" in m for m in vistos)
    assert any("arrancando" in m for m in vistos)


def test_los_tests_verdes_quedan_ANOTADOS_en_el_ledger(tmp_path, monkeypatch):
    """La revision existe para que la compuerta de POLITICA no gaste otro turno.

    REGRESION 2026-08-30: la primera version llamaba a `registrar_verificacion`
    con `salida=` cuando el parametro se llama `salida_corta`, y el
    `except: pass` se tragaba el TypeError -- el ledger no se escribia NUNCA y
    desde afuera se veia exactamente igual que si funcionara.
    """
    prod = tmp_path / "prod"
    prod.mkdir()
    _escribir(prod, "calc.py", "def doble(n):\n    return n * 2\n")
    _escribir(prod, "test_calc.py",
              "from calc import doble\n\n\ndef test_doble():\n    assert doble(3) == 6\n")

    anotados = []
    import cognia.hermes.parada_verificada as pv
    real = pv.registrar_verificacion

    def _espia(*a, **k):
        anotados.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr(pv, "registrar_verificacion", _espia)

    fase = rp.fase_tests([str(prod / "calc.py")], raiz=prod)
    assert fase["ok"] is True, fase
    assert "1 passed" in fase["resumen"]
    assert anotados, "los tests corrieron y NADIE lo anoto en el ledger"
    assert anotados[0][1].get("salida_corta") is not None
    assert "ledger" not in fase["detalle"]      # y no hubo degradacion


def test_un_fallo_del_ledger_se_DICE_en_el_detalle(tmp_path, monkeypatch):
    """Un except mudo no puede volver a esconder esto."""
    prod = tmp_path / "prod"
    prod.mkdir()
    _escribir(prod, "calc.py", "def doble(n):\n    return n * 2\n")
    _escribir(prod, "test_calc.py",
              "from calc import doble\n\n\ndef test_doble():\n    assert doble(3) == 6\n")

    def _revienta(*a, **k):
        raise TypeError("parametro inesperado")

    import cognia.hermes.parada_verificada as pv
    monkeypatch.setattr(pv, "registrar_verificacion", _revienta)
    fase = rp.fase_tests([str(prod / "calc.py")], raiz=prod)
    assert fase["ok"] is True                    # el veredicto no cambia
    assert "ledger" in fase["detalle"]           # pero se DICE


# -- mandos --------------------------------------------------------------------

def test_apagada_no_corre_y_lo_dice(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_REVISION", "0")
    f = _escribir(tmp_path, "main.py", PROGRAMA_QUE_REVIENTA)
    inf = rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path), "pasos": 5})
    assert inf["corrida"] is False
    assert inf["motivo"] == "apagada"
    assert inf["nudge"] is None


def test_apagar_solo_el_arranque_deja_viva_la_sintaxis(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_REVISION_EJECUTAR", "0")
    f = _escribir(tmp_path, "main.py", PROGRAMA_QUE_REVIENTA)
    inf = rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path), "pasos": 5})
    assert inf["fases"]["sintaxis"]["ok"] is True
    assert inf["fases"]["producto"]["ok"] is None
    assert "apagada" in inf["fases"]["producto"]["detalle"]
    assert inf["nudge"] is None


def test_rondas_cero_revisa_pero_no_pide_reparacion(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_REVISION_RONDAS", "0")
    f = _escribir(tmp_path, "main.py", PROGRAMA_QUE_REVIENTA)
    inf = rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path), "pasos": 5})
    assert inf["ok"] is False and inf["nudge"] is None
    assert "QUEDA ROTO" in inf["footer"]


def test_la_superficie_de_mensajeria_apaga_la_compuerta(tmp_path):
    f = _escribir(tmp_path, "main.py", PROGRAMA_QUE_REVIENTA)
    inf = rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path),
                      "pasos": 5, "superficie": "telegram"})
    assert inf["corrida"] is False
    assert inf["motivo"] == "superficie_silenciosa"


def test_los_umbrales_se_mueven_por_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_REVISION_FICHEROS", "1")
    f = _escribir(tmp_path, "utilidades.py", "X = 1\n")
    assert rp.es_compleja([f], pasos=1)["compleja"] is True


# -- contrato: no lanza NUNCA --------------------------------------------------

@pytest.mark.parametrize("basura", [None, "", 42, [], {"ficheros_editados": None},
                                    {"ficheros_editados": [None, 3, ""]}])
def test_revisar_nunca_lanza(basura):
    inf = rp.revisar(basura)
    assert isinstance(inf, dict)
    assert "ok" in inf and "motivo" in inf


def test_render_y_footer_nunca_lanzan():
    assert isinstance(rp.render({}), list)
    assert rp.footer_de({}) == ""
    assert rp.nudge_de({}) is None
    assert isinstance(rp.render(rp.revisar({})), list)


def test_el_informe_queda_disponible_para_la_puerta(tmp_path):
    f = _escribir(tmp_path, "main.py", PROGRAMA_SANO)
    rp.revisar({"ficheros_editados": [f], "workspace": str(tmp_path), "pasos": 5})
    assert rp.ultimo().get("corrida") is True


# -- la puerta del CLI ---------------------------------------------------------

def test_la_puerta_esta_registrada_y_sale_en_ayuda():
    """Codigo sin puerta no esta entregado (CLAUDE.md, regla vinculante)."""
    import cognia.cli as cli
    assert "/revision" in cli._CMD_DESCRIPTIONS
    assert callable(cli._slash_revision)
    assert "/revision" in cli._CMD_DETAILS


def test_las_claves_de_config_del_cli_existen_con_default_sensato():
    import cognia.cli as cli
    for clave, esperado in (("revision", "on"), ("revision_ejecutar", "on"),
                            ("revision_rondas", "2"), ("revision_segundos", "180")):
        assert cli._CONFIG_DEFAULTS[clave] == esperado


def test_la_config_se_siembra_al_entorno(monkeypatch, tmp_path):
    """Sin siembra, `/revision off` mentiria: quien lee el flag es agent/loop.py."""
    import cognia.cli as cli
    for var in ("COGNIA_REVISION", "COGNIA_REVISION_EJECUTAR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli, "_load_config",
                        lambda: {"revision": "off", "revision_ejecutar": "on",
                                 "revision_rondas": "3", "revision_segundos": "90"})
    cli._aplicar_config_revision()
    assert os.environ["COGNIA_REVISION"] == "0"
    assert os.environ["COGNIA_REVISION_RONDAS"] == "3"
    assert rp.activa() is False


def test_el_bucle_del_agente_tiene_la_compuerta_cableada():
    """El modulo puede estar perfecto y no estar ENCHUFADO: eso ya paso en este
    repo (el adaptador nativo 'registrado' que el modelo nunca recibia)."""
    import inspect

    from cognia.agent import loop
    fuente = inspect.getsource(loop.bucle_nativo)
    assert "revision_profunda" in fuente
    assert "_rev_mod.revisar(" in fuente
    assert "footer_de(_informe_rev)" in fuente


# -- HTML/JS en la fase de sintaxis (2026-08-31) --------------------------------

HTML_CORTADO = ("<!DOCTYPE html>\n<html><body>\n<script>\n"
                "class Renderer {\n  draw(){\n    this.gl.clear();\n")
HTML_ENTERO = ("<!DOCTYPE html>\n<html><body>\n<script>\n"
               "document.body.onclick = () => 1;\n</script>\n</body></html>\n")


def test_fase_sintaxis_caza_el_html_truncado(tmp_path):
    """Hasta el 2026-08-31 esta fase saltaba .html y devolvia 'no evaluada'
    sobre una entrega HTML: el producto que el agente entrega mas a menudo era
    el unico que nadie miraba. El caso es el index.html de 32 KB de la traza
    del dueno, cortado a mitad de una clase."""
    roto = tmp_path / "index.html"
    roto.write_text(HTML_CORTADO, encoding="utf-8")
    res = rp.fase_sintaxis([str(roto)])
    assert res["ok"] is False and res["revisados"] == 1
    assert any("INCOMPLETO" in e for e in res["errores"])


def test_fase_sintaxis_deja_pasar_el_html_entero(tmp_path):
    sano = tmp_path / "index.html"
    sano.write_text(HTML_ENTERO, encoding="utf-8")
    res = rp.fase_sintaxis([str(sano)])
    assert res["ok"] is True and res["errores"] == []


def test_fase_sintaxis_sigue_mirando_py_y_json(tmp_path):
    """El camino de siempre no se toca: HTML se SUMA, no reemplaza."""
    py = tmp_path / "roto.py"
    py.write_text("def f(:\n", encoding="utf-8")
    res = rp.fase_sintaxis([str(py)])
    assert res["ok"] is False and res["revisados"] == 1
