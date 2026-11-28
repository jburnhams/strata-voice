"""The person's writing as one cleaned, split table (`models.Writing`): built from strata-takeout's views (source.py)
by `build`, which the `writing` job (the My writing screen's Build) and `strata-voice writing build` run.

What a build does, and why (voice-research voice-design/data-collection.md §2 and written.md):

1. **Read** every row the person wrote: mail, chat lines, posts, comments and their prompts to Claude.
2. **Join chat lines**: the person's lines in a row, with nobody else's in between and no gap over `JOIN_GAP`, are
   one message, joined with line breaks (Jonathan, 2026-11-28: "for chat then can concat consecutive messages").
   How a thought is split across sends is itself a habit, so the breaks stay. A conversation with more than one
   other person in it is `chat-group`, else `chat-direct`.
3. **Clean mail** (clean.py): quotes, forwards, signatures and client footers out, as spans; and a reply that still
   shares `clean.LEAK_WORDS` words in a row with the mail it answers is flagged `leak`.
4. **Mark trivial** what is too short to say anything about a voice (Jonathan: "can't get much sense of voice from
   'yep, see you soon'"): under `TRIVIAL_WORDS` words and no question. Kept and counted (how often someone sends
   "yep" is part of a voice) but never an example or a task. The line is checked on the sample, not assumed.
5. **Find copies**: the same words (a template, a mail sent to several lists) or nearly the same (`NEAR` Jaccard
   over five-word shingles) are one text; the first is kept, the rest flagged, and all go to one split.
6. **Split** (split.py), frozen on the first build and never moved by a later one.
7. **Draw the cleaning sample**: `SAMPLE_SIZE` rows per medium worth checking, the same rows on every build, which
   the person marks on the Check tab. Step 2 starts once each medium's sample is at least 95% clean.

Nothing is sent anywhere: the build reads the shared database and writes the app's own."""

import datetime
import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, delete, func, insert, select
from sqlalchemy.orm import Session
from strata_python.contracts import ApiModel, Page, Task
from strata_python.tasks.progress import report_progress
from strata_python.tasks.queue import Job, Queue

from stratavoice import settings
from stratavoice.models import Writing, WritingSplit
from stratavoice.writing import clean, split
from stratavoice.writing import source as sources
from stratavoice.writing.source import Line, Written

log = logging.getLogger(__name__)

KIND = "writing"  # the build's job kind on the queue
JOIN_GAP = datetime.timedelta(minutes=5)
TRIVIAL_WORDS = 6
NEAR = 0.8
NEAR_MIN_WORDS = 20  # shorter texts repeat by chance ("see you there"), so only longer ones are compared
SHINGLE = 5
BANDS, ROWS = 4, 4  # MinHash: 16 hashes in 4 bands of 4, so a pair at Jaccard 0.8 shares a band 87% of the time
SAMPLE_SIZE = 50
VERDICTS = ("clean", "quote", "signature", "not-mine", "other")

EMAIL, CHAT, POST, COMMENT, PROMPT = "email", "chat", "post", "comment", "prompt"
MEDIUMS = ("email-personal", "email-work", "chat-direct", "chat-group", "social", "prompt")


class Removed(ApiModel):
    """A span taken out of a mail's original text (clean.py): `quote`, `forward`, `signature` or `client`."""

    kind: str
    start: int
    end: int


class WritingOut(ApiModel):
    """One thing the person wrote, as cleaned (the fields are explained in models.Writing). `original` is null when
    nothing was taken out of it; `removed` are offsets into it."""

    id: int
    at: datetime.datetime
    platform: str
    kind: str
    medium: str
    work: bool
    subject: str | None
    text: str
    original: str | None
    removed: list[Removed]
    parts: int
    words: int
    trivial: bool
    flags: list[str]
    split: str
    assisted: bool
    sample: int | None
    checked_as: str | None


