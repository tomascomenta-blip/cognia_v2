"""
cognia/context/band_router.py
=============================
HYDRA-analogue: a dynamic 3-band CONTEXT/MEMORY router.

This is a SYSTEM-LEVEL analogue of HYDRA's per-token band routing. It does
NOT touch model attention or weights (the model is pre-quantized INT4 and
pre-sharded). Instead it routes *context assembly* across three memory bands,
deciding per-query which bands to activate and what to retrieve from each:

  LOCAL  -- immediate context: current query + recent working-memory buffer.
            Always active, cheap, high fidelity.
  MEDIA  -- compressed/summarized memory: working-memory context labels and,
            when available, a summary/compressor layer.
  GLOBAL -- episodic + semantic retrieval by vector similarity. Active only
            when the query needs long-range recall.

It is built ON TOP OF the existing LOGOS/TECHNE/RHETOR semantic router
(shattering.router.GlobalRouter), which it reuses rather than duplicates, to
pick the persona/temperature. The band-activation logic is a thin, readable
heuristic layer on top of the real memory classes.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional


# -- Band-activation heuristics (module-level constants) -------------------
# Exposed so the WHY behind each gate is inspectable / tunable in one place.

# MEDIA: a query is "long/multi-part" enough to benefit from compressed
# context once it crosses this many words.
MEDIA_LONG_QUERY_WORDS = 12

# GLOBAL: recall cues (Spanish + English) that signal the query references
# prior knowledge or a past interaction, i.e. long-range recall is needed.
GLOBAL_RECALL_CUES = [
    # Spanish
    "recuerda", "recordas", "recordas", "recuerdas", "antes", "la vez",
    "mencion", "dijiste", "habiamos", "habiamos hablado", "ya habiamos",
    "quien es", "que es", "define", "anteriormente",
    # English
    "earlier", "previously", "remember", "what did", "you said",
    "you mentioned", "before", "last time",
]

# MEDIA: clause-joining tokens that indicate multiple bundled requests.
_MEDIA_CLAUSE_JOINERS = [";", " y ", " and "]

# Persona -> default sampling temperature. RouteDecision carries no
# temperature field (verified against shattering/router.py), so we derive a
# documented default per persona: TECHNE deterministic, RHETOR creative.
_PERSONA_TEMPERATURE = {
    "techne": 0.2,   # code wants determinism
    "logos": 0.5,    # reasoning wants balance
    "rhetor": 0.85,  # prose wants creativity
}
_DEFAULT_TEMPERATURE = 0.5


@dataclass
class BandResult:
    name: str
    active: bool
    score: float
    items: List[str] = field(default_factory=list)


@dataclass
class HydraRouting:
    query: str
    persona: str
    temperature: float
    persona_confidence: float
    bands: List[BandResult]
    assembled_context: str


def _clean(text: str, max_len: int = 120) -> str:
    """Collapse whitespace and force ASCII so Windows CP1252 stdout is safe."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


