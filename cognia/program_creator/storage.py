"""
storage.py — Almacenamiento de programas exitosos generados por Cognia.

CAMBIOS v2:
  - Cognia puede ELIMINAR programas mediocres automáticamente
  - replace_if_better(): cuando llega algo mejor de la misma categoría, borra el viejo
  - auto_cleanup(): si la biblioteca crece mucho, descarta los peores
  - Registro completo de eliminaciones en deleted_programs.json
  - El resumen distingue ideas propias (🧠) de categorías predefinidas (📋)
"""

import json
import os
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from .generator  import GeneratedProgram
from .evaluator  import EvaluationResult, format_evaluation_text

# ── Configuración ──────────────────────────────────────────────────────────────

DEFAULT_STORAGE_DIR    = Path(__file__).parent / "generated_programs"
INDEX_FILE             = "index.json"
DELETION_LOG_FILE      = "deleted_programs.json"
AUTO_CLEANUP_THRESHOLD = 25    # Si hay más programas que esto, limpia automático
SURVIVAL_SCORE         = 6.0   # Puntuación mínima para sobrevivir una limpieza


# ── Dataclass de metadata ──────────────────────────────────────────────────────

@dataclass
class StoredProgramMeta:
    id:            str
    title:         str
    category:      str
    description:   str
    total_score:   float
    created_at:    str
    directory:     str
    self_proposed: bool = False


# ── Utilidades internas ────────────────────────────────────────────────────────

def _sanitize_dirname(title: str) -> str:
    name = title.lower().strip()
    name = re.sub(r"[^a-z0-9\s_-]", "", name)
    name = re.sub(r"[\s-]+", "_", name)
    name = name[:50].strip("_")
    return name or "unnamed_program"

def _make_unique_dirname(base: str, storage_dir: Path) -> str:
    candidate, counter = base, 1
    while (storage_dir / candidate).exists():
        candidate = f"{base}_{counter:02d}"
        counter  += 1
    return candidate

def _load_index(storage_dir: Path) -> list:
    p = storage_dir / INDEX_FILE
    if not p.exists(): return []
    try:
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    except (json.JSONDecodeError, OSError): return []

