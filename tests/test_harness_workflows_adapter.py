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

import sys
from dataclasses import dataclass, field

import pytest

from cognia.harness import workflows_adapter as wf
from cognia.ux import events as ux

# La lista la publica el modulo: un test que la re-escriba a mano deja de
# vigilar la forma fija el dia que alguien agregue una clave en un solo camino.
CLAVES_ENVELOPE = wf.CLAVES_ENVELOPE


@dataclass
class _RespBackend:
    """Lo minimo que agente() mira de una RespuestaChat (misma forma que el
    _Resp de tests/test_workflows_eventos.py). Se inyecta en el BACKEND para
    los tests que necesitan el motor REAL corriendo debajo del adaptador."""
    texto: str = ""
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 3,
                                                 "completion_tokens": 3})
    error: str = ""


@pytest.fixture(autouse=True)
def _dir_wf(tmp_path, monkeypatch):
    """Las corridas de estos tests no escriben en ~/.cognia del dueño."""
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path))


@pytest.fixture
def bus():
    vistos: list = []
    ux.suscribir(vistos.append)
    try:
        yield vistos
    finally:
        ux.desuscribir(vistos.append)


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
    """El doble va en el BACKEND y no en agente() (misma razon que
    test_el_workflow_fin_declara_el_exito): sustituir agente() entero deja al
    motor sin un solo AgenteInicio y el cierre declara la corrida fallida CON
    RAZON. Desde el defecto #1 (2026-08-17) el envelope refleja el veredicto
    del cierre, asi que un doble que se salte el motor ya no puede dar ok=True.
    """
    def _backend(mensajes, **kw):
        if "rota" in mensajes[-1]["content"]:
            return _RespBackend(error="presupuesto agotado")
        return _RespBackend(f"ok: {mensajes[-1]['content']}")

    monkeypatch.setattr("cognia.agent.chat_client.completar", _backend)
    res = wf.ejecutar("buena; rota", modo="secuencial", nombre="test_mixto")
    assert res["ok"] is True, "un fallo parcial no invalida el resto"
    assert res["cancelados"] == 0
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


# --- critica adversarial opt-in (2026-08-15) ---------------------------------

def test_criticar_salida_antepone_el_veredicto(monkeypatch):
    """El veredicto va ARRIBA del texto, no al pie.

    Un 'REFUTADO' detras de 4.000 tokens de informe no lo lee nadie: la razon
    es la misma por la que la lista de tareas se reemite entera al final del
    contexto.
    """
    monkeypatch.setattr("cognia.agent.workflows.agente",
                        lambda c, p, *a, **k: "resultado del paso")
    monkeypatch.setattr(
        "cognia.agent.workflows.criticar",
        lambda c, texto, **k: {"veredicto": "REFUTADO", "refutan": 2,
                               "respondieron": 3, "fanout": "3/3 ok",
                               "mortales": [{"defecto": "la cuenta no da"}]})
    r = wf.ejecutar("paso uno; paso dos", criticar_salida=True)

    assert r["texto"].startswith("[critica: REFUTADO")
    assert "la cuenta no da" in r["texto"]
    assert r["critica"]["veredicto"] == "REFUTADO"


def test_sin_criticar_salida_no_hay_llamada_extra(monkeypatch):
    """Opt-in de verdad: criticar cuesta una llamada POR LENTE, y en un
    workflow de 3 pasos eso duplica el gasto."""
    llamadas = []
    monkeypatch.setattr("cognia.agent.workflows.agente",
                        lambda c, p, *a, **k: "ok")
    monkeypatch.setattr("cognia.agent.workflows.criticar",
                        lambda *a, **k: llamadas.append(1))
    r = wf.ejecutar("paso uno")

    assert llamadas == []
    assert r.get("critica") is None
    assert not r["texto"].startswith("[critica:")


