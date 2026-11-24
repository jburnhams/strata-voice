"""The pilot report (step 4 of docs/implementation-plan.md): one recording session's takes read against each of
scoring.py's thresholds, so the thresholds are tuned from the speaker's own room, microphone and voice rather than
from the usual figures they started as.

A session is a run of takes with no gap longer than `SESSION_GAP` between one and the next; the report reads the
newest one unless it is given a day to start from. For each check it gives the spread of what was measured (least,
median, most), how many takes failed, and how many came within `margin` of failing: a check that fails often with a
tight spread says the limit is wrong for this setup, one that fails rarely but has many near misses says the room or
the microphone is borderline. Then where the time went: how long the speaker waited before speaking and after the
last word (the crop's lead and tail), takes per prompt, and kept speech per minute at the microphone, which is what
the starter set's "about ten minutes" depends on.

Nothing is changed: the report only reads what scoring stored. Takes not scored yet (strata-models was down) count
in the session but not in the checks; `strata-voice score` fills them in."""

import datetime
import statistics
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session
from strata_python.contracts import ApiModel

from stratavoice import scoring
from stratavoice.models import Prompt, Take

#: Longer than this between two takes is a break: the next take starts a new session.
SESSION_GAP = datetime.timedelta(minutes=30)


class Spread(ApiModel):
    """The least, median and most of what a check measured, over the takes it applies to."""

    least: float
    median: float
    most: float


class Check(ApiModel):
    """One of scoring.py's checks over the session: its limit, what was measured, and how many failed or nearly did."""

    code: str  # the problem code scoring writes: quiet, noisy, clipped, words
    title: str
    limit: float
    unit: str
    fails_when: str  # "below" or "above" the limit
    margin: float  # a take within this of the limit, on the passing side, is a near miss
    measured: int  # takes with a value (scored, and for `words` read rather than spontaneous)
    spread: Spread | None
    failed: int
    near: int


class Pilot(ApiModel):
    """One session's takes against the thresholds, and where the session's time went."""

    started: datetime.datetime | None
    ended: datetime.datetime | None
    takes: int
    prompts: int
    again: int  # prompts recorded more than once in the session
    verdicts: dict[str, int]  # good, retry, unchecked, and "unscored" for takes not judged yet
    accepted: int  # retry takes the speaker kept anyway
    recorded_seconds: float  # every take, end to end
    speech_seconds: float  # the crops of the usable takes: what goes to the dataset
    minutes: float  # from the first take's start to the last one's end
    speech_per_minute: float | None  # seconds of kept speech per minute at the microphone
    lead: Spread | None  # seconds from Record to the first word (the crop's start)
    tail: Spread | None  # seconds from the last word to Stop
    checks: list[Check]


def _utc(t: datetime.datetime) -> datetime.datetime:
    return t if t.tzinfo else t.replace(tzinfo=datetime.UTC)  # SQLite gives the stored UTC time back naive


def _seconds(t: Take) -> float:
    return t.frames / t.sample_rate


def session(db: Session, since: datetime.date | None = None) -> list[Take]:
    """The takes of the newest session, oldest first; or every take from the start of `since` (UTC) on."""
    takes = list(db.scalars(select(Take).order_by(Take.id)))
    if since is not None:
        start = datetime.datetime.combine(since, datetime.time(), datetime.UTC)
        return [t for t in takes if _utc(t.created) >= start]
    first = max(0, len(takes) - 1)
    while first > 0 and _utc(takes[first].created) - _utc(takes[first - 1].created) <= SESSION_GAP:
        first -= 1
    return takes[first:]


def _spread(values: list[float]) -> Spread | None:
    if not values:
        return None
    return Spread(least=round(min(values), 3), median=round(statistics.median(values), 3), most=round(max(values), 3))


def _check(
    code: str,
    title: str,
    limit: float,
    unit: str,
    below: bool,
    margin: float,
    values: list[float],
    near: Callable[[float], bool] | None = None,
) -> Check:
    def fails(v: float) -> bool:
        return v < limit if below else v > limit

    def close(v: float) -> bool:
        return (limit <= v <= limit + margin) if below else (limit - margin <= v <= limit)

    is_near = near or close
    return Check(
        code=code,
        title=title,
        limit=limit,
        unit=unit,
        fails_when="below" if below else "above",
        margin=margin,
        measured=len(values),
        spread=_spread(values),
        failed=sum(fails(v) for v in values),
        near=sum(not fails(v) and is_near(v) for v in values),
    )


