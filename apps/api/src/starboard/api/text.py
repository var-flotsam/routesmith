"""Text the API takes in: none of it may hold a control character.

Postgres cannot store the NUL character in text (https://www.postgresql.org/docs/current/
datatype-character.html), so a NUL that reached a query was a server error; and a name,
an address or a stop id has no use for any other control character. Text with one is
refused as a validation error instead.
"""

from typing import Annotated

from fastapi import Path
from pydantic import StringConstraints

# C0 controls and DEL, as a character-class body that Python, Rust (pydantic) and
# JSON Schema regular expressions all read the same way.
CONTROL_CHARACTERS = r"\x00-\x1f\x7f"
_PLAIN = rf"^[^{CONTROL_CHARACTERS}]*$"

# The name of an organization or a route.
Name = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=_PLAIN)]

# A stop's id from its upload, as a path parameter.
StopId = Annotated[str, Path(pattern=_PLAIN)]
