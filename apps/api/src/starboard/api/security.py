"""Tokens for magic links and sessions: random, sent once, stored only as a hash."""

import hashlib
import secrets
from typing import Annotated

from pydantic import StringConstraints

from starboard.api.text import CONTROL_CHARACTERS

# 32 random bytes: 256 bits, beyond guessing for the life of a link or session.
_TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def token_hash(token: str) -> str:
    """SHA-256 of the token, in hex; the only form a token is stored in."""
    return hashlib.sha256(token.encode()).hexdigest()


def normalized_email(email: str) -> str:
    return email.strip().lower()


# An address as the spec states it: something@somewhere, no spaces and no control
# characters. Deliverability is not judged here; a link to an address that does not
# exist is simply never opened.
_ADDRESS_PART = rf"[^@\s{CONTROL_CHARACTERS}]+"
EmailAddress = Annotated[
    str, StringConstraints(max_length=320, pattern=rf"^{_ADDRESS_PART}@{_ADDRESS_PART}$")
]
