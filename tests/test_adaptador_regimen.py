"""
Tests del ADAPTADOR del agente: quien decide el REGIMEN y el SAMPLING.

LA REGRESION QUE CUBREN (2026-08-13). model_profiles decidia el regimen con
`fam in modelo` contra cinco literales escritos a mano: un modelo fuera de esa
lista caia al marco de texto AUNQUE el server emitiera tool_calls perfectos, y
uno DENTRO de la lista se declaraba nativo aunque el server no parseara nada.
El coste esta medido (COMPARACION_MODELOS_20260813.md): Qwen3-4B-Thinking
0/26 en texto contra 15/26 en nativo. Los dos primeros tests son EL
CONTRAFACTUAL DEL NOMBRE y fallan con el codigo viejo:

  - modelo INVENTADO (fuera de toda tabla) + sonda que dice SI  -> NATIVO
  - modelo de la tabla (qwythos) + sonda que dice NO            -> TEXTO

El resto cubre lo que el nombre del modelo si puede seguir decidiendo (el
SAMPLING), la tabla de usuario que lo extiende sin tocar codigo, la base que
declara el propio server, el TTL del cache de /props y que resetear_cache()
tambien olvide la medicion de la sonda.

Sin red: props() y capacidad.medicion() van con dobles deterministas. La
verificacion contra el :8080 vivo se hace fuera de pytest (perfil_del_agente
con forzar=True), como manda CLAUDE.md.
"""
import json
import time

import pytest

import cognia.backend_activo as ba
from cognia.agent import capacidad, model_profiles
from cognia.agent.model_profiles import perfil_del_agente, verificar_arranque

URL = "http://127.0.0.1:8080"


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch, tmp_path):
    """HOME virgen (perfiles_modelo.json + cache de la sonda) y caches vacios:
    un test que herede el cache del anterior mide otra cosa."""
    for var in ("COGNIA_AGENT_TOOLS", "COGNIA_AGENT_LEGACY",
                "COGNIA_REASONING_EFFORT", "COGNIA_LLM_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path))
    monkeypatch.setattr(ba, "_props_cache", {})
    monkeypatch.setattr(ba, "_props_sello", {})
    monkeypatch.setattr(capacidad, "_mem", {})


def _servidor(monkeypatch, modelo, sonda, n_ctx=16384, sampling=None):
    """Un server de mentira: `modelo` es lo que dice /props y `sonda` lo que
    mide capacidad. Son INDEPENDIENTES a proposito: esa independencia es la
    tesis de la tarea."""
    datos = ({"modelo": modelo, "n_ctx": n_ctx, "puerto": 8080,
              "sampling": dict(sampling or {})} if modelo else {})
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: dict(datos))
    monkeypatch.setattr(capacidad, "medicion",
                        lambda url="", forzar=False: {
                            "soporta_tools": sonda, "modelo": modelo,
                            "motivo": ("tool call valido en 1.2s" if sonda
                                       else "respondio sin tool_calls")})


# ── EL CONTRAFACTUAL DEL NOMBRE ─────────────────────────────────────────────

def test_modelo_inventado_con_sonda_positiva_va_NATIVO(monkeypatch):
    """El punto de toda la tarea: un GGUF que no esta en ninguna tabla, y que
    el server SI sabe servir con tools, entra en regimen nativo."""
    _servidor(monkeypatch, "modelo-inventado-7b.gguf", sonda=True)
    p = perfil_del_agente()
    assert p["tools"] == "nativo"
    assert p["capacidad"] == "sonda"
    assert p["familia"] == ""            # no casa con ninguna: no hace falta
    assert p["max_tokens"] >= model_profiles.MIN_TOKENS_RAZONADOR
    assert verificar_arranque(p) == []


