"""
cognia/memory/hierarchical.py
=============================
Chimera "Hierarchical Memory" facade (Chimera section 5.2).

This module does NOT reimplement memory mechanics. It UNIFIES the five
existing layers (working / episodic / semantic / forgetting+consolidation)
behind a single object and adds the ONE thing they lacked: a WRITE-GATE
that decides WHETHER an observation deserves to be persisted to long-term
(episodic) storage, instead of blindly storing everything.

Write-gate rationale (Chimera 5.2): biological memory does not persist every
percept. It commits to long-term storage based on (a) SURPRISE — how novel the
observation is versus what is already stored — and (b) IMPORTANCE — how much
the observation matters. We combine the two into a single gate score and only
persist episodic memories that clear the threshold. Working memory always
receives the observation (it is the volatile short-term buffer); the gate only
governs the durable episodic write.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .working import PerceptionModule, WorkingMemory
from .episodic import EpisodicMemory
from .semantic import SemanticMemory
from .forgetting import ForgettingModule, ConsolidationModule
from ..vectors import analyze_emotion
from ..config import DB_PATH


# ── Write-gate tunables ────────────────────────────────────────────────
# WHY: gate score is a convex combination of surprise and importance, both in
# [0,1], so the threshold also lives in [0,1]. 0.45 keeps the gate permissive
# enough that a genuinely novel fact (surprise ~1.0) is stored even when its
# importance is only moderate, while a near-duplicate trivial line (low surprise
# AND low importance) is correctly rejected.
WRITE_GATE_THRESHOLD = 0.45

# WHY: surprise is weighted slightly higher than importance because novelty is
# the cheaper-to-measure, harder-to-fake signal — a brand-new fact carries
# information regardless of how "important" our crude heuristic judges it.
W_SURPRISE = 0.6
W_IMPORTANCE = 0.4


def compute_surprise(vector: list, episodic: "EpisodicMemory", top_k: int = 5) -> float:
    """Surprise = 1 - max similarity to any existing episode.

    An empty or missing DB means everything is novel -> surprise = 1.0.
    Never raises: any backend failure degrades to "treat as novel".
    """
    try:
        results = episodic.retrieve_similar(vector, top_k=top_k)
    except Exception:
        return 1.0
    if not results:
        return 1.0
    # retrieve_similar dicts expose raw cosine under "similarity"
    sims = [float(r.get("similarity", 0.0)) for r in results if isinstance(r, dict)]
    if not sims:
        return 1.0
    max_sim = max(0.0, min(1.0, max(sims)))
    return round(1.0 - max_sim, 4)


# WHY: cheap, language-agnostic (ES+EN) markers that an observation encodes a
# durable decision/preference/goal rather than transient chatter. Substring
# match ("decid" catches decidi/decidir/decided/decision).
_IMPORTANCE_MARKERS = (
    "decid", "import", "clave", "objetivo",
    "never", "always", "recorda", "preferenc",
)


def estimate_importance(observation: str, explicit: Optional[float] = None) -> float:
    """Heuristic importance in [0,1].

    Combines (a) length signal — longer statements tend to carry more content,
    and (b) presence of decision/preference/goal markers. An explicit override,
    when provided, wins outright (clamped to [0,1]).
    """
    if explicit is not None:
        return max(0.0, min(1.0, float(explicit)))

    text = (observation or "").strip()
    if not text:
        return 0.0

    low = text.lower()

    # Length signal: saturates around ~120 chars so a one-word "ok" scores low.
    length_score = min(1.0, len(text) / 120.0)

    # Marker signal: each distinct marker adds weight, capped at 1.0.
    hits = sum(1 for m in _IMPORTANCE_MARKERS if m in low)
    marker_score = min(1.0, hits * 0.4)

    # Markers dominate (they are the strong signal); length is a gentle prior.
    importance = 0.35 * length_score + 0.65 * marker_score
    return round(max(0.0, min(1.0, importance)), 4)


@dataclass
class WriteResult:
    stored_episodic: bool
    in_working: bool
    surprise: float
    importance: float
    gate_score: float
    ep_id: Optional[int]
    reason: str


# WHY: importance forced for a pinned/critical fact. The episodic schema clamps
# stored importance to 3.0 and has no dedicated "pin" column, so we use the max
# importance plus a "pinned" context tag — decay (forgetting.py) scales retention
# by importance, so a 3.0 importance episode is effectively durable.
_PINNED_IMPORTANCE = 3.0
_PINNED_TAG = "pinned"


class HierarchicalMemory:
    """Unified 5-layer memory facade with surprise+importance write-gating."""

    LAYERS = {
        "immediate": "live KV/query context (not persisted here)",
        "working": "volatile short-term buffer (always written)",
        "episodic": "durable experiences, gated by surprise+importance",
        "semantic": "abstracted concepts via consolidation",
        "permanent": "long-term consolidated facts (KG promotion)",
    }

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH

        # WHY: lazily/defensively build each layer. A missing or unreadable DB
        # must never crash construction — read methods already degrade to empty.
        self.perception = PerceptionModule()
        self.working = WorkingMemory()
        self.episodic = self._safe(lambda: EpisodicMemory(self.db_path))
        self.semantic = self._safe(lambda: SemanticMemory(self.db_path))
        self.forgetting = self._safe(lambda: ForgettingModule(self.db_path))
        self.consolidator = self._safe(
            lambda: ConsolidationModule(self.db_path, self.semantic)
        )

    @staticmethod
    def _safe(builder):
        try:
            return builder()
        except Exception:
            return None

    @property
    def layers(self) -> List[str]:
        return list(self.LAYERS.keys())

    def write(self, observation: str, label: Optional[str] = None,
              importance: Optional[float] = None, emotion: Optional[dict] = None,
              pin: bool = False) -> WriteResult:
        """Write an observation through the hierarchy with gating. Never raises."""
        observation = observation if observation is not None else ""
        if label is None:
            # WHY: a compact ASCII label keeps episodic rows queryable/printable.
            label = observation.strip().split("\n")[0][:48] or "obs"

        try:
            vector = self.perception.encode(observation)
        except Exception:
            vector = []

        if emotion is None:
            try:
                emotion = analyze_emotion(observation)
            except Exception:
                emotion = {"score": 0.0, "label": "neutral", "intensity": 0.0}

        # Layer 2: working memory ALWAYS receives the observation.
        in_working = False
        try:
            self.working.add(observation, label, vector, emotion, confidence=0.5)
            in_working = True
        except Exception:
            in_working = False

        # Gate signals.
        surprise = 1.0
        if self.episodic is not None and vector:
            surprise = compute_surprise(vector, self.episodic)

        imp = estimate_importance(observation, explicit=importance)
        if pin:
            imp = 1.0  # pin forces importance high for the gate computation

        gate_score = round(W_SURPRISE * surprise + W_IMPORTANCE * imp, 4)

        stored_episodic = False
        ep_id: Optional[int] = None
        reason = ""

        should_store = pin or gate_score >= WRITE_GATE_THRESHOLD

        if should_store and self.episodic is not None and vector:
            try:
                if pin:
                    ep_id = self.episodic.store(
                        observation, label, vector,
                        confidence=0.5, importance=_PINNED_IMPORTANCE,
                        emotion=emotion, surprise=surprise,
                        context_tags=[_PINNED_TAG],
                    )
                    reason = "pinned: stored with max importance (durable)"
                else:
                    # WHY: scale heuristic importance into episodic's 0..3 range
                    # so a high-importance fact resists decay proportionally.
                    scaled = round(1.0 + 2.0 * imp, 4)
                    ep_id = self.episodic.store(
                        observation, label, vector,
                        confidence=0.5, importance=scaled,
                        emotion=emotion, surprise=surprise,
                    )
                    reason = "above gate"
                stored_episodic = ep_id is not None and ep_id >= 0
                if ep_id is not None and ep_id < 0:
                    reason = "episodic store failed"
            except Exception:
                stored_episodic = False
                reason = "episodic store error"
        elif not should_store:
            reason = "below gate"
        else:
            reason = "no episodic backend"

        return WriteResult(
            stored_episodic=stored_episodic,
            in_working=in_working,
            surprise=surprise,
            importance=imp,
            gate_score=gate_score,
            ep_id=ep_id,
            reason=reason,
        )

    def recall(self, query: str, top_k: int = 5) -> List[str]:
        """Recall short ASCII 'label[score]' strings from episodic + semantic."""
        try:
            vector = self.perception.encode(query)
        except Exception:
            return []

        out: List[str] = []

        if self.episodic is not None:
            try:
                eps = self.episodic.retrieve_similar(vector, top_k=top_k)
                for r in eps:
                    if not isinstance(r, dict):
                        continue
                    lbl = str(r.get("label") or r.get("observation") or "?")[:40]
                    sc = float(r.get("score", r.get("similarity", 0.0)))
                    out.append(_ascii(f"{lbl}[{sc:.2f}]"))
            except Exception:
                pass

        if self.semantic is not None:
            try:
                rels = self.semantic.find_related(vector, top_k=top_k)
                for r in rels:
                    if not isinstance(r, dict):
                        continue
                    lbl = str(r.get("concept") or "?")[:40]
                    sc = float(r.get("similarity", 0.0))
                    out.append(_ascii(f"~{lbl}[{sc:.2f}]"))
            except Exception:
                pass

        return out[: top_k * 2]

    def consolidate(self, user_id: str = "default") -> dict:
        """Run the real consolidation layer(s); return counts. Never raises."""
        result = {"concepts_consolidated": 0, "longterm_facts": 0}
        if self.consolidator is not None:
            try:
                result["concepts_consolidated"] = self.consolidator.consolidate(min_support=2)
            except Exception:
                pass
        try:
            from .long_term_consolidator import LongTermConsolidator
            ltc = LongTermConsolidator(self.db_path)
            result["longterm_facts"] = ltc.consolidate(user_id, min_occurrences=3)
        except Exception:
            pass
        return result

    def decay(self) -> dict:
        """Run the real forgetting decay cycle; return its dict. Never raises."""
        if self.forgetting is None:
            return {"total_checked": 0, "forgotten": 0, "compressed": 0}
        try:
            return self.forgetting.decay_cycle()
        except Exception:
            return {"total_checked": 0, "forgotten": 0, "compressed": 0}

    def stats(self) -> dict:
        """Cheap snapshot: episodic count (if available), working size, layers."""
        ep_count = None
        if self.episodic is not None:
            try:
                ep_count = self.episodic.count()
            except Exception:
                ep_count = None
        try:
            working_size = len(self.working.get_recent(WorkingMemory.CAPACITY))
        except Exception:
            working_size = 0
        return {
            "episodic_count": ep_count,
            "working_buffer": working_size,
            "layers": self.layers,
        }


def _ascii(s: str) -> str:
    # WHY: Windows CP1252 console; strip any non-ASCII so prints never crash.
    return s.encode("ascii", "replace").decode("ascii")


# ── CLI / demo ─────────────────────────────────────────────────────────
def _demo(db_path: Optional[str] = None) -> None:
    mem = HierarchicalMemory(db_path=db_path)
    print("=== Chimera Hierarchical Memory demo ===")
    print("layers: " + ", ".join(mem.layers))
    print("gate threshold=%.2f  w_surprise=%.2f  w_importance=%.2f"
          % (WRITE_GATE_THRESHOLD, W_SURPRISE, W_IMPORTANCE))
    print()

    novel = "Decidi que el proyecto Cognia usara siempre embeddings hash de 256 dimensiones."
    r1 = mem.write(novel, label="decision-embeddings")
    print("[1] NOVEL fact")
    print("    " + _ascii(novel[:70]))
    print("    stored_episodic=%s surprise=%.3f importance=%.3f gate=%.3f reason=%s"
          % (r1.stored_episodic, r1.surprise, r1.importance, r1.gate_score, r1.reason))
    print()

    dup = "Decidi que el proyecto Cognia usara siempre embeddings hash de 256 dimensiones de largo."
    r2 = mem.write(dup, label="decision-embeddings-dup")
    print("[2] NEAR-DUPLICATE")
    print("    " + _ascii(dup[:70]))
    print("    stored_episodic=%s surprise=%.3f importance=%.3f gate=%.3f reason=%s"
          % (r2.stored_episodic, r2.surprise, r2.importance, r2.gate_score, r2.reason))
    print()

    trivial = "ok"
    r3 = mem.write(trivial, label="trivial")
    print("[3] TRIVIAL low-importance line")
    print("    text=%r" % trivial)
    print("    stored_episodic=%s surprise=%.3f importance=%.3f gate=%.3f reason=%s"
          % (r3.stored_episodic, r3.surprise, r3.importance, r3.gate_score, r3.reason))
    print()

    critical = "La clave de API de produccion nunca debe subirse al repositorio."
    r4 = mem.write(critical, label="critical-secret", pin=True)
    print("[4] PINNED critical fact")
    print("    " + _ascii(critical[:70]))
    print("    stored_episodic=%s surprise=%.3f importance=%.3f gate=%.3f reason=%s"
          % (r4.stored_episodic, r4.surprise, r4.importance, r4.gate_score, r4.reason))
    print()

    print("[5] RECALL query='embeddings hash dimensiones'")
    hits = mem.recall("embeddings hash dimensiones", top_k=5)
    if hits:
        for h in hits:
            print("    - " + h)
    else:
        print("    (no hits)")
    print()

    print("[6] STATS")
    s = mem.stats()
    print("    episodic_count=%s working_buffer=%s" % (s["episodic_count"], s["working_buffer"]))
    print("    layers=%s" % ", ".join(s["layers"]))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="cognia.memory.hierarchical",
        description="Chimera hierarchical memory facade (write-gated).",
    )
    parser.add_argument("--db", default=None, help="DB path (default: live cognia DB)")
    sub = parser.add_subparsers(dest="cmd")

    p_w = sub.add_parser("write", help="write an observation")
    p_w.add_argument("text")
    p_w.add_argument("--label", default=None)
    p_w.add_argument("--importance", type=float, default=None)
    p_w.add_argument("--pin", action="store_true")

    p_r = sub.add_parser("recall", help="recall a query")
    p_r.add_argument("query")
    p_r.add_argument("--top-k", type=int, default=5)

    sub.add_parser("stats", help="print stats")
    sub.add_parser("decay", help="run decay cycle")
    p_c = sub.add_parser("consolidate", help="run consolidation")
    p_c.add_argument("--user", default="default")

    args = parser.parse_args()

    if args.cmd is None:
        _demo(db_path=args.db)
        return

    mem = HierarchicalMemory(db_path=args.db)
    if args.cmd == "write":
        r = mem.write(args.text, label=args.label,
                      importance=args.importance, pin=args.pin)
        print("stored_episodic=%s in_working=%s surprise=%.3f importance=%.3f gate=%.3f ep_id=%s reason=%s"
              % (r.stored_episodic, r.in_working, r.surprise, r.importance,
                 r.gate_score, r.ep_id, r.reason))
    elif args.cmd == "recall":
        for h in mem.recall(args.query, top_k=args.top_k):
            print(h)
    elif args.cmd == "stats":
        s = mem.stats()
        print("episodic_count=%s working_buffer=%s layers=%s"
              % (s["episodic_count"], s["working_buffer"], ", ".join(s["layers"])))
    elif args.cmd == "decay":
        print(mem.decay())
    elif args.cmd == "consolidate":
        print(mem.consolidate(args.user))


if __name__ == "__main__":
    main()
