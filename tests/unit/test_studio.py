import datetime
import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from strata_python.testing import FakeModels, sine_wav
from takes import heard, speech

from stratavoice import coverage, curriculum, phonemes, settings, studio
from stratavoice.models import Prompt


@pytest.fixture
def consented() -> None:
    settings.SETTINGS.save({"consented_on": "2026-11-23"})


def test_the_starter_curriculum_is_seeded_once_in_order(db_session: Session):
    assert studio.seed(db_session) == len(curriculum.STARTER)
    assert studio.seed(db_session) == 0
    listed = studio.prompts(db_session)
    assert [p.key for p in listed] == [s.key for s in curriculum.STARTER]
    assert (listed[0].takes, listed[0].skipped) == (0, False)


def test_the_queue_moves_on_past_recorded_and_skipped_prompts(db_session: Session, consented: None):
    first = studio.studio(db_session)
    assert first.consented
    assert [p.key for p in first.queue] == [s.key for s in curriculum.STARTER[:10]]
    assert first.progress.model_dump() == {
        "prompts": len(curriculum.STARTER),
        "recorded": 0,
        "skipped": 0,
        "takes": 0,
        "seconds": 0.0,
    }

    studio.add_take(db_session, first.queue[0].id, sine_wav(1.0), device="USB mic")
    second = studio.next_prompt(db_session)
    assert second is not None
    assert second.key == "phon-02"
    assert studio.skip(db_session, second.id).skipped
    third = studio.next_prompt(db_session)
    assert third is not None
    assert third.key == "phon-03"
    assert not studio.skip(db_session, second.id, skipped=False).skipped
    back = studio.next_prompt(db_session)
    assert back is not None
    assert back.key == "phon-02"  # put back: in its place again

    studio.add_take(db_session, first.queue[0].id, sine_wav(2.0))  # a retry: another take of the same prompt
    p = studio.progress(db_session)
    assert (p.recorded, p.skipped, p.takes, p.seconds) == (1, 0, 2, 3.0)


def _old_free_talk(db: Session, *keys: str) -> list[Prompt]:
    """Free-talk prompts as a database seeded before 2026-11-24 has them."""
    now = datetime.datetime.now(datetime.UTC)
    rows = [
        Prompt(key=k, text="Talk about your weekend.", kind=curriculum.FREE_TALK, cue=None, partition="train",
               source="starter", position=0, created=now)
        for k in keys
    ]  # fmt: skip
    db.add_all(rows)
    db.commit()
    return rows


def test_free_talk_prompts_from_an_older_curriculum_leave_unless_recorded(
    db_session: Session, consented: None, models: FakeModels
):
    studio.seed(db_session)
    _, kept, judged = _old_free_talk(db_session, "spont-01", "spont-02", "spont-03")
    studio.add_take(db_session, kept.id, speech())
    models.down = False
    models.results["transcribe"] = heard("")  # nothing said: `retry`, so not a usable take
    assert studio.score_take(db_session, studio.add_take(db_session, judged.id, speech()).id).verdict == "retry"
    assert studio.seed(db_session) == 0
    keys = set(db_session.scalars(select(Prompt.key)))
    assert ("spont-01" in keys, "spont-02" in keys, "spont-03" in keys) == (False, True, True)  # kept with their takes
    assert all(p.kind != curriculum.FREE_TALK for p in studio.upcoming(db_session, 100))  # never offered again
    assert judged.skipped is not None
    assert coverage.coverage(db_session).prompts == 0  # not heard yet: no words to count
    studio.seed(db_session)  # already skipped: left as it is
    assert judged.skipped is not None


def test_an_old_free_talk_take_is_its_transcript(db_session: Session, consented: None, models: FakeModels):
    (talk,) = _old_free_talk(db_session, "spont-01")
    models.down = False
    long = " ".join(["Well, my morning started with a very long walk"] * 60)  # 2,880 characters: kept whole
    models.results["transcribe"] = heard(long)
    t = studio.score_take(db_session, studio.add_take(db_session, talk.id, speech()).id)
    assert (t.verdict, t.wer) == ("good", None)  # no text to match
    (record,) = studio.manifest(db_session)
    assert (record["text"], record["phonemes"], record["requested_style"]) == (long, None, None)
    said = {u.value: u.count for u in coverage.coverage(db_session).groups[0].units}
    assert said["w"] >= 2  # "Well", "walk": coverage counts what was said


