"""Confirmation and program-signature safety contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

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
    def authorize_typed(self, action: DangerousAction, entry: InteractiveEntry) -> ConfirmationPermit:
        raise NotImplementedError("SafetyGate.authorize_typed is not implemented")
    def consume(self, permit: ConfirmationPermit, action: DangerousAction) -> None:
        raise NotImplementedError("SafetyGate.consume is not implemented")


class SignatureStatus(str, Enum):
    NOT_CONFIGURED = "not-configured"
    PENDING = "pending"
    VERIFIED = "verified"


class SignatureReader(Protocol):
    def read_memory(self, address: int, size: int) -> bytes: ...


class SignatureGuard:
    def __init__(self, spec: SignatureSpec) -> None:
        self._spec = spec
    def check(self, reader: SignatureReader) -> SignatureStatus:
        raise NotImplementedError("SignatureGuard.check is not implemented")
    def rearm(self) -> None:
        raise NotImplementedError("SignatureGuard.rearm is not implemented")


__all__ = ["ConfirmationPermit", "DangerousAction", "InteractiveEntry", "SafetyGate", "SignatureGuard", "SignatureReader", "SignatureStatus"]
