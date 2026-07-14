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
