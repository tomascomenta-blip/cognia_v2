# -*- coding: utf-8 -*-
"""Tests del protocolo de worker del summoner (CPU puro, sin GPU, sin red externa).

Todo con manejar_fn/cargar_fn fakes sobre 127.0.0.1 en puertos efimeros.
Cubre el contrato congelado (plan_olas.md, agente B):
  - /health responde DURANTE un job lento (ocupado: true)
  - /job serializado por Lock (nunca dos jobs a la vez)
  - excepcion en el job -> {"ok": false, "error"} y el worker SIGUE vivo
  - /apagar termina limpio
  - COGNIA_WORKER_PRELOAD: 1 = cargar antes de abrir puerto; 0 = perezoso
  - manejar() de worker_imagen: validacion de op/kwargs y gate de backend
"""
import contextlib
import importlib.util
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from cognia.summoner_worker import servir

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- helpers ---

def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(puerto: int, ruta: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(
            "http://127.0.0.1:%d%s" % (puerto, ruta), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(puerto: int, ruta: str, payload=None, timeout: float = 30.0,
          crudo: bytes = None) -> dict:
    datos = crudo if crudo is not None else json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (puerto, ruta), data=datos,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _esperar_health(puerto: int, plazo: float = 5.0) -> dict:
    fin = time.time() + plazo
    ultimo = None
    while time.time() < fin:
        try:
            ultimo = _get(puerto, "/health", timeout=1.0)
            if ultimo.get("ok"):
                return ultimo
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.05)
    raise AssertionError("el worker no levanto /health en %.1fs (ultimo: %r)"
                         % (plazo, ultimo))


@contextlib.contextmanager
def _worker(manejar_fn, cargar_fn=None, rol="fake"):
    """Levanta servir() en un hilo y lo apaga limpio al salir del with."""
    puerto = _puerto_libre()
    hilo = threading.Thread(target=servir, args=(puerto, rol, cargar_fn, manejar_fn),
                            daemon=True)
    hilo.start()
    _esperar_health(puerto)
    try:
        yield puerto, hilo
    finally:
        if hilo.is_alive():
            with contextlib.suppress(Exception):
                _post(puerto, "/apagar", timeout=5.0)
            hilo.join(timeout=5.0)


# ----------------------------------------------------------------- health ---

def test_health_responde_durante_job_lento():
    """El contrato clave: /health vive mientras un job de minutos corre."""
    puerta = threading.Event()

    def manejar(payload):
        puerta.wait(timeout=15)
        return {"listo": True}

    with _worker(manejar) as (puerto, _):
        resultado = {}

        def lanzar():
            resultado.update(_post(puerto, "/job", {"x": 1}))

        t = threading.Thread(target=lanzar, daemon=True)
        t.start()
        # Poll hasta ver el worker OCUPADO -- prueba que health responde en
        # pleno job y que el flag es visible.
        fin = time.time() + 5
        h = {}
        while time.time() < fin:
            h = _get(puerto, "/health", timeout=1.0)
            if h.get("ocupado"):
                break
            time.sleep(0.02)
        assert h.get("ocupado") is True, "health nunca reporto ocupado: %r" % h
        assert h["ok"] is True and h["rol"] == "fake"
        puerta.set()
        t.join(timeout=10)
        assert resultado.get("ok") is True and resultado.get("listo") is True
        # Al terminar el job, desocupado de vuelta.
        assert _get(puerto, "/health")["ocupado"] is False


def test_health_contrato_campos():
    with _worker(lambda p: {}) as (puerto, _):
        h = _get(puerto, "/health")
        assert set(h) == {"ok", "rol", "ocupado", "cargado"}
        assert h == {"ok": True, "rol": "fake", "ocupado": False, "cargado": False}


def test_ruta_desconocida_404():
    with _worker(lambda p: {}) as (puerto, _):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(puerto, "/nada")
        assert exc.value.code == 404


# -------------------------------------------------------------------- lock ---

def test_jobs_serializados_por_lock():
    """Dos jobs concurrentes jamas se solapan (una GPU = un job a la vez)."""
    en_curso = {"n": 0, "max": 0}
    guardia = threading.Lock()

    def manejar(payload):
        with guardia:
            en_curso["n"] += 1
            en_curso["max"] = max(en_curso["max"], en_curso["n"])
        time.sleep(0.25)
        with guardia:
            en_curso["n"] -= 1
        return {"eco": payload["i"]}

    with _worker(manejar) as (puerto, _):
        salidas = [None, None]

        def lanzar(i):
            salidas[i] = _post(puerto, "/job", {"i": i})

        hilos = [threading.Thread(target=lanzar, args=(i,), daemon=True)
                 for i in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=10)
        assert en_curso["max"] == 1, "dos jobs corrieron a la vez"
        assert {s["eco"] for s in salidas} == {0, 1}
        assert all(s["ok"] for s in salidas)


# ------------------------------------------------------------- excepciones ---

def test_excepcion_no_mata_al_worker():
    llamadas = {"n": 0}

    def manejar(payload):
        llamadas["n"] += 1
        if payload.get("romper"):
            raise ValueError("boom del job 42")
        return {"sano": True}

    with _worker(manejar) as (puerto, _):
        r = _post(puerto, "/job", {"romper": True})
        assert r["ok"] is False
        assert "boom del job 42" in r["error"]
        assert len(r["error"]) <= 2000  # tb recortado a la cola
        # El worker sigue vivo y procesa el siguiente job.
        r2 = _post(puerto, "/job", {})
        assert r2 == {"sano": True, "ok": True}
        assert llamadas["n"] == 2
        assert _get(puerto, "/health")["ok"] is True


def test_payload_no_json_devuelve_error_sin_matar():
    with _worker(lambda p: {"ok": True}) as (puerto, _):
        r = _post(puerto, "/job", crudo=b"esto no es json {")
        assert r["ok"] is False and r["error"]
        assert _get(puerto, "/health")["ok"] is True


def test_payload_json_no_dict_devuelve_error():
    with _worker(lambda p: {"ok": True}) as (puerto, _):
        r = _post(puerto, "/job", crudo=b"[1, 2, 3]")
        assert r["ok"] is False
        assert "objeto JSON" in r["error"]


def test_manejar_fn_que_no_devuelve_dict_es_error_visible():
    with _worker(lambda p: "cadena") as (puerto, _):
        r = _post(puerto, "/job", {})
        assert r["ok"] is False
        assert "se esperaba dict" in r["error"]


def test_manejar_fn_ok_false_pasa_tal_cual():
    # Un {"ok": false} diagnostico del manejar_fn NO se pisa con ok=True.
    with _worker(lambda p: {"ok": False, "error": "backend apagado"}) as (puerto, _):
        r = _post(puerto, "/job", {})
        assert r == {"ok": False, "error": "backend apagado"}


# ------------------------------------------------------------------ apagar ---

def test_apagar_limpio():
    def manejar(payload):
        return {}

    puerto = _puerto_libre()
    hilo = threading.Thread(target=servir, args=(puerto, "fake", None, manejar),
                            daemon=True)
    hilo.start()
    _esperar_health(puerto)
    r = _post(puerto, "/apagar", timeout=5.0)
    assert r == {"ok": True}
    hilo.join(timeout=5.0)
    assert not hilo.is_alive(), "servir() no retorno tras /apagar"
    # El puerto quedo libre de verdad (server_close corrio).
    with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
        _get(puerto, "/health", timeout=1.0)


# ----------------------------------------------------------------- preload ---

def test_preload_carga_antes_de_abrir_puerto(monkeypatch):
    monkeypatch.setenv("COGNIA_WORKER_PRELOAD", "1")
    orden = []

    def cargar():
        time.sleep(0.2)  # carga "lenta": el puerto NO debe abrir antes
        orden.append("cargado")

    def manejar(payload):
        return {}

    puerto = _puerto_libre()
    hilo = threading.Thread(target=servir, args=(puerto, "fake", cargar, manejar),
                            daemon=True)
    hilo.start()
    h = _esperar_health(puerto)
    try:
        assert orden == ["cargado"], "el puerto abrio antes de cargar_fn"
        assert h["cargado"] is True
    finally:
        _post(puerto, "/apagar", timeout=5.0)
        hilo.join(timeout=5.0)


def test_sin_preload_carga_perezosa_en_primer_job(monkeypatch):
    monkeypatch.delenv("COGNIA_WORKER_PRELOAD", raising=False)
    cargas = {"n": 0}

    def cargar():
        cargas["n"] += 1

    with _worker(lambda p: {"eco": p.get("i")}, cargar_fn=cargar) as (puerto, _):
        assert _get(puerto, "/health")["cargado"] is False
        assert cargas["n"] == 0
        r1 = _post(puerto, "/job", {"i": 1})
        assert r1["ok"] is True
        assert _get(puerto, "/health")["cargado"] is True
        _post(puerto, "/job", {"i": 2})
        assert cargas["n"] == 1, "cargar_fn debe correr UNA sola vez"


# ------------------------------------------------- worker_imagen.manejar() ---

def _cargar_worker_imagen():
    spec = importlib.util.spec_from_file_location(
        "worker_imagen_test", str(REPO / "scripts" / "worker_imagen.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_worker_imagen_op_desconocida():
    wi = _cargar_worker_imagen()
    r = wi.manejar({"op": "bailar"})
    assert r["ok"] is False
    assert "op desconocida" in r["error"]
    r2 = wi.manejar({})
    assert r2["ok"] is False


def test_worker_imagen_gate_backend_no_disponible(monkeypatch):
    wi = _cargar_worker_imagen()
    import cognia.assets as assets
    monkeypatch.setattr(assets, "backend_disponible",
                        lambda: (False, "sin CUDA en el test"))
    r = wi.manejar({"op": "generar", "prompt": "una manzana"})
    assert r["ok"] is False
    assert "sin CUDA en el test" in r["error"]


def test_worker_imagen_generar_exige_prompt(monkeypatch):
    wi = _cargar_worker_imagen()
    import cognia.assets as assets
    monkeypatch.setattr(assets, "backend_disponible", lambda: (True, "ok"))
    r = wi.manejar({"op": "generar"})
    assert r["ok"] is False and "prompt" in r["error"]


def test_worker_imagen_generar_pasa_kwargs_y_salida(monkeypatch, tmp_path):
    wi = _cargar_worker_imagen()
    import cognia.assets as assets
    monkeypatch.setenv("COGNIA_ASSETS_OUT", str(tmp_path))
    monkeypatch.setattr(assets, "backend_disponible", lambda: (True, "ok"))
    visto = {}

    def fake_generar(prompt, **kw):
        visto["prompt"] = prompt
        visto.update(kw)
        return kw["salida"]

    monkeypatch.setattr(assets, "generar_transparente", fake_generar)
    r = wi.manejar({"op": "generar", "prompt": "una manzana roja", "seed": 7})
    assert r["ok"] is True
    assert visto["prompt"] == "una manzana roja"
    assert visto["seed"] == 7
    # salida SIEMPRE explicita, bajo COGNIA_ASSETS_OUT
    assert str(tmp_path) in r["ruta"]
    assert r["ruta"].endswith(".png")


def test_worker_imagen_quitar_fondo_usa_gate_birefnet(monkeypatch, tmp_path):
    wi = _cargar_worker_imagen()
    import cognia.assets as assets
    monkeypatch.setenv("COGNIA_ASSETS_OUT", str(tmp_path))
    # backend_disponible (LayerDiffuse) apagado NO debe frenar un matting sano
    monkeypatch.setattr(assets, "backend_disponible",
                        lambda: (False, "falta layerdiffuse"))
    monkeypatch.setattr(assets, "birefnet_disponible", lambda: (True, "ok"))
    monkeypatch.setattr(assets, "quitar_fondo",
                        lambda entrada, **kw: kw["salida"])
    r = wi.manejar({"op": "quitar_fondo", "entrada": "foto.png"})
    assert r["ok"] is True
    assert str(tmp_path) in r["ruta"]


def test_worker_imagen_editar_exige_imagen_y_prompt(monkeypatch):
    wi = _cargar_worker_imagen()
    import cognia.assets as assets
    monkeypatch.setattr(assets, "backend_disponible", lambda: (True, "ok"))
    r = wi.manejar({"op": "editar", "prompt": "mas brillo"})
    assert r["ok"] is False and "imagen" in r["error"]


# ===========================================================================
# Rol 'worker' del summoner (llama chico Qwen3-4B en :8082) -- SIN GPU.
# Todo por monkeypatch de las seams de cognia/summoner.py, calcado del estilo
# de tests/test_summoner.py: lo testeable en CPU es la LOGICA (registry,
# plan de eviccion, idle, postchecks), que es donde viven los bugs.
# ===========================================================================

from cognia import summoner as S


@pytest.fixture
def sandbox_s(tmp_path, monkeypatch):
    """Estado del summoner en tmp, reloj congelado, sin sleeps reales."""
    monkeypatch.setenv("COGNIA_SUMMONER_STATE", str(tmp_path / "summoner.json"))
    monkeypatch.setattr(S, "_ahora", lambda: 1000.0)
    monkeypatch.setattr(S, "_dormir", lambda s: None)
    return tmp_path


# ---------------------------------------------------------------- registry ---

def test_rol_worker_registry_bien_formado():
    spec = S.ROLES["worker"]
    assert spec["tipo"] == "llama"
    assert spec["script"] == "servir_modelo.py"
    # 8082 disjunto de TODOS los demas roles y de la oficina (8088/8090/8092)
    assert spec["puerto"] == 8082
    otros = {r: s["puerto"] for r, s in S.ROLES.items() if r != "worker"}
    assert 8082 not in otros.values(), f"8082 colisiona: {otros}"
    assert 8082 not in {8088, 8090, 8092}
    # --puerto DEBE ir en args: _lanzar no lo pasa y el default de
    # servir_modelo.py es 8080 (pisaria al cerebro)
    args = spec["args"]
    assert "--puerto" in args
    assert args[args.index("--puerto") + 1] == str(spec["puerto"])
    assert "--sin-draft" in args    # el 4B no tiene draft que valga la pena
    # la identidad va en minusculas y tiene que aparecer en el trozo de
    # --modelo: si no, el postcheck contradiria al lanzamiento
    assert spec["identidad"] == spec["identidad"].lower() == "qwen3-4b"
    modelo_arg = args[args.index("--modelo") + 1]
    assert spec["identidad"] in modelo_arg.lower()
    assert spec["idle_s"] == 900


def test_rol_worker_identidad_en_gguf_real():
    """La identidad debe casar con un GGUF instalado de verdad (si el dir
    existe): un registry que apunta a un modelo fantasma falla recien en GPU."""
    dir_modelos = Path.home() / ".cognia" / "models"
    if not dir_modelos.is_dir():
        pytest.skip("sin ~/.cognia/models en esta maquina")
    nombres = [m.name.lower() for m in dir_modelos.glob("*.gguf")]
    if not nombres:
        pytest.skip("sin GGUFs instalados")
    assert any(S.ROLES["worker"]["identidad"] in n for n in nombres), \
        "ningun GGUF instalado casa con la identidad del worker"


# ---------------------------------------------------- _plan_eviccion (pura) ---

def test_plan_worker_victima_antes_que_vlm():
    """El worker es mas prescindible que el vlm: cae primero, y el cerebro
    jamas sin permiso explicito."""
    vivos = {"vlm": {"ultima": 999}, "worker": {"ultima": 999},
             "cerebro": {"ultima": 999}}
    plan = S._plan_eviccion(0, 3000, vivos, ahora=1000.0)
    assert plan == ["worker"]           # 5800 MiB ya cubren 3000+512
    plan2 = S._plan_eviccion(0, 6000, vivos, ahora=1000.0)
    assert plan2 == ["worker", "vlm"]   # hace falta mas: vlm despues
    assert "cerebro" not in S._plan_eviccion(0, 20000, vivos, ahora=1000.0)


def test_plan_worker_solicitante_evicta_jobs_primero():
    """Para hacerle sitio al worker caen antes las reservas y los jobs con
    idle vencido; el vlm queda vivo si con eso alcanza."""
    vivos = {"imagen": {"ultima": 100},   # idle 300 vencido (900s sin uso)
             "vlm": {"ultima": 999}}
    plan = S._plan_eviccion(0, S.ROLES["worker"]["vram_mib"], vivos,
                            ahora=1000.0)
    assert plan == ["imagen"]           # 12000 MiB cubren 5800+512


def test_plan_worker_vivo_victima_de_otro_rol():
    """Un worker vivo tambien es victima valida para otro rol (p.ej. vlm)."""
    vivos = {"worker": {"ultima": 999}}
    plan = S._plan_eviccion(0, S.ROLES["vlm"]["vram_mib"], vivos, ahora=1000.0)
    assert plan == ["worker"]


# ------------------------------------------------------------------ _idle_s ---

def test_idle_worker_default_y_override(monkeypatch):
    monkeypatch.delenv("COGNIA_SUMMONER_IDLE_WORKER", raising=False)
    assert S._idle_s("worker") == 900.0
    monkeypatch.setenv("COGNIA_SUMMONER_IDLE_WORKER", "120")
    assert S._idle_s("worker") == 120.0
    # env basura -> cae al default del registry, no revienta
    monkeypatch.setenv("COGNIA_SUMMONER_IDLE_WORKER", "basura")
    assert S._idle_s("worker") == 900.0


def test_idle_worker_no_lee_el_env_del_vlm(monkeypatch):
    monkeypatch.delenv("COGNIA_SUMMONER_IDLE_WORKER", raising=False)
    monkeypatch.setenv("COGNIA_SUMMONER_IDLE_VLM", "5")
    assert S._idle_s("worker") == 900.0


# ----------------------------------------------------- ensure() con fakes ---

def _fakes_ensure_worker(monkeypatch, *, slots=1,
                         modelo="Qwen3-4B-Thinking-2507-Q4_K_M.gguf"):
    """Escenario tipico calcado de test_summoner._fakes_ensure: nada servido,
    lanzamiento fake que 'levanta' el server, props verificables."""
    reg = {"lanzar": 0, "args": None, "arriba": False, "invalidados": 0}

    def fake_lanzar(rol, spec, args):
        reg["lanzar"] += 1
        reg["args"] = list(args)
        reg["arriba"] = True
        return 4242, ["cmd-fake"]

    monkeypatch.setattr(S, "_lanzar", fake_lanzar)
    monkeypatch.setattr(S, "_salud",
                        lambda puerto, timeout=3.0:
                        (200, {"ok": True}) if reg["arriba"] else (None, None))
    monkeypatch.setattr(S, "vram_mib", lambda: (2000, 16311))
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    monkeypatch.setattr(S, "_total_slots", lambda url: slots)
    monkeypatch.setattr(S, "_props",
                        lambda url: {"modelo": modelo, "n_ctx": 16384})
    monkeypatch.setattr(S, "_invalidar_caches",
                        lambda: reg.__setitem__("invalidados",
                                                reg["invalidados"] + 1))
    # hermetico ante la puerta anti-ajeno (2026-08-11): sin este stub, un
    # estado sembrado con pid vivo consultaria el netstat REAL de la maquina
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: None)
    return reg


def test_ensure_worker_frio_ok_e_invalida_caches(sandbox_s, monkeypatch):
    reg = _fakes_ensure_worker(monkeypatch)
    r = S.ensure("worker")
    assert r["ok"] and r["arranque_frio"] and r["pid"] == 4242
    assert r["url"] == "http://127.0.0.1:8082"
    assert r["n_ctx"] == 16384
    assert reg["lanzar"] == 1
    # los args del lanzamiento llevan el --puerto (sin el, pisaria al cerebro)
    assert ["--puerto", "8082"] == \
        reg["args"][reg["args"].index("--puerto"):reg["args"].index("--puerto") + 2]
    # 8082 esta en la lista de puertos que invalidan caches al arranque frio
    assert reg["invalidados"] == 1


def test_ensure_worker_postcheck_slots(sandbox_s, monkeypatch):
    """El postcheck total_slots==1 tambien aplica al worker: una build que
    ignora --parallel 1 parte el ctx y sirve HTTP 500 silenciosos."""
    _fakes_ensure_worker(monkeypatch, slots=4)
    monkeypatch.setattr(S, "_matar_pid", lambda pid: None)
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: None)
    with pytest.raises(S.SummonerError, match="slots"):
        S.ensure("worker")


def test_ensure_worker_identidad_ajena_falla(sandbox_s, monkeypatch):
    """Si en :8082 quedo otro modelo, ensure falla visible (no mata lo ajeno)."""
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (200, None))
    monkeypatch.setattr(S, "_props",
                        lambda url: {"modelo": "gpt-oss-20b.gguf", "n_ctx": 4096})
    with pytest.raises(S.SummonerError, match="ajeno"):
        S.ensure("worker")


