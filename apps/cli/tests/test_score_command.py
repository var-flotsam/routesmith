import json
import math

import requests

from starboard.cli import main as cli
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid

GRID = Grid()


def stops_csv(tmp_path):
    rows = ["stop_id,current_sequence,street,lon,lat"]
    for index, (x, y) in enumerate([(20, -10), (60, -10), (110, 50), (150, 90)], start=1):
        point = GRID.at(x, y)
        rows.append(f"s{index},{index},,{point.lon},{point.lat}")
    rows.append("bad,5,,not-a-number,41")
    path = tmp_path / "stops.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_score_prints_the_scorecard_as_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "fetch_network", lambda bbox, cache_dir, extract: build_state_graph(GRID.segments())
    )
    assert cli.main(["score", str(stops_csv(tmp_path)), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    card = report["scorecard"]
    assert card["stops_serviced"] == 4
    assert card["stops_unreachable"] == 0
    assert report["rejected_rows"] == 1
    assert math.isfinite(card["drive_time_s"]) and card["drive_time_s"] > 0


def test_score_reports_a_network_failure_without_a_traceback(tmp_path, monkeypatch, capsys):
    def unreachable(bbox, cache_dir, extract):
        raise requests.ConnectTimeout("timed out")

    monkeypatch.setattr(cli, "fetch_network", unreachable)
    assert cli.main(["score", str(stops_csv(tmp_path))]) == 2
    assert "could not fetch the OSM street network" in capsys.readouterr().err


def test_optimize_compares_current_and_optimized(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "fetch_network", lambda bbox, cache_dir, extract: build_state_graph(GRID.segments())
    )
    yard, disposal = GRID.at(0, 0), GRID.at(300, 300)
    args = [
        "optimize",
        str(stops_csv(tmp_path)),
        f"--yard={yard.lon},{yard.lat}",  # "=" because a negative longitude looks like a flag
        f"--disposal={disposal.lon},{disposal.lat}",
        "--capacity",
        "2",
        "--json",
    ]
    assert cli.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["optimized"]["wrong_side_pickups"] == 0
    assert report["optimized"]["stops_serviced"] == report["current"]["stops_serviced"] == 4
    assert report["optimized"]["disposal_visits"] >= 2
    assert sorted(report["optimized_order"]) == ["s1", "s2", "s3", "s4"]


def test_optimize_needs_both_sites(tmp_path, capsys):
    assert cli.main(["optimize", str(stops_csv(tmp_path))]) == 1
    assert "needs a yard and a disposal site" in capsys.readouterr().err


def test_a_route_file_supplies_the_sites_and_truck(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "fetch_network", lambda bbox, cache_dir, extract: build_state_graph(GRID.segments())
    )
    yard = GRID.at(0, 0)
    route = tmp_path / "route.json"
    route.write_text(
        json.dumps(
            {
                "yard": {"lon": yard.lon, "lat": yard.lat},
                "disposal": {"lon": yard.lon, "lat": yard.lat},
                "capacity_carts": 2,
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["optimize", str(stops_csv(tmp_path)), "--route", str(route), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["optimized"]["disposal_visits"] >= 2


def test_optimize_with_two_trucks_reports_two_routes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "fetch_network", lambda bbox, cache_dir, extract: build_state_graph(GRID.segments())
    )
    yard = GRID.at(0, 0)
    args = [
        "optimize",
        str(stops_csv(tmp_path)),
        f"--yard={yard.lon},{yard.lat}",
        f"--disposal={yard.lon},{yard.lat}",
        "--trucks",
        "2",
        "--json",
    ]
    assert cli.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["routes"]) == 2
    assert sum(r["stops_serviced"] for r in report["routes"]) == 4
    assert report["area"]["objective"] == "balanced-total"