class HydraContextRouter:
    """
    3-band context/memory router on top of the LOGOS/TECHNE/RHETOR router.

    Construction is defensive: every external layer (router, working memory,
    episodic, semantic, perception) is wired lazily and wrapped so a missing
    or empty DB never raises -- a failed layer simply yields an inactive /
    empty band.
    """

    def __init__(self, db_path: Optional[str] = None):
        # Default db_path matches what the memory classes use (cognia.config.DB_PATH)
        # so the router points at the real store unless overridden.
        if db_path is None:
            try:
                from cognia.config import DB_PATH
                db_path = DB_PATH
            except Exception:
                db_path = None
        self.db_path = db_path

        # -- Semantic persona router (reused, never duplicated) -------------
        self._router = None
        try:
            from shattering.router import GlobalRouter
            self._router = GlobalRouter()
        except Exception:
            self._router = None

        # -- Perception (string -> vector) ---------------------------------
        self._perception = None
        try:
            from cognia.memory.working import PerceptionModule
            self._perception = PerceptionModule()
        except Exception:
            self._perception = None

        # -- Working memory (in-process buffer; no DB) ---------------------
        self._working = None
        try:
            from cognia.memory.working import WorkingMemory
            self._working = WorkingMemory()
        except Exception:
            self._working = None

        # -- Episodic memory (DB-backed; tolerate empty/missing DB) ---------
        self._episodic = None
        try:
            from cognia.memory.episodic import EpisodicMemory
            self._episodic = (
                EpisodicMemory(self.db_path) if self.db_path
                else EpisodicMemory()
            )
        except Exception:
            self._episodic = None

        # -- Semantic memory (DB-backed; tolerate empty/missing DB) ---------
        self._semantic = None
        try:
            from cognia.memory.semantic import SemanticMemory
            self._semantic = (
                SemanticMemory(self.db_path) if self.db_path
                else SemanticMemory()
            )
        except Exception:
            self._semantic = None

        # -- Summarizer (deterministic extractive compressor for MEDIA) -----
        # WHY: MEDIA is the "compressed/summarized" band per the whitepaper, so
        # it must emit a real summary -- not just labels. Built lazily and
        # defensively so a missing dep never breaks construction.
        self._summarizer = None
        try:
            from cognia.summarizer.session_summarizer import SessionSummarizer
            self._summarizer = SessionSummarizer()
        except Exception:
            self._summarizer = None

    # -- Persona ----------------------------------------------------------

    def _route_persona(self, query: str):
        """Return (persona, temperature, confidence) from the real router."""
        if self._router is None:
            return "logos", _DEFAULT_TEMPERATURE, 0.3
        try:
            decision = self._router.route(query)
            persona = decision.sub_model
            conf = float(decision.confidence)
            temp = _PERSONA_TEMPERATURE.get(persona, _DEFAULT_TEMPERATURE)
            return persona, temp, conf
        except Exception:
            return "logos", _DEFAULT_TEMPERATURE, 0.3

    # -- Band scoring -----------------------------------------------------

    def _score_local(self, query: str) -> float:
        # WHY 1.0: immediate context is always the cheapest, highest-fidelity
        # signal -- there is no scenario where we would not want it.
        return 1.0

    def _score_media(self, query: str) -> float:
        # WHY: compressed/summarized memory pays off when the query is long,
        # bundles several requests, or there is already buffered context to
        # summarize. Each independent piece of evidence raises the score.
        words = query.split()
        evidence = 0.0
        if len(words) >= MEDIA_LONG_QUERY_WORDS:
            evidence += 0.5
        low = " " + query.lower() + " "
        if any(j in low for j in _MEDIA_CLAUSE_JOINERS):
            evidence += 0.3
        if self._working is not None:
            try:
                if self._working.get_recent(n=1):
                    evidence += 0.3
            except Exception:
                pass
        return min(1.0, evidence)

    def _score_global(self, query: str, persona: str) -> float:
        # WHY: long-range retrieval is only worth its cost when the query
        # actually reaches back -- explicit recall cues, or a LOGOS-style
        # knowledge question (persona=="logos" with a "?"). Score scales with
        # how many distinct cues fire so a single weak cue is not over-weighted.
        low = query.lower()
        cue_hits = sum(1 for cue in GLOBAL_RECALL_CUES if cue in low)
        score = min(1.0, 0.45 + 0.2 * cue_hits) if cue_hits else 0.0
        if persona == "logos" and "?" in query:
            score = max(score, 0.5)
        return round(score, 3)

    # -- Band retrieval ---------------------------------------------------

    def _retrieve_local(self, query: str) -> List[str]:
        items: List[str] = []
        if self._working is not None:
            try:
                for entry in self._working.get_recent(n=3):
                    label = entry.get("label") or ""
                    obs = entry.get("observation") or ""
                    snippet = label or obs
                    if snippet:
                        items.append(_clean(snippet))
            except Exception:
                pass
        items.append("query: " + _clean(query))
        return items

    def _retrieve_media(self, query: str) -> List[str]:
        items: List[str] = []
        if self._working is not None:
            try:
                labels = self._working.get_context_labels()
                items.extend(_clean(lbl) for lbl in labels if lbl)
            except Exception:
                pass
        # MEDIA is the compressed/summarized band: in ADDITION to the labels,
        # build a real extractive summary from recent working-memory turns plus
        # the current query. SessionSummarizer.extract_summary wants a list of
        # {"role","content"} dicts and only reads role=="user" content, so the
        # query and recent observations are framed as user turns. Any failure
        # falls back silently to the labels already collected -- never raises.
        if self._summarizer is not None:
            try:
                messages: List[dict] = []
                if self._working is not None:
                    for entry in self._working.get_recent(n=5):
                        text = entry.get("observation") or entry.get("label") or ""
                        if text:
                            messages.append({"role": "user", "content": text})
                messages.append({"role": "user", "content": query})
                summary = self._summarizer.extract_summary(messages)
                if summary and summary.strip():
                    items.append("summary: " + _clean(summary, max_len=300))
            except Exception:
                pass
        return items

    def _retrieve_global(self, query: str) -> List[str]:
        items: List[str] = []
        vec = None
        if self._perception is not None:
            try:
                vec = self._perception.encode(query)
            except Exception:
                vec = None
        if vec is None:
            return items

        if self._episodic is not None:
            try:
                for ep in self._episodic.retrieve_similar(vec, top_k=3):
                    label = ep.get("label") or ep.get("observation") or ""
                    if label:
                        sim = ep.get("similarity", 0.0)
                        items.append("episodic[%0.2f]: %s" % (sim, _clean(label)))
            except Exception:
                pass

        if self._semantic is not None:
            try:
                for rel in self._semantic.find_related(vec, top_k=3):
                    concept = rel.get("concept") or ""
                    if concept:
                        sim = rel.get("similarity", 0.0)
                        items.append("semantic[%0.2f]: %s" % (sim, _clean(concept)))
            except Exception:
                pass
        return items

    # -- Assembly ---------------------------------------------------------

    def _assemble_context(self, bands: List[BandResult]) -> str:
        # Priority order LOCAL, MEDIA, GLOBAL: cheapest/highest-fidelity first.
        order = {"LOCAL": 0, "MEDIA": 1, "GLOBAL": 2}
        blocks: List[str] = []
        for band in sorted(bands, key=lambda b: order.get(b.name, 99)):
            if not band.active or not band.items:
                continue
            lines = ["[%s]" % band.name]
            lines.extend("  - " + it for it in band.items)
            blocks.append("\n".join(lines))
        text = "\n".join(blocks)
        return text.encode("ascii", "replace").decode("ascii")

    # -- Public API -------------------------------------------------------

    def route(self, query: str) -> HydraRouting:
        query = query or ""
        persona, temperature, confidence = self._route_persona(query)

        local_score = self._score_local(query)
        media_score = self._score_media(query)
        global_score = self._score_global(query, persona)

        local_active = True
        media_active = media_score > 0.0
        global_active = global_score > 0.0

        bands = [
            BandResult(
                "LOCAL", local_active, local_score,
                self._retrieve_local(query) if local_active else [],
            ),
            BandResult(
                "MEDIA", media_active, media_score,
                self._retrieve_media(query) if media_active else [],
            ),
            BandResult(
                "GLOBAL", global_active, global_score,
                self._retrieve_global(query) if global_active else [],
            ),
        ]

        assembled = self._assemble_context(bands)
        return HydraRouting(
            query=query,
            persona=persona,
            temperature=temperature,
            persona_confidence=confidence,
            bands=bands,
            assembled_context=assembled,
        )


