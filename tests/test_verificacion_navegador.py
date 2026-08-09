"""
tests/test_verificacion_navegador.py
El juez ABRE el navegador (cognia/autoprueba.py::_fases_html).

Regresion 2026-08-02: la fase se llamaba 'arranca' pero NO arrancaba nada — solo
revisar_html(), que lee TEXTO. Una landing con "ReferenceError: daily is not
defined" quedaba EN NEGRO de la mitad para abajo y se sello 'verificado: corre
(9.5/10)'. vista_navegador.py existia desde 2026-07-19 por un caso identico
(8.7/10 estatico, pagina negra en Chrome) pero nadie lo habia enchufado al
veredicto.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from cognia import autoprueba as ap
from cognia.program_creator import vista_navegador as vn


def _informe(errores=None, nota=""):
    return SimpleNamespace(errores_js=list(errores or []), nota=nota,
                           input_images=[], output_images=[])


# ---------------------------------------------------------------------------
# El gate: un error de JS no puede pasar la verificacion
# ---------------------------------------------------------------------------

class TestGateNavegador:
    def test_error_js_reprueba(self):
        with patch.object(vn, "revisar_en_navegador",
                          return_value=_informe(["Uncaught ReferenceError: daily is not defined"])), \
             patch.object(ap, "_mirar_con_vlm", return_value=""):
            ok, detalle, errores = ap._mirar_en_navegador("<html></html>")
        assert ok is False
        assert "daily is not defined" in detalle
        assert errores

    def test_sin_errores_aprueba(self):
        with patch.object(vn, "revisar_en_navegador", return_value=_informe()), \
             patch.object(ap, "_mirar_con_vlm", return_value=""):
            ok, _, errores = ap._mirar_en_navegador("<html></html>")
        assert ok is True and errores == []

    def test_sin_navegador_no_reprueba_pero_lo_dice(self):
        """No todos los entornos tienen Chrome: ausencia != producto roto.
        Pero tiene que quedar DICHO, o es un chequeo que se salta en silencio."""
        with patch.object(vn, "revisar_en_navegador",
                          return_value=_informe(nota="Sin navegador instalado")), \
             patch.object(ap, "_mirar_con_vlm", return_value=""):
            ok, detalle, _ = ap._mirar_en_navegador("<html></html>")
        assert ok is True
        assert "Sin navegador" in detalle

    def test_fallo_del_navegador_no_tumba_la_verificacion(self):
        with patch.object(vn, "revisar_en_navegador", side_effect=RuntimeError("chrome murio")), \
             patch.object(ap, "_mirar_con_vlm", return_value=""):
            ok, detalle, _ = ap._mirar_en_navegador("<html></html>")
        assert ok is True
        assert "sin este chequeo" in detalle

    def test_se_puede_apagar_por_env(self, monkeypatch):
        monkeypatch.setenv("COGNIA_VERIFICAR_NAVEGADOR", "0")
        with patch.object(vn, "revisar_en_navegador",
                          side_effect=AssertionError("no debia abrirse")):
            ok, detalle, _ = ap._mirar_en_navegador("<html></html>")
        assert ok is True and "desactivado" in detalle


# ---------------------------------------------------------------------------
# 'arranca' exige AMBOS criterios
# ---------------------------------------------------------------------------

class TestFasesHtml:
    def _prod(self, tmp_path, html):
        p = tmp_path / "index.html"
        p.write_text(html, encoding="utf-8")
        return {"entrypoint": str(p), "lenguaje": "html", "title": "x"}

    def test_estatico_ok_pero_navegador_roto_no_pasa(self, tmp_path):
        """EL caso real: revisar_html aprueba y el navegador reprueba."""
        html = "<html><head></head><body>" + "<p>hola</p>" * 30 + "</body></html>"
        with patch.object(ap, "_mirar_en_navegador",
                          return_value=(False, "errores de JavaScript al cargar: X", ["X"])):
            fases = ap._fases_html(self._prod(tmp_path, html))
        assert fases["arranca"]["ok"] is False
        assert "X" in fases["arranca"]["stderr"]

    def test_ambos_ok_pasa(self, tmp_path):
        """Se fija TAMBIEN el lado estatico: lo que se prueba aqui es el AND, y
        un html de fixture minimo no aprueba revisar_html por su cuenta."""
        html = "<html><head></head><body>" + "<p>hola</p>" * 30 + "</body></html>"
        estatico_ok = SimpleNamespace(success=True, exit_code=0,
                                      execution_output="", execution_errors="")
        with patch.object(ap, "_mirar_en_navegador",
                          return_value=(True, "abre sin errores", [])), \
             patch.object(ap, "revisar_html", return_value=estatico_ok):
            fases = ap._fases_html(self._prod(tmp_path, html))
        assert fases["arranca"]["ok"] is True
        assert "navegador" in fases["arranca"]["detalle"]

    def test_navegador_ok_pero_estatico_roto_tampoco_pasa(self, tmp_path):
        """El AND va en los dos sentidos: el navegador no absuelve al estatico."""
        html = "<html><head></head><body>" + "<p>hola</p>" * 30 + "</body></html>"
        estatico_roto = SimpleNamespace(success=False, exit_code=1,
                                        execution_output="", execution_errors="CDN externo")
        with patch.object(ap, "_mirar_en_navegador",
                          return_value=(True, "abre sin errores", [])), \
             patch.object(ap, "revisar_html", return_value=estatico_roto):
            fases = ap._fases_html(self._prod(tmp_path, html))
        assert fases["arranca"]["ok"] is False


# ---------------------------------------------------------------------------
# El cazador de errores va ARRIBA: si no, no ve nada
# ---------------------------------------------------------------------------

class TestCazadorDeErrores:
    def test_se_inyecta_antes_de_los_scripts_de_la_pagina(self, tmp_path):
        """El listener vivia con la sonda, antes de </body> — o sea DESPUES de
        los <script> de la pagina, asi que errores_js salia SIEMPRE vacio."""
        code = ("<html><head><title>t</title></head><body>"
                "<script>boom()</script></body></html>")
        ruta = vn._preparar_pagina(code, tmp_path)
        html = ruta.read_text(encoding="utf-8")
        pos_caza   = html.find("__cognia_errores__")
        pos_script = html.find("boom()")
        assert pos_caza != -1, "el cazador de errores no se inyecto"
        assert pos_caza < pos_script, (
            "el cazador quedo DESPUES del script de la pagina: no vera lo que lance")

    def test_sin_head_tambien_se_inyecta(self, tmp_path):
        ruta = vn._preparar_pagina("<body><script>boom()</script></body>", tmp_path)
        html = ruta.read_text(encoding="utf-8")
        assert html.find("__cognia_errores__") < html.find("boom()")


# ---------------------------------------------------------------------------
# El VLM informa, pero NO decide el pase
# ---------------------------------------------------------------------------

class TestArbitroVlm:
    def test_vlm_ausente_se_declara(self):
        from cognia.program_creator import arbitro_visual as av
        with patch.object(av, "vlm_disponible", return_value=(False, "sin VLM")):
            assert "NO juzgo" in ap._mirar_con_vlm(_informe(), "idea")

    def test_vlm_no_cambia_el_veredicto(self):
        """Nota baja del VLM sobre una pagina que EJECUTA bien no la reprueba:
        juez_ejecutable.py documenta por que (el VLM firmo un juego de memoria
        con las 16 cartas destapadas). La ejecucion manda; el ojo informa."""
        from cognia.program_creator import arbitro_visual as av
        with patch.object(vn, "revisar_en_navegador", return_value=_informe()), \
             patch.object(av, "vlm_disponible", return_value=(True, "ok")), \
             patch.object(av, "arbitrar_desde_informe",
                          return_value={"nota": 2.0, "veredicto": "feo",
                                        "defectos": ["a", "b"]}):
            ok, detalle, _ = ap._mirar_en_navegador("<html></html>")
        assert ok is True, "la estetica no puede reprobar una pagina que corre"
        assert "2.0/10" in detalle

    def test_vlm_que_explota_no_rompe_nada(self):
        from cognia.program_creator import arbitro_visual as av
        with patch.object(av, "vlm_disponible", side_effect=RuntimeError("boom")):
            assert "error al mirar" in ap._mirar_con_vlm(_informe(), "idea")