def test_a_take_is_written_as_a_wav_master_and_described(db_session: Session, consented: None):
    prompt = studio.prompts(db_session)[3]
    data = sine_wav(1.25, rate=44_100)
    take = studio.add_take(db_session, prompt.id, data, device="  " + "m" * 300)
    assert (take.prompt_id, take.prompt_text, take.kind) == (prompt.id, prompt.text, prompt.kind)
    assert (take.seconds, take.sample_rate, take.sample_width, take.size_bytes) == (1.25, 44_100, 2, len(data))
    assert take.device == "m" * 200
    assert take.created.tzinfo is not None
    path = studio.take_file(db_session, take.id)
    assert path == os.path.join(settings.recordings_dir(), "human", f"take_{take.id:06d}.wav")
    with open(path, "rb") as f:
        assert f.read() == data
    assert studio.add_take(db_session, prompt.id, data, device="   ").device is None


def test_nothing_is_kept_without_consent_or_for_a_bad_file(db_session: Session):
    prompt = studio.prompts(db_session)[0]
    with pytest.raises(studio.NotConsented, match="Agree to be recorded first"):
        studio.add_take(db_session, prompt.id, sine_wav(1.0))
    settings.SETTINGS.save({"consented_on": "2026-11-23"})
    with pytest.raises(ValueError, match="mono"):
        studio.add_take(db_session, prompt.id, sine_wav(1.0, channels=2))
    with pytest.raises(KeyError, match=r"There is no prompt 999\."):
        studio.add_take(db_session, 999, sine_wav(1.0))
    with pytest.raises(KeyError, match=r"There is no prompt 999\."):
        studio.skip(db_session, 999)
    assert studio.progress(db_session).takes == 0
    assert not os.path.exists(os.path.join(settings.recordings_dir(), "human"))


