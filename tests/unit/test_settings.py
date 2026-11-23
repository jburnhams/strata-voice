import os

import pytest

from stratavoice import settings


def test_defaults_and_environment_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path):
    assert settings.recordings_dir() == os.path.join(settings.SETTINGS.home(), "recordings")
    assert (settings.consented(), settings.max_take_seconds()) == (False, 60)
    monkeypatch.setenv("STRATAVOICE_RECORDINGS_DIR", str(tmp_path))
    monkeypatch.setenv("STRATAVOICE_CONSENTED_ON", "2026-11-23")
    monkeypatch.setenv("STRATAVOICE_MAX_TAKE_SECONDS", "120")
    assert (settings.recordings_dir(), settings.consented(), settings.max_take_seconds()) == (str(tmp_path), True, 120)


def test_save_validate_and_reset_in_the_settings_file():
    assert settings.SETTINGS.load() == {}
    assert settings.SETTINGS.save({"consented_on": "2026-11-23"}) == {"consented_on": "2026-11-23"}
    assert settings.consented()
    assert os.path.isfile(os.path.join(settings.SETTINGS.home(), "settings.json"))
    assert settings.SETTINGS.save({"consented_on": ""}) == {"consented_on": ""}  # withdrawn: blank, not the default
    assert not settings.consented()
    with pytest.raises(ValueError, match="consented_on"):
        settings.SETTINGS.save({"consented_on": "yesterday"})
    with pytest.raises(ValueError, match="max_take_seconds"):
        settings.SETTINGS.save({"max_take_seconds": "1"})
    with pytest.raises(ValueError, match="recordings_dir"):
        settings.SETTINGS.save({"recordings_dir": "relative/path"})
