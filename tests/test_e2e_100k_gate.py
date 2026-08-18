"""
tests/test_e2e_100k_gate.py
===========================
El GATE de escala (scripts/e2e_100k_gate.py) es lo que se corre para la corrida
de 200.000 tokens, asi que sus fallos MUDOS cuestan una noche de GPU. Estas
regresiones fijan lo que tiene que gritar (2026-08-18):

  - el directorio de salida se CREA (OUT.write_text no lo crea: la corrida moria
    con FileNotFoundError despues de planificar el outline);
  - los avisos de generate_delegated (outline corto / worker mudo / cabeza que no
    entra) quedan en el sidecar apenas ocurren, no al final;
  - la introduccion se escribe al FICHERO (antes solo vivia en result['text'] y
    el documento en disco salia sin cabeza aunque la cabeza hubiera respondido);
  - un documento sin introduccion o truncado NO sale con exit 0.

Sin modelo: se sustituye LlamaBackend.try_load por un backend de guion.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
GATE_PY = RAIZ / "scripts" / "e2e_100k_gate.py"


class _BackendGuion:
    """Backend falso: reparte `tokens_por_worker` entre n_tasks y devuelve lo que
    se le pida de cabeza/truncado."""

    def __init__(self, n_secciones, tokens_por_worker, head="Intro tejida.",
                 head_error=None, truncado=None, avisos=()):
        self.n = n_secciones
        self.tpw = tokens_por_worker
        self.head = head
        self.head_error = head_error
        self.truncado = truncado
        self.avisos = list(avisos)

    def generate_delegated(self, prompt, target_tokens=None, n_tasks=None,
                           on_outline=None, on_task=None, on_aviso=None, **kw):
        titulos = [f"Seccion {i + 1}" for i in range(n_tasks)]
        on_outline(titulos)
        for tipo, msg in self.avisos:
            on_aviso(tipo, msg)
        for i in range(self.n):
            on_task(i + 1, n_tasks, titulos[i], self.tpw,
                    f"cuerpo de la seccion {i + 1}", "eos")
        if self.truncado:
            on_aviso("worker", self.truncado)
        if self.head_error:
            on_aviso("cabeza", self.head_error)
        return {"text": "x", "outline": titulos, "sections": self.n,
                "total_tokens": self.tpw * self.n, "rounds": self.n,
                "head": self.head, "head_error": self.head_error,
                "truncado": self.truncado, "plan": {"niveles": 2, "lote": 24}}


def _correr(tmp_path, monkeypatch, backend, target=1000, tasks=10, sub="salida"):
    """Importa el gate FRESCO con su env y lo corre. Devuelve (rc, out, state)."""
    out = tmp_path / sub / "doc.txt"
    monkeypatch.setenv("LARGO_TARGET", str(target))
    monkeypatch.setenv("LARGO_TASKS", str(tasks))
    monkeypatch.setenv("LARGO_OUT", str(out))
    monkeypatch.setenv("LARGO_PROMPT", "Escribe algo largo.")
    from node.llama_backend import LlamaBackend
    monkeypatch.setattr(LlamaBackend, "try_load", staticmethod(lambda *a, **k: backend))

    spec = importlib.util.spec_from_file_location("gate_bajo_prueba", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rc = mod.main()
    state = json.loads(Path(str(out) + ".state.json").read_text(encoding="utf-8"))
    return rc, out, state


class TestGateNoFallaMudo:
    def test_crea_el_directorio_de_salida(self, tmp_path, monkeypatch):
        """El prereg tenia que decir 'mkdir -p salida_200k' a mano; ya no."""
        be = _BackendGuion(10, 100)
        rc, out, _state = _correr(tmp_path, monkeypatch, be, sub="no_existe_aun")
        assert out.is_file()
        assert rc == 0

    def test_la_introduccion_llega_al_fichero(self, tmp_path, monkeypatch):
        be = _BackendGuion(10, 100, head="Intro tejida.")
        rc, out, state = _correr(tmp_path, monkeypatch, be)
        texto = out.read_text(encoding="utf-8")
        assert texto.startswith("Intro tejida.")
        assert "## 1. Seccion 1" in texto
        assert state["head_chars"] == len("Intro tejida.")
        assert rc == 0

    def test_cabeza_fallida_no_sale_con_exit_0(self, tmp_path, monkeypatch):
        """El fallo exacto de ~151 secciones: documento sin introduccion."""
        be = _BackendGuion(10, 100, head="",
                           head_error="la cabeza no respondio (prompt de 15600 "
                                      "tokens contra n_ctx 16384): documento sin "
                                      "introduccion")
        rc, _out, state = _correr(tmp_path, monkeypatch, be)
        assert rc == 1                       # tokens OK pero documento incompleto
        assert state["total_tokens"] == 1000
        assert "documento sin introduccion" in state["head_error"]
        assert [a["tipo"] for a in state["avisos"]] == ["cabeza"]

    def test_truncado_no_sale_con_exit_0(self, tmp_path, monkeypatch):
        be = _BackendGuion(10, 100,
                           truncado="el worker 11 de 10 no respondio: el documento "
                                    "queda con 10 secciones de 10")
        rc, _out, state = _correr(tmp_path, monkeypatch, be)
        assert rc == 1
        assert state["truncado"]
        assert [a["tipo"] for a in state["avisos"]] == ["worker"]

    def test_plan_invalido_corta_antes_de_gastar_la_gpu(self, tmp_path, monkeypatch):
        """generate_delegated devuelve None: el gate lo dice CON el motivo."""

        class _BackendPlanMalo:
            def generate_delegated(self, prompt, on_aviso=None, **kw):
                on_aviso("outline", "esquema incompleto: pedi 144, parsee 55")
                return None

        rc, _out, state = _correr(tmp_path, monkeypatch, _BackendPlanMalo())
        assert rc == 1
        assert state["avisos"][0]["tipo"] == "outline"
        assert "pedi 144, parsee 55" in state["avisos"][0]["mensaje"]
        assert state["done"] == 0            # ni un worker corrido

    def test_pocos_tokens_sigue_siendo_fail(self, tmp_path, monkeypatch):
        be = _BackendGuion(5, 100)           # 500 de 1000 pedidos
        rc, _out, state = _correr(tmp_path, monkeypatch, be)
        assert rc == 1 and state["total_tokens"] == 500

    def test_los_avisos_quedan_en_el_sidecar_apenas_ocurren(self, tmp_path, monkeypatch):
        be = _BackendGuion(10, 100, avisos=[("outline", "aviso temprano")])
        _rc, _out, state = _correr(tmp_path, monkeypatch, be)
        assert state["avisos"][0]["mensaje"] == "aviso temprano"
        assert "t" in state["avisos"][0]
