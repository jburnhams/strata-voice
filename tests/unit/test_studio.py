import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from strata_python.testing import sine_wav

from stratavoice import curriculum, settings, studio


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
    assert second.key == "spont-02"
    assert studio.skip(db_session, second.id).skipped
    third = studio.next_prompt(db_session)
    assert third is not None
    assert third.key == "spont-03"
    assert not studio.skip(db_session, second.id, skipped=False).skipped
    back = studio.next_prompt(db_session)
    assert back is not None
    assert back.key == "spont-02"  # put back: in its place again

    studio.add_take(db_session, first.queue[0].id, sine_wav(2.0))  # a retry: another take of the same prompt
    p = studio.progress(db_session)
    assert (p.recorded, p.skipped, p.takes, p.seconds) == (1, 0, 2, 3.0)


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
    spont, phon = listed[0], listed[3]
    expr = next(p for p in listed if p.kind == "expressive")
    studio.add_take(db_session, phon.id, sine_wav(0.5))
    newest = sine_wav(1.0, hz=330)
    retry = studio.add_take(db_session, phon.id, newest, device="Desk mic")
    studio.add_take(db_session, expr.id, sine_wav(0.5))
    studio.add_take(db_session, spont.id, sine_wav(0.5))

    records = list(studio.manifest(db_session))
    assert [r["prompt"]["key"] for r in records] == [spont.key, phon.key, expr.key]  # queue order
    spont_rec, phon_rec, expr_rec = records
    assert spont_rec["text"] is None  # nothing fixed to say: no transcript to hold it to
    assert phon_rec == {
        "id": f"take_{retry.id:06d}",
        "source": "human",
        "audio_uri": f"human/take_{retry.id:06d}.wav",
        "sha256": hashlib.sha256(newest).hexdigest(),
        "text": phon.text,
        "prompt": {"key": phon.key, "text": phon.text, "kind": "phonetic", "source": "starter"},
        "locale": "en-GB",
        "requested_style": None,
        "observed_style": {"review_status": "unverified"},
        "elicitation": {"mode": "plain_text", "demonstration_heard": False},
        "audio": {"sample_rate": 16_000, "sample_width": 2, "seconds": 1.0},
        "device": "Desk mic",
        "recorded": retry.created.isoformat(),
        "quality": {"asr_wer": None, "clipping": None, "noise_ok": None},
        "partition": "train",
    }
    assert (expr_rec["requested_style"], expr_rec["elicitation"]["mode"]) == ({"label": expr.cue}, "written_label")
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