class MediumCount(ApiModel):
    """One medium's rows: how many, how many trivial, words in the rest, the years they span, and how far the
    person has got checking its cleaning sample (`checked` of `sample`, `clean` of those)."""

    medium: str
    rows: int
    trivial: int
    words: int
    first: datetime.datetime
    last: datetime.datetime
    sample: int
    checked: int
    clean: int


class Count(ApiModel):
    """Rows by one value (a split, a year, a flag)."""

    value: str
    rows: int


class WritingSummary(ApiModel):
    """What the writing holds: rows by medium, split, year and flag; the frozen split's cutoff and held-out
    recipients; when it was last built and the newest build job (null: never built)."""

    built: datetime.datetime | None
    rows: int
    assisted: int
    mediums: list[MediumCount]
    splits: list[Count]
    years: list[Count]
    flags: list[Count]
    cutoff: datetime.datetime | None
    holdout: int
    job: Task | None


class Built(ApiModel):
    """What a build did."""

    read: int
    rows: int
    joined: int
    trivial: int
    duplicates: int
    leaks: int
    signatures: int
    splits: list[Count]
    cutoff: datetime.datetime


@dataclass
class Entry:
    """A row being built."""

    platform: str
    source: str
    kind: str
    medium: str
    work: bool
    parts: list[Written]
    text: str
    original: str | None = None
    removed: list[clean.Span] = field(default_factory=lambda: [])
    recipient: str | None = None
    recipients: int | None = None
    group: str = ""
    flags: list[str] = field(default_factory=lambda: [])
    split: str = split.TRAIN
    sample: int | None = None

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.parts[0].source_id}"

    @property
    def at(self) -> datetime.datetime:
        return self.parts[0].at

    @property
    def ended(self) -> datetime.datetime:
        return self.parts[-1].at


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _utc(t: datetime.datetime) -> datetime.datetime:
    return t.replace(tzinfo=datetime.UTC) if t.tzinfo is None else t.astimezone(datetime.UTC)


def _runs(mine: list[Written], lines: list[Line]) -> list[list[Written]]:
    """The person's lines of one conversation as runs to join: consecutive in the timeline (nobody else's line
    between) and no more than `JOIN_GAP` apart. A line of theirs missing from the timeline stands alone."""
    by_id = {w.source_id: w for w in mine}
    runs: list[list[Written]] = []
    run: list[Written] = []
    seen: set[str] = set()
    for line in lines:
        w = by_id.get(line.source_id)
        if w is None or line.source_id in seen:
            if run:
                runs.append(run)
                run = []
            continue
        seen.add(line.source_id)
        if run and w.at - run[-1].at > JOIN_GAP:
            runs.append(run)
            run = []
        run.append(w)
    if run:
        runs.append(run)
    runs.extend([w] for w in mine if w.source_id not in seen)
    return sorted(runs, key=lambda r: (r[0].at, r[0].source_id))


def _chats(src: Engine, rows: list[Written]) -> Iterator[Entry]:
    by_conv: dict[tuple[str, str], list[Written]] = defaultdict(list)
    for w in rows:
        by_conv[(w.platform, w.conversation_id or f"row:{w.source_id}")].append(w)
    timelines = sources.timelines(src, set(by_conv))
    for (platform, conv), mine in by_conv.items():
        lines = timelines.get((platform, conv), [])
        ids = {w.source_id for w in mine}
        others = {line.sender for line in lines if line.source_id not in ids and line.sender is not None}
        medium = "chat-group" if len(others) > 1 else "chat-direct"
        previous: datetime.datetime | None = None
        session = ""
        for run in _runs(mine, lines):
            if previous is None or run[0].at - previous > split.SESSION_GAP:
                session = run[0].source_id
            previous = run[-1].at
            yield Entry(
                platform=platform,
                source=run[0].source,
                kind=CHAT,
                medium=medium,
                work=any(w.work for w in run),
                parts=run,
                text="\n".join(w.text for w in run),
                recipient=_hash(platform, conv)[:32],
                recipients=max(1, len(others)),
                group=_hash(platform, conv, session),
            )


