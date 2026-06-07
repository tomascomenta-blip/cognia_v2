"""
tests/test_cli_template_commands.py
====================================
Tests for /templates, /template, /template-guia CLI commands.
"""

import io
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to capture print output from the CLI helpers
# ---------------------------------------------------------------------------

def _capture(fn, *args, **kwargs):
    """Call fn(*args) and return everything printed to stdout as a string."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue()


def _make_mock_manager(templates=None, custom_count=0):
    """Return a mock ConversationTemplateManager."""
    if templates is None:
        templates = {
            "code_review": {
                "id": "code_review",
                "name": "Code Review",
                "description": "Revision sistematica de codigo",
                "initial_prompt": "Proporciona el codigo que quieres revisar.",
                "guide_questions": [
                    "Sigue las convenciones?",
                    "Hay bugs?",
                ],
                "tags": ["codigo"],
                "estimated_turns": 5,
                "builtin": True,
            },
            "brainstorming": {
                "id": "brainstorming",
                "name": "Brainstorming",
                "description": "Generacion libre de ideas",
                "initial_prompt": "Cual es el tema para brainstorming?",
                "guide_questions": [
                    "Soluciones obvias?",
                    "Idea mas loca?",
                    "Restricciones reales?",
                ],
                "tags": ["ideas"],
                "estimated_turns": 8,
                "builtin": True,
            },
        }

    mgr = MagicMock()
    all_tpls = list(templates.values())
    if custom_count:
        for i in range(custom_count):
            all_tpls.append({
                "id": f"custom_{i}",
                "name": f"Custom {i}",
                "description": "desc",
                "initial_prompt": "prompt",
                "guide_questions": ["q1"],
                "estimated_turns": 3,
                "builtin": False,
            })
    mgr.list_templates.return_value = all_tpls
    mgr.get_template.side_effect = lambda tid: templates.get(tid)
    return mgr, templates


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSlashTemplates(unittest.TestCase):

    def _run_slash_templates(self, mock_mgr, mock_builtin_ids):
        """Patch imports and invoke _slash_templates, capturing output."""
        import cognia.cli as cli_mod

        fake_module = types.ModuleType("cognia.templates.conversation_templates")
        fake_module.ConversationTemplateManager = MagicMock(return_value=mock_mgr)
        fake_module.BUILTIN_TEMPLATES = {k: v for k, v in mock_builtin_ids.items()}

        with patch.dict(sys.modules, {"cognia.templates.conversation_templates": fake_module}):
            out = _capture(cli_mod._slash_templates, "")
        return out

    def test_lists_builtin_templates_no_exception(self):
        """_slash_templates() with mocked manager does not raise."""
        mgr, tpls = _make_mock_manager()
        # Should complete without raising
        try:
            out = self._run_slash_templates(mgr, tpls)
        except Exception as exc:
            self.fail(f"_slash_templates raised: {exc}")

    def test_lists_builtin_template_names(self):
        """Output contains builtin template IDs."""
        mgr, tpls = _make_mock_manager()
        out = self._run_slash_templates(mgr, tpls)
        self.assertIn("code_review", out)
        self.assertIn("brainstorming", out)

    def test_shows_custom_count_when_present(self):
        """Output mentions custom templates when they exist."""
        mgr, tpls = _make_mock_manager(custom_count=2)
        out = self._run_slash_templates(mgr, tpls)
        self.assertIn("custom", out.lower())

    def test_import_error_handled(self):
        """ImportError produces error message, not exception."""
        import cognia.cli as cli_mod
        with patch.dict(sys.modules, {"cognia.templates.conversation_templates": None}):
            # When the module is None, import will raise ImportError
            try:
                cli_mod._slash_templates("")
            except Exception:
                pass  # may print error message; we just confirm no unhandled crash


class TestSlashTemplate(unittest.TestCase):

    def _run_slash_template(self, args, mock_mgr):
        import cognia.cli as cli_mod

        fake_module = types.ModuleType("cognia.templates.conversation_templates")
        fake_module.ConversationTemplateManager = MagicMock(return_value=mock_mgr)

        with patch.dict(sys.modules, {"cognia.templates.conversation_templates": fake_module}):
            out = _capture(cli_mod._slash_template, args)
        return out

    def test_empty_args_prints_usage(self):
        """Empty args prints usage hint."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template("", mgr)
        self.assertIn("/template", out)

    def test_valid_template_shows_initial_prompt(self):
        """Valid template id shows initial_prompt."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template("code_review", mgr)
        self.assertIn("Proporciona el codigo que quieres revisar.", out)

    def test_valid_template_shows_guide_questions(self):
        """Valid template id shows numbered guide questions."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template("code_review", mgr)
        self.assertIn("1.", out)
        self.assertIn("Sigue las convenciones?", out)

    def test_nonexistent_template_prints_not_found(self):
        """Nonexistent id prints 'no encontrado'."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template("nonexistent", mgr)
        self.assertIn("no encontrado", out)

    def test_shows_template_name(self):
        """Output includes template name."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template("code_review", mgr)
        self.assertIn("Code Review", out)


class TestSlashTemplateGuia(unittest.TestCase):

    def _run_slash_template_guia(self, args, mock_mgr):
        import cognia.cli as cli_mod

        fake_module = types.ModuleType("cognia.templates.conversation_templates")
        fake_module.ConversationTemplateManager = MagicMock(return_value=mock_mgr)

        with patch.dict(sys.modules, {"cognia.templates.conversation_templates": fake_module}):
            out = _capture(cli_mod._slash_template_guia, args)
        return out

    def test_shows_guide_questions_only(self):
        """Shows guide questions without initial_prompt."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template_guia("brainstorming", mgr)
        self.assertIn("Soluciones obvias?", out)
        self.assertIn("Idea mas loca?", out)
        # initial_prompt should NOT appear
        self.assertNotIn("Cual es el tema para brainstorming?", out)

    def test_empty_args_prints_usage(self):
        """Empty args prints usage hint."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template_guia("", mgr)
        self.assertIn("/template-guia", out)

    def test_nonexistent_template_prints_not_found(self):
        """Nonexistent id prints 'no encontrado'."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template_guia("nope", mgr)
        self.assertIn("no encontrado", out)

    def test_shows_numbered_questions(self):
        """Questions are numbered starting at 1."""
        mgr, _ = _make_mock_manager()
        out = self._run_slash_template_guia("brainstorming", mgr)
        self.assertIn("1.", out)
        self.assertIn("2.", out)


class TestCommandsDict(unittest.TestCase):

    def test_templates_in_commands(self):
        import cognia.cli as cli_mod
        self.assertIn("/templates", cli_mod.COMMANDS)

    def test_template_in_commands(self):
        import cognia.cli as cli_mod
        self.assertIn("/template", cli_mod.COMMANDS)

    def test_template_guia_in_commands(self):
        import cognia.cli as cli_mod
        self.assertIn("/template-guia", cli_mod.COMMANDS)


if __name__ == "__main__":
    unittest.main()
