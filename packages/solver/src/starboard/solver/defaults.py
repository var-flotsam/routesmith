"""Every tunable in Starboard Routing, each with its unit, reason and source.

Code reads values from here and never writes a bare number for a tunable.
`source` is a public link where one exists; `None` marks a stated default
whose reason is the whole justification.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tunable:
    value: float
    unit: str
    reason: str
    source: str | None = None


def all_tunables() -> dict[str, Tunable]:
    """Every module-level `Tunable` in this file, keyed by name."""
    return {name: value for name, value in globals().items() if isinstance(value, Tunable)}
