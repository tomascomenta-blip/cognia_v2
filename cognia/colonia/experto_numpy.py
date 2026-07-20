"""
experto_numpy.py — inferencia de micro-expertos en numpy puro, sin torch.

POR QUE NUMPY: el runtime de Cognia no depende de PyTorch (regla del repo:
sin torch en nodos) y su inferencia nativa ya es numpy sobre .npz — los
shards INT4 funcionan asi. Los micro-expertos entran por la misma puerta:
scripts/entrenar_flota.py entrena con torch en venv312gpu y exporta pesos.npz;
aqui se cargan y se corre el forward a mano. Un 0.8M sobre 96 bytes son
matmuls diminutas: <1 ms de CPU.

PARIDAD VERIFICADA, no asumida: cada experto se exporta con paridad_ref.npz
(entradas + logits de torch). verificar_paridad() compara este forward contra
esos logits con tolerancia 1e-4 — es la guardia contra el bug silencioso de
reimplementar mal una capa (pre-LN, mascaras, orden de cabezas...). El test
de regresion la corre siempre.

Replica exactamente nn.TransformerEncoderLayer(norm_first=True, relu):
    x = x + MHA(LN1(x));  x = x + FF(LN2(x))
y el mean-pool ignora el padding, como en el entrenamiento.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

DIR_MICROEXPERTOS = Path(__file__).resolve().parent.parent / "microexpertos"
MAX_LEN = 96


def _ln(x: np.ndarray, w: np.ndarray, b: np.ndarray,
        eps: float = 1e-5) -> np.ndarray:
    mu = x.mean(-1, keepdims=True)
    var = x.var(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * w + b


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


class ExpertoNumpy:
    """Un micro-experto cargado de pesos.npz, listo para opinar en CPU."""

    def __init__(self, nombre: str):
        base = DIR_MICROEXPERTOS / nombre
        cfg = json.loads((base / "config.json").read_text(encoding="utf-8"))
        self.nombre = nombre
        self.clases: list[str] = cfg["clases"]
        self.dim = cfg["dim"]
        self.capas = cfg["capas"]
        self.cabezas = cfg["cabezas"]
        self.p = {k: v for k, v in np.load(base / "pesos.npz").items()}

    # ── el forward, capa a capa ────────────────────────────────────────

    def _atencion(self, x: np.ndarray, capa: int,
                  pad: np.ndarray) -> np.ndarray:
        d, h = self.dim, self.cabezas
        dk = d // h
        pre = f"torso.layers.{capa}.self_attn."
        qkv = x @ self.p[pre + "in_proj_weight"].T + self.p[pre + "in_proj_bias"]
        q, k, v = np.split(qkv, 3, axis=-1)

        def cabezas(t):        # (L, d) -> (h, L, dk)
            return t.reshape(-1, h, dk).transpose(1, 0, 2)

        q, k, v = cabezas(q), cabezas(k), cabezas(v)
        puntajes = q @ k.transpose(0, 2, 1) / np.sqrt(dk)
        # el padding no puede recibir atencion
        puntajes[:, :, pad] = -1e9
        att = _softmax(puntajes) @ v                     # (h, L, dk)
        att = att.transpose(1, 0, 2).reshape(-1, d)       # (L, d)
        return att @ self.p[pre + "out_proj.weight"].T + \
            self.p[pre + "out_proj.bias"]

    def _bloque(self, x: np.ndarray, capa: int,
                pad: np.ndarray) -> np.ndarray:
        pre = f"torso.layers.{capa}."
        # norm_first: x + MHA(LN1(x)) ; x + FF(LN2(x))
        x = x + self._atencion(
            _ln(x, self.p[pre + "norm1.weight"], self.p[pre + "norm1.bias"]),
            capa, pad)
        h = _ln(x, self.p[pre + "norm2.weight"], self.p[pre + "norm2.bias"])
        h = h @ self.p[pre + "linear1.weight"].T + self.p[pre + "linear1.bias"]
        h = np.maximum(h, 0.0)                           # relu
        h = h @ self.p[pre + "linear2.weight"].T + self.p[pre + "linear2.bias"]
        return x + h

    def logits(self, texto: str) -> np.ndarray:
        b = texto.encode("utf-8")[:MAX_LEN]
        ids = np.zeros(MAX_LEN, dtype=np.int64)
        ids[:len(b)] = np.frombuffer(bytes(b), dtype=np.uint8)
        pad = np.ones(MAX_LEN, dtype=bool)
        pad[:len(b)] = False

        x = self.p["emb.weight"][ids] + self.p["pos.weight"][:MAX_LEN]
        for capa in range(self.capas):
            x = self._bloque(x, capa, pad)
        # mean-pool ignorando padding, como en el entrenamiento
        peso = (~pad).astype(np.float32)[:, None]
        pooled = (x * peso).sum(0) / max(peso.sum(), 1.0)
        return pooled @ self.p["cabeza.weight"].T + self.p["cabeza.bias"]

    def opinar(self, texto: str) -> tuple[str, float]:
        """(clase, confianza softmax). Nunca lanza: en error, ('', 0.0)."""
        try:
            lg = self.logits(texto)
            probs = _softmax(lg[None])[0]
            i = int(probs.argmax())
            return self.clases[i], float(probs[i])
        except Exception as e:
            logger.warning("Experto %s no pudo opinar: %s", self.nombre, e)
            return "", 0.0


def verificar_paridad(nombre: str, tolerancia: float = 1e-4) -> float:
    """
    Compara este forward contra los logits de torch guardados al exportar.
    Devuelve la diferencia maxima. Lanza si excede la tolerancia: una
    reimplementacion desviada NO puede entrar en silencio.
    """
    base = DIR_MICROEXPERTOS / nombre
    ref = np.load(base / "paridad_ref.npz")
    exp = ExpertoNumpy(nombre)
    peor = 0.0
    for i in range(len(ref["entradas"])):
        ids = ref["entradas"][i]
        pad = ref["mascaras"][i].astype(bool)
        x = exp.p["emb.weight"][ids] + exp.p["pos.weight"][:MAX_LEN]
        for capa in range(exp.capas):
            x = exp._bloque(x, capa, pad)
        peso = (~pad).astype(np.float32)[:, None]
        pooled = (x * peso).sum(0) / max(peso.sum(), 1.0)
        mios = pooled @ exp.p["cabeza.weight"].T + exp.p["cabeza.bias"]
        peor = max(peor, float(np.abs(mios - ref["logits"][i]).max()))
    if peor > tolerancia:
        raise AssertionError(
            f"paridad de {nombre} rota: diff max {peor:.2e} > {tolerancia}")
    return peor
