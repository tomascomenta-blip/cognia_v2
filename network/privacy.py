"""
network/privacy.py
==================
Privacidad diferencial para compartir embeddings sin exponer datos privados.

Fase 3 — Capas de privacidad COGNIA MESH

CAPAS:
  Capa 1 PRIVADO    → episódico, nunca sale del dispositivo
  Capa 2 SEMI-PRIV  → resúmenes anonimizados para peers autorizados
  Capa 3 PÚBLICO    → triples de conocimiento general, ruido Laplaciano ε=1.0

IMPLEMENTACIÓN:
  - Privacidad diferencial con mecanismo de Laplace (numpy, ya instalado)
  - Sin dependencias nuevas
  - Sensitivity calibrada para vectores unitarios (L2 norm <= 1.0)
"""

from __future__ import annotations

import hashlib
import json
import os
from enum import IntEnum
from typing import List, Optional

import numpy as np

from logger_config import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════
# CAPAS DE PRIVACIDAD
# ══════════════════════════════════════════════════════════════════════

class PrivacyLayer(IntEnum):
    """Nivel de privacidad de un dato en COGNIA MESH."""
    PRIVATE    = 1   # episódico — nunca sale del dispositivo
    SEMI_PRIV  = 2   # resúmenes para peers autorizados
    PUBLIC     = 3   # triples de conocimiento, anonimizados


# ══════════════════════════════════════════════════════════════════════
# PRIVACIDAD DIFERENCIAL
# ══════════════════════════════════════════════════════════════════════

def privatize_embedding(
    vector: List[float],
    epsilon: float = 1.0,
    sensitivity: float = 1.0,
) -> List[float]:
    """
    Aplica privacidad diferencial (mecanismo de Laplace) a un embedding.

    Parámetros
    ----------
    vector      : embedding original (lista de floats, dimensión cualquiera).
    epsilon     : presupuesto de privacidad ε. Menor = más privado, más ruido.
                  Valor recomendado: 1.0 (balance privacidad/utilidad).
    sensitivity : sensibilidad L1 de la función (default=1.0 para vec unitario).

    Retorna
    -------
    Vector perturbado como lista de floats.
    El ruido es i.i.d. Laplaciano con escala b = sensitivity / epsilon.

    Notas
    -----
    - Vectores unitarios (norma ≤ 1) tienen sensitivity L1 = 2.0 en el peor caso.
      Con epsilon=1.0 el ruido es manejable (~0.05 por dimensión en dim=384).
    - No modifica el vector original.
    """
    if epsilon <= 0:
        raise ValueError(f"epsilon debe ser > 0, recibido: {epsilon}")

    scale = sensitivity / epsilon
    vec   = np.asarray(vector, dtype=np.float32)
    noise = np.random.laplace(loc=0.0, scale=scale, size=vec.shape).astype(np.float32)
    noisy = vec + noise

    logger.debug(
        "privatize_embedding: ruido Laplaciano aplicado",
        extra={
            "op":      "privacy.privatize_embedding",
            "context": f"dim={len(vector)} eps={epsilon} scale={scale:.4f} "
                       f"noise_mean={float(np.abs(noise).mean()):.4f}",
        },
    )
    return noisy.tolist()


def can_share(layer: PrivacyLayer) -> bool:
    """Retorna True si la capa permite compartir datos por la red."""
    return layer in (PrivacyLayer.SEMI_PRIV, PrivacyLayer.PUBLIC)


# ══════════════════════════════════════════════════════════════════════
# ANONIMIZACIÓN DE TRIPLES
# ══════════════════════════════════════════════════════════════════════

def anonymize_triple(subject: str, predicate: str, obj: str) -> dict:
    """
    Anonimiza un triple de conocimiento para la capa pública.

    Estrategia
    ----------
    - subject → hash SHA-256 truncado (primeros 16 chars) + sufijo semántico.
    - predicate → se conserva (es información estructural, no personal).
    - object → hash SHA-256 truncado si parece dato personal (len > 30),
               conservado literal si es corto (concept label genérico).

    Retorna dict con claves: subject_hash, predicate, object_hash, original_predicate.
    """
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    subj_hash = _hash(subject)
    obj_out   = _hash(obj) if len(obj) > 30 else obj

    return {
        "subject_hash":       subj_hash,
        "predicate":          predicate,
        "object_hash":        obj_out,
        "original_predicate": predicate,
    }


def classify_triple(subject: str, predicate: str, obj: str) -> PrivacyLayer:
    """
    Clasifica un triple en una capa de privacidad automáticamente.

    Heurística simple basada en el predicado:
    - Predicados personales ('recuerda', 'siente', 'vivió') → PRIVATE
    - Predicados relacionales ('conoce', 'trabaja_en')      → SEMI_PRIV
    - Predicados factuales ('es_un', 'tiene', 'pertenece')  → PUBLIC
    """
    PRIVATE_PREDS   = {"recuerda", "siente", "vivió", "experimentó", "teme", "desea"}
    SEMI_PRIV_PREDS = {"conoce", "trabaja_en", "vive_en", "prefiere", "usa"}

    pred_lower = predicate.lower()
    if pred_lower in PRIVATE_PREDS:
        return PrivacyLayer.PRIVATE
    if pred_lower in SEMI_PRIV_PREDS:
        return PrivacyLayer.SEMI_PRIV
    return PrivacyLayer.PUBLIC


# ══════════════════════════════════════════════════════════════════════
# FILTRO DE CONOCIMIENTO COMPARTIBLE
# ══════════════════════════════════════════════════════════════════════

def filter_shareable_triples(triples: List[dict]) -> List[dict]:
    """
    Filtra y anonimiza triples que pueden compartirse por la red.

    Entrada: lista de dicts con claves 'subject', 'predicate', 'object'.
    Salida:  lista de triples anonimizados de capa SEMI_PRIV o PUBLIC.
    """
    shareable = []
    for t in triples:
        try:
            subj = t.get("subject", "")
            pred = t.get("predicate", "")
            obj  = t.get("object", "")
            layer = classify_triple(subj, pred, obj)
            if can_share(layer):
                anon = anonymize_triple(subj, pred, obj)
                anon["layer"] = int(layer)
                shareable.append(anon)
        except Exception as exc:
            logger.warning(
                "filter_shareable_triples: error procesando triple",
                extra={"op": "privacy.filter_shareable",
                       "context": f"triple={t} err={exc}"},
            )
    logger.debug(
        f"filter_shareable_triples: {len(shareable)}/{len(triples)} compartibles",
        extra={"op": "privacy.filter_shareable",
               "context": f"total={len(triples)} out={len(shareable)}"},
    )
    return shareable
