"""Compare street names written differently, such as 'Chestnut St W' and 'Chestnut Street West'.

Abbreviations follow USPS Publication 28: street suffixes from Appendix C1
(https://pe.usps.com/text/pub28/28apc_002.htm) and directionals from
section 233 (https://pe.usps.com/text/pub28/28c2_014.htm). The list covers
common residential suffixes and grows as imports need it.
"""

import re

_SUFFIXES = {
    "aly": "alley",
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "cir": "circle",
    "ct": "court",
    "cv": "cove",
    "dr": "drive",
    "expy": "expressway",
    "hwy": "highway",
    "ln": "lane",
    "pkwy": "parkway",
    "pl": "place",
    "plz": "plaza",
    "rd": "road",
    "sq": "square",
    "st": "street",
    "ter": "terrace",
    "trl": "trail",
    "way": "way",
}

_DIRECTIONALS = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}

_WORD = re.compile(r"[a-z0-9]+")


def normalized_street_name(name: str) -> str:
    """Lower case, punctuation removed, suffixes and directionals spelled out."""
    words = _WORD.findall(name.lower())
    return " ".join(_SUFFIXES.get(word, _DIRECTIONALS.get(word, word)) for word in words)


def same_street_name(first: str | None, second: str | None) -> bool:
    if first is None or second is None:
        return False
    return normalized_street_name(first) == normalized_street_name(second)