def test_modelo_de_la_tabla_con_sonda_negativa_va_TEXTO(monkeypatch):
    """Y al reves: estar en la tabla no basta. Un llama-server sin --jinja
    devuelve prosa y el bucle nativo la leeria como 'fin natural' (cierre en
    el paso 1 sin ejecutar nada); la sonda lo ve y manda a texto."""
    _servidor(monkeypatch, "qwythos-9b.gguf", sonda=False)
    p = perfil_del_agente()
    assert p["tools"] == "texto"
    assert p["nombre"] == "texto_legacy"
    assert "sin tool_calls" in p["motivo"]


# ── Los overrides GANAN a la sonda ──────────────────────────────────────────

def test_override_texto_gana_a_la_sonda(monkeypatch):
    _servidor(monkeypatch, "modelo-inventado-7b.gguf", sonda=True)
    monkeypatch.setenv("COGNIA_AGENT_TOOLS", "texto")
    assert perfil_del_agente()["tools"] == "texto"


def test_override_legacy_gana_a_la_sonda(monkeypatch):
    _servidor(monkeypatch, "modelo-inventado-7b.gguf", sonda=True)
    monkeypatch.setenv("COGNIA_AGENT_LEGACY", "1")
    assert perfil_del_agente()["tools"] == "texto"


def test_override_nativo_gana_a_la_sonda(monkeypatch):
    """Forzar nativo sobre una sonda negativa sigue siendo posible (es el A/B
    del plan), pero el perfil lo declara y verificar_arranque lo GRITA con el
    motivo real de la medicion — antes comparaba el dict consigo mismo."""
    _servidor(monkeypatch, "qwythos-9b.gguf", sonda=False)
    monkeypatch.setenv("COGNIA_AGENT_TOOLS", "nativo")
    p = perfil_del_agente()
    assert p["tools"] == "nativo" and p["capacidad"] == "forzado"
    avisos = verificar_arranque(p)
    assert any("sonda dice que NO" in a and "sin tool_calls" in a
               for a in avisos), avisos


def test_sonda_que_revienta_degrada_a_texto(monkeypatch):
    """Nada de lo que haga la sonda puede romper /hacer: si lanza, texto."""
    def _explota(url="", forzar=False):
        raise RuntimeError("boom")
    _servidor(monkeypatch, "modelo-inventado-7b.gguf", sonda=True)
    monkeypatch.setattr(capacidad, "medicion", _explota)
    p = perfil_del_agente()
    assert p["tools"] == "texto"
    assert "RuntimeError" in p["motivo"] and "boom" in p["motivo"]


def test_sin_backend_va_texto(monkeypatch):
    _servidor(monkeypatch, "", sonda=False)
    p = perfil_del_agente()
    assert p["tools"] == "texto" and p["modelo"] == "(sin backend)"


# ── SAMPLING: familia -> server -> ultimo recurso ───────────────────────────

SAMPLING_SERVER = {"temperature": 0.8, "top_p": 0.95, "repeat_penalty": 1.0}


def test_sampling_base_lo_declara_el_SERVER_no_el_fichero(monkeypatch):
    """El vicio que elimina la tarea: a un modelo sin familia se le inventaba
    0.7/0.8 (sampling de Qwen). Ahora manda default_generation_settings."""
    _servidor(monkeypatch, "modelo-inventado-7b.gguf", sonda=True,
              sampling=SAMPLING_SERVER)
    p = perfil_del_agente()
    assert (p["temperature"], p["top_p"]) == (0.8, 0.95)
    assert "server" in p["sampling_origen"]


def test_repeat_penalty_NO_viaja_al_perfil(monkeypatch, tmp_path):
    """Lo declaraba el server Y lo pedia el usuario, y aun asi no sale en el
    perfil: el sampling del agente lo arma loop.py:409-415 con temperature/
    top_p/max_tokens/reasoning_effort/url, y cli.py:10503 excluye rp A
    PROPOSITO (rp=1.3 hundio al 3B en 3.8.4). Un numero que aparece en el
    perfil y no llega a ningun consumidor es un control FINGIDO."""
    (tmp_path / "perfiles_modelo.json").write_text(
        json.dumps({"inventado": {"repeat_penalty": 1.3}}), encoding="utf-8")
    _servidor(monkeypatch, "modelo-inventado-7b.gguf", sonda=True,
              sampling=SAMPLING_SERVER)
    p = perfil_del_agente()
    assert "repeat_penalty" not in p, p
    assert "repeat_penalty" not in model_profiles._CLAVES_SAMPLING


