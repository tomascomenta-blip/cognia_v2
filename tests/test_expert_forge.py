"""
tests/test_expert_forge.py
Tests RAPIDOS para expert_forge/lora_trainer.py: tiny Qwen2 random
(hidden 64, 2 capas, vocab 512) construido en tmp_path, sin bajar el 0.5B.

Tokenizer: WordLevel minimo construido sobre el vocabulario del dataset
sintetico (PreTrainedTokenizerFast). NO se usa el tokenizer del 0.5B aunque
este bajado: su vocab de ~151k produce ids fuera del embedding de 512 del
tiny model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Workaround (mismo patron que el purge de rich en conftest.py): si otro
# modulo de test importo coordinator.app antes, su GlobalRouter dispara en un
# hilo la carga de sentence-transformers DURANTE ese import y 'transformers'
# queda "partially initialized" en sys.modules ("most likely due to a circular
# import") -> aca peft moriria con ImportError: cannot import AutoModel.
# Purgar los modulos envenenados deja que el import arranque limpio.
# NOTA: el conftest pre-importa transformers completo a nivel de sesion; sin
# eso, un test que importe coordinator.app antes que este archivo deja
# 'transformers' partially-initialized y peft muere aca (ver conftest.py).
torch = pytest.importorskip("torch")
pytest.importorskip("peft")
transformers = pytest.importorskip("transformers")

from transformers import (  # noqa: E402
    AutoTokenizer,
    PreTrainedTokenizerFast,
    Qwen2Config,
    Qwen2ForCausalLM,
)

from expert_forge.lora_trainer import (  # noqa: E402
    _adaptive_rank,
    _build_labels,
    _encode_example,
    train_lora,
)


def _dataset_sintetico(n: int = 20) -> list[dict]:
    """n ejemplos {prompt, completion} con vocabulario chico y repetitivo
    para que 30 steps de LoRA alcancen a bajar la loss."""
    return [{"prompt": "pregunta %d :" % i,
             "completion": "respuesta %d fin" % (i % 4)} for i in range(n)]


def _build_tiny_model(tmp_path: Path, dataset: list[dict]) -> str:
    """Tiny Qwen2 random + tokenizer WordLevel del vocab del dataset,
    guardados con save_pretrained en tmp_path/tiny."""
    tokenizers = pytest.importorskip("tokenizers")
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    tiny_dir = tmp_path / "tiny"
    cfg = Qwen2Config(hidden_size=64, num_hidden_layers=2, vocab_size=512,
                      intermediate_size=128, num_attention_heads=4,
                      num_key_value_heads=2, max_position_embeddings=512)
    torch.manual_seed(0)
    model = Qwen2ForCausalLM(cfg)
    model.save_pretrained(str(tiny_dir))

    words: set[str] = set()
    for ex in dataset:
        words |= set((ex["prompt"] + " " + ex["completion"]).split())
    vocab = {"<unk>": 0, "<eos>": 1}
    for w in sorted(words):
        vocab[w] = len(vocab)
    tok = tokenizers.Tokenizer(WordLevel(vocab, unk_token="<unk>"))
    tok.pre_tokenizer = Whitespace()
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="<unk>",
                                   eos_token="<eos>", pad_token="<eos>")
    fast.save_pretrained(str(tiny_dir))
    return str(tiny_dir)


class TestTrainLora:
    def test_loss_baja_y_adapter_guardado(self, tmp_path):
        """(a) 30 steps sobre el tiny -> final_loss < initial_loss y el
        adapter queda en disco como adapter_model.safetensors."""
        dataset = _dataset_sintetico(20)
        tiny_dir = _build_tiny_model(tmp_path, dataset)
        out_dir = tmp_path / "adapter"
        pasos: list[int] = []
        # lr alto (3e-2): LoRA solo toca q/k/v/o_proj y el tiny es random,
        # con el 2e-4 default 30 steps no alcanzan a mover la loss.
        result = train_lora(tiny_dir, dataset, str(out_dir), rank=4,
                            steps=30, lr=3e-2,
                            progress_fn=lambda s, t, l: pasos.append(s))
        assert result["final_loss"] < result["initial_loss"]
        assert result["steps"] == 30
        assert result["adapter_dir"] == str(out_dir)
        assert (out_dir / "adapter_model.safetensors").is_file()
        assert (out_dir / "adapter_config.json").is_file()
        assert pasos == list(range(1, 31))

    def test_rank_explicito_gana_al_adaptativo(self, tmp_path):
        """(b) rank=4 explicito se respeta aunque haya RAM para 8/16,
        y queda escrito en el adapter_config.json."""
        dataset = _dataset_sintetico(6)
        tiny_dir = _build_tiny_model(tmp_path, dataset)
        out_dir = tmp_path / "adapter_r4"
        result = train_lora(tiny_dir, dataset, str(out_dir), rank=4, steps=2)
        assert result["rank"] == 4
        raw = json.loads((out_dir / "adapter_config.json")
                         .read_text(encoding="utf-8"))
        assert raw["r"] == 4
        assert raw["lora_alpha"] == 8          # alpha = 2*rank
        assert sorted(raw["target_modules"]) == ["k_proj", "o_proj",
                                                 "q_proj", "v_proj"]

    def test_rank_adaptativo_por_ram(self, monkeypatch):
        """(b bis) _adaptive_rank mapea RAM disponible -> 16/8/4."""
        import expert_forge.lora_trainer as lt

        class _VM:
            def __init__(self, gb):
                self.available = int(gb * 1024 ** 3)

        for gb, esperado in ((32, 16), (12, 8), (4, 4)):
            monkeypatch.setattr(lt.psutil, "virtual_memory",
                                lambda gb=gb: _VM(gb))
            assert _adaptive_rank() == esperado


class TestMasking:
    def test_labels_prompt_en_menos_100(self):
        """(c) _build_labels: -100 en cada token del prompt, ids reales en
        el completion."""
        labels = _build_labels([11, 12, 13], [44, 45])
        assert labels == [-100, -100, -100, 44, 45]

    def test_encode_example_maskea_prompt_y_agrega_eos(self, tmp_path):
        dataset = _dataset_sintetico(4)
        tiny_dir = _build_tiny_model(tmp_path, dataset)
        tokenizer = AutoTokenizer.from_pretrained(tiny_dir)
        input_ids, labels = _encode_example(
            tokenizer, dataset[0]["prompt"], dataset[0]["completion"], 512)
        n_prompt = len(tokenizer(dataset[0]["prompt"],
                                 add_special_tokens=False)["input_ids"])
        assert labels[:n_prompt] == [-100] * n_prompt
        assert all(l != -100 for l in labels[n_prompt:])
        assert input_ids[-1] == tokenizer.eos_token_id   # EOS del completion
        assert labels[-1] == tokenizer.eos_token_id
        assert len(input_ids) == len(labels)

    def test_encode_example_sin_completion_util_devuelve_none(self, tmp_path):
        """Si seq_len trunca todo el completion, el ejemplo se descarta."""
        dataset = _dataset_sintetico(4)
        tiny_dir = _build_tiny_model(tmp_path, dataset)
        tokenizer = AutoTokenizer.from_pretrained(tiny_dir)
        n_prompt = len(tokenizer(dataset[0]["prompt"],
                                 add_special_tokens=False)["input_ids"])
        assert _encode_example(tokenizer, dataset[0]["prompt"],
                               dataset[0]["completion"], n_prompt) is None
