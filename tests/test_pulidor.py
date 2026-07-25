"""
El LOOP THINKING (pulidor): construir -> juzgar -> pensar -> ¿otro ciclo?
Estos tests parchean flota/LLM/juez y verifican la LOGICA de los ciclos y los
cortes; el e2e real (con swaps de flota de verdad) se corre aparte.
"""

from unittest.mock import patch

from cognia.program_creator import pulidor as pl
from cognia.program_creator.generator import GeneratedProgram


def _prog(code="<html><body>v1</body></html>"):
    return GeneratedProgram(title="P", description="d", code=code,
                            category="g", lenguaje="html")


class _R1:
    """ResultadoDiseno falso del ciclo 1."""
    def __init__(self, code):
        self.program = _prog(code)
        self.motivo_corte = "x"
    def html_entregable(self):
        return self.program.code


def _base_patches(tmp_path, juzgados, decisiones, reparado=None):
    """Parches comunes. juzgados: lista de (nota, defectos, shot) por ciclo.
    decisiones: lista de dicts {'seguir','cambios'} por llamada a _decidir."""
    return [
        patch.object(pl, "_combo", return_value=True),
        patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
              return_value=_R1("<html><body>v1</body></html>")),
        patch.object(pl, "_juzgar", side_effect=juzgados),
        patch.object(pl, "_decidir", side_effect=decisiones),
        patch("cognia.program_creator.generator.reparar_web",
              return_value=reparado),
        patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path),
    ]


def _run(ps, **kw):
    for p in ps:
        p.start()
    try:
        return pl.pulir("un juego chico", verbose=False,
                        gestionar_flota=False, **kw)
    finally:
        for p in reversed(ps):
            p.stop()


def test_corta_por_gate_de_pulido(tmp_path):
    ps = _base_patches(tmp_path, juzgados=[(9.0, [], None)], decisiones=[])
    res = _run(ps, gate_final=8.5)
    assert res.ciclos == 1
    assert "gate de pulido" in res.motivo
    assert (tmp_path / "pulidos" / "un_juego_chico" / "index.html").exists()
    assert (tmp_path / "pulidos" / "un_juego_chico" / "reporte.md").exists()


def test_el_pensador_puede_entregar(tmp_path):
    ps = _base_patches(tmp_path,
                       juzgados=[(6.0, ["algo"], None)],
                       decisiones=[{"seguir": False, "cambios": []}])
    res = _run(ps, gate_final=8.5, ciclos_max=3)
    assert res.ciclos == 1
    assert "ENTREGAR" in res.motivo


def test_ciclo_extra_con_cambios_y_mejora(tmp_path):
    reparado = _prog("<html><body>v2 pulida</body></html>")
    ps = _base_patches(
        tmp_path,
        juzgados=[(6.0, ["feo"], None), (9.0, [], None)],
        decisiones=[{"seguir": True, "cambios": ["mas contraste"]}],
        reparado=reparado)
    res = _run(ps, gate_final=8.5, ciclos_max=3)
    assert res.ciclos == 2
    assert res.nota_final == 9.0
    assert "v2 pulida" in res.html
    # ambos ciclos versionados en disco
    d = tmp_path / "pulidos" / "un_juego_chico"
    assert (d / "ciclo_1.html").exists() and (d / "ciclo_2.html").exists()


def test_disyuntor_sin_mejora_entre_ciclos(tmp_path):
    reparado = _prog("<html><body>v2</body></html>")
    ps = _base_patches(
        tmp_path,
        juzgados=[(6.0, ["x"], None), (5.5, ["x"], None)],
        decisiones=[{"seguir": True, "cambios": ["algo"]}],
        reparado=reparado)
    res = _run(ps, gate_final=8.5, ciclos_max=4)
    assert res.ciclos == 2
    assert "sin mejora" in res.motivo


def test_tope_de_ciclos(tmp_path):
    reparado = _prog("<html><body>v2</body></html>")
    ps = _base_patches(
        tmp_path,
        juzgados=[(5.0, ["x"], None), (6.0, ["x"], None)],
        decisiones=[{"seguir": True, "cambios": ["a"]},
                    {"seguir": True, "cambios": ["b"]}],
        reparado=reparado)
    res = _run(ps, gate_final=9.5, ciclos_max=2)
    assert res.ciclos == 2
    assert res.motivo == "tope de ciclos"


def test_reparacion_sin_cambio_corta_sin_rejuzgar(tmp_path):
    """Si la reparacion no cambia el html, re-juzgar solo muestrea el ruido del
    juez (medido: una nota 'subio' 7.5->8.5 con html identico). Se corta."""
    juzgadas = []

    def _juzgar_contando(goal, html, d):
        juzgadas.append(1)
        return (6.0, ["x"], None)

    ps = [
        patch.object(pl, "_combo", return_value=True),
        patch("cognia.program_creator.diseno_a_codigo.construir_para_mockup",
              return_value=_R1("<html><body>v1</body></html>")),
        patch.object(pl, "_juzgar", side_effect=_juzgar_contando),
        patch.object(pl, "_decidir",
                     return_value={"seguir": True, "cambios": ["algo"]}),
        # la "reparacion" devuelve EL MISMO codigo -> no avanzo
        patch("cognia.program_creator.generator.reparar_web",
              return_value=_prog("<html><body>v1</body></html>")),
        patch("cognia.program_creator.storage.DEFAULT_STORAGE_DIR", tmp_path),
    ]
    res = _run(ps, gate_final=9.5, ciclos_max=4)
    assert len(juzgadas) == 1            # solo se juzgo el ciclo 1
    assert "no avanzo" in res.motivo


def test_decidir_parsea_formato():
    with patch.object(pl, "_pensador", return_value=(
            "DECISION: SEGUIR\nCAMBIOS:\n- mas contraste en el header\n- ejes")):
        d = pl._decidir("g", 6.0, ["x"], 1, 4, [])
    assert d["seguir"] is True
    assert len(d["cambios"]) == 2


def test_decidir_entregar_sin_cambios():
    with patch.object(pl, "_pensador", return_value=(
            "DECISION: ENTREGAR\nCAMBIOS:\n- ninguno")):
        d = pl._decidir("g", 9.0, [], 2, 4, [])
    assert d["seguir"] is False


def test_sin_pensador_entrega_lo_que_hay():
    with patch.object(pl, "_pensador", return_value=None):
        d = pl._decidir("g", 5.0, ["x"], 1, 4, [])
    assert d["seguir"] is False
