import json
from collections.abc import Callable
from pathlib import Path

from strata_python.testing import CliResult

from stratavoice import curriculum, settings

Cli = Callable[..., CliResult]  # the `cli` fixture (tests/integration/conftest.py)


def test_doctor_reports_the_environment(cli: Cli):
    r = cli("doctor", check=False)
    assert "strata-voice 0.1.0" in r.stdout
    assert "sqlalchemy" in r.stdout
    assert r.code == 0


def test_the_queue_lives_in_the_fallback_database_in_the_app_home(cli: Cli):
    listed = json.loads(cli("prompts", "--json").stdout)
    assert [p["key"] for p in listed] == [s.key for s in curriculum.STARTER]
    # no database configured: SQLite in the app's home, migrated on first use
    assert (Path(settings.SETTINGS.home()) / "stratavoice.db").is_file()
    assert "no takes yet" in cli("takes").stdout
    assert cli("manifest").stdout == ""


def test_settings_are_viewed_and_updated_from_the_command_line(cli: Cli):
    assert "consented_on = 2026-11-23" in cli("set", "consented_on", "2026-11-23").stdout
    assert cli("set", "consented_on", "soon", check=False).stderr == "consented_on: must be a date, YYYY-MM-DD\n"
    assert cli("set", "nope", "x", check=False).code != 0


def test_the_committed_schema_check_passes(cli: Cli):
    # What CI runs on the Python side, so a stale web/openapi.json fails without Node.
    assert cli("openapi", "--check").code == 0


def test_the_command_line_runs_as_a_real_process(cli_subprocess: Cli):
    assert "strata-voice 0.1.0" in cli_subprocess("doctor").stdout
    assert "waiting" in cli_subprocess("prompts").stdout