# ---------------------------------------------------------------- liberar ---

def test_liberar_worker_invalida_caches(sandbox_s, monkeypatch):
    estado = S._leer_estado()
    estado["roles"]["worker"] = {"pid": 777, "puerto": 8082, "t_ultima": 1000.0}
    S._guardar_estado(estado)
    muertos = []
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: pid not in muertos)
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: True)
    monkeypatch.setattr(S, "_matar_pid", lambda pid: muertos.append(pid))
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    invalidados = {"n": 0}
    monkeypatch.setattr(S, "_invalidar_caches",
                        lambda: invalidados.__setitem__("n", invalidados["n"] + 1))
    assert S.liberar("worker") is True
    assert muertos == [777]
    assert invalidados["n"] == 1, "worker liberado sin invalidar caches"


# ===========================================================================
# Fixes 2026-08-11 (revision adversarial): vram_mib del worker, puerta
# anti proceso AJENO, candado por rol y deficit exacto en el _fallar.
# ===========================================================================

def _lanzar_prohibido(*a):
    """Seam de _lanzar para tests donde lanzar seria el BUG: si se llama, el
    test falla con un error que no es SummonerError (visible pre-fix)."""
    raise AssertionError("_lanzar no debia ser llamado en este escenario")


def test_worker_vram_declarada_cubre_la_cota_medida():
    """Fix 2026-08-11: 4200 subdeclaraba la cota inferior MEDIDA del
    artefacto (peso GGUF 2382 MiB + KV f16 @16k 2304 MiB = 4686) y la
    eviccion hacia sitio de MENOS. Sobredeclarar es seguro (solo una
    eviccion mas conservadora); subdeclarar no (OOM al cargar)."""
    assert S.ROLES["worker"]["vram_mib"] == 5800
    assert S.ROLES["worker"]["vram_mib"] >= 2382 + 2304  # cota medida


