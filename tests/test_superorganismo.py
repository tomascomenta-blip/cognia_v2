# -*- coding: utf-8 -*-
"""Tests del superorganismo (etapa 4 de generar_codigo) — con fakes, sin fleet.

Regresión por lección medida:
- filtra_contradicciones: NEWX4 tenía el mismo input con dos outputs
  esperados distintos -> oráculo imposible por diseño, presupuesto quemado.
- keep-best del solve: nunca devolver código sin `def entry`.
- presupuesto/kill-switch: sin fleet -> None; enabled() lee la env var.
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cognia.agent.superorganismo import (_parse_carto, _run_asserts,
                                         _valida_asserts,
                                         filtra_contradicciones,
                                         superorganismo_enabled,
                                         superorganismo_solve)


# ── filtro determinista de contradicciones (lección NEWX4/SPEC4) ─────────
def test_contradicciones_mismo_input_distinto_output_fuera():
    asserts = [
        "assert f('123') == ['length', 'digit']",
        "assert f('123') == ['sequence']",          # contradice al anterior
        "assert f('abc') == []",
    ]
    out = filtra_contradicciones(asserts)
    assert out == ["assert f('abc') == []"]


def test_contradicciones_duplicado_exacto_se_conserva():
    asserts = ["assert f(1) == 2", "assert f(1) == 2", "assert f(3) == 4"]
    assert filtra_contradicciones(asserts) == asserts


def test_contradicciones_sin_eq_pasan():
    asserts = ["assert es_valido('x')", "assert f(1) == 1"]
    assert filtra_contradicciones(asserts) == asserts


def test_contradicciones_normaliza_espacios():
    asserts = ["assert f( 1 ) == 2", "assert f( 1 )  ==  3"]
    assert filtra_contradicciones(asserts) == []


# ── piezas portadas del harness de eval ──────────────────────────────────
def test_valida_asserts_filtra_no_compilables_y_requiere():
    out = _valida_asserts(
        ["assert calc('1') == 1", "assert calc('1+' == ", "print('no')",
         "assert otra(2) == 2"], requiere="calc")
    assert out == ["assert calc('1') == 1"]


def test_parse_carto_json_valido():
    raw = ('bla {"helpers": [{"name": "h", "signature": "def h(x):", '
           '"contract": "c", "asserts": ["assert h(1) == 1"]}], '
           '"spec_asserts": ["assert f(1) == 1", "assert f(2) == 2"]} bla')
    c = _parse_carto(raw, "f")
    assert c["helpers"][0]["name"] == "h"
    assert len(c["spec_asserts"]) == 2


def test_parse_carto_sin_spec_asserts_es_none():
    assert _parse_carto('{"helpers": [], "spec_asserts": []}', "f") is None
    assert _parse_carto("sin json", "f") is None


def test_parse_carto_salva_json_truncado():
    """Regresión de la causa raíz medida (SPEC3, 2026-07-15): el razonador
    sobre-genera spec_asserts y trunca el JSON a mitad de string; sin
    salvage se perdían los helpers (que venían completos). El salvage los
    recupera + los asserts cerrados (descarta el truncado)."""
    truncado = ('{"helpers": [{"name": "h1", "signature": "def h1(a, b):", '
                '"contract": "c", "asserts": ["assert h1(1, 2) == 3"]}], '
                '"spec_asserts": ["assert f(1) == 1", "assert f(2) == 2", '
                '"assert f(3) == 3", "assert f(4) == 4", "assert f(5) == 5", '
                '"assert f(6) == 6", "assert f(999) == 99')  # <-- cortado
    c = _parse_carto(truncado, "f")
    assert c is not None
    assert len(c["helpers"]) == 1 and c["helpers"][0]["name"] == "h1"
    # 6 asserts cerrados; el 7º truncado se descarta
    assert len(c["spec_asserts"]) == 6
    assert "assert f(999)" not in " ".join(c["spec_asserts"])


def test_parse_carto_truncado_sin_helpers_igual_recupera_asserts():
    truncado = ('{"helpers": [], "spec_asserts": ["assert g(1) == 1", '
                '"assert g(2) == 2", "assert g(3) == 3", "assert g(4')
    c = _parse_carto(truncado, "g")
    assert c is not None and len(c["spec_asserts"]) == 3


def test_run_asserts_cuenta_pases_y_fallos():
    code = "def f(x):\n    return x + 1\n"
    n, fallos = _run_asserts(code, ["assert f(1) == 2", "assert f(1) == 99"])
    assert n == 1
    assert len(fallos) == 1
    assert "assert f(1) == 99" in fallos[0]


# ── kill-switch y fallo blando ───────────────────────────────────────────
def test_enabled_lee_env(monkeypatch):
    monkeypatch.delenv("COGNIA_SUPERORGANISMO", raising=False)
    assert superorganismo_enabled() is False
    monkeypatch.setenv("COGNIA_SUPERORGANISMO", "1")
    assert superorganismo_enabled() is True


def test_solve_sin_fleet_devuelve_none(monkeypatch):
    import node.fleet_registry as fr
    monkeypatch.setattr(fr, "fleet_backend", lambda *_a, **_k: None)
    assert superorganismo_solve("suma dos numeros", "sumar") is None


# ── solve end-to-end con backend fake (sin modelos) ──────────────────────
class _FakeBackend:
    """Devuelve respuestas canned por orden de llamada."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = 0

    def generate(self, prompt, **kw):
        self.llamadas += 1
        if self.respuestas:
            return self.respuestas.pop(0)
        return ""


