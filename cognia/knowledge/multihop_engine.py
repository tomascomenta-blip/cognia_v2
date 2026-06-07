"""
cognia/knowledge/multihop_engine.py
=====================================
Multi-hop reasoning engine over the Knowledge Graph.
Chains facts through relations to answer complex questions.

MAX_HOPS = 3 — never allows infinite chains.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

MAX_HOPS = 3


class MultiHopEngine:
    """
    Razonamiento multi-hop sobre el Knowledge Graph.
    Encadena hechos a través de relaciones para responder preguntas complejas.
    """

    def __init__(self):
        from cognia.knowledge.graph import KnowledgeGraph
        self._kg = KnowledgeGraph()

    # ── Internal helpers ──────────────────────────────────────────────

    def _get_outgoing(self, concept: str) -> list[dict]:
        """Return all triples where concept is the subject."""
        return self._kg.get_neighbors(concept)

    def _get_isa_chain(self, concept: str, max_depth: int = MAX_HOPS) -> list[str]:
        """Walk is_a chain upward; returns ordered list of ancestors."""
        return self._kg.get_ancestors(concept, max_depth=max_depth)

    # ── Public API ────────────────────────────────────────────────────

    def find_path(self, source: str, target: str, max_hops: int = MAX_HOPS) -> list[list]:
        """
        BFS to find the shortest path between source and target.
        Returns list of (subject, predicate, object) tuples that connect them.
        Returns [] if no path exists within max_hops or source == target.

        max_hops is capped to MAX_HOPS to prevent runaway traversal.
        """
        if max_hops <= 0:
            return []
        max_hops = min(max_hops, MAX_HOPS)
        source = source.lower().strip()
        target = target.lower().strip()
        if source == target:
            return []

        # BFS: each queue entry = (current_concept, path_so_far)
        # path_so_far is a list of (subject, predicate, object) triples
        queue: deque = deque()
        queue.append((source, []))
        visited: set = {source}

        while queue:
            current, path = queue.popleft()
            if len(path) >= max_hops:
                continue

            neighbors = self._kg.get_neighbors(current)
            for nb in neighbors:
                next_concept = nb["concept"]
                relation = nb.get("relation", "related_to")
                new_path = path + [(current, relation, next_concept)]
                if next_concept == target:
                    return new_path
                if next_concept not in visited:
                    visited.add(next_concept)
                    queue.append((next_concept, new_path))

        return []

    def infer_properties(self, concept: str, depth: int = 2) -> dict:
        """
        Infers all properties of a concept through is_a chains.

        Returns:
          {
            "concept": str,
            "direct_facts": list[dict],    # direct non-is_a facts
            "inherited_facts": list[dict], # facts from is_a parents
            "parent_chain": list[str],     # ordered ancestor chain
            "total_facts": int
          }
        """
        depth = min(depth, MAX_HOPS)
        concept_lower = concept.lower().strip()

        # Direct facts (non-is_a relations where concept is subject)
        raw_direct = self._kg.get_neighbors(concept_lower)
        direct_facts = [
            {"subject": concept_lower, "predicate": nb["relation"], "object": nb["concept"]}
            for nb in raw_direct
            if nb.get("relation") != "is_a"
        ]

        # Parent chain via is_a
        parent_chain = self._get_isa_chain(concept_lower, max_depth=depth)

        # Inherited: facts from each ancestor (non-is_a, deduplicated)
        inherited_facts: list[dict] = []
        seen: set = set()
        for parent in parent_chain:
            for nb in self._kg.get_neighbors(parent):
                if nb.get("relation") == "is_a":
                    continue
                key = (parent, nb.get("relation"), nb["concept"])
                if key not in seen:
                    seen.add(key)
                    inherited_facts.append({
                        "subject": parent,
                        "predicate": nb.get("relation", "related_to"),
                        "object": nb["concept"],
                        "inherited_by": concept_lower,
                    })

        return {
            "concept": concept_lower,
            "direct_facts": direct_facts,
            "inherited_facts": inherited_facts,
            "parent_chain": parent_chain,
            "total_facts": len(direct_facts) + len(inherited_facts),
        }

    def find_common_ancestors(self, concept_a: str, concept_b: str) -> list[str]:
        """
        Finds shared ancestors in the is_a chain.
        Useful for answering "what do X and Y have in common?"
        Returns a list of common ancestor concept strings (may be empty).
        """
        a_ancestors = set(self._get_isa_chain(concept_a.lower().strip(), max_depth=MAX_HOPS))
        b_ancestors = set(self._get_isa_chain(concept_b.lower().strip(), max_depth=MAX_HOPS))
        return sorted(a_ancestors & b_ancestors)

    def explain_relationship(self, concept_a: str, concept_b: str) -> dict:
        """
        Explains how two concepts are related.

        Returns:
          {
            "direct_path": list,
            "common_ancestors": list[str],
            "relationship_type": str,  # "direct", "inherited", "sibling", "unrelated"
            "explanation": str
          }
        """
        a = concept_a.lower().strip()
        b = concept_b.lower().strip()

        direct_path = self.find_path(a, b)
        common_ancestors = self.find_common_ancestors(a, b)

        if direct_path:
            rel_type = "direct"
            hops = len(direct_path)
            chain = " -> ".join(
                f"{s} --[{p}]--> {o}" for s, p, o in direct_path
            )
            explanation = f"{a} and {b} are directly connected in {hops} hop(s): {chain}"
        elif common_ancestors:
            # Check if one is ancestor of the other (inherited) vs sibling
            a_ancestors = set(self._get_isa_chain(a, max_depth=MAX_HOPS))
            b_ancestors = set(self._get_isa_chain(b, max_depth=MAX_HOPS))
            if b in a_ancestors:
                rel_type = "inherited"
                explanation = f"{a} inherits from {b} via is_a chain"
            elif a in b_ancestors:
                rel_type = "inherited"
                explanation = f"{b} inherits from {a} via is_a chain"
            else:
                rel_type = "sibling"
                explanation = (
                    f"{a} and {b} share common ancestor(s): "
                    + ", ".join(common_ancestors)
                )
        else:
            rel_type = "unrelated"
            explanation = f"No known relationship found between {a} and {b} within {MAX_HOPS} hops"

        return {
            "direct_path": direct_path,
            "common_ancestors": common_ancestors,
            "relationship_type": rel_type,
            "explanation": explanation,
        }

    def answer_question(self, question: str) -> dict:
        """
        Attempts to answer a question using the KG via multi-hop lookup.

        Extracts tokens >= 4 chars, queries infer_properties() for each,
        builds a natural-language answer from collected facts.

        Returns:
          {
            "question": str,
            "entities_found": list[str],
            "facts": list[dict],
            "confidence": float,
            "answer_text": str
          }
        """
        import re

        # Stopwords to skip during entity extraction
        _SKIP = {
            "what", "that", "this", "which", "when", "where", "does", "have",
            "from", "with", "about", "como", "para", "qué", "cuál", "cuáles",
            "tiene", "tiene", "cómo", "dónde", "quién", "cuándo", "entre",
        }

        tokens = re.findall(r'[a-záéíóúñüA-ZÁÉÍÓÚÑÜ]{4,}', question)
        entities = [t.lower() for t in tokens if t.lower() not in _SKIP]
        # Deduplicate while preserving order
        seen_e: set = set()
        unique_entities: list[str] = []
        for e in entities:
            if e not in seen_e:
                seen_e.add(e)
                unique_entities.append(e)

        all_facts: list[dict] = []
        entities_found: list[str] = []

        for entity in unique_entities:
            props = self.infer_properties(entity, depth=2)
            if props["total_facts"] > 0:
                entities_found.append(entity)
                all_facts.extend(props["direct_facts"])
                all_facts.extend(props["inherited_facts"])

        # Build natural-language answer
        if not all_facts:
            answer_text = "No relevant facts found in the knowledge graph for this question."
        else:
            lines: list[str] = []
            for f in all_facts[:10]:
                subj = f.get("subject", "")
                pred = f.get("predicate", "").replace("_", " ")
                obj = f.get("object", "")
                if f.get("inherited_by"):
                    lines.append(f"{subj} {pred} {obj} (inherited by {f['inherited_by']})")
                else:
                    lines.append(f"{subj} {pred} {obj}")
            answer_text = "Based on the knowledge graph: " + "; ".join(lines) + "."

        confidence = min(1.0, len(all_facts) * 0.1)

        return {
            "question": question,
            "entities_found": entities_found,
            "facts": all_facts,
            "confidence": confidence,
            "answer_text": answer_text,
        }
