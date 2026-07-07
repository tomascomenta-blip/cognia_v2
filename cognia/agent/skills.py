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

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from cognia.logger_config import get_logger

logger = get_logger(__name__)

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


# ── Uso real de skills (CP2 §3.5): sidecar JSON, nunca el frontmatter ──
# record_skill_use() persiste uses_ok/uses_fail en <dir>/.skill_usage.json
# (un sidecar por directorio de origen, NO por skill) para no reescribir el
# .md del usuario. Escritura atomica (tmp + os.replace): un corte a mitad de
# escritura nunca deja el sidecar corrupto.

_USAGE_FILE = ".skill_usage.json"
_FAIL_STREAK_MIN = 3   # uses_fail >= esto y uses_ok == 0 -> se penaliza


def _usage_file(skill_dir: Path) -> Path:
    return skill_dir / _USAGE_FILE


def _load_usage(skill_dir: Path) -> dict:
    """{nombre_skill: {uses_ok, uses_fail}} del directorio, o {} si no hay
    sidecar o esta corrupto (best-effort, nunca levanta)."""
    try:
        return json.loads(_usage_file(skill_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_usage_atomic(skill_dir: Path, data: dict) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    tmp = skill_dir / f"{_USAGE_FILE}.tmp-{os.getpid()}"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _usage_file(skill_dir))   # atomico: nunca a medio escribir


def _usage_for(spec: "SkillSpec") -> dict:
    """{'uses_ok': int, 'uses_fail': int} de la skill (ceros si no hay uso
    registrado todavia)."""
    data = _load_usage(Path(spec.source).parent)
    return data.get(spec.name, {"uses_ok": 0, "uses_fail": 0})


def record_skill_use(name: str, ok: bool, skills: dict = None) -> None:
    """
    Registra un uso de la skill `name` (CP2 §3.5 — senal de aprendizaje del
    uso real, no del frontmatter estatico). Best-effort: si la skill no
    existe o el sidecar no se puede escribir (p.ej. skill del usuario en un
    dir de solo lectura), no hace nada — nunca levanta.
    """
    try:
        skills = skills if skills is not None else load_skills()
        spec = skills.get(name)
        if spec is None:
            return
        skill_dir = Path(spec.source).parent
        data = _load_usage(skill_dir)
        entry = data.get(name, {"uses_ok": 0, "uses_fail": 0})
        key = "uses_ok" if ok else "uses_fail"
        entry[key] = entry.get(key, 0) + 1
        data[name] = entry
        _save_usage_atomic(skill_dir, data)
    except OSError as exc:
        logger.warning("no se pudo persistir el uso de la skill",
                       extra={"op": "record_skill_use",
                              "context": f"name={name} err={exc}"})


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-záéíóúñ]{3,}", (text or "").lower())
            if w not in _STOP}


# Umbral conservador del fallback semantico (TAREA 3a): calibrado a mano
# contra el fallback de n-gramas de cognia/vectors.py (sentence-transformers
# no esta instalado en este repo -> text_to_vector cae a _ngram_vector, ver
# cognia_embedding.py). Con texto corto (un pedido, un name+description) la
# señal es ruidosa (bigrams de caracteres + hash de palabras), asi que el
# umbral se elige ALTO a proposito: mejor perder algun parafraseo real que
# matchear texto no relacionado (medido: pares realmente parafraseados
# rondan 0.30-0.44 tras sacar stopwords, pares no relacionados 0.21-0.32 —
# bandas que se pisan, por eso "conservador" y no "ajustado").
SEMANTIC_MATCH_THRESHOLD = 0.35

# Umbral del dedupe semantico de persist_skill (TAREA 3b): sobre el body
# COMPLETO (no boW de stopwords) dos redacciones de la MISMA skill miden
# ~0.81-0.98 (medido variando 1-3 palabras); skills de tema distinto miden
# ~0.50-0.58. 0.90 deja margen grande de los dos lados.
SEMANTIC_DUP_THRESHOLD = 0.90


