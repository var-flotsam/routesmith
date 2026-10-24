"""Build data/demo/stops.csv from the Connecticut 9-1-1 address points.

Run from the repository root, with the extracted state file:

    uv run --with pyogrio==0.11.1 python scripts/build_demo_dataset.py CT911_CTData.gdb

It keeps Greenwich address points inside the demo bounding box, drops unit
rows so each address is one stop, and numbers the stops in a synthetic
current order: by street name, then house number, as route sheets are
commonly sorted. The output is deterministic for a given input file.
"""

import argparse
import csv
import math
import re
from pathlib import Path

import pyogrio

# Byram, Greenwich, CT: a 1.5 km square centred on (-73.6545, 41.0015).
DEMO_BBOX = (-73.66343, 40.99475, -73.64557, 41.00825)  # west, south, east, north
MUNICIPALITY = "Greenwich"
OUTPUT = Path("data/demo/stops.csv")

_PART_FIELDS = ("St_PreDir", "St_PreTyp", "St_Name", "St_PosTyp", "St_PosDir")
_DISAMBIGUATION = re.compile(r"\s*\([^)]*\)\s*")


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def street_name(row: dict[str, object]) -> str:
    parts = (_DISAMBIGUATION.sub(" ", _clean(row[field])).strip() for field in _PART_FIELDS)
    return " ".join(part for part in parts if part)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gdb", type=Path, help="path to the extracted CT911_CTData.gdb")
    args = parser.parse_args()

    # The filter field must be among the columns read, or the filter matches nothing.
    columns = ["Inc_Muni", *_PART_FIELDS, "Add_Number", "AddNum_Suf", "Unit"]
    frame = pyogrio.read_dataframe(
        args.gdb, where=f"Inc_Muni = '{MUNICIPALITY}'", columns=columns
    ).to_crs(4326)
    west, south, east, north = DEMO_BBOX
    frame["lon"] = frame.geometry.x
    frame["lat"] = frame.geometry.y
    frame = frame[
        frame["lon"].between(west, east) & frame["lat"].between(south, north) & frame["Unit"].isna()
    ]

    stops: dict[tuple[str, int, str], tuple[float, float]] = {}
    for row in frame.to_dict("records"):
        key = (street_name(row), int(row["Add_Number"]), _clean(row["AddNum_Suf"]))
        location = (round(float(row["lon"]), 6), round(float(row["lat"]), 6))
        stops[key] = min(stops.get(key, location), location)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["stop_id", "current_sequence", "house_number", "street", "lon", "lat"])
        for sequence, (street, number, suffix) in enumerate(sorted(stops), start=1):
            lon, lat = stops[(street, number, suffix)]
            writer.writerow(
                [f"demo-{sequence:04d}", sequence, f"{number}{suffix}", street, lon, lat]
            )
    print(f"wrote {len(stops)} stops to {OUTPUT}")


if __name__ == "__main__":
    main()