def test_sin_sampling_del_server_queda_el_ultimo_recurso(monkeypatch):
    _servidor(monkeypatch, "modelo-inventado-7b.gguf", sonda=True, sampling={})
    p = perfil_del_agente()
    assert (p["temperature"], p["top_p"]) == (0.7, 0.8)
    assert "fallback" in p["sampling_origen"]


def test_familia_del_codigo_pisa_al_server(monkeypatch):
    """qwythos esta MEDIDO a mano (0.7/0.8): eso vence al default del server."""
    _servidor(monkeypatch, "huihui-qwythos-9b-abliterated-q4_k.gguf",
              sonda=True, sampling=SAMPLING_SERVER)
    p = perfil_del_agente()
    assert (p["temperature"], p["top_p"]) == (0.7, 0.8)
    assert p["familia"] == "qwythos"
    assert p["reasoning_effort"] == ""       # familia sin effort de harmony


def test_familia_del_JSON_de_usuario_sin_tocar_codigo(monkeypatch, tmp_path):
    """Un modelo nuevo se configura editando ~/.cognia/perfiles_modelo.json.
    Antes habia que editar _FAMILIAS_NATIVAS y reinstalar: por eso la tabla
    llevaba meses con cinco entradas."""
    (tmp_path / "perfiles_modelo.json").write_text(json.dumps(
        {"inventado": {"temperature": 0.33, "top_p": 0.44,
                       "usa_effort": True}}), encoding="utf-8")
    _servidor(monkeypatch, "modelo-inventado-7b.gguf", sonda=True,
              sampling=SAMPLING_SERVER)
    p = perfil_del_agente()
    assert (p["temperature"], p["top_p"]) == (0.33, 0.44)
    assert p["familia"] == "inventado"
    assert p["reasoning_effort"] == "low"    # usa_effort del fichero


def test_JSON_de_usuario_pisa_la_tabla_del_codigo_y_completa(monkeypatch,
                                                             tmp_path):
    """El fichero gana a _FAMILIAS_NATIVAS, y lo que NO declara lo completa el
    server (no se pierde el top_p por declarar solo la temperatura)."""
    (tmp_path / "perfiles_modelo.json").write_text(
        json.dumps({"qwythos": {"temperature": 0.11}}), encoding="utf-8")
    _servidor(monkeypatch, "qwythos-9b.gguf", sonda=True,
              sampling=SAMPLING_SERVER)
    p = perfil_del_agente()
    assert p["temperature"] == 0.11
    assert p["top_p"] == 0.95                # del server, no el 0.8 del codigo


def test_JSON_de_usuario_corrupto_no_rompe_el_perfil(monkeypatch, tmp_path):
    (tmp_path / "perfiles_modelo.json").write_text("{esto no es json",
                                                   encoding="utf-8")
    _servidor(monkeypatch, "qwythos-9b.gguf", sonda=True,
              sampling=SAMPLING_SERVER)
    assert model_profiles.familias_usuario() == {}
    p = perfil_del_agente()
    assert (p["temperature"], p["top_p"]) == (0.7, 0.8)   # tabla del codigo


def test_gpt_oss_conserva_su_harmony(monkeypatch):
    """El adaptador no toca lo ya medido: harmony sigue 1.0/1.0 con effort."""
    _servidor(monkeypatch, "gpt-oss-20b-MXFP4.gguf", sonda=True,
              sampling=SAMPLING_SERVER)
    p = perfil_del_agente()
    assert (p["temperature"], p["top_p"]) == (1.0, 1.0)
    assert p["reasoning_effort"] == "low"


