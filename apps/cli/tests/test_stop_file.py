from pathlib import Path

from starboard.cli.stop_file import read_stop_file


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