def test_solve_feliz_con_fakes(monkeypatch):
    """Carto JSON válido (6 asserts: sin refuerzo-coder) -> pieza que pasa
    -> ensamble que pasa todo."""
    import node.fleet_registry as fr
    carto = ('{"helpers": [{"name": "doble", "signature": "def doble(x):", '
             '"contract": "doubles x", "asserts": ["assert doble(2) == 4"]}],'
             ' "spec_asserts": ["assert cuad(2) == 8", '
             '"assert cuad(1) == 2", "assert cuad(0) == 0", '
             '"assert cuad(3) == 18", "assert cuad(4) == 32", '
             '"assert cuad(5) == 50"]}')
    razonador = _FakeBackend([carto])
    coder = _FakeBackend([
        "```python\ndef doble(x):\n    return 2 * x\n```",
        "```python\ndef cuad(x):\n    return doble(x) * x\n```",
    ])
    backends = {"qwen3_4b": razonador, "qwen35_4b": coder}
    monkeypatch.setattr(fr, "fleet_backend", lambda n, **_k: backends.get(n))
    monkeypatch.setattr(fr, "close_fleet_member", lambda *_a, **_k: None)
    r = superorganismo_solve("cuad(x) = 2*x*x", "cuad")
    assert r is not None
    assert r["spec_pass"] == r["spec_total"] == 6
    assert "def cuad" in r["code"] and "def doble" in r["code"]
    assert r["piezas"] == ["doble: 1/1"]


def test_solve_refuerzo_coder_une_asserts(monkeypatch):
    """Oráculo pobre (<6 asserts) -> el coder extrae los suyos y se usa la
    UNIÓN (la clave de NEWX3)."""
    import node.fleet_registry as fr
    carto = ('{"helpers": [], "spec_asserts": ["assert inc(1) == 2", '
             '"assert inc(2) == 3", "assert inc(0) == 1", '
             '"assert inc(9) == 10"]}')
    razonador = _FakeBackend([carto])
    coder = _FakeBackend([
        # respuesta al refuerzo: asserts planos (se unen a los 4 del carto)
        "assert inc(-1) == 0\nassert inc(100) == 101",
        # respuesta al ensamble
        "```python\ndef inc(x):\n    return x + 1\n```",
    ])
    backends = {"qwen3_4b": razonador, "qwen35_4b": coder}
    monkeypatch.setattr(fr, "fleet_backend", lambda n, **_k: backends.get(n))
    monkeypatch.setattr(fr, "close_fleet_member", lambda *_a, **_k: None)
    r = superorganismo_solve("inc(x) = x+1", "inc")
    assert r is not None
    assert r["spec_total"] == 6          # 4 del razonador + 2 del coder
    assert r["spec_pass"] == 6