def format_trace(routing: HydraRouting) -> str:
    """Human-readable, ASCII-only multi-line trace of a routing decision."""
    lines: List[str] = []
    lines.append("INPUT: " + _clean(routing.query, max_len=200))
    lines.append(
        "PERSONA: %s  (temp=%.2f, confidence=%.2f)"
        % (routing.persona, routing.temperature, routing.persona_confidence)
    )
    lines.append("BAND SCORES:")
    for b in routing.bands:
        lines.append("  %-6s score=%.2f" % (b.name, b.score))
    active = [b.name for b in routing.bands if b.active]
    lines.append("ACTIVE BANDS: " + (", ".join(active) if active else "(none)"))
    lines.append("RETRIEVED ITEMS:")
    for b in routing.bands:
        if not b.active:
            continue
        if b.items:
            lines.append("  %s:" % b.name)
            for it in b.items:
                lines.append("    - " + it)
        else:
            lines.append("  %s: (none)" % b.name)
    lines.append("ASSEMBLED CONTEXT:")
    ctx = routing.assembled_context or "(empty)"
    for cl in ctx.splitlines():
        lines.append("  " + cl)
    text = "\n".join(lines)
    return text.encode("ascii", "replace").decode("ascii")


_DEMO_QUERIES = [
    "escribe una funcion de binary search en python",
    "recuerda lo que me dijiste antes sobre la arquitectura de shards?",
    "redacta un parrafo elegante sobre el oceano",
]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="HYDRA-analogue 3-band context/memory router."
    )
    parser.add_argument(
        "query", nargs="?", default=None,
        help="Query to route. If omitted, runs 3 built-in demo queries.",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Override DB path (default: cognia.config.DB_PATH).",
    )
    args = parser.parse_args(argv)

    router = HydraContextRouter(db_path=args.db_path)
    queries = [args.query] if args.query else _DEMO_QUERIES

    for i, q in enumerate(queries):
        if i:
            print("")
        print("=" * 60)
        routing = router.route(q)
        out = format_trace(routing)
        # ASCII-safe print for Windows CP1252 stdout.
        print(out.encode("ascii", "replace").decode("ascii"))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
