# -*- coding: utf-8 -*-
"""
tests/test_workflows_engine.py — motor de workflows (WP2, contrato 2026-08-11)
==============================================================================
Sin red y sin GPU: completar_fn siempre inyectado como stub. Lo que se fija
aca es el CONTRATO del motor, no el modelo:

- el presupuesto corta ANTES de llamar (el stub no debe ejecutarse);
- resume_de sirve claves identicas desde el journal viejo sin llamar;
- el retry lleva el error REAL del validador en el prompt del 2do intento;
- finish_reason 'length' NO se reintenta (mismo prompt = mismo truncado);
- _valida cubre required/type/enum;
- paralelo respeta el cap y convierte fallos en None;
- pipeline no tiene barrera entre items (documentacion ejecutable);
- el journal sobrevive un crash a mitad de linea (resume carga lo entero).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

import pytest

from cognia.agent.workflows import (
    PresupuestoTokens, _valida, agente, corrida, paralelo, pipeline,
)


@dataclass
class _Resp:
    """Lo minimo que agente() mira de una RespuestaChat (duck-typing a
    proposito: el motor no debe depender de mas campos que estos)."""
    texto: str = ""
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 10,
                                                 "completion_tokens": 5})
    error: str = ""


class _Stub:
    """completar_fn de mentira: devuelve respuestas en orden y guarda los
    mensajes/kwargs de cada llamada para inspeccion."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def __call__(self, mensajes, **kw):
        self.llamadas.append({"mensajes": mensajes, "kw": kw})
        if not self.respuestas:
            raise AssertionError("stub sin respuestas: llamada de mas")
        return self.respuestas.pop(0)


@pytest.fixture
def dir_wf(tmp_path, monkeypatch):
    """Corridas bajo tmp_path: nada toca ~/.cognia real."""
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path))
    return tmp_path


def _corrida(nombre="prueba", **kw):
    # print_fn silencioso: los avisos de degradacion son ruido en tests
    return corrida(nombre, print_fn=lambda *a, **k: None, **kw)


# ---------------------------------------------------------------- presupuesto

def test_presupuesto_corta_antes_de_llamar(dir_wf):
    c = _corrida(presupuesto_tokens=10)
    c.presupuesto.registrar({"prompt_tokens": 8, "completion_tokens": 4})
    stub = _Stub([_Resp(texto="no deberia salir")])
    salida = agente(c, "hola", completar_fn=stub)
    c.cerrar()
    assert isinstance(salida, dict) and "_error" in salida
    assert "agotado" in salida["_error"]
    assert "10" in salida["_error"] and "12" in salida["_error"]
    assert stub.llamadas == []          # SIN llamar: el corte es previo


def test_presupuesto_registra_usage_de_cada_respuesta(dir_wf):
    c = _corrida(presupuesto_tokens=1000)
    stub = _Stub([_Resp(usage={"prompt_tokens": 100, "completion_tokens": 40})])
    agente(c, "hola", completar_fn=stub)
    c.cerrar()
    assert c.presupuesto.gastado() == 140
    assert c.presupuesto.restante() == 860.0
    assert not c.presupuesto.agotado()


def test_presupuesto_sin_techo_nunca_agota():
    p = PresupuestoTokens(None)
    p.registrar({"prompt_tokens": 10 ** 9, "completion_tokens": 0})
    assert p.restante() == float("inf") and not p.agotado()


# --------------------------------------------------------------- cache/resume

