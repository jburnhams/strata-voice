"""The app's records: SQLAlchemy models, migrated by Alembic (`src/stratavoice/migrations/`, declared in
`src/stratavoice/strata-db.toml`).

The spoken voice's tables: the prompts the speaker is asked to read (or talk about), the takes recorded for them,
and the recordings brought in on the Upload screen (ingest.py), whose sentences become takes too; the written voice's:
what the person wrote, cleaned (`writing`), and its frozen split (`writing_splits`); plus strata-python's job queue
(`jobs`), which runs each upload and each build of the writing in the background. The audio itself
is a file in the recordings folder (`settings.recordings_dir`), never in the database: masters are large, must be
lossless and are handed to training tools as files. A take row says where its file is and what it holds.

Each model change comes with a reviewed revision: `uv run strata-db revision -m "..."` writes it from the difference
between these models and the migrations (a rename reads as drop + add, so read it), and `uv run strata-db check` (CI)
fails when they disagree. Models stay portable (generic types) so the same code runs on the local SQLite fallback and
on the shared Postgres; see strata-python's README, "Database"."""

import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, MetaData, String, Text, false
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from strata_python.db import NAMING_CONVENTION
from strata_python.tasks.queue import jobs_table


class Base(MappedAsDataclass, DeclarativeBase):
    # Written out rather than `make_base()`: ty refuses a function's result as a base class. The shared naming convention
    # gives every constraint the same name on every app and engine, so migrations never drift on a name.
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Upload(Base):
    """A recording the speaker brought in (an old voice note, a talk, a video): any format ffmpeg reads, kept as it came
    at `path` under `root` (the recordings folder then, as for a take), and processed by the `ingest` job `job_id`
    (ingest.py): decoded to one lossless mono WAV at one gain (`normalized`, `gain_db`), transcribed, cut into
    sentences, each a take of its own (`Take.upload_id`). `speaker_reference` says what each sentence's voice was
    compared with: `studio` (the speaker's own studio takes), `upload` (no studio takes yet: the voice that speaks most
    here) or null (strata-models could not measure voices, so every sentence was kept). `sha256` refuses the same file
    twice."""

    __tablename__ = "uploads"
    __table_args__ = {"sqlite_autoincrement": True}  # noqa: RUF012 - SQLAlchemy reads it from the class

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    name: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(400))
    root: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    created: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float, default=None)
    job_id: Mapped[int | None] = mapped_column(Integer, default=None)
    normalized: Mapped[str | None] = mapped_column(String(400), default=None)
    gain_db: Mapped[float | None] = mapped_column(Float, default=None)
    transcript: Mapped[str | None] = mapped_column(Text, default=None)
    asr_model: Mapped[str | None] = mapped_column(String(100), default=None)
    speaker_reference: Mapped[str | None] = mapped_column(String(10), default=None)


