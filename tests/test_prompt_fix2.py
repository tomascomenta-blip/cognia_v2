"""
COGNIA_PROMPT_FIX2 — los dos ladrones del prompt cazados por la sonda del
2026-07-27 (PREREG_BON_RONDAS, novena/décima enmienda):

1. El troceo por comas de _componentes_de_idea MUTILA enumeraciones: la
   checklist decía "REQUIRED: data-precio 100" cuando la idea pide
   "data-precio 100,50,25" — le miente al modelo sobre los datos exactos
   que el contrato verifica (−2 celdas netas apareadas en el brutal).
2. La regla "Format numbers for humans (toLocaleString)" produce "8,00"
   donde un contrato interactivo exige "8" exacto (falla crítica idéntica
   en 2 de 3 réplicas de hoja_calculo).

El fix va env-gated para poder INTERCALAR el A/B de confirmación; estos
tests fijan ambos comportamientos (con y sin flag).
"""

from cognia.program_creator.generator import (_build_prompt_web,
                                              _componentes_de_idea)

_IDEA_CARRITO = (
    'Un carrito de compra con STOCK en un solo archivo HTML. OBLIGATORIO: '
    '3 productos como <div class="prod"> con data-id p1,p2,p3, data-precio '
    '100,50,25 y data-stock 2,3,1. Cada uno tiene un <button class="add">.')

_IDEA_DASHBOARD = "Un dashboard de inversiones con grafico y tabla"


def test_troceo_por_comas_mutila_sin_flag(monkeypatch):
    monkeypatch.delenv("COGNIA_PROMPT_FIX2", raising=False)
    partes = _componentes_de_idea(_IDEA_CARRITO)
    # el comportamiento viejo (documentado, no deseado): fragmentos mutilados
    assert any(p == "data-precio 100" for p in partes)
    assert not any("100,50,25" in p for p in partes)


def test_troceo_por_frases_preserva_enumeraciones(monkeypatch):
    monkeypatch.setenv("COGNIA_PROMPT_FIX2", "1")
    partes = _componentes_de_idea(_IDEA_CARRITO)
    assert any("data-precio 100,50,25" in p for p in partes)
    assert any("data-stock 2,3,1" in p for p in partes)
    assert not any(p == "data-precio 100" for p in partes)


def test_troceo_con_flag_corta_el_adorno_target_look(monkeypatch):
    # fix2 v3 (UNDÉCIMA enmienda): el lazo adorna la idea con ". TARGET
    # LOOK, match it: {brief}" y el troceo por frases del v2 absorbía el
    # brief ENTERO como REQUIRED component (mecanismo verificado sin GPU
    # tras el A/B ON 12/24 vs OFF 17/24). El troceo debe operar sobre la
    # idea ORIGINAL: nada del brief entra a la checklist.
    monkeypatch.setenv("COGNIA_PROMPT_FIX2", "1")
    adornada = (_IDEA_CARRITO + ". TARGET LOOK, match it: paleta oscura "
                "con acentos neon, tarjetas con sombra suave, tipografia "
                "grande y bordes redondeados")
    partes = _componentes_de_idea(adornada)
    assert any("data-precio 100,50,25" in p for p in partes)
    assert not any("TARGET LOOK" in p or "neon" in p or "sombra" in p
                   for p in partes)


def test_regla_de_numeros_exactos_en_interactiva(monkeypatch):
    monkeypatch.setenv("COGNIA_PROMPT_FIX2", "1")
    p = _build_prompt_web(_IDEA_CARRITO, "hint")
    assert "EXACTLY as the idea and the current state" in p
    assert "toLocaleString" not in p


def test_dashboard_conserva_formato_humano_con_flag(monkeypatch):
    monkeypatch.setenv("COGNIA_PROMPT_FIX2", "1")
    p = _build_prompt_web(_IDEA_DASHBOARD, "hint")
    assert "toLocaleString" in p


def test_sin_flag_todo_queda_como_estaba(monkeypatch):
    monkeypatch.delenv("COGNIA_PROMPT_FIX2", raising=False)
    p = _build_prompt_web(_IDEA_CARRITO, "hint")
    assert "toLocaleString" in p
    assert "EXACTLY as the idea and the current state" not in p