# ── backend_activo.props: sampling del server y TTL del cache ───────────────

def _urlopen_falso(monkeypatch, payload, contador=None):
    """Sustituye urllib.request.urlopen por uno que devuelve `payload` (dict o
    callable que devuelve dict) y cuenta las llamadas."""
    class _Resp:
        def __init__(self, cuerpo):
            self._cuerpo = cuerpo
        def read(self):
            return json.dumps(self._cuerpo).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def _fake(url, timeout=None):
        if contador is not None:
            contador.append(url)
        return _Resp(payload() if callable(payload) else payload)

    monkeypatch.setattr(ba.urllib.request, "urlopen", _fake)


# El /props REAL de llama-server b10066 (:8080, medido 2026-08-13): el
# sampling vive en default_generation_settings.params, no plano.
PROPS_B10066 = {
    "model_path": "C:/modelos/qwythos-9b.gguf",
    "default_generation_settings": {
        "n_ctx": 200192,
        "params": {"temperature": 0.800000011920929, "top_k": 40,
                   "top_p": 0.949999988079071, "repeat_penalty": 1.0},
    },
}


def test_props_extrae_el_sampling_de_params(monkeypatch):
    """props() es el ESPEJO de /props: reporta lo que el server declara, rp
    incluido (es auditoria, y ver que el server usa rp=1.0 vale para
    diagnosticar). Quien decide que se PROPAGA al agente es model_profiles,
    que deja rp fuera — ver test_repeat_penalty_NO_viaja_al_perfil."""
    _urlopen_falso(monkeypatch, PROPS_B10066)
    p = ba.props(URL, forzar=True)
    assert p["modelo"] == "qwythos-9b.gguf" and p["n_ctx"] == 200192
    # redondeado: el server entrega el float de C (0.800000011920929)
    assert p["sampling"] == {"temperature": 0.8, "top_p": 0.95,
                             "repeat_penalty": 1.0}


def test_props_tambien_lee_el_formato_plano_viejo(monkeypatch):
    _urlopen_falso(monkeypatch, {
        "model_path": "/m/viejo.gguf",
        "default_generation_settings": {"n_ctx": 4096, "temperature": 0.5,
                                        "top_p": 0.9}})
    p = ba.props(URL, forzar=True)
    assert p["sampling"] == {"temperature": 0.5, "top_p": 0.9}


def test_props_TTL_reconsulta_tras_el_vencimiento(monkeypatch):
    """La averia: el cache era eterno, asi que tras un swap de modelo en el
    MISMO puerto (lo que hace el summoner) props() seguia devolviendo el
    modelo viejo toda la vida del proceso y el regimen del agente se decidia
    sobre un modelo que ya no estaba."""
    servido = {"n": 0}

    def _payload():
        servido["n"] += 1
        return {"model_path": f"/m/modelo-{servido['n']}.gguf",
                "default_generation_settings": {"n_ctx": 4096}}

    _urlopen_falso(monkeypatch, _payload)
    assert ba.props(URL)["modelo"] == "modelo-1.gguf"
    assert ba.props(URL)["modelo"] == "modelo-1.gguf"      # cache dentro del TTL
    ba._props_sello[URL] = time.time() - (ba._TTL_PROPS_S + 1)
    assert ba.props(URL)["modelo"] == "modelo-2.gguf"      # vencio: reconsulta


def test_props_entrada_inyectada_a_mano_no_caduca(monkeypatch):
    """Contrato con las fixtures que escriben _props_cache[url] directamente
    (tests/test_llm_local_perfil.py): sin sello no hay expiracion."""
    def _no_debe_llamarse(url, timeout=None):
        raise AssertionError("una entrada inyectada no debe re-consultarse")
    monkeypatch.setattr(ba.urllib.request, "urlopen", _no_debe_llamarse)
    ba._props_cache[URL] = {"modelo": "puesto-a-mano.gguf", "n_ctx": 8}
    assert ba.props(URL)["modelo"] == "puesto-a-mano.gguf"