def test_cache_hit_en_resume_no_llama_al_stub(dir_wf):
    c1 = _corrida()
    stub1 = _Stub([_Resp(texto="respuesta cara")])
    r1 = agente(c1, "pregunta cara", system="sos util", completar_fn=stub1)
    c1.cerrar()
    assert r1 == "respuesta cara" and len(stub1.llamadas) == 1

    c2 = _corrida(resume_de=c1.run_id)
    stub2 = _Stub([])                   # cualquier llamada revienta el test
    r2 = agente(c2, "pregunta cara", system="sos util", completar_fn=stub2)
    c2.cerrar()
    assert r2 == "respuesta cara"
    assert stub2.llamadas == []         # servido del journal viejo

    # el hit queda ANOTADO en el journal nuevo
    lineas = [json.loads(l) for l in
              (c2.dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    hits = [l for l in lineas if l.get("tipo") == "agente"]
    assert hits and hits[0]["cache_hit"] is True


def test_resume_no_reusa_clave_distinta(dir_wf):
    c1 = _corrida()
    agente(c1, "pregunta A", completar_fn=_Stub([_Resp(texto="a")]))
    c1.cerrar()
    c2 = _corrida(resume_de=c1.run_id)
    stub = _Stub([_Resp(texto="b")])
    # max_tokens distinto -> clave distinta -> se paga la llamada
    r = agente(c2, "pregunta A", max_tokens=999, completar_fn=stub)
    c2.cerrar()
    assert r == "b" and len(stub.llamadas) == 1


def test_temperatura_no_entra_a_la_clave(dir_wf):
    c1 = _corrida()
    agente(c1, "p", temperatura=0.2, completar_fn=_Stub([_Resp(texto="x")]))
    c1.cerrar()
    c2 = _corrida(resume_de=c1.run_id)
    r = agente(c2, "p", temperatura=0.9, completar_fn=_Stub([]))
    c2.cerrar()
    assert r == "x"                     # ajustar sampling no rompe el resume


def test_error_no_se_cachea(dir_wf):
    c1 = _corrida()
    agente(c1, "p", completar_fn=_Stub([_Resp(error="backend caido")]))
    c1.cerrar()
    c2 = _corrida(resume_de=c1.run_id)
    stub = _Stub([_Resp(texto="ahora si")])
    r = agente(c2, "p", completar_fn=stub)
    c2.cerrar()
    assert r == "ahora si" and len(stub.llamadas) == 1


# ------------------------------------------------------------ schema y retry

_SCHEMA = {"type": "object",
           "properties": {"x": {"type": "integer"}},
           "required": ["x"]}


def test_schema_valido_devuelve_dict(dir_wf):
    c = _corrida()
    stub = _Stub([_Resp(texto='{"x": 7}')])
    r = agente(c, "dame x", schema=_SCHEMA, completar_fn=stub)
    c.cerrar()
    assert r == {"x": 7}
    # el kwarg response_format viajo con la forma verificada en vivo
    rf = stub.llamadas[0]["kw"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == _SCHEMA
    assert rf["json_schema"]["strict"] is True


def test_retry_lleva_el_error_real_en_el_prompt(dir_wf):
    c = _corrida()
    stub = _Stub([_Resp(texto='{"y": 1}'),          # falta 'x' -> retry
                  _Resp(texto='{"x": 3}')])
    r = agente(c, "dame x", schema=_SCHEMA, completar_fn=stub)
    c.cerrar()
    assert r == {"x": 3} and len(stub.llamadas) == 2
    prompt2 = stub.llamadas[1]["mensajes"][-1]["content"]
    assert "falta la clave requerida 'x'" in prompt2   # el error REAL, no uno generico
    assert "dame x" in prompt2                         # el pedido original sigue


def test_segundo_fallo_devuelve_error_y_crudo(dir_wf):
    c = _corrida()
    stub = _Stub([_Resp(texto="no es json"), _Resp(texto="tampoco")])
    r = agente(c, "dame x", schema=_SCHEMA, completar_fn=stub)
    c.cerrar()
    assert "_error" in r and r["_crudo"] == "tampoco"
    assert len(stub.llamadas) == 2      # reintentos=1 -> 2 intentos y basta


def test_length_no_reintenta(dir_wf):
    c = _corrida()
    stub = _Stub([_Resp(texto='{"x":', finish_reason="length",
                        usage={"prompt_tokens": 10, "completion_tokens": 2048})])
    r = agente(c, "dame x", schema=_SCHEMA, max_tokens=2048, completar_fn=stub)
    c.cerrar()
    assert "_error" in r
    assert "length" in r["_error"] and "2048" in r["_error"]
    assert len(stub.llamadas) == 1      # mismo prompt = mismo truncado: no insistir


def test_resp_error_vuelve_como_dict(dir_wf):
    c = _corrida()
    r = agente(c, "hola", completar_fn=_Stub([_Resp(error="HTTP 500 de x")]))
    c.cerrar()
    assert r == {"_error": "HTTP 500 de x"}


# -------------------------------------------------------------------- _valida

def test_valida_required_faltante():
    errs = _valida({"y": 1}, _SCHEMA)
    assert len(errs) == 1 and "requerida 'x'" in errs[0]


def test_valida_type_malo():
    errs = _valida({"x": "siete"}, _SCHEMA)
    assert errs and "type" in errs[0] and "$.x" in errs[0]


def test_valida_bool_no_es_integer():
    # bool es subclase de int en Python: el schema NO debe dejarlo pasar
    assert _valida({"x": True}, _SCHEMA)


def test_valida_enum():
    schema = {"type": "string", "enum": ["a", "b"]}
    assert _valida("a", schema) == []
    errs = _valida("c", schema)
    assert errs and "enum" in errs[0]


def test_valida_items_y_anidado():
    schema = {"type": "object",
              "properties": {"l": {"type": "array",
                                   "items": {"type": "integer"}}},
              "required": ["l"]}
    assert _valida({"l": [1, 2]}, schema) == []
    errs = _valida({"l": [1, "dos"]}, schema)
    assert errs and "$.l[1]" in errs[0]


def test_valida_conforme_vacio():
    assert _valida({"x": 7}, _SCHEMA) == []


# ------------------------------------------------------------------- paralelo

def test_paralelo_respeta_cap_y_orden():
    vivos = {"n": 0, "max": 0}
    lock = threading.Lock()

    def _thunk(i):
        def _t():
            with lock:
                vivos["n"] += 1
                vivos["max"] = max(vivos["max"], vivos["n"])
            time.sleep(0.05)
            with lock:
                vivos["n"] -= 1
            return i
        return _t

    r = paralelo([_thunk(i) for i in range(5)], cap=2)
    assert r == [0, 1, 2, 3, 4]         # en orden de entrada, no de fin
    assert vivos["max"] <= 2            # el cap ES max_workers


def test_paralelo_error_da_none():
    def _bum():
        raise RuntimeError("bum")
    r = paralelo([lambda: "ok", _bum, lambda: 3], cap=2)
    assert r == ["ok", None, 3]


def test_paralelo_timeout_da_none():
    lento = lambda: time.sleep(2) or "tarde"
    r = paralelo([lambda: "rapido", lento], cap=2, timeout_s=0.2)
    assert r[0] == "rapido" and r[1] is None


# ------------------------------------------------------------------- pipeline

def test_pipeline_sin_barrera_entre_items():
    """El item rapido debe TERMINAR TODO antes de que el lento salga de la
    etapa 1: si hubiera barrera por etapa, el rapido esperaria al lento."""
    eventos = []
    lock = threading.Lock()

    def _etapa(nombre, dormir_item0):
        def _e(item):
            if item == 0:
                time.sleep(dormir_item0)
            with lock:
                eventos.append((nombre, item))
            return item
        return _e

    r = pipeline([0, 1], _etapa("e1", 0.3), _etapa("e2", 0.0), cap=2)
    assert r == [0, 1]
    assert eventos.index(("e2", 1)) < eventos.index(("e1", 0))


def test_pipeline_etapa_que_lanza_deja_none_y_no_sigue():
    tocados = []

    def _e1(x):
        if x == "malo":
            raise ValueError("no va")
        return x + "-1"

    def _e2(x):
        tocados.append(x)
        return x + "-2"

    r = pipeline(["bueno", "malo"], _e1, _e2, cap=2)
    assert r == ["bueno-1-2", None]
    assert tocados == ["bueno-1"]       # el item roto NO llego a la etapa 2


# -------------------------------------------------------------------- journal

def test_journal_legible_tras_crash_a_mitad_de_linea(dir_wf):
    c1 = _corrida()
    agente(c1, "p1", completar_fn=_Stub([_Resp(texto="r1")]))
    agente(c1, "p2", completar_fn=_Stub([_Resp(texto="r2")]))
    c1.cerrar()

    # Simular el crash: truncar el archivo a mitad de la ULTIMA linea
    ruta = c1.dir / "journal.jsonl"
    crudo = ruta.read_text(encoding="utf-8")
    lineas = crudo.splitlines(keepends=True)
    ruta.write_text("".join(lineas[:-1]) + lineas[-1][: len(lineas[-1]) // 2],
                    encoding="utf-8")

    # El resume carga lo entero (p1) y re-paga solo lo truncado (p2)
    c2 = _corrida(resume_de=c1.run_id)
    stub = _Stub([_Resp(texto="r2-bis")])
    assert agente(c2, "p1", completar_fn=_Stub([])) == "r1"
    assert agente(c2, "p2", completar_fn=stub) == "r2-bis"
    c2.cerrar()
    assert len(stub.llamadas) == 1


def test_journal_una_linea_json_por_llamada(dir_wf):
    c = _corrida()
    agente(c, "p1", completar_fn=_Stub([_Resp(texto="r1")]))
    c.cerrar()
    lineas = (c.dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    parseadas = [json.loads(l) for l in lineas]     # todas JSON valido
    tipos = [p["tipo"] for p in parseadas]
    assert tipos == ["corrida", "agente"]
    ag = parseadas[1]
    assert ag["cache_hit"] is False and ag["error"] is None
    assert ag["resultado"] == "r1" and ag["usage"]["completion_tokens"] == 5


# -------------------------------------------------- degradacion worker->cerebro

def test_rol_worker_degrada_al_cerebro_con_aviso(dir_wf, monkeypatch):
    import sys, types
    # summoner de mentira cuyo ensure explota: la corrida debe SEGUIR
    falso = types.ModuleType("cognia.summoner")
    def _ensure(rol, **kw):
        raise RuntimeError("sin VRAM")
    falso.ensure = _ensure
    monkeypatch.setitem(sys.modules, "cognia.summoner", falso)
    monkeypatch.setenv("COGNIA_LLM_URL", "http://127.0.0.1:8080")

    avisos = []
    c = corrida("wk", print_fn=avisos.append)
    stub = _Stub([_Resp(texto="desde el cerebro")])
    r = agente(c, "hola", rol="worker", completar_fn=stub)
    c.cerrar()
    assert r == "desde el cerebro"
    assert avisos and "worker no disponible" in avisos[0]
    kw = stub.llamadas[0]["kw"]
    assert kw["url"] == "http://127.0.0.1:8080"     # degrado al cerebro
    assert kw["temperature"] == 0.7 and kw["top_p"] == 0.8


def test_rol_worker_usa_url_y_sampling_del_worker(dir_wf, monkeypatch):
    import sys, types
    falso = types.ModuleType("cognia.summoner")
    falso.ensure = lambda rol, **kw: {"ok": True, "rol": rol,
                                      "url": "http://127.0.0.1:8082"}
    monkeypatch.setitem(sys.modules, "cognia.summoner", falso)

    c = _corrida("wk2")
    stub = _Stub([_Resp(texto="desde el worker")])
    r = agente(c, "hola", rol="worker", completar_fn=stub)
    c.cerrar()
    assert r == "desde el worker"
    kw = stub.llamadas[0]["kw"]
    assert kw["url"] == "http://127.0.0.1:8082"
    assert kw["temperature"] == 0.6 and kw["top_p"] == 0.95


def test_temperatura_explicita_pisa_el_sampling(dir_wf):
    c = _corrida()
    stub = _Stub([_Resp(texto="x")])
    agente(c, "hola", temperatura=0.1, completar_fn=stub)
    c.cerrar()
    kw = stub.llamadas[0]["kw"]
    assert kw["temperature"] == 0.1 and kw["top_p"] == 0.8


def test_completar_sin_kwarg_response_format_tolerado(dir_wf):
    """WP1 (kwarg response_format en completar) corre en paralelo: si no
    aterrizo, agente() debe reintentar la llamada SIN el kwarg en vez de
    morir por TypeError."""
    llamadas = []

    def _viejo(mensajes, url="", temperature=1.0, top_p=1.0,
               max_tokens=4096, razonador=True, via=""):
        # firma SIN response_format, como el chat_client pre-WP1
        llamadas.append(mensajes)
        return _Resp(texto='{"x": 1}')

    c = _corrida()
    r = agente(c, "dame x", schema=_SCHEMA, completar_fn=_viejo)
    c.cerrar()
    assert r == {"x": 1} and len(llamadas) == 1


# ----------------------------------------------- fixes 2026-08-11 (regresion)
# Cada test de este bloque falla SIN su fix por construccion (verificado
# aplicandolos sobre el codigo pre-fix durante la revision adversarial).

def test_paralelo_timeout_no_bloquea_hasta_el_thunk_colgado():
    # Fix 1: el 'with ThreadPoolExecutor' hacia shutdown(wait=True) en el
    # __exit__ y ESPERABA al thunk colgado: con timeout_s=1 y un thunk de 8 s
    # la pared real era ~8 s (timeout cosmetico). Ahora retorna en <2 s y el
    # hilo colgado queda huerfano vivo (documentado en el docstring).
    t0 = time.monotonic()
    r = paralelo([lambda: time.sleep(8) or "tarde"], cap=1, timeout_s=1)
    pared = time.monotonic() - t0
    assert r == [None]
    assert pared < 2, f"paralelo bloqueo {pared:.1f}s: espero al thunk colgado"


def test_journal_tolera_write_tardio_de_huerfano(dir_wf, capsys):
    # Fix 1 (huerfanos): un thunk huerfano de paralelo() puede escribir al
    # journal de una corrida YA CERRADA; debe tragarse con aviso, jamas
    # lanzar (el journal es constancia, no puede tumbar nada).
    c = _corrida()
    c.cerrar()
    c._journal({"tipo": "tardio"})          # _fh None: no-op, sin excepcion
    c2 = _corrida()
    c2._fh.close()                          # fh cerrado pero NO None (carrera
    c2._journal({"tipo": "tardio"})         # cerrar() a medio camino)
    c2._fh = None                           # que cerrar() posterior sea no-op
    assert "journal no escribible" in capsys.readouterr().err


def test_falla_conserva_usage_y_url_en_el_journal(dir_wf):
    # Fix 2: los caminos de FALLO journaleaban usage=None y la url del caller
    # (vacia casi siempre) en vez de la efectiva: una corrida llena de fallos
    # no dejaba rastro de lo GASTADO ni de contra que backend.
    c = _corrida(presupuesto_tokens=10000)
    stub = _Stub([
        _Resp(texto="no es json",
              usage={"prompt_tokens": 100, "completion_tokens": 30}),
        _Resp(texto="tampoco",
              usage={"prompt_tokens": 120, "completion_tokens": 35}),
    ])
    r = agente(c, "dame x", schema=_SCHEMA, url="http://127.0.0.1:9999",
               completar_fn=stub)
    c.cerrar()
    assert "_error" in r and len(stub.llamadas) == 2
    # el presupuesto registro AMBAS llamadas aunque el parseo fallara:
    # los tokens ya se pagaron
    assert c.presupuesto.gastado() == 285
    lineas = [json.loads(l) for l in
              (c.dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    ag = [l for l in lineas if l.get("tipo") == "agente"][-1]
    assert ag["error"] and "no conforme" in ag["error"]
    assert ag["usage"] == {"prompt_tokens": 120, "completion_tokens": 35}
    assert ag["url"] == "http://127.0.0.1:9999"


def test_typeerror_interno_de_completar_fn_se_propaga(dir_wf):
    # Fix 3: el except TypeError de _llamar no distinguia "fn no acepta
    # response_format" de "fn revento ADENTRO con TypeError": tragaba el bug
    # y pagaba una SEGUNDA llamada identica con la gramatica caida en
    # silencio. La decision ahora es por firma y la llamada es UNA.
    llamadas = []

    def _roto(mensajes, **kw):
        llamadas.append(kw)
        raise TypeError("bug interno de completar_fn")

    c = _corrida()
    with pytest.raises(TypeError, match="bug interno"):
        agente(c, "dame x", schema=_SCHEMA, completar_fn=_roto)
    c.cerrar()
    assert len(llamadas) == 1           # UNA llamada: sin reintento pagado


def test_schema_vacio_no_es_sin_schema(dir_wf):
    # Fix 4: schema={} es falsy y el truthiness lo trataba como texto libre;
    # {} es un JSON Schema valido (todo JSON conforme) y debe activar el
    # camino estructurado (response_format + json.loads).
    c = _corrida()
    stub = _Stub([_Resp(texto='{"a": 1}')])
    r = agente(c, "dame json", schema={}, completar_fn=stub)
    c.cerrar()
    assert r == {"a": 1}                # dict parseado, no el string crudo
    rf = stub.llamadas[0]["kw"]["response_format"]
    assert rf["json_schema"]["schema"] == {}


def test_valida_enum_bool_no_cruza_con_int():
    # Fix 5: True == 1 en Python (bool es subclase de int) y 'obj in enum'
    # dejaba pasar true contra [1, 2] — el server lo rechazaria. La igualdad
    # numerica matematica entre no-bools (1.0 vs 1) SI vale, como en JSON.
    assert _valida(True, {"enum": [1, 2]})              # bool no matchea int
    assert _valida(False, {"enum": [0]})                # ni False a 0
    assert _valida(1, {"enum": [True, False]})          # ni int a bool
    assert _valida(1, {"enum": [1, 2]}) == []
    assert _valida(1.0, {"enum": [1, 2]}) == []         # numerica matematica
    assert _valida(True, {"enum": [True, False]}) == []


def test_length_reporta_el_max_tokens_clampeado(dir_wf):
    # Fix 6: el error de 'length' decia el max_tokens PRE-clamp (el caller
    # pedia 64) mientras chat_client llamaba clampeado a MIN_TOKENS_RAZONADOR:
    # el caller "subia" el presupuesto a 512 y no cambiaba nada. El clamp
    # ahora vive al principio de agente(): clave de cache, llamada y error
    # hablan del mismo numero.
    from cognia.agent.model_profiles import MIN_TOKENS_RAZONADOR
    c = _corrida()
    stub = _Stub([_Resp(texto="", finish_reason="length",
                        usage={"prompt_tokens": 10,
                               "completion_tokens": MIN_TOKENS_RAZONADOR})])
    r = agente(c, "hola", max_tokens=64, completar_fn=stub)
    c.cerrar()
    assert "_error" in r
    assert f"max_tokens={MIN_TOKENS_RAZONADOR}" in r["_error"]
    assert "max_tokens=64" not in r["_error"]
    # y la llamada real viajo con el numero clampeado
    assert stub.llamadas[0]["kw"]["max_tokens"] == MIN_TOKENS_RAZONADOR


def test_corrida_concurrente_no_comparte_run_id(dir_wf):
    # Regresion del TOCTOU ya arreglado (mkdir exist_ok=False como reserva
    # atomica): dos corridas del mismo nombre lanzadas a la VEZ (Barrier ->
    # mismo segundo -> mismo run_id candidato) no deben compartir dir ni
    # journal; una de las dos gana el mkdir y la otra sufija -2.
    barrera = threading.Barrier(2)
    corridas, errores = [], []
    lock = threading.Lock()

    def _abrir():
        try:
            barrera.wait(timeout=5)
            c = _corrida("misma")
            with lock:
                corridas.append(c)
        except Exception as e:     # pragma: no cover - solo diagnostica
            with lock:
                errores.append(e)

    hilos = [threading.Thread(target=_abrir) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=10)
    for c in corridas:
        c.cerrar()
    assert errores == [] and len(corridas) == 2
    assert corridas[0].run_id != corridas[1].run_id
    assert corridas[0].dir != corridas[1].dir