def test_indeterminado_se_declara_como_falta_de_datos(monkeypatch):
    """Sin quorum, el texto tiene que decir que NO es una aprobacion: es
    exactamente donde 'fallo' se lee como 'no habia nada'."""
    monkeypatch.setattr("cognia.agent.workflows.agente",
                        lambda c, p, *a, **k: "ok")
    monkeypatch.setattr(
        "cognia.agent.workflows.criticar",
        lambda c, texto, **k: {"veredicto": "INDETERMINADO", "refutan": 0,
                               "respondieron": 1, "fanout": "1/3 ok, 2 fallidos",
                               "mortales": []})
    r = wf.ejecutar("paso uno", criticar_salida=True)
    assert "NO es una aprobacion" in r["texto"]


# --- el envelope tiene UNA sola forma (tanda UI 2026-08-17) ------------------

def test_todos_los_caminos_devuelven_el_mismo_envelope(monkeypatch):
    """Los caminos de error devolvian 6 claves y el OK 7: un consumidor que
    lea res['critica'] revienta con KeyError justo cuando el workflow falla —
    el mismo fallo silencioso de paralelo() con otro disfraz."""
    import cognia.agent.workflows as motor      # el de verdad, para restaurar
    _agente_real = motor.agente                 # el camino de excepcion lo pisa
    envelopes = {}

    envelopes["sin_pasos"] = wf.ejecutar("", nombre="e_vacio")

    monkeypatch.setattr(wf._dentro, "activo", True, raising=False)
    envelopes["dentro_de_un_workflow"] = wf.ejecutar("a; b", nombre="e_rec")
    monkeypatch.setattr(wf._dentro, "activo", False, raising=False)

    # None en sys.modules -> ImportError en el `from ... import` de ejecutar().
    # Se restaura a mano y NO con monkeypatch.undo(): undo() tira TAMBIEN el
    # COGNIA_WORKFLOWS_DIR del fixture (misma instancia de monkeypatch) y las
    # corridas siguientes escribirian en ~/.cognia de verdad.
    monkeypatch.setitem(sys.modules, "cognia.agent.workflows", None)
    envelopes["motor_no_importable"] = wf.ejecutar("a", nombre="e_import")
    monkeypatch.setitem(sys.modules, "cognia.agent.workflows", motor)

    def _revienta(c, prompt, **kw):
        raise RuntimeError("el backend exploto")

    monkeypatch.setattr("cognia.agent.workflows.agente", _revienta)
    envelopes["excepcion"] = wf.ejecutar("a", modo="secuencial", nombre="e_exc")

    # El exito va con el doble en el BACKEND y con agente() RESTAURADO: con
    # agente() sustituido el motor no ve ningun AgenteInicio y el cierre
    # declara la corrida fallida con razon (y desde el defecto #1 el envelope
    # dice lo mismo que el cierre, en vez de contradecirlo con un ok=True).
    monkeypatch.setattr("cognia.agent.workflows.agente", _agente_real)
    monkeypatch.setattr("cognia.agent.chat_client.completar",
                        lambda mensajes, **kw: _RespBackend("listo"))
    envelopes["exito"] = wf.ejecutar("a", modo="secuencial", nombre="e_ok")

    for camino, res in envelopes.items():
        assert set(res) == CLAVES_ENVELOPE, f"{camino}: {sorted(res)}"

    # Que cada camino sea EL que dice ser: si no, el test pasa por vacio.
    assert "al menos una" in envelopes["sin_pasos"]["error"]
    assert "DENTRO de un workflow" in envelopes["dentro_de_un_workflow"]["error"]
    assert "no disponible" in envelopes["motor_no_importable"]["error"]
    assert "el backend exploto" in envelopes["excepcion"]["error"]
    assert envelopes["exito"]["ok"] is True
    # la clave nueva, en los CINCO caminos y con el tipo correcto
    for camino, res in envelopes.items():
        assert res["cancelados"] == 0, camino