def _emails(src: Engine, rows: list[Written]) -> tuple[list[Entry], int]:
    """The mails, cleaned; and how many signatures were learnt from them."""
    first = [clean.clean_email(w.text)[0] for w in rows]
    signatures = clean.learn_signatures(first)
    replied = sources.replied_to(src, (w.in_reply_to for w in rows if w.in_reply_to))
    out: list[Entry] = []
    for w in rows:
        kept, spans = clean.clean_email(w.text, signatures)
        kept = clean.unwrap(kept)  # the client's line breaks, not the person's
        addresses = sorted({a.lower() for a in (w.recipients or "").split() if a})
        e = Entry(
            platform=w.platform,
            source=w.source,
            kind=EMAIL,
            medium="email-work" if w.work else "email-personal",
            work=w.work,
            parts=[w],
            text=kept,
            original=w.text if spans or kept != w.text else None,
            removed=spans,
            recipient=_hash(*addresses)[:32] if addresses else None,
            recipients=len(addresses) or None,
            group=_hash(EMAIL, w.conversation_id) if w.conversation_id else _hash(EMAIL, "row", w.source_id),
        )
        parent = replied.get(w.in_reply_to or "")
        if parent and clean.leaks(kept, parent):
            e.flags.append("leak")
        out.append(e)
    return out, len(signatures)


def _others(rows: list[Written]) -> Iterator[Entry]:
    """Posts, comments and prompts to an assistant: each one as it is, a group of its own."""
    for w in rows:
        yield Entry(
            platform=w.platform,
            source=w.source,
            kind=w.kind,
            medium=PROMPT if w.kind == PROMPT else "social",
            work=w.work,
            parts=[w],
            text=w.text,
            group=_hash(w.platform, w.kind, w.source_id),
        )


def trivial(text: str) -> bool:
    """Too short to say anything about a voice: under `TRIVIAL_WORDS` words and not a question."""
    return len(clean.words(text)) < TRIVIAL_WORDS and "?" not in text


def _signature(words: list[str]) -> list[int]:
    # A stable hash (Python's own is salted per process), so the same texts are found to be copies on every build.
    shingles = {
        int.from_bytes(hashlib.blake2b(" ".join(words[i : i + SHINGLE]).encode(), digest_size=4).digest())
        for i in range(len(words) - SHINGLE + 1)
    }
    out: list[int] = []
    for k in range(BANDS * ROWS):
        a, b = 2 * k + 1, 7919 * (k + 3)
        out.append(min((a * s + b) % 4294967311 for s in shingles))
    return out


def _copies(entries: list[Entry]) -> int:
    """Flag each row that is a copy of an earlier one (`duplicate`: the same words; `near-duplicate`: Jaccard at
    least `NEAR`), and give every member of a cluster its most held-out split. Returns how many were flagged."""
    parent = list(range(len(entries)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i: int, j: int) -> None:
        a, b = root(i), root(j)
        parent[max(a, b)] = min(a, b)  # the same root (a == b) points at itself, which changes nothing

    exact: dict[str, int] = {}
    near: dict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    shingled: dict[int, set[str]] = {}
    kind: dict[int, str] = {}
    for i, e in enumerate(entries):
        ws = clean.words(e.text)
        if len(ws) < TRIVIAL_WORDS:
            continue
        h = _hash(" ".join(ws))
        if h in exact:
            join(exact[h], i)
            kind[i] = "duplicate"
            continue
        exact[h] = i
        if len(ws) >= NEAR_MIN_WORDS:
            shingled[i] = {" ".join(ws[k : k + SHINGLE]) for k in range(len(ws) - SHINGLE + 1)}
            sig = _signature(ws)
            for band in range(BANDS):
                bucket = near[(band, tuple(sig[band * ROWS : (band + 1) * ROWS]))]
                for j in bucket:
                    a, b = shingled[i], shingled[j]
                    if i not in kind and len(a & b) / len(a | b) >= NEAR:
                        join(j, i)
                        kind[i] = "near-duplicate"
                bucket.append(i)
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(entries)):
        clusters[root(i)].append(i)
    for members in clusters.values():
        if len(members) > 1:
            top = split.highest(entries[i].split for i in members)
            for i in members:
                entries[i].split = top
    for i, k in kind.items():
        entries[i].flags.append(k)
    return len(kind)


