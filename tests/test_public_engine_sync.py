"""
tests/test_public_engine_sync.py
================================
Enforce that the vendored public-API inference engine
(cognia_public_api/cognia_inference/) stays byte-for-byte derivable from the canonical
node/+shattering sources. This closes the "fix one copy, miss the other" drift trap that
let the SWA prefill-corruption bug (2026-06-30) live independently in both engine copies.

The single source of truth for the transform is scripts/sync_public_engine.py. If any
canonical engine file is edited without re-running that script, these tests fail and point
at the exact command to run.
"""
import sys
from pathlib import Path

import pytest

# Allow importing scripts/ directly (same pattern as tests/test_export_kg.py)
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from sync_public_engine import (  # noqa: E402
    REPO_ROOT,
    VENDORED_FILES,
    check,
    render_vendored,
    _rendered_for,
)


class TestVendoredCopiesInSync:
    """The on-disk vendored copies must equal the freshly-rendered canonical sources."""

    @pytest.mark.parametrize("spec", VENDORED_FILES, ids=lambda s: s["target"])
    def test_target_matches_rendered_source(self, spec):
        want = _rendered_for(spec)
        target = REPO_ROOT / spec["target"]
        assert target.exists(), f"vendored file missing: {spec['target']}"
        have = target.read_bytes()
        assert have == want, (
            f"{spec['target']} has drifted from {spec['source']}. "
            f"Run:  python scripts/sync_public_engine.py"
        )

    def test_check_reports_all_in_sync(self):
        stale = check()
        assert stale == [], (
            "out-of-sync vendored engine files: "
            + ", ".join(s["target"] for s in stale)
            + " -- run python scripts/sync_public_engine.py"
        )

    def test_no_canonical_import_survives_in_vendored(self):
        # Whatever the sync produced, the vendored copies must not import shattering/node.
        for spec in VENDORED_FILES:
            text = (REPO_ROOT / spec["target"]).read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                s = line.strip()
                mod = None
                if s.startswith("from "):
                    parts = s.split()
                    mod = parts[1] if len(parts) > 1 else None
                elif s.startswith("import "):
                    mod = s.split()[1].rstrip(",")
                if mod and mod.split(".")[0] in ("shattering", "node"):
                    pytest.fail(
                        f"{spec['target']}:{i} imports a canonical package: {line!r}"
                    )


class TestRenderGuards:
    """render_vendored must refuse silently-wrong output (drift-guard behaviour)."""

    def test_missing_transform_line_raises(self):
        # A canonical source that no longer contains a declared transform line must fail
        # loudly rather than emit a copy with a stale/absent import.
        src = "import numpy as np\nx = 1\n"
        with pytest.raises(ValueError):
            render_vendored(src, {"from shattering.model_constants import SWA_WINDOW":
                                  "from cognia_inference.model_constants import SWA_WINDOW"})

    def test_duplicate_transform_line_raises(self):
        src = "from foo import bar\nfrom foo import bar\n"
        with pytest.raises(ValueError):
            render_vendored(src, {"from foo import bar": "from baz import bar"})

    def test_untransformed_canonical_import_raises(self):
        # A NEW canonical import the transform spec didn't cover must be caught, not
        # silently shipped into the standalone public package.
        src = "from shattering.new_module import thing\nx = 1\n"
        with pytest.raises(ValueError):
            render_vendored(src, {})

    def test_clean_source_passes_through(self):
        src = "import numpy as np\nfrom cognia_inference.x import y\nz = 2\n"
        assert render_vendored(src, {}) == src


class TestModelConstantsSharedValues:
    """model_constants.py is a curated SUBSET in the vendored copy (it omits the persona
    prompt). It is not regenerated, but every constant it DOES share with the canonical
    module must have an identical value -- catches e.g. an SWA_WINDOW drift."""

    @staticmethod
    def _load_constants(rel_path):
        ns = {}
        src = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        exec(compile(src, str(rel_path), "exec"), ns)  # pure constant module, no imports
        return {k: v for k, v in ns.items() if not k.startswith("__")}

    def test_shared_constants_have_equal_values(self):
        canonical = self._load_constants("shattering/model_constants.py")
        vendored = self._load_constants(
            "cognia_public_api/cognia_inference/model_constants.py")
        shared = set(canonical) & set(vendored)
        assert shared, "expected shared constants between the two model_constants copies"
        mismatched = {k: (canonical[k], vendored[k])
                      for k in shared if canonical[k] != vendored[k]}
        assert not mismatched, f"model_constants drift on shared keys: {mismatched}"

    def test_swa_window_matches(self):
        canonical = self._load_constants("shattering/model_constants.py")
        vendored = self._load_constants(
            "cognia_public_api/cognia_inference/model_constants.py")
        assert canonical["SWA_WINDOW"] == vendored["SWA_WINDOW"]