def test_si_criticar_revienta_el_envelope_de_error_sigue_completo(monkeypatch):
    """`critica` sigue siendo None por la inicializacion y el envelope trae
    las siete claves igual.

    LIMITE HONESTO: la otra mitad del contrato —una excepcion POSTERIOR a
    criticar() no borra un veredicto ya pagado con 3 llamadas al LLM— no se
    puede provocar desde fuera hoy, porque dentro del `try` no hay ninguna
    sentencia despues de `criticar()`. El envelope de error pasa la variable
    `critica` y no `None` para que siga siendo cierto el dia que la haya.
    (El `texto` consolidado SI se puede: ver el test de abajo.)
    """
    monkeypatch.setattr("cognia.agent.workflows.agente",
                        lambda c, p, *a, **k: "resultado")

    def _critica_rota(c, texto, **k):
        raise RuntimeError("el critico exploto")

    monkeypatch.setattr("cognia.agent.workflows.criticar", _critica_rota)
    r = wf.ejecutar("paso uno", modo="secuencial", criticar_salida=True,
                    nombre="e_critica")
    assert set(r) == CLAVES_ENVELOPE
    assert r["ok"] is False and r["critica"] is None
    assert "el critico exploto" in r["error"]


def test_el_texto_ya_pagado_sobrevive_a_la_excepcion(monkeypatch):
    """Un fallo DESPUES de consolidar no borra los pasos que si salieron.

    Mismo argumento que `critica`: el consolidado costo hasta 6 llamadas al
    LLM y ya esta en la variable local cuando criticar() revienta. Devolver
    texto="" tira trabajo YA PAGADO —cli.py corta con `if not res["ok"]:
    print(error); return`, asi que el usuario perdia los dos pasos y pagaba
    sus 30 tokens por nada.
    """
    def _agente_que_gasta(c, prompt, **kw):
        c.presupuesto.registrar({"prompt_tokens": 5, "completion_tokens": 10})
        return f"RESULTADO REAL del paso: {prompt}"

    def _critica_rota(c, texto, **k):
        raise RuntimeError("el critico exploto")

    monkeypatch.setattr("cognia.agent.workflows.agente", _agente_que_gasta)
    monkeypatch.setattr("cognia.agent.workflows.criticar", _critica_rota)
    r = wf.ejecutar("paso uno; paso dos", modo="secuencial",
                    criticar_salida=True, nombre="e_texto_pagado")

    assert set(r) == CLAVES_ENVELOPE
    assert r["ok"] is False and "el critico exploto" in r["error"]
    assert r["pasos"] == 2 and r["tokens"] == 30, (
        f"la corrida se pago: {r['pasos']} pasos, {r['tokens']} tokens")
    assert "RESULTADO REAL del paso: paso uno" in r["texto"], (
        f"se tiro el texto pagado: {r['texto']!r}")
    assert "RESULTADO REAL del paso: paso dos" in r["texto"]
    assert "2 pasos completados" in r["texto"]


# --- identidad de los pasos y cierre declarado -------------------------------

def test_el_adaptador_numera_los_pasos(monkeypatch):
    """La identidad la pone quien CONSTRUYE los thunks: paralelo() recibe
    callables opacos y no sabe que es cada uno."""
    vistos = []

    def _falso_agente(c, prompt, **kw):
        vistos.append(kw)
        return "ok"

    monkeypatch.setattr("cognia.agent.workflows.agente", _falso_agente)
    wf.ejecutar("uno; dos; tres", modo="secuencial", nombre="e_num")

    assert [v["indice"] for v in vistos] == [1, 2, 3]
    assert all(v["total"] == 3 and v["fase"] == "pasos" for v in vistos)
    assert [v["etiqueta"] for v in vistos] == ["uno", "dos", "tres"]