def _rule(db: Session, entries: list[Entry]) -> tuple[split.Rule, WritingSplit | None]:
    """The frozen split, or a new one to freeze (returned as the row to add, so the caller writes it with the rest)."""
    row = db.scalars(select(WritingSplit).order_by(WritingSplit.id)).first()
    if row is not None:
        return split.Rule(_utc(row.cutoff), row.seed, frozenset(row.holdout.split())), None
    direct = ("email-personal", "email-work", "chat-direct")
    rule = split.freeze((e.at, e.recipient if e.medium in direct else None) for e in entries)
    new = WritingSplit(created=_now(), cutoff=rule.cutoff, seed=rule.seed, holdout=" ".join(sorted(rule.holdout)))
    return rule, new


def _assign(rule: split.Rule, entries: list[Entry]) -> None:
    groups: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        groups[e.group].append(e)
    for key, members in groups.items():
        last = max(e.ended for e in members)
        recipients = {e.recipient for e in members if e.recipient is not None}
        s = split.assign(rule, key, last, recipients)
        for e in members:
            e.split = s


def _sample(entries: list[Entry]) -> None:
    by_medium: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        if not trivial(e.text) and not e.flags:
            by_medium[e.medium].append(e)
    for members in by_medium.values():
        for i, e in enumerate(sorted(members, key=lambda e: split.draw("sample", e.key))[:SAMPLE_SIZE]):
            e.sample = i


def build(db: Session, src: Engine, progress: Callable[..., None] = report_progress) -> Built:
    """Rebuild the `writing` table from the source (see the module docstring). The split is frozen on the first
    build; each row's check mark is kept by its key."""
    progress(0, None, "Reading what you wrote", "read")
    rows = list(sources.written(src))
    if not rows:
        raise ValueError(f"{settings.writing_tables()[0]} holds nothing: there is no writing to build from.")
    by_kind: dict[str, list[Written]] = defaultdict(list)
    for w in rows:
        by_kind[EMAIL if w.platform == EMAIL else w.kind].append(w)
    progress(0, None, f"{len(rows)} rows; joining chat lines", "join")
    entries = list(_chats(src, by_kind[CHAT]))
    joined = sum(len(e.parts) - 1 for e in entries)
    progress(0, None, f"Cleaning {len(by_kind[EMAIL])} mails", "clean")
    mails, signatures = _emails(src, by_kind[EMAIL])
    entries.extend(mails)
    entries.extend(_others([w for k, ws in by_kind.items() if k not in (CHAT, EMAIL) for w in ws]))
    entries.sort(key=lambda e: (e.at, e.key))
    progress(0, None, "Splitting and finding copies", "split")
    rule, frozen = _rule(db, entries)
    _assign(rule, entries)
    duplicates = _copies(entries)
    _sample(entries)
    since = settings.assistant_since()
    checks = {k: (v, t) for k, v, t in db.execute(select(Writing.key, Writing.checked_as, Writing.checked))}
    now = _now()
    # Every read is done before the first write, and nothing is reported while the writes are open: the job's own
    # progress goes through another connection, which SQLite would make wait on this transaction's lock.
    progress(0, None, f"Writing {len(entries)} rows", "write")
    values: list[dict[str, Any]] = []
    for e in entries:
        mark, when = checks.get(e.key, (None, None))
        values.append(
            {
                "key": e.key,
                "platform": e.platform,
                "source": e.source,
                "kind": e.kind,
                "medium": e.medium,
                "work": e.work,
                "at": e.at,
                "ended": e.ended,
                "conversation": e.parts[0].conversation_id,
                "group_key": e.group,
                "recipient": e.recipient,
                "recipients": e.recipients,
                "subject": e.parts[0].subject,
                "text": e.text,
                "original": e.original,
                "removed": json.dumps(e.removed),
                "parts": len(e.parts),
                "source_ids": " ".join(w.source_id for w in e.parts),
                "words": len(clean.words(e.text)),
                "trivial": trivial(e.text),
                "flags": " ".join(e.flags),
                "assisted": since is not None and e.at.date() >= since,
                "split": e.split,
                "content_hash": _hash(" ".join(clean.words(e.text))),
                "in_reply_to": e.parts[0].in_reply_to,
                "built": now,
                "sample": e.sample,
                "checked_as": mark,
                "checked": when,
            }
        )
    if frozen is not None:
        db.add(frozen)
    db.execute(delete(Writing))
    for i in range(0, len(values), 2000):
        db.execute(insert(Writing), values[i : i + 2000])
    db.commit()
    splits: dict[str, int] = defaultdict(int)
    for e in entries:
        splits[e.split] += 1
    return Built(
        read=len(rows),
        rows=len(entries),
        joined=joined,
        trivial=sum(1 for v in values if v["trivial"]),
        duplicates=duplicates,
        leaks=sum(1 for e in entries if "leak" in e.flags),
        signatures=signatures,
        splits=[Count(value=s, rows=splits[s]) for s in split.SPLITS if splits[s]],
        cutoff=rule.cutoff,
    )


