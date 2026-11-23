"""The app's records: SQLAlchemy models, migrated by Alembic (`src/stratavoice/migrations/`, declared in
`src/stratavoice/strata-db.toml`).

Two tables: the prompts the speaker is asked to read (or talk about), and the takes recorded for them. The audio itself
is a file in the recordings folder (`settings.recordings_dir`), never in the database: masters are large, must be
lossless and are handed to training tools as files. A take row says where its file is and what it holds.

Each model change comes with a reviewed revision: `uv run strata-db revision -m "..."` writes it from the difference
between these models and the migrations (a rename reads as drop + add, so read it), and `uv run strata-db check` (CI)
fails when they disagree. Models stay portable (generic types) so the same code runs on the local SQLite fallback and
on the shared Postgres; see strata-python's README, "Database"."""

import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from strata_python.db import NAMING_CONVENTION


class Base(MappedAsDataclass, DeclarativeBase):
    # Written out rather than `make_base()`: ty refuses a function's result as a base class. The shared naming convention
    # gives every constraint the same name on every app and engine, so migrations never drift on a name.
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Prompt(Base):
    """Something to say. `kind` is the curriculum's group (spontaneous, phonetic, prosodic, expressive, evaluation),
    `cue` the written delivery label shown with it ("dry, amused"), `partition` where its takes go in a dataset
    (`train`, or `eval` for the held-out set a model never trains on). `source` says who wrote it (`starter` for the
    built-in curriculum; later the prompt planner), and `position` orders the queue. A skipped prompt keeps its row,
    so the skip is part of the record and can be undone."""

    __tablename__ = "prompts"
    __table_args__ = {"sqlite_autoincrement": True}  # noqa: RUF012 - SQLAlchemy reads it from the class

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    text: Mapped[str] = mapped_column(String(600))
    kind: Mapped[str] = mapped_column(String(20))
    cue: Mapped[str | None] = mapped_column(String(200))
    partition: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    created: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    skipped: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Take(Base):
    """One recording of a prompt: a mono PCM WAV master in the recordings folder (`path`, relative to it, so the
    folder can move). A prompt may have several takes; the newest is the one in use, earlier ones are kept until
    removed. Ids grow with time and are never reused (the takes list pages with `after=<id>`), hence AUTOINCREMENT."""

    __tablename__ = "takes"
    __table_args__ = {"sqlite_autoincrement": True}  # noqa: RUF012 - SQLAlchemy reads it from the class

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), index=True)
    path: Mapped[str] = mapped_column(String(300))
    sample_rate: Mapped[int] = mapped_column(Integer)
    sample_width: Mapped[int] = mapped_column(Integer)  # bytes per sample: 2 (16-bit) or 3 (24-bit)
    frames: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    device: Mapped[str | None] = mapped_column(String(200))
    created: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
