"""Structural checks on .github/workflows/demo-purge.yml — operational-
hardening prompt 1's "scheduled workflow configuration is tested/linted
where practical" acceptance criterion. Parses the real YAML (catches
syntax errors) and asserts the specific properties this prompt's
requirements depend on, rather than trusting the file by inspection
alone: the schedule trigger exists, the workflow-dispatch apply toggle
defaults to dry-run, a concurrency lock is present and non-cancelling,
and the run script's own command-selection logic unconditionally applies
for a schedule-triggered run (a shell-logic property, checked as a
string match on the embedded script rather than executed — genuinely
running the script needs a real SSH target this test suite doesn't
have)."""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "demo-purge.yml"


def _load():
    # PyYAML parses the bare `on:` mapping key as the boolean True, not
    # the string "on" — harmless for how this test reads it, but the
    # loader itself is what proves the file is valid YAML at all.
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def test_workflow_file_is_valid_yaml():
    workflow = _load()
    assert workflow["name"] == "Demo account purge"


def test_schedule_trigger_present():
    workflow = _load()
    triggers = workflow[True]  # `on:` key, see _load's own note
    assert "schedule" in triggers
    assert triggers["schedule"][0]["cron"]


def test_workflow_dispatch_apply_input_defaults_to_dry_run():
    workflow = _load()
    triggers = workflow[True]
    apply_input = triggers["workflow_dispatch"]["inputs"]["apply"]
    assert apply_input["type"] == "boolean"
    assert apply_input["default"] is False


def test_concurrency_lock_present_and_never_cancels_in_progress():
    """requirement 6: a single-run mechanism — never killing an
    in-flight destructive run is as important as preventing a second one
    from starting."""
    workflow = _load()
    concurrency = workflow["concurrency"]
    assert concurrency["group"] == "demo-purge-production"
    assert concurrency["cancel-in-progress"] is False


def test_no_production_environment_approval_gate():
    """Deliberate — see the workflow file's own comment: a
    required-reviewer gate on a nightly schedule would mean clicking
    approve every night, which isn't genuinely automatic. Confirms this
    stays a conscious choice, not something a future edit reintroduces
    by copying migrate-profiles.yml's pattern without noticing why it
    doesn't apply here."""
    workflow = _load()
    purge_job = workflow["jobs"]["purge"]
    assert "environment" not in purge_job


def test_run_script_applies_unconditionally_for_schedule_events():
    """requirement 1: the scheduled run must always delete, not just
    report — checked as a string match on the embedded script's own
    command-selection logic (genuinely executing it needs a real SSH
    target this suite doesn't have)."""
    workflow = _load()
    steps = workflow["jobs"]["purge"]["steps"]
    script = next(s["run"] for s in steps if s.get("name") == "Run demo purge on the server")
    assert "github.event_name" in script and "schedule" in script
    assert "--apply" in script
    assert "exit 1" in script  # fail closed AND loud on missing secrets, not exit 0


def test_run_script_checks_both_ssh_secrets_before_proceeding():
    workflow = _load()
    steps = workflow["jobs"]["purge"]["steps"]
    script = next(s["run"] for s in steps if s.get("name") == "Run demo purge on the server")
    assert "SSH_KEY" in script
    assert "SSH_HOST" in script
