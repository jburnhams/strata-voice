"""What the recordings cover, and which prompt to ask for next (step 3; spec §6 and §7.1).

Coverage is counted over the text of every prompt with a usable take (an old free-talk take counts its transcript),
as units in six groups:

  phoneme        RP's 43 phonemes (phonemes.INVENTORY), each time one is said
  pair           two phonemes in a row, across word boundaries too (connected speech): the spec's phoneme bigrams
  stress         the stress pattern of each word of two or more syllables ("010", "banana")
  length         short (up to 6 words), medium (to 14) or long
  sentence       statement, yes/no question, wh-question, exclamation, list, several sentences
  style          the prompt's delivery (curriculum.STYLES)

`rank` orders the generated prompts still to record by expected value per second of the speaker's time, the spec's
`utility` with the terms this step can measure (teacher disagreement and student error come with a model): each unit
a prompt has is worth its group's weight over one plus the times it has been said, so a phoneme never said is worth
the most and a common one little; that sum is divided by the seconds the prompt takes to set up and say, and cut by
how much its words repeat a prompt already recorded or ranked above it. The order is greedy: once a prompt is
placed, what it would add counts as said, so the next one is chosen for what is still missing (a queue of ten
prompts all after the same rare sound would waste nine). The starter set keeps its own order first; generated
prompts follow it. The weights and timings are first guesses for step 4 (the pilot) to tune.

The queue is ranked again every `RERANK_EVERY` usable takes (spec §7.3: every 5 to 10 recordings), after a batch of
prompts is written, and by `strata-voice rank`; ranking moves only `position` and `score`."""

import itertools
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from strata_python.contracts import ApiModel

from stratavoice import curriculum, phonemes, scoring
from stratavoice.models import Prompt, Take

GENERATED = "generated"
#: Generated prompts are placed after the starter set: their positions start here.
GENERATED_BASE = 100_000
RERANK_EVERY = 5

#: What one new unit of each group is worth. Phonemes and styles are what a voice model most visibly lacks when they
#: are missing; pairs are many and each matters less.
WEIGHTS = {"phoneme": 4.0, "pair": 1.0, "stress": 1.5, "length": 1.0, "sentence": 2.0, "style": 3.0}
GROUPS = tuple(WEIGHTS)
TITLES = {
    "phoneme": "Phonemes",
    "pair": "Phoneme pairs",
    "stress": "Stress patterns",
    "length": "Lengths",
    "sentence": "Sentence types",
    "style": "Styles",
}
#: Seconds a prompt costs before its words: reading it, Record, Stop, the check. A cue to act on adds a little.
SETUP_SECONDS = 4.0
CUE_SECONDS = 2.0
WORDS_PER_SECOND = 2.5  # unhurried read speech, about 150 words a minute

LENGTHS = ("short", "medium", "long")
SENTENCES = ("statement", "yes/no question", "wh-question", "exclamation", "list", "several sentences")
# A wh-word opening the question or its last clause ("Hang on, where did I put my keys?").
_WH = re.compile(r"(^|[,;:]\s*)\W*(what|when|where|which|who|whom|whose|why|how)\b", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z']+")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "from",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "our",
        "their",
        "not",
        "no",
        "so",
        "if",
        "as",
        "do",
        "did",
        "does",
        "have",
        "has",
        "had",
        "will",
        "would",
        "can",
        "could",
        "just",
        "then",
        "there",
        "here",
    ]
)


Unit = tuple[str, str]  # (group, value)


@dataclass(frozen=True)
class Text:
    """What coverage needs of a prompt: its words, its phonemes (kept, or None) and its style."""

    text: str
    phonemes: str | None
    style: str | None
    cue: str | None = None


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def length(text: str) -> str:
    n = len(words(text))
    return "short" if n <= 6 else "medium" if n <= 14 else "long"


def sentence_types(text: str) -> set[str]:
    """The sentence types of a text (one text can be several: a statement and then a question)."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    found: set[str] = set()
    for part in parts:
        if part.endswith("?"):
            found.add("wh-question" if _WH.search(part) else "yes/no question")
        elif part.endswith("!"):
            found.add("exclamation")
        else:
            found.add("statement")
        if part.count(",") >= 2 and re.search(r"\b(and|or)\b", part):
            found.add("list")
    if len(parts) >= 2:
        found.add("several sentences")
    return found


def units(t: Text) -> Counter[Unit]:
    """Every unit a text has, with how many times."""
    out: Counter[Unit] = Counter()
    for clause in phonemes.parse(t.phonemes) if t.phonemes else []:
        flat = [p for w in clause for p in w.phones]
        out.update(("phoneme", p) for p in flat)
        out.update(("pair", f"{a} {b}") for a, b in itertools.pairwise(flat))
        out.update(("stress", w.stress) for w in clause if len(w.stress) >= 2)
    out[("length", length(t.text))] += 1
    out.update(("sentence", s) for s in sentence_types(t.text))
    if t.style:
        out[("style", t.style)] += 1
    return out


def seconds(t: Text) -> float:
    """What a prompt costs the speaker, roughly: setting up, its words, and acting on a cue."""
    return SETUP_SECONDS + len(words(t.text)) / WORDS_PER_SECOND + (CUE_SECONDS if t.cue else 0.0)


def _content(text: str) -> frozenset[str]:
    return frozenset(w.lower() for w in words(text) if w.lower() not in _STOPWORDS)


def _overlap(a: frozenset[str], others: Iterable[frozenset[str]]) -> float:
    """The most of `a`'s content words shared with any of `others` (Jaccard), 0 when it has none."""
    return max((len(a & b) / len(a | b) for b in others if a and b), default=0.0)