def _save_index(storage_dir: Path, index: list) -> None:
    with open(storage_dir / INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

def _load_deletion_log(storage_dir: Path) -> list:
    p = storage_dir / DELETION_LOG_FILE
    if not p.exists(): return []
    try:
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    except (json.JSONDecodeError, OSError): return []

def _save_deletion_log(storage_dir: Path, log: list) -> None:
    with open(storage_dir / DELETION_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

def _build_description_text(program: GeneratedProgram,
                              eval_result: EvaluationResult,
                              created_at: str) -> str:
    origin = "Yes — Cognia invented this idea" if getattr(program, "self_proposed", False) else "No — from predefined category"
    return "\n".join([
        f"Title         : {program.title}",
        f"Category      : {program.category}",
        f"Created at    : {created_at}",
        f"Score         : {eval_result.total_score:.1f} / 10",
        f"Self-proposed : {origin}",
        "",
        "Description:",
        f"  {program.description}",
    ])


# ── Eliminación ────────────────────────────────────────────────────────────────

def delete_program(program_id: str, reason: str = "manual deletion",
                   storage_dir: Path = None) -> bool:
    """
    Elimina un programa físicamente y lo registra en el log de eliminaciones.
    Cognia usa este log para aprender qué tipos de programas no funcionan.
    """
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR

    prog_dir = storage_dir / program_id
    if not prog_dir.exists(): return False

    index = _load_index(storage_dir)
    entry = next((e for e in index if e.get("id") == program_id), None)

    try:
        shutil.rmtree(prog_dir)
    except Exception as exc:
        print(f"[storage] ❌ Error eliminando {program_id}: {exc}")
        return False

    _save_index(storage_dir, [e for e in index if e.get("id") != program_id])

    if entry:
        log = _load_deletion_log(storage_dir)
        log.append({**entry, "deleted_at": datetime.now().isoformat(), "reason": reason})
        _save_deletion_log(storage_dir, log)
        print(f"[storage] 🗑️  Eliminado: '{entry.get('title', program_id)}' "
              f"(score={entry.get('total_score', '?'):.1f}) — {reason}")
    return True


def auto_cleanup(storage_dir: Path = None, keep_minimum: int = 10,
                 survival_score: float = SURVIVAL_SCORE, verbose: bool = True) -> int:
    """
    Cognia revisa su biblioteca y descarta los programas más débiles.
    - Nunca toca los top-5 por puntuación (sus mejores trabajos)
    - Elimina los que están por debajo de survival_score
    - Nunca deja la biblioteca con menos de keep_minimum programas
    """
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR

    index = _load_index(storage_dir)
    if len(index) <= keep_minimum: return 0

    if verbose:
        print(f"[storage] 🔍 Revisando biblioteca ({len(index)} programas)...")

    # Proteger los top-5
    sorted_index  = sorted(index, key=lambda e: e.get("total_score", 0), reverse=True)
    protected_ids = {e["id"] for e in sorted_index[:5]}

    candidates = sorted(
        [e for e in index
         if e.get("total_score", 0) < survival_score and e.get("id") not in protected_ids],
        key=lambda e: (e.get("total_score", 0), e.get("created_at", ""))
    )

    deleted = 0
    for entry in candidates:
        if len(index) - deleted <= keep_minimum: break
        reason = (f"auto-cleanup: score {entry.get('total_score', 0):.1f} "
                  f"< survival threshold {survival_score}")
        if delete_program(entry["id"], reason=reason, storage_dir=storage_dir):
            deleted += 1

    if verbose:
        if deleted > 0:
            print(f"[storage] 🧹 Limpieza: {deleted} programas eliminados")
        else:
            print(f"[storage] ✨ Biblioteca limpia — todo por encima del umbral")
    return deleted


def replace_if_better(new_program: GeneratedProgram, new_eval: EvaluationResult,
                      storage_dir: Path = None) -> bool:
    """
    Si hay un programa de la misma categoría con puntuación >1 punto menor,
    lo elimina para hacer espacio al nuevo y mejor.
    """
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR

    index = _load_index(storage_dir)
    same_cat = [
        e for e in index
        if e.get("category", "").lower() == new_program.category.lower()
        and e.get("total_score", 0) < new_eval.total_score - 1.0
    ]
    if not same_cat: return False

    worst  = min(same_cat, key=lambda e: e.get("total_score", 0))
    reason = (f"replaced by '{new_program.title}' "
              f"(score {new_eval.total_score:.1f} > {worst.get('total_score', 0):.1f})")
    return delete_program(worst["id"], reason=reason, storage_dir=storage_dir)


# ── API pública ────────────────────────────────────────────────────────────────

def save_program(program: GeneratedProgram, eval_result: EvaluationResult,
                 storage_dir: Path = None) -> StoredProgramMeta:
    """Guarda un programa aprobado. Reemplaza inferiores de su categoría si los hay."""
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    storage_dir.mkdir(parents=True, exist_ok=True)

    replace_if_better(program, eval_result, storage_dir)

    base_name  = _sanitize_dirname(program.title)
    dir_name   = _make_unique_dirname(base_name, storage_dir)
    prog_dir   = storage_dir / dir_name
    prog_dir.mkdir(parents=True, exist_ok=True)

    created_at    = datetime.now().isoformat()
    self_proposed = getattr(program, "self_proposed", False)
    origin        = "self-proposed idea" if self_proposed else "predefined category"

    with open(prog_dir / "program.py", "w", encoding="utf-8") as f:
        f.write(f"# Generated by Cognia | {created_at}\n")
        f.write(f"# Category: {program.category}\n")
        f.write(f"# Score: {eval_result.total_score:.1f}/10\n")
        f.write(f"# Origin: {origin}\n\n")
        f.write(program.code)

    with open(prog_dir / "description.txt", "w", encoding="utf-8") as f:
        f.write(_build_description_text(program, eval_result, created_at))

    with open(prog_dir / "evaluation.txt", "w", encoding="utf-8") as f:
        f.write(format_evaluation_text(eval_result))

    meta = StoredProgramMeta(
        id=dir_name, title=program.title, category=program.category,
        description=program.description, total_score=eval_result.total_score,
        created_at=created_at, directory=dir_name, self_proposed=self_proposed,
    )

    index = _load_index(storage_dir)
    index.append(asdict(meta))
    _save_index(storage_dir, index)
    print(f"[storage] 💾 Guardado: {prog_dir}")

    if len(index) > AUTO_CLEANUP_THRESHOLD:
        auto_cleanup(storage_dir=storage_dir, verbose=True)

    return meta


def list_programs(storage_dir: Path = None) -> list[StoredProgramMeta]:
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    programs = []
    for entry in _load_index(storage_dir):
        try:
            if "self_proposed" not in entry: entry["self_proposed"] = False
            programs.append(StoredProgramMeta(**entry))
        except TypeError:
            continue
    return sorted(programs, key=lambda p: p.created_at, reverse=True)


def get_program_count(storage_dir: Path = None) -> int:
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    return len(_load_index(storage_dir))


def load_program_code(program_id: str, storage_dir: Path = None) -> str:
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    prog_file = storage_dir / program_id / "program.py"
    if not prog_file.exists(): return ""
    try:
        with open(prog_file, "r", encoding="utf-8") as f: return f.read()
    except OSError: return ""


def get_deletion_log(storage_dir: Path = None) -> list:
    if storage_dir is None: storage_dir = DEFAULT_STORAGE_DIR
    return _load_deletion_log(storage_dir)


def format_library_summary(storage_dir: Path = None) -> str:
    programs = list_programs(storage_dir)
    if not programs:
        return "📂 Biblioteca vacía — aún no se ha guardado ningún programa."

    self_proposed_count = sum(1 for p in programs if p.self_proposed)
    avg_score           = sum(p.total_score for p in programs) / len(programs)
    deletion_log        = get_deletion_log(storage_dir)

    lines = [
        f"📂 Biblioteca Cognia ({len(programs)} programas)",
        f"   Ideas propias: {self_proposed_count} | Promedio: {avg_score:.1f}/10 | Eliminados históricamente: {len(deletion_log)}",
        "",
    ]
    for prog in programs[:10]:
        tag = "🧠" if prog.self_proposed else "📋"
        lines.append(f"  {tag} [{prog.total_score:.1f}/10] {prog.title}  ({prog.category})")
    if len(programs) > 10:
        lines.append(f"  ... y {len(programs) - 10} más.")
    return "\n".join(lines)
