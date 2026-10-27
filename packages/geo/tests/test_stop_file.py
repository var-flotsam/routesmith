from pathlib import Path

from starboard.geo.stop_file import (
    MAX_ROUTE_ID_LENGTH,
    MAX_STOP_ID_LENGTH,
    MAX_STREET_LENGTH,
    read_stop_file,
    read_stop_rows,
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "stops.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_stops_come_back_in_current_sequence_order(tmp_path):
    path = write(
        tmp_path,
        "stop_id,current_sequence,street,lon,lat\nb,2,Elm St,-73.0,41.0\na,1,,-73.1,41.1\n",
    )
    stop_file = read_stop_file(path)
    assert [s.stop_id for s in stop_file.stops] == ["a", "b"]
    assert stop_file.stops[0].street is None
    assert stop_file.stops[1].street == "Elm St"
    assert stop_file.rejected == ()


def test_bad_rows_are_rejected_with_a_reason_not_raised(tmp_path):
    path = write(
        tmp_path,
        "stop_id,current_sequence,lon,lat\n"
        "a,1,-73.0,41.0\n"
        ",2,-73.0,41.0\n"
        "c,three,-73.0,41.0\n"
        "d,4,-200,41.0\n"
        "a,5,-73.0,41.0\n",
    )
    stop_file = read_stop_file(path)
    assert [s.stop_id for s in stop_file.stops] == ["a"]
    assert [(r.line_number, r.reason) for r in stop_file.rejected] == [
        (3, "no stop_id"),
        (4, "current_sequence, lon or lat is not a number"),
        (5, "lon or lat is out of range"),
        (6, "duplicate stop_id a"),
    ]


def test_a_damaged_or_oversized_row_is_rejected_and_the_rest_are_read():
    nul = chr(0)
    lines = [
        "stop_id,current_sequence,street,route_id,lon,lat",
        f"a{nul}b,1,,A,-73.0,41.0",
        f"c,2,Elm St,A,-73.0,41.0,{nul}",  # in a cell past the header's columns
        '"' + "x" * 200_000 + '",3,,A,-73.0,41.0',  # over the csv module's limit
        "s" * (MAX_STOP_ID_LENGTH + 1) + ",4,,A,-73.0,41.0",
        "e,5,," + "r" * (MAX_ROUTE_ID_LENGTH + 1) + ",-73.0,41.0",
        "f,6," + "m" * (MAX_STREET_LENGTH + 1) + ",A,-73.0,41.0",
        "g,7,Elm St,A,-73.0,41.0",
    ]
    stop_file = read_stop_rows(lines)
    assert [s.stop_id for s in stop_file.stops] == ["g"]
    reasons = [(r.line_number, r.reason) for r in stop_file.rejected]
    assert reasons[:2] == [(2, "holds a NUL character"), (3, "holds a NUL character")]
    assert reasons[2][0] == 4 and reasons[2][1].startswith("unreadable: ")
    assert reasons[3:] == [
        (5, f"stop_id is longer than {MAX_STOP_ID_LENGTH} characters"),
        (6, f"route_id is longer than {MAX_ROUTE_ID_LENGTH} characters"),
        (7, f"street is longer than {MAX_STREET_LENGTH} characters"),
    ]


def test_missing_columns_are_one_rejected_row(tmp_path):
    stop_file = read_stop_file(write(tmp_path, "id,lon,lat\n1,-73,41\n"))
    assert stop_file.stops == ()
    assert stop_file.rejected[0].reason == "missing columns: stop_id, current_sequence"


def test_the_demo_file_reads_cleanly():
    demo = Path(__file__).resolve().parents[3] / "data" / "demo" / "stops.csv"
    stop_file = read_stop_file(demo)
    assert len(stop_file.stops) == 754
    assert stop_file.rejected == ()


def test_a_route_id_column_names_each_stops_route(tmp_path):
    path = write(
        tmp_path,
        "stop_id,route_id,current_sequence,lon,lat\n"
        "a,R1,1,-73.0,41.0\n"
        "b,R2,1,-73.0,41.0\n"
        "c,,2,-73.0,41.0\n",
    )
    stop_file = read_stop_file(path)
    assert stop_file.route_of == {"a": "R1", "b": "R2"}
    assert [r.reason for r in stop_file.rejected] == ["no route_id"]


def test_without_a_route_id_column_no_routes_are_named(tmp_path):
    path = write(tmp_path, "stop_id,current_sequence,lon,lat\na,1,-73.0,41.0\n")
    assert read_stop_file(path).route_of == {}


def test_rows_read_from_text_lines_match_a_file(tmp_path):
    text = "stop_id,current_sequence,lon,lat\nb,2,-73.0,41.0\na,1,-73.1,41.1\n"
    from_text = read_stop_rows(text.splitlines(keepends=True))
    assert from_text == read_stop_file(write(tmp_path, text))


def test_a_row_with_only_an_address_waits_for_the_geocoder(tmp_path):
    path = write(
        tmp_path,
        "stop_id,current_sequence,house_number,street,city,state,zip,lon,lat\n"
        "b,2,12,Elm St,Town,CT,06830,,\n"
        "a,1,1,Main St,Town,CT,06830,-73.0,41.0\n"
        "c,3,,,,,,,\n",
    )
    stop_file = read_stop_file(path)
    assert [s.stop_id for s in stop_file.stops] == ["a"]
    (unlocated,) = stop_file.unlocated
    assert unlocated.stop_id == "b"
    assert unlocated.address.one_line() == "12 Elm St, Town, CT, 06830"
    assert stop_file.order == ("a", "b")
    assert [r.reason for r in stop_file.rejected] == ["no lon/lat and no address"]


def test_an_address_column_is_enough_to_place_stops(tmp_path):
    stop_file = read_stop_file(write(tmp_path, "stop_id,current_sequence,address\na,1,1 Main St\n"))
    assert stop_file.rejected == ()
    assert stop_file.unlocated[0].address.street == "1 Main St"
