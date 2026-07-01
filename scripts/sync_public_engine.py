"""
scripts/sync_public_engine.py
=============================
Regenerate the vendored public-API inference engine from the canonical
node/+shattering sources so the two copies can never silently drift.

Background: cognia_public_api/cognia_inference/ ships a HAND-MAINTAINED copy of the
numpy inference engine (qwen2_ops.py + quantization.py) as the standalone public /
HF-Space package. On 2026-06-30 the SWA prefill-corruption bug had to be fixed in BOTH
copies by hand -- the classic "fix one copy, miss the other" trap. This script makes the
canonical files (node/qwen2_ops.py, shattering/quantization.py) the single source of
truth and mechanically re-derives the vendored copies. The ONLY legitimate difference is
the import namespace (shattering./node. -> cognia_inference.), declared per file below.

Usage:
    python scripts/sync_public_engine.py            # rewrite the vendored copies in place
    python scripts/sync_public_engine.py --check     # exit 1 if any copy is out of sync

tests/test_public_engine_sync.py enforces the invariant on every test run, so a future
edit to node/qwen2_ops.py that forgets to re-run this script fails the suite loudly
instead of shipping a stale public engine.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Each vendored file: canonical source -> vendored target, plus exact full-line import
# rewrites. Every `old` line must appear EXACTLY once in the source; a changed/removed
# import therefore breaks sync loudly, forcing a human to review the transform spec.
VENDORED_FILES = [
    {
        "source": "node/qwen2_ops.py",
        "target": "cognia_public_api/cognia_inference/qwen2_ops.py",
        "transforms": {
            "from shattering.quantization import quantize_int4, dequantize_int4":
                "from cognia_inference.quantization import quantize_int4, dequantize_int4",
            "from shattering.model_constants import SWA_WINDOW":
                "from cognia_inference.model_constants import SWA_WINDOW",
            "        from node.build_fast_kernels import build":
                "        from cognia_inference.build_fast_kernels import build  # type: ignore",
        },
    },
    {
        "source": "shattering/quantization.py",
        "target": "cognia_public_api/cognia_inference/quantization.py",
        "transforms": {},  # byte-identical copy (no cross-package imports)
    },
]

# The vendored packages that a public copy must NOT keep importing (they don't exist in
# the standalone package). Any top-level import of these after the declared transforms is
# a spec gap -- a new/renamed canonical import the transform list didn't account for.
_CANONICAL_PKGS = ("shattering", "node")


def _imports_canonical_pkg(line: str) -> bool:
    """True if `line` is an `import`/`from` of a canonical (shattering/node) package."""
    s = line.strip()
    if s.startswith("from "):
        parts = s.split()
        if len(parts) < 2:
            return False
        mod = parts[1]
    elif s.startswith("import "):
        mod = s.split()[1].rstrip(",")
    else:
        return False
    return mod.split(".")[0] in _CANONICAL_PKGS


def render_vendored(source_text: str, transforms: dict) -> str:
    """Apply the declared import rewrites to a canonical source.

    Raises ValueError if a declared line is missing or duplicated, or if any
    canonical-package import survives after the rewrites (spec gap). The transforms
    replace newline-free substrings, so line endings (CRLF on this tree) are preserved.
    """
    out = source_text
    for old, new in transforms.items():
        n = out.count(old)
        if n != 1:
            raise ValueError(
                f"transform line must appear exactly once, found {n}x: {old!r}")
        out = out.replace(old, new)
    for i, line in enumerate(out.splitlines(), 1):
        if _imports_canonical_pkg(line):
            raise ValueError(
                f"line {i}: un-rewritten canonical import survives in vendored output "
                f"(add a transform to VENDORED_FILES): {line!r}")
    return out


def _rendered_for(spec: dict) -> bytes:
    """Read the canonical source for a spec and return the vendored bytes (utf-8)."""
    source = (REPO_ROOT / spec["source"]).read_bytes().decode("utf-8")
    return render_vendored(source, spec["transforms"]).encode("utf-8")


def check() -> list:
    """Return the list of specs whose on-disk vendored target is out of sync."""
    stale = []
    for spec in VENDORED_FILES:
        want = _rendered_for(spec)
        target = REPO_ROOT / spec["target"]
        have = target.read_bytes() if target.exists() else b""
        if want != have:
            stale.append(spec)
    return stale


def sync() -> list:
    """Rewrite every out-of-sync vendored target. Returns the specs that were updated."""
    stale = check()
    for spec in stale:
        (REPO_ROOT / spec["target"]).write_bytes(_rendered_for(spec))
    return stale


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check_only = "--check" in argv
    if check_only:
        stale = check()
        if stale:
            print("[sync_public_engine] OUT OF SYNC:")
            for spec in stale:
                print(f"  {spec['source']} -> {spec['target']}")
            print("Run:  python scripts/sync_public_engine.py")
            return 1
        print("[sync_public_engine] vendored public engine is in sync.")
        return 0
    updated = sync()
    if updated:
        for spec in updated:
            print(f"[sync_public_engine] wrote {spec['target']} <- {spec['source']}")
    else:
        print("[sync_public_engine] already in sync; nothing to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
