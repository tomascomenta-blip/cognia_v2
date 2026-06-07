"""
tests/test_tier_config.py
=========================
Unit tests for cognia/auth/tier_config.py
"""

import pytest
from cognia.auth.tier_config import get_tier_config, get_rate_limit, check_feature


def test_free_rate_limit():
    assert get_tier_config("free")["rate_limit_per_min"] == 100


def test_enterprise_rate_limit_zero():
    assert get_tier_config("enterprise")["rate_limit_per_min"] == 0


def test_pro_rate_limit():
    assert get_rate_limit("pro") == 500


def test_enterprise_debug_enabled():
    assert check_feature("enterprise", "debug_endpoint") is True


def test_free_debug_disabled():
    assert check_feature("free", "debug_endpoint") is False


def test_unknown_tier_falls_back_to_free():
    cfg = get_tier_config("unknown_tier")
    assert cfg == get_tier_config("free")