class Prompt(Base):
    """Something to say. `kind` is the curriculum's group (phonetic, prosodic, expressive, evaluation),
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
    # Step 3 (coverage.py, writer.py). `style` is the delivery from curriculum.STYLES (null on a row from before step 3),
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
    # Text, not a bounded String: a 300 s take can run long.
    transcript: Mapped[str | None] = mapped_column(Text, default=None)
    asr_model: Mapped[str | None] = mapped_column(String(100), default=None)
    wer: Mapped[float | None] = mapped_column(Float, default=None)
    speech_start: Mapped[float | None] = mapped_column(Float, default=None)
    speech_end: Mapped[float | None] = mapped_column(Float, default=None)
    # The speaker kept a take that was judged `retry` (a name the recogniser does not know, a deliberate cough).
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # A sentence cut from an upload (ingest.py): which one, where it was in the recording (seconds into the original),
    # and how like the speaker its voice is (cosine similarity of speaker embeddings, null when not measured).
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"), default=None, index=True)
    source_start: Mapped[float | None] = mapped_column(Float, default=None)
    source_end: Mapped[float | None] = mapped_column(Float, default=None)
    speaker_similarity: Mapped[float | None] = mapped_column(Float, default=None)


class Writing(Base):
    """One thing the person wrote, cleaned for learning their written voice (writing/corpus.py): a mail, a post, a
    comment, or a run of their chat lines with nobody else's in between (`parts` lines, joined with line breaks).

    `original` is the text as stored and `removed` the spans taken out of it (JSON `[[kind, start, end], ...]`:
    `quote`, `forward`, `signature`, `client`), so `text` is `original` without them and the screen can show both;
    `original` is null when nothing was removed. Nothing else is changed: spelling, casing, emoji and line breaks are
    the voice. `key` (`platform:first source id`) survives a rebuild, so a check mark (`checked_as`) does too.

    `medium` is what the research conditions on: `email-work`, `email-personal`, `chat-direct`, `chat-group`,
    `social`. `recipient` is an opaque key (a hash of the addresses, or of the conversation), never a name.
    `trivial` (too short to say anything about a voice: under six words and no question) is counted but never used
    as an example or a task. `flags` are space-separated codes (`leak`: eight or more words in a row also in the mail
    it answers; `duplicate`, `near-duplicate`: a copy of another row, which is the one used). `assisted`: written on
    or after the `assistant_since` setting. `split` is `train`, `dev`, `sealed` or `buffer` (writing/split.py), fixed
    by the frozen `WritingSplit`."""

    __tablename__ = "writing"
    __table_args__ = {"sqlite_autoincrement": True}  # noqa: RUF012 - SQLAlchemy reads it from the class

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10))
    medium: Mapped[str] = mapped_column(String(20), index=True)
    work: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    conversation: Mapped[str | None] = mapped_column(String(300))
    group_key: Mapped[str] = mapped_column(String(64))
    recipient: Mapped[str | None] = mapped_column(String(32))
    recipients: Mapped[int | None] = mapped_column(Integer)
    subject: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    original: Mapped[str | None] = mapped_column(Text)
    removed: Mapped[str] = mapped_column(Text)
    parts: Mapped[int] = mapped_column(Integer)
    source_ids: Mapped[str] = mapped_column(Text)
    words: Mapped[int] = mapped_column(Integer)
    trivial: Mapped[bool] = mapped_column(Boolean, index=True)
    flags: Mapped[str] = mapped_column(String(200))
    assisted: Mapped[bool] = mapped_column(Boolean)
    split: Mapped[str] = mapped_column(String(10), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    in_reply_to: Mapped[str | None] = mapped_column(String(500))
    built: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    # Its place in its medium's cleaning sample (0 to SAMPLE_SIZE - 1, writing/corpus.py), null outside it: a fixed
    # random draw of the rows worth checking, so a rebuild asks about the same rows.
    sample: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    # The person's check of the cleaning (the screen's Check tab): `clean`, `quote`, `signature`, `not-mine`, `other`.
    checked_as: Mapped[str | None] = mapped_column(String(20), default=None)
    checked: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class WritingSplit(Base):
    """The split of the writing into train, dev and sealed, frozen the first time the corpus is built and never
    changed by a rebuild (writing/split.py): `cutoff` (everything from then on is sealed, a year before the newest
    message at freezing), the `seed` the dev share and the held-out recipients are drawn with, and those recipients
    (`holdout`, space-separated keys). A new message brought in later is placed by the same rule, so the sealed set
    can only grow. Only one row: a second split would make every earlier experiment's sealed set leak."""

    __tablename__ = "writing_splits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    created: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    cutoff: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    seed: Mapped[str] = mapped_column(String(32))
    holdout: Mapped[str] = mapped_column(Text)


#: strata-python's job queue, which runs each upload's `ingest` job (in the server's worker; `strata-voice ingest` in
#: the CLI). Part of the metadata, so the migrations make it.
JOBS = jobs_table(Base.metadata)
