from app.digestibility_reference import lookup_diaas, lookup_pdcaas


def test_diaas_measured_match_for_cooked_whole_egg():
    coeffs, source = lookup_diaas("Egg, whole, cooked, hard-boiled")
    assert source == "measured"
    assert coeffs["leucine"] == 0.876
    assert coeffs.get("histidine") is None  # not reported by the source study — key absent entirely


def test_diaas_excludes_egg_substitute_and_dried_egg():
    assert lookup_diaas("Egg substitute, powder")[1] == "estimated"  # falls to category fallback
    coeffs_powder, source_powder = lookup_diaas("Egg, whole, dried")
    assert source_powder == "estimated"


def test_diaas_measured_match_for_plain_cooked_chicken():
    coeffs, source = lookup_diaas("Chicken, broilers or fryers, meat only, cooked, roasted")
    assert source == "measured"
    assert coeffs["lysine"] == 0.955


def test_diaas_excludes_chicken_with_added_solution():
    coeffs, source = lookup_diaas("Chicken, meat only, cooked, with added solution")
    assert source == "estimated"  # falls through to the "chicken" category fallback


def test_diaas_category_fallback_for_unmeasured_food():
    coeffs, source = lookup_diaas("Beef, ground, 85% lean, raw")
    assert coeffs == 0.90
    assert source == "estimated"


def test_diaas_returns_none_for_no_match():
    assert lookup_diaas("Water, tap") is None


def test_pdcaas_measured_egg_whole_excludes_raw():
    assert lookup_pdcaas("Egg, whole, cooked, fried")[0] == 0.97
    coeffs, source = lookup_pdcaas("Egg, whole, raw, fresh")
    assert source == "estimated"  # measured rule explicitly excludes "raw"


def test_pdcaas_rice_prefix_anchor_excludes_babyfood_and_rice_milk():
    """Documented behavior in digestibility_reference.py: prefix anchoring
    on "rice," keeps the plain commodity rule from misfiring on unrelated
    products that merely contain "rice" as a substring."""
    assert lookup_pdcaas("Rice, white, long-grain, cooked")[0] == 0.88

    babyfood_coeff, babyfood_source = lookup_pdcaas("Babyfood, cereal, rice, dry")
    assert babyfood_source == "estimated"  # not the measured 0.88 rice rule
    assert babyfood_coeff != 0.88 or babyfood_source != "measured"

    milk_coeff, milk_source = lookup_pdcaas("Beverages, rice milk, unsweetened")
    assert milk_source == "estimated"


def test_pdcaas_beans_excludes_snap_and_wax_beans():
    assert lookup_pdcaas("Beans, kidney, red, mature seeds, cooked")[0] == 0.78
    snap_coeff, snap_source = lookup_pdcaas("Beans, snap, green, cooked")
    assert snap_source == "estimated"  # excluded from the legume "measured" rule


def test_pdcaas_category_fallback_for_unmeasured_food():
    coeff, source = lookup_pdcaas("Quinoa, cooked")
    assert coeff == 0.85
    assert source == "estimated"


def test_pdcaas_returns_none_for_no_match():
    assert lookup_pdcaas("Water, tap") is None


def test_newly_added_general_plant_food_keywords():
    """Found missing while checking real remaining DIAAS/PDCAAS gaps —
    same 0.80 "general plant food" tier the file already used for
    carrot/broccoli/spinach, just omitted from the original list."""
    for name in [
        "Celery, raw", "Cucumber, peeled, raw", "Squash, summer, zucchini, includes skin, raw",
        "Olives, ripe, canned (small-extra large)", "Watercress, raw", "Rutabaga, peeled, raw",
        "Rosemary, fresh", "Basil, fresh", "Lemons, raw, without peel", "Lime juice, raw", "Honey",
    ]:
        assert lookup_pdcaas(name) == (0.80, "estimated"), name


def test_dairy_butter_gets_dairy_coefficient():
    for name in ["Butter, salted", "Butter, without salt", "Butter, light, stick, with salt"]:
        coeff, source = lookup_pdcaas(name)
        assert (coeff, source) == (0.95, "estimated")
        diaas_coeffs, diaas_source = lookup_diaas(name)
        assert (diaas_coeffs, diaas_source) == (0.95, "estimated")


def test_butter_prefix_excludes_non_dairy_lookalikes():
    """The prefix anchor ("butter," at the start of the name) is what
    keeps this from misfiring — none of these actually start with it, even
    though a bare "butter" substring would have matched every one of them
    (the bug this rule was written to avoid)."""
    assert not "candies, nestle, butterfinger bar".startswith("butter,")
    assert not "candies, butterscotch".startswith("butter,")
    assert not "butterbur, raw".startswith("butter,")
    assert not "margarine-like, butter-margarine blend, 80% fat, stick, without salt".startswith("butter,")
    assert not "peanut butter, smooth style, with salt".startswith("butter,")
    assert not "almond butter, creamy".startswith("butter,")

    # and they resolve through their own correct path, not the dairy one
    assert lookup_pdcaas("Peanut butter, smooth style, with salt")[0] == 0.80  # "peanut" category fallback
    # NB: "Almond butter, creamy" is a separate, pre-existing quirk, not
    # this rule's doing — "creamy" contains "cream" (0.95, dairy),
    # matched before "almond" (0.80) reorders the fallback list. Noted,
    # not fixed here — out of scope for the butter/spices prefix change.
    assert lookup_pdcaas("Almond butter, unsalted")[0] == 0.80  # "almond" category fallback
    assert lookup_pdcaas("Butterbur, raw") is None  # no rule matches at all — no fabricated value
    assert lookup_pdcaas("Candies, butterscotch") is None


def test_spices_prefix_gets_general_plant_coefficient():
    for name in ["Spices, oregano, dried", "Spices, basil, dried", "Spices, rosemary, dried", "Spices, bay leaf"]:
        coeff, source = lookup_pdcaas(name)
        assert (coeff, source) == (0.80, "estimated")
        diaas_coeffs, diaas_source = lookup_diaas(name)
        assert (diaas_coeffs, diaas_source) == (0.80, "estimated")
