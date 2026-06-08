"""
scripts/cognia_doctor.py
=========================
Thin wrapper kept for backward compatibility. The real diagnostics now live in
the package module cognia/doctor.py so they ship in the pip wheel and `/doctor`
works when installed. Run with:  python scripts/cognia_doctor.py

Usage:
    python scripts/cognia_doctor.py
"""

from __future__ import annotations

import os
import sys

# Allow running from a source checkout without installation.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cognia.doctor import main

if __name__ == "__main__":
    sys.exit(main())
