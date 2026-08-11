# -*- coding: utf-8 -*-
"""Flujos estilo n8n (flows.py): validación DAG, ejecución con interpolación,
retries, condicionales, from_plan. run_tool fake (sin modelo)."""
import pytest

from cognia.agent.flows import (FlowError, ejecutar, from_json, from_plan,
                                to_json, validar)


def _fake_run(registro):
    """Devuelve un run_tool(name,args,ctx) que consulta un dict tool->fn."""
    def run(name, args, ctx):
        return registro[name](args)
    return run


def test_validar_orden_topologico():
    flujo = {"nodos": [
        {"id": "a", "tool": "t", "wires": ["b", "c"]},
        {"id": "b", "tool": "t", "wires": ["d"]},
        {"id": "c", "tool": "t", "wires": ["d"]},
        {"id": "d", "tool": "t", "wires": []}]}
    orden = validar(flujo)
    assert orden.index("a") < orden.index("b") < orden.index("d")
    assert orden.index("c") < orden.index("d")


def test_validar_detecta_ciclo():
    flujo = {"nodos": [
        {"id": "a", "tool": "t", "wires": ["b"]},
        {"id": "b", "tool": "t", "wires": ["a"]}]}
    with pytest.raises(FlowError, match="CICLO"):
        validar(flujo)


def test_validar_wire_colgado_y_dup():
    with pytest.raises(FlowError, match="inexistente"):
        validar({"nodos": [{"id": "a", "tool": "t", "wires": ["zzz"]}]})
    with pytest.raises(FlowError, match="duplicados"):
        validar({"nodos": [{"id": "a", "tool": "t"}, {"id": "a", "tool": "t"}]})


def test_validar_tool_inexistente():
    with pytest.raises(FlowError, match="no existe"):
        validar({"nodos": [{"id": "a", "tool": "fantasma"}]},
                tool_existe=lambda n: n in {"real"})


def test_ejecutar_encadena_e_interpola():
    flujo = {"nodos": [
        {"id": "a", "tool": "eco", "args": "hola", "wires": ["b"]},
        {"id": "b", "tool": "eco", "args": "vi: {{a}}", "wires": []}]}
    reg = {"eco": lambda a: f"RESULTADO eco: {a}"}
    r = ejecutar(flujo, {}, _fake_run(reg))
    assert r["salidas"]["a"] == "RESULTADO eco: hola"
    assert "vi: RESULTADO eco: hola" in r["salidas"]["b"]
    assert r["errores"] == {}


def test_ejecutar_reintenta_hasta_ok():
    intentos = {"n": 0}

    def flaky(args):
        intentos["n"] += 1
        return "RESULTADO x: ok" if intentos["n"] >= 2 else "RESULTADO x ERROR: fallo"

    flujo = {"nodos": [{"id": "a", "tool": "f", "args": "", "reintentos": 2,
                        "wires": []}]}
    r = ejecutar(flujo, {}, _fake_run({"f": flaky}))
    assert intentos["n"] == 2
    assert r["errores"] == {}


def test_ejecutar_error_no_frena_flujo():
    flujo = {"nodos": [
        {"id": "a", "tool": "malo", "args": "", "wires": ["b"]},
        {"id": "b", "tool": "bueno", "args": "sigo", "wires": []}]}
    reg = {"malo": lambda a: "RESULTADO malo ERROR: boom",
           "bueno": lambda a: "RESULTADO bueno: ok"}
    r = ejecutar(flujo, {}, _fake_run(reg))
    assert "a" in r["errores"]
    assert r["salidas"]["b"] == "RESULTADO bueno: ok"   # b igual corrió


def test_ejecutar_saltar_si():
    flujo = {"nodos": [
        {"id": "a", "tool": "eco", "args": "todo bien", "wires": ["b"]},
        {"id": "b", "tool": "eco", "args": "x", "saltar_si": "bien", "wires": []}]}
    reg = {"eco": lambda a: f"RESULTADO eco: {a}"}
    r = ejecutar(flujo, {}, _fake_run(reg))
    assert "b" in r["saltados"]


def test_from_plan_lineal():
    pasos = [{"description": "leer x", "tool_required": "leer_archivo"},
             {"description": "resumir", "tool_required": "resumir"}]
    flujo = from_plan("mi flujo", pasos)
    assert flujo["nombre"] == "mi flujo"
    orden = validar(flujo)
    assert orden == ["n0", "n1"]
    assert flujo["nodos"][0]["tool"] == "leer_archivo"
    assert flujo["nodos"][0]["wires"] == ["n1"]


