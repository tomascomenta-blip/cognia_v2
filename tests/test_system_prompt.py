# -*- coding: utf-8 -*-
"""System prompt grande (cognia/system_prompt.py, pedido del dueno 2026-07-23).

Lo que se protege aca: que exista contenido real por rol, que el perfil chico
NO reciba el prompt largo (sobre-instruir degrada al 3B) y que el cerebro siga
heredando su identidad aunque el modulo nuevo falle.
"""
import pytest

from cognia.system_prompt import build_system_prompt, tamano


def test_identidad_en_todos_los_roles_y_perfiles():
    for rol in ("cerebro", "agente"):
        for perfil in ("minimo", "compacto", "completo"):
            t = build_system_prompt(rol, perfil)
            assert "Cognia" in t and "Tomas Montes" in t


def test_las_reglas_de_tools_no_van_en_el_system():
    """Medido 2026-07-23: dos manuales (system + TOOLS_DOC) compiten y el gate
    cae de 10/10 a 3/5 corridas perfectas. El system del agente lleva conducta;
    el manual vive en reglas_de_herramientas(), que se pliega al TOOLS_DOC."""
    t = build_system_prompt("agente", "completo")
    assert "escribir_archivo" not in t
    assert "agente" in t.lower()          # si conserva su rol


def test_reglas_apagadas_por_defecto(monkeypatch):
    """A/B 2026-07-23: plegar el manual al TOOLS_DOC baja el gate de 10/10 a
    2/6 corridas perfectas. Se enciende a mano o no se enciende."""
    from cognia.system_prompt import reglas_de_herramientas
    monkeypatch.delenv("COGNIA_SYSTEM_PROMPT_PERFIL", raising=False)
    assert reglas_de_herramientas() == ""
    monkeypatch.setenv("COGNIA_SYSTEM_PROMPT_PERFIL", "completo")
    assert "escribir_archivo" in reglas_de_herramientas()


def test_reglas_de_herramientas_traen_lo_medido():
    from cognia.system_prompt import reglas_de_herramientas
    plano = " ".join(reglas_de_herramientas("completo").split())
    assert "comillas triples" in plano
    assert "SOBRESCRIBE" in plano
    assert "ACCION" in plano and "responder" in plano


def test_reglas_compactas_mas_cortas():
    from cognia.system_prompt import reglas_de_herramientas
    assert len(reglas_de_herramientas("compacto")) < len(reglas_de_herramientas("completo"))
    assert reglas_de_herramientas("minimo") == ""


def test_el_cerebro_no_recibe_el_manual_de_tools():
    """El cerebro decide y conversa: el manual de ACCION solo estorba."""
    t = build_system_prompt("cerebro", "completo")
    assert "ACCION" not in t
    assert "cerebro" in t.lower()


def test_compacto_es_mas_corto_que_completo():
    """Sobre-instruir degrada a los modelos chicos: el perfil chico es corto."""
    c = tamano("cerebro", "compacto")["chars"]
    f = tamano("cerebro", "completo")["chars"]
    assert c < f, f"compacto {c} deberia ser menor que completo {f}"


def test_minimo_es_solo_identidad():
    t = build_system_prompt("agente", "minimo")
    assert "COMO TE COMPORTAS" not in t and len(t) < 400


def test_perfil_auto_por_tamano_de_modelo(monkeypatch):
    import cognia.system_prompt as sp
    monkeypatch.delenv("COGNIA_SYSTEM_PROMPT_PERFIL", raising=False)
    monkeypatch.setenv("LLAMA_GGUF_PATH", "/models/qwen2.5-7b-instruct-q4.gguf")
    assert sp._perfil_auto() == "completo"
    monkeypatch.setenv("LLAMA_GGUF_PATH", "/models/qwen-coder-3b-q4.gguf")
    assert sp._perfil_auto() == "compacto"          # default seguro


def test_override_por_env(monkeypatch):
    import cognia.system_prompt as sp
    monkeypatch.setenv("COGNIA_SYSTEM_PROMPT_PERFIL", "minimo")
    assert sp._perfil_auto() == "minimo"


def test_aviso_de_arbitro_opcional():
    sin = build_system_prompt("agente", "completo", con_arbitro=False)
    con = build_system_prompt("agente", "completo", con_arbitro=True)
    assert "arbitro" in con.lower() and "arbitro" not in sin.lower()
    assert len(con) > len(sin)


def test_el_cerebro_hereda_la_base_grande():
    """adaptive_prompt debe construir sobre el system prompt nuevo."""
    from cognia.agent.adaptive_prompt import _base
    b = _base()
    assert "Cognia" in b and len(b) > 300      # ya no son las 4 lineas viejas


def test_base_no_revienta_sin_perfil(monkeypatch):
    monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)
    monkeypatch.delenv("COGNIA_SYSTEM_PROMPT_PERFIL", raising=False)
    assert build_system_prompt("agente")       # no lanza
