"""Status-transition validation shared by orders, deliveries and invoices.

Each domain declares which moves are legal; this enforces them identically everywhere, so
an invalid move is always a 409 with the same shape rather than a per-module invention.
"""

from dataclasses import dataclass

from fastapi import status

from app.shared.exceptions.api_error import ApiError


@dataclass(frozen=True)
class StatusMachine:
    """Allowed moves for one resource, keyed by the state being left."""

    name: str
    allowed: dict[str, frozenset[str]]
    terminal: frozenset[str] = frozenset()

    def can_move(self, current: str, target: str) -> bool:
        return target in self.allowed.get(current, frozenset())

    def require_move(self, current: str, target: str, *, code: str = "INVALID_STATUS_TRANSITION") -> None:
        """Raise 409 unless `current` -> `target` is declared legal.

        A repeat of a move that already happened is reported the same way, which is what
        makes a double dispatch or a second approval safe to retry from a flaky network.
        """
        if not self.can_move(current, target):
            raise ApiError(code, status.HTTP_409_CONFLICT)

    def is_terminal(self, state: str) -> bool:
        return state in self.terminal