def test_roundtrip_json():
    flujo = {"nombre": "f", "nodos": [{"id": "a", "tool": "t", "args": "x",
                                       "wires": []}]}
    assert from_json(to_json(flujo)) == flujo
    with pytest.raises(FlowError):
        from_json('{"foo": 1}')


# ── paralelo opt-in por niveles (WP3 2026-08-11) ────────────────────────────

def test_paralelo_rombo_termina_y_respeta_dependencias():
    """Rombo a→(b,c)→d con paralelo=True: las 4 salidas llegan, b y c corren
    DE VERDAD a la vez (la barrera de 2 solo pasa si ambos hilos están
    dentro; en secuencial rompería por timeout) y d ve a sus dos padres."""
    import threading
    barrera = threading.Barrier(2, timeout=5)

    def par(a):
        barrera.wait()
        return f"RESULTADO par: {a}"

    reg = {"eco": lambda a: f"RESULTADO eco: {a}", "par": par}
    flujo = {"nodos": [
        {"id": "a", "tool": "eco", "args": "ini", "wires": ["b", "c"]},
        {"id": "b", "tool": "par", "args": "B", "wires": ["d"]},
        {"id": "c", "tool": "par", "args": "C", "wires": ["d"]},
        {"id": "d", "tool": "eco", "args": "{{b}}+{{c}}", "wires": []}]}
    r = ejecutar(flujo, {}, _fake_run(reg), paralelo=True, cap=2)
    assert len(r["salidas"]) == 4
    assert r["errores"] == {}
    # d corrió después de b y c: sus salidas ya estaban para interpolar
    assert r["salidas"]["d"] == "RESULTADO eco: RESULTADO par: B+RESULTADO par: C"


def test_paralelo_cap1_equivale_al_secuencial():
    reg = {"eco": lambda a: f"RESULTADO eco: {a}"}
    flujo = {"nodos": [
        {"id": "a", "tool": "eco", "args": "ini", "wires": ["b", "c"]},
        {"id": "b", "tool": "eco", "args": "b:{{a}}", "wires": ["d"]},
        {"id": "c", "tool": "eco", "args": "c:{{a}}", "wires": ["d"]},
        {"id": "d", "tool": "eco", "args": "{{b}}|{{c}}", "wires": []}]}
    seq = ejecutar(flujo, {}, _fake_run(reg))
    par = ejecutar(flujo, {}, _fake_run(reg), paralelo=True, cap=1)
    assert par["salidas"] == seq["salidas"]
    assert par["orden"] == seq["orden"]
    assert par["errores"] == seq["errores"] == {}


def test_desvio_semantico_saltar_si_entre_hermanos():
    """DOCUMENTACIÓN EJECUTABLE del desvío de paralelo=True (ver docstring de
    ejecutar): en secuencial un hermano posterior VE la salida del anterior
    (Kahn los serializa) y su saltar_si puede dispararse por ella; en
    paralelo los hermanos del mismo nivel NO se ven — solo los niveles
    previos completos. Si este test rompe, cambió el contrato documentado."""
    flujo = {"nodos": [
        {"id": "a", "tool": "eco", "args": "arranque", "wires": ["b", "c"]},
        {"id": "b", "tool": "eco", "args": "bandera", "wires": []},
        {"id": "c", "tool": "eco", "args": "x", "saltar_si": "bandera",
         "wires": []}]}
    reg = {"eco": lambda a: f"RESULTADO eco: {a}"}
    seq = ejecutar(flujo, {}, _fake_run(reg))
    assert "c" in seq["saltados"]           # secuencial: c vio a su hermano b
    par = ejecutar(flujo, {}, _fake_run(reg), paralelo=True, cap=2)
    assert "c" not in par["saltados"]       # paralelo: c NO ve a b
    assert par["salidas"]["c"] == "RESULTADO eco: x"


# ── cache/resume por clave de nodo ──────────────────────────────────────────

def test_cache_reusa_nodo_ok_y_no_reusa_error():
    llamadas = {"ok": 0, "mal": 0}

    def okt(a):
        llamadas["ok"] += 1
        return f"RESULTADO okt: {a}"

    def malt(a):
        llamadas["mal"] += 1
        return "RESULTADO malt ERROR: boom"

    flujo = {"nodos": [
        {"id": "a", "tool": "okt", "args": "x", "wires": []},
        {"id": "b", "tool": "malt", "args": "y", "wires": []}]}
    reg = {"okt": okt, "malt": malt}
    cache = {}
    r1 = ejecutar(flujo, {}, _fake_run(reg), cache=cache)
    assert r1["cacheados"] == []
    assert llamadas == {"ok": 1, "mal": 1}
    # el ERROR no entra al cache: solo quedó la salida sana de 'a'
    assert list(cache.values()) == ["RESULTADO okt: x"]
    r2 = ejecutar(flujo, {}, _fake_run(reg), cache=cache)
    assert r2["cacheados"] == ["a"]
    assert llamadas["ok"] == 1              # 'a' se reusó sin ejecutar
    assert llamadas["mal"] == 2             # 'b' (ERROR) se reintenta siempre
    assert r2["salidas"]["a"] == "RESULTADO okt: x"


