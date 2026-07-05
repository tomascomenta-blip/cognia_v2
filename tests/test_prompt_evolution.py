"""
Tests de cognia/agent/prompt_evolution.py y cognia_v3/eval/bfcl_split.py.

Todo con un backend FALSO (generate inyectado): verifican la MECANICA del
optimizador (scoring, gate de no-regresion, mutaciones, persistencia, split)
sin cargar el 3B. La "verificacion REAL" con el modelo de verdad es una corrida
aparte (cognia_v3/eval/run_prompt_evolution.py).
"""
from __future__ import annotations

import json

import pytest

from cognia.agent import prompt_evolution as pe
from cognia_v3.eval.bfcl_split import load_split


# ── Items sinteticos: 1 funcion 'add(a,b)', ground_truth a=1,b=2 ──────────
def _synth_items(n=4):
    functions = [{
        "name": "add",
        "description": "Add two integers.",
        "parameters": {"type": "object",
                       "properties": {"a": {"type": "integer"},
                                      "b": {"type": "integer"}},
                       "required": ["a", "b"]},
    }]
    gt = [{"add": {"a": [1], "b": [2]}}]
    return [{"id": f"synth_{i}", "category": "simple", "functions": functions,
             "question": "Add 1 and 2.", "ground_truth": gt} for i in range(n)]


def _gen_correct(prompt, **kw):
    return "add(a=1, b=2)"


def _gen_wrong(prompt, **kw):
    return "add(a=9, b=9)"


# fake que MEJORA cuando el system-prompt contiene la regla de strings exactos:
# modela un operador de mutacion que de verdad ayuda (para testear el gate).
def _gen_rule_sensitive(prompt, **kw):
    if pe._RULE_EXACT_STRINGS in prompt:
        return "add(a=1, b=2)"
    return "add(a=9, b=9)"


def test_score_scaffold_perfect_and_zero():
    items = _synth_items(4)
    s = pe.Scaffold(name="t", system_prompt="sys")
    good = pe.score_scaffold(s, items, _gen_correct, repair=False)
    assert good.accuracy == 1.0 and good.n_passed == 4
    bad = pe.score_scaffold(s, items, _gen_wrong, repair=False)
    assert bad.accuracy == 0.0 and bad.error_buckets   # algun bucket de error


def test_token_cost_and_compression_lowers_it():
    from cognia_v3.eval.bench_bfcl_slice import SYSTEM_PROMPT
    s = pe.Scaffold(name="t", system_prompt=SYSTEM_PROMPT)
    shorter = pe.mut_compress_system(s)
    assert shorter is not None
    assert shorter.token_cost() < s.token_cost()   # 'menos detallado' == menos costo


def test_mutation_idempotent_returns_none():
    s = pe.Scaffold(name="t", system_prompt="sys " + pe._RULE_EXACT_STRINGS)
    # la regla ya esta -> no debe duplicar (None = no gastar una eval)
    assert pe.mut_rule_exact_strings(s) is None


def test_propose_targets_dominant_bucket():
    items = _synth_items(3)
    s = pe.seed_scaffold()
    score = pe.score_scaffold(s, items, _gen_wrong, repair=False)
    # el bucket dominante es un value_error -> la 1ra propuesta es la regla de strings
    props = pe.propose_mutations(s, score)
    assert props, "deberia proponer algo"
    tags = [t for t, _ in props]
    assert "rule_exact_strings" in tags


def test_evolve_accepts_improving_mutation():
    items = _synth_items(6)
    seed = pe.seed_scaffold()
    logs = []
    ev = pe.evolve(seed, items, _gen_rule_sensitive, rounds=2, log=logs.append)
    # el seed falla (sin la regla) y una mutacion (la regla de strings) lo arregla
    assert ev.seed_score.accuracy == 0.0
    assert ev.best_score.accuracy == 1.0
    assert pe._RULE_EXACT_STRINGS in ev.best_scaffold.system_prompt
    assert ev.best_scaffold.name != seed.name        # adopto una mutacion


def test_evolve_no_regression_keeps_seed_when_nothing_helps():
    items = _synth_items(6)
    seed = pe.seed_scaffold()
    # generate SIEMPRE correcto -> ninguna mutacion puede subir accuracy (ya 1.0);
    # el gate solo aceptaria Pareto (misma acc, menos costo) = compresion.
    ev = pe.evolve(seed, items, _gen_correct, rounds=2, log=lambda m: None)
    assert ev.best_score.accuracy == 1.0
    # nunca baja de la semilla
    assert ev.best_score.accuracy >= ev.seed_score.accuracy


