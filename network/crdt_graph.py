"""
network/crdt_graph.py
=====================
CRDT de conocimiento para COGNIA MESH.

Fase 3 — Consistencia eventual sin coordinador central.

TIPO: G-Set (Grow-Only Set) por triple.
GARANTÍA: convergencia eventual — dos nodos con los mismos triples
          producen el mismo estado sin importar el orden de merge.

PRINCIPIO:
  - Un triple agregado NUNCA se elimina (solo se invalida con metadatos).
  - merge(remote) es idempotente: merge(merge(A, B), B) == merge(A, B).
  - Sin coordinador central, sin líder, sin locks distribuidos.

DEPENDENCIAS: solo stdlib (json, time, hashlib) + logger_config existente.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


from logger_config import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════
# TRIPLE CRDT
# ══════════════════════════════════════════════════════════════════════

@dataclass
class CRDTTriple:
    """
    Un triple de conocimiento en el G-Set CRDT.

    Campos
    ------
    subject   : sujeto del triple (puede ser hash anonimizado).
    predicate : predicado / relación.
    object    : objeto del triple.
    node_id   : ID del nodo que originó el triple.
    timestamp : Unix timestamp de creación (float).
    valid     : False = invalidado (soft-delete), nunca se elimina del set.
    triple_id : hash SHA-256 de (subject, predicate, object) — clave única.
    """
    subject:   str
    predicate: str
    object:    str
    node_id:   str
    timestamp: float = field(default_factory=time.time)
    valid:     bool  = True
    triple_id: str   = field(init=False)

    def __post_init__(self):
        self.triple_id = _triple_hash(self.subject, self.predicate, self.object)

    def to_dict(self) -> dict:
        return {
            "triple_id": self.triple_id,
            "subject":   self.subject,
            "predicate": self.predicate,
            "object":    self.object,
            "node_id":   self.node_id,
            "timestamp": self.timestamp,
            "valid":     self.valid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CRDTTriple":
        t = cls(
            subject   = d["subject"],
            predicate = d["predicate"],
            object    = d["object"],
            node_id   = d.get("node_id", "unknown"),
            timestamp = d.get("timestamp", time.time()),
            valid     = d.get("valid", True),
        )
        return t


def _triple_hash(subject: str, predicate: str, obj: str) -> str:
    """Hash SHA-256 determinístico de un triple."""
    raw = f"{subject}|{predicate}|{obj}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ══════════════════════════════════════════════════════════════════════
# CRDT KNOWLEDGE GRAPH
# ══════════════════════════════════════════════════════════════════════

class CRDTKnowledgeGraph:
    """
    G-Set (Grow-Only Set) para conocimiento distribuido en COGNIA MESH.

    Propiedades CRDT
    ----------------
    - Commutativa:  merge(A, B) == merge(B, A)
    - Asociativa:   merge(merge(A, B), C) == merge(A, merge(B, C))
    - Idempotente:  merge(A, A) == A

    Un triple invalidado (valid=False) NO se elimina del set — esto preserva
    la propiedad de convergencia (si se re-recibiera el triple original,
    no revertiría la invalidación).

    Uso
    ---
        g = CRDTKnowledgeGraph(node_id="nodo-local")
        g.add("Python", "es_un", "lenguaje")
        delta = g.get_delta(since_ts=1234567890.0)
        g.merge(remote_delta)
    """

    def __init__(self, node_id: str):
        self.node_id: str = node_id
        # triple_id → CRDTTriple
        self._triples: Dict[str, CRDTTriple] = {}

    # ──────────────────────────────────────────────────────────────────
    # Escritura
    # ──────────────────────────────────────────────────────────────────

    def add(self, subject: str, predicate: str, obj: str) -> CRDTTriple:
        """
        Agrega un triple al G-Set.
        Si ya existe (mismo triple_id), no hace nada (idempotente).
        Retorna el triple (nuevo o existente).
        """
        tid = _triple_hash(subject, predicate, obj)
        if tid in self._triples:
            return self._triples[tid]

        triple = CRDTTriple(
            subject   = subject,
            predicate = predicate,
            object    = obj,
            node_id   = self.node_id,
        )
        self._triples[tid] = triple
        logger.debug(
            "CRDTGraph: triple agregado",
            extra={"op":      "crdt.add",
                   "context": f"id={tid} subj={subject} pred={predicate}"},
        )
        return triple

    def invalidate(self, subject: str, predicate: str, obj: str) -> bool:
        """
        Invalida un triple (soft-delete). NO lo elimina del set.
        Retorna True si existía y fue invalidado, False si no existía.
        """
        tid = _triple_hash(subject, predicate, obj)
        if tid not in self._triples:
            return False
        self._triples[tid].valid = False
        logger.debug(
            "CRDTGraph: triple invalidado",
            extra={"op": "crdt.invalidate", "context": f"id={tid}"},
        )
        return True

    # ──────────────────────────────────────────────────────────────────
    # Merge (núcleo CRDT)
    # ──────────────────────────────────────────────────────────────────

    def merge(self, remote_triples: List[dict]) -> int:
        """
        Unión idempotente con un estado remoto.

        Recibe lista de dicts (serialización de CRDTTriple).
        Regla de merge:
          - Triple nuevo (no existe local) → agregar.
          - Triple existente + remoto inválido → invalidar (valid=False gana).
          - Triple existente + ambos válidos → conservar el más antiguo
            (timestamp menor = fue creado primero).

        Retorna cantidad de triples nuevos integrados.
        """
        new_count = 0
        for d in remote_triples:
            try:
                remote = CRDTTriple.from_dict(d)
                tid    = remote.triple_id

                if tid not in self._triples:
                    # Triple nuevo — agregar directamente
                    self._triples[tid] = remote
                    new_count += 1
                else:
                    local = self._triples[tid]
                    # Invalidación gana siempre (monotónica)
                    if not remote.valid:
                        local.valid = False
                    # Conservar timestamp más antiguo (registro histórico)
                    if remote.timestamp < local.timestamp:
                        local.timestamp = remote.timestamp
                        local.node_id   = remote.node_id

            except Exception as exc:
                logger.warning(
                    "CRDTGraph.merge: triple remoto inválido, ignorando",
                    extra={"op":      "crdt.merge",
                           "context": f"triple={d} err={exc}"},
                )

        logger.debug(
            f"CRDTGraph.merge: {new_count} triples nuevos integrados",
            extra={"op":      "crdt.merge",
                   "context": f"remote={len(remote_triples)} new={new_count} "
                              f"total={len(self._triples)}"},
        )
        return new_count

    # ──────────────────────────────────────────────────────────────────
    # Consulta
    # ──────────────────────────────────────────────────────────────────

    def get_delta(self, since_ts: float = 0.0) -> List[dict]:
        """
        Retorna todos los triples creados/modificados después de since_ts.
        Usado para sincronización incremental con peers.
        Solo incluye triples compartibles (no PRIVATE).
        """
        from network.privacy import classify_triple, can_share, PrivacyLayer
        delta = []
        for t in self._triples.values():
            if t.timestamp >= since_ts:
                try:
                    layer = classify_triple(t.subject, t.predicate, t.object)
                    if can_share(layer):
                        delta.append(t.to_dict())
                except Exception:
                    pass
        return delta

    def get_valid(self) -> List[CRDTTriple]:
        """Retorna todos los triples válidos (no invalidados)."""
        return [t for t in self._triples.values() if t.valid]

    def stats(self) -> dict:
        """Estadísticas del grafo CRDT."""
        total   = len(self._triples)
        valid   = sum(1 for t in self._triples.values() if t.valid)
        by_node: Dict[str, int] = {}
        for t in self._triples.values():
            by_node[t.node_id] = by_node.get(t.node_id, 0) + 1
        return {
            "total":    total,
            "valid":    valid,
            "invalid":  total - valid,
            "by_node":  by_node,
        }

    # ──────────────────────────────────────────────────────────────────
    # Serialización
    # ──────────────────────────────────────────────────────────────────

    def to_json(self) -> str:
        """Serializa el grafo completo a JSON (para persistencia local)."""
        return json.dumps(
            [t.to_dict() for t in self._triples.values()],
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, node_id: str, data: str) -> "CRDTKnowledgeGraph":
        """Reconstruye el grafo desde JSON persistido."""
        g = cls(node_id=node_id)
        try:
            triples = json.loads(data)
            for d in triples:
                t = CRDTTriple.from_dict(d)
                g._triples[t.triple_id] = t
        except Exception as exc:
            logger.warning(
                "CRDTGraph.from_json: error al deserializar",
                extra={"op": "crdt.from_json", "context": f"err={exc}"},
            )
        return g
