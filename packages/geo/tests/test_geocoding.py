"""The Census geocoder: batch answers read, batched, cached, never raising; one-line search."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from starboard.geo.geocoding import (
    CENSUS_BATCH_URL,
    CENSUS_ONELINE_MAX_CHARACTERS,
    CENSUS_ONELINE_URL,
    Address,
    CensusGeocoder,
    FoundPlace,
    GeocodeQuality,
    GeocoderUnavailableError,
    geocode_all,
)
from starboard.solver.graph import LonLat

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


# The one-line search's answer layout, cut to the fields read here.
ONE_LINE_ANSWER = json.dumps(
    {
        "result": {
            "input": {"address": {"address": "1 Main St, Town, CT"}},
            "addressMatches": [
                {
                    "matchedAddress": "1 MAIN ST, TOWN, CT, 06830",
                    "coordinates": {"x": -73.6, "y": 41.0},
                },
                {
                    "matchedAddress": "1 MAIN ST, TOWN, CT, 06831",
                    "coordinates": {"x": -73.5, "y": 41.1},
                },
            ],
        }
    }
)


class OneLineRecorder:
    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.queries: list[dict[str, str]] = []

    def __call__(self, url: str, params: dict[str, str]) -> str:
        assert url == CENSUS_ONELINE_URL
        self.queries.append(params)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_a_one_line_address_lists_every_place_it_could_be(tmp_path):
    get = OneLineRecorder(ONE_LINE_ANSWER)
    places = CensusGeocoder(tmp_path, get=get).find("  1 Main St,   Town, CT ")
    assert places == [
        FoundPlace("1 MAIN ST, TOWN, CT, 06830", LonLat(lon=-73.6, lat=41.0)),
        FoundPlace("1 MAIN ST, TOWN, CT, 06831", LonLat(lon=-73.5, lat=41.1)),
    ]
    assert get.queries[0]["address"] == "1 Main St, Town, CT"


def test_a_one_line_answer_is_cached_whatever_its_spacing_or_case(tmp_path):
    CensusGeocoder(tmp_path, get=OneLineRecorder(ONE_LINE_ANSWER)).find("1 Main St, Town, CT")
    unused = OneLineRecorder(RuntimeError("asked again"))
    again = CensusGeocoder(tmp_path, get=unused).find("1 MAIN ST,  town, ct")
    assert len(again) == 2 and unused.queries == []


def test_an_address_that_names_no_place_finds_none(tmp_path):
    answer = json.dumps({"result": {"addressMatches": []}})
    assert CensusGeocoder(tmp_path, get=OneLineRecorder(answer)).find("nowhere") == []


@pytest.mark.parametrize(
    "answer", [requests.ConnectionError("offline"), "<html>busy</html>", '{"errors": ["?"]}']
)
def test_no_answer_or_an_unreadable_one_is_the_geocoder_unavailable(tmp_path, answer):
    with pytest.raises(GeocoderUnavailableError):
        CensusGeocoder(tmp_path, get=OneLineRecorder(answer)).find("1 Main St")
    assert not any(tmp_path.rglob("*.json"))  # nothing cached, so it is asked again


def test_an_address_longer_than_the_service_takes_finds_none_without_asking(tmp_path):
    get = OneLineRecorder(RuntimeError("asked"))
    address = "1 Main St, " + "x" * CENSUS_ONELINE_MAX_CHARACTERS
    assert CensusGeocoder(tmp_path, get=get).find(address) == []
    assert get.queries == []


def test_an_address_the_service_refuses_finds_none_and_is_asked_again(tmp_path):
    refused = requests.Response()
    refused.status_code = 400
    get = OneLineRecorder(requests.HTTPError(response=refused))
    assert CensusGeocoder(tmp_path, get=get).find("1 Main St") == []
    assert not any(tmp_path.rglob("*.json"))


def test_a_damaged_cache_file_is_asked_again(tmp_path):
    CensusGeocoder(tmp_path, get=OneLineRecorder(ONE_LINE_ANSWER)).find("1 Main St")
    (cached,) = tmp_path.rglob("*.json")
    cached.write_text("", encoding="utf-8")  # as a write cut short would leave it
    get = OneLineRecorder(ONE_LINE_ANSWER)
    assert len(CensusGeocoder(tmp_path, get=get).find("1 Main St")) == 2
    assert len(get.queries) == 1


def test_lookups_of_one_address_at_once_each_get_the_answer(tmp_path):
    def slow(url, params):
        time.sleep(0.01)
        return ONE_LINE_ANSWER

    geocoder = CensusGeocoder(tmp_path, get=slow)
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        with ThreadPoolExecutor(8) as pool:
            answers = list(pool.map(lambda _: geocoder.find("1 Main St"), range(32)))
    finally:
        sys.setswitchinterval(interval)
    assert all(len(places) == 2 for places in answers)
    assert not any(tmp_path.rglob("*.tmp"))
