"""Tokens for magic links and sessions: random, sent once, stored only as a hash."""

import hashlib
import secrets
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from starboard.api.text import CONTROL_CHARACTERS, SPACES

# 32 random bytes: 256 bits, beyond guessing for the life of a link or session.
_TOKEN_BYTES = 32
# The length of the email columns (migrations/0001): RFC 5321's 64 + "@" + 255.
_EMAIL_LENGTH = 320


def new_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def token_hash(token: str) -> str:
    """SHA-256 of the token, in hex; the only form a token is stored in."""
    return hashlib.sha256(token.encode()).hexdigest()


def normalized_email(email: str) -> str:
    return email.strip().lower()


def _fits_once_normalized(email: str) -> str:
    # Lower case can be longer: U+0130, a capital I with a dot, becomes "i" and a
    # combining dot.
    if len(normalized_email(email)) > _EMAIL_LENGTH:
        raise ValueError(f"the address is over {_EMAIL_LENGTH} characters in lower case")
    return email


# An address as the spec states it: something@somewhere, no spaces and no control
# characters. Deliverability is not judged here; a link to an address that does not
# exist is simply never opened.
_ADDRESS_PART = rf"[^@{CONTROL_CHARACTERS}{SPACES}]+"
EmailAddress = Annotated[
    str,
    StringConstraints(max_length=_EMAIL_LENGTH, pattern=rf"^{_ADDRESS_PART}@{_ADDRESS_PART}$"),
    AfterValidator(_fits_once_normalized),
]
