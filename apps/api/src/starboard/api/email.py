"""Sending sign-in links. Deployed environments plug in a real mail service."""

import sys
from dataclasses import dataclass, field
from typing import Protocol


class EmailSender(Protocol):
    async def send_sign_in_link(self, to: str, link: str) -> None: ...


class ConsoleEmailSender:
    """Running locally: the link is printed in the API's output instead of mailed.

    With Docker Compose, `docker compose logs api` shows it.
    """

    async def send_sign_in_link(self, to: str, link: str) -> None:
        print(f"Sign-in link for {to}: {link}", file=sys.stdout, flush=True)


@dataclass
class RecordingEmailSender:
    """Tests: keeps every link it is asked to send."""

    sent: list[tuple[str, str]] = field(default_factory=list)

    async def send_sign_in_link(self, to: str, link: str) -> None:
        self.sent.append((to, link))