# ------------------------------------------- puerto ocupado por un ajeno ---

def test_ensure_worker_puerto_ajeno_http_no_lanza(sandbox_s, monkeypatch):
    """Fix 2026-08-11: un proceso ajeno que responde HTTP raro (404) en el
    puerto del rol -> SummonerError visible ANTES de limpiar/evictar/lanzar
    (llama-server solo emite 200/503; lanzar encima es en vano: el bind
    falla despues de pagar toda la eviccion)."""
    monkeypatch.setattr(S, "_lanzar", _lanzar_prohibido)
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (404, None))
    monkeypatch.setattr(S, "vram_mib", lambda: (2000, 16311))
    with pytest.raises(S.SummonerError,
                       match="puerto :8082 del rol 'worker' ocupado por un "
                             "proceso ajeno"):
        S.ensure("worker")


def test_ensure_worker_puerto_de_otro_pid_no_lanza(sandbox_s, monkeypatch):
    """Fix 2026-08-11: /health no responde pero netstat dice que el puerto lo
    tiene OTRO pid mientras el nuestro sigue vivo -> ajeno; ni se limpia la
    entrada, ni se mata a nadie, ni se lanza."""
    estado = S._leer_estado()
    estado["roles"]["worker"] = {"pid": 777, "puerto": 8082, "t_ultima": 1000.0}
    S._guardar_estado(estado)
    monkeypatch.setattr(S, "_lanzar", _lanzar_prohibido)
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: False)
    monkeypatch.setattr(S, "_matar_pid",
                        lambda pid: pytest.fail("mato un pid con puerto ajeno"))
    monkeypatch.setattr(S, "vram_mib", lambda: (2000, 16311))
    with pytest.raises(S.SummonerError, match="ocupado por un proceso ajeno"):
        S.ensure("worker")
    # la entrada sobrevive intacta: fallo visible, no limpieza a ciegas
    assert S._leer_estado()["roles"]["worker"]["pid"] == 777


