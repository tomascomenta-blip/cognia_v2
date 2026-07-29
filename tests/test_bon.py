"""Tests de cognia/program_creator/bon.py — modo BoN de réplicas
independientes (PREREG_BON_HELDOUT). Sin GPU: construir_para_mockup y
juzgar_web se monkeypatchean; lo que se prueba es la selección, el gating
por env y la degradación ruidosa sin selector."""

from types import SimpleNamespace

import pytest

from cognia.program_creator import bon
from cognia.program_creator import diseno_a_codigo, juez_ejecutable


class _Res:
    """Doble mínimo de ResultadoDiseno: lo único que bon usa."""

    def __init__(self, html):
        self._html = html
        self.bon = None

    @property
    def html(self):
        return self._html

    def html_entregable(self):
        return self._html


def _veredicto(aprobado, checks_ok, total=5):
    checks = ([SimpleNamespace(ok=True)] * checks_ok
              + [SimpleNamespace(ok=False)] * (total - checks_ok))
    return SimpleNamespace(aprobado=aprobado, checks=checks)


CONTRATO = {"nombre": "sel", "pasos": [{"accion": "contar", "selector": ".x",
                                        "esperado": 1, "critico": True}]}


def test_k_configurado(monkeypatch):
    monkeypatch.delenv(bon.BON_K_ENV, raising=False)
    assert bon.k_configurado() == 1
    monkeypatch.setenv(bon.BON_K_ENV, "4")
    assert bon.k_configurado() == 4
    monkeypatch.setenv(bon.BON_K_ENV, "abc")
    assert bon.k_configurado() == 1
    monkeypatch.setenv(bon.BON_K_ENV, "0")
    assert bon.k_configurado() == 1


def test_selector_configurado(monkeypatch, tmp_path):
    monkeypatch.delenv(bon.BON_SELECTOR_ENV, raising=False)
    assert bon.selector_configurado() is None
    f = tmp_path / "sel.json"
    f.write_text('{"nombre": "x", "pasos": [{"accion": "contar"}]}',
                 encoding="utf-8")
    monkeypatch.setenv(bon.BON_SELECTOR_ENV, str(f))
    assert bon.selector_configurado()["nombre"] == "x"
    monkeypatch.setenv(bon.BON_SELECTOR_ENV, str(tmp_path / "no_existe.json"))
    assert bon.selector_configurado() is None
    # un JSON sin pasos no es un contrato: no vale como selector
    f.write_text('{"nombre": "x"}', encoding="utf-8")
    monkeypatch.setenv(bon.BON_SELECTOR_ENV, str(f))
    assert bon.selector_configurado() is None


def test_k1_delega_sin_bon(monkeypatch):
    centinela = _Res("<html>a</html>")
    llamadas = []
    monkeypatch.setattr(diseno_a_codigo, "construir_para_mockup",
                        lambda idea, **kw: llamadas.append(idea) or centinela)
    monkeypatch.delenv(bon.BON_K_ENV, raising=False)
    res = bon.construir_bon("una idea", k=1, verbose=False)
    assert res is centinela and llamadas == ["una idea"]
    assert res.bon is None          # k=1 no anota metadatos de muestreo


def test_sin_selector_degrada_a_una_replica(monkeypatch, capsys):
    centinela = _Res("<html>a</html>")
    llamadas = []
    monkeypatch.setattr(diseno_a_codigo, "construir_para_mockup",
                        lambda idea, **kw: llamadas.append(idea) or centinela)
    monkeypatch.delenv(bon.BON_SELECTOR_ENV, raising=False)
    res = bon.construir_bon("idea", k=4, verbose=False)
    assert res is centinela and len(llamadas) == 1
    assert "SIN contrato selector" in capsys.readouterr().out


