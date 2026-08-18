# -*- coding: utf-8 -*-
"""
tests/test_control_agente_defectos.py — los 6 defectos del control por agente
=============================================================================
Reproducidos por un verificador independiente sobre la entrega del 2026-08-17
(cancelar_agente / cancelar_corrida / decirle). Un test por defecto, cada uno
escrito para FALLAR contra el codigo de esa entrega:

  #1  el envelope de ejecutar() decia "ningun paso devolvio resultado" a un
      usuario que acababa de apretar cancelar, y con 1 de 3 pasos cortado
      devolvia ok=True mientras WorkflowFin decia ok=False. Dos consumidores
      del MISMO cierre, diagnosticos opuestos.
  #2  decirle() a un agente cancelado devolvia 'aceptado' y el mensaje se
      evaporaba sin una sola linea de journal.
  #3  cancelar_agente() sobre uno que YA ENTREGO devolvia ok=True/ya_cancelado
      despues de un panico global, porque esta_cancelado() (que ORea el flag
      global) se consultaba ANTES del estado del agente.
  #4  la clave 'pendientes' significaba tres cosas distintas segun quien
      contestara: mensajes en cola, agentes vivos y corridas alcanzadas.
  #5  cada corte se contabilizaba como CERO tokens (usage vacio al cortar):
      medido con /tokenize, ~88-90 tokens por corte y una sub-cuenta del 56%.
  #6  el movil recibia MensajeAlAgente y AgenteProgreso como JSON crudo.

Sin red y sin GPU salvo el server SSE de juguete de #5 (mismo patron que
tests/test_chat_client_stream.py: nada de mocks del transporte).
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from dataclasses import dataclass, field

import pytest

from cognia.agent import workflows as motor
from cognia.agent.workflows import (agente, cancelar_agente, cancelar_corrida,
                                    corrida, decirle, estado_agente)
from cognia.harness import workflows_adapter as adaptador
from cognia.remoto.sesiones import interpretar_evento
from cognia.ux import events as ux


# --------------------------------------------------------------- andamiaje

@dataclass
class _Resp:
    """Lo minimo que agente() mira de una RespuestaChat."""
    texto: str = ""
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 3,
                                                 "completion_tokens": 3})
    error: str = ""
    cortado: bool = False
    usage_estimado: bool = False


@pytest.fixture(autouse=True)
def _dir_wf(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path))


@pytest.fixture
def bus():
    vistos: list = []
    ux.suscribir(vistos.append)
    try:
        yield vistos
    finally:
        ux.desuscribir(vistos.append)


@contextlib.contextmanager
def _suscrito(fn):
    ux.suscribir(fn)
    try:
        yield fn
    finally:
        ux.desuscribir(fn)


def _corrida(nombre="defectos", **kw):
    return corrida(nombre, print_fn=lambda *a, **k: None, **kw)


def _journal(c) -> list:
    crudo = (c.dir / "journal.jsonl").read_text(encoding="utf-8")
    return [json.loads(l) for l in crudo.splitlines() if l.strip()]


def _fin(bus):
    return [e for e in bus if isinstance(e, ux.WorkflowFin)][-1]


# ── #1 — el envelope de PRODUCCION no puede contradecir a WorkflowFin ──────

def test_1a_tras_el_panico_el_envelope_dice_que_lo_cancelo_el_usuario(
        monkeypatch, bus):
    """cli.py hace `if not res["ok"]: print(error)`. Al usuario que acaba de
    apretar cancelar se le decia 'ningun paso devolvio resultado': el
    diagnostico OPUESTO al que corresponde."""
    monkeypatch.setattr("cognia.agent.chat_client.completar",
                        lambda mensajes, **kw: _Resp("no deberia llamarse"))

    def _panico(ev):
        if isinstance(ev, ux.AgenteInicio):
            cancelar_corrida(ev.run_id)

    with _suscrito(_panico):
        res = adaptador.ejecutar("uno; dos", modo="secuencial",
                                 nombre="e_panico", interactivo=True)

    fin = _fin(bus)
    assert fin.cancelados == 2 and fin.ok is False
    assert res["ok"] == fin.ok, (
        f"el envelope dice ok={res['ok']} y WorkflowFin ok={fin.ok}: "
        f"dos consumidores del mismo cierre, veredictos opuestos")
    assert "cancel" in res["error"].lower(), res["error"]
    assert "ningun paso devolvio resultado" not in res["error"]
    assert res["cancelados"] == 2


def test_1b_con_un_paso_cancelado_de_tres_los_dos_consumidores_coinciden(
        monkeypatch, bus):
    """La VARIANTE PEOR: ejecutar() devolvia ok=True error='' y WorkflowFin
    ok=False cancelados=1 sobre la MISMA corrida."""
    monkeypatch.setattr("cognia.agent.chat_client.completar",
                        lambda mensajes, **kw: _Resp("salio bien"))

    def _cortar_el_primero(ev):
        if isinstance(ev, ux.AgenteInicio) and ev.indice == 1:
            cancelar_agente(ev.agente_id, "me equivoque")

    with _suscrito(_cortar_el_primero):
        res = adaptador.ejecutar("uno; dos; tres", modo="secuencial",
                                 nombre="e_uno_de_tres", interactivo=True)

    fin = _fin(bus)
    assert (fin.cancelados, fin.ok) == (1, False)
    assert res["ok"] == fin.ok, (
        f"envelope ok={res['ok']} vs WorkflowFin ok={fin.ok}")
    assert res["cancelados"] == 1
    assert "cancel" in res["error"].lower(), res["error"]
    # Lo YA PAGADO sigue en el envelope: dos pasos si dieron resultado.
    assert res["texto"].count("salio bien") == 2


def test_1c_la_clave_nueva_esta_en_TODOS_los_caminos(monkeypatch):
    """El envelope de forma variable ya mordio una vez en este repo: la clave
    nueva va en los 4 caminos de error tambien, o no va."""
    import sys
    envs = {}
    envs["sin_pasos"] = adaptador.ejecutar("", nombre="d_vacio")
    monkeypatch.setattr(adaptador._dentro, "activo", True, raising=False)
    envs["anidado"] = adaptador.ejecutar("a; b", nombre="d_anid")
    monkeypatch.setattr(adaptador._dentro, "activo", False, raising=False)
    monkeypatch.setitem(sys.modules, "cognia.agent.workflows", None)
    envs["sin_motor"] = adaptador.ejecutar("a", nombre="d_imp")
    monkeypatch.setitem(sys.modules, "cognia.agent.workflows", motor)

    def _revienta(c, prompt, **kw):
        raise RuntimeError("el backend exploto")

    real = motor.agente
    monkeypatch.setattr("cognia.agent.workflows.agente", _revienta)
    envs["excepcion"] = adaptador.ejecutar("a", modo="secuencial",
                                           nombre="d_exc")
    # El exito con el motor REAL debajo (doble en el backend): con agente()
    # sustituido no hay AgenteInicio y el cierre declara la corrida fallida.
    monkeypatch.setattr("cognia.agent.workflows.agente", real)
    monkeypatch.setattr("cognia.agent.chat_client.completar",
                        lambda mensajes, **kw: _Resp("listo"))
    envs["exito"] = adaptador.ejecutar("a", modo="secuencial", nombre="d_ok")

    for camino, res in envs.items():
        assert set(res) == adaptador.CLAVES_ENVELOPE, f"{camino}: {sorted(res)}"
        assert isinstance(res["cancelados"], int), camino
    assert envs["exito"]["ok"] is True and envs["exito"]["cancelados"] == 0
    assert "el backend exploto" in envs["excepcion"]["error"]


# ── #2 — ningun mensaje se descarta en silencio ───────────────────────────

def test_2_decirle_a_un_cancelado_no_dice_aceptado_ni_se_evapora(bus):
    c = _corrida(interactivo=True)
    envs = []

    def _cancelar_y_hablar(ev):
        if isinstance(ev, ux.AgenteInicio):
            envs.append(cancelar_agente(ev.agente_id, "no era eso"))
            envs.append(decirle(ev.agente_id, "cambia el plan"))

    with _suscrito(_cancelar_y_hablar):
        agente(c, "hola", completar_fn=lambda *a, **k: _Resp("no llamar"))

    assert envs[0]["ok"] is True and envs[0]["estado"] == "aceptado"
    assert envs[1]["ok"] is False, (
        "decirle() a un agente cancelado devolvio 'aceptado' por un mensaje "
        "que nadie va a leer")
    assert envs[1]["estado"] == motor.YA_CANCELADO
    tipos = [d.get("tipo") for d in _journal(c)]
    assert "mensaje_no_atendido" in tipos, (
        f"el mensaje se evaporo sin rastro; journal={tipos}")
    msg = [e for e in bus if isinstance(e, ux.MensajeAlAgente)][-1]
    assert msg.aceptado is False and msg.estado == motor.YA_CANCELADO


def test_2b_un_mensaje_ya_encolado_que_pilla_la_cancelacion_deja_rastro():
    """El otro lado del mismo agujero: el mensaje entra ANTES de que el corte
    llegue, y el checkpoint B devuelve _cancelado() sin mirar el buzon."""
    c = _corrida(interactivo=True)

    def _hablar_y_cancelar(ev):
        if isinstance(ev, ux.AgenteInicio):
            decirle(ev.agente_id, "espera, mejor asi")
            cancelar_agente(ev.agente_id, "mejor no")

    with _suscrito(_hablar_y_cancelar):
        agente(c, "hola", completar_fn=lambda *a, **k: _Resp("no llamar"))

    no_atendidos = [d for d in _journal(c)
                    if d.get("tipo") == "mensaje_no_atendido"]
    assert no_atendidos, "el mensaje encolado se perdio sin una linea"
    assert no_atendidos[0].get("texto") == "espera, mejor asi"


# ── #3 — un agente que ya entrego no se "cancela" ni tras un panico ───────

def test_3_cancelar_a_uno_que_ya_entrego_no_miente_tras_el_panico(bus):
    c = _corrida(interactivo=True)
    ids = []

    def _anotar(ev):
        if isinstance(ev, ux.AgenteInicio):
            ids.append(ev.agente_id)

    with _suscrito(_anotar):
        r = agente(c, "hola", completar_fn=lambda *a, **k: _Resp("LISTO"))
    assert r == "LISTO"

    sin_panico = cancelar_agente(ids[0])
    assert (sin_panico["ok"], sin_panico["estado"]) == (False, motor.YA_TERMINO)

    cancelar_corrida(c.run_id, "boton de panico")
    tras_panico = cancelar_agente(ids[0])
    assert tras_panico["estado"] == motor.YA_TERMINO, (
        f"un agente TERMINADO con su resultado intacto salio como "
        f"{tras_panico['estado']}: cancelar_agente miente")
    assert tras_panico["ok"] is False
    assert estado_agente(ids[0]) == motor.EST_TERMINADO
    assert c.cache, "el resultado seguia cacheado: no se cancelo nada"


def test_3b_un_cancelado_que_ya_murio_sigue_diciendo_ya_cancelado():
    """El reverso: idempotencia. Reordenar los checks no puede convertir un
    agente CORTADO en un 'ya_termino' (que dice 'entrego su resultado')."""
    c = _corrida(interactivo=True)
    ids = []

    def _cancelar(ev):
        if isinstance(ev, ux.AgenteInicio):
            ids.append(ev.agente_id)
            cancelar_agente(ev.agente_id, "no era eso")

    with _suscrito(_cancelar):
        agente(c, "hola", completar_fn=lambda *a, **k: _Resp("no llamar"))

    env = cancelar_agente(ids[0])
    assert env["estado"] == motor.YA_CANCELADO and env["ok"] is True


# ── #4 — 'pendientes' significa UNA cosa ──────────────────────────────────

def test_4_pendientes_son_mensajes_y_nada_mas():
    c = _corrida(interactivo=True)
    vistos = {}

    def _medir(ev):
        if isinstance(ev, ux.AgenteInicio):
            vistos["decirle"] = decirle(ev.agente_id, "un mensaje")
            vistos["corrida"] = cancelar_corrida(ev.run_id)
            vistos["global"] = cancelar_corrida("")

    with _suscrito(_medir):
        agente(c, "hola", completar_fn=lambda *a, **k: _Resp("x"))

    assert vistos["decirle"]["pendientes"] == 1
    assert vistos["corrida"]["pendientes"] == 0, (
        "cancelar_corrida(rid) metia los agentes vivos en 'pendientes': una "
        "UI que pinte 'N mensajes pendientes' muestra agentes")
    assert vistos["corrida"]["agentes"] == 1
    assert vistos["global"]["pendientes"] == 0, (
        "el panico global metia las corridas alcanzadas en 'pendientes'")
    assert vistos["global"]["corridas"] == 1
    # forma FIJA: las mismas claves en los tres, y en el envelope sin motor
    claves = set(vistos["decirle"])
    for k, v in vistos.items():
        assert set(v) == claves, f"{k}: {sorted(v)}"
    assert set(adaptador._ENV_SIN_MOTOR) == claves


# ── #5 — el corte se COBRA ────────────────────────────────────────────────

def test_5_el_corte_deja_de_contabilizarse_como_cero(monkeypatch):
    """Un corte con 40 frames de contenido no puede costar 0 tokens.

    La estimacion se marca como tal (misma regla que timings.predicted_n) y
    el presupuesto sabe decir cuanto de lo gastado es estimado."""
    c = _corrida(interactivo=True, presupuesto_tokens=10_000)

    def _corta(mensajes, **kw):
        # lo que devuelve chat_client al cortar: sin usage del server, pero
        # con la estimacion por frames de contenido ya resuelta adentro.
        return _Resp(texto="a" * 120, finish_reason="cancelado", cortado=True,
                     usage={"completion_tokens": 40}, usage_estimado=True)

    llamadas = {"n": 0}

    def _stub(mensajes, **kw):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return _corta(mensajes, **kw)
        return _Resp("ya esta")

    def _hablar_una_vez(ev):
        if isinstance(ev, ux.AgenteInicio):
            decirle(ev.agente_id, "cambia el enfoque")

    with _suscrito(_hablar_una_vez):
        agente(c, "hola", completar_fn=_stub)

    assert c.presupuesto.gastado() >= 40, (
        f"el corte se conto como cero: gastado={c.presupuesto.gastado()}")
    assert c.presupuesto.estimados() == 40
    corte = [d for d in _journal(c) if d.get("tipo") == "corte"][0]
    assert corte["usage_desconocido"] is False
    assert corte["usage_estimado"] is True


# La otra mitad de #5 —que chat_client SEPA estimar el corte— vive en
# tests/test_chat_client_stream.py, donde esta el server SSE de verdad:
#   test_al_cortar_se_estiman_los_tokens_por_frames_de_contenido
#   test_un_corte_sin_un_solo_frame_sigue_siendo_desconocido


# ── #6 — una linea humana para el movil ───────────────────────────────────

def test_6_el_movil_no_recibe_json_crudo():
    msg = ux.a_dict(ux.MensajeAlAgente(
        run_id="r1", destino="r1#pasos.2@2", texto="cambia el enfoque",
        aceptado=True, estado="aceptado", pendientes=1))
    quien, texto, _ = interpretar_evento(msg)
    assert quien is not None
    assert not texto.startswith("MensajeAlAgente: {"), texto
    assert "{" not in texto, f"JSON crudo volcado al movil: {texto}"
    assert "cambia el enfoque" in texto

    prog = ux.a_dict(ux.AgenteProgreso(run_id="r1", chars=1200,
                                       chars_razonamiento=300, intento=1))
    quien, texto, _ = interpretar_evento(prog)
    assert quien is not None
    assert "{" not in texto, f"JSON crudo volcado al movil: {texto}"
    assert "AgenteProgreso:" not in texto


def test_6b_un_mensaje_RECHAZADO_se_ve_en_el_chat_no_plegado():
    """El invariante de events.py:250 tambien vale del lado del movil: un
    mensaje rechazado tiene que verse."""
    msg = ux.a_dict(ux.MensajeAlAgente(
        run_id="r1", destino="r1#pasos.2@2", texto="para",
        aceptado=False, estado="ya_cancelado", pendientes=0))
    quien, texto, _ = interpretar_evento(msg)
    assert quien == "sistema", quien
    assert "ya_cancelado" in texto or "cancelado" in texto
