"""The recording studio's logic: the queue of prompts, the takes recorded for them and the dataset manifest.

Functions that touch records take the caller's `Session` (the server's per-request `DbSession`, the CLI's
`db.session()`, a test's `db_session`) and commit their own writes. Answers are `contracts.ApiModel`s, which the routes
declare, so the web app's types are generated from them (`web/src/api.generated.ts`).

The queue (step 1 of docs/implementation-plan.md) is the starter curriculum in its order: the next prompt is the first
that has no take and was not skipped. Retrying a prompt adds another take; the newest is the one in use and the
earlier ones stay on disk until removed, because a master is never overwritten. Scoring takes and choosing prompts by
value come in later steps and change only `next_prompt` and what a take records about itself."""

import datetime
import hashlib
import json
import os
from collections.abc import Iterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from strata_python.contracts import ApiModel, Page
from strata_python.files import inside, write_bytes_atomic
from strata_python.wav import read_wav

from stratavoice import curriculum, settings
from stratavoice.models import Prompt, Take

LOCALE = "en-GB"  # the spec's first locale; one voice, one accent
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


class TakeOut(ApiModel):
    """A kept take, with the prompt it was recorded for. Ids grow with time and are never reused."""

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


class Progress(ApiModel):
    """How far through the queue the speaker is. `seconds` counts every take kept, retries included."""

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
    """Add the starter prompts that are not there yet (by key), after the ones that are. Returns how many were added."""
    have = set(db.scalars(select(Prompt.key)))
    position = db.scalar(select(func.max(Prompt.position))) or 0
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
            )
        )
    if added:
        db.commit()
    return added


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
    """The next prompts to record, in queue order: no take yet and not skipped. More than one, so the studio can
    show the one after while a skip is still inside its undo window."""
    recorded = select(Take.prompt_id)
    q = select(Prompt).where(Prompt.skipped.is_(None), Prompt.id.not_in(recorded)).order_by(Prompt.position)
    return [_prompt_out(p, 0) for p in db.scalars(q.limit(limit))]


def next_prompt(db: Session) -> PromptOut | None:
    """The first prompt still to record, or None when every one is done."""
    return next(iter(upcoming(db, 1)), None)


def progress(db: Session) -> Progress:
    total = db.scalar(select(func.count()).select_from(Prompt)) or 0
    skipped = db.scalar(select(func.count()).select_from(Prompt).where(Prompt.skipped.is_not(None))) or 0
    recorded = db.scalar(select(func.count(func.distinct(Take.prompt_id)))) or 0
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
    t.path = f"human/take_{t.id:06d}.wav"
    try:
        target = os.path.join(settings.recordings_dir(), t.path)
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


def take_file(db: Session, take_id: int) -> str:
    """The path of a take's WAV. KeyError (a 404) when there is no such take or its file has gone."""
    t = _take(db, take_id)
    path = inside(settings.recordings_dir(), t.path)
    if not os.path.isfile(path):
        raise KeyError(f"The file of take {take_id} is missing from the recordings folder.")
    return path


def remove_take(db: Session, take_id: int) -> TakeOut:
    """Remove a take and its file. The speaker can always take back a recording (spec §5: export and deletion)."""
    t = _take(db, take_id)
    gone = _take_out(t, _prompt(db, t.prompt_id))
    path = inside(settings.recordings_dir(), t.path)
    db.delete(t)
    db.commit()
    if os.path.isfile(path):
        os.remove(path)
    return gone


def manifest(db: Session) -> Iterator[dict[str, Any]]:
    """The dataset as spec §5's JSON records, one per prompt's take in use (its newest), in queue order. `audio_uri` is
    relative to the recordings folder. Quality fields are null until scoring (step 2) fills them."""
    newest = select(func.max(Take.id)).group_by(Take.prompt_id)
    q = select(Take, Prompt).join(Prompt, Take.prompt_id == Prompt.id).where(Take.id.in_(newest))
    for t, p in db.execute(q.order_by(Prompt.position)):
        yield {
            "id": f"take_{t.id:06d}",
            "source": "human",
            "audio_uri": t.path,
            "sha256": t.sha256,
            "text": None if p.kind == "spontaneous" else p.text,
            "prompt": {"key": p.key, "text": p.text, "kind": p.kind, "source": p.source},
            "locale": LOCALE,
            "requested_style": None if p.cue is None else {"label": p.cue},
            "observed_style": {"review_status": "unverified"},
            "elicitation": {"mode": "written_label" if p.cue else "plain_text", "demonstration_heard": False},
            "audio": {
                "sample_rate": t.sample_rate,
                "sample_width": t.sample_width,
                "seconds": t.frames / t.sample_rate,
            },
            "device": t.device,
            "recorded": _utc(t.created).isoformat(),
            "quality": {"asr_wer": None, "clipping": None, "noise_ok": None},
            "partition": p.partition,
        }


def manifest_line(record: dict[str, Any]) -> str:
    """One manifest record as a JSONL line."""
    return json.dumps(record, ensure_ascii=False) + "\n"