def gain(have: Counter[Unit], candidate: Counter[Unit]) -> float:
    """What a prompt adds: each of its units once, worth its group's weight over one plus the times already said."""
    return sum(WEIGHTS[g] / (1 + have[(g, v)]) for g, v in candidate)


def value(have: Counter[Unit], t: Text, unit_counts: Counter[Unit], seen: Sequence[frozenset[str]]) -> float:
    """A prompt's value per second of the speaker's time, cut by how much it repeats what was said."""
    return gain(have, unit_counts) / seconds(t) * (1.0 - _overlap(_content(t.text), seen))


def _text(p: Prompt, transcript: str | None = None) -> Text:
    if transcript is not None:  # old free talk: what was said is its text
        return Text(transcript, phonemes.ipa_or_none(transcript), None)
    return Text(p.text, p.phonemes, p.style, p.cue)


def recorded(db: Session) -> list[Text]:
    """The text of every prompt with a usable take (its newest, for an old free-talk one's transcript)."""
    newest = select(Take.prompt_id, Take.transcript).where(scoring.usable()).order_by(Take.id)
    transcripts: dict[int, str | None] = {pid: tr for pid, tr in db.execute(newest)}  # noqa: C416 - a Row is not a pair to dict()
    out: list[Text] = []
    for p in db.scalars(select(Prompt).where(Prompt.id.in_(transcripts)).order_by(Prompt.position)):
        if p.kind != curriculum.FREE_TALK:
            out.append(_text(p))
        elif transcripts[p.id]:
            out.append(_text(p, transcripts[p.id]))
    return out


def counted(texts: Iterable[Text]) -> Counter[Unit]:
    have: Counter[Unit] = Counter()
    for t in texts:
        have.update(units(t))
    return have


def pending(db: Session) -> list[Prompt]:
    """The generated prompts still to record: no usable take, not skipped, in the training set."""
    done = select(Take.prompt_id).where(scoring.usable())
    q = select(Prompt).where(
        Prompt.source == GENERATED, Prompt.skipped.is_(None), Prompt.id.not_in(done), Prompt.partition == "train"
    )
    return list(db.scalars(q.order_by(Prompt.id)))


def rank(db: Session) -> int:
    """Order the generated prompts still to record by value (greedy; see the module docstring), writing `position`
    and `score`. Returns how many were ranked."""
    said = recorded(db)
    have = counted(said)
    seen = [_content(t.text) for t in said]
    left = [(p, _text(p)) for p in pending(db)]
    each = {p.id: units(t) for p, t in left}
    place = GENERATED_BASE
    while left:
        scored = [(value(have, t, each[p.id], seen), -p.id, i) for i, (p, t) in enumerate(left)]
        best, _, i = max(scored)
        p, t = left.pop(i)
        place += 1
        p.position, p.score = place, round(best, 4)
        have.update(each[p.id])
        seen.append(_content(t.text))
    db.commit()
    return place - GENERATED_BASE


def due(db: Session) -> bool:
    """Whether the queue should be ranked again: every `RERANK_EVERY` usable takes."""
    n = db.scalar(select(func.count()).select_from(Take).where(scoring.usable())) or 0
    return n > 0 and n % RERANK_EVERY == 0


class UnitOut(ApiModel):
    """One unit and how often it has been said; `example` is a word that has it, for a phoneme."""

    value: str
    count: int
    example: str | None


class Group(ApiModel):
    """One group of units: how many of its inventory have been said at least once (`inventory` null where the set is
    open, as for pairs and stress patterns), and its units, least said first (every one of a known inventory, so the
    missing ones show)."""

    key: str
    title: str
    covered: int
    inventory: int | None
    units: list[UnitOut]


class Coverage(ApiModel):
    """What the recordings cover. `prompts` counts those recorded and `seconds` what they took; `waiting` the generated
    prompts still to record; `phonemised` is false when espeak is missing, so phonemes cannot be counted."""

    prompts: int
    waiting: int
    phonemised: bool
    groups: list[Group]


_INVENTORIES: dict[str, dict[str, str | None]] = {
    "phoneme": dict(phonemes.INVENTORY),
    "length": dict.fromkeys(LENGTHS),
    "sentence": dict.fromkeys(SENTENCES),
    "style": dict.fromkeys(curriculum.STYLES),
}
#: Open groups list only their least said units; a pair never said is not listed, as most pairs never occur.
OPEN_LIMIT = 40


def group(key: str, have: Counter[Unit]) -> Group:
    said = {v: n for (g, v), n in have.items() if g == key}
    known = _INVENTORIES.get(key)
    if known is None:
        items = sorted(said.items(), key=lambda kv: (kv[1], kv[0]))[:OPEN_LIMIT]
        out = [UnitOut(value=v, count=n, example=None) for v, n in items]
        return Group(key=key, title=TITLES[key], covered=len(said), inventory=None, units=out)
    order = list(known)
    out = sorted(
        (UnitOut(value=v, count=said.get(v, 0), example=known[v]) for v in order),
        key=lambda u: (u.count, order.index(u.value)),
    )
    covered = sum(1 for v in order if said.get(v, 0))
    return Group(key=key, title=TITLES[key], covered=covered, inventory=len(order), units=out)


def coverage(db: Session) -> Coverage:
    said = recorded(db)
    have = counted(said)
    return Coverage(
        prompts=len(said),
        waiting=len(pending(db)),
        phonemised=phonemes.available(),
        groups=[group(g, have) for g in GROUPS],
    )