def test_a_failed_write_keeps_neither_row_nor_file(db_session: Session, consented: None, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf8")
    settings.SETTINGS.save({"recordings_dir": str(blocker)})  # a file where the folder should be: makedirs fails
    prompt = studio.prompts(db_session)[0]
    with pytest.raises(OSError, match="not-a-folder"):
        studio.add_take(db_session, prompt.id, sine_wav(1.0))
    assert studio.progress(db_session).takes == 0


def test_takes_are_paged_newest_first_and_removed_with_their_files(db_session: Session, consented: None):
    ids = [p.id for p in studio.prompts(db_session)[:3]]
    made = [studio.add_take(db_session, i, sine_wav(0.5)).id for i in ids]
    page = studio.takes_page(db_session, limit=2)
    assert ([t.id for t in page.items], page.next) == ([made[2], made[1]], str(made[1]))
    rest = studio.takes_page(db_session, after=int(page.next or 0), limit=2)
    assert ([t.id for t in rest.items], rest.next) == ([made[0]], None)

    path = studio.take_file(db_session, made[1])
    assert studio.remove_take(db_session, made[1]).id == made[1]
    assert not os.path.exists(path)
    with pytest.raises(KeyError, match=f"There is no take {made[1]}."):
        studio.take_file(db_session, made[1])
    with pytest.raises(KeyError, match=f"There is no take {made[1]}."):
        studio.remove_take(db_session, made[1])

    os.remove(studio.take_file(db_session, made[0]))  # gone from the folder by hand
    with pytest.raises(KeyError, match="missing from the recordings folder"):
        studio.take_file(db_session, made[0])
    assert studio.remove_take(db_session, made[0]).id == made[0]  # the row can still be removed


def test_the_manifest_has_one_record_per_prompt_its_newest_take(db_session: Session, consented: None):
    listed = studio.prompts(db_session)
    first, phon = listed[0], listed[3]
    expr = next(p for p in listed if p.kind == "expressive")
    studio.add_take(db_session, phon.id, sine_wav(0.5))
    newest = sine_wav(1.0, hz=330)
    retry = studio.add_take(db_session, phon.id, newest, device="Desk mic")
    studio.add_take(db_session, expr.id, sine_wav(0.5))
    studio.add_take(db_session, first.id, sine_wav(0.5))

    records = list(studio.manifest(db_session))
    assert [r["prompt"]["key"] for r in records] == [first.key, phon.key, expr.key]  # queue order
    _, phon_rec, expr_rec = records
    assert phon_rec == {
        "id": f"take_{retry.id:06d}",
        "source": "human",
        "audio_uri": f"human/take_{retry.id:06d}.wav",
        "sha256": hashlib.sha256(newest).hexdigest(),
        "text": phon.text,
        "prompt": {"key": phon.key, "text": phon.text, "kind": "phonetic", "source": "starter", "writer": None},
        "locale": "en-GB",
        "phonemes": phonemes.ipa(phon.text),  # espeak's en-GB IPA, kept on the prompt
        "requested_style": {"vocabulary": studio.STYLE_VOCABULARY, "category": "neutral", "label": None},
        "observed_style": {"review_status": "unverified"},
        "elicitation": {"mode": "plain_text", "demonstration_heard": False},
        "audio": {"sample_rate": 16_000, "sample_width": 2, "seconds": 1.0},
        "speech": None,  # not scored: no crop yet
        "device": "Desk mic",
        "recorded": retry.created.isoformat(),
        "asr": None,
        "quality": {
            "verdict": None,
            "problems": [],
            "accepted": False,
            "asr_wer": None,
            "clipping": None,
            "noise_ok": None,
            "peak_db": None,
            "noise_db": None,
            "speech_db": None,
        },
        "partition": "train",
    }
    assert (expr_rec["requested_style"]["category"], expr_rec["requested_style"]["label"]) == ("excited", expr.cue)
    assert expr_rec["elicitation"]["mode"] == "written_label"
    assert json.loads(studio.manifest_line(phon_rec)) == phon_rec
    assert studio.manifest_line(phon_rec).endswith("}\n")


def test_takes_stay_reachable_after_the_recordings_folder_changes(db_session: Session, consented: None, tmp_path: Path):
    first = studio.prompts(db_session)[3]
    old = studio.add_take(db_session, first.id, sine_wav(0.5))
    old_path = studio.take_file(db_session, old.id)
    settings.SETTINGS.save({"recordings_dir": str(tmp_path / "elsewhere")})  # as Settings does
    assert studio.take_file(db_session, old.id) == old_path  # still played back from where it was written
    (record,) = studio.manifest(db_session)
    assert record["audio_uri"] == old_path  # absolute: it is not under the folder the manifest is relative to
    new = studio.add_take(db_session, studio.prompts(db_session)[4].id, sine_wav(0.5))
    assert studio.take_file(db_session, new.id).startswith(str(tmp_path / "elsewhere"))
    studio.remove_take(db_session, old.id)
    assert not os.path.exists(old_path)


def test_a_file_that_cannot_be_removed_keeps_its_take(
    db_session: Session, consented: None, monkeypatch: pytest.MonkeyPatch
):
    take = studio.add_take(db_session, studio.prompts(db_session)[3].id, sine_wav(0.5))

    def refuse(path: str) -> None:  # a read-only folder; running as root ignores a chmod, so the refusal is stood in
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(os, "remove", refuse)
    with pytest.raises(PermissionError):
        studio.remove_take(db_session, take.id)
    monkeypatch.undo()
    assert os.path.isfile(studio.take_file(db_session, take.id))  # still listed, so Remove can be tried again
    assert studio.remove_take(db_session, take.id).id == take.id


def test_the_queue_is_paged_by_a_cursor_that_survives_takes_leaving_it(db_session: Session, consented: None):
    first = studio.queue_page(db_session, limit=3)
    assert [p.key for p in first.items] == [s.key for s in curriculum.STARTER[:3]]
    assert first.next is not None
    studio.add_take(db_session, first.items[0].id, sine_wav(1.0))  # the front leaves: the next page is not shifted
    second = studio.queue_page(db_session, after=first.next, limit=3)
    assert [p.key for p in second.items] == [s.key for s in curriculum.STARTER[3:6]]
    rest = studio.queue_page(db_session, after=second.next, limit=200)
    assert rest.next is None
    assert len(first.items) + len(second.items) + len(rest.items) == len(curriculum.STARTER)
    with pytest.raises(ValueError, match="not a place in the queue"):
        studio.queue_page(db_session, after="soon")
