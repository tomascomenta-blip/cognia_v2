# -*- coding: utf-8 -*-
"""
tests/test_workflows_control.py — control POR AGENTE (2026-08-17)
=================================================================
Sin red y sin GPU: completar_fn siempre inyectado, COGNIA_WORKFLOWS_DIR a
tmp_path, y el bus se desuscribe SIEMPRE (un suscriptor colgado contamina los
tests que corran despues).

El truco que hace todo esto determinista y SIN hilos: emitir() es sincrono, asi
que un suscriptor que reciba AgenteInicio y llame cancelar_agente(ev.agente_id)
o decirle(ev.agente_id, …) corre ANTES del checkpoint A del agente.

Un invariante por test. Los dos que mas caro cuestan si se rompen:
  - un agente cancelado JAMAS queda cacheado como bueno (T3, T4);
  - a un agente al que se le hablo NO se le sirve la respuesta vieja en un
    resume (T5), ni el cache-hit lo salta antes de leer el mensaje (T6).
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from dataclasses import dataclass, field

import pytest

from cognia.agent import workflows as wf
from cognia.agent.workflows import (agente, cancelar_agente, cancelar_corrida,
                                    corridas_vivas, corrida, criticar, decirle,
                                    estado_agente, paralelo)
from cognia.ux import events as ux


# --------------------------------------------------------------- andamiaje

@dataclass
class _Resp:
    """Lo minimo que agente() mira de una RespuestaChat."""
    texto: str = ""
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 10,
                                                 "completion_tokens": 5})
    error: str = ""
    cortado: bool = False


class _Stub:
    """completar_fn de mentira: devuelve respuestas en orden."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def __call__(self, mensajes, **kw):
        self.llamadas.append({"mensajes": [dict(m) for m in mensajes],
                              "kw": dict(kw)})
        if not self.respuestas:
            raise AssertionError("stub sin respuestas: llamada de mas")
        return self.respuestas.pop(0)


class _StubFn:
    """completar_fn gobernado por una funcion (n_llamada, mensajes, kw).

    Hace falta porque el corte en vuelo es un EFECTO LATERAL a mitad de la
    llamada: la unica forma honesta de simularlo es que el propio stub llame a
    decirle()/cancelar_agente() y devuelva cortado=True, como haria
    chat_client al consultar cancelado()."""

    def __init__(self, fn):
        self.fn = fn
        self.llamadas = []

    def __call__(self, mensajes, **kw):
        self.llamadas.append({"mensajes": [dict(m) for m in mensajes],
                              "kw": dict(kw)})
        return self.fn(len(self.llamadas), mensajes, kw)


def _completar_estricto(mensajes, url=None, temperature=None, top_p=None,
                        max_tokens=None, razonador=None, via=None):
    """completar() de un caller VIEJO: firma explicita, sin **kw y sin
    'cancelado'. Es el caso que tiene que degradar A LA VISTA."""
    _completar_estricto.llamadas.append(mensajes)
    return _Resp(texto="listo")


_completar_estricto.llamadas = []


@pytest.fixture
def dir_wf(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path))
    return tmp_path


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
        yield
    finally:
        ux.desuscribir(fn)


def _corrida(nombre="prueba", **kw):
    return corrida(nombre, print_fn=lambda *a, **k: None, **kw)


def _de(bus, clase):
    return [e for e in bus if isinstance(e, clase)]


def _journal(c) -> list:
    crudo = (c.dir / "journal.jsonl").read_text(encoding="utf-8")
    return [json.loads(l) for l in crudo.splitlines() if l.strip()]


# --------------------------------------------------- T1: el default no cambia

def test_sin_interactivo_el_body_no_cambia(dir_wf, bus):
    c = _corrida()
    stub = _Stub([_Resp(texto="listo")])
    agente(c, "hola", completar_fn=stub)
    kw = stub.llamadas[0]["kw"]
    for prohibido in ("cancelado", "on_token", "on_reasoning"):
        assert prohibido not in kw, (
            f"{prohibido} viajo sin interactivo: chat_client entraria en la "
            f"rama SSE para TODA corrida batch")
    assert not _de(bus, ux.TokenTexto)