def test_salud_distingue_libre_de_ocupado_por_ajeno():
    """Fix 2026-08-11: la tercera senal de _salud. (None, None) = nadie
    escucha (conexion rechazada); (-1, None) = algo ESCUCHA pero no habla
    HTTP. Sin la distincion, un proceso ajeno no-HTTP en el puerto era
    indistinguible de un puerto libre y ensure() lanzaba en vano."""
    # puerto libre: el SO rechaza la conexion al instante
    assert S._salud(_puerto_libre(), timeout=1.0) == (None, None)
    # listener crudo que acepta y corta sin hablar HTTP
    srv = socket.socket()
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        puerto = srv.getsockname()[1]

        def aceptar_y_cortar():
            with contextlib.suppress(Exception):
                con, _ = srv.accept()
                con.close()

        hilo = threading.Thread(target=aceptar_y_cortar, daemon=True)
        hilo.start()
        assert S._salud(puerto, timeout=2.0) == (-1, None)
        hilo.join(timeout=5)
    finally:
        srv.close()


# ------------------------------------------------- concurrencia de ensure ---

def test_candado_por_rol_unico_y_reentrante():
    """Fix 2026-08-11: un candado POR rol (no global) y RLock obligatorio:
    ensure() se recursa a si mismo y llama liberar/tocar en el mismo hilo."""
    a = S._candado_rol("worker")
    assert S._candado_rol("worker") is a, "dos candados para el mismo rol"
    assert S._candado_rol("vlm") is not a, "candado global: serializa de mas"
    assert a.acquire(blocking=False)
    try:
        assert a.acquire(blocking=False), "no reentrante: ensure se bloquearia"
        a.release()
    finally:
        a.release()


