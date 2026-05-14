"""
scripts/audit_deps.py
=====================
Dependency vulnerability audit using pip-audit.

Exits 0 if no known vulnerabilities are found or if pip-audit is not installed.
Exits 1 if vulnerabilities are found.

Usage:
    python scripts/audit_deps.py [--requirements PATH]
    python scripts/audit_deps.py --json    # machine-readable output

In CI, install pip-audit first:
    pip install pip-audit
    python scripts/audit_deps.py
"""

import argparse
import os
import subprocess
import sys


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_REQ = os.path.join(_ROOT, "requirements.txt")


def _pip_audit_available() -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "pip_audit", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run(requirements: str, as_json: bool) -> int:
    if not _pip_audit_available():
        print("[WARN] pip-audit not installed. Skipping dependency audit.")
        print("       Install with: pip install pip-audit")
        return 0

    cmd = [sys.executable, "-m", "pip_audit", "--requirement", requirements]
    if as_json:
        cmd += ["--format", "json"]

    result = subprocess.run(cmd)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Python dependencies for known vulnerabilities"
    )
    parser.add_argument("--requirements", default=_DEFAULT_REQ,
                        help="Path to requirements.txt")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    args = parser.parse_args()

    if not os.path.exists(args.requirements):
        print(f"[FAIL] Requirements file not found: {args.requirements}")
        return 1

    return run(args.requirements, args.json)


if __name__ == "__main__":
    sys.exit(main())
