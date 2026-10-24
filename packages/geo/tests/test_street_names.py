import pytest

from starboard.geo.street_names import normalized_street_name, same_street_name


@pytest.mark.parametrize(
    ("written", "spelled_out"),
    [
        ("Chestnut St W", "Chestnut Street West"),
        ("N. Water St.", "North Water Street"),
        ("Stormy Circle Dr", "Stormy Circle Drive"),
        ("Ocean View Ave", "ocean view avenue"),
    ],
)
def test_abbreviations_match_spelled_out_names(written, spelled_out):
    assert same_street_name(written, spelled_out)


def test_different_streets_do_not_match():
    assert not same_street_name("Mill St", "Mill Road")
    assert not same_street_name(None, "Mill Street")


def test_normalized_name_is_lower_case_words():
    assert normalized_street_name("  S New St ") == "south new street"
