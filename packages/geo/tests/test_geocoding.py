"""The Census batch geocoder: answers read correctly, batched, cached, never raising."""

from starboard.geo.geocoding import (
    CENSUS_BATCH_URL,
    Address,
    CensusGeocoder,
    GeocodeQuality,
    geocode_all,
)

# The service's answer layout: id, input, status, exactness, matched address, "lon,lat", ...
ANSWER = "\n".join(
    [
        '"0","1 Main St, Town, CT, 06830","Match","Exact",'
        '"1 MAIN ST, TOWN, CT, 06830","-73.6,41.0","1","L"',
        '"1","2 Elm St, Town, CT","Match","Non_Exact",'
        '"2 ELM ST, TOWN, CT, 06830","-73.5,41.1","2","R"',
        '"2","3 Oak St, Town, CT","Tie"',
        '"3","nowhere","No_Match"',
    ]
)


class Recorder:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.batches: list[bytes] = []

    def __call__(self, url: str, batch: bytes) -> str:
        assert url == CENSUS_BATCH_URL
        self.batches.append(batch)
        return self.answer


ADDRESSES = [
    Address("1 Main St", "Town", "CT", "06830"),
    Address("2 Elm St", "Town", "CT"),
    Address("3 Oak St", "Town", "CT"),
    Address("nowhere"),
]


def test_each_answer_is_read_and_in_input_order(tmp_path):
    post = Recorder(ANSWER)
    outcomes = CensusGeocoder(tmp_path, post).geocode(ADDRESSES)
    assert [o.quality for o in outcomes] == [
        GeocodeQuality.EXACT,
        GeocodeQuality.INEXACT,
        GeocodeQuality.AMBIGUOUS,
        GeocodeQuality.NOT_FOUND,
    ]
    assert (outcomes[0].location.lon, outcomes[0].location.lat) == (-73.6, 41.0)
    assert outcomes[1].matched_address == "2 ELM ST, TOWN, CT, 06830"
    assert len(post.batches) == 1
    assert b"1 Main St,Town,CT,06830" in post.batches[0]


def test_answers_are_cached_so_an_address_is_asked_for_once(tmp_path):
    post = Recorder(ANSWER)
    CensusGeocoder(tmp_path, post).geocode(ADDRESSES)
    again = CensusGeocoder(tmp_path, Recorder("")).geocode(ADDRESSES[:2])
    assert [o.quality for o in again] == [GeocodeQuality.EXACT, GeocodeQuality.INEXACT]


def test_an_address_the_answer_leaves_out_is_not_found_and_asked_again(tmp_path):
    post = Recorder("")
    (outcome,) = CensusGeocoder(tmp_path, post).geocode([Address("1 Main St")])
    assert outcome.quality is GeocodeQuality.NOT_FOUND
    CensusGeocoder(tmp_path, post).geocode([Address("1 Main St")])
    assert len(post.batches) == 2


def test_geocode_all_sorts_stops_into_placed_inexact_and_unplaced(tmp_path):
    geocoder = CensusGeocoder(tmp_path, Recorder(ANSWER))
    result = geocode_all(geocoder, [(f"s{k}", a) for k, a in enumerate(ADDRESSES)])
    assert set(result.points) == {"s0", "s1"}
    assert result.inexact == {"s1"}
    assert result.unplaced == {"s2": GeocodeQuality.AMBIGUOUS, "s3": GeocodeQuality.NOT_FOUND}