def test_evolve_pareto_compression_accepted_when_acc_equal():
    items = _synth_items(4)
    seed = pe.seed_scaffold()
    # correcto siempre -> acc queda 1.0; el unico cambio aceptable es reducir costo
    ev = pe.evolve(seed, items, _gen_correct, rounds=3, log=lambda m: None)
    if ev.best_scaffold.name != seed.name:
        # si adopto algo con acc igual, debe ser por costo menor (Pareto)
        assert ev.best_score.token_cost <= ev.seed_score.token_cost


def test_persist_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "STATE_DIR", tmp_path)
    monkeypatch.setattr(pe, "BEST_SCAFFOLD_PATH", tmp_path / "best.json")
    s = pe.Scaffold(name="w", system_prompt="hello", fewshot=[("f", "q", "a")],
                    repair_hint="hint", origin="test")
    pe.persist_best(s, meta={"acc": 0.9})
    loaded = pe.load_best()
    assert loaded is not None
    assert loaded.name == "w" and loaded.system_prompt == "hello"
    assert loaded.fewshot == [("f", "q", "a")] and loaded.repair_hint == "hint"


def test_load_best_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "BEST_SCAFFOLD_PATH", tmp_path / "nope.json")
    assert pe.load_best() is None


def test_split_deterministic_disjoint_covers_all():
    dev, test = load_split()
    dev2, test2 = load_split()
    assert dev == dev2 and test == test2                 # determinista
    ids_dev = {x["id"] for x in dev}
    ids_test = {x["id"] for x in test}
    assert not (ids_dev & ids_test)                      # disjunto
    assert len(ids_dev) + len(ids_test) == 200           # cubre las 200
    assert len(ids_dev) == 40 and len(ids_test) == 160


def test_scaffold_to_from_dict_roundtrip():
    s = pe.seed_scaffold()
    d = s.to_dict()
    back = pe.Scaffold.from_dict(d)
    assert back.system_prompt == s.system_prompt
    assert back.fewshot == s.fewshot
    assert json.loads(json.dumps(d))            # serializable


# ── BootstrapFewShot: cosecha de trazas verificadas ───────────────────────
def test_bootstrap_harvests_only_verified():
    items = _synth_items(4)
    base = pe.seed_scaffold()
    # generate correcto -> los 4 pasan el oraculo -> se cosechan exemplars
    ex = pe.bootstrap_exemplars(base, items, _gen_correct, k=2)
    assert len(ex) == 2
    for funcs, q, ans in ex:
        assert funcs == ""                       # exemplar SOLO-FORMATO (sin schema)
        assert "add(a=1, b=2)" in ans            # la respuesta VERIFICADA


def test_bootstrap_discards_wrong():
    items = _synth_items(4)
    base = pe.seed_scaffold()
    # generate incorrecto -> el oraculo rechaza todo -> nada que cosechar
    ex = pe.bootstrap_exemplars(base, items, _gen_wrong, k=2)
    assert ex == []
    assert pe.make_bootstrapped(base, ex) is None


def test_make_bootstrapped_appends_formatonly_exemplars():
    base = pe.seed_scaffold()
    ex = [("", "Do the thing", "do_thing()")]
    boot = pe.make_bootstrapped(base, ex)
    assert boot is not None
    assert len(boot.fewshot) == len(base.fewshot) + 1
    tf = [{"name": "x", "parameters": {}}]
    base_prompt = pe.build_user_msg(base, tf, "q")
    boot_prompt = pe.build_user_msg(boot, tf, "q")
    assert "Do the thing" in boot_prompt
    # el exemplar SOLO-FORMATO no re-lista un schema -> NO agrega 'Available
    # functions:' respecto al base (solo el bloque Question/Answer, barato).
    assert boot_prompt.count("Available functions:") == base_prompt.count("Available functions:")


def test_minimal_system_is_shorter_and_distinct():
    base = pe.seed_scaffold()
    mn = pe.mut_minimal_system(base)
    assert mn is not None
    assert mn.system_prompt == pe._MINIMAL_SYSTEM
    assert len(mn.system_prompt) < len(base.system_prompt)
    assert pe.mut_minimal_system(mn) is None      # idempotente
