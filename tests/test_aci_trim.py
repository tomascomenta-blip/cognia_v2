# -*- coding: utf-8 -*-
"""ACI: compactacion de tool-outputs (mejora de harness).

2026-08-14: estos tests pasaron a fijar la VENTANA explícitamente. Antes
asumían el cap fijo de 1800 y, cuando el cap pasó a escalar con `n_ctx`, su
resultado dependía de si había un llama-server vivo y con qué contexto — un
test que cambia de veredicto según lo que corra en la máquina no protege
nada. La ventana se declara en cada caso.
"""
import cognia.agent.tools as tools

# Las dos ventanas que importan: donde se midió el 1800 original, y la que
# sirve el cerebro de hoy.
CTX_VIEJO = 16_384
CTX_MILLON = 1_048_576


def test_output_corto_intacto():
    s = "RESULTADO listar: a.py b.py c.py"
    assert tools.aci_trim(s, "listar") == s


def test_output_largo_recortado(tmp_path, monkeypatch):
    """Contrafactual: a la ventana donde se midió, el recorte es el de siempre."""
    import cognia.agents.workers.dev_tools as dev
    monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(tools, "_n_ctx_actual", lambda: CTX_VIEJO)
    largo = "RESULTADO leer_archivo: " + ("X" * 5000)
    out = tools.aci_trim(largo, "leer_archivo")
    assert len(out) < len(largo)
    assert out.startswith("RESULTADO leer_archivo: XXX")   # cabeza preservada
    assert "chars omitidos" in out
    assert out.endswith("X" * 50)                          # cola preservada
    # el completo se guardo
    over = list((tmp_path / ".aci_overflow").glob("*.txt"))
    assert over and over[0].read_text(encoding="utf-8") == largo


def test_con_ventana_de_un_millon_el_stack_entero_llega(tmp_path, monkeypatch):
    """La mejora: 5.000 chars son el 0,015% de un contexto de 1M. Recortarlos
    ahí no protegía la ventana, tiraba el medio del stack trace."""
    import cognia.agents.workers.dev_tools as dev
    monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(tools, "_n_ctx_actual", lambda: CTX_MILLON)
    largo = "RESULTADO ejecutar: " + ("X" * 5000) + "\nTraceback: boom"
    assert tools.aci_trim(largo, "ejecutar") == largo      # intacto
    # Pero sigue habiendo techo: 100k de output no entran ni con 1M.
    gigante = "RESULTADO ejecutar: " + ("Y" * 100_000)
    out = tools.aci_trim(gigante, "ejecutar")
    assert "chars omitidos" in out and len(out) < 25_000


def test_run_tool_aplica_trim(tmp_path, monkeypatch):
    import cognia.agents.workers.dev_tools as dev
    monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(tools, "_n_ctx_actual", lambda: CTX_VIEJO)
    tools.TOOLS["_falsa_larga"] = {
        "fn": lambda a, c: "RESULTADO _falsa_larga: " + ("Y" * 4000),
        "doc": "x", "danger": False}
    try:
        r = tools.run_tool("_falsa_larga", "", {})
        assert "chars omitidos" in r and len(r) < 2500
    finally:
        del tools.TOOLS["_falsa_larga"]
