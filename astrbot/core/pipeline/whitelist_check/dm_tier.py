"""Single DM permission and quota policy shared by core and Router."""

DM_TIER_LIMITS = {
    0: (0, 0, 0),
    1: (100, 1000, 0),
    2: (300, 3000, 500),
    3: (600, 12000, 1500),
    4: (600, 12000, 1500),
}


def get_dm_tier(origin: str, settings: dict) -> int:
    tiers = settings.get("dm_tiers", {})
    if not isinstance(tiers, dict):
        return 0
    tier = tiers.get(origin, 0)
    return tier if type(tier) is int and tier in DM_TIER_LIMITS else 0
