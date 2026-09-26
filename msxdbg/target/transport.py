"""Socket transport contracts for the openMSX control protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


class ConnectionMode:
    PER_COMMAND = "per-command"
    PERSISTENT = "persistent"


@dataclass(frozen=True)
class TransportConfig:
    socket_path: Path
    timeout_seconds: float
    connection_mode: str = ConnectionMode.PER_COMMAND

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("transport timeout must be positive")
        if self.connection_mode not in (ConnectionMode.PER_COMMAND, ConnectionMode.PERSISTENT):
            raise ValueError("unsupported connection mode")


@dataclass(frozen=True)
class TclReply:
    status: str
    text: str


@dataclass(frozen=True)
class ProtocolEvent:
    kind: str
    text: str


class OpenMSXTransport:
    def __init__(self, config: TransportConfig) -> None:
        self._config = config

    def request(self, tcl: str) -> TclReply:
        raise NotImplementedError("OpenMSXTransport.request is not implemented")

    def drain_events(self) -> Tuple[ProtocolEvent, ...]:
        raise NotImplementedError("OpenMSXTransport.drain_events is not implemented")

    def close(self) -> None:
        raise NotImplementedError("OpenMSXTransport.close is not implemented")


def discover_socket(explicit: Optional[Path]) -> Path:
    raise NotImplementedError("target.discover_socket is not implemented")


__all__ = ["ConnectionMode", "OpenMSXTransport", "ProtocolEvent", "TclReply", "TransportConfig", "discover_socket"]
