# Clean-room statement

Project start date: 2026-10-24.

Starboard Routing is independent original work. It is built by its owner on
the owner's own equipment and in the owner's own time, from public sources
only: published papers and textbooks on arc routing, public documentation of
the open-source libraries it uses, and the public data sources listed below.

## Data sources

| Source | Used for | Licence |
| --- | --- | --- |
| [OpenStreetMap](https://www.openstreetmap.org/) via [OSMnx](https://osmnx.readthedocs.io/) | Street network, one-way and turn restrictions, speed limits | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/) |
| [OpenAddresses](https://openaddresses.io/) | Address points for the public demo dataset in `data/demo/` | Per source; recorded in `data/demo/PROVENANCE.md` |
| [Nominatim](https://nominatim.org/) | Geocoding uploaded addresses | Software GPL-2.0, run as a separate service; results are OSM data under ODbL |
| Published transportation agency tables (cited where used) | Default turn delays and speeds in `packages/solver/defaults.py` | Public documents, cited by link |

No other data is used. Customer data is never committed to this repository.