def _semantic_best_match(text: str, candidates: dict, threshold: float):
    """Fallback semantico de find_skill: similitud coseno (cognia/vectors.py,
    sin dependencias nuevas) entre `text` y name+description de cada skill
    candidata. Solo lo llama find_skill cuando el solapamiento lexico no
    encontro nada -- capa barata para pedidos parafraseados con vocabulario
    distinto al de la skill."""
    if not candidates:
        return None
    # El umbral esta calibrado para sentence-transformers; con el fallback
    # n-gram (ST ausente o sistema bajo presion) el coseno da similitudes
    # espurias entre textos cortos -> matches falsos (visto como flakiness
    # de test de aislamiento y como riesgo real en maquinas sin ST).
    from cognia.cognia_embedding import semantic_model_active
    if not semantic_model_active():
        logger.info("fallback semantico deshabilitado: backend n-gram activo",
                    extra={"op": "find_skill"})
        return None
    from cognia.vectors import cosine_similarity, text_to_vector
    req_vec = text_to_vector(text)
    best, best_sim = None, 0.0
    for s in candidates.values():
        sim = cosine_similarity(req_vec, text_to_vector(f"{s.name} {s.description}"))
        if sim > best_sim:
            best, best_sim = s, sim
    return best if best_sim >= threshold else None


def find_skill(text: str, skills: dict = None, min_overlap: int = 2,
               semantic_fallback: bool = True):
    """
    Best skill whose name+description overlaps the request, or None.
    1. Solapamiento lexico (bag-of-words, barato, no-LLM) -- gana si
       encuentra algo (comportamiento original, intacto).
    2. Si el lexico no encontro nada: fallback a similitud coseno semantica
       (TAREA 3a) sobre name+description, para pedidos parafraseados.
    Skills con historial de uso consistentemente malo (record_skill_use:
    >= _FAIL_STREAK_MIN fallos y 0 exitos) se excluyen de ambas capas -- se
    loguea la exclusion, no se silencia.

    ``semantic_fallback=False``: solo capa lexica. Para el AUTO-APPLY del
    agent loop es obligatorio (bench_estancamiento post-fix 2026-07-07): el
    coseno a 0.35 matcheaba skills IRRELEVANTES en tareas cortas ("Calcula
    15 por 4" -> escribir-tests, "echo cognia_ok" -> claude-mem) y la
    guidance inyectada metia archivos inexistentes (codigo_a_testear.py)
    que el 3B intentaba leer en loop hasta el stuck-detector. El fallback
    semantico queda para pedidos EXPLICITOS del usuario (/skill).
    """
    skills = skills if skills is not None else load_skills()
    if not skills:
        return None
    req = _tokens(text)
    if not req:
        return None

    usable = {}
    for name, s in skills.items():
        usage = _usage_for(s)
        if usage.get("uses_fail", 0) >= _FAIL_STREAK_MIN and usage.get("uses_ok", 0) == 0:
            logger.info("skill excluida del match: historial de uso malo",
                        extra={"op": "find_skill",
                               "context": f"name={name} uses_fail={usage['uses_fail']}"})
            continue
        usable[name] = s

    best, best_score = None, 0
    for s in usable.values():
        score = len(req & (_tokens(s.name) | _tokens(s.description)))
        if score > best_score:
            best, best_score = s, score
    if best is not None and best_score >= min_overlap:
        return best

    if not semantic_fallback:
        return None
    return _semantic_best_match(text, usable, SEMANTIC_MATCH_THRESHOLD)


def skill_guidance(skill: SkillSpec, max_chars: int = 2000) -> str:
    """The instruction block to inject into the agent/LLM for this skill."""
    body = skill.body[:max_chars]
    return (f"Estas operando bajo la skill '{skill.name}': {skill.description}\n"
            f"Segui estas instrucciones:\n{body}")


