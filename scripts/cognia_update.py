"""
scripts/cognia_update.py
========================
cognia update command: pulls latest code and applies DB schema migrations.

Steps:
  1. git pull (requires git CLI)
  2. pip install -r requirements.txt --upgrade
  3. Run DB migrations via cognia.migrations.runner

Usage:
    python scripts/cognia_update.py [--db PATH] [--skip-git] [--skip-pip]

Exit codes:
    0  All steps succeeded (or were skipped)
    1  A required step failed
"""

import argparse
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = os.path.join(_ROOT, "cognia_memory.db")
_REQ = os.path.join(_ROOT, "requirements.txt")


def _run(cmd: list[str], cwd: str) -> int:
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


def step_git_pull(root: str) -> bool:
    print("[UPDATE] Pulling latest changes...")
    rc = _run(["git", "pull", "--ff-only"], cwd=root)
    if rc != 0:
        print("[FAIL] git pull failed. Resolve conflicts manually and retry.")
        return False
    print("[OK] git pull")
    return True


def step_pip_install(root: str) -> bool:
    print("[UPDATE] Upgrading dependencies...")
    rc = _run(
        [sys.executable, "-m", "pip", "install", "-r", _REQ, "--upgrade", "-q"],
        cwd=root,
    )
    if rc != 0:
        print("[FAIL] pip install failed.")
        return False
    print("[OK] pip install")
    return True


def step_migrate(db_path: str) -> bool:
    if not os.path.exists(db_path):
        print(f"[SKIP] Database not found at {db_path}. No migrations to run.")
        return True

    sys.path.insert(0, _ROOT)
    try:
        from cognia.migrations import run_migrations
        applied = run_migrations(db_path)
        if applied:
            print(f"[OK] Applied {applied} DB migration(s).")
        else:
            print("[OK] DB schema is up to date.")
        return True
    except Exception as exc:
        print(f"[FAIL] DB migration error: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Cognia to the latest version")
    parser.add_argument("--db", default=_DEFAULT_DB, help="Path to cognia_memory.db")
    parser.add_argument("--skip-git", action="store_true", help="Skip git pull step")
    parser.add_argument("--skip-pip", action="store_true", help="Skip pip install step")
    args = parser.parse_args()

    print("Cognia Update")
    print("=" * 40)

    if not args.skip_git:
        if not step_git_pull(_ROOT):
            return 1

    if not args.skip_pip:
        if not step_pip_install(_ROOT):
            return 1

    if not step_migrate(args.db):
        return 1

    print("=" * 40)
    print("[OK] Update complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
