"""Tokens for magic links and sessions: random, sent once, stored only as a hash."""

import hashlib
import secrets

# 32 random bytes: 256 bits, beyond guessing for the life of a link or session.
_TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def token_hash(token: str) -> str:
    """SHA-256 of the token, in hex; the only form a token is stored in."""
    return hashlib.sha256(token.encode()).hexdigest()


def normalized_email(email: str) -> str:
    return email.strip().lower()