def test_la_etiqueta_de_un_paso_multilinea_es_de_UNA_linea(monkeypatch):
    """`prompt[:60]` era un slice crudo y se llevaba el salto de linea.

    La firma publica acepta LISTA, y por ahi nadie pasa por partir_pasos: un
    paso multilinea llegaba entero a la etiqueta. La segunda linea sale del
    panel sin marca ⏺/·/✗, `es_eco_renderer` (remoto/sesiones.py) no la caza y
    el chat del movil la anota como prosa del asistente.
    """
    from cognia.remoto.sesiones import es_eco_renderer
    vistas = []

    def _agente_espia(c, prompt, **kw):
        vistas.append(kw.get("etiqueta"))
        return "ok"

    monkeypatch.setattr("cognia.agent.workflows.agente", _agente_espia)
    wf.ejecutar(["resume esto:\nsegunda linea del paso"], modo="secuencial",
                nombre="e_etiqueta_multilinea")

    assert vistas, "el paso no llego a agente()"
    for e in vistas:
        assert "\n" not in e, f"etiqueta multilinea: {e!r}"
        # la que se colaba: una linea suelta que el remoto no reconoce como eco
        assert "segunda linea del paso" not in e, (
            f"la segunda linea viaja como titulo: {e!r}")
    assert vistas[0] == "resume esto:"
    assert not es_eco_renderer("segunda linea del paso"), (
        "premisa del defecto: sin marca, el remoto la toma por prosa")


def test_la_etiqueta_larga_se_recorta_con_puntos(monkeypatch):
    """_etiqueta() recorta a 60 y marca el corte; el slice crudo no lo marcaba."""
    vistas = []
    monkeypatch.setattr("cognia.agent.workflows.agente",
                        lambda c, p, **kw: vistas.append(kw.get("etiqueta")))
    largo = "z" * 200
    wf.ejecutar([largo], modo="secuencial", nombre="e_etiqueta_larga")
    assert vistas[0] == "z" * 60 + "…", repr(vistas[0])


def test_el_workflow_declara_su_total_de_agentes(monkeypatch, bus):
    monkeypatch.setattr("cognia.agent.workflows.agente",
                        lambda c, p, **kw: "ok")
    wf.ejecutar("uno; dos", modo="secuencial", nombre="e_total")
    ini = [e for e in bus if isinstance(e, ux.WorkflowInicio)][-1]
    assert ini.total_agentes == 2


def test_el_workflow_fin_declara_el_fallo(monkeypatch, bus):
    def _revienta(c, prompt, **kw):
        raise RuntimeError("el backend exploto")

    monkeypatch.setattr("cognia.agent.workflows.agente", _revienta)
    res = wf.ejecutar("uno", modo="secuencial", nombre="e_fin_fallo")
    fin = [e for e in bus if isinstance(e, ux.WorkflowFin)][-1]
    assert res["ok"] is False
    assert fin.ok is False and "el backend exploto" in fin.resumen


def test_el_workflow_fin_declara_el_exito(monkeypatch, bus):
    """El doble va en el BACKEND, no en `agente()`.

    Sustituir `agente` entero deja al motor sin ver un solo AgenteInicio, y con
    la contabilidad honesta del cierre (workflows.cerrar 2026-08-17) eso es
    "2 declarados, 0 arrancados" -> el cierre lo declara fallo, CON RAZON. Un
    doble que se come el evento que el test mide no mide nada: el camino real
    siempre emite AgenteInicio, asi que el doble tiene que ir por debajo, donde
    se paga el LLM. Verificado contra el camino real 2026-08-17.
    """
    monkeypatch.setattr("cognia.agent.chat_client.completar",
                        lambda mensajes, **kw: _RespBackend("ok"))
    wf.ejecutar("uno; dos", modo="secuencial", nombre="e_fin_ok")
    fin = [e for e in bus if isinstance(e, ux.WorkflowFin)][-1]
    assert fin.ok is True and fin.resumen == ""
    # el denominador tambien: "ok=True" con agentes=0 seria exito vacio
    assert (fin.agentes, fin.fallidos) == (2, 0)
    assert (fin.arrancados, fin.no_arrancados, fin.colgando) == (2, 0, 0)
