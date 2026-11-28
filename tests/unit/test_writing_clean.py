import pytest

from stratavoice.writing import clean


def cut(text: str, kept: str, *kinds: str, signatures: frozenset[tuple[str, ...]] = frozenset()) -> None:
    got, spans = clean.clean_email(text, signatures)
    assert got == kept
    assert [k for k, _, _ in spans] == list(kinds)
    # Every span is a piece of the original, and the kept text is the original without them.
    rebuilt, at = "", 0
    for _, start, end in spans:
        rebuilt += text[at:start]
        at = end
    assert (rebuilt + text[at:]).rstrip() == kept


def test_a_plain_mail_is_kept_exactly_as_written() -> None:
    text = "hiya\n\ni'll be there at 8 :)  dont wait up\nJ"
    cut(text, text)


def test_quoted_lines_are_taken_out_and_an_inline_reply_kept() -> None:
    text = "Sounds good.\n\nOn Tue, 3 Mar 2020 at 10:00, Sam <sam@example> wrote:\n> Can you do Friday?\n>\n> Sam\nFriday works.\n"
    cut(text, "Sounds good.\n\nFriday works.", "quote")


def test_an_attribution_wrapped_onto_two_lines() -> None:
    text = "Yes.\nOn Tue, 3 Mar 2020 at 10:00, Sam Smith <\nsam@example> wrote:\n\n> Friday?\n"
    cut(text, "Yes.", "quote")


def test_an_attribution_without_quote_marks_takes_the_rest() -> None:
    # An HTML mail flattened to text: the quoted message follows with no `>`.
    text = "Will do.\n\nOn Mon, Jan 6, 2020 at 9:12 AM Sam wrote:\nPlease send the file.\nThanks"
    cut(text, "Will do.", "quote")


def test_a_lone_quote_block_without_an_attribution() -> None:
    cut("> what time?\n\n8pm", "8pm", "quote")


def test_outlook_headers_and_original_message_take_the_rest() -> None:
    cut("Agreed\n\nFrom: Sam\nSent: 03 March 2020 10:00\nTo: Me\nSubject: Re: plan\n\nold words", "Agreed", "quote")
    cut("Agreed\n-----Original Message-----\nold words", "Agreed", "quote")
    # A `From:` line that is not a header block is the person's text.
    cut("From: the top of the page\nit says no", "From: the top of the page\nit says no")


def test_a_forwarded_message_is_not_theirs() -> None:
    cut("FYI\n\n---------- Forwarded message ---------\nFrom: x\nbody", "FYI", "forward")
    cut("see below\nBegin forwarded message:\n\nstuff", "see below", "forward")


def test_a_dash_dash_signature_and_a_client_footer() -> None:
    cut("Cheers\nJ\n-- \nJ Smith | 07700 900123", "Cheers\nJ", "signature")
    cut("On my way\n\nSent from my iPhone", "On my way", "client")
    cut("ok\nGet Outlook for Android\n", "ok", "client")


def test_a_learnt_signature_goes_and_a_sign_off_stays() -> None:
    signature = ("Jonathan Smith", "Acme Ltd", "+44 20 7946 0000")
    text = "Thanks for this.\n\nCheers,\nJonathan Smith\nAcme Ltd\n+44 20 7946 0000\n"
    cut(text, "Thanks for this.\n\nCheers,", "signature", signatures=frozenset({signature}))
    # Without the learnt block nothing is taken.
    cut(text, text.rstrip())


def test_learn_signatures_needs_repeats_and_the_shape_of_one() -> None:
    sig = "\n--\nA Person\nAcme Ltd\nwww.acme.example"
    mails = [f"note {i}\nThanks,\nJonathan\n{sig.strip()}" for i in range(clean.SIGNATURE_REPEATS)]
    mails += [f"other {i}\nThanks,\nJonathan" for i in range(clean.SIGNATURE_REPEATS)]
    found = clean.learn_signatures(mails)
    assert ("A Person", "Acme Ltd", "www.acme.example") in found
    assert ("www.acme.example",) in found  # contact details on one line are enough
    # A two-line sign-off with no contact details is a habit, not a signature.
    assert ("Thanks,", "Jonathan") not in found
    assert clean.learn_signatures(mails[: clean.SIGNATURE_REPEATS - 1]) == frozenset()


@pytest.mark.parametrize(
    ("text", "replied", "leaked"),
    [
        (
            "as you said the train leaves at eight from platform four tomorrow",
            "the train leaves at eight from platform four tomorrow morning",
            True,
        ),
        ("the train leaves at eight", "the train leaves at eight from platform four tomorrow morning", False),
        ("anything at all here", "too short", False),
    ],
)
def test_a_reply_that_still_holds_the_mail_it_answers(text: str, replied: str, leaked: bool) -> None:
    assert clean.leaks(text, replied) is leaked


def test_words_are_lower_cased() -> None:
    assert clean.words("Hello, World! it's") == ["hello", "world", "it", "s"]


def test_spans_that_touch_or_are_empty_are_merged_or_dropped() -> None:
    assert clean._merge([("quote", 5, 9), ("quote", 3, 3), ("signature", 8, 12), ("client", 12, 14)]) == [
        ("quote", 5, 14)
    ]  # pyright: ignore[reportPrivateUsage]
