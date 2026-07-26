"""
_llm_de_cognia tiene que hablar por el endpoint de CHAT, no por /completion.

Regresion del 2026-07-26: la version que envolvia orch.infer (prompt crudo,
sin plantilla) hacia que un cerebro de razonamiento (gpt-oss) pensara en texto
plano y agotara max_tokens antes del HTML — el lazo diseno-a-codigo rechazaba
la generacion inicial y caia al camino corto, asi que el sistema nunca
ejercitaba mockup/arbitro/juez. El wrapper debe delegar en llm_local.generar
(que usa /v1/chat/completions y deja auditoria).
"""

from unittest.mock import patch

from cognia.program_creator.program_creator import _llm_de_cognia


class _ConOrq:
    _orchestrator = object()


class _SinOrq:
    _orchestrator = None


def test_delega_en_llm_local_generar_con_system_separado():
    capturado = {}

    def _generar(prompt, system="", temperature=0.4, max_tokens=600,
                 via="llm_local", timeout=None):
        capturado.update(prompt=prompt, system=system,
                         temperature=temperature, max_tokens=max_tokens,
                         via=via)
        return "Title: x\n```html\n<html></html>\n```"

    with patch("cognia.llm_local.generar", side_effect=_generar):
        llm = _llm_de_cognia(_ConOrq())
        out = llm("haz una pagina", "eres frontend", 6000, 0.2)

    assert out.startswith("Title:")
    # El system viaja como rol de sistema (plantilla de chat), NO concatenado
    # al prompt crudo — esa concatenacion era el bug.
    assert capturado["system"] == "eres frontend"
    assert "eres frontend" not in capturado["prompt"]
    assert capturado["max_tokens"] == 6000
    assert capturado["temperature"] == 0.2
    assert capturado["via"] == "construir"


def test_sin_orquestador_devuelve_none():
    assert _llm_de_cognia(_SinOrq()) is None


def test_respuesta_vacia_es_none():
    with patch("cognia.llm_local.generar", return_value=""):
        llm = _llm_de_cognia(_ConOrq())
        assert llm("p") is None
