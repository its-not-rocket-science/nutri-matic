"""Tests for candidate_metadata.py — prompt 5: layered practical
metadata, safe category defaults, and the "exclude unknown/unsuitable by
default" fallback."""

import pytest

from app.candidate_metadata import (
    CandidateKind,
    FoodGroup,
    ServingRange,
    is_plausible_serving,
    resolve_candidate_metadata,
)
from app.models import Food


def make_food(name, data_type="sr_legacy_food"):
    return Food(id=1, name=name, protein_g_per_100g=1.0, amino_acids={}, data_type=data_type)


def test_serving_range_rejects_invalid_ordering():
    with pytest.raises(ValueError):
        ServingRange(minimum_g=100, default_g=50, maximum_g=200)  # default below minimum
    with pytest.raises(ValueError):
        ServingRange(minimum_g=100, default_g=150, maximum_g=120)  # maximum below default
    with pytest.raises(ValueError):
        ServingRange(minimum_g=0, default_g=0, maximum_g=0)


def test_serving_range_contains():
    serving = ServingRange(50, 100, 150)
    assert serving.contains(100) is True
    assert serving.contains(50) is True
    assert serving.contains(150) is True
    assert serving.contains(49) is False
    assert serving.contains(151) is False


def test_curated_food_resolves_with_real_serving_range():
    metadata = resolve_candidate_metadata(make_food("Bananas, raw"))
    assert metadata.source == "curated"
    assert metadata.food_group == FoodGroup.FRUIT
    assert metadata.suitable_for_direct_suggestion is True
    assert metadata.serving.default_g > 0


def test_branded_food_excluded_even_if_name_would_otherwise_match():
    metadata = resolve_candidate_metadata(make_food("Banana, raw", data_type="branded_food"))
    assert metadata.suitable_for_direct_suggestion is False
    assert metadata.source == "unknown_excluded"


@pytest.mark.parametrize("name", [
    "Baking powder, double acting",
    "Spices, parsley, dried",
    "Oil, olive",
    "Soup, beef broth, bouillon cube",
    "Whey protein powder, isolate",
])
def test_known_bad_standalone_suggestions_excluded(name):
    metadata = resolve_candidate_metadata(make_food(name))
    assert metadata.suitable_for_direct_suggestion is False


def test_category_default_applies_to_uncurated_yogurt_brand_variant():
    metadata = resolve_candidate_metadata(make_food("Yogurt, plain, low fat"))
    assert metadata.source == "category_default"
    assert metadata.suitable_for_direct_suggestion is True
    assert metadata.food_group == FoodGroup.DAIRY


def test_truly_unknown_food_excluded_by_default():
    metadata = resolve_candidate_metadata(make_food("Some Obscure Ingredient Nobody Curated"))
    assert metadata.suitable_for_direct_suggestion is False
    assert metadata.source == "unknown_excluded"


def test_raw_meat_and_fish_never_fall_through_to_a_safe_default():
    """Regression guard: there must be no blanket "contains 'raw'"
    fallback that could mark an uncurated raw meat/fish/egg as safe to
    suggest as-is — a real safety concern, not just an odd suggestion."""
    for name in ("Chicken, raw", "Salmon, raw", "Beef, raw", "Pork, raw"):
        metadata = resolve_candidate_metadata(make_food(name))
        if metadata.suitable_for_direct_suggestion:
            assert metadata.requires_preparation is True, (
                f"{name!r} resolved as directly suggestible without requiring preparation"
            )


def test_is_plausible_serving_reflects_metadata_range():
    metadata = resolve_candidate_metadata(make_food("Bananas, raw"))
    assert is_plausible_serving(metadata, metadata.serving.default_g) is True
    assert is_plausible_serving(metadata, metadata.serving.maximum_g * 10) is False


def test_condiment_is_flagged_as_normally_added_to_another_meal():
    metadata = resolve_candidate_metadata(make_food("Peanut butter, smooth style without salt"))
    assert metadata.kind == CandidateKind.CONDIMENT
    assert metadata.normally_added_to_another_meal is True
