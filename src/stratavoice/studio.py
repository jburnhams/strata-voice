"""The recording studio's logic: the queue of prompts, the takes recorded for them and the dataset manifest.

Functions that touch records take the caller's `Session` (the server's per-request `DbSession`, the CLI's
`db.session()`, a test's `db_session`) and commit their own writes. Answers are `contracts.ApiModel`s, which the routes
declare, so the web app's types are generated from them (`web/src/api.generated.ts`).

The queue (step 1 of docs/implementation-plan.md) is the starter curriculum in its order: the next prompt is the first
that has no take and was not skipped. Retrying a prompt adds another take; the newest is the one in use and the
earlier ones stay on disk until removed, because a master is never overwritten. Each take is then judged
(`scoring.py`): a prompt whose takes were all judged `retry`, and not kept anyway, is back at the front of the queue,
so the studio asks again at once. A take not judged yet, or `unchecked`, counts: the speaker is never held up by the
models service. After the starter set come the prompts the writer generated (writer.py), in the order coverage.py
ranks them, which it refreshes every few usable takes."""

import datetime
import hashlib
import json
import os
from collections.abc import Iterator
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session
from strata_python.contracts import ApiModel, Page
from strata_python.files import inside, write_bytes_atomic
from strata_python.wav import read_wav

from stratavoice import coverage, curriculum, phonemes, scoring, settings
from stratavoice.models import Prompt, Take

LOCALE = "en-GB"  # the spec's first locale; one voice, one accent
STYLE_VOCABULARY = "strata-voice-everyday-1"  # curriculum.STYLES; renamed if the list ever changes meaning
DEVICE_MAX = 200
MIN_TAKE_SECONDS = 0.3  # shorter than any prompt can be said in: a click on Record then Stop


class NotConsented(ValueError):
    """Recording before the speaker agreed to it (a 400 with the sentence)."""


def _utc(t: datetime.datetime) -> datetime.datetime:
    # Every time stored here is UTC. SQLite keeps no zone, so its times come back naive; Postgres's come back in the
    # session's zone. Either way the answer is in UTC.
    return t.replace(tzinfo=datetime.UTC) if t.tzinfo is None else t.astimezone(datetime.UTC)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class PromptOut(ApiModel):
    """A prompt with how far it has got: how many takes, and whether it was skipped."""

    id: int
    key: str
    text: str
    kind: str
    cue: str | None
    partition: str
    takes: int
    skipped: bool
    style: str | None
    source: str
    score: float | None


class TakeOut(ApiModel):
    """A kept take, with the prompt it was recorded for and how it was judged (`verdict` null: not scored yet; the
    other fields are explained in models.Take). Ids grow with time and are never reused."""

    id: int
    prompt_id: int
    prompt_text: str
    kind: str
    seconds: float
    sample_rate: int
    sample_width: int
    size_bytes: int
    device: str | None
    created: datetime.datetime
    verdict: str | None
    problems: list[scoring.Problem]
    accepted: bool
    transcript: str | None
    asr_model: str | None
    wer: float | None
    peak_db: float | None
    noise_db: float | None
    speech_db: float | None
    clipped: int | None
    speech_start: float | None
    speech_end: float | None


class Progress(ApiModel):
    """How far through the queue the speaker is: `recorded` counts prompts with a usable take; `takes` and `seconds`
    count every take kept, retries included."""

    prompts: int
    recorded: int
    skipped: int
    takes: int
    seconds: float


class Studio(ApiModel):
    """What the studio screen needs at once: may it record, what to say next (empty when the queue is done), how far."""

    consented: bool
    queue: list[PromptOut]
    progress: Progress
    max_take_seconds: int


