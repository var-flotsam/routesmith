"""CSV, GPX, KML and PDF exports, compared byte for byte with snapshots in tests/snapshots/.

Run with UPDATE_SNAPSHOTS=1 to write new snapshots after an intended change.
"""

import dataclasses
import importlib.util
import io
import itertools
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from starboard.export.files import routes_gpx, routes_kml, stops_csv
from starboard.export.model import RunExport, Step
from starboard.export.route_sheet import distance, duration, instruction, route_sheet_pdf

SNAPSHOTS = Path(__file__).parent / "snapshots"


def _sample():
    spec = importlib.util.spec_from_file_location("sample", Path(__file__).parent / "sample.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RUN


@pytest.mark.parametrize(
    ("make", "name"),
    [(stops_csv, "stops.csv"), (routes_gpx, "routes.gpx"), (routes_kml, "routes.kml")],
)
def test_the_export_matches_its_snapshot_byte_for_byte(make, name):
    data = make(_sample())
    snapshot = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        snapshot.write_bytes(data)
    assert data == snapshot.read_bytes()
    assert make(_sample()) == data  # the same run, the same bytes


def test_the_csv_lists_stops_in_each_routes_collection_order():
    rows = stops_csv(_sample()).decode().splitlines()
    assert rows[0] == "route,sequence,stop_id,street,lon,lat,current_route,current_sequence"
    assert [r.split(",")[:3] for r in rows[1:]] == [
        ["1", "1", "s2"],
        ["1", "2", "s1"],
        ["2", "1", "s3"],
        ["2", "2", "s9"],
    ]


def test_names_are_escaped_in_xml():
    gpx = routes_gpx(_sample()).decode()
    assert "Byram &amp; Mill, route 1" in gpx
    assert "<" not in gpx.split("<name>")[1].split("</name>")[0]


def test_the_route_sheet_pdf_matches_its_snapshot_byte_for_byte():
    data = route_sheet_pdf(_sample())
    assert data.startswith(b"%PDF")
    snapshot = SNAPSHOTS / "route_sheet.pdf"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        snapshot.write_bytes(data)
    assert data == snapshot.read_bytes()
    assert route_sheet_pdf(_sample()) == data


def test_each_step_reads_as_an_instruction():
    run = _sample()
    second = run.routes[1]
    assert [instruction(step) for step in second.steps] == [
        "Leave onto Byram Rd",
        "Turn left onto Ole's <Lane>",
        "Return to the yard",
    ]


def _pages(pdf: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages]


def test_street_names_print_as_named_even_with_markup_characters():
    pages = _pages(route_sheet_pdf(_sample()))
    assert "Byram & Mill: truck 1 of 2" in pages[0]
    assert "Turn left onto Ole's <Lane>" in pages[1]


def _with_second_route(**changes) -> RunExport:
    run = _sample()
    return dataclasses.replace(
        run, routes=(run.routes[0], dataclasses.replace(run.routes[1], **changes))
    )


def test_every_page_names_the_route_its_truck_and_its_number():
    steps = tuple(Step("right", f"Street {k}", 50.0, ()) for k in range(150))
    pages = _pages(route_sheet_pdf(_with_second_route(steps=steps)))
    assert len(pages) > 2
    assert "Byram & Mill" in pages[0] and "Truck 1 of 2, page 1" in pages[0]
    for number, text in enumerate(pages[1:], start=2):
        assert "Byram & Mill" in text and f"Truck 2 of 2, page {number}" in text


def test_a_page_the_steps_run_on_to_says_whose_it_is():
    steps = tuple(Step("right", f"Street {k}", 50.0, ()) for k in range(150))
    pages = _pages(route_sheet_pdf(_with_second_route(steps=steps)))
    assert "continued" not in pages[0] + pages[1]
    assert all("Truck 2 of 2, continued" in text for text in pages[2:])


def test_a_long_route_name_leaves_the_truck_and_page_on_the_page():
    run = dataclasses.replace(_sample(), route_name="North " * 40)
    footer = _pages(route_sheet_pdf(run))[0].splitlines()[-2:]
    assert footer[0].startswith("North North") and footer[0].endswith("…")
    assert footer[1] == "Truck 1 of 2, page 1"


def test_street_names_beyond_western_european_letters_print_as_named():
    steps = (Step("depart", "Kalākaua Ave", 120.0, ()), Step("left", "Łódź Rd", 80.0, ()))
    pages = _pages(route_sheet_pdf(_with_second_route(steps=steps)))
    assert "Leave onto Kalākaua Ave" in pages[1]
    assert "Turn left onto Łódź Rd" in pages[1]


def test_the_sheet_carries_its_own_fonts():
    pdf = route_sheet_pdf(_sample())
    fonts = set(re.findall(rb"/BaseFont\s*/([^\s/]+)", pdf))
    # A subset of each font, embedded: no font is left to the printer to stand in for.
    assert fonts == {b"AAAAAA+DejaVuSans", b"AAAAAA+DejaVuSans-Bold"}
    assert pdf.count(b"/FontFile2") == len(fonts)


def test_a_letter_the_font_lacks_never_stops_the_sheet():
    steps = (Step("depart", "中山路", 50.0, ()),)  # a street named in Chinese
    pages = _pages(route_sheet_pdf(_with_second_route(steps=steps)))
    assert len(pages) == 2 and "Leave onto" in pages[1]


def test_sheets_laid_out_at_the_same_time_are_each_whole():
    # The API lays sheets out in worker threads. A short switch interval makes threads
    # interleave far more often than they would by chance.
    run = _sample()
    expected = route_sheet_pdf(run)
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        with ThreadPoolExecutor(8) as pool:
            sheets = list(pool.map(lambda _: route_sheet_pdf(run), range(64)))
    finally:
        sys.setswitchinterval(interval)
    assert all(sheet == expected for sheet in sheets)


def _text_starts(pdf: bytes, page: int) -> dict[str, float]:
    """Where each piece of text on a page first starts, in points from its left edge."""
    starts: dict[str, float] = {}

    def visit(text, cm, tm, font, size):
        if text.strip():
            starts.setdefault(text.strip(), tm[4] * cm[0] + cm[4])

    PdfReader(io.BytesIO(pdf)).pages[page].extract_text(visitor_text=visit)
    return starts


def test_the_headings_and_a_four_digit_step_number_fit_their_columns():
    steps = tuple(Step("right", "Mill St", 50.0, ()) for _ in range(1000))
    pdf = route_sheet_pdf(_with_second_route(steps=steps))
    padding = 2 * 6  # ReportLab's default: 6 points inside each side of a cell
    heading = _text_starts(pdf, 1)
    for this, after in itertools.pairwise(["#", "Do this", "Distance", "Carts"]):
        assert heading[this] + stringWidth(this, "DejaVuSans-Bold", 13) <= heading[after] - padding
    last = _text_starts(pdf, len(_pages(pdf)) - 1)
    assert last["1000"] + stringWidth("1000", "DejaVuSans", 13) <= heading["Do this"] - padding


def test_long_stop_ids_print_shortened_and_never_stop_the_sheet():
    stop_ids = tuple(f"{k:02d}" + "W" * 98 for k in range(12))
    pages = _pages(
        route_sheet_pdf(_with_second_route(steps=(Step("depart", "Mill St", 9.0, stop_ids),)))
    )
    text = "".join(pages).replace("\n", "")  # a long id wraps inside its cell
    assert "00" + "W" * 21 + "…" in text
    assert "W" * 22 not in text


@pytest.mark.parametrize(
    ("metres", "shown"),
    [(40.0, "40 m"), (999.4, "999 m"), (1000.0, "1.0 km"), (12345.0, "12.3 km")],
)
def test_distances_read_in_metres_then_kilometres(metres, shown):
    assert distance(metres) == shown


@pytest.mark.parametrize(
    ("seconds", "shown"), [(1800.0, "30 min"), (3600.0, "1 h 00 min"), (27000.0, "7 h 30 min")]
)
def test_durations_read_in_hours_and_minutes(seconds, shown):
    assert duration(seconds) == shown
