"""User settings: one JSON file, `~/.stratavoice/settings.json` (the folder moves with STRATAVOICE_HOME).

`STRATAVOICE_<KEY>` overrides the file (handy for tests and one-off runs).

  recordings_dir     where the takes are written (default `<home>/recordings`). Recordings of a voice are personal
                     data that can be used to clone it: keep the folder on a disk you back up and nobody else reads.
  consented_on       the day the speaker agreed to be recorded (YYYY-MM-DD), blank until then. The studio records
                     nothing before it is set, and clearing it stops recording (the takes stay until removed).
  max_take_seconds   the longest take the server keeps (5 to 300): a guard against a recorder left running.
  espeak             the espeak-ng program that phonemises prompts (phonemes.py), when it is not on the PATH as
                     `espeak-ng` (the Windows installer puts it under Program Files). Blank looks on the PATH.

The written voice (writing/) reads what the person wrote from three tables or views, normally strata-takeout's views in
the shared database (`unified.my_writing`, `unified.messages_all`, `unified.emails_all`; see its docs/unified.md):

  writing_url        the database those are in. Blank is the app's own database (the shared Postgres in a
                     deployment, where the views live beside the app's schema).
  writing_source     what the person wrote: one row per mail, chat line, post or comment (strata-takeout's
                     `my_writing` columns).
  writing_context    every chat line of every conversation, theirs and other people's: tells two of the person's
                     lines in a row from a reply in between, and a chat with one person from a group.
  writing_emails     every mail, so the mail a reply answers can be checked for quoted text left in the reply.
  assistant_since    the day the person may have started writing with AI help (YYYY-MM-DD); what they wrote from then
                     on is marked `assisted` and kept out of the reference for their voice. Blank (the default: the owner wrote
                     their mail and chats without it, 2026-11-28) marks nothing.

The file handling, precedence, validation and the `GET`/`PUT /api/settings` routes are
[strata_python.settings](https://github.com/jburnhams/strata-python); this module only declares the app's settings."""

import datetime
import os
import re

from strata_python.settings import Setting, Settings, absolute_path, iso_date, whole_between

# A table or view name, optionally schema-qualified: the only shape the writing settings may take, as they are put
# into SQL (a bound parameter cannot name a table).
TABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?")


def table_name(value: str) -> str:
    value = value.strip()
    if not TABLE_NAME.fullmatch(value):
        raise ValueError(f"{value!r} is not a table name (letters, digits and _, optionally schema.table).")
    return value


def _default_recordings() -> str:
    return os.path.join(SETTINGS.home(), "recordings")


SETTINGS = Settings(
    "stratavoice",
    [
        Setting("recordings_dir", default=_default_recordings, normalise=absolute_path),
        Setting("consented_on", default="", normalise=iso_date(allow_blank=True)),
        Setting("max_take_seconds", default="60", normalise=whole_between(5, 300)),
        Setting("espeak", default=""),
        Setting("writing_url", default=""),
        Setting("writing_source", default="unified.my_writing", normalise=table_name),
        Setting("writing_context", default="unified.messages_all", normalise=table_name),
        Setting("writing_emails", default="unified.emails_all", normalise=table_name),
        # ChatGPT's public release: before it, nothing the person sent can have been written with an assistant's help.
        Setting("assistant_since", default="", normalise=iso_date(allow_blank=True)),
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


def espeak() -> str:
    """The espeak program named in settings, or blank to look for it on the PATH."""
    return SETTINGS.get("espeak").strip()


def writing_url() -> str:
    """The database the person's writing is read from; blank is the app's own."""
    return SETTINGS.get("writing_url").strip()


def writing_tables() -> tuple[str, str, str]:
    """What they wrote, every chat line, every mail (see the module docstring)."""
    return SETTINGS.get("writing_source"), SETTINGS.get("writing_context"), SETTINGS.get("writing_emails")


def assistant_since() -> datetime.date | None:
    """From when what the person wrote may have had an assistant's help; None marks nothing."""
    v = SETTINGS.get("assistant_since")
    return datetime.date.fromisoformat(v) if v else None
