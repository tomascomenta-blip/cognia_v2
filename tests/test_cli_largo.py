"""
tests/test_cli_largo.py
========================
Tests de /largo (escala + checkpoint incremental + --continuar):

  (a) _parse_largo_flags: parseo de --tokens/--secciones/--tareas/--continuar,
      en cualquier orden, con derivacion de n_tasks en _slash_largo.
  (b) Validacion sana: tope de --tokens, modo plano acotado a GEN_LONG_MAX_TOKENS.
  (c) Escritura incremental: el archivo y el sidecar <archivo>.largo_state.json
      crecen A MEDIDA que llegan rondas/secciones/tareas (no todo al final).
  (d) /largo --continuar: retoma SOLO lo que falta (jerarquico/delegado) o re-ancla
      con la cola del archivo (plano); sidecar ausente/corrupto -> error claro.

Todo con backends FALSOS (FakeImpl de generate()); ningun servidor/modelo real.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

from node.llama_backend import LlamaBackend


# ---------------------------------------------------------------------------
# (a)(b) _parse_largo_flags -- funcion pura
# ---------------------------------------------------------------------------

class TestParseLargoFlags:
    def test_pedido_sin_flags(self):
        import cognia.cli as cli_mod
        out = cli_mod._parse_largo_flags("escribe un poema")
        assert out["pedido"] == "escribe un poema"
        assert not out["jerarquico"] and not out["delegado"]
        assert out["tokens"] is None and out["secciones"] is None and out["tareas"] is None
        assert out["continuar"] is None

    def test_tokens_secciones_en_cualquier_orden(self):
        import cognia.cli as cli_mod
        out = cli_mod._parse_largo_flags(
            "--secciones 4 --jerarquico --tokens 9000 escribe una guia")
        assert out["jerarquico"] is True
        assert out["tokens"] == 9000
        assert out["secciones"] == 4
        assert out["pedido"] == "escribe una guia"

    def test_delegado_con_tareas(self):
        import cognia.cli as cli_mod
        out = cli_mod._parse_largo_flags("--delegado --tareas 6 --tokens 30000 tema X")
        assert out["delegado"] is True
        assert out["tareas"] == 6
        assert out["tokens"] == 30000
        assert out["pedido"] == "tema X"

    def test_continuar_extrae_archivo(self):
        import cognia.cli as cli_mod
        out = cli_mod._parse_largo_flags("--continuar salida.txt")
        assert out["continuar"] == "salida.txt"
        assert out["pedido"] == ""

    def test_valor_no_numerico_se_ignora_sin_consumir_el_resto(self):
        import cognia.cli as cli_mod
        out = cli_mod._parse_largo_flags("--tokens abc escribe algo")
        assert out["tokens"] is None
        # "abc escribe algo" queda como pedido (no se pierde texto)
        assert "escribe algo" in out["pedido"]


# ---------------------------------------------------------------------------
# Helpers comunes
# ---------------------------------------------------------------------------

def _ai_con_llama(llama):
    return types.SimpleNamespace(_orchestrator=types.SimpleNamespace(_llama=llama))


class _SpyLlama:
    """Backend falso que solo REGISTRA con que kwargs lo llamo _slash_largo (para
    probar la derivacion de n_tasks / el clamping de --tokens sin correr generacion
    real seccion por seccion)."""

    def __init__(self):
        self.calls = {}

    def generate_long(self, *a, **kw):
        self.calls["generate_long"] = (a, kw)
        return {"text": "ok", "total_tokens": 10, "stop_reason": "eos", "rounds": 1}

    def generate_hierarchical(self, *a, **kw):
        self.calls["generate_hierarchical"] = (a, kw)
        return {"text": "## s\nok", "outline": ["s"], "sections": 1,
               "total_tokens": 10, "rounds": 1}

    def generate_delegated(self, *a, **kw):
        self.calls["generate_delegated"] = (a, kw)
        return {"text": "## s\nok", "outline": ["s"], "sections": 1,
               "total_tokens": 10, "rounds": 1, "head": ""}


class TestSlashLargoWiring:
    """(b) Validacion + derivacion, con un backend espia (sin generacion real)."""

    def test_delegado_deriva_n_tasks_de_tokens(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        spy = _SpyLlama()
        cli_mod._slash_largo(_ai_con_llama(spy), "--delegado --tokens 12000 mi pedido")
        kw = spy.calls["generate_delegated"][1]
        assert kw["target_tokens"] == 12000
        assert kw["n_tasks"] == 3   # ceil(12000/5000)

    def test_delegado_tareas_explicito_no_se_deriva(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        spy = _SpyLlama()
        cli_mod._slash_largo(_ai_con_llama(spy),
                             "--delegado --tareas 7 --tokens 12000 mi pedido")
        kw = spy.calls["generate_delegated"][1]
        assert kw["n_tasks"] == 7

    def test_delegado_sin_tokens_ni_tareas_no_deriva(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        spy = _SpyLlama()
        cli_mod._slash_largo(_ai_con_llama(spy), "--delegado mi pedido")
        kw = spy.calls["generate_delegated"][1]
        assert kw["n_tasks"] is None   # generate_delegated usa su propio default

    def test_tokens_por_encima_del_tope_absoluto_se_recorta(self, tmp_path, monkeypatch, capsys):
        import cognia.cli as cli_mod
        from shattering.model_constants import GEN_USER_MAX_TOKENS_CAP
        monkeypatch.chdir(tmp_path)
        spy = _SpyLlama()
        cli_mod._slash_largo(_ai_con_llama(spy),
                             f"--delegado --tokens {GEN_USER_MAX_TOKENS_CAP + 50000} x")
        kw = spy.calls["generate_delegated"][1]
        assert kw["target_tokens"] == GEN_USER_MAX_TOKENS_CAP
        assert "supera el tope" in capsys.readouterr().out

    def test_modo_plano_tokens_grande_se_acota_y_avisa(self, tmp_path, monkeypatch, capsys):
        import cognia.cli as cli_mod
        from shattering.model_constants import GEN_LONG_MAX_TOKENS
        monkeypatch.chdir(tmp_path)
        spy = _SpyLlama()
        cli_mod._slash_largo(_ai_con_llama(spy), "--tokens 50000 escribe algo")
        kw = spy.calls["generate_long"][1]
        assert kw["max_total_tokens"] == GEN_LONG_MAX_TOKENS
        out = capsys.readouterr().out
        assert "modo plano esta acotado" in out
        assert "--delegado" in out

    def test_modo_plano_tokens_chico_se_respeta(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        spy = _SpyLlama()
        cli_mod._slash_largo(_ai_con_llama(spy), "--tokens 1500 escribe algo")
        kw = spy.calls["generate_long"][1]
        assert kw["max_total_tokens"] == 1500

    def test_jerarquico_pasa_secciones(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        spy = _SpyLlama()
        cli_mod._slash_largo(_ai_con_llama(spy), "--jerarquico --secciones 8 tema Y")
        kw = spy.calls["generate_hierarchical"][1]
        assert kw["n_sections"] == 8


# ---------------------------------------------------------------------------
# (c) Escritura incremental -- modo PLANO
# ---------------------------------------------------------------------------

class _FakeLongImplSnapshot:
    """Como el _FakeLongImpl de test_llama_backend, pero ademas registra el
    contenido del archivo de salida en el momento de cada llamada a generate()
    -- ANTES de que la ronda actual se appendee -- para probar que la escritura
    en disco ocurre A MEDIDA que llegan las rondas (no toda junta al final)."""

    def __init__(self, rounds, out_path: Path):
        self._rounds = list(rounds)
        self.out_path = out_path
        self.last_tokens_predicted = None
        self.last_stop_reason = None
        self.snapshots: list = []

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
        self.snapshots.append(
            self.out_path.read_text(encoding="utf-8") if self.out_path.exists() else None)
        if not self._rounds:
            return None
        text, toks, reason = self._rounds.pop(0)
        self.last_tokens_predicted = toks
        self.last_stop_reason = reason
        return text


class TestSlashLargoIncrementalPlano:
    def test_archivo_crece_incrementalmente_y_sidecar_refleja_progreso(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "salida.txt"
        monkeypatch.setattr(cli_mod, "_largo_default_path", lambda pedido: out_path)

        impl = _FakeLongImplSnapshot(
            [("Hola ", 50, "limit"), ("mundo.", 30, "eos")], out_path)
        backend = LlamaBackend(impl)

        cli_mod._slash_largo(_ai_con_llama(backend), "escribe algo corto")

        # (1) el archivo final tiene TODO el texto concatenado
        assert out_path.read_text(encoding="utf-8") == "Hola mundo."
        # (2) la 2da ronda vio en disco lo que dejo la 1ra -> escritura incremental
        assert impl.snapshots == ["", "Hola "]

        state_path = tmp_path / "salida.txt.largo_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["mode"] == "plano"
        assert state["stop_reason"] == "eos"
        assert state["total_tokens"] == 80
        assert state["done"] is True   # fin natural (eos) -> COMPLETO


# ---------------------------------------------------------------------------
# (c) Escritura incremental -- modo DELEGADO (outline temprano + head al final)
# ---------------------------------------------------------------------------

class _FakeDelegatedImplSnapshot:
    """Variante de FakeImpl (test_generate_delegated.py) que ademas registra, en
    cada generate(), cuantos done_indices tenia YA el sidecar (proxy de que el
    checkpoint avanza seccion a seccion, no de una sola vez al final)."""

    def __init__(self, out_path: Path, state_holder: dict):
        self.last_tokens_predicted = 10
        self.last_stop_reason = "eos"
        self.out_path = out_path
        self.state_holder = state_holder
        self.done_snapshots: list = []

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
        state_path = self.out_path.with_name(self.out_path.name + ".largo_state.json")
        if state_path.exists():
            st = json.loads(state_path.read_text(encoding="utf-8"))
            self.done_snapshots.append(len(st.get("done_indices", [])))
        else:
            self.done_snapshots.append(None)
        low = prompt.lower()
        if "esquema de exactamente" in low or "numeradas" in low:
            return "1. Introduccion\n2. Desarrollo\n3. Conclusion"
        if "introduccion breve" in low:
            return "Esta es la introduccion unificadora."
        return "Contenido generado para esta seccion con suficiente texto."


class TestSlashLargoIncrementalDelegado:
    def test_outline_temprano_y_done_indices_crecen_por_tarea(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "salida_del.txt"
        monkeypatch.setattr(cli_mod, "_largo_default_path", lambda pedido: out_path)

        impl = _FakeDelegatedImplSnapshot(out_path, {})
        backend = LlamaBackend(impl)

        cli_mod._slash_largo(_ai_con_llama(backend), "--delegado --tareas 3 tema Y")

        # outline (1ra llamada) NO tiene done_indices previos; secciones 2/3/4 ven
        # 0, 1, 2 tareas ya completadas respectivamente; la cabeza (5ta llamada) ve 3.
        assert impl.done_snapshots == [0, 0, 1, 2, 3]

        state = json.loads((tmp_path / "salida_del.txt.largo_state.json").read_text(encoding="utf-8"))
        assert state["outline"] == ["Introduccion", "Desarrollo", "Conclusion"]
        assert state["done_indices"] == [0, 1, 2]
        assert state["completed"] == 3
        assert state["done"] is True

        texto = out_path.read_text(encoding="utf-8")
        assert texto.count("## ") == 4   # 3 secciones + 1 cabeza al final
        assert texto.startswith("## Introduccion")   # append-only: cabeza va AL FINAL
        assert texto.rstrip().endswith("introduccion unificadora.")


# ---------------------------------------------------------------------------
# (d) /largo --continuar
# ---------------------------------------------------------------------------

class _FakeContinuarImpl:
    """Backend falso para --continuar: solo expone generate(); cada llamada devuelve
    el siguiente item de una lista fija (una seccion/tarea faltante por llamada,
    terminando en 'eos' -> 1 sola ronda cada una)."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.last_tokens_predicted = 20
        self.last_stop_reason = "eos"
        self.prompts: list = []

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
        self.prompts.append(prompt)
        if not self._texts:
            return None
        return self._texts.pop(0)


