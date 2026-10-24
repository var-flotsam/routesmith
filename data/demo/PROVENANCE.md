# Demo dataset provenance

`stops.csv` holds 754 residential address points in Byram, Greenwich,
Connecticut. It is the only address data in this repository.

## Source

| | |
| --- | --- |
| Dataset | Connecticut 9-1-1 Address Points |
| Publisher | CT Department of Emergency Services and Public Protection, Division of Statewide Emergency Telecommunications |
| Dataset page | https://data.ct.gov/Public-Safety/Connecticut-9-1-1-Address-Points/m6xx-nb28 |
| File | `CT911_CTData.gdb.zip`, 86,415,864 bytes, SHA-256 `fdb505bc1ddab6e5bd1e7ef78a48aa34e987ecc24a30f1daece92cb57f1545de` |
| Download URL | https://data.ct.gov/api/views/m6xx-nb28/files/35ec5873-bc1d-4f36-a0a1-07b44f28bc3d?filename=CT911_CTData.gdb.zip |
| Downloaded | 2026-10-24 |
| Latest `DateUpdated` in the file | 2026-05-26 |
| Licence | Public Domain, as stated on the dataset page (licence id `PUBLIC_DOMAIN` in https://data.ct.gov/api/views/m6xx-nb28.json); no attribution required |

This is the source OpenAddresses lists for Connecticut:
[`sources/us/ct/statewide.json`](https://github.com/openaddresses/openaddresses/blob/master/sources/us/ct/statewide.json)
in the OpenAddresses source catalogue, which records the same file, URL and
Public Domain licence. The file was taken directly from the publisher because
OpenAddresses' processed downloads require an account.

## How `stops.csv` was made

`scripts/build_demo_dataset.py` (run as its docstring shows) does this:

1. Keeps points whose `Inc_Muni` is `Greenwich` and that fall inside the box
   west -73.66343, south 40.99475, east -73.64557, north 41.00825 (a 1.5 km
   square centred on Byram, WGS 84).
2. Drops rows with a `Unit`, so each address is one stop.
3. Builds the street name from the directional, type and name fields,
   removing the parenthesised community tags some names carry.
4. Keeps one point per house number and street, rounded to 6 decimal places.
5. Sorts by street name, then house number, and numbers the stops in that
   order. This `current_sequence` is synthetic: it imitates how route sheets
   are commonly ordered and does not describe any real collection route.

## Columns

| Column | Meaning |
| --- | --- |
| `stop_id` | `demo-NNNN`, stable for this file |
| `current_sequence` | synthetic current order, 1 to 754 |
| `house_number` | house number with any suffix |
| `street` | street name as built in step 3 |
| `lon`, `lat` | WGS 84 degrees |
