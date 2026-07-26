"""
Los dos fixes de la noche del 26/07 contra el lazo con gpt-oss de cerebro:

1. reparar_web pasa reasoning_effort=low + timeout largo + UN reintento.
   Medido (scripts/probe_reparacion_budget.py): sin el kwarg, 6/6 sondas
   mueren en finish=length con 22-53k chars de razonamiento y contenido 0
   (las 4 reparaciones del brazo BoN murieron asi); con el, 2/2 reparan en
   ~3000 tokens. La linea "Reasoning: low" en el system NO lo consigue: el
   esfuerzo real lo fija chat_template_kwargs del server.
2. generar_contrato rechaza contratos con pasos malformados (un dict donde
   va un string -> AttributeError .strip() dentro de juzgar_web en CADA
   ronda: contrato existente pero inusable, que ademas bloquea el reintento).
"""

from unittest.mock import patch

from cognia import llm_local
from cognia.program_creator import generator as g
from cognia.program_creator.generator import GeneratedProgram
from cognia.program_creator.juez_ejecutable import _pasos_validos


def _prog():
    return GeneratedProgram(title="P", description="d",
                            code="<html><body>x</body></html>",
                            category="dashboard", lenguaje="html")


# ── el kwarg viaja hasta el payload del server ───────────────────────────────

def test_generar_pone_reasoning_effort_en_el_payload():
    capturado = {}

    def _post_falso(url, payload, timeout=120):
        capturado.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    with patch.object(llm_local, "_post", side_effect=_post_falso), \
         patch.object(llm_local, "detectar_backend",
                      return_value={"tipo": "llama", "url": "http://x"}):
        llm_local.generar("p", reasoning_effort="low")
    assert capturado["chat_template_kwargs"] == {"reasoning_effort": "low"}


def test_generar_sin_effort_no_toca_el_template():
    capturado = {}

    def _post_falso(url, payload, timeout=120):
        capturado.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    with patch.object(llm_local, "_post", side_effect=_post_falso), \
         patch.object(llm_local, "detectar_backend",
                      return_value={"tipo": "llama", "url": "http://x"}):
        llm_local.generar("p")
    assert "chat_template_kwargs" not in capturado


def test_reparar_web_pide_effort_low_y_reintenta_una_vez():
    llamadas = []

    def _generar_falso(prompt, system="", temperature=0.4, max_tokens=600,
                       via="", timeout=120, reasoning_effort=None):
        llamadas.append(reasoning_effort)
        return None                          # siempre vacio: cola estocastica

    with patch.object(g, "generar", side_effect=_generar_falso), \
         patch.object(g, "_call_ollama", return_value=None):
        r = g.reparar_web(_prog(), ["(juez) x: esperaba 1"])
    assert r is None
    # DOS llamadas (la original + el reintento), ambas con effort=low.
    # _call_llm cae a Ollama tras generar; el mock de generar es el que cuenta.
    assert llamadas == ["low", "low"]


# ── contratos malformados se rechazan, los legitimos no ──────────────────────

def test_pasos_con_dict_donde_va_string_se_rechazan():
    assert not _pasos_validos([{"accion": {"tipo": "click"}, "selector": "#a"}])
    assert not _pasos_validos([{"accion": "click", "selector": {"css": "#a"}}])
    assert not _pasos_validos([{"accion": "tecla", "key": {"k": "Enter"}}])
    assert not _pasos_validos("no soy una lista")
    assert not _pasos_validos([])


def test_pasos_legitimos_pasan():
    assert _pasos_validos([
        {"accion": "click", "selector": "#mas", "tras_ms": 300},
        {"accion": "escribir", "selector": "#nueva", "texto": 5},
        {"nombre": "grupo", "critico": True,
         "acciones": [{"accion": "existe", "selector": ".tile"}]},
        {"accion": "contar", "selector": ".tile", "esperado": 16},
    ])