def _out(w: Writing) -> WritingOut:
    spans: list[list[Any]] = json.loads(w.removed)
    return WritingOut(
        id=w.id,
        at=_utc(w.at),
        platform=w.platform,
        kind=w.kind,
        medium=w.medium,
        work=w.work,
        subject=w.subject,
        text=w.text,
        original=w.original,
        removed=[Removed(kind=str(k), start=int(s), end=int(e)) for k, s, e in spans],
        parts=w.parts,
        words=w.words,
        trivial=w.trivial,
        flags=w.flags.split(),
        split=w.split,
        assisted=w.assisted,
        sample=w.sample,
        checked_as=w.checked_as,
    )


def page(
    db: Session,
    after: int | None = None,
    limit: int = 20,
    medium: str | None = None,
    year: int | None = None,
    trivial: bool | None = None,
) -> Page[WritingOut]:
    """One page of the writing, newest first, after the row with id `after` (rows are written oldest first, so ids
    follow time). Filtered by medium, year and whether trivial."""
    q = select(Writing).order_by(Writing.id.desc()).limit(limit + 1)
    if after is not None:
        q = q.where(Writing.id < after)
    if medium:
        q = q.where(Writing.medium == medium)
    if year is not None:
        start = datetime.datetime(year, 1, 1, tzinfo=datetime.UTC)
        q = q.where(Writing.at >= start, Writing.at < start.replace(year=year + 1))
    if trivial is not None:
        q = q.where(Writing.trivial == trivial)
    rows = list(db.scalars(q))
    items = [_out(w) for w in rows[:limit]]
    return Page[WritingOut](items=items, next=str(items[-1].id) if len(rows) > limit else None)


def to_check(db: Session, medium: str) -> list[WritingOut]:
    """The rows of a medium's cleaning sample the person has not marked yet, in sample order."""
    q = select(Writing).where(Writing.medium == medium, Writing.sample.is_not(None), Writing.checked_as.is_(None))
    return [_out(w) for w in db.scalars(q.order_by(Writing.sample))]


def check(db: Session, writing_id: int, verdict: str | None) -> WritingOut:
    """Mark how a row was cleaned (one of `VERDICTS`), or clear the mark (None)."""
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError(f"{verdict!r} is not a verdict; one of {', '.join(VERDICTS)}.")
    w = db.get(Writing, writing_id)
    if w is None:
        raise KeyError(f"There is no writing {writing_id}.")
    w.checked_as = verdict
    w.checked = None if verdict is None else _now()
    db.commit()
    return _out(w)


def _counts(db: Session, column: Any) -> list[Count]:
    return [
        Count(value=str(v), rows=n)
        for v, n in db.execute(select(column, func.count()).group_by(column).order_by(column))
    ]


