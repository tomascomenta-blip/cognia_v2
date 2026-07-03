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


# ── Escritura de skills nivel-2 (CP2, 06_AGENTE_PLAN §3) ────────────────
# Un skill nivel-2 es markdown (instrucciones, no codigo): blast radius
# cero por construccion. Aun asi, NADA se persiste si el cuerpo contiene
# patrones peligrosos que el agente podria luego obedecer — blocklist
# SIEMPRE activo, sin flag para saltearlo (a diferencia del diseño de
# Hermes de confiar en el contenedor: defensa en profundidad).

DANGEROUS_PATTERNS = [
    # borrado/destruccion de disco o arbol
    re.compile(r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\b", re.IGNORECASE),
    re.compile(r"\b(del|erase)\s+/[sqf]", re.IGNORECASE),
    re.compile(r"\brmdir\s+/s", re.IGNORECASE),
    re.compile(r"\bmkfs(\.\w+)?\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    re.compile(r">\s*/dev/(sd|nvme|null\b.{0,20}<)", re.IGNORECASE),
    # pipe-a-shell desde la red (instalacion ciega)
    re.compile(r"\b(curl|wget|iwr|invoke-webrequest)\b[^\n|]{0,200}\|\s*"
               r"(sh|bash|zsh|iex|powershell)\b", re.IGNORECASE),
    # apagado / persistencia de sistema
    re.compile(r"\b(shutdown|reboot)\b", re.IGNORECASE),
    re.compile(r"\breg\s+add\s+hklm", re.IGNORECASE),
    re.compile(r":\(\)\s*\{.*\};\s*:", re.DOTALL),  # fork bomb
    # escritura fuera del workspace via la tool de archivos
    re.compile(r"escribir_archivo\s+([a-z]:\\|/etc/|/usr/|~[/\\]\.|"
               r"c:\\windows)", re.IGNORECASE),
    # exfiltracion de secretos tipicos
    re.compile(r"(\.env\b|id_rsa|\.ssh[/\\]|api[_-]?key).{0,80}"
               r"(http_get|curl|wget|post)", re.IGNORECASE | re.DOTALL),
]

_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9\-]{2,40}$")
AUTO_SKILL_DIR = _REPO / "cognia_skills"


def skill_safety_scan(text: str) -> list:
    """Patrones peligrosos presentes en el texto (vacio = seguro).
    Se aplica a nombre+descripcion+cuerpo ANTES de persistir."""
    return [rx.pattern[:50] for rx in DANGEROUS_PATTERNS
            if rx.search(text or "")]


def persist_skill(name: str, description: str, body: str,
                  evidence: str) -> dict:
    """Escribe un skill nivel-2 VERIFICADO a cognia_skills/<name>.md.

    Gates (todos obligatorios, en orden):
      1. nombre slug valido;
      2. no existe ya un skill con nombre igual/similar (crear-vs-reusar);
      3. blocklist duro sobre nombre+descripcion+cuerpo;
      4. ``evidence`` no vacio: la traza que lo origino cerro con oraculo
         duro (regla §3.4 — Hermes persiste por 'salio bien', nosotros NO).
    Devuelve {ok, path|reason}."""
    if not _SKILL_NAME_RE.match(name or ""):
        return {"ok": False, "reason": f"nombre invalido: {name!r}"}
    if not (evidence or "").strip():
        return {"ok": False, "reason": "sin evidencia de oraculo duro: no se persiste"}

    import difflib
    existing = load_skills()
    for ex_name in existing:
        ratio = difflib.SequenceMatcher(None, name, ex_name.lower()).ratio()
        if ratio >= 0.8:
            return {"ok": False,
                    "reason": f"skill similar existente: {ex_name} — reusar"}

    hits = skill_safety_scan(name + "\n" + description + "\n" + body)
    if hits:
        return {"ok": False,
                "reason": f"blocklist: patron(es) peligrosos {hits[:3]}"}

    AUTO_SKILL_DIR.mkdir(parents=True, exist_ok=True)
    path = AUTO_SKILL_DIR / f"{name}.md"
    if path.exists():
        return {"ok": False, "reason": f"ya existe {path.name} — editar, no pisar"}
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description[:120]}\n"
        "auto_generated: true\n"
        f"verified: {evidence[:150]}\n"
        "version: 0.1.0\n"
        "---\n\n"
        + body.strip() + "\n"
    )
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(path)}