def test_sin_cache_no_hay_cacheados_pero_la_clave_existe():
    # default intacto: sin cache el resultado igual trae la clave (vacía)
    flujo = {"nodos": [{"id": "a", "tool": "eco", "args": "x", "wires": []}]}
    r = ejecutar(flujo, {}, _fake_run({"eco": lambda a: f"RESULTADO eco: {a}"}))
    assert r["cacheados"] == []


# ── sub-flujos: profundidad 1 permitida, profundidad 2 con ERROR ────────────

def _flujos_anidados(tmp_path, monkeypatch, contador):
    """Registra t_fake y arma i←m←o: 'o' ejecuta 'm', 'm' ejecuta 'i'."""
    import json
    from cognia.agent import tools as T

    def fake(args, ctx):
        contador["n"] += 1
        return f"RESULTADO t_fake: {args}"

    monkeypatch.setitem(T.TOOLS, "t_fake",
                        {"fn": fake, "doc": "t_fake <x>", "danger": False})
    inner = tmp_path / "i.flujo.json"
    inner.write_text(json.dumps({"nodos": [
        {"id": "x", "tool": "t_fake", "args": "hondo", "wires": []}]}),
        encoding="utf-8")
    mid = tmp_path / "m.flujo.json"
    mid.write_text(json.dumps({"nodos": [
        {"id": "m", "tool": "ejecutar_flujo", "args": str(inner),
         "wires": []}]}), encoding="utf-8")
    outer = tmp_path / "o.flujo.json"
    outer.write_text(json.dumps({"nodos": [
        {"id": "o", "tool": "ejecutar_flujo", "args": str(mid),
         "wires": []}]}), encoding="utf-8")
    return T, inner, mid, outer


def test_subflujo_profundidad_1_funciona(tmp_path, monkeypatch):
    contador = {"n": 0}
    T, inner, mid, outer = _flujos_anidados(tmp_path, monkeypatch, contador)
    ctx = {}
    r = T.TOOLS["ejecutar_flujo"]["fn"](str(mid), ctx)
    assert "1 nodos, 0 con error" in r
    assert contador["n"] == 1               # el flujo interno corrió de verdad
    # el nivel del llamador queda intacto: la profundidad viaja en una COPIA
    # del ctx (el contador mutado en el ctx compartido sufría carrera con
    # hermanos paralelos: ambos leían 1, escribían 2 y sus finally lo bajaban
    # a 0, dejando pasar anidamiento de profundidad 3)
    assert not ctx.get("_flujo_depth")


def test_subflujo_profundidad_2_da_error(tmp_path, monkeypatch):
    contador = {"n": 0}
    T, inner, mid, outer = _flujos_anidados(tmp_path, monkeypatch, contador)
    r = T.TOOLS["ejecutar_flujo"]["fn"](str(outer), {})
    # o corre (nivel 1) y ejecuta m (nivel 2); m intenta ejecutar i (nivel 3)
    # y ahí corta la guardia: el flujo más hondo jamás llega a correr
    assert contador["n"] == 0
    assert "1 con error" in r


def test_guardia_profundidad_directa():
    # llamador ya en el techo: el ERROR sale sin tocar disco
    from cognia.agent import tools as T
    r = T.TOOLS["ejecutar_flujo"]["fn"]("lo_que_sea", {"_flujo_depth": 2})
    assert "ERROR" in r and "profundidad" in r


