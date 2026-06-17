"""
Regression: when COGNIA_AGENT_WORKSPACE is unset, the agent's write workspace
must default to the CURRENT working directory (where the user launched Cognia),
NOT a hidden folder inside the installed package.

Before the fix the default was <repo>/agent_workspace, which on a PyPI install
resolves inside site-packages -- so "crea esto en esta carpeta" wrote the file
into site-packages\agent_workspace, invisible to the user.
"""
import importlib
from pathlib import Path

import cognia.agents.workers.dev_tools as dev_tools


def test_default_workspace_is_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIA_AGENT_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    try:
        importlib.reload(dev_tools)
        assert Path(dev_tools.AGENT_WORKSPACE_ROOT).resolve() == tmp_path.resolve()
        # And the default workspace must NOT sit inside the installed package.
        assert "site-packages" not in str(dev_tools.AGENT_WORKSPACE_ROOT).lower()
    finally:
        # Restore the module to a clean state for the rest of the suite.
        importlib.reload(dev_tools)


def test_env_override_still_wins(tmp_path, monkeypatch):
    forced = tmp_path / "sandbox_fijo"
    forced.mkdir()
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(forced))
    try:
        importlib.reload(dev_tools)
        assert Path(dev_tools.AGENT_WORKSPACE_ROOT).resolve() == forced.resolve()
    finally:
        monkeypatch.delenv("COGNIA_AGENT_WORKSPACE", raising=False)
        importlib.reload(dev_tools)
