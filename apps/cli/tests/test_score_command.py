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
        cli, "fetch_network", lambda bbox, cache_dir: build_state_graph(GRID.segments())
    )
    assert cli.main(["score", str(stops_csv(tmp_path)), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    card = report["scorecard"]
    assert card["stops_serviced"] == 4
    assert card["stops_unreachable"] == 0
    assert report["rejected_rows"] == 1
    assert math.isfinite(card["drive_time_s"]) and card["drive_time_s"] > 0


def test_score_reports_a_network_failure_without_a_traceback(tmp_path, monkeypatch, capsys):
    def unreachable(bbox, cache_dir):
        raise requests.ConnectTimeout("timed out")

    monkeypatch.setattr(cli, "fetch_network", unreachable)
    assert cli.main(["score", str(stops_csv(tmp_path))]) == 2
    assert "could not fetch the OSM street network" in capsys.readouterr().err
