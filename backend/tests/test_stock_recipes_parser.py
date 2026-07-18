"""Parser tests — prompt section 16: fractions, ranges, UK units, unicode
quantities, optional ingredients, "to taste", alternatives, sections,
malformed lines."""

from app.stock_recipes.ingredient_parser import parse_ingredient_line, parse_ingredient_lines


def test_plain_mass_unit():
    p = parse_ingredient_line("500 g lean beef mince")
    assert p.quantity_min == p.quantity_max == 500.0
    assert p.unit == "g"
    assert p.name == "lean beef mince"
    assert p.parsing_confidence == 1.0


def test_range_quantity():
    p = parse_ingredient_line("2-3 tbsp olive oil")
    assert p.quantity_min == 2.0
    assert p.quantity_max == 3.0
    assert p.unit == "tbsp"
    assert p.normalised_quantity == 2.5


def test_range_with_to_word():
    p = parse_ingredient_line("2 to 3 cloves garlic")
    assert (p.quantity_min, p.quantity_max) == (2.0, 3.0)
    assert p.unit == "clove"


def test_ascii_mixed_fraction():
    p = parse_ingredient_line("1 1/2 cups plain flour")
    assert p.quantity_min == p.quantity_max == 1.5
    assert p.unit == "cup"


def test_plain_fraction():
    p = parse_ingredient_line("1/2 tsp salt")
    assert p.quantity_min == 0.5
    assert p.unit == "tsp"


def test_unicode_fraction():
    p = parse_ingredient_line("½ tsp bicarbonate of soda")
    assert p.quantity_min == p.quantity_max == 0.5
    assert p.unit == "tsp"


def test_unicode_mixed_fraction():
    p = parse_ingredient_line("1½ tbsp sugar")
    assert p.quantity_min == p.quantity_max == 1.5


def test_uk_units_recognised():
    for raw, unit in [
        ("400 g tin chopped tomatoes", "g"),
        ("2 tsp curry powder", "tsp"),
        ("3 tbsp olive oil", "tbsp"),
        ("2 oz butter", "oz"),
        ("1 lb potatoes", "lb"),
        ("2 tins chopped tomatoes", "tin"),
        ("1 packet stuffing mix", "packet"),
        ("1 jar pasta sauce", "jar"),
        ("4 cloves garlic", "clove"),
        ("2 slices bread", "slice"),
    ]:
        p = parse_ingredient_line(raw)
        assert p.unit == unit, raw


def test_optional_ingredient():
    p = parse_ingredient_line("3-4 eggs (optional)")
    assert p.optional is True
    assert p.name == "eggs"


def test_to_taste():
    p = parse_ingredient_line("Salt and pepper, to taste")
    assert p.optional is True
    assert p.quantity_min is None
    assert "to taste" in p.prep_note


def test_alternatives():
    p = parse_ingredient_line("Butter or olive oil, for frying")
    assert p.name == "Butter"
    assert p.alternatives


def test_alternatives_with_unit():
    p = parse_ingredient_line("1 tbsp Worcestershire sauce or Henderson's relish")
    assert p.name == "Worcestershire sauce"
    assert p.alternatives == ["Henderson's relish"]


def test_plus_extra():
    p = parse_ingredient_line("1 tbsp olive oil, plus extra for frying")
    assert p.quantity_min == 1.0
    assert "plus extra" in p.prep_note


def test_divided():
    p = parse_ingredient_line("1 onion, divided")
    assert p.optional is False
    assert "divided" in p.prep_note


def test_to_serve():
    p = parse_ingredient_line("Fresh basil, to serve")
    assert p.optional is True
    assert "to serve" in p.prep_note


def test_multipack_notation():
    p = parse_ingredient_line("2 x 400g tins chopped tomatoes")
    assert p.quantity_min == p.quantity_max == 800.0
    assert p.unit == "g"


def test_dual_unit_annotation_discarded():
    p = parse_ingredient_line("400g/14oz can chickpeas, drained and rinsed")
    assert p.quantity_min == 400.0
    assert p.unit == "g"
    assert "14oz" not in p.name


def test_juice_of_idiom():
    p = parse_ingredient_line("Juice of 1 lemon")
    assert p.quantity_min == 1.0
    assert p.name == "lemon juice"


def test_zest_of_idiom():
    p = parse_ingredient_line("Zest of 2 limes")
    assert p.quantity_min == 2.0
    assert p.name == "limes zest"


def test_article_unit_idiom():
    p = parse_ingredient_line("A large pinch of salt")
    assert p.quantity_min == 1.0
    assert p.unit == "pinch"
    assert p.name == "salt"


def test_prep_note_parenthetical():
    p = parse_ingredient_line("1 large onion (peeled and finely diced)")
    assert p.prep_note == "peeled and finely diced"
    assert p.name == "large onion"


def test_prep_note_trailing_comma():
    p = parse_ingredient_line("2 cloves garlic, crushed")
    assert p.prep_note == "crushed"
    assert p.name == "garlic"


def test_bare_count_no_unit():
    p = parse_ingredient_line("2 onions")
    assert p.quantity_min == 2.0
    assert p.unit is None
    assert p.name == "onions"


def test_malformed_empty_line_never_raises():
    p = parse_ingredient_line("")
    assert p.parsing_confidence == 0.0
    assert p.quantity_min is None


def test_malformed_whitespace_only():
    p = parse_ingredient_line("   ")
    assert p.parsing_confidence == 0.0


def test_no_quantity_at_all():
    p = parse_ingredient_line("low calorie cooking spray")
    assert p.quantity_min is None
    assert p.name == "low calorie cooking spray"
    assert p.parsing_confidence < 1.0


def test_sections_tracked_across_list():
    parsed = parse_ingredient_lines(
        ["For the sauce:", "2 tbsp olive oil", "1 onion, chopped", "To serve", "Fresh coriander"]
    )
    assert [p.name for p in parsed] == ["olive oil", "onion", "Fresh coriander"]
    assert parsed[0].section == "For the sauce"
    assert parsed[1].section == "For the sauce"
    assert parsed[2].section == "To serve"


def test_parse_ingredient_lines_skips_blank_lines():
    parsed = parse_ingredient_lines(["2 eggs", "", "  ", "1 onion"])
    assert len(parsed) == 2


def test_never_invents_a_quantity():
    for raw in ["Salt, to taste", "A pinch of pepper", "Fresh coriander, to serve"]:
        p = parse_ingredient_line(raw)
        # normalised_quantity is only non-None when the line actually stated
        # (or the idiom rewrite established) an amount
        if p.quantity_min is None:
            assert p.normalised_quantity is None
