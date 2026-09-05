# -*- coding: utf-8 -*-
"""embeddings.py — Embebedor perezoso para memoria_larga (MiniLM-L6 en CPU).

Reglas (contrato en __init__.py):
- NO carga nada al importar ni al construir: solo en la primera llamada a
  `embeber`, en un hilo con timeout (`COGNIA_MEMORIA_EMBED_TIMEOUT`, 30 s).
- Reusa `cognia.cognia_embedding.LazyEmbeddingModel` (singleton, `device="cpu"`),
  así el modelo se comparte con el resto del CLI y nunca se carga dos veces.
  NO usa la `AsyncEmbeddingQueue` porque su fallback de n-gramas NO es comparable
  con los vectores reales (01_almacenes.md §2): aquí, sin modelo → None.
- Si no carga, falla o vence el timeout → devuelve None, avisa UNA sola vez con
  logging.warning, y `disponible()` queda en False (el retrieval sigue léxico).
- Kill-switch: `COGNIA_MEMORIA_EMBED=0`.
- Vectores normalizados (`normalize_embeddings=True`), lotes de 64.

Medido 2026-09-04 (venv312, Python 3.12.10, CPU, sentence-transformers 5.6.0,
proceso fresco con solo este módulo importado):
- carga fría (1.ª `embeber`, incluye importar torch/transformers + pesos):
  9,3 s; 4,1 s si torch ya estaba importado en el proceso (pytest). El CLI
  completo medía 23,6 s (01_almacenes.md §2) por la contención con el resto
  de imports; por eso el timeout por defecto es 30 s.
- lote de 64 textos de 200 chars: 293-304 ms (3 pasadas tras warm-up)
  → 4,6 ms/texto. Coseno para 130 candidatas sin vector: ~0,6 s la 1.ª vez,
  luego 0 (vectores persistidos en `vectores`).
- RAM del proceso (psutil RSS): 28 MB antes → 32 MB tras importar este
  módulo → 519 MB tras cargar (+491 MB: torch + modelo). Importar no cuesta.
  Se rehace con `tests/test_memoria_larga_embeddings.py::test_modelo_real_medidas -s`.
"""
from __future__ import annotations

import logging
import os
import threading
import time

_log = logging.getLogger(__name__)

ENV_KILL = "COGNIA_MEMORIA_EMBED"
ENV_TIMEOUT = "COGNIA_MEMORIA_EMBED_TIMEOUT"
# Modelo configurable (COGNIA_MEMORIA_EMBED_MODELO): all-MiniLM-L6-v2 es ingles;
# para consultas en espanol el banco compara con paraphrase-multilingual-MiniLM-L12-v2.
MODELO = os.environ.get("COGNIA_MEMORIA_EMBED_MODELO", "all-MiniLM-L6-v2").strip() or "all-MiniLM-L6-v2"
DIM = 384
BATCH = 64


def _activo() -> bool:
    return os.environ.get(ENV_KILL, "1").strip().lower() not in ("0", "no", "off", "false")


def _timeout_s() -> float:
    try:
        return max(1.0, float(os.environ.get(ENV_TIMEOUT, "30")))
    except ValueError:
        _log.warning("memoria_larga.embeddings: %s inválido, uso 30 s", ENV_TIMEOUT)
        return 30.0


def _cargar_modelo():
    """Carga real (corre dentro del hilo). Devuelve el modelo o lanza."""
    try:
        from cognia.cognia_embedding import LazyEmbeddingModel
        modelo = LazyEmbeddingModel.get()
        if modelo is not None:
            return modelo
        raise ImportError("LazyEmbeddingModel devolvió None (sentence-transformers ausente)")
    except ImportError:
        # Sin el módulo de Cognia (o sin ST): último intento directo, siempre CPU.
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(MODELO, device="cpu")