def _write_sidecar(out_path: Path, **overrides):
    state = {
        "mode": "delegado",
        "pedido": "tema Z",
        "target_tokens": None,
        "outline": ["Uno", "Dos", "Tres", "Cuatro"],
        "done_indices": [0, 1],
        "prev_summary": "",
        "completed": 2,
        "total_tokens": 200,
        "stop_reason": "eos",
        "done": False,
        "timestamp": "2026-01-01T00:00:00",
    }
    state.update(overrides)
    state_path = out_path.with_name(out_path.name + ".largo_state.json")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


class TestSlashLargoContinuar:
    def test_continua_solo_las_faltantes_y_appendea(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "parcial.txt"
        out_path.write_text("## Uno\ntexto uno\n\n## Dos\ntexto dos", encoding="utf-8")
        _write_sidecar(out_path)

        impl = _FakeContinuarImpl(["texto tres", "texto cuatro"])
        backend = LlamaBackend(impl)

        cli_mod._slash_largo_continuar(_ai_con_llama(backend), str(out_path))

        # Solo 2 llamadas (las 2 tareas faltantes), NO se regenera el outline
        assert len(impl.prompts) == 2
        assert "Escribe SOLO la seccion 3: Tres" in impl.prompts[0]
        assert "Escribe SOLO la seccion 4: Cuatro" in impl.prompts[1]

        texto = out_path.read_text(encoding="utf-8")
        assert texto == ("## Uno\ntexto uno\n\n## Dos\ntexto dos"
                         "\n\n## Tres\ntexto tres\n\n## Cuatro\ntexto cuatro")

        state = json.loads((tmp_path / "parcial.txt.largo_state.json").read_text(encoding="utf-8"))
        assert state["done_indices"] == [0, 1, 2, 3]
        assert state["done"] is True

    def test_continuar_ya_completo_no_hace_nada(self, tmp_path, monkeypatch, capsys):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "listo.txt"
        out_path.write_text("contenido", encoding="utf-8")
        _write_sidecar(out_path, done=True)

        impl = _FakeContinuarImpl(["no deberia usarse"])
        backend = LlamaBackend(impl)
        cli_mod._slash_largo_continuar(_ai_con_llama(backend), str(out_path))

        assert impl.prompts == []   # no se llamo al backend
        assert "COMPLETO" in capsys.readouterr().out

    def test_continuar_sidecar_ausente_error_claro(self, tmp_path, monkeypatch, capsys):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "sin_sidecar.txt"
        out_path.write_text("contenido", encoding="utf-8")
        # sin escribir el sidecar

        cli_mod._slash_largo_continuar(_ai_con_llama(_SpyLlama()), str(out_path))
        out = capsys.readouterr().out
        assert "checkpoint" in out.lower()

    def test_continuar_sidecar_corrupto_error_claro_sin_excepcion(self, tmp_path, monkeypatch, capsys):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "corrupto.txt"
        out_path.write_text("contenido", encoding="utf-8")
        state_path = tmp_path / "corrupto.txt.largo_state.json"
        state_path.write_text("{esto no es json valido", encoding="utf-8")

        # No debe levantar excepcion
        cli_mod._slash_largo_continuar(_ai_con_llama(_SpyLlama()), str(out_path))
        out = capsys.readouterr().out
        assert "checkpoint" in out.lower()

    def test_continuar_archivo_inexistente_error_claro(self, tmp_path, monkeypatch, capsys):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        cli_mod._slash_largo_continuar(_ai_con_llama(_SpyLlama()), str(tmp_path / "fantasma.txt"))
        out = capsys.readouterr().out
        assert "no existe" in out.lower()

    def test_continuar_jerarquico_no_capa_per_unit_a_gen_long_max_tokens(self, tmp_path, monkeypatch):
        """generate_hierarchical NO capa el presupuesto por seccion a GEN_LONG_MAX_TOKENS
        (a diferencia de delegado, que si lo capa via per_task_cap) -- /largo --continuar
        debe reusar la MISMA formula por modo, no la de delegado para ambos."""
        import cognia.cli as cli_mod
        from shattering.model_constants import GEN_LONG_MAX_TOKENS

        class _SpyGenerateLong:
            def __init__(self):
                self.last_tokens_predicted = 10
                self.last_stop_reason = "eos"
                self.max_tokens_seen = []

            def generate_long(self, prompt, max_total_tokens=None, **kw):
                self.max_tokens_seen.append(max_total_tokens)
                return {"text": "seccion faltante", "total_tokens": 10,
                       "stop_reason": "eos", "rounds": 1}

        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "jer_parcial.txt"
        out_path.write_text("## Uno\ntexto uno", encoding="utf-8")
        _write_sidecar(out_path, mode="jerarquico", outline=["Uno", "Dos"],
                       done_indices=[0], target_tokens=20000, completed=1)

        spy = _SpyGenerateLong()
        cli_mod._slash_largo_continuar(_ai_con_llama(spy), str(out_path))

        # 20000 tokens / 2 secciones = 10000 por seccion, SIN capar a GEN_LONG_MAX_TOKENS
        assert spy.max_tokens_seen == [10000]
        assert 10000 > GEN_LONG_MAX_TOKENS

    def test_continuar_modo_plano_reancla_con_la_cola(self, tmp_path, monkeypatch):
        """Modo plano: re-ancla con los ultimos ~1500 chars del archivo como
        resume_text, y sigue hasta completar target_tokens restante."""
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "plano_parcial.txt"
        out_path.write_text("texto previo ya escrito. ", encoding="utf-8")
        _write_sidecar(out_path, mode="plano", pedido="cuenta una historia",
                      outline=[], done_indices=[], target_tokens=200, total_tokens=100)

        from tests.test_llama_backend import _FakeLongImpl
        impl = _FakeLongImpl([("mas texto nuevo.", 50, "eos")])
        backend = LlamaBackend(impl)

        cli_mod._slash_largo_continuar(_ai_con_llama(backend), str(out_path))

        assert "texto previo ya escrito." in impl.prompts[0][0]
        assert out_path.read_text(encoding="utf-8") == \
            "texto previo ya escrito. mas texto nuevo."
        state = json.loads((tmp_path / "plano_parcial.txt.largo_state.json").read_text(encoding="utf-8"))
        assert state["done"] is True
        assert state["total_tokens"] == 150


# ---------------------------------------------------------------------------
# (e) AUTO-CONTINUAR (D1): cognia encadena sola las continuaciones
# ---------------------------------------------------------------------------

class _FakeLongImplRounds:
    """generate() devuelve tuplas (texto, tokens, stop) en orden; registra
    cuantas veces lo llamaron. Sin snapshots (aca importa el ENCADENADO)."""

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls = 0
        self.last_tokens_predicted = None
        self.last_stop_reason = None

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
        self.calls += 1
        if not self._rounds:
            return None
        text, toks, reason = self._rounds.pop(0)
        self.last_tokens_predicted = toks
        self.last_stop_reason = reason
        return text


def _capture_lines(cli_mod, monkeypatch):
    lines = []
    monkeypatch.setattr(cli_mod, "_print_line", lambda s: lines.append(s))
    return lines


class TestAutoContinuar:
    def test_cortado_encadena_solo_hasta_completar(self, tmp_path, monkeypatch):
        """CORTADO -> auto-continuar corre pasadas hasta que el sidecar queda
        done (fin natural en la continuacion) SIN intervencion del usuario."""
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "salida.txt"
        monkeypatch.setattr(cli_mod, "_largo_default_path", lambda pedido: out_path)
        lines = _capture_lines(cli_mod, monkeypatch)

        # corrida inicial: 2 rondas limit (5200 >= target 5000) -> CORTADO;
        # continuacion: 1 ronda eos -> COMPLETO
        impl = _FakeLongImplRounds([
            ("A" * 40, 2600, "limit"), ("B" * 40, 2600, "limit"),
            ("C" * 40, 500, "eos"),
        ])
        backend = LlamaBackend(impl)
        cli_mod._slash_largo(_ai_con_llama(backend), "escribe algo")

        state = json.loads((tmp_path / "salida.txt.largo_state.json")
                           .read_text(encoding="utf-8"))
        assert state["done"] is True
        contenido = out_path.read_text(encoding="utf-8")
        assert "A" * 40 in contenido and "C" * 40 in contenido
        assert any("auto-continuar" in ln for ln in lines)
        assert any("COMPLETO tras auto-continuar" in ln for ln in lines)

    def test_manual_desactiva_el_encadenado(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "salida.txt"
        monkeypatch.setattr(cli_mod, "_largo_default_path", lambda pedido: out_path)
        lines = _capture_lines(cli_mod, monkeypatch)

        impl = _FakeLongImplRounds([
            ("A" * 40, 2600, "limit"), ("B" * 40, 2600, "limit"),
            ("C" * 40, 500, "eos"),   # NO deberia consumirse
        ])
        backend = LlamaBackend(impl)
        cli_mod._slash_largo(_ai_con_llama(backend), "--manual escribe algo")

        state = json.loads((tmp_path / "salida.txt.largo_state.json")
                           .read_text(encoding="utf-8"))
        assert state["done"] is False           # quedo CORTADO, sin encadenar
        assert impl.calls == 2                  # solo la corrida inicial
        assert not any("auto-continuar" in ln for ln in lines)

    def test_tope_de_pasadas_evita_loop_sin_fin(self, tmp_path, monkeypatch):
        """Modelo que NUNCA cierra (siempre limit): el auto-continuar corta en
        el tope y lo declara INCOMPLETO con el comando manual para seguir."""
        import cognia.cli as cli_mod
        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "salida.txt"
        monkeypatch.setattr(cli_mod, "_largo_default_path", lambda pedido: out_path)
        monkeypatch.setattr(cli_mod, "_LARGO_AUTO_PASADAS", 2)
        lines = _capture_lines(cli_mod, monkeypatch)

        impl = _FakeLongImplRounds([("X" * 20, 2600, "limit")] * 10)
        backend = LlamaBackend(impl)
        cli_mod._slash_largo(_ai_con_llama(backend), "escribe algo")

        state = json.loads((tmp_path / "salida.txt.largo_state.json")
                           .read_text(encoding="utf-8"))
        assert state["done"] is False
        # inicial (2 rondas hasta el target) + 2 pasadas de 1 ronda c/u
        assert impl.calls == 4
        assert any("Sigue INCOMPLETO tras 2 pasadas" in ln for ln in lines)
