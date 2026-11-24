"""Writing new prompts (step 3; spec §6 "Use an LLM to produce candidate prompts but a deterministic coverage analyser
to score them", §7.1 "Generate 20-100 candidate prompts at a time, constrained to be natural and short").

A cloud model writes a batch through strata-models' `write` role (Claude Sonnet by default; the role, not this app,
chooses the model). Its brief is what coverage.py finds missing: the phonemes said least, each with a word that has
it, the sentence types and styles said least, and the kinds of prompt to write. The answer is a JSON list (the job's
`schema`). Each candidate is checked here, phonemised (phonemes.py) and kept as a prompt with `source` "generated";
then the queue is ranked (coverage.rank), so the writer proposes and the ranker decides what is asked first.

Only the prompts' text leaves the computer: the brief names sounds and styles, never a recording or a transcript
(design brief: "the takes never leave the speaker's computer")."""

import datetime
import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from strata_python.clients import models as sm
from strata_python.contracts import ApiModel

from stratavoice import coverage, curriculum, phonemes
from stratavoice.models import Prompt

log = logging.getLogger(__name__)

APP = "strata-voice"
ROLE = "write"
DEFAULT_COUNT = 40
MAX_COUNT = 100
WAIT_SECONDS = 300.0  # a batch of 40 is a minute or so of a cloud model's writing
MAX_TOKENS = 8000  # about 60 tokens a prompt with its fields, with room to spare
KINDS = ("phonetic", "prosodic", "expressive")
MIN_WORDS, MAX_WORDS = 3, 30
MAX_CHARS = 300
MAX_CUE = 120
#: How many of each group's least said units the brief names.
BRIEF_PHONEMES, BRIEF_SENTENCES, BRIEF_STYLES = 10, 3, 8

