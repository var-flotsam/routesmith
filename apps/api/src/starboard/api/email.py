"""Sending sign-in links. Deployed environments plug in a real mail service."""

import logging
from dataclasses import dataclass, field
from typing import Protocol

_log = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send_sign_in_link(self, to: str, link: str) -> None: ...


class ConsoleEmailSender:
    """Development: the link goes to the log instead of a mailbox."""

    async def send_sign_in_link(self, to: str, link: str) -> None:
        _log.info("sign-in link for %s: %s", to, link)


@dataclass
class RecordingEmailSender:
    """Tests: keeps every link it is asked to send."""

    sent: list[tuple[str, str]] = field(default_factory=list)

    async def send_sign_in_link(self, to: str, link: str) -> None:
        self.sent.append((to, link))