def test_solve_respeta_presupuesto(monkeypatch):
    """Ensamble que nunca pasa: corta en budget y devuelve el mejor con
    def entry (keep-best), o None si jamás hubo función."""
    import node.fleet_registry as fr
    carto = ('{"helpers": [], "spec_asserts": ["assert g(1) == 1", '
             '"assert g(2) == 2", "assert g(3) == 3", '
             '"assert g(4) == 4"]}')
    razonador = _FakeBackend([carto])
    # el coder siempre devuelve una g() incorrecta -> feromona itera
    coder = _FakeBackend(["```python\ndef g(x):\n    return 0\n```"] * 50)
    backends = {"qwen3_4b": razonador, "qwen35_4b": coder}
    monkeypatch.setattr(fr, "fleet_backend", lambda n, **_k: backends.get(n))
    monkeypatch.setattr(fr, "close_fleet_member", lambda *_a, **_k: None)
    r = superorganismo_solve("g identidad", "g", budget=5)
    assert r is not None and "def g" in r["code"]
    assert r["spec_pass"] == 0
    assert r["gens"] <= 5


def test_carto_no_mata_de_hambre_al_ensamble(monkeypatch):
    """Regresión del smoke e2e (2026-07-15): en CPU lento el carto podía
    consumir todo el timeout y dejar 0 gens de ensamble → None. La reserva
    (carto ≤55% del timeout) garantiza que el ensamble corra. Se simula
    latencia: cada gen del razonador 'tarda' avanzando un reloj falso."""
    import cognia.agent.superorganismo as SO
    import node.fleet_registry as fr

    reloj = {"t": 1000.0}
    monkeypatch.setattr(SO.time, "time", lambda: reloj["t"])

    class _LentoRazonador:
        def generate(self, *a, **k):
            reloj["t"] += 100.0            # cada carto-gen "tarda" 100s
            # nunca da JSON válido -> forzaría los 3 temps + fallback
            return "no json aqui"

    class _Coder:
        def __init__(self):
            self.llamadas = 0
        def generate(self, *a, **k):
            reloj["t"] += 5.0
            self.llamadas += 1
            # 1ª = refuerzo-coder (asserts planos); 2ª+ = ensamble
            if self.llamadas == 1:
                return "assert g(1) == 1\nassert g(2) == 2\nassert g(3) == 3"
            return "```python\ndef g(x):\n    return x\n```"

    coder = _Coder()
    backends = {"qwen3_4b": _LentoRazonador(), "qwen35_4b": coder}
    monkeypatch.setattr(fr, "fleet_backend", lambda n, **_k: backends.get(n))
    monkeypatch.setattr(fr, "close_fleet_member", lambda *_a, **_k: None)
    # timeout 250s con carto-gens de 100s: SIN la reserva, el carto (3 temps +
    # fallback = 400s) excede los 250s y el ensamble (chequea time-t0<=250)
    # nunca corre → None (el bug del smoke). CON la reserva (carto_deadline =
    # 55%×250 = 137s) el carto se corta a 2 gens (~200s... el break ocurre al
    # 3er check) y el ensamble SÍ alcanza a correr.
    r = superorganismo_solve("g identidad", "g", budget=16, timeout_s=250)
    assert r is not None and "def g" in r["code"]
    assert coder.llamadas >= 2             # corrió al menos un ensamble


def test_solve_oraculo_contradictorio_devuelve_none(monkeypatch):
    """Si TODOS los asserts se anulan por contradicción, no hay oráculo ->
    None (sin feromona contra mapa falso; lección NEWX4)."""
    import node.fleet_registry as fr
    carto = ('{"helpers": [], "spec_asserts": ["assert h(1) == 1", '
             '"assert h(1) == 2", "assert h(2) == 3", '
             '"assert h(2) == 4"]}')
    razonador = _FakeBackend([carto])
    coder = _FakeBackend([""] * 5)   # refuerzo-coder no aporta nada
    backends = {"qwen3_4b": razonador, "qwen35_4b": coder}
    monkeypatch.setattr(fr, "fleet_backend", lambda n, **_k: backends.get(n))
    monkeypatch.setattr(fr, "close_fleet_member", lambda *_a, **_k: None)
    assert superorganismo_solve("h", "h") is None