def seed(db: Session) -> int:
    """Add the starter prompts that are not there yet (by key), after the ones that are, and drop the starter prompts
    the curriculum no longer has (the free-talk ones, 2026-11-24). One that was recorded stays with its takes (a take is
    the speaker's) but is skipped, so the studio never offers it again. Returns how many were added."""
    keys = {s.key for s in curriculum.STARTER}
    recorded = set(db.scalars(select(Take.prompt_id)))
    gone = list(db.scalars(select(Prompt).where(Prompt.source == "starter", Prompt.key.not_in(keys))))
    retired = False
    for p in gone:
        if p.id not in recorded:
            db.delete(p)
            retired = True
        elif p.skipped is None:  # kept for its takes, never offered again (even after a take judged `retry`)
            p.skipped = _now()
            retired = True
    have = set(db.scalars(select(Prompt.key)))
    position = db.scalar(select(func.max(Prompt.position)).where(Prompt.source == "starter")) or 0
    added = 0
    for s in curriculum.STARTER:
        if s.key in have:
            continue
        position += 1
        added += 1
        db.add(
            Prompt(
                key=s.key,
                text=s.text,
                kind=s.kind,
                cue=s.cue,
                partition=s.partition,
                source="starter",
                position=position,
                created=_now(),
                style=curriculum.style(s),
                phonemes=phonemes.ipa_or_none(s.text),
            )
        )
    if added or retired:
        db.commit()
    _fill(db)
    return added


def _fill(db: Session) -> None:
    """Give prompts kept before step 3 (or while espeak was missing) their style and phonemes, once each can be had."""
    styles = {s.key: curriculum.style(s) for s in curriculum.STARTER}
    q = select(Prompt).where(Prompt.style.is_(None), Prompt.key.in_(styles))
    changed = False
    for p in db.scalars(q):
        p.style, changed = styles[p.key], True
    if phonemes.available():
        for p in db.scalars(select(Prompt).where(Prompt.phonemes.is_(None))):
            p.phonemes, changed = phonemes.ipa_or_none(p.text), True
    if changed:
        db.commit()


def _usable() -> ColumnElement[bool]:
    return scoring.usable()


def _take_counts(db: Session) -> dict[int, int]:
    return dict(
        db.execute(select(Take.prompt_id, func.count()).group_by(Take.prompt_id)).all()
    )  # .all(): a Result has keys()


def _prompt_out(p: Prompt, takes: int) -> PromptOut:
    return PromptOut(
        id=p.id,
        key=p.key,
        text=p.text,
        kind=p.kind,
        cue=p.cue,
        partition=p.partition,
        takes=takes,
        skipped=p.skipped is not None,
        style=p.style,
        source=p.source,
        score=p.score,
    )


def _prompt(db: Session, prompt_id: int) -> Prompt:
    p = db.get(Prompt, prompt_id)
    if p is None:
        raise KeyError(f"There is no prompt {prompt_id}.")
    return p


def prompts(db: Session) -> list[PromptOut]:
    """Every prompt in queue order, each with its count of takes."""
    seed(db)
    counts = _take_counts(db)
    return [_prompt_out(p, counts.get(p.id, 0)) for p in db.scalars(select(Prompt).order_by(Prompt.position))]


def upcoming(db: Session, limit: int = 10) -> list[PromptOut]:
    """The next prompts to record, in queue order: no usable take yet and not skipped. More than one, so the studio
    can show the one after while a skip is still inside its undo window."""
    recorded = select(Take.prompt_id).where(_usable())
    q = select(Prompt).where(Prompt.skipped.is_(None), Prompt.id.not_in(recorded)).order_by(Prompt.position)
    return [_prompt_out(p, 0) for p in db.scalars(q.limit(limit))]


def next_prompt(db: Session) -> PromptOut | None:
    """The first prompt still to record, or None when every one is done."""
    return next(iter(upcoming(db, 1)), None)


def progress(db: Session) -> Progress:
    total = db.scalar(select(func.count()).select_from(Prompt)) or 0
    skipped = db.scalar(select(func.count()).select_from(Prompt).where(Prompt.skipped.is_not(None))) or 0
    recorded = db.scalar(select(func.count(func.distinct(Take.prompt_id))).where(_usable())) or 0
    takes = db.scalar(select(func.count()).select_from(Take)) or 0
    seconds = sum(f / r for f, r in db.execute(select(Take.frames, Take.sample_rate)))
    return Progress(prompts=total, recorded=recorded, skipped=skipped, takes=takes, seconds=round(seconds, 2))


