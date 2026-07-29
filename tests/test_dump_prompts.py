"""Test del volcado pasivo de prompts de _call_llm (COGNIA_DUMP_PROMPTS)."""

import json

from cognia.program_creator.generator import _call_llm


def test_volcado_pasivo_registra_el_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_DUMP_PROMPTS", str(tmp_path))
    salida = _call_llm("PROMPT DEL LAZO", lenguaje="html",
                       llm=lambda p, s, m, t: "<html>x</html>")
    assert salida == "<html>x</html>"
    lineas = (tmp_path / "prompts.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    fila = json.loads(lineas[-1])
    assert fila["prompt"] == "PROMPT DEL LAZO"
    assert fila["lenguaje"] == "html"
    assert "system" in fila and fila["system"]


def test_apagado_por_defecto_no_escribe(monkeypatch, tmp_path):
    monkeypatch.delenv("COGNIA_DUMP_PROMPTS", raising=False)
    _call_llm("otro", lenguaje="html", llm=lambda p, s, m, t: "ok")
    assert not (tmp_path / "prompts.jsonl").exists()
