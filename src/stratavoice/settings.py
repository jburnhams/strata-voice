"""User settings: one JSON file, `~/.stratavoice/settings.json` (the folder moves with STRATAVOICE_HOME).

`STRATAVOICE_<KEY>` overrides the file (handy for tests and one-off runs).

  recordings_dir     where the takes are written (default `<home>/recordings`). Recordings of a voice are personal
                     data that can be used to clone it: keep the folder on a disk you back up and nobody else reads.
  consented_on       the day the speaker agreed to be recorded (YYYY-MM-DD), blank until then. The studio records
                     nothing before it is set, and clearing it stops recording (the takes stay until removed).
  max_take_seconds   the longest take the server keeps (5 to 300): a guard against a recorder left running.

The file handling, precedence, validation and the `GET`/`PUT /api/settings` routes are
[strata_python.settings](https://github.com/jburnhams/strata-python); this module only declares the app's settings."""

import os

from strata_python.settings import Setting, Settings, absolute_path, iso_date, whole_between


def _default_recordings() -> str:
    return os.path.join(SETTINGS.home(), "recordings")


SETTINGS = Settings(
    "stratavoice",
    [
        Setting("recordings_dir", default=_default_recordings, normalise=absolute_path),
        Setting("consented_on", default="", normalise=iso_date(allow_blank=True)),
        Setting("max_take_seconds", default="60", normalise=whole_between(5, 300)),
    ],
    numbers=True,
)


def recordings_dir() -> str:
    """The folder takes are written to (made when the first take is kept)."""
    return SETTINGS.get("recordings_dir")


def consented() -> bool:
    """Whether the speaker has agreed to be recorded."""
    return bool(SETTINGS.get("consented_on"))


def max_take_seconds() -> int:
    return SETTINGS.get_int("max_take_seconds")
