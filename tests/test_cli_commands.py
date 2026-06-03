"""
tests/test_cli_commands.py
Tests for CLI commands added in cycles 9-12.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from unittest.mock import MagicMock, patch


class TestSlashAprendeRepo:
    """Tests for _slash_aprende_repo helper."""

    def test_no_repos_found_returns_message(self):
        from cognia.cli import _slash_aprende_repo
        ai = MagicMock()
        mock_scraper = MagicMock()
        mock_scraper.search_repos.return_value = []
        with patch("cognia.research_engine.github_scraper.GitHubScraper", return_value=mock_scraper):
            result = _slash_aprende_repo(ai, "nonexistent_xyz_query_abc")
        assert "No se encontraron" in result

    def test_query_stores_repos(self):
        from cognia.cli import _slash_aprende_repo
        ai = MagicMock()
        mock_repo = MagicMock()
        mock_repo.to_learning_text.return_value = "Repositorio: test_repo\n\nREADME content here"
        mock_repo.label.return_value = "test_repo (Python)"
        mock_repo.repo_name = "owner/test_repo"
        mock_scraper = MagicMock()
        mock_scraper.search_repos.return_value = [mock_repo]
        with patch("cognia.research_engine.github_scraper.GitHubScraper", return_value=mock_scraper):
            result = _slash_aprende_repo(ai, "machine learning")
        ai.observe.assert_called_once()
        assert "test_repo" in result

    def test_github_url_uses_search_repos(self):
        from cognia.cli import _slash_aprende_repo
        ai = MagicMock()
        mock_repo = MagicMock()
        mock_repo.to_learning_text.return_value = "Repositorio: transformers"
        mock_repo.label.return_value = "transformers (Python)"
        mock_repo.repo_name = "huggingface/transformers"
        mock_scraper = MagicMock()
        mock_scraper.search_repos.return_value = [mock_repo]
        with patch("cognia.research_engine.github_scraper.GitHubScraper", return_value=mock_scraper):
            result = _slash_aprende_repo(ai, "https://github.com/huggingface/transformers")
        assert ai.observe.called
        assert "transformers" in result

    def test_github_url_fallback_on_empty_result(self):
        from cognia.cli import _slash_aprende_repo
        ai = MagicMock()
        mock_scraper = MagicMock()
        # First call (full repo path) returns empty, second call (repo name only) also empty
        mock_scraper.search_repos.return_value = []
        with patch("cognia.research_engine.github_scraper.GitHubScraper", return_value=mock_scraper):
            result = _slash_aprende_repo(ai, "https://github.com/owner/some-repo")
        assert "No se encontraron" in result

    def test_observe_exception_does_not_crash(self):
        from cognia.cli import _slash_aprende_repo
        ai = MagicMock()
        ai.observe.side_effect = RuntimeError("observe failed")
        mock_repo = MagicMock()
        mock_repo.to_learning_text.return_value = "some text"
        mock_repo.label.return_value = "repo (Python)"
        mock_repo.repo_name = "owner/repo"
        mock_scraper = MagicMock()
        mock_scraper.search_repos.return_value = [mock_repo]
        with patch("cognia.research_engine.github_scraper.GitHubScraper", return_value=mock_scraper):
            result = _slash_aprende_repo(ai, "some query")
        # Should not raise; stored count is 0
        assert "No se pudo" in result

    def test_import_error_returns_message(self):
        from cognia.cli import _slash_aprende_repo
        ai = MagicMock()
        with patch.dict("sys.modules", {"cognia.research_engine.github_scraper": None}):
            result = _slash_aprende_repo(ai, "anything")
        assert "no disponible" in result.lower()


class TestSkillsParsing:
    """Tests for skill frontmatter parsing."""

    def test_parse_frontmatter_valid(self):
        from cognia.cli import _parse_frontmatter
        text = "---\nname: test\ndescription: test desc\n---\n\nBody content here"
        meta, body = _parse_frontmatter(text)
        assert meta.get("name") == "test"
        assert meta.get("description") == "test desc"
        assert "Body content here" in body

    def test_parse_frontmatter_missing_returns_empty_meta(self):
        from cognia.cli import _parse_frontmatter
        text = "No frontmatter here, just body text"
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert "body text" in body

    def test_parse_frontmatter_body_not_in_meta(self):
        from cognia.cli import _parse_frontmatter
        text = "---\nname: myskill\n---\n\nThis is the skill body."
        meta, body = _parse_frontmatter(text)
        assert meta == {"name": "myskill"}
        assert "This is the skill body." in body

    def test_parse_frontmatter_unclosed_returns_empty_meta(self):
        from cognia.cli import _parse_frontmatter
        # Opening --- but no closing --- means no frontmatter parsed
        text = "---\nname: orphan\nno closing"
        meta, body = _parse_frontmatter(text)
        assert meta == {}


class TestCommandsDict:
    """Verify all expected commands are registered."""

    def test_new_commands_present(self):
        from cognia.cli import COMMANDS
        for cmd in [
            "/aprende-repo",
            "/pensar",
            "/revisar",
            "/memoria-stats",
            "/diff",
            "/hacer",
        ]:
            assert cmd in COMMANDS, f"Missing command: {cmd}"

    def test_aprende_repo_description(self):
        from cognia.cli import COMMANDS
        assert "GitHub" in COMMANDS["/aprende-repo"] or "repo" in COMMANDS["/aprende-repo"].lower()

    def test_plan_commands_present(self):
        from cognia.cli import COMMANDS
        for cmd in ["/plan", "/plan-ver", "/plan-ok", "/plan-borrar"]:
            assert cmd in COMMANDS, f"Missing command: {cmd}"


class TestPlanSystem:
    """Tests for /plan persistent task planning system."""

    def test_plans_load_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        result = cli_mod._plans_load()
        assert result == {"plans": []}

    def test_plans_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        data = {"plans": [{"id": "p1", "goal": "test", "created": "2026-05-30T10:00:00", "steps": []}]}
        cli_mod._plans_save(data)
        result = cli_mod._plans_load()
        assert result["plans"][0]["id"] == "p1"

    def test_next_id_empty(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        assert cli_mod._plans_next_id({"plans": []}) == "p1"

    def test_next_id_increments(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        data = {"plans": [{"id": "p3", "goal": "x", "created": "now", "steps": []}]}
        assert cli_mod._plans_next_id(data) == "p4"

    def test_plan_ok_marks_step(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        data = {"plans": [{"id": "p1", "goal": "test", "created": "now",
                           "steps": [{"text": "step1", "done": False}, {"text": "step2", "done": False}]}]}
        cli_mod._plans_save(data)
        result = cli_mod._slash_plan_ok("p1", 1)
        assert "completado" in result.lower()
        loaded = cli_mod._plans_load()
        assert loaded["plans"][0]["steps"][0]["done"] is True
        assert loaded["plans"][0]["steps"][1]["done"] is False

    def test_plan_ok_invalid_step(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        data = {"plans": [{"id": "p1", "goal": "test", "created": "now",
                           "steps": [{"text": "step1", "done": False}]}]}
        cli_mod._plans_save(data)
        result = cli_mod._slash_plan_ok("p1", 99)
        assert "invalido" in result.lower() or "invalid" in result.lower()

    def test_plan_ok_unknown_id(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        cli_mod._plans_save({"plans": []})
        result = cli_mod._slash_plan_ok("p99", 1)
        assert "no encontrado" in result.lower()

    def test_plan_ver_empty(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        cli_mod._plans_save({"plans": []})
        result = cli_mod._slash_plan_ver()
        assert "No hay planes" in result

    def test_plan_ver_shows_plans(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        data = {"plans": [{"id": "p1", "goal": "mi objetivo", "created": "now",
                           "steps": [{"text": "hacer algo", "done": False}]}]}
        cli_mod._plans_save(data)
        result = cli_mod._slash_plan_ver()
        assert "mi objetivo" in result
        assert "[ ]" in result

    def test_plan_borrar(self, tmp_path, monkeypatch):
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        data = {"plans": [{"id": "p1", "goal": "test", "created": "now", "steps": []}]}
        cli_mod._plans_save(data)
        result = cli_mod._slash_plan_borrar("p1")
        assert "eliminado" in result.lower()
        assert cli_mod._plans_load() == {"plans": []}

    def test_plan_crear_no_llm_steps(self, tmp_path, monkeypatch):
        """When LLM returns no parseable steps, returns error message."""
        import cognia.cli as cli_mod
        monkeypatch.setattr(cli_mod, '_PLANS_PATH', tmp_path / "cognia_plans.json")
        mock_result = MagicMock()
        mock_result.text = ""  # empty LLM output
        mock_orch = MagicMock()
        mock_orch.infer.return_value = mock_result
        ai = MagicMock()
        ai._orchestrator = mock_orch
        result = cli_mod._slash_plan_crear(ai, "test goal")
        assert "No se pudo" in result or "objetivo" in result.lower()