# ------------------------------------------------- T2/T3: cancelar antes de llamar

def test_cancelar_antes_de_llamar_no_llama_al_modelo(dir_wf, bus):
    c = _corrida()
    envs = []

    def _cancelar(ev):
        if isinstance(ev, ux.AgenteInicio):
            envs.append(cancelar_agente(ev.agente_id, "no era eso"))

    stub = _Stub([])                    # una llamada de mas revienta el stub
    with _suscrito(_cancelar):
        r = agente(c, "hola", completar_fn=stub)

    assert stub.llamadas == []
    assert "cancelado" in r["_error"] and "no era eso" in r["_error"]
    assert envs[0]["ok"] and envs[0]["estado"] == "aceptado"
    # Nace y muere: la contabilidad de cerrar() cuenta con eso.
    assert len(_de(bus, ux.AgenteInicio)) == 1
    fin = _de(bus, ux.AgenteFin)[0]
    assert fin.ok is False and fin.cancelado is True and fin.intentos == 0


def test_agente_cancelado_no_entra_en_cache(dir_wf, bus):
    c = _corrida()

    def _cancelar(ev):
        if isinstance(ev, ux.AgenteInicio):
            cancelar_agente(ev.agente_id)

    with _suscrito(_cancelar):
        agente(c, "hola", completar_fn=_Stub([]))

    assert c.cache == {}
    lineas = [d for d in _journal(c) if d.get("tipo") == "agente"]
    assert len(lineas) == 1
    assert lineas[0]["error"] and "resultado" not in lineas[0]


# ------------------------------------------------------ T4/T5: resume REAL

def test_resume_no_sirve_un_agente_cancelado(dir_wf, bus):
    ca = _corrida("a")

    def _cancelar_el_dos(ev):
        if isinstance(ev, ux.AgenteInicio) and ev.indice == 2:
            cancelar_agente(ev.agente_id)

    stub_a = _Stub([_Resp(texto="r1")])
    with _suscrito(_cancelar_el_dos):
        agente(ca, "p1", completar_fn=stub_a, indice=1, total=2, fase="pasos")
        agente(ca, "p2", completar_fn=stub_a, indice=2, total=2, fase="pasos")
    ca.cerrar()

    cb = _corrida("b", resume_de=ca.run_id)
    stub_b = _Stub([_Resp(texto="r2")])
    assert agente(cb, "p1", completar_fn=stub_b) == "r1"
    assert stub_b.llamadas == [], "el paso sano tiene que servirse de cache"
    assert agente(cb, "p2", completar_fn=stub_b) == "r2"
    assert len(stub_b.llamadas) == 1, (
        "el paso CANCELADO se sirvio de cache: un corte quedaria congelado "
        "como resultado bueno para siempre")