def studio(db: Session) -> Studio:
    seed(db)
    return Studio(
        consented=settings.consented(),
        queue=upcoming(db),
        progress=progress(db),
        max_take_seconds=settings.max_take_seconds(),
    )


def skip(db: Session, prompt_id: int, skipped: bool = True) -> PromptOut:
    """Skip a prompt (it leaves the queue but keeps its row), or with `skipped=False` put it back."""
    p = _prompt(db, prompt_id)
    p.skipped = _now() if skipped else None
    db.commit()
    return _prompt_out(p, _take_counts(db).get(p.id, 0))


def _take_out(t: Take, p: Prompt) -> TakeOut:
    return TakeOut(
        id=t.id,
        prompt_id=p.id,
        prompt_text=p.text,
        kind=p.kind,
        seconds=round(t.frames / t.sample_rate, 3),
        sample_rate=t.sample_rate,
        sample_width=t.sample_width,
        size_bytes=t.size_bytes,
        device=t.device,
        created=_utc(t.created),
        verdict=t.verdict,
        problems=scoring.problems(t, p),
        accepted=t.accepted,
        transcript=t.transcript,
        asr_model=t.asr_model,
        wer=t.wer,
        peak_db=t.peak_db,
        noise_db=t.noise_db,
        speech_db=t.speech_db,
        clipped=t.clipped,
        speech_start=t.speech_start,
        speech_end=t.speech_end,
    )


