from stratavoice import curriculum


def test_the_starter_curriculum_is_balanced_and_its_keys_are_stable_and_unique():
    keys = [s.key for s in curriculum.STARTER]
    assert len(keys) == len(set(keys))
    assert {s.kind for s in curriculum.STARTER} == set(curriculum.KINDS)
    # The groups come in the order they are asked for: the speaker's own voice first, the held-out set last.
    assert [s.kind for s in curriculum.STARTER] == sorted(
        (s.kind for s in curriculum.STARTER), key=curriculum.KINDS.index
    )
    assert {s.partition for s in curriculum.STARTER if s.kind == "evaluation"} == {"eval"}
    assert {s.partition for s in curriculum.STARTER if s.kind != "evaluation"} == {"train"}
    assert all(s.cue for s in curriculum.EXPRESSIVE)  # an expressive prompt always says how
    assert all(len(s.text) <= 600 and len(s.cue or "") <= 200 and len(s.key) <= 60 for s in curriculum.STARTER)