def test_resume_no_sirve_la_respuesta_vieja_a_un_agente_al_que_se_le_hablo(
        dir_wf, bus):
    ca = _corrida("a", interactivo=True)
    ident = {}

    def _cap(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident["id"] = ev.agente_id

    def _fn(i, mensajes, kw):
        if i == 1:
            decirle(ident["id"], "mejor en ingles")
            assert kw["cancelado"]() is True
            return _Resp(texto="a med", cortado=True, usage={})
        return _Resp(texto="R2")

    with _suscrito(_cap):
        assert agente(ca, "p", completar_fn=_StubFn(_fn)) == "R2"
    ca.cerrar()

    ok = [d for d in _journal(ca)
          if d.get("tipo") == "agente" and not d.get("error")]
    assert len(ok) == 1
    assert "resultado_dialogo" in ok[0] and ok[0]["dialogo_n"] == 1
    assert "resultado" not in ok[0], (
        "con la clave 'resultado' el loader del resume lo recogeria y "
        "serviria una respuesta que contesto a OTRA pregunta")

    cb = _corrida("b", resume_de=ca.run_id)
    stub_b = _Stub([_Resp(texto="fresco")])
    assert agente(cb, "p", completar_fn=stub_b) == "fresco"
    assert len(stub_b.llamadas) == 1
    avisos = [e for e in bus if isinstance(e, ux.Aviso)
              and "recibieron mensajes" in e.texto]
    assert avisos, "un resume que cuesta el doble tiene que explicar por que"


# ------------------------------------------------------------- T6: cache-hit

def test_mensaje_pendiente_invalida_el_cache_hit(dir_wf, bus):
    c = _corrida(interactivo=True)
    stub = _Stub([_Resp(texto="viejo"), _Resp(texto="nuevo")])
    assert agente(c, "p", completar_fn=stub) == "viejo"      # cachea

    def _hablar(ev):
        if isinstance(ev, ux.AgenteInicio) and ev.agente_id.endswith("@2"):
            assert decirle(ev.agente_id, "cambia")["ok"]

    with _suscrito(_hablar):
        r2 = agente(c, "p", completar_fn=stub)
    assert r2 == "nuevo" and len(stub.llamadas) == 2, (
        "el hit devolvio la respuesta vieja sin leer el mensaje")


# ---------------------------------------------- T7/T8/T9: cortar y repreguntar

def test_corte_en_vuelo_vuelve_a_preguntar(dir_wf, bus):
    c = _corrida(interactivo=True)
    ident = {}

    def _cap(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident["id"] = ev.agente_id

    def _fn(i, mensajes, kw):
        if i == 1:
            decirle(ident["id"], "en realidad quiero X")
            return _Resp(texto="a med", cortado=True, usage={})
        return _Resp(texto="final con X")

    stub = _StubFn(_fn)
    with _suscrito(_cap):
        r = agente(c, "haz Y", completar_fn=stub)

    assert len(stub.llamadas) == 2
    assert r == "final con X" and "a med" not in str(r)
    msgs = stub.llamadas[1]["mensajes"]
    assert msgs[-1] == {"role": "user", "content": "en realidad quiero X"}
    assert msgs[0] == {"role": "user", "content": "haz Y"}
    fin = _de(bus, ux.AgenteFin)[0]
    assert fin.repreguntas == 1 and fin.ok is True and fin.intentos == 2


def test_lo_generado_se_tira_pero_queda_en_el_journal(dir_wf, bus):
    c = _corrida(interactivo=True)
    ident = {}

    def _cap(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident["id"] = ev.agente_id

    def _fn(i, mensajes, kw):
        if i == 1:
            decirle(ident["id"], "para")
            return _Resp(texto="a med", cortado=True, usage={})
        return _Resp(texto="ok")

    with _suscrito(_cap):
        agente(c, "p", completar_fn=_StubFn(_fn))

    cortes = [d for d in _journal(c) if d.get("tipo") == "corte"]
    assert len(cortes) == 1
    assert cortes[0]["causa"] == "mensaje"
    assert cortes[0]["descartado"] == "a med"
    assert cortes[0]["descartado_chars"] == 5
    assert _de(bus, ux.AgenteFin)[0].descartado_chars == 5


def test_el_intento_cortado_cuesta_presupuesto(dir_wf, bus):
    # (a) con usage: se suma, porque esos tokens YA se pagaron.
    c = _corrida(interactivo=True, presupuesto_tokens=10_000)
    ident = {}

    def _cap(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident["id"] = ev.agente_id

    def _con_usage(i, mensajes, kw):
        if i == 1:
            decirle(ident["id"], "para")
            return _Resp(texto="xx", cortado=True,
                         usage={"prompt_tokens": 100, "completion_tokens": 7})
        return _Resp(texto="ok")

    with _suscrito(_cap):
        agente(c, "p", completar_fn=_StubFn(_con_usage))
    assert c.presupuesto.gastado() == 100 + 7 + 10 + 5

    # (b) sin usage: se registra 0 y la linea lo DECLARA. Prohibido estimar:
    # None es "no se pudo saber", que no es "0 tokens".
    c2 = _corrida("b", interactivo=True, presupuesto_tokens=10_000)
    ident2 = {}

    def _cap2(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident2["id"] = ev.agente_id

    def _sin_usage(i, mensajes, kw):
        if i == 1:
            decirle(ident2["id"], "para")
            return _Resp(texto="xx", cortado=True, usage={})
        return _Resp(texto="ok")

    with _suscrito(_cap2):
        agente(c2, "p", completar_fn=_StubFn(_sin_usage))
    assert c2.presupuesto.gastado() == 15          # solo la 2a llamada
    corte = [d for d in _journal(c2) if d.get("tipo") == "corte"][0]
    assert corte["usage_desconocido"] is True


# ----------------------------------------------------------- T10: tope

def test_tope_de_repreguntas(dir_wf, bus):
    c = _corrida(interactivo=True)
    ident = {}

    def _cap(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident["id"] = ev.agente_id

    def _siempre_corta(i, mensajes, kw):
        decirle(ident["id"], f"otra mas {i}")
        return _Resp(texto="zz", cortado=True, usage={})

    stub = _StubFn(_siempre_corta)
    with _suscrito(_cap):
        r = agente(c, "p", completar_fn=stub)

    assert "8 repreguntas seguidas" in r["_error"]
    assert len(stub.llamadas) == 9, "el lazo no se corto donde dice el contrato"
    assert _de(bus, ux.AgenteFin)[0].repreguntas == 8
    no_atendidos = [d for d in _journal(c)
                    if d.get("tipo") == "mensaje_no_atendido"]
    assert no_atendidos and no_atendidos[0]["motivo"] == "tope de repreguntas"


# --------------------------------------------- T11/T12/T13: el envelope habla

def test_decirle_a_uno_comprometido_devuelve_ya_termino(dir_wf, bus):
    c = _corrida(interactivo=True)
    envs = []

    def _hablar_al_muerto(ev):
        if isinstance(ev, ux.AgenteFin):
            envs.append(decirle(ev.agente_id, "una cosa mas"))

    with _suscrito(_hablar_al_muerto):
        agente(c, "p", completar_fn=_Stub([_Resp(texto="ya esta")]))

    assert envs[0]["ok"] is False and envs[0]["estado"] == "ya_termino"
    assert envs[0]["pendientes"] == 0


def test_ids_inexistentes_no_son_silencio(dir_wf, bus):
    c = _corrida()
    fantasma = f"{c.run_id}#suelto.99@99"
    assert decirle(fantasma, "hola")["estado"] == "desconocido_agente"
    assert decirle(f"{c.run_id}#suelto.1@1", "  ")["estado"] == "texto_vacio"
    assert (cancelar_agente("20990101-000000-nadie#x.1@1")["estado"]
            == "desconocido_corrida")
    c.cerrar()
    env = cancelar_agente(f"{c.run_id}#suelto.1@1")
    assert env["estado"] == "corrida_cerrada" and c.run_id in env["detalle"]
    # las OCHO claves del envelope, siempre las mismas. Los tres contadores
    # van separados desde el defecto #4 (2026-08-17): 'pendientes' significaba
    # mensajes en cola, agentes vivos y corridas alcanzadas segun quien
    # contestara, asi que una UI que pintara "N mensajes" mostraba corridas.
    for env in (decirle(fantasma, "x"), cancelar_corrida("nada"),
                cancelar_agente(fantasma)):
        assert set(env) == {"ok", "estado", "agente_id", "run_id",
                            "pendientes", "agentes", "corridas", "detalle"}


def test_cancelar_es_idempotente(dir_wf, bus):
    c = _corrida()
    envs = []

    def _dos_veces(ev):
        if isinstance(ev, ux.AgenteInicio):
            envs.append(cancelar_agente(ev.agente_id))
            envs.append(cancelar_agente(ev.agente_id))

    with _suscrito(_dos_veces):
        agente(c, "p", completar_fn=_Stub([]))

    assert envs[0]["estado"] == "aceptado" and envs[0]["ok"] is True
    assert envs[1]["estado"] == "ya_cancelado" and envs[1]["ok"] is True


def test_buzon_lleno_no_traga_el_noveno_mensaje(dir_wf, bus):
    c = _corrida(interactivo=True)
    envs = []

    def _spamear(ev):
        if isinstance(ev, ux.AgenteInicio):
            for i in range(10):
                envs.append(decirle(ev.agente_id, f"mensaje {i}"))

    with _suscrito(_spamear):
        agente(c, "p", completar_fn=_Stub([_Resp(texto="ok")]))

    assert [e["estado"] for e in envs[:8]] == ["aceptado"] * 8
    assert envs[7]["pendientes"] == 8
    assert envs[8]["ok"] is False and envs[8]["estado"] == "buzon_lleno"
    assert "no los esta leyendo" in envs[8]["detalle"]


def test_cancelar_corrida_sin_id_es_el_boton_de_panico(dir_wf, bus):
    c1, c2 = _corrida("una"), _corrida("otra")
    env = cancelar_corrida()
    assert env["ok"] and env["estado"] == "aceptado"
    # 'corridas' y no 'pendientes' (defecto #4): el panico alcanza CORRIDAS,
    # y 'pendientes' quedo reservado a los mensajes en cola de UN agente.
    assert env["corridas"] >= 2 and env["pendientes"] == 0
    assert c1.run_id in env["detalle"] and c2.run_id in env["detalle"]
    # y las dos corridas cortan de verdad
    for c in (c1, c2):
        r = agente(c, "p", completar_fn=_Stub([]))
        assert "cancelado por el usuario" in r["_error"]
    c1.cerrar()
    c2.cerrar()
    # cerrar() da de baja del directorio: el panico ya no las alcanza. Se mira
    # esto y no "no hay ninguna corrida viva" en todo el proceso, que dependeria
    # de que ningun test anterior haya dejado una Corrida sin recolectar.
    restantes = [d["run_id"] for d in corridas_vivas()]
    assert c1.run_id not in restantes and c2.run_id not in restantes


# ------------------------------------------------------------ T14: huerfano

def test_cancelar_corrida_alcanza_al_huerfano_de_paralelo(dir_wf, bus):
    c = _corrida(interactivo=True)
    puerta = threading.Event()

    def _lento(i, mensajes, kw):
        puerta.wait(10)
        return _Resp(texto="llegue tarde")

    def _thunk():
        return agente(c, "lento", completar_fn=_StubFn(_lento))

    assert paralelo([_thunk], cap=1, timeout_s=0.3) == [None]
    env = cancelar_corrida(c.run_id, "el usuario abandono")
    assert env["ok"] and env["estado"] == "aceptado"
    c.cerrar()
    puerta.set()

    fin = None
    for _ in range(200):
        candidatos = _de(bus, ux.AgenteFin)
        if candidatos:
            fin = candidatos[0]
            break
        time.sleep(0.02)
    assert fin is not None, "el huerfano nunca cerro"
    assert fin.cancelado is True and fin.tardio is True and fin.ok is False


# -------------------------------------------------------- T15/T16: invariantes

def test_el_agente_id_es_ruteable_por_prefijo(dir_wf, bus):
    c = _corrida("con guiones y ACENTOS")
    assert "#" not in c.run_id

    def _veredicto(i, mensajes, kw):
        return _Resp(texto='{"refutado": false, "motivo": "ok"}')

    agente(c, "suelto", completar_fn=_StubFn(_veredicto))
    criticar(c, "entrega", completar_fn=_StubFn(_veredicto))
    criticar(c, "entrega", completar_fn=_StubFn(_veredicto))   # 2a ronda

    ids = [e.agente_id for e in _de(bus, ux.AgenteInicio)]
    assert len(ids) == 7 and len(set(ids)) == 7
    for aid in ids:
        assert aid.split("#", 1)[0] == c.run_id
        assert wf._run_de(aid) == c.run_id


def test_clave_cache_congelada(dir_wf):
    # Si este hash cambia, alguien metio algo nuevo en la clave y acaba de
    # invalidar TODOS los resumes existentes. El dialogo NO va aca.
    assert (wf._clave_cache("p", "s", None, "", 1024)
            == "880f8013bc808dab5d8e5a06793c7bfe9fbea73b4943d10dadaf2f8ab4d0ab3a")


# -------------------------------------------------- T17: degradacion visible

def test_completar_sin_cancelado_degrada_y_avisa(dir_wf, bus):
    _completar_estricto.llamadas = []
    c = _corrida(interactivo=True)
    r1 = agente(c, "p1", completar_fn=_completar_estricto)
    r2 = agente(c, "p2", completar_fn=_completar_estricto)

    assert r1 == "listo" and r2 == "listo"
    degradados = [e for e in _de(bus, ux.Degradado)
                  if e.donde == "workflows._llamar"]
    assert len(degradados) == 1, "el aviso sale UNA vez por corrida"
    assert "cancelado" in degradados[0].motivo
    assert len(_completar_estricto.llamadas) == 2
    assert all(f.ok for f in _de(bus, ux.AgenteFin))


# ------------------------------------------------- T18/T19: tokens y latido

def test_tokentexto_sellado_y_opt_in(dir_wf, bus):
    c = _corrida(interactivo=True)
    ident = {}

    def _cap(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident["id"] = ev.agente_id

    def _fn(i, mensajes, kw):
        for trozo in ("ho", "la", "!"):
            kw["on_token"](trozo)
        kw["on_reasoning"]("pienso")
        return _Resp(texto="hola!")

    with _suscrito(_cap):
        agente(c, "p", completar_fn=_StubFn(_fn))

    toks = _de(bus, ux.TokenTexto)
    assert [t.texto for t in toks] == ["ho", "la", "!"]
    assert all(t.agente_id == ident["id"] for t in toks)

    # y con interactivo=False, ni uno
    bus.clear()
    c2 = _corrida("b")
    agente(c2, "p", completar_fn=_Stub([_Resp(texto="x")]))
    assert _de(bus, ux.TokenTexto) == []


def test_agenteprogreso_throttleado(dir_wf, bus, monkeypatch):
    # Reloj CONGELADO: solo puede disparar el umbral de chars (400).
    monkeypatch.setattr(wf, "_reloj", lambda: 1000.0)
    c = _corrida(interactivo=True)

    def _fn(i, mensajes, kw):
        for _ in range(2000):
            kw["on_token"]("x")
        return _Resp(texto="x" * 2000)

    agente(c, "p", completar_fn=_StubFn(_fn))

    prog = _de(bus, ux.AgenteProgreso)
    assert len(_de(bus, ux.TokenTexto)) == 2000, "el CONTENIDO no se throttlea"
    assert 1 <= len(prog) <= 6, f"{len(prog)} latidos: el throttle no aplico"
    assert prog[-1].chars == 2000


# --------------------------------------------- T20/T21/T22: el resto del bus

def test_mensajealagente_se_emite_tambien_al_rechazar(dir_wf, bus):
    c = _corrida()
    fantasma = f"{c.run_id}#suelto.42@42"
    decirle(fantasma, "hola?")
    evs = _de(bus, ux.MensajeAlAgente)
    assert len(evs) == 1
    assert evs[0].aceptado is False
    assert evs[0].estado == "desconocido_agente"
    assert evs[0].destino == fantasma and evs[0].texto == "hola?"


def test_workflowfin_declara_los_cancelados(dir_wf, bus):
    c = _corrida(total_agentes=3)

    def _cancelar_dos(ev):
        if isinstance(ev, ux.AgenteInicio) and ev.indice in (2, 3):
            cancelar_agente(ev.agente_id)

    stub = _Stub([_Resp(texto="r1")])
    with _suscrito(_cancelar_dos):
        for i in (1, 2, 3):
            agente(c, f"p{i}", completar_fn=stub, indice=i, total=3,
                   fase="pasos")
    c.cerrar()

    fin = _de(bus, ux.WorkflowFin)[0]
    assert fin.cancelados == 2 and fin.ok is False
    assert "cancelados por el usuario" in fin.resumen


def test_un_suscriptor_roto_no_impide_cancelar(dir_wf, bus):
    c = _corrida()
    envs = []

    def _roto(ev):
        if isinstance(ev, ux.MensajeAlAgente):
            raise RuntimeError("consumidor de pacotilla")

    def _actuar(ev):
        if isinstance(ev, ux.AgenteInicio):
            decirle(ev.agente_id, "algo")       # dispara el suscriptor roto
            envs.append(cancelar_agente(ev.agente_id))

    with _suscrito(_roto), _suscrito(_actuar):
        agente(c, "p", completar_fn=_Stub([]))

    assert envs and envs[0]["ok"] and envs[0]["estado"] == "aceptado"


# ------------------------------- el retry de schema no se apila ni se pierde

def test_el_repair_no_se_apila_con_dos_reintentos(dir_wf, bus):
    # El lazo de re-preguntas rearma `mensajes` cada vuelta; si el prompt de
    # reparacion se construyera sobre el mensaje YA reparado, con reintentos>=2
    # el segundo intento llevaria "SALIDA INVALIDA" dos veces y el modelo veria
    # el error de una respuesta que ya no existe.
    c = _corrida()
    esquema = {"type": "object", "required": ["x"],
               "properties": {"x": {"type": "integer"}}}
    stub = _Stub([_Resp(texto="no soy json"), _Resp(texto='{"x": "no"}'),
                  _Resp(texto='{"x": 7}')])
    assert agente(c, "dame x", esquema, reintentos=2, completar_fn=stub) == {"x": 7}
    ultimo = stub.llamadas[2]["mensajes"][-1]["content"]
    assert ultimo.count("SALIDA INVALIDA") == 1
    assert ultimo.startswith("dame x")


def test_la_repregunta_reinicia_el_retry_de_schema(dir_wf, bus):
    c = _corrida(interactivo=True)
    esquema = {"type": "object", "required": ["x"],
               "properties": {"x": {"type": "integer"}}}
    ident = {}

    def _cap(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident["id"] = ev.agente_id

    def _fn(i, mensajes, kw):
        if i == 1:
            return _Resp(texto="basura")            # gasta el unico reintento
        if i == 2:
            decirle(ident["id"], "mejor dame y")
            return _Resp(texto="a", cortado=True, usage={})
        if i == 3:
            return _Resp(texto="mas basura")        # el retry volvio a nacer
        return _Resp(texto='{"x": 1}')

    stub = _StubFn(_fn)
    with _suscrito(_cap):
        r = agente(c, "dame x", esquema, reintentos=1, completar_fn=stub)
    assert r == {"x": 1} and len(stub.llamadas) == 4


def test_plantilla_sin_turnos_consecutivos_degrada_y_fusiona(dir_wf, bus):
    # Cognia ya no es mono-familia: hay plantillas que revientan con dos turnos
    # de usuario seguidos. Se reintenta UNA vez con los turnos FUSIONADOS.
    c = _corrida(interactivo=True)
    ident = {}

    def _cap(ev):
        if isinstance(ev, ux.AgenteInicio):
            ident["id"] = ev.agente_id

    def _fn(i, mensajes, kw):
        if i == 1:
            decirle(ident["id"], "y ademas Z")
            return _Resp(texto="", cortado=True, usage={})
        if i == 2:
            assert len([m for m in mensajes if m["role"] == "user"]) == 2
            return _Resp(error="HTTP 400: consecutive user turns")
        return _Resp(texto="ok fusionado")

    stub = _StubFn(_fn)
    with _suscrito(_cap):
        assert agente(c, "haz Y", completar_fn=stub) == "ok fusionado"

    fusionado = stub.llamadas[2]["mensajes"]
    assert len(fusionado) == 1
    assert fusionado[0]["content"] == "haz Y\n\ny ademas Z"
    degr = [d for d in _journal(c)
            if d.get("tipo") == "degradado" and d["donde"] == "plantilla"]
    assert len(degr) == 1


# ------------------------------------------------------ consulta sin efectos

def test_estado_agente_y_corridas_vivas(dir_wf, bus):
    c = _corrida("viva", interactivo=True)
    estados = {}

    def _mirar(ev):
        if isinstance(ev, ux.AgenteInicio):
            estados["en_curso"] = estado_agente(ev.agente_id)
            estados["id"] = ev.agente_id
            vivas = [d for d in corridas_vivas() if d["run_id"] == c.run_id]
            estados["vivas"] = vivas

    with _suscrito(_mirar):
        agente(c, "p", completar_fn=_Stub([_Resp(texto="x")]))

    assert estados["en_curso"] == "vivo"
    assert estados["vivas"][0]["interactivo"] is True
    assert estados["vivas"][0]["agentes_vivos"] == 1
    # ya paso por el finally (checkpoint F): terminado, no comprometido
    assert estado_agente(estados["id"]) == "terminado"
    c.cerrar()
    assert estado_agente(estados["id"]) == "corrida_cerrada"
    assert [d for d in corridas_vivas() if d["run_id"] == c.run_id] == []