# ── n_ctx SIN SONDA: la barra de estado no paga un POST de generacion ───────

def test_n_ctx_del_backend_NO_sonda(monkeypatch):
    """LA REGRESION MEDIDA (2026-08-13): cli.py:6467 llamaba a
    perfil_del_agente() solo para sacar n_ctx, dentro de _datos_barra_estado(),
    que prompt_toolkit invoca en CADA redibujado del prompt. Con el cache de la
    sonda frio, el primer pintado del REPL pasaba de 0,064 s a 3,42 s (mismo
    :8080) y hasta 30 s (capacidad._TIMEOUT_S) con un server lento. La via sin
    sonda solo mira /props (GET local cacheado)."""
    def _prohibido(*a, **k):
        raise AssertionError("n_ctx_del_backend NO debe sondar al modelo")
    monkeypatch.setattr(capacidad, "sondar", _prohibido)
    monkeypatch.setattr(capacidad, "medicion", _prohibido)
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {
        "modelo": "qwythos-9b.gguf", "n_ctx": 200192, "puerto": 8080,
        "sampling": {}})
    assert model_profiles.n_ctx_del_backend() == 200192
    # ...y el camino que SI decide regimen sigue sondando (contraprueba: sin
    # esto el test no distinguiria una via de la otra). Se ve en el motivo:
    # perfil_del_agente atrapa el fallo de la sonda y degrada a texto, o sea
    # la llamo.
    p = perfil_del_agente()
    assert p["tools"] == "texto" and "AssertionError" in p["motivo"], p


def test_n_ctx_del_backend_sin_backend_devuelve_None(monkeypatch):
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {})
    assert model_profiles.n_ctx_del_backend() is None


# ── La orden que se le sugiere al usuario sin backend ───────────────────────

def test_orden_arrancar_no_manda_al_combo_equivocado():
    """EL DEFECTO (revision adversarial 2026-08-13): los tres avisos de 'no hay
    backend' decian 'flota arrancar pensar', y ese combo levanta gpt-oss-20b —
    NO el cerebro principal (flota.COMBO_DEFAULT='pensar-qwythos' desde el
    2026-08-09). Al usuario que se quedo sin backend se le mandaba a levantar
    otro modelo del que espera el resto del sistema."""
    from cognia import flota
    orden = ba.orden_arrancar()
    combo = orden.split("flota arrancar", 1)[1].strip()
    assert combo != "pensar", orden
    assert combo == flota.COMBO_DEFAULT and combo in flota.COMBOS, orden


def test_sin_backend_sugiere_el_cerebro_principal(monkeypatch, tmp_path,
                                                  capsys):
    """El aviso REAL que ve el usuario (stderr, sin oyentes del bus)."""
    monkeypatch.setattr(ba, "AUDIT", tmp_path / "audit.jsonl")
    ba.sin_backend("chat", "prueba del combo")
    err = capsys.readouterr().err
    assert "flota arrancar pensar-qwythos" in err, err


def test_estado_sin_backend_sugiere_el_cerebro_principal(monkeypatch):
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {})
    avisos = ba.estado()["avisos"]
    assert avisos and "flota arrancar pensar-qwythos" in avisos[0], avisos


def test_resetear_cache_tambien_olvida_la_sonda(monkeypatch, tmp_path):
    """El cache de la sonda esta indexado por (url, modelo) y el modelo sale
    de props(): si se resetea uno sin el otro, el regimen queda decidido con
    la medicion del modelo anterior."""
    capacidad._mem["x|y"] = {"soporta_tools": True, "cuando": time.time()}
    ba._props_cache[URL] = {"modelo": "algo.gguf"}
    ba._props_sello[URL] = time.time()
    ba.resetear_cache()
    assert ba._props_cache == {} and ba._props_sello == {}
    assert capacidad._mem == {}
