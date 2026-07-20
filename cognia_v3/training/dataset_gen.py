"""
DatasetGenerator: converts Cognia's knowledge graph into QA training pairs.

Sources:
  1. KG triples  → factual QA pairs  (subject/predicate/object → prompt/completion)
  2. Episodes    → QA por label + continuation pairs desde episodic_memory

Run: .\\venv312\\Scripts\\python.exe -m cognia_v3.training.dataset_gen
"""
import json
import random
from dataclasses import dataclass


@dataclass
class TrainingPair:
    prompt: str
    completion: str
    source: str      # "kg_triple" | "episode"
    quality: float   # 0.0–1.0


# predicate → (prompt_template, completion_template)
TRIPLE_TEMPLATES = {
    "is_a":         ("What is a {s}?",                  "A {s} is a type of {o}."),
    "causes":       ("What does {s} cause?",            "{s} causes {o}."),
    "has_property": ("What are the properties of {s}?", "{s} has the property of being {o}."),
    "capable_of":   ("What can a {s} do?",              "A {s} is capable of {o}."),
    "part_of":      ("What is {s} a part of?",          "{s} is a part of {o}."),
    "located_in":   ("Where is {s}?",                   "{s} is located in {o}."),
    "used_for":     ("What is {s} used for?",           "{s} is used for {o}."),
    "opposite_of":  ("What is the opposite of {s}?",    "The opposite of {s} is {o}."),
    "related_to":   ("How are {s} and {o} related?",    "{s} and {o} are related."),
}
DEFAULT_TEMPLATE = ("Tell me about the relationship: {s} {p} {o}.", "{s} {p} {o}.")


class DatasetGenerator:

    def __init__(self, kg=None, db_path: str = "cognia_memory.db"):
        self.kg = kg
        self.db_path = db_path

    # ── Fuentes ─────────────────────────────────────────────────────────

    def _get_triples(self, limit: int) -> list[dict]:
        """Extrae triples del KG. Preferencia: grafo networkx en memoria; fallback: SQLite."""
        triples = []
        if self.kg is not None and hasattr(self.kg, "_get_graph"):
            try:
                g = self.kg._get_graph()
                for s, o, data in list(g.edges(data=True))[:limit]:
                    pred = data.get("relation", data.get("predicate", "related_to"))
                    triples.append({"subject": str(s), "predicate": str(pred), "object": str(o)})
                if triples:
                    return triples
            except Exception as e:
                print(f"[dataset_gen] networkx falló ({e}), fallback a SQLite")
        try:
            # db_connect del core (respeta la regla: nada de sqlite3.connect directo)
            from cognia_v3.core.cognia_v3 import db_connect
            conn = db_connect(self.db_path)
            rows = conn.execute(
                "SELECT subject, predicate, object FROM knowledge_graph "
                "ORDER BY weight DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            triples = [{"subject": r[0], "predicate": r[1], "object": r[2]} for r in rows]
        except Exception as e:
            print(f"WARNING: Could not load triples from any source: {e}")
        return triples

    def _get_episodes(self, limit: int) -> list[dict]:
        try:
            from cognia_v3.core.cognia_v3 import db_connect
            conn = db_connect(self.db_path)
            rows = conn.execute(
                "SELECT observation, label, confidence FROM episodic_memory "
                "WHERE forgotten = 0 ORDER BY importance DESC, confidence DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            return [{"observation": r[0], "label": r[1], "confidence": r[2]} for r in rows]
        except Exception as e:
            print(f"WARNING: Could not load episodes: {e}")
            return []

    # ── Conversión a pares ──────────────────────────────────────────────

    def kg_triples_to_pairs(self, limit: int = 2000) -> list[TrainingPair]:
        pairs = []
        for triple in self._get_triples(limit):
            s = str(triple.get("subject", "")).strip()
            p = str(triple.get("predicate", "related_to")).strip()
            o = str(triple.get("object", "")).strip()
            if not s or not o or len(s) < 2 or len(o) < 2:
                continue
            tpl = TRIPLE_TEMPLATES.get(p, DEFAULT_TEMPLATE)
            try:
                prompt = tpl[0].format(s=s, o=o, p=p)
                completion = tpl[1].format(s=s, o=o, p=p)
            except (KeyError, IndexError):
                prompt = f"What is the relationship between {s} and {o}?"
                completion = f"{s} {p} {o}."
            pairs.append(TrainingPair(prompt=prompt, completion=completion,
                                      source="kg_triple", quality=0.8))
        return pairs

    def episodes_to_pairs(self, limit: int = 500) -> list[TrainingPair]:
        pairs = []
        for ep in self._get_episodes(limit):
            text = str(ep.get("observation", "")).strip()
            label = str(ep.get("label", "") or "").strip()
            conf = float(ep.get("confidence", 0.5) or 0.5)
            if len(text) < 40:
                continue
            if label and not label.startswith("archivo:"):
                # par QA anclado al label aprendido
                pairs.append(TrainingPair(
                    prompt=f"What do you know about {label.replace('_', ' ')}?",
                    completion=text[:400], source="episode",
                    quality=min(0.9, 0.4 + conf * 0.5)))
            else:
                mid = len(text) // 2
                completion = text[mid:]
                if len(completion) > 10:
                    pairs.append(TrainingPair(
                        prompt=f"Continue the following: {text[:mid]}",
                        completion=completion, source="episode", quality=0.6))
        return pairs

    def generate_all(self, kg_limit: int = 2000, episode_limit: int = 500) -> list[TrainingPair]:
        pairs = self.kg_triples_to_pairs(kg_limit) + self.episodes_to_pairs(episode_limit)
        pairs = [p for p in pairs if p.quality >= 0.5]
        random.shuffle(pairs)
        kg_count = sum(1 for p in pairs if p.source == "kg_triple")
        print(f"Generated {len(pairs)} training pairs: {kg_count} from KG, "
              f"{len(pairs) - kg_count} from episodes")
        return pairs

    def save_jsonl(self, pairs: list[TrainingPair], path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps({"prompt": p.prompt, "completion": p.completion,
                                    "source": p.source}, ensure_ascii=False) + "\n")
        print(f"Saved {len(pairs)} pairs -> {path}")


if __name__ == "__main__":
    # Smoke con KG mock + dataset real desde cognia_memory.db
    import networkx as nx

    class MockKG:
        def __init__(self):
            self._g = nx.DiGraph()
            self._g.add_edge("dog", "mammal", relation="is_a")
            self._g.add_edge("rain", "flood", relation="causes")
            self._g.add_edge("python", "programming language", relation="is_a")
            self._g.add_edge("hammer", "nail", relation="used_for")

        def _get_graph(self):
            return self._g

    gen = DatasetGenerator(MockKG())
    pairs = gen.kg_triples_to_pairs()
    gen.save_jsonl(pairs, "cognia_v3/training/test_dataset.jsonl")
    print("Sample pair:")
    print(f"  Prompt:     {pairs[0].prompt}")
    print(f"  Completion: {pairs[0].completion}")

    print("\n--- Dataset real desde cognia_memory.db ---")
    real = DatasetGenerator()  # sin KG en memoria: lee SQLite directamente
    real_pairs = real.generate_all(kg_limit=3000, episode_limit=500)
    if real_pairs:
        real.save_jsonl(real_pairs, "cognia_v3/training/cognia_dataset.jsonl")