def add_take(db: Session, prompt_id: int, data: bytes, device: str | None = None) -> TakeOut:
    """Keep a recording of a prompt: check the WAV, write it under `<recordings>/human/`, then record the row.

    The row is flushed first for its id (the file is named by it, so names are never reused), the file is written
    atomically, and only then is the row committed: a failed write leaves neither a row nor a half file."""
    if not settings.consented():
        raise NotConsented("Agree to be recorded first: nothing is kept until you do.")
    p = _prompt(db, prompt_id)
    info = read_wav(data, min_seconds=MIN_TAKE_SECONDS, max_seconds=settings.max_take_seconds())
    clean_device = (device or "").strip()[:DEVICE_MAX] or None
    t = Take(
        prompt_id=p.id,
        path="",
        sample_rate=info.sample_rate,
        sample_width=info.sample_width,
        frames=info.frames,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        device=clean_device,
        created=_now(),
    )
    db.add(t)
    db.flush()
    t.root = settings.recordings_dir()
    t.path = f"human/take_{t.id:06d}.wav"
    try:
        target = os.path.join(t.root, t.path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        write_bytes_atomic(target, data)
    except BaseException:
        db.rollback()
        raise
    db.commit()
    return _take_out(t, p)


def takes_page(db: Session, after: int | None = None, limit: int = 20) -> Page[TakeOut]:
    """One page of takes, newest first: those older than the one with id `after` (the last one the client holds).
    A cursor, not an offset, so a take removed between pages cannot make the next page skip one."""
    q = select(Take, Prompt).join(Prompt, Take.prompt_id == Prompt.id).order_by(Take.id.desc()).limit(limit + 1)
    if after is not None:
        q = q.where(Take.id < after)
    rows = list(db.execute(q))
    items = [_take_out(t, p) for t, p in rows[:limit]]
    return Page[TakeOut](items=items, next=str(items[-1].id) if len(rows) > limit else None)


def _take(db: Session, take_id: int) -> Take:
    t = db.get(Take, take_id)
    if t is None:
        raise KeyError(f"There is no take {take_id}.")
    return t


def _file(t: Take) -> str:
    """Where a take's WAV is: under the folder it was written to, which may no longer be the current one."""
    return inside(t.root or settings.recordings_dir(), t.path)


def take_file(db: Session, take_id: int) -> str:
    """The path of a take's WAV. KeyError (a 404) when there is no such take or its file has gone."""
    t = _take(db, take_id)
    path = _file(t)
    if not os.path.isfile(path):
        raise KeyError(f"The file of take {take_id} is missing from the recordings folder.")
    return path


def score_take(db: Session, take_id: int) -> TakeOut:
    """Judge a take (again): its levels at once, its words through strata-models (scoring.py)."""
    t = _take(db, take_id)
    p = _prompt(db, t.prompt_id)
    scoring.score(db, t, p, take_file(db, take_id))
    if coverage.due(db):  # spec §7.3: re-rank every few recordings, not after each (the queue stays steady)
        coverage.rank(db)
    return _take_out(t, p)


def accept_take(db: Session, take_id: int, accepted: bool = True) -> TakeOut:
    """Keep a take judged `retry` anyway (its prompt leaves the queue), or with `accepted=False` take that back."""
    t = _take(db, take_id)
    t.accepted = accepted
    db.commit()
    return _take_out(t, _prompt(db, t.prompt_id))


def unscored(db: Session) -> list[int]:
    """The takes whose words are still to hear, oldest first: never scored, or scored while the models service could
    not answer. That is `unchecked`, and also a `retry` for its levels alone, which still needs its transcript and crop."""
    q = select(Take.id).where(Take.asr_model.is_(None)).order_by(Take.id)
    return list(db.scalars(q))


def remove_take(db: Session, take_id: int) -> TakeOut:
    """Remove a take and its file. The speaker can always take back a recording (spec §5: export and deletion).

    The file goes first: if it cannot be removed (a folder made read-only), the error answers and the row stays, so
    the take is still listed and Remove can be tried again. A row whose file is already gone is just removed."""
    t = _take(db, take_id)
    gone = _take_out(t, _prompt(db, t.prompt_id))
    path = _file(t)
    if os.path.isfile(path):
        os.remove(path)
    db.delete(t)
    db.commit()
    return gone


def manifest(db: Session) -> Iterator[dict[str, Any]]:
    """The dataset as spec §5's JSON records, one per prompt's take in use (its newest usable one), in queue order: a
    prompt whose takes were all judged `retry` is left out. `audio_uri` is relative to the recordings folder, or
    absolute for a take written to an earlier one. `speech` is the crop in seconds into the file and `quality` the
    verdict; both are null for a take not scored yet. An old free-talk take's text is its transcript."""
    newest = select(func.max(Take.id)).where(_usable()).group_by(Take.prompt_id)
    q = select(Take, Prompt).join(Prompt, Take.prompt_id == Prompt.id).where(Take.id.in_(newest))
    for t, p in db.execute(q.order_by(Prompt.position)):
        yield {
            "id": f"take_{t.id:06d}",
            "source": "human",
            "audio_uri": t.path if t.root in ("", settings.recordings_dir()) else _file(t),
            "sha256": t.sha256,
            "text": t.transcript if p.kind == curriculum.FREE_TALK else p.text,
            "prompt": {"key": p.key, "text": p.text, "kind": p.kind, "source": p.source, "writer": p.writer},
            "locale": LOCALE,
            "phonemes": None if p.kind == curriculum.FREE_TALK else p.phonemes,
            "requested_style": None
            if p.style is None
            else {"vocabulary": STYLE_VOCABULARY, "category": p.style, "label": p.cue},
            "observed_style": {"review_status": "unverified"},
            "elicitation": {"mode": "written_label" if p.cue else "plain_text", "demonstration_heard": False},
            "audio": {
                "sample_rate": t.sample_rate,
                "sample_width": t.sample_width,
                "seconds": t.frames / t.sample_rate,
            },
            "speech": None if t.speech_start is None else {"start": t.speech_start, "end": t.speech_end},
            "device": t.device,
            "recorded": _utc(t.created).isoformat(),
            "asr": None if t.asr_model is None else {"model": t.asr_model, "hypothesis": t.transcript},
            "quality": {
                "verdict": t.verdict,
                "problems": t.problems.split(),
                "accepted": t.accepted,
                "asr_wer": t.wer,
                "clipping": None if t.clipped is None else t.clipped > scoring.CLIPPED_SAMPLES,
                "noise_ok": None if t.noise_db is None else t.noise_db <= scoring.NOISY_FLOOR_DB,
                "peak_db": t.peak_db,
                "noise_db": t.noise_db,
                "speech_db": t.speech_db,
            },
            "partition": p.partition,
        }


def manifest_line(record: dict[str, Any]) -> str:
    """One manifest record as a JSONL line."""
    return json.dumps(record, ensure_ascii=False) + "\n"
