from starboard.solver import defaults


def test_every_tunable_states_a_unit_and_a_reason() -> None:
    for name, tunable in defaults.all_tunables().items():
        assert tunable.unit.strip(), f"{name} has no unit"
        assert len(tunable.reason.strip()) >= 10, f"{name} has no reason"
        if tunable.source is not None:
            assert tunable.source.startswith("https://"), f"{name} source is not a link"
