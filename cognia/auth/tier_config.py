"""
cognia/auth/tier_config.py
==========================
Tier definitions for Cognia API monetization.

Tiers: free, pro, enterprise, local.
"""

TIERS = {
    "free": {
        "rate_limit_per_min": 100,
        "max_goals": 10,
        "max_webhooks": 3,
        "web_search": True,
        "export_history": True,
        "debug_endpoint": False,
        "max_keys": 3,
    },
    "pro": {
        "rate_limit_per_min": 500,
        "max_goals": 100,
        "max_webhooks": 20,
        "web_search": True,
        "export_history": True,
        "debug_endpoint": False,
        "max_keys": 10,
    },
    "enterprise": {
        "rate_limit_per_min": 0,  # 0 = no limit
        "max_goals": -1,          # -1 = unlimited
        "max_webhooks": -1,
        "web_search": True,
        "export_history": True,
        "debug_endpoint": True,
        "max_keys": -1,
    },
    "local": {
        "rate_limit_per_min": 200,  # local mode without key
        "max_goals": -1,
        "max_webhooks": -1,
        "web_search": True,
        "export_history": True,
        "debug_endpoint": False,
        "max_keys": -1,
    },
}


def get_tier_config(tier: str) -> dict:
    return TIERS.get(tier, TIERS["free"])


def get_rate_limit(tier: str) -> int:
    return get_tier_config(tier)["rate_limit_per_min"]


def check_feature(tier: str, feature: str) -> bool:
    return get_tier_config(tier).get(feature, False)
