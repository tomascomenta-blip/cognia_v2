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
