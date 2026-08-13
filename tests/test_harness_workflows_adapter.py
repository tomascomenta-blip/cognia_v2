# -*- coding: utf-8 -*-
"""El agente sabe usar su propio motor de workflows.

`cognia/agent/workflows.py` estaba completo desde el 2026-08-11 y HUERFANO: sin
comando del REPL y sin herramienta del agente. Este fichero fija el contrato del
adaptador que lo pone a su alcance, incluidos los dos bugs que solo aparecieron
probando contra el modelo real (2026-08-13):

  - `PresupuestoTokens.gastado` es un METODO: leerlo como atributo reportaba
    "0 tokens" mientras el journal registraba 844.
  - Qwythos cuela sintaxis de otra plantilla DENTRO del argumento
    ("...TLS</parameter>\\n<parameter=modo>\\nparalelo"), y sin sanearla el
    adaptador lanzaba 5 subtareas —dos de ellas basura— pagando una llamada al
    LLM por cada una.

Los tests que ejercitan el motor de verdad NO llaman al modelo: inyectan un
doble por el parametro documentado del motor.
"""

from __future__ import annotations

import pytest

from cognia.harness import workflows_adapter as wf


# ── partir_pasos ───────────────────────────────────────────────────────
def test_separa_por_punto_y_coma_y_limpia_numeracion():
    pasos = wf.partir_pasos("1. resume HTTP; 2) resume DNS; - resume TLS")
    assert pasos == ["resume HTTP", "resume DNS", "resume TLS"], (
        "un paso que empieza por '3.' hace creer al modelo que le falta contexto")


def test_separa_por_saltos_de_linea():
    assert wf.partir_pasos("uno\ndos\n\ntres") == ["uno", "dos", "tres"]


def test_texto_vacio_no_da_pasos():
    assert wf.partir_pasos("") == []
    assert wf.partir_pasos("   ;  ; ") == []


# ── el saneado de lo que emite el modelo real ──────────────────────────
CONTAMINADO = ("investigar HTTP; investigar DNS; investigar TLS"
               "</parameter>\n<parameter=modo>\nparalelo")


def test_los_restos_de_plantilla_no_se_vuelven_subtareas():
    pasos = wf.partir_pasos(CONTAMINADO)
    assert len(pasos) == 3, f"se colaron subtareas basura: {pasos}"
    assert all("parameter" not in p for p in pasos), pasos
    assert pasos[-1] == "investigar TLS"


def test_el_argumento_incrustado_se_recupera_en_vez_de_perderse():
    _, claves = wf.sanear(CONTAMINADO)
    assert claves.get("modo") == "paralelo", (
        "el modelo queria modo=paralelo; tirarlo pierde su intencion")


def test_sanear_no_toca_un_texto_normal():
    limpio, claves = wf.sanear("resume HTTP; resume DNS")
    assert limpio == "resume HTTP; resume DNS"
    assert claves == {}


# ── topes ──────────────────────────────────────────────────────────────
def test_no_se_pasa_del_tope_de_pasos(monkeypatch):
    llamadas = []

    def _falso_agente(c, prompt, **kw):
        llamadas.append(prompt)
        return f"respuesta a {prompt}"

    monkeypatch.setattr("cognia.agent.workflows.agente", _falso_agente)
    muchos = "; ".join(f"tarea {i}" for i in range(20))
    res = wf.ejecutar(muchos, modo="secuencial", nombre="test_tope")
    assert res["pasos"] == wf.MAX_PASOS
    assert len(llamadas) == wf.MAX_PASOS, (
        "mas pasos no es mas capacidad: es mas espera y mas tokens")


def test_un_paso_no_puede_lanzar_otro_workflow(monkeypatch):
    """Sin este tope, un workflow dentro de otro se multiplica."""
    monkeypatch.setattr(wf._dentro, "activo", True, raising=False)
    res = wf.ejecutar("a; b", nombre="test_recursion")
    assert res["ok"] is False
    assert "DENTRO de un workflow" in res["error"]


def test_sin_subtareas_devuelve_error_util():
    res = wf.ejecutar("", nombre="test_vacio")
    assert res["ok"] is False
    assert "al menos una" in res["error"]


# ── el resultado que ve el modelo ──────────────────────────────────────
def test_consolida_con_los_fallos_visibles(monkeypatch):
    def _falso_agente(c, prompt, **kw):
        if "rota" in prompt:
            return {"_error": "presupuesto agotado"}
        return f"ok: {prompt}"

    monkeypatch.setattr("cognia.agent.workflows.agente", _falso_agente)
    res = wf.ejecutar("buena; rota", modo="secuencial", nombre="test_mixto")
    assert res["ok"] is True, "un fallo parcial no invalida el resto"
    assert "ok: buena" in res["texto"]
    assert "presupuesto agotado" in res["texto"], (
        "un paso que fallo tiene que verse: si no, el modelo cree que salio todo")
    assert "1 de 2" in res["texto"]


def test_devuelve_el_run_id_para_poder_reanudar(monkeypatch):
    monkeypatch.setattr("cognia.agent.workflows.agente",
                        lambda c, prompt, **kw: "listo")
    res = wf.ejecutar("una tarea", modo="secuencial", nombre="test_runid")
    assert res["run_id"], "sin run_id no se puede usar corrida(resume_de=...)"


def test_los_tokens_reportados_no_son_cero(monkeypatch):
    """`gastado` es un metodo: leerlo como atributo daba siempre 0."""
    def _falso_agente(c, prompt, **kw):
        c.presupuesto.registrar({"prompt_tokens": 10, "completion_tokens": 30})
        return "listo"

    monkeypatch.setattr("cognia.agent.workflows.agente", _falso_agente)
    res = wf.ejecutar("a; b", modo="secuencial", nombre="test_tokens")
    assert res["tokens"] == 80, f"reporto {res['tokens']} en vez de 80"


# ── el registro nativo ─────────────────────────────────────────────────
def test_la_tool_se_publica_con_firma_tipada(monkeypatch):
    monkeypatch.setenv("COGNIA_WORKFLOW_TOOL", "1")
    from cognia.agent.tool_schemas import schemas_para
    fn = next(s["function"] for s in schemas_para({"workflow"})
              if s["function"]["name"] == "workflow")
    props = fn["parameters"]["properties"]
    assert set(props) == {"pasos", "modo"}
    assert fn["parameters"]["required"] == ["pasos"]
    assert "args" not in props, "salio como string generico, no como firma"


def test_la_tool_no_engorda_el_catalogo_por_defecto(monkeypatch):
    from cognia.agent.tools import CORE_TOOLS, TOOLS, flag_de_optin
    from cognia.simple_mode import visible_tools
    assert "workflow" not in CORE_TOOLS
    assert flag_de_optin("workflow") == "COGNIA_WORKFLOW_TOOL"
    monkeypatch.delenv("COGNIA_WORKFLOW_TOOL", raising=False)
    assert "workflow" not in visible_tools(set(TOOLS), override="sencillo")
