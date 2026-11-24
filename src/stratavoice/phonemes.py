# ruff: noqa: RUF001, RUF002, RUF003 - IPA is this module's subject; its letters are meant, not look-alikes
"""British English phonemes of a text, from espeak-ng's `en-gb-x-rp` voice (spec §6: "an explicit phoneme and
phoneme-bigram inventory (with British English phonemisation)").

espeak-ng is a rule-and-lexicon phonemiser that runs locally on Linux, macOS and Windows in milliseconds, so the
coverage ranker stays deterministic and offline. It is a program the speaker installs (`apt install espeak-ng`,
`brew install espeak-ng`, the Windows installer), like ffmpeg for other apps; the `espeak` setting names it when it
is not on the PATH, and `strata-voice doctor` says whether it was found.

A text is phonemised once, when its prompt is added, and the result kept on the prompt (`Prompt.phonemes`): espeak's
own IPA, phones joined by `_`, words by spaces, clauses by ` | `. `parse` reads that back, so ranking never runs
espeak and a prompt keeps the phonemes it was ranked by. Without espeak the prompt is kept with none, and coverage
counts what it can without them (length, sentence type, style).

The inventory is Received Pronunciation's (`VOICE`): 24 consonants and 19 vowels, the textbooks' 44 less /ʊə/, which
today's RP (and espeak's RP voice) has merged into /ɔː/, so it would never be said and always look missing. A few
symbols are folded into it (`FOLD`): plain `en-gb`'s "a" of "trap" and its /ʊə/, the reduced vowel of "ago" (schwa),
the final vowel of "happy" (/ɪ/), and a syllabic "l" or a triphthong, which count as their parts."""

import functools
import shutil
import subprocess
from dataclasses import dataclass

from stratavoice import settings

#: Received Pronunciation, the accent the inventory below is (plain `en-gb` gives "bath" the vowel of "trap").
#: Another accent would need its own inventory.
VOICE = "en-gb-x-rp"
TIMEOUT_SECONDS = 10.0

PRIMARY, SECONDARY = "ˈ", "ˌ"  # written before the stressed vowel's phone

#: The inventory in espeak's symbols, each with a word that has it: what coverage is counted against, and how the
#: prompt writer is told which sounds are missing.
CONSONANTS: dict[str, str] = {
    "p": "pin",
    "b": "bin",
    "t": "tin",
    "d": "din",
    "k": "kin",
    "ɡ": "go",
    "tʃ": "chin",
    "dʒ": "gin",
    "f": "fin",
    "v": "van",
    "θ": "thin",
    "ð": "then",
    "s": "sin",
    "z": "zoo",
    "ʃ": "shin",
    "ʒ": "measure",
    "h": "hat",
    "m": "man",
    "n": "no",
    "ŋ": "sing",
    "l": "let",
    "ɹ": "red",
    "j": "yes",
    "w": "wet",
}
VOWELS: dict[str, str] = {
    "ɪ": "kit",
    "ɛ": "dress",
    "æ": "trap",
    "ʌ": "strut",
    "ɒ": "lot",
    "ʊ": "foot",
    "ə": "comma",
    "iː": "fleece",
    "ɑː": "palm",
    "ɔː": "thought",
    "uː": "goose",
    "ɜː": "nurse",
    "eɪ": "face",
    "aɪ": "price",
    "ɔɪ": "choice",
    "əʊ": "goat",
    "aʊ": "mouth",
    "iə": "near",
    "eə": "square",
}
INVENTORY: dict[str, str] = {**CONSONANTS, **VOWELS}

FOLD: dict[str, tuple[str, ...]] = {
    "a": ("æ",),  # trap, as plain en-gb writes it
    "ʊə": ("ɔː",),  # cure: modern RP says "poor" and "pour" alike, as the RP voice does
    "ɐ": ("ə",),  # ɐ (ago) -> ə
    "i": ("ɪ",),  # happY, as plain en-gb writes it
    "əl": ("ə", "l"),  # syllabic l (bottle)
    "aɪə": ("aɪ", "ə"),  # aɪə (fire)
    "aʊə": ("aʊ", "ə"),  # aʊə (hour)
}

_VOWEL_LETTERS = set("iyɨʉɯɪʏuʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒ")


class Unavailable(RuntimeError):
    """espeak-ng is not installed, or the `espeak` setting names no program that runs."""


@dataclass(frozen=True)
class Word:
    """One word's phones (folded into the inventory's symbols, stress marks off) and its stress pattern: a digit per
    syllable, 1 primary, 2 secondary, 0 none ("010" is "banana")."""

    phones: tuple[str, ...]
    stress: str


def program() -> str | None:
    """The espeak program: the `espeak` setting when it is set, else espeak-ng or espeak on the PATH."""
    named = settings.espeak()
    if named:
        return shutil.which(named)
    return shutil.which("espeak-ng") or shutil.which("espeak")


def available() -> bool:
    return program() is not None


@functools.lru_cache(maxsize=4096)
def _run(exe: str, text: str) -> str:
    # The text goes on stdin, not as an argument: a prompt that starts with "-" would read as an option.
    done = subprocess.run(  # noqa: S603 - a fixed program and options; the text is data on stdin
        [exe, "-q", "-v", VOICE, "--ipa", "--sep=_"],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf8",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    if done.returncode != 0:
        raise Unavailable(f"espeak-ng could not read the text: {done.stderr.strip() or done.returncode}")
    return " | ".join(line.strip() for line in done.stdout.splitlines() if line.strip())


def ipa(text: str) -> str:
    """The text's phonemes as espeak writes them (the form kept on a prompt). Unavailable without espeak."""
    exe = program()
    if exe is None:
        raise Unavailable(
            "espeak-ng is not installed, so prompts cannot be phonemised: install it, or set `espeak` to its path."
        )
    return _run(exe, text)


def ipa_or_none(text: str) -> str | None:
    """`ipa`, or None when espeak is not there: a prompt is still kept, and coverage counts it without phonemes."""
    try:
        return ipa(text)
    except Unavailable:
        return None


def _is_vowel(phone: str) -> bool:
    return phone[0] in _VOWEL_LETTERS


def _word(token: str) -> Word | None:
    phones: list[str] = []
    stress = ""
    for raw in token.split("_"):
        mark = "1" if PRIMARY in raw else "2" if SECONDARY in raw else "0"
        bare = raw.replace(PRIMARY, "").replace(SECONDARY, "").replace("‍", "")
        if not bare:
            continue
        for phone in FOLD.get(bare, (bare,)):
            phones.append(phone)
            if _is_vowel(phone):
                stress += mark
                mark = "0"  # a folded triphthong is one stressed vowel and a schwa
    return Word(tuple(phones), stress) if phones else None


def parse(kept: str) -> list[list[Word]]:
    """The clauses of a kept phoneme string, each a list of words."""
    clauses: list[list[Word]] = []
    for clause in kept.split(" | "):
        words = [w for w in (_word(t) for t in clause.split()) if w is not None]
        if words:
            clauses.append(words)
    return clauses
