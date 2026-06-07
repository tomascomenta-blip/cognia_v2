"""
tests/test_comprehensive_report.py
====================================
5 tests for ComprehensiveReportGenerator.
"""

import os
import tempfile

import pytest

from cognia.export.comprehensive_report import ComprehensiveReportGenerator


@pytest.fixture
def gen():
    return ComprehensiveReportGenerator()


def test_generate_returns_nonempty_string(gen):
    result = gen.generate()
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_contains_header(gen):
    result = gen.generate()
    assert "Reporte Cognia" in result


def test_generate_contains_objetivos_section(gen):
    result = gen.generate()
    assert "## Objetivos" in result


def test_generate_no_crash_with_no_data(gen):
    """Should not raise even when all subsystems are unavailable / DB empty."""
    result = gen.generate(period_days=1, user_id="nonexistent_user_xyz")
    assert isinstance(result, str)
    assert "Reporte Cognia" in result


def test_save_creates_file(gen):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "report_test.md")
        saved = gen.save(path)
        assert os.path.isfile(saved)
        with open(saved, encoding="utf-8") as f:
            content = f.read()
        assert "Reporte Cognia" in content