def test_elige_la_aprobada(monkeypatch, tmp_path):
    resultados = [_Res("<html>1</html>"), _Res("<html>2</html>"),
                  _Res("<html>3</html>")]
    monkeypatch.setattr(diseno_a_codigo, "construir_para_mockup",
                        lambda idea, **kw: resultados.pop(0))
    veredictos = [_veredicto(False, 2), _veredicto(True, 5),
                  _veredicto(False, 4)]
    monkeypatch.setattr(juez_ejecutable, "juzgar_web",
                        lambda html, c: veredictos.pop(0))
    res = bon.construir_bon("idea", k=3, contrato_selector=CONTRATO,
                            guardar_muestras=tmp_path, verbose=False)
    assert res.html == "<html>2</html>"
    assert res.bon["elegida_s"] == 2 and res.bon["k"] == 3
    assert len(res.bon["muestras"]) == 3
    assert (tmp_path / "s2" / "index.html").is_file()


def test_desempate_por_checks_y_orden(monkeypatch, tmp_path):
    resultados = [_Res("<html>1</html>"), _Res("<html>2</html>"),
                  _Res("<html>3</html>")]
    monkeypatch.setattr(diseno_a_codigo, "construir_para_mockup",
                        lambda idea, **kw: resultados.pop(0))
    # ninguna aprueba: gana la de mas checks; empate -> la mas temprana
    veredictos = [_veredicto(False, 4), _veredicto(False, 2),
                  _veredicto(False, 4)]
    monkeypatch.setattr(juez_ejecutable, "juzgar_web",
                        lambda html, c: veredictos.pop(0))
    res = bon.construir_bon("idea", k=3, contrato_selector=CONTRATO,
                            guardar_muestras=tmp_path, verbose=False)
    assert res.bon["elegida_s"] == 1


def test_replica_que_crashea_no_mata_el_modo(monkeypatch, tmp_path):
    estados = iter([RuntimeError("boom"), _Res("<html>2</html>")])

    def _fabricar(idea, **kw):
        r = next(estados)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(diseno_a_codigo, "construir_para_mockup", _fabricar)
    monkeypatch.setattr(juez_ejecutable, "juzgar_web",
                        lambda html, c: _veredicto(True, 5))
    res = bon.construir_bon("idea", k=2, contrato_selector=CONTRATO,
                            guardar_muestras=tmp_path, verbose=False)
    assert res.bon["elegida_s"] == 2
    assert res.bon["muestras"][0]["error"].startswith("RuntimeError")


def test_todas_crashean_lanza(monkeypatch, tmp_path):
    def _fabricar(idea, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(diseno_a_codigo, "construir_para_mockup", _fabricar)
    with pytest.raises(RuntimeError, match="las 2 replicas|boom"):
        bon.construir_bon("idea", k=2, contrato_selector=CONTRATO,
                          guardar_muestras=tmp_path, verbose=False)


def test_sin_html_devuelve_ultimo_con_meta(monkeypatch, tmp_path):
    resultados = [_Res(None), _Res(None)]
    monkeypatch.setattr(diseno_a_codigo, "construir_para_mockup",
                        lambda idea, **kw: resultados.pop(0))
    res = bon.construir_bon("idea", k=2, contrato_selector=CONTRATO,
                            guardar_muestras=tmp_path, verbose=False)
    assert res.html is None
    assert res.bon["elegida_s"] is None and res.bon["k"] == 2


def test_juez_crasheado_no_mata_la_seleccion(monkeypatch, tmp_path):
    resultados = [_Res("<html>1</html>"), _Res("<html>2</html>")]
    monkeypatch.setattr(diseno_a_codigo, "construir_para_mockup",
                        lambda idea, **kw: resultados.pop(0))
    veredictos = iter([RuntimeError("juez caido"), _veredicto(True, 5)])

    def _juzgar(html, c):
        v = next(veredictos)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(juez_ejecutable, "juzgar_web", _juzgar)
    res = bon.construir_bon("idea", k=2, contrato_selector=CONTRATO,
                            guardar_muestras=tmp_path, verbose=False)
    assert res.bon["elegida_s"] == 2
    assert res.bon["muestras"][0]["sel_crasheo"].startswith("juez caido")
