"""Tests for app.inspect_fdc_release (prompts.txt PROMPT 11) -- the
read-only, evidence-only FDC release-metadata inspection command."""

from app.inspect_fdc_release import inspect_directory


def test_matching_directory_name_produces_a_low_confidence_hint(tmp_path):
    directory = tmp_path / "FoodData_Central_foundation_food_csv_2026-04-30"
    directory.mkdir()

    findings = inspect_directory(directory)

    assert findings["directory_name_hint"]["dataset"] == "foundation_food"
    assert findings["directory_name_hint"]["date"] == "2026-04-30"
    assert "low" in findings["directory_name_hint"]["confidence"]
    assert "never promoted to upstream_release_version" in findings["directory_name_hint"]["confidence"]


def test_non_matching_directory_name_produces_no_hint(tmp_path):
    directory = tmp_path / "FoodData_Central_sr_legacy_food_csv_2018-04"  # month-only, not a full date
    directory.mkdir()

    findings = inspect_directory(directory)

    assert findings["directory_name_hint"] is None


def test_conversion_factor_files_are_never_flagged_as_metadata(tmp_path):
    """Regression: "version" is a substring of "conversion" -- a
    substring-based match previously false-flagged every real FDC
    export's *_conversion_factor.csv data files as metadata. Caught by
    testing this module against the real downloaded FDC directories
    before relying on it."""
    directory = tmp_path / "some_fdc_dir"
    directory.mkdir()
    (directory / "food_calorie_conversion_factor.csv").write_text("a,b\n1,2\n")
    (directory / "food_nutrient_conversion_factor.csv").write_text("a,b\n1,2\n")

    findings = inspect_directory(directory)

    assert findings["metadata_files_found"] == []


def test_readme_and_metadata_named_files_are_flagged(tmp_path):
    directory = tmp_path / "some_fdc_dir"
    directory.mkdir()
    (directory / "README.txt").write_text("this file describes the release\n")
    (directory / "metadata.json").write_text("{}\n")
    (directory / "food.csv").write_text("a,b\n1,2\n")

    findings = inspect_directory(directory)

    names_found = {p.split("\\")[-1].split("/")[-1] for p in findings["metadata_files_found"]}
    assert names_found == {"README.txt", "metadata.json"}


def test_subdirectories_are_never_treated_as_files(tmp_path):
    """inspect_directory must skip subdirectories entirely -- only real
    files are candidates for the metadata-filename check."""
    (tmp_path / "readme_subdir").mkdir()

    findings = inspect_directory(tmp_path)

    assert findings["metadata_files_found"] == []
