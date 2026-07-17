# -*- coding: utf-8 -*-
"""Regresion del lote CLI de deuda tecnica 2026-07-16.

- /backup buscaba 'cognia.db' (cwd/~/storage) y NUNCA respaldaba la DB real
  (~/.cognia/cognia_memory.db, config.DB_PATH).
- /feedback nunca alimentaba el learner: cli importaba cognia.feedback.*
  (modulo inexistente) y el except dejaba _feedback_learner=None siempre.
- /debate, /y-si, /cadena-causal, /reflexion-profunda y /argumento eran
  PLANTILLAS enlatadas (cero LLM) vendidas como analisis -> ahora generan
  con el backend real y sin backend degradan con causa honesta.
- /help no existia pero 3 mensajes del propio CLI lo recomendaban.
"""
import io
import contextlib

import cognia.cli as cli


class _FakeInfer:
    text = "ANALISIS GENERADO POR EL MODELO"
    mode = "local"


class _FakeOrch:
    def infer(self, prompt, max_tokens=None, temperature=None):
        return _FakeInfer()


class _FakeAi:
    def __init__(self, con_orch=True):
        if con_orch:
            self._orchestrator = _FakeOrch()


def _out(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args)
    return buf.getvalue()


def test_feedback_learner_cargado():
    assert cli._feedback_learner is not None, (
        "el import de FeedbackLearner volvio a romperse (cognia.adaptive)")


def test_backup_usa_db_real(tmp_path, monkeypatch):
    import cognia.config as config
    fake_db = tmp_path / "cognia_memory.db"
    fake_db.write_bytes(b"sqlite fake")
    monkeypatch.setattr(config, "DB_PATH", str(fake_db))
    out = _out(cli._slash_backup, str(tmp_path / "backups"))
    assert "Backup guardado" in out


def test_debate_usa_llm():
    out = _out(cli._slash_debate, _FakeAi(), "trabajar remoto")
    assert "ANALISIS GENERADO POR EL MODELO" in out
    assert "puede mejorar la eficiencia" not in out  # plantilla vieja muerta


def test_debate_sin_backend_honesto():
    out = _out(cli._slash_debate, _FakeAi(con_orch=False), "trabajar remoto")
    assert "install-model" in out
    assert "A FAVOR" not in out  # nada de analisis inventado


def test_familia_analisis_sin_backend_honesta():
    ai = _FakeAi(con_orch=False)
    for fn in (cli._slash_y_si, cli._slash_cadena_causal,
               cli._slash_reflexion_profunda, cli._slash_argumento):
        out = _out(fn, ai, "tema de prueba")
        assert "install-model" in out, fn.__name__


def test_familia_analisis_con_llm():
    ai = _FakeAi()
    for fn in (cli._slash_y_si, cli._slash_cadena_causal,
               cli._slash_reflexion_profunda, cli._slash_argumento):
        out = _out(fn, ai, "tema de prueba")
        assert "ANALISIS GENERADO POR EL MODELO" in out, fn.__name__


def test_analisis_llm_rechaza_simulation():
    class _SimInfer:
        text = "placeholder"
        mode = "simulation"

    class _SimOrch:
        def infer(self, *a, **kw):
            return _SimInfer()

    class _SimAi:
        _orchestrator = _SimOrch()

    assert cli._analisis_llm(_SimAi(), "x") is None


def test_help_alias_existe():
    """3 mensajes del CLI recomiendan /help; debe despachar como /ayuda."""
    import inspect
    src = inspect.getsource(cli)
    assert 'raw in ("/ayuda", "/help")' in src


def test_cmd_descriptions_sin_duplicados():
    import ast, re
    src = open(cli.__file__, encoding="utf-8").read()
    m = re.search(r"_CMD_DESCRIPTIONS\s*=\s*(\{.*?\n\})", src, re.DOTALL)
    tree = ast.parse(m.group(1), mode="eval")
    keys = [k.value for k in tree.body.keys]
    dup = {k for k in keys if keys.count(k) > 1}
    assert not dup, f"claves duplicadas en _CMD_DESCRIPTIONS: {dup}"


def test_help_text_incluye_comandos_nucleo():
    for cmd in ("/hacer", "/esfuerzo", "/modelo", "/largo", "/pensar",
                "/crear", "/agente estado"):
        assert cmd in cli.HELP_TEXT, f"{cmd} ausente del /ayuda"
