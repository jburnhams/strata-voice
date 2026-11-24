# ruff: noqa: RUF001, RUF003 - IPA is what these tests check; its letters are meant, not look-alikes
"""phonemes.py against the real espeak-ng (installed in CI as ffmpeg is for other apps): British phonemes, stress
patterns, the folds into RP's inventory, and what happens when espeak is missing or broken."""

import sys

import pytest

from stratavoice import phonemes, settings


def _flat(text: str) -> list[str]:
    return [p for clause in phonemes.parse(phonemes.ipa(text)) for w in clause for p in w.phones]


def test_a_sentence_is_read_in_british_english():
    kept = phonemes.ipa("The bath is far.")
    (clause,) = phonemes.parse(kept)
    assert [w.phones for w in clause] == [("ð", "ə"), ("b", "ɑː", "θ"), ("ɪ", "z"), ("f", "ɑː")]  # bath: /ɑː/, no r
    assert [w.stress for w in clause] == ["0", "1", "0", "1"]
    assert phonemes.ipa("The bath is far.") == kept  # the same every time: ranking is deterministic


def test_stress_patterns_and_clauses():
    (first, second) = phonemes.parse(phonemes.ipa("A banana, then a photograph."))
    assert [w.stress for w in first] == ["0", "010"]  # a, banana
    assert second[-1].stress == "102"  # photograph: the last syllable keeps a secondary stress


def test_espeaks_extra_symbols_fold_into_the_inventory():
    assert _flat("ago") == ["ə", "ɡ", "əʊ"]  # ɐ is schwa
    assert _flat("happy")[-1] == "ɪ"  # the happY vowel
    assert "ʊə" not in phonemes.INVENTORY  # merged into /ɔː/ in today's RP
    assert _flat("poor") == ["p", "ɔː"]
    assert len(phonemes.INVENTORY) == 43
    assert _flat("bottle")[-2:] == ["ə", "l"]  # syllabic l
    assert _flat("fire")[-2:] == ["aɪ", "ə"]  # a triphthong is a diphthong and schwa
    (fire,) = phonemes.parse(phonemes.ipa("fire"))[0]
    assert fire.stress == "10"  # one stressed vowel, then the schwa
    assert set(_flat("Usually the measure of a choice is its joy.")) <= set(phonemes.INVENTORY)


def test_text_that_looks_like_an_option_is_still_text():
    assert _flat("-yes") == ["j", "ɛ", "s"]  # sent on stdin, never as an argument


def test_without_espeak_prompts_have_no_phonemes(monkeypatch: pytest.MonkeyPatch):
    settings.SETTINGS.save({"espeak": "no-such-espeak-program"})
    assert (phonemes.program(), phonemes.available()) == (None, False)
    assert phonemes.ipa_or_none("hello") is None
    with pytest.raises(phonemes.Unavailable, match="espeak-ng is not installed"):
        phonemes.ipa("hello")


def test_a_program_that_fails_is_reported():
    settings.SETTINGS.save({"espeak": sys.executable})  # Python, given espeak's options, exits with an error
    with pytest.raises(phonemes.Unavailable, match="espeak-ng could not read the text"):
        phonemes.ipa("hello there")
    assert phonemes.ipa_or_none("hello there") is None


def test_parse_skips_empty_words_and_clauses():
    assert phonemes.parse(" | ð_ɪ_ ˈəʊ_k | ") == [[phonemes.Word(("ð", "ɪ"), "0"), phonemes.Word(("əʊ", "k"), "1")]]
