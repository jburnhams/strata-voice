"""The starter curriculum: the prompts a new voice is recorded from before the prompt planner has anything to go on.

Shaped by the spoken-voice spec (§6, "Initial recording curriculum"): a balanced pilot of about eight to ten minutes
rather than a long script, in four groups, in the order they are asked for:

  phonetic      ~2 min of short sentences that between them cover English sounds, clusters and stress patterns
  prosodic      ~2 min of contrasts: the same words with the emphasis moved, statement against question
  expressive    ~2 min of everyday, mild expression with a written cue, never a caricature
  evaluation    ~1-2 min held out (`partition = "eval"`): never trained on, kept to measure a model against

The sentences are written for en-GB speech and for this app; none is taken from a published corpus. Each has a stable
`key`, so seeding is idempotent and a later edit to the wording can be tracked against takes already made.

The spec's fifth group, about 90 s of unscripted talk ("talk about your weekend"), is left out: Jonathan does not want
free-talk prompts (2026-11-24), so every prompt is read from its text.

`STYLES` is the vocabulary a prompt's delivery is counted in (coverage.py) and the prompt writer chooses from: the
W3C EmotionML "everyday" categories that suit mild, everyday speech, plus neutral, and four stances that are not
emotions (sarcastic, sympathetic, reassuring, whispered; the spec leaves open how to encode stance, §15). `style()`
gives each starter prompt its one."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Seed:
    key: str
    kind: str
    text: str
    cue: str | None = None
    partition: str = "train"


KINDS = ("phonetic", "prosodic", "expressive", "evaluation")

STYLES = (
    "neutral",
    "happy",
    "amused",
    "excited",
    "pleased",
    "relaxed",
    "confident",
    "interested",
    "affectionate",
    "surprised",
    "puzzled",
    "sad",
    "disappointed",
    "worried",
    "afraid",
    "annoyed",
    "angry",
    "bored",
    "tired",
    "sarcastic",
    "sympathetic",
    "reassuring",
    "whispered",
)

#: The starter prompts whose cue is not neutral delivery (the others read plainly).
_STYLE_OF = {
    "pros-05": "surprised",
    "pros-06": "pleased",
    "pros-07": "sarcastic",
    "pros-11": "reassuring",
    "expr-01": "excited",
    "expr-02": "tired",
    "expr-03": "sympathetic",
    "expr-04": "confident",
    "expr-05": "puzzled",
    "expr-06": "annoyed",
    "expr-07": "whispered",
    "expr-08": "excited",
    "expr-09": "disappointed",
    "expr-10": "amused",
    "eval-04": "relaxed",
    "eval-05": "pleased",
    "eval-06": "sympathetic",
}

PHONETIC = [
    Seed("phon-01", "phonetic", "The thick fog over the harbour cleared just before the ferry left."),
    Seed("phon-02", "phonetic", "She measured the beige fabric twice before cutting the pleasure boat's sail."),
    Seed("phon-03", "phonetic", "Judge the choir on their joy, not on the strength of their voices."),
    Seed("phon-04", "phonetic", "A quiet young queen wrapped twelve woollen scarves in the wardrobe."),
    Seed("phon-05", "phonetic", "Bring the singing children home through the long, winding lane."),
    Seed("phon-06", "phonetic", "Our neighbour's dog buried a bone beneath the old oak tree."),
    Seed("phon-07", "phonetic", "Three thousand birds gathered on the northern cliffs this month."),
    Seed("phon-08", "phonetic", "Few people knew the view from the tower was quite so beautiful."),
    Seed("phon-09", "phonetic", "The plumber's apprentice spilled a jug of hot soup on his boots."),
    Seed("phon-10", "phonetic", "Clare and her father shared a pair of hired bikes near the pier."),
    Seed("phon-11", "phonetic", "Strong rhythms and twelfth-century sculptures fill the cathedral's crypt."),
    Seed("phon-12", "phonetic", "Would you rather have a photograph or a hand-drawn picture of the castle?"),
    Seed("phon-13", "phonetic", "The garage on Tuesday asked for eighty-five pounds and sixty pence."),
    Seed("phon-14", "phonetic", "Usually the lazy zebra yawns at visitors in the zoo's enclosure."),
]

PROSODIC = [
    Seed("pros-01", "prosodic", "I didn't say she took the money.", "neutral, no word stressed"),
    Seed("pros-02", "prosodic", "I didn't say she took the money.", "stress 'say': I only implied it"),
    Seed("pros-03", "prosodic", "I didn't say she took the money.", "stress 'she': someone else did"),
    Seed("pros-04", "prosodic", "You're coming tomorrow.", "a plain statement"),
    Seed("pros-05", "prosodic", "You're coming tomorrow?", "a surprised question"),
    Seed("pros-06", "prosodic", "Well, that went better than expected.", "sincere, relieved"),
    Seed("pros-07", "prosodic", "Well, that went better than expected.", "dry, sarcastic"),
    Seed("pros-08", "prosodic", "We need eggs, flour, butter and sugar, and then we can start.", "a list, unhurried"),
    Seed("pros-09", "prosodic", "If the train is late again, I'm taking the car.", None),
    Seed("pros-10", "prosodic", "Can you pass the salt? Thanks. And the pepper, please.", None),
    Seed("pros-11", "prosodic", "It's fine. Honestly, it's fine. Don't worry about it.", "reassuring, slowing down"),
]

EXPRESSIVE = [
    Seed("expr-01", "expressive", "Oh, you're joking! That's brilliant news.", "delighted"),
    Seed(
        "expr-02", "expressive", "I've told you three times now. Please put your shoes away.", "patient, a little tired"
    ),
    Seed(
        "expr-03",
        "expressive",
        "I'm so sorry to hear that. Let me know if there's anything I can do.",
        "gentle, sympathetic",
    ),
    Seed("expr-04", "expressive", "Right, everyone, listen up. We leave in ten minutes.", "brisk, in charge"),
    Seed("expr-05", "expressive", "Hang on, where did I put my keys?", "puzzled, to yourself"),
    Seed(
        "expr-06", "expressive", "That's the third parcel this week that's gone to the wrong house.", "mildly annoyed"
    ),
    Seed("expr-07", "expressive", "Shh, the baby's finally asleep.", "whispered"),
    Seed(
        "expr-08",
        "expressive",
        "And then, just as we got to the top, the clouds cleared.",
        "telling a story, building up",
    ),
    Seed(
        "expr-09",
        "expressive",
        "Oh. Right. I didn't realise it had already been decided.",
        "disappointed, trying not to show it",
    ),
    Seed("expr-10", "expressive", "Go on then, just one more biscuit.", "playful, giving in"),
]

EVALUATION = [
    Seed("eval-01", "evaluation", "The library closes early on Saturdays during the summer.", partition="eval"),
    Seed("eval-02", "evaluation", "Could you send me the address before you set off?", partition="eval"),
    Seed("eval-03", "evaluation", "We watched the storm roll in from the comfort of the kitchen.", partition="eval"),
    Seed("eval-04", "evaluation", "Honestly, I thought the film was a bit too long.", "relaxed, opinionated", "eval"),
    Seed("eval-05", "evaluation", "Twenty-three people signed up, which is more than last year.", "pleased", "eval"),
    Seed("eval-06", "evaluation", "Don't forget your umbrella; it's meant to pour later.", "caring", "eval"),
]

STARTER: list[Seed] = [*PHONETIC, *PROSODIC, *EXPRESSIVE, *EVALUATION]


def style(seed: Seed) -> str:
    """A starter prompt's style: its cue's, or neutral."""
    return _STYLE_OF.get(seed.key, "neutral")