def summary(db: Session, queue: Queue | None = None) -> WritingSummary:
    """Rows by medium, split, year and flag, the split, the last build and its job."""
    mediums: list[MediumCount] = []
    rows = 0
    for medium in MEDIUMS:
        base = select(func.count()).select_from(Writing).where(Writing.medium == medium)
        n = db.scalar(base) or 0
        if not n:
            continue
        rows += n
        first, last = db.execute(
            select(func.min(Writing.at), func.max(Writing.at)).where(Writing.medium == medium)
        ).one()
        mediums.append(
            MediumCount(
                medium=medium,
                rows=n,
                trivial=db.scalar(base.where(Writing.trivial.is_(True))) or 0,
                words=db.scalar(
                    select(func.coalesce(func.sum(Writing.words), 0)).where(
                        Writing.medium == medium, Writing.trivial.is_(False)
                    )
                )
                or 0,
                first=sources.when(first),
                last=sources.when(last),
                sample=db.scalar(base.where(Writing.sample.is_not(None))) or 0,
                checked=db.scalar(base.where(Writing.checked_as.is_not(None))) or 0,
                clean=db.scalar(base.where(Writing.checked_as == "clean")) or 0,
            )
        )
    years: dict[str, int] = defaultdict(int)
    for (at,) in db.execute(select(Writing.at)):
        years[str(sources.when(at).year)] += 1
    flags: dict[str, int] = defaultdict(int)
    for (f,) in db.execute(select(Writing.flags).where(Writing.flags != "")):
        for code in str(f).split():
            flags[code] += 1
    rule = db.scalars(select(WritingSplit).order_by(WritingSplit.id)).first()
    built = db.scalar(select(func.max(Writing.built)))
    job = None
    if queue is not None:
        found = queue.page(kind=KIND, limit=1).items
        job = found[0] if found else None
    return WritingSummary(
        built=None if built is None else sources.when(built),
        rows=rows,
        assisted=db.scalar(select(func.count()).select_from(Writing).where(Writing.assisted.is_(True))) or 0,
        mediums=mediums,
        splits=sorted(
            _counts(db, Writing.split), key=lambda c: split.SPLITS.index(c.value) if c.value in split.SPLITS else 99
        ),
        years=[Count(value=y, rows=years[y]) for y in sorted(years)],
        flags=[Count(value=k, rows=flags[k]) for k in sorted(flags)],
        cutoff=None if rule is None else _utc(rule.cutoff),
        holdout=0 if rule is None else len(rule.holdout.split()),
        job=job,
    )


def export(db: Session, include_trivial: bool = False) -> Iterator[str]:
    """The writing as JSON lines, oldest first, copies left out: one record per row, for looking at outside the app."""
    q = select(Writing).order_by(Writing.id)
    if not include_trivial:
        q = q.where(Writing.trivial.is_(False))
    for w in db.scalars(q.execution_options(yield_per=2000)):
        if "duplicate" in w.flags.split() or "near-duplicate" in w.flags.split():
            continue
        o = _out(w)
        yield (
            json.dumps(
                o.model_dump(mode="json", exclude={"original", "removed", "sample", "checked_as"}), ensure_ascii=False
            )
            + "\n"
        )


def start(queue: Queue) -> Task:
    """Queue a build (one at a time: a second request while one waits or runs is the same job)."""
    job_id = queue.enqueue(KIND, {}, domain="writing", dedupe=True)
    job = queue.get(job_id)
    if job is None:  # pragma: no cover - the row was just written
        raise KeyError(f"There is no job {job_id}.")
    return job.to_task()


def run_build(engine: Engine) -> Built:
    """A build on the app's database, reading from the writing source (source.engine)."""
    src = sources.engine(engine)
    try:
        with Session(engine) as s:
            return build(s, src)
    finally:
        if src is not engine:
            src.dispose()


def handler(engine: Callable[[], Engine]) -> Callable[[Job], Any]:
    """The queue's `writing` handler on the server's (or the CLI's) database."""

    def run(job: Job) -> Any:
        return run_build(engine()).model_dump(mode="json")

    return run