def test_ensure_worker_concurrente_lanza_una_sola_vez(sandbox_s, monkeypatch):
    """Fix 2026-08-11: dos hilos de paralelo() pidiendo el MISMO rol a la vez
    producian doble lanzamiento y estado pisado. Con el candado por rol el
    segundo hilo espera y encuentra el rol ya servido (arranque_frio=False).
    Pre-fix: el sleep REAL del lanzamiento fake mantiene abierta la ventana
    de carrera y ambos hilos ven /health caido -> 2 lanzamientos."""
    reg = {"lanzar": 0, "arriba": False}

    def fake_lanzar(rol, spec, args):
        reg["lanzar"] += 1
        time.sleep(0.3)   # ventana de carrera (sleep real, no _dormir stub)
        reg["arriba"] = True
        return 4242, ["cmd-fake"]

    monkeypatch.setattr(S, "_lanzar", fake_lanzar)
    monkeypatch.setattr(S, "_salud",
                        lambda puerto, timeout=3.0:
                        (200, {"ok": True}) if reg["arriba"] else (None, None))
    monkeypatch.setattr(S, "vram_mib", lambda: (2000, 16311))
    monkeypatch.setattr(S, "_pid_vivo", lambda pid: True)
    monkeypatch.setattr(S, "_total_slots", lambda url: 1)
    monkeypatch.setattr(S, "_props",
                        lambda url: {"modelo": "Qwen3-4B-Thinking.gguf",
                                     "n_ctx": 16384})
    monkeypatch.setattr(S, "_invalidar_caches", lambda: None)
    monkeypatch.setattr(S, "_pid_dueno_del_puerto", lambda pid, puerto: None)

    barrera = threading.Barrier(2)
    resultados, errores = [], []

    def pedir():
        barrera.wait(timeout=5)
        try:
            resultados.append(S.ensure("worker"))
        except Exception as e:
            errores.append(e)

    hilos = [threading.Thread(target=pedir, daemon=True) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=15)
    assert errores == [], f"ensure concurrente exploto: {errores}"
    assert reg["lanzar"] == 1, "doble lanzamiento del mismo rol"
    assert len(resultados) == 2 and all(r["ok"] for r in resultados)
    # uno arranco frio; el otro espero el candado y lo encontro servido
    assert sorted(r["arranque_frio"] for r in resultados) == [False, True]


# ----------------------------------------------- deficit exacto al fallar ---

def test_ensure_worker_no_cabe_dice_deficit_exacto(sandbox_s, monkeypatch):
    """El _fallar de 'no cabe' debe decir el DEFICIT exacto en MiB. Con el
    vram_mib=5800 del fix 2026-08-11: libres = 16311 - 14000 = 2311; necesita
    5800 + 512 = 6312; deficit = 4001. Sin victimas vivas el plan es vacio y
    el numero va crudo en el mensaje (accionable sin calculadora)."""
    monkeypatch.setattr(S, "_lanzar", _lanzar_prohibido)
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    monkeypatch.setattr(S, "vram_mib", lambda: (14000, 16311))
    with pytest.raises(S.SummonerError, match=r"no cabe 'worker': faltan 4001 MiB"):
        S.ensure("worker", evictar=False)
