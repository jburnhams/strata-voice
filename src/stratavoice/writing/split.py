"""The split of the writing into train, dev and sealed, frozen before anything learns from it.

The largest risk in measuring a written voice is leakage (the design spec, §6; voice-research written-evaluation.md
§2): a random split overstates (LaMP's best score fell from 0.586 to 0.547 under a time split), and a draft judged
against a message whose thread was in the examples is judged against itself. So:

- the unit is a **group**: a mail thread, a chat session (the person's lines in one conversation with no gap over
  `SESSION_GAP`), or a lone post; every row of a group, and every copy of a text (corpus.py's duplicate clusters),
  goes to one split;
- **sealed** is the newest year (from `cutoff`, a year before the newest row when the split was frozen) and every
  group written to a held-out recipient, so the test asks whether the voice carries to new writing and new readers
  (voice-research written-context.md: verification falls from 0.90 within a year to 0.69 after ten);
- **buffer** is the `BUFFER` before the cutoff, used for nothing, so a conversation that runs across the cutoff
  does not leave its last train lines answering its first sealed ones;
- **dev** is a fixed `DEV_SHARE` of the older groups, drawn by hashing the group with the split's seed, for choosing
  among methods; **train** is the rest.

The draw is a hash, not a random state, so the same group always lands in the same split: a rebuild, or new
messages brought in later, never moves an old row (only `freeze` makes the rule, once)."""

import datetime
import hashlib
import secrets
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

TRAIN = "train"
DEV = "dev"
SEALED = "sealed"
BUFFER = "buffer"
SPLITS = (TRAIN, DEV, BUFFER, SEALED)  # in rising order of how held out: a duplicate cluster takes its highest

SEALED_SPAN = datetime.timedelta(days=365)
BUFFER_SPAN = datetime.timedelta(days=7)
SESSION_GAP = datetime.timedelta(hours=6)
DEV_SHARE = 0.10
HOLDOUT_SHARE = 0.05  # of the rows before the cutoff, written to recipients held out whole
KEEP_TOP = 10  # the most written-to recipients are never held out: without them there is too little to learn from
HOLDOUT_MIN = 5  # a recipient written to fewer times than this is too thin to test on


@dataclass(frozen=True)
class Rule:
    """A frozen split (models.WritingSplit)."""

    cutoff: datetime.datetime
    seed: str
    holdout: frozenset[str]


def draw(seed: str, key: str) -> float:
    """A fixed number in [0, 1) for a key: the same split for the same group on every build."""
    return int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:15], 16) / 16**15


def freeze(rows: Iterable[tuple[datetime.datetime, str | None]], seed: str | None = None) -> Rule:
    """The rule for a corpus never split before, from each row's (time, recipient): the cutoff a year before the
    newest row, and the held-out recipients, drawn (by `draw`) until they hold `HOLDOUT_SHARE` of the rows before
    the cutoff, passing over the `KEEP_TOP` most written-to and those under `HOLDOUT_MIN` rows."""
    seed = seed or secrets.token_hex(8)
    listed = list(rows)
    if not listed:
        raise ValueError("There is nothing to split: no writing was read.")
    cutoff = max(at for at, _ in listed) - SEALED_SPAN
    counts = Counter(r for at, r in listed if r is not None and at < cutoff)
    top = {r for r, _ in counts.most_common(KEEP_TOP)}
    budget = HOLDOUT_SHARE * sum(1 for at, _ in listed if at < cutoff)
    held: set[str] = set()
    taken = 0
    for r in sorted(counts, key=lambda r: draw(seed, r)):
        if taken >= budget:
            break
        if r in top or counts[r] < HOLDOUT_MIN or taken + counts[r] > budget * 1.5:
            continue
        held.add(r)
        taken += counts[r]
    return Rule(cutoff=cutoff, seed=seed, holdout=frozenset(held))


def assign(rule: Rule, group: str, last: datetime.datetime, recipients: set[str]) -> str:
    """The split of one group, from its key, its last row's time and the recipients written to in it."""
    if last >= rule.cutoff or recipients & rule.holdout:
        return SEALED
    if last >= rule.cutoff - BUFFER_SPAN:
        return BUFFER
    return DEV if draw(rule.seed, group) < DEV_SHARE else TRAIN


def highest(splits: Iterable[str]) -> str:
    """The most held-out of several splits: where a text with copies in several groups goes."""
    return max(splits, key=SPLITS.index)