class Embebedor:
    """Vectoriza textos con MiniLM en CPU, cargando el modelo solo la primera vez."""

    def __init__(self, timeout_s: float | None = None, batch_size: int = BATCH):
        self.timeout_s = timeout_s
        self.batch_size = batch_size
        self._modelo = None
        self._intentado = False
        self._avisado = False
        self._lock = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._caja: dict = {}
        self._t0 = 0.0
        self.latencia_carga_s: float | None = None
        self.ultimo_error: str = ""

    # --- estado ---------------------------------------------------------
    def disponible(self) -> bool:
        """True solo si el modelo ya cargó y no está apagado por env."""
        return _activo() and self._modelo is not None

    def _avisar(self, motivo: str) -> None:
        self.ultimo_error = motivo
        if not self._avisado:
            self._avisado = True
            _log.warning("memoria_larga.embeddings degradado a léxico: %s", motivo)

    # --- carga ----------------------------------------------------------
    def precalentar(self) -> None:
        """Arranca la carga en segundo plano SIN esperar (para el arranque del REPL):
        la primera `embeber` solo espera lo que falte. No-op si está apagado."""
        if _activo():
            self._iniciar_carga()

    def _iniciar_carga(self):
        """Lanza el hilo de carga una sola vez y lo devuelve."""
        with self._lock:
            if self._hilo is None:
                self._caja = {}
                self._t0 = time.perf_counter()

                def _hilo():
                    try:
                        self._caja["modelo"] = _cargar_modelo()
                    except Exception as e:  # noqa: BLE001 — se reporta en _asegurar_modelo
                        self._caja["error"] = f"{type(e).__name__}: {e}"

                self._hilo = threading.Thread(target=_hilo, name="memoria_larga-embed-carga", daemon=True)
                self._hilo.start()
            return self._hilo

    def _asegurar_modelo(self):
        if self._modelo is not None:
            return self._modelo
        if self._intentado:
            return None
        h = self._iniciar_carga()
        timeout = self.timeout_s if self.timeout_s is not None else _timeout_s()
        h.join(timeout)
        with self._lock:
            if self._modelo is not None or self._intentado:
                return self._modelo
            self._intentado = True
            if h.is_alive():
                self._avisar(f"el modelo {MODELO} no cargó en {timeout:.1f} s")
                return None
            if "error" in self._caja:
                self._avisar(f"no se pudo cargar {MODELO}: {self._caja['error']}")
                return None
            self._modelo = self._caja.get("modelo")
            self.latencia_carga_s = time.perf_counter() - self._t0
            _log.info("memoria_larga.embeddings: %s cargado en %.1f s", MODELO, self.latencia_carga_s)
            return self._modelo

    # --- API ------------------------------------------------------------
    def embeber(self, textos: list[str]) -> list[list[float]] | None:
        """Vectores normalizados (384 d) para cada texto, o None si no hay modelo."""
        if not _activo():
            return None
        if not textos:
            return []
        modelo = self._asegurar_modelo()
        if modelo is None:
            return None
        try:
            limpios = [(t if isinstance(t, str) and t.strip() else " ") for t in textos]
            vecs = modelo.encode(limpios, batch_size=self.batch_size,
                                 normalize_embeddings=True, convert_to_numpy=True,
                                 show_progress_bar=False)
            return [[float(x) for x in v] for v in vecs]
        except Exception as e:  # noqa: BLE001 — degradación explícita
            self._avisar(f"fallo al embeber ({len(textos)} textos): {type(e).__name__}: {e}")
            return None


_compartido: Embebedor | None = None


def embebedor_compartido() -> Embebedor:
    """Un Embebedor por proceso (el modelo ya es singleton; esto comparte el estado de aviso)."""
    global _compartido
    if _compartido is None:
        _compartido = Embebedor()
    return _compartido


__all__ = ["Embebedor", "embebedor_compartido", "MODELO", "DIM", "BATCH", "ENV_KILL", "ENV_TIMEOUT"]
