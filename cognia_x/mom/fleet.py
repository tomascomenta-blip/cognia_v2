"""Flota del MoM — manifest + carga perezosa de expertos (torch CPU, venv312).

El manifest es un JSON con rutas (relativas a la raíz del repo) de tokenizer, checkpoints por
destino ('gen' + dominios) y el selector serializado. Carga perezosa: el generalista se carga
al abrir; cada experto la primera vez que el selector lo pide (97.5M fp32 ≈ 390MB c/u en RAM)."""
import json
from pathlib import Path

import torch

from .model import XHLM
from .selector import Selector

REPO_ROOT = Path(__file__).resolve().parents[2]


class Fleet:
    def __init__(self, manifest_path):
        self.manifest_path = Path(manifest_path)
        m = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.vocab = m["vocab"]
        self.paths = {k: (REPO_ROOT / v) for k, v in m["models"].items()}
        from tokenizers import Tokenizer
        self.tokenizer = Tokenizer.from_file(str(REPO_ROOT / m["tokenizer"]))
        self.selector = Selector.from_dict(m["selector"])
        self._models = {}
        self.eos_id = m.get("eos_id", 0)

    def model(self, name):
        if name not in self._models:
            p = self.paths[name]
            sd = torch.load(p, map_location="cpu")
            mdl = XHLM(self.vocab)
            mdl.load_state_dict({k: v.float() for k, v in sd.items()})
            mdl.eval()
            self._models[name] = mdl
        return self._models[name]

    def route(self, text):
        return self.selector.select(text)

    @torch.no_grad()
    def generate(self, prompt, n_new=150, temperature=0.8, top_p=0.95, force=None):
        """Rutea el prompt, genera con el modelo elegido. → (texto, destino, posterior)."""
        dest, post = (force, self.selector.posterior(prompt)) if force \
            else self.route(prompt)
        mdl = self.model(dest)
        ids = self.tokenizer.encode(prompt).ids
        x = torch.tensor([ids], dtype=torch.long)
        y = mdl.generate(x, n_new, temperature=temperature, top_p=top_p, eos_id=self.eos_id)
        return self.tokenizer.decode(y[0].tolist()), dest, post


def build_manifest(src_dir, out_path, names, tokenizer_rel, vocab=16384,
                   selector=None, eos_id=0):
    """Arma el manifest desde un dir de checkpoints (rutas guardadas relativas al repo)."""
    src = Path(src_dir)
    models = {}
    for dest, fname in names.items():
        p = src / fname
        assert p.exists(), f"falta checkpoint {p}"
        models[dest] = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
    m = {"vocab": vocab, "eos_id": eos_id, "tokenizer": tokenizer_rel,
         "models": models, "selector": selector.to_dict()}
    Path(out_path).write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m
