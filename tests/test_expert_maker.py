"""
tests/test_expert_maker.py
Tests rapidos del dataset y eval del meta-modelo creador de expertos.
Sin modelos reales ni red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from expert_forge.expert_maker_dataset import (_MODEL_KEYS, build_dataset,
                                               eval_json_validity,
                                               split_dataset)


class TestBuildDataset:
    def test_determinista_por_seed(self):
        a = build_dataset(n=40, seed=7)
        b = build_dataset(n=40, seed=7)
        assert a == b
        c = build_dataset(n=40, seed=8)
        assert a != c

    def test_formato(self):
        for ex in build_dataset(n=30):
            assert ex["prompt"].startswith("Peticion: ")
            assert ex["prompt"].endswith("Spec JSON:")
            spec = json.loads(ex["completion"])
            assert spec["model_key"] in _MODEL_KEYS
            assert spec["backend"] == "gguf"
            assert spec["id"] and " " not in spec["id"]


class TestSplit:
    def test_sin_fuga(self):
        data = build_dataset(n=100)
        train, val = split_dataset(data)
        train_prompts = {d["prompt"] + d["completion"] for d in train}
        for d in val:
            assert (d["prompt"] + d["completion"]) not in train_prompts
        assert len(train) + len(val) == len(data)
        assert len(val) >= 1

    def test_determinista(self):
        data = build_dataset(n=60)
        assert split_dataset(data) == split_dataset(data)


class TestEvalJsonValidity:
    def test_output_bueno(self):
        good = ' {"id":"chef","nombre":"Chef","dedicacion":"cocina","model_key":"chat-7b","backend":"gguf"}'
        assert eval_json_validity([good]) == 1.0

    def test_output_con_texto_alrededor(self):
        wrapped = 'Spec JSON: {"id":"x","nombre":"X","dedicacion":"d","model_key":"coder-14b","backend":"gguf"} gracias'
        assert eval_json_validity([wrapped]) == 1.0

    def test_outputs_rotos(self):
        casos = [
            "no hay json aca",
            '{"id":"x"}',                                   # faltan claves
            '{"id":"x","nombre":"X","dedicacion":"d","model_key":"gpt-4","backend":"gguf"}',  # model_key invalido
            '{"id":"x","nombre":"X","dedicacion":"d","model_key":"chat-7b","backend":',       # truncado
        ]
        assert eval_json_validity(casos) == 0.0

    def test_mezcla(self):
        good = '{"id":"a","nombre":"A","dedicacion":"d","model_key":"chat-7b","backend":"gguf"}'
        assert eval_json_validity([good, "basura"]) == 0.5

    def test_vacio(self):
        assert eval_json_validity([]) == 0.0