def report(db: Session, since: datetime.date | None = None) -> Pilot:
    """The pilot report over the newest session (or from `since`)."""
    takes = session(db, since)
    kinds = {p.id: p.kind for p in db.scalars(select(Prompt).where(Prompt.id.in_({t.prompt_id for t in takes})))}
    scored = [t for t in takes if t.verdict is not None]
    verdicts: dict[str, int] = dict.fromkeys((scoring.GOOD, scoring.RETRY, scoring.UNCHECKED, "unscored"), 0)
    for t in takes:
        verdicts[t.verdict or "unscored"] += 1
    per_prompt: dict[int, int] = {}
    for t in takes:
        per_prompt[t.prompt_id] = per_prompt.get(t.prompt_id, 0) + 1
    usable = [t for t in takes if t.verdict != scoring.RETRY or t.accepted]
    cropped = [t for t in scored if t.speech_start is not None and t.speech_end is not None]
    speech = sum(
        t.speech_end - t.speech_start for t in usable if t.speech_start is not None and t.speech_end is not None
    )
    started = _utc(takes[0].created) - datetime.timedelta(seconds=_seconds(takes[0])) if takes else None
    ended = _utc(takes[-1].created) if takes else None
    minutes = (ended - started).total_seconds() / 60 if started and ended else 0.0
    levels = [t for t in scored if t.peak_db is not None]
    words = [t for t in scored if t.wer is not None and kinds.get(t.prompt_id) != "spontaneous"]
    return Pilot(
        started=started,
        ended=ended,
        takes=len(takes),
        prompts=len(per_prompt),
        again=sum(n > 1 for n in per_prompt.values()),
        verdicts=verdicts,
        accepted=sum(t.accepted for t in takes if t.verdict == scoring.RETRY),
        recorded_seconds=round(sum(_seconds(t) for t in takes), 1),
        speech_seconds=round(speech, 1),
        minutes=round(minutes, 1),
        speech_per_minute=round(speech / minutes, 1) if minutes > 0 else None,
        lead=_spread([t.speech_start for t in cropped if t.speech_start is not None]),
        tail=_spread([_seconds(t) - t.speech_end for t in cropped if t.speech_end is not None]),
        checks=[
            _check("quiet", "Peak level", scoring.QUIET_PEAK_DB, "dBFS", True, 6.0, [t.peak_db for t in levels if t.peak_db is not None]),
            _check("noisy", "Noise floor", scoring.NOISY_FLOOR_DB, "dBFS", False, 6.0, [t.noise_db for t in levels if t.noise_db is not None]),
            # Any clipping at all is a near miss: the limit allows a couple of samples, not a habit.
            _check("clipped", "Clipped samples", scoring.CLIPPED_SAMPLES, "samples", False, scoring.CLIPPED_SAMPLES,
                   [float(t.clipped) for t in levels if t.clipped is not None], near=lambda v: v > 0),
            # A wrong word at all is a near miss: a long sentence passes with one, which is worth knowing.
            _check("words", "Word error rate", scoring.MAX_WER, "share", False, scoring.MAX_WER,
                   [t.wer for t in words if t.wer is not None], near=lambda v: v > 0),
        ],
    )  # fmt: skip


def describe(p: Pilot) -> list[str]:
    """The report as lines for the CLI."""
    if p.started is None or p.ended is None:
        return ["No takes yet: record a session in the studio, then run this again."]
    v = p.verdicts
    out = [
        f"Session {p.started:%Y-%m-%d %H:%M} to {p.ended:%H:%M} UTC, {p.minutes:g} min: {p.takes} take(s) of "
        f"{p.prompts} prompt(s), {p.again} recorded more than once.",
        f"Verdicts: {v['good']} good, {v['retry']} retry ({p.accepted} kept anyway), {v['unchecked']} unchecked, "
        f"{v['unscored']} not scored yet.",
        f"Speech kept: {p.speech_seconds:g} s of {p.recorded_seconds:g} s recorded"
        + (f", {p.speech_per_minute:g} s per minute at the microphone." if p.speech_per_minute is not None else "."),
    ]
    if p.lead and p.tail:
        out.append(
            f"Before the first word: median {p.lead.median:g} s (most {p.lead.most:g} s); "
            f"after the last: median {p.tail.median:g} s (most {p.tail.most:g} s)."
        )
    for c in p.checks:
        if c.spread is None:
            out.append(f"{c.title}: nothing measured.")
            continue
        s = c.spread
        out.append(
            f"{c.title}: limit {c.limit:g} {c.unit} (fails {c.fails_when}); measured {s.least:g} to {s.most:g}, "
            f"median {s.median:g}, over {c.measured}; {c.failed} failed, {c.near} near."
        )
    if v["unscored"] or v["unchecked"]:
        out.append(
            "Some takes are not fully judged: start strata-models and run `strata-voice score`, then this again."
        )
    return out