def test_subflujo_hermanos_paralelos_no_burlan_guardia(tmp_path, monkeypatch):
    # REGRESION (carrera): con COGNIA_FLOWS_PARALELO=1, dos ejecutar_flujo
    # hermanos compartian ctx y el contador leer/incrementar/decrementar
    # dejaba la profundidad en 0 al terminar ambos -> un tercer sub-flujo del
    # nivel siguiente arrancaba como top-level y su cadena mid->deep corria a
    # profundidad real 3. La barrera dentro de los hermanos fuerza el
    # interleaving (ambos incrementos antes de cualquier decremento), que era
    # determinista 20/20 antes del fix.
    import json
    import threading
    from cognia.agent import tools as T

    contador = {"deep": 0}
    barrera = threading.Barrier(2)

    def probe(args, ctx):
        try:
            barrera.wait(timeout=5)
        except Exception:
            return "RESULTADO t_probe ERROR: barrera rota"
        return "RESULTADO t_probe: ok"

    def hondo(args, ctx):
        contador["deep"] += 1
        return "RESULTADO t_deep: corri (NO deberia)"

    monkeypatch.setitem(T.TOOLS, "t_probe",
                        {"fn": probe, "doc": "t_probe", "danger": False})
    monkeypatch.setitem(T.TOOLS, "t_deep",
                        {"fn": hondo, "doc": "t_deep", "danger": False})
    monkeypatch.setenv("COGNIA_FLOWS_PARALELO", "1")
    monkeypatch.delenv("COGNIA_FLOWS_CACHE", raising=False)

    def _w(nombre, nodos):
        p = tmp_path / f"{nombre}.flujo.json"
        p.write_text(json.dumps({"nodos": nodos}), encoding="utf-8")
        return p

    i1 = _w("i1", [{"id": "p", "tool": "t_probe", "args": "1", "wires": []}])
    i2 = _w("i2", [{"id": "p", "tool": "t_probe", "args": "2", "wires": []}])
    deep = _w("deep", [{"id": "d", "tool": "t_deep", "args": "x",
                        "wires": []}])
    mid = _w("mid", [{"id": "m", "tool": "ejecutar_flujo", "args": str(deep),
                      "wires": []}])
    outer = _w("outer", [
        {"id": "s1", "tool": "ejecutar_flujo", "args": str(i1),
         "wires": ["s3"]},
        {"id": "s2", "tool": "ejecutar_flujo", "args": str(i2),
         "wires": ["s3"]},
        {"id": "s3", "tool": "ejecutar_flujo", "args": str(mid),
         "wires": []}])

    ctx = {}
    r = T.TOOLS["ejecutar_flujo"]["fn"](str(outer), ctx)
    # los hermanos legitimos (profundidad real 2) corren sin rechazo espurio
    assert "barrera rota" not in r
    # y la cadena s3->mid->deep (profundidad real 3) JAMAS ejecuta
    assert contador["deep"] == 0
    # el ctx del llamador queda sin nivel residual
    assert not ctx.get("_flujo_depth")


def test_cache_persistente_subflujo_no_se_pisa(tmp_path, monkeypatch):
    """REGRESION (fix 2026-08-11): con COGNIA_FLOWS_CACHE=1 el padre leia el
    .flujo_cache.json al ARRANCAR y al terminar escribia SU dict tal cual:
    las claves que el sub-flujo hijo persistio DURANTE la corrida del padre
    (el hijo termina antes) se perdian — el padre pisaba el archivo con su
    snapshot viejo. Ahora el padre relee y fusiona antes del tmp+replace:
    la clave A del hijo sobrevive junto a las B del padre."""
    import json
    from cognia.agent import tools as T
    from cognia.agents.workers import dev_tools as DT

    def fake(args, ctx):
        return f"RESULTADO t_fake: {args}"

    monkeypatch.setitem(T.TOOLS, "t_fake",
                        {"fn": fake, "doc": "t_fake <x>", "danger": False})
    monkeypatch.setattr(DT, "_root_actual", lambda: str(tmp_path))
    monkeypatch.setenv("COGNIA_FLOWS_CACHE", "1")
    monkeypatch.delenv("COGNIA_FLOWS_PARALELO", raising=False)
    inner = tmp_path / "i.flujo.json"
    inner.write_text(json.dumps({"nodos": [
        {"id": "x", "tool": "t_fake", "args": "hijo_A", "wires": []}]}),
        encoding="utf-8")
    outer = tmp_path / "o.flujo.json"
    outer.write_text(json.dumps({"nodos": [
        {"id": "sub", "tool": "ejecutar_flujo", "args": str(inner),
         "wires": ["p"]},
        {"id": "p", "tool": "t_fake", "args": "padre_B", "wires": []}]}),
        encoding="utf-8")
    r = T.TOOLS["ejecutar_flujo"]["fn"](str(outer), {})
    assert "0 con error" in r
    datos = json.loads((tmp_path / ".flujo_cache.json")
                       .read_text(encoding="utf-8"))
    vals = set(datos.values())
    # la salida del nodo del HIJO (escrita primero) y la del PADRE conviven
    assert "RESULTADO t_fake: hijo_A" in vals       # antes: pisada
    assert "RESULTADO t_fake: padre_B" in vals
