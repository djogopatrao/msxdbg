"""Confirmation and program-signature safety contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol
from uuid import uuid4

from .results import SafetyError

from .state import SignatureSpec


class DangerousAction(str, Enum):
    RESET = "reset"
    LOAD = "load"


@dataclass(frozen=True)
class InteractiveEntry:
    text: str
    fresh_input: bool


@dataclass(frozen=True)
class ConfirmationPermit:
    action: DangerousAction
    session_id: str
    nonce: int


class SafetyGate:
    def __init__(self, session_id: Optional[str] = None) -> None:
        self._session_id = session_id or uuid4().hex
        self._next_nonce = 1
        self._outstanding = set()

    def authorize_typed(self, action: DangerousAction, entry: InteractiveEntry) -> ConfirmationPermit:
        expected = f"{action.value} yes"
        if not entry.fresh_input or entry.text != expected:
            raise SafetyError(f"{expected!r} must be fresh interactive input")
        permit = ConfirmationPermit(action, self._session_id, self._next_nonce)
        self._next_nonce += 1
        self._outstanding.add((permit.action, permit.session_id, permit.nonce))
        return permit

    def consume(self, permit: ConfirmationPermit, action: DangerousAction) -> None:
        key = (permit.action, permit.session_id, permit.nonce)
        if permit.session_id != self._session_id or permit.action != action:
            raise SafetyError("confirmation permit belongs to another session or action")
        if key not in self._outstanding:
            raise SafetyError("confirmation permit is invalid, consumed, or replayed")
        self._outstanding.remove(key)


class SignatureStatus(str, Enum):
    NOT_CONFIGURED = "not-configured"
    PENDING = "pending"
    VERIFIED = "verified"


class SignatureReader(Protocol):
    def read_memory(self, address: int, size: int) -> bytes: ...


class SignatureGuard:
    def __init__(self, spec: Optional[SignatureSpec]) -> None:
        self._spec = spec
        self._status = (SignatureStatus.NOT_CONFIGURED if spec is None
                        else SignatureStatus.PENDING)
    def check(self, reader: SignatureReader) -> SignatureStatus:
        if self._status in (SignatureStatus.NOT_CONFIGURED, SignatureStatus.VERIFIED):
            return self._status
        assert self._spec is not None
        data = reader.read_memory(self._spec.address, len(self._spec.expected))
        if data == self._spec.expected:
            self._status = SignatureStatus.VERIFIED
        return self._status
    def rearm(self) -> None:
        if self._spec is not None:
            self._status = SignatureStatus.PENDING


__all__ = ["ConfirmationPermit", "DangerousAction", "InteractiveEntry", "SafetyGate", "SignatureGuard", "SignatureReader", "SignatureStatus"]
