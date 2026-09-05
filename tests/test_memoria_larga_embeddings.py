# -*- coding: utf-8 -*-
"""Tests del Embebedor perezoso de memoria_larga."""
from __future__ import annotations

import logging
import math
import os
import sys
import time

import pytest

from cognia.memoria_larga import embeddings as E


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_kill_switch_devuelve_none_sin_cargar(monkeypatch):
    monkeypatch.setenv(E.ENV_KILL, "0")
    llamado = []
    monkeypatch.setattr(E, "_cargar_modelo", lambda: llamado.append(1))
    e = E.Embebedor()
    assert e.embeber(["hola"]) is None
    assert e.disponible() is False
    assert llamado == [] and e._intentado is False


def test_fallo_de_carga_avisa_una_vez_y_queda_lexico(monkeypatch, caplog):
    monkeypatch.delenv(E.ENV_KILL, raising=False)

    def rompe():
        raise RuntimeError("sin modelo en disco")
    monkeypatch.setattr(E, "_cargar_modelo", rompe)
    e = E.Embebedor()
    with caplog.at_level(logging.WARNING, logger="cognia.memoria_larga.embeddings"):
        assert e.embeber(["a"]) is None
        assert e.embeber(["b"]) is None
    assert caplog.text.count("degradado a léxico") == 1
    assert e.disponible() is False and "sin modelo en disco" in e.ultimo_error


def test_timeout_de_carga(monkeypatch, caplog):
    monkeypatch.delenv(E.ENV_KILL, raising=False)

    def lento():
        time.sleep(2)
        return object()
    monkeypatch.setattr(E, "_cargar_modelo", lento)
    e = E.Embebedor(timeout_s=0.2)
    with caplog.at_level(logging.WARNING, logger="cognia.memoria_larga.embeddings"):
        assert e.embeber(["a"]) is None
    assert "no cargó" in caplog.text and e.disponible() is False


def test_precalentar_no_bloquea_y_embeber_espera(monkeypatch):
    monkeypatch.delenv(E.ENV_KILL, raising=False)

    class ModeloFalso:
        def encode(self, textos, **kw):
            return [[1.0, 0.0] for _ in textos]

    def lento():
        time.sleep(0.3)
        return ModeloFalso()
    monkeypatch.setattr(E, "_cargar_modelo", lento)
    e = E.Embebedor(timeout_s=5)
    t0 = time.perf_counter()
    e.precalentar()
    assert time.perf_counter() - t0 < 0.2 and e.disponible() is False
    assert e.embeber(["a"]) == [[1.0, 0.0]] and e.disponible()
    assert e.latencia_carga_s is not None and e.latencia_carga_s >= 0.3


def test_kill_switch_no_precalienta(monkeypatch):
    monkeypatch.setenv(E.ENV_KILL, "0")
    monkeypatch.setattr(E, "_cargar_modelo", lambda: (_ for _ in ()).throw(AssertionError("no debía cargar")))
    e = E.Embebedor()
    e.precalentar()
    assert e._hilo is None


def test_lista_vacia_no_carga(monkeypatch):
    monkeypatch.delenv(E.ENV_KILL, raising=False)
    monkeypatch.setattr(E, "_cargar_modelo", lambda: (_ for _ in ()).throw(AssertionError("no debía cargar")))
    assert E.Embebedor().embeber([]) == []


def test_modelo_real_medidas(monkeypatch):
    """Modelo real en CPU: 384 d normalizados, semántica y latencias (con -s se ven)."""
    import importlib.util
    if importlib.util.find_spec("sentence_transformers") is None:  # sin importarlo: la carga fría se mide entera
        pytest.skip("sentence_transformers no instalado")
    monkeypatch.delenv(E.ENV_KILL, raising=False)
    psutil = pytest.importorskip("psutil")
    proc = psutil.Process(os.getpid())
    rss0 = proc.memory_info().rss / 2**20
    e = E.Embebedor(timeout_s=120)
    t0 = time.perf_counter()
    v = e.embeber(["usamos SQLite", "la base de datos es SQLite", "el botón del menú es azul"])
    carga = time.perf_counter() - t0
    assert v is not None and e.disponible(), e.ultimo_error
    assert len(v) == 3 and all(len(x) == 384 for x in v)
    for x in v:
        assert abs(math.sqrt(sum(a * a for a in x)) - 1.0) < 1e-3
    assert _cos(v[0], v[1]) > 0.6
    assert _cos(v[0], v[2]) < 0.4
    rss1 = proc.memory_info().rss / 2**20

    lote = [f"decisión {i}: " + ("la base de datos usa WAL y el pool tiene 4 conexiones; " * 4)[:200 - 14]
            for i in range(64)]
    e.embeber(lote)  # warm-up
    t1 = time.perf_counter()
    out = e.embeber(lote)
    ms_lote = (time.perf_counter() - t1) * 1000
    assert out is not None and len(out) == 64
    print(f"\n[embeddings] carga fría (1.ª llamada, 3 textos): {carga:.1f} s "
          f"(latencia_carga_s={e.latencia_carga_s:.1f}); lote 64x200 chars: {ms_lote:.0f} ms "
          f"= {ms_lote / 64:.2f} ms/texto; RSS {rss0:.0f} MB -> {rss1:.0f} MB "
          f"(+{rss1 - rss0:.0f}); python {sys.version.split()[0]}", flush=True)
