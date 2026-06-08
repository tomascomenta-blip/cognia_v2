"""
cognia/agent/skills.py
=====================
Make Claude-format skills usable by Cognia.

A Claude skill is a markdown file with YAML-ish frontmatter (name, description)
and a body of instructions -- either `<name>.md` (flat) or `<name>/SKILL.md`
(directory). Cognia's own cognia_skills/*.md use the same shape, so one loader
reads both. A loaded skill is a SkillSpec; its body becomes extra guidance that
shapes the agent/LLM when the skill is invoked or auto-matched to a request.

Sources scanned (later wins on name clash, so a bundled skill can override):
  ~/.claude/skills            -- the user's installed Claude skills (read-only)
  <repo>/.claude/skills       -- project Claude skills
  <repo>/cognia_skills        -- Cognia's existing skills
  <repo>/cognia/skills        -- skills bundled WITH Cognia (the curated set)

Concrete: a dataclass + a few functions. No plugin runtime, no exec.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

SKILL_DIRS = [
    Path.home() / ".claude" / "skills",
    _REPO / ".claude" / "skills",
    _REPO / "cognia_skills",
    _REPO / "cognia" / "skills",
]

_STOP = {
    "the", "and", "for", "with", "que", "con", "los", "las", "una", "uno", "del",
    "por", "para", "como", "este", "esta", "usage", "skill", "mode", "cuando",
    "use", "your", "you", "when", "esto", "eso", "sobre",
}


@dataclass
class SkillSpec:
    name: str
    description: str
    body: str
    source: str       # absolute path it came from
    kind: str         # "claude" | "cognia"


def _parse(text: str) -> tuple:
    """(frontmatter dict, body). Reads simple `key: value` frontmatter."""
    lines = text.splitlines()
    fm: dict = {}
    if not lines or lines[0].strip() != "---":
        return fm, text
    end = next((i for i, ln in enumerate(lines[1:], 1) if ln.strip() == "---"), -1)
    if end == -1:
        return fm, text
    for ln in lines[1:end]:
        if ":" in ln and not ln.startswith(" "):
            k, _, v = ln.partition(":")
            fm[k.strip().lower()] = v.strip()
    return fm, "\n".join(lines[end + 1:]).lstrip("\n")


def _skill_from_file(path: Path, kind: str) -> "SkillSpec | None":
    try:
        fm, body = _parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    name = (fm.get("name") or path.stem).strip()
    if name.upper() == "SKILL":             # <name>/SKILL.md -> use the dir name
        name = path.parent.name
    if not name:
        return None
    return SkillSpec(
        name=name,
        description=fm.get("description", "").strip(),
        body=body.strip(),
        source=str(path),
        kind=kind,
    )


def load_skills(extra_dirs: list = None) -> dict:
    """
    Discover all skills. Returns {name: SkillSpec}. Later directories override
    earlier ones on name clash (bundled overrides user). Never raises.
    """
    skills: dict = {}
    dirs = list(SKILL_DIRS) + [Path(d) for d in (extra_dirs or [])]
    for d in dirs:
        try:
            if not d.is_dir():
                continue
            kind = "claude" if ".claude" in d.parts else "cognia"
            # flat <name>.md
            for f in sorted(d.glob("*.md")):
                s = _skill_from_file(f, kind)
                if s:
                    skills[s.name] = s
            # directory <name>/SKILL.md
            for f in sorted(d.glob("*/SKILL.md")):
                s = _skill_from_file(f, kind)
                if s:
                    skills[s.name] = s
        except Exception:
            continue
    return skills


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-záéíóúñ]{3,}", (text or "").lower())
            if w not in _STOP}


def find_skill(text: str, skills: dict = None, min_overlap: int = 2):
    """
    Best skill whose name+description overlaps the request, or None. Cheap keyword
    overlap (no LLM) -- used to auto-apply a skill to a matching request.
    """
    skills = skills if skills is not None else load_skills()
    if not skills:
        return None
    req = _tokens(text)
    if not req:
        return None
    best, best_score = None, 0
    for s in skills.values():
        score = len(req & (_tokens(s.name) | _tokens(s.description)))
        if score > best_score:
            best, best_score = s, score
    return best if best_score >= min_overlap else None


def skill_guidance(skill: SkillSpec, max_chars: int = 2000) -> str:
    """The instruction block to inject into the agent/LLM for this skill."""
    body = skill.body[:max_chars]
    return (f"Estas operando bajo la skill '{skill.name}': {skill.description}\n"
            f"Segui estas instrucciones:\n{body}")
