"""Text the API takes in, and the characters it refuses in it.

Postgres cannot store the NUL character in text (https://www.postgresql.org/docs/current/
datatype-character.html), so no text that reaches a query holds one. A name or an email
address has no use for any other control character either, and refuses them all. A stop
id is whatever its upload's file says, so a path naming one refuses only NUL, which no
stored id holds.

The patterns are written so that Python, Rust (pydantic) and JSON Schema (ECMA) regular
expressions read them the same way, so the published spec and the server agree on every
character: no `\\s`, which each of the three reads differently, and no `\\d` or `\\w`.
"""

from typing import Annotated

from fastapi import Path, Query
from pydantic import StringConstraints

from starboard.geo.geocoding import CENSUS_ONELINE_MAX_CHARACTERS

# C0 controls and DEL, as a character-class body.
CONTROL_CHARACTERS = r"\x00-\x1f\x7f"
# The other white space: Unicode's White_Space characters above the controls, and the
# byte order mark, which ECMA counts as space. A character-class body.
SPACES = r"\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_PLAIN = rf"^[^{CONTROL_CHARACTERS}]*$"
# Plain, and more than spaces: the spec refuses a blank line, as the server does once it
# has dropped the spaces around a line.
_NOT_BLANK = rf"^[^{CONTROL_CHARACTERS}]*[^{CONTROL_CHARACTERS}{SPACES}][^{CONTROL_CHARACTERS}]*$"

_LINE = StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=_NOT_BLANK)

# The name of an organization or a route, without the spaces around it.
Name = Annotated[str, _LINE]

# An address on one line, as a planner types it or as the geocoder matched it.
AddressLine = Annotated[str, _LINE]

# An address to look up, as a query parameter, no longer than the geocoder takes.
ADDRESS_QUERY = Query(min_length=1, max_length=CENSUS_ONELINE_MAX_CHARACTERS, pattern=_NOT_BLANK)

# A stop's id from its upload, as a path parameter.
StopId = Annotated[str, Path(pattern=r"^[^\x00]*$")]
