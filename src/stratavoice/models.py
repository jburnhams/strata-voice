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

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, MetaData, String, Text, false
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
    built-in curriculum, `generated` for the prompt writer's), and `position` orders the queue. A skipped prompt keeps its row,
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
    # Step 3 (coverage.py, writer.py). `style` is the delivery from curriculum.STYLES (null for spontaneous talk),
    # `phonemes` espeak's en-GB IPA of the text (phonemes.py; null when espeak was not there), `writer` the model that
    # wrote a generated prompt (`source` is "generated"), and `score` its value per second when it was last ranked.
    style: Mapped[str | None] = mapped_column(String(20), default=None)
    phonemes: Mapped[str | None] = mapped_column(Text, default=None)
    writer: Mapped[str | None] = mapped_column(String(100), default=None)
    score: Mapped[float | None] = mapped_column(Float, default=None)


class Take(Base):
    """One recording of a prompt: a mono PCM WAV master at `path` under `root`, the recordings folder it was written to.
    The root is kept per take because changing the recordings folder in Settings leaves earlier takes where they are;
    `path` stays relative so a folder moved by hand needs only its `root` changed. A blank root (none yet) is the
    current folder. A prompt may have several takes; the newest is the one in use, earlier ones are kept until
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
    root: Mapped[str] = mapped_column(String(500), default="", server_default="")
    # How the take was judged (scoring.py), all null until it is scored. `verdict` is `good`, `retry` (a problem the
    # speaker should record again for: `problems` names each) or `unchecked` (the levels were fine but the speech
    # could not be transcribed yet). The levels are dBFS from strata_python.wav.measure; `speech_start`/`speech_end`
    # are the crop, from the transcript's word timings, in seconds into the master (which is never cut).
    verdict: Mapped[str | None] = mapped_column(String(10), default=None, index=True)
    problems: Mapped[str] = mapped_column(String(200), default="", server_default="")  # codes, space-separated
    scored: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    peak_db: Mapped[float | None] = mapped_column(Float, default=None)
    noise_db: Mapped[float | None] = mapped_column(Float, default=None)
    speech_db: Mapped[float | None] = mapped_column(Float, default=None)
    clipped: Mapped[int | None] = mapped_column(Integer, default=None)
    # Text, not a bounded String: a spontaneous take's transcript is its training text, and a 300 s take can run long.
    transcript: Mapped[str | None] = mapped_column(Text, default=None)
    asr_model: Mapped[str | None] = mapped_column(String(100), default=None)
    wer: Mapped[float | None] = mapped_column(Float, default=None)
    speech_start: Mapped[float | None] = mapped_column(Float, default=None)
    speech_end: Mapped[float | None] = mapped_column(Float, default=None)
    # The speaker kept a take that was judged `retry` (a name the recogniser does not know, a deliberate cough).
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