SYSTEM = """You write short prompts for a British English speaker to read aloud in a home recording studio. The \
recordings will teach a voice model how this person sounds, so the prompts must be what a real person would say: \
natural, everyday British English (spelling, vocabulary and idiom), easy to read at a glance, and emotionally \
plausible. Never ask for a caricature: expression is mild and everyday, as in real life.

Rules for every prompt:
- One to three sentences, between three and thirty words.
- Spell numbers out as words ("twenty-three", never "23") and avoid abbreviations, symbols and initialisms.
- Avoid rare proper names: a speech recogniser checks each reading against the text.
- No quotation marks around the whole prompt, no stage directions inside the text.
- Every prompt different from the others in topic and wording.

Kinds:
- phonetic: an ordinary sentence that happens to contain the sounds asked for, several times if natural. style is \
"neutral" and cue is null.
- prosodic: a sentence whose meaning depends on emphasis, intonation or rhythm: a question against a statement, a \
list, a contrast, stress on one word. The cue says how to say it in a few words ("stress 'she'", "a surprised \
question").
- expressive: a line someone would really say in a situation that calls for the style; the cue names the feeling \
in a few plain words ("a little tired", "delighted"). Never exaggerated."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "style": {"type": "string", "enum": list(curriculum.STYLES)},
                    "cue": {"type": ["string", "null"]},
                },
                "required": ["text", "kind", "style", "cue"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["prompts"],
    "additionalProperties": False,
}


class WriterFailed(RuntimeError):
    """The writer ran and gave nothing usable, or took too long (a 502 with the sentence)."""


class Written(ApiModel):
    """A batch: how many prompts the writer offered, how many were kept (the rest repeated a prompt or broke a rule),
    which model wrote them, what it cost when the service says, and how many generated prompts now wait."""

    offered: int
    added: int
    writer: str | None
    cost_usd: float | None
    waiting: int


def brief(cov: coverage.Coverage, count: int) -> str:
    """The instruction for one batch: how many of each kind, and what the recordings lack so far."""
    groups = {g.key: g for g in cov.groups}
    lines = [
        f"Write {count} new prompts: about half phonetic, a quarter prosodic and a quarter expressive.",
        "",
        "What the recordings so far lack, least said first; aim the prompts at these:",
    ]
    if cov.phonemised:
        sounds = [
            f"/{u.value}/ as in “{u.example}”" + (" (never said yet)" if u.count == 0 else f" (said {u.count} times)")
            for u in groups["phoneme"].units[:BRIEF_PHONEMES]
        ]
        lines.append("- Sounds: " + "; ".join(sounds) + ".")
    lines.append("- Sentence types: " + ", ".join(u.value for u in groups["sentence"].units[:BRIEF_SENTENCES]) + ".")
    lines.append(
        "- Styles for the expressive and prosodic prompts: "
        + ", ".join(u.value for u in groups["style"].units[:BRIEF_STYLES])
        + "."
    )
    lines.append("")
    lines.append("Mix short, medium and long prompts. Answer with the JSON object only.")
    return "\n".join(lines)


def _key(text: str, cue: str | None) -> str:
    # Named by its words and cue, so the same prompt written twice (in two batches) is one prompt.
    return "gen-" + hashlib.sha256(f"{text}\n{cue or ''}".encode()).hexdigest()[:16]


def check(item: object) -> tuple[str, str, str, str | None] | None:
    """A candidate as (text, kind, style, cue), or None when it breaks a rule the speaker or the scorer would trip on."""
    if not isinstance(item, dict):
        return None
    fields: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType] - a JSON object from the model
    text, kind, style, cue = fields.get("text"), fields.get("kind"), fields.get("style"), fields.get("cue")
    if not isinstance(text, str) or kind not in KINDS:
        return None
    text = " ".join(text.split()).strip('"“”')
    n = len(coverage.words(text))
    if not MIN_WORDS <= n <= MAX_WORDS or len(text) > MAX_CHARS or any(c.isdigit() for c in text):
        return None  # digits: a recogniser writes "23" or "twenty-three" at will, and the check would fail either way
    clean_style = style if style in curriculum.STYLES else "neutral"
    clean_cue = (" ".join(cue.split())[:MAX_CUE] or None) if isinstance(cue, str) else None
    return text, str(kind), str(clean_style), clean_cue


def _answer(result: sm.Json) -> list[object]:
    parsed: object = result.get("json")
    if parsed is None and isinstance(result.get("text"), str):
        try:
            parsed = json.loads(str(result["text"]))
        except ValueError:
            parsed = None
    found: dict[str, object] = parsed if isinstance(parsed, dict) else {}  # pyright: ignore[reportUnknownVariableType] - JSON
    items = found.get("prompts")
    if not isinstance(items, list):
        raise WriterFailed("The prompt writer's answer had no list of prompts. Try again.")
    return list(items)  # pyright: ignore[reportUnknownArgumentType] - JSON from the model, checked item by item


def write(db: Session, count: int = DEFAULT_COUNT) -> Written:
    """Ask the writer for `count` prompts, keep the good ones, and rank the queue."""
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"Ask for between 1 and {MAX_COUNT} prompts at a time.")
    params: dict[str, Any] = {
        "prompt": brief(coverage.coverage(db), count),
        "system": SYSTEM,
        "schema": SCHEMA,
        "max_tokens": MAX_TOKENS,
    }
    try:
        result, made = sm.run_with_provenance(ROLE, params, APP, timeout=WAIT_SECONDS)
    except sm.Unavailable as e:
        raise sm.Unavailable(
            f"strata-models is not running, so no prompts can be written: start it and try again. ({e})"
        ) from None
    except TimeoutError:
        raise WriterFailed("The prompt writer took too long. Try again, or ask for fewer.") from None
    except sm.JobFailed as e:
        raise WriterFailed(f"The prompt writer failed: {e}") from None
    items = _answer(result)
    have = set(db.scalars(select(Prompt.key)))
    added = 0
    for item in items:
        ok = check(item)
        if ok is None:
            continue
        text, kind, style, cue = ok
        key = _key(text, cue)
        if key in have:
            continue
        have.add(key)
        added += 1
        db.add(
            Prompt(
                key=key,
                text=text,
                kind=kind,
                cue=cue,
                partition="train",
                source=coverage.GENERATED,
                position=coverage.GENERATED_BASE,  # rank() places it
                created=datetime.datetime.now(datetime.UTC),
                style=style,
                phonemes=phonemes.ipa_or_none(text),
                writer=made.model,
            )
        )
    db.commit()
    log.info("prompt writer %s offered %d, kept %d", made.model, len(items), added)
    coverage.rank(db)
    cost = result.get("cost_usd")
    return Written(
        offered=len(items),
        added=added,
        writer=made.model,
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        waiting=len(coverage.pending(db)),
    )
