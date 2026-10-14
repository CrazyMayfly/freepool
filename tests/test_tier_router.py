from app import tier_router
from app.tier_router import Tier


def _tiers():
    return {
        "fast": Tier("fast", "快速档", ["a-flash", "b-flash"]),
        "max": Tier("max", "旗舰档", ["x-max", "y-max"]),
    }


def test_alias_resolves_to_full_chain():
    tier, candidates = tier_router.resolve_candidates("fast", _tiers())
    assert tier == "fast"
    assert candidates == ["a-flash", "b-flash"]


def test_concrete_model_falls_back_within_tier():
    tier, candidates = tier_router.resolve_candidates("a-flash", _tiers())
    assert tier is None
    assert candidates == ["a-flash", "b-flash"]


def test_unknown_model_passes_through():
    tier, candidates = tier_router.resolve_candidates("whatever", _tiers())
    assert tier is None
    assert candidates == ["whatever"]


def test_empty_request():
    assert tier_router.resolve_candidates("", _tiers()) == (None, [])
    assert tier_router.resolve_candidates(None, _tiers()) == (None, [])
