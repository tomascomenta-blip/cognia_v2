"""
Cableado de /construir al CLI: Cognia.construir_web corre el lazo diseno-a-codigo
y guarda el index.html resultante. Aqui se cubre la LOGICA (guardado + formato +
guardas) sin servidores: el lazo se parchea; su e2e real ya se verifico aparte.
"""

import types
from pathlib import Path
from unittest.mock import patch

from cognia.cognia import Cognia


def _fake_self():
    # construir_web solo lee self._orchestrator (via _llm_de_cognia).
    return types.SimpleNamespace(_orchestrator=None)


def _fake_res(html="<html><body>ok</body></html>", nota=6.5, rondas=2,
              defectos=None, mockup=None, motivo="tope de rondas",
              sello="APROBADO"):
    return types.SimpleNamespace(
        html=html, program=object(), nota_visual=nota, rondas=rondas,
        defectos=defectos or ["x"], mockup=mockup, motivo_corte=motivo,
        sello=sello, veredicto=None, contrato=None,
        assets={}, html_entregable=lambda: html)


def test_idea_vacia_devuelve_uso():
    r = Cognia.construir_web(_fake_self(), "   ")
    assert "Uso:" in r


def test_guarda_html_y_reporta_fidelidad(tmp_path):
    res = _fake_res()
    with patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
               return_value=res), \
         patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path):
        out = Cognia.construir_web(_fake_self(), "dashboard de ventas")

    destino = tmp_path / "construidos" / "dashboard_de_ventas" / "index.html"
    assert destino.exists()
    assert "ok" in destino.read_text(encoding="utf-8")
    # El sello del juez manda; la fidelidad visual solo acompana a un APROBADO.
    assert "APROBADO por juez ejecutable" in out
    assert "6.5/10" in out
    assert "2 ronda" in out


def test_sin_verificar_no_muestra_numero(tmp_path):
    """Regla del dueno: si no hubo contrato, el sello dice 'sin verificar' y
    NUNCA aparece un numero de calidad al lado."""
    res = _fake_res(sello="sin verificar", nota=6.5)
    with patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
               return_value=res), \
         patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path):
        out = Cognia.construir_web(_fake_self(), "dashboard de ventas")
    assert "sin verificar" in out
    assert "6.5/10" not in out


def test_sin_html_reporta_el_motivo(tmp_path):
    res = _fake_res(html=None, motivo="no se pudo generar la pagina inicial")
    with patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
               return_value=res), \
         patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path):
        out = Cognia.construir_web(_fake_self(), "algo imposible")
    assert "No se pudo construir" in out
    assert "no se pudo generar" in out


def test_copia_el_mockup_si_existe(tmp_path):
    mock = tmp_path / "m.png"
    mock.write_bytes(b"\x89PNG\r\n")
    res = _fake_res(mockup=str(mock))
    with patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
               return_value=res), \
         patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path):
        out = Cognia.construir_web(_fake_self(), "landing", usar_mockup=True)
    assert (tmp_path / "construidos" / "landing" / "mockup.png").exists()
    assert "Mockup:" in out
