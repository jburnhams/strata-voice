"""Prompts for the tests: the `write` role's answer (a JSON list of candidate prompts, as strata-models' cloud runtimes
give it when the job has a `schema`) for `fake_models` to give back, and generated prompts added straight to the
database, phonemised as the writer would."""

import datetime
from typing import Any

from sqlalchemy.orm import Session

from stratavoice import coverage, phonemes
from stratavoice.models import Prompt


def offer(*items: dict[str, Any], cost: float | None = 0.031, as_text: bool = False) -> dict[str, Any]:
    """The write role's result offering `items` ({text, kind, style, cue}). `as_text` gives the JSON only as the
    answer's text, as a model that ignored the schema does."""
    body = {"prompts": list(items)}
    if as_text:
        import json

        return {"text": json.dumps(body), "json": None, "cost_usd": cost}
    return {"text": "", "json": body, "cost_usd": cost}


def candidate(text: str, kind: str = "phonetic", style: str = "neutral", cue: str | None = None) -> dict[str, Any]:
    return {"text": text, "kind": kind, "style": style, "cue": cue}


def generated(
    db: Session, text: str, *, kind: str = "phonetic", style: str = "neutral", cue: str | None = None
) -> Prompt:
    """A generated prompt kept as the writer keeps one (not yet ranked)."""
    p = Prompt(
        key=f"gen-test-{abs(hash((text, cue))):x}"[:60],
        text=text,
        kind=kind,
        cue=cue,
        partition="train",
        source=coverage.GENERATED,
        position=coverage.GENERATED_BASE,
        created=datetime.datetime.now(datetime.UTC),
        style=style,
        phonemes=phonemes.ipa_or_none(text),
        writer="fake-write",
    )
    db.add(p)
    db.commit()
    return p