# ── Escritura de skills nivel-2 (CP2, 06_AGENTE_PLAN §3) ────────────────
# Un skill nivel-2 es markdown (instrucciones, no codigo): blast radius
# cero por construccion — NO se ejecuta directamente. El blocklist de abajo
# es DEFENSA EN PROFUNDIDAD sobre esa garantia estructural: reduce el riesgo
# de persistir instrucciones que un agente futuro podria obedecer, pero NO
# es un gate hermetico (un regex de patrones peligrosos siempre es evadible
# con ofuscacion; ver P8 del plan). El gate REAL de ejecucion vive en la capa
# de tools (allowlist de imports + sandbox de tool_synthesis, blocklist de
# _shell en tools.py). Aca se cazan las formas mas obvias.

DANGEROUS_PATTERNS = [
    # borrado/destruccion de disco o arbol (flags juntos o separados)
    re.compile(r"\brm\s+(-\w+\s+)*-?\w*[rf]\w*\s+(-\w+\s+)*-?\w*[rf]", re.IGNORECASE),
    re.compile(r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\b", re.IGNORECASE),
    re.compile(r"\brm\s+--(recursive|force)\b", re.IGNORECASE),
    re.compile(r"\b(del|erase)\s+/[sqf]", re.IGNORECASE),
    re.compile(r"\brmdir\s+/s", re.IGNORECASE),
    re.compile(r"\bmkfs(\.\w+)?\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    re.compile(r">\s*/dev/(sd|nvme|null\b.{0,20}<)", re.IGNORECASE),
    # pipe-a-interprete desde la red (instalacion ciega; tolera sudo/env
    # entre el pipe y el interprete, y python/perl/ruby ademas de shells)
    re.compile(r"\b(curl|wget|iwr|invoke-webrequest)\b[^\n]{0,200}\|\s*"
               r"(sudo\s+|env\s+\S+\s+)*"
               r"(sh|bash|zsh|iex|powershell|python\d?|perl|ruby|node)\b",
               re.IGNORECASE),
    # apagado / persistencia de sistema
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.IGNORECASE),
    re.compile(r"\breg\s+add\s+hklm", re.IGNORECASE),
    re.compile(r":\(\)\s*\{.*\};\s*:", re.DOTALL),  # fork bomb
    # escritura fuera del workspace via la tool de archivos (back o forward slash)
    re.compile(r"escribir_archivo\s+([a-z]:[\\/]windows|/etc/|/usr/|/bin/|"
               r"~[/\\]\.)", re.IGNORECASE),
    # exfiltracion de secretos tipicos (marcador o verbo de red en cualquier orden)
    re.compile(r"(\.env\b|id_rsa|\.ssh[/\\]|api[_-]?key)[^\n]{0,80}"
               r"(http_get|curl|wget|\bpost\b|@)", re.IGNORECASE),
    re.compile(r"(curl|wget|http_get)[^\n]{0,80}(\.env\b|id_rsa|\.ssh[/\\])",
               re.IGNORECASE),
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

    # 2b. dedupe SEMANTICO (TAREA 3b): el nombre puede ser distinto pero el
    # contenido (lo que de verdad importa reusar) casi el mismo -- el check
    # de arriba solo compara el string del nombre. Umbral alto (~0.9): solo
    # rechaza duplicados casi textuales, no skills genuinamente distintas.
    if existing:
        from cognia.vectors import cosine_similarity, text_to_vector
        new_vec = text_to_vector(f"{description}\n{body}")
        for ex_name, ex_spec in existing.items():
            sim = cosine_similarity(
                new_vec, text_to_vector(f"{ex_spec.description}\n{ex_spec.body}"))
            if sim >= SEMANTIC_DUP_THRESHOLD:
                return {"ok": False,
                        "reason": (f"skill semanticamente duplicada de {ex_name} "
                                  f"(sim={sim:.2f}) — reusar")}

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
