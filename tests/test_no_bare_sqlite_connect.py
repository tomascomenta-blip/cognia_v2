"""
tests/test_no_bare_sqlite_connect.py
====================================
Enforces the CLAUDE.md hard rule:

    "Sin sqlite3.connect() directo -> usar storage/db_pool.py si existe."

This is a *ratchet*, not a big-bang migration. There is a frozen baseline of
files that already call sqlite3.connect() directly (a pre-existing debt that the
db_pool __del__ safety net + explicit-commit audits have already neutralised for
correctness). The test fails if:

  - a NEW file introduces a bare sqlite3.connect() call (the debt must not grow), or
  - a baseline file is cleaned up (migrated to db_pool) but left in the baseline
    (the baseline must shrink, never silently drift).

Detection is AST-based so docstrings/comments that merely mention
"sqlite3.connect()" are not false positives.

When you legitimately migrate a file to storage/db_pool.py, remove it from
KNOWN_BARE_SQLITE below. New code must use storage.db_pool.db_connect_pooled().
"""
import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories whose .py files are exempt from the rule:
#   tests/   - test fixtures legitimately build throwaway in-memory/temp DBs
#   scripts/ - one-shot maintenance/conversion tools, not the running app
#   generated_programs/ - salida de Cognia, no codigo fuente del repo. Son
#     programas sueltos que se ejecutan solos en un sandbox: no pueden importar
#     storage/db_pool.py, que es infraestructura interna. Disparo real el
#     2026-07-20 al pedirle a Cognia un gestor de tareas con SQLite: cumplio el
#     encargo y el guardian marco su salida como violacion del repo.
#   generated_games/ - lo mismo, salida de game_manager.
_EXCLUDE_DIR_PARTS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "tests", "scripts", "build", "dist",
    "generated_programs", "generated_games",
}


def _is_excluded_part(part: str) -> bool:
    # Any virtualenv layout counts (venv, venv312, .venv, ...): third-party
    # site-packages must never trip the repo's own hygiene ratchet.
    return part in _EXCLUDE_DIR_PARTS or part.startswith(("venv", ".venv"))

# Frozen baseline (captured 2026-06-17). Each entry is a file that already used a
# bare sqlite3.connect() before this guard existed. ONLY remove entries (after
# migrating that file to storage/db_pool.py). NEVER add entries.
KNOWN_BARE_SQLITE = {
    # Pool/wrapper layer — these legitimately own the raw sqlite3 connection.
    "storage/db_pool.py",
    "cognia/database.py",
    "cognia_v3.py",
    # coordinator/* run as a separate service process (per CLAUDE.md scope note).
    "coordinator/contributor.py",
    "coordinator/federated_store.py",
    "coordinator/registry.py",
    "coordinator/shard_registry.py",
    # Pre-existing debt (raw sqlite3; GC-closed, commits audited 2026-06-16/17).
    "code_memory.py",
    "cognia/agents/self_improvement.py",
    "cognia/agents/task_queue.py",
    "cognia/consolidation_engine.py",
    "cognia/goal_and_pattern_engine.py",
    "cognia/migrations/runner.py",
    "cognia/reasoning/thought_cache.py",
    "cognia/research_engine/knowledge_integrator.py",
    "cognia_modules_adicionales.py",
    "cognia_public_api/key_store.py",
    "consolidation_engine.py",
    "curiosidad_pasiva.py",
    "curiosity_engine.py",
    "feedback_engine.py",
    "investigador.py",
    "model_collapse_guard.py",
    "prompt_optimizer.py",
    "response_cache.py",
    "scoring_engine.py",
    "self_architect.py",
    "shattering/distillation/data_generator.py",
    "symbolic_responder.py",
    "symbolic_synthesizer.py",
    "teacher_interface.py",
    "tools/auto_editor.py",
    "web_app.py",
}


def _calls_sqlite_connect(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "sqlite3"
        ):
            return True
    return False


def _scan() -> set:
    found = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_parts = Path(dirpath).relative_to(ROOT).parts
        if any(_is_excluded_part(p) for p in rel_parts):
            dirnames[:] = []
            continue
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = Path(dirpath) / fn
            if _calls_sqlite_connect(p):
                found.add(p.relative_to(ROOT).as_posix())
    return found


def test_no_new_bare_sqlite_connect():
    current = _scan()
    new_violations = current - KNOWN_BARE_SQLITE
    assert not new_violations, (
        "New bare sqlite3.connect() detected (CLAUDE.md hard rule). "
        "Use storage.db_pool.db_connect_pooled() instead. Offending file(s): "
        + ", ".join(sorted(new_violations))
    )


def test_venv_layouts_are_excluded():
    """Regresion: venv312 (el venv real del repo) no matcheaba la exclusion
    exacta 'venv' y el escaner reportaba site-packages de terceros (torch,
    filelock) como violaciones propias."""
    assert _is_excluded_part("venv")
    assert _is_excluded_part("venv312")
    assert _is_excluded_part(".venv")
    assert not _is_excluded_part("cognia")
    assert not _is_excluded_part("node")


def test_baseline_has_no_stale_entries():
    current = _scan()
    cleaned = KNOWN_BARE_SQLITE - current
    assert not cleaned, (
        "These files no longer call sqlite3.connect() directly -- remove them "
        "from KNOWN_BARE_SQLITE so the baseline ratchets down: "
        + ", ".join(sorted(cleaned))
    )
