"""Socket transport contracts for the openMSX control protocol."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from html import escape
from pathlib import Path
import socket
import stat
from typing import Optional, Tuple
from xml.etree import ElementTree

from .api import TargetProtocolError, TargetTimeout, TargetUnavailable


_OPENMSX_RUNTIME_ROOT = Path("/tmp")
_EVENT_QUEUE_LIMIT = 256
_READ_SIZE = 4096


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


@dataclass(frozen=True)
class TransportStats:
    requests: int
    connections: int


class OpenMSXTransport:
    def __init__(self, config: TransportConfig) -> None:
        self._config = config
        self._events: deque[ProtocolEvent] = deque()
        self._dropped_events = 0
        self._closed = False
        self._control: Optional[socket.socket] = None
        self._parser: Optional[ElementTree.XMLPullParser] = None
        self._root_seen = False
        self._requests = 0
        self._connections = 0

    @property
    def stats(self) -> TransportStats:
        return TransportStats(self._requests, self._connections)

    def request(self, tcl: str) -> TclReply:
        if self._closed:
            raise TargetUnavailable(
                "openMSX transport is closed", "transport.request"
            )
        self._requests += 1
        if self._config.connection_mode == ConnectionMode.PERSISTENT:
            return self._request_persistent(tcl)
        return self._request_per_command(tcl)

    def _request_per_command(self, tcl: str) -> TclReply:
        control = self._connect()
        parser = ElementTree.XMLPullParser(events=("start", "end"))
        try:
            reply, _ = self._exchange(control, parser, False, tcl)
            return reply
        finally:
            _close_socket(control)

    def _request_persistent(self, tcl: str) -> TclReply:
        if self._control is None:
            self._control = self._connect()
            self._parser = ElementTree.XMLPullParser(events=("start", "end"))
            self._root_seen = False
        assert self._parser is not None
        try:
            reply, self._root_seen = self._exchange(
                self._control, self._parser, self._root_seen, tcl
            )
            return reply
        except BaseException:
            self._discard_persistent()
            raise

    def _connect(self) -> socket.socket:
        try:
            control = _connect_unix(
                self._config.socket_path, self._config.timeout_seconds
            )
        except socket.timeout as error:
            raise TargetTimeout(
                "timed out connecting to openMSX", "transport.request"
            ) from error
        except (ConnectionError, OSError) as error:
            raise TargetUnavailable(
                f"cannot connect to openMSX: {error}", "transport.request"
            ) from error
        self._connections += 1
        return control

    def _exchange(self, control: socket.socket,
                  parser: ElementTree.XMLPullParser, root_seen: bool,
                  tcl: str) -> Tuple[TclReply, bool]:
        sent = False
        try:
            while not root_seen:
                chunk = _receive(control, sent)
                parser.feed(chunk)
                for event, element in parser.read_events():
                    if event == "start":
                        if not root_seen:
                            if element.tag != "openmsx-output":
                                raise _protocol_error(
                                    "expected openmsx-output handshake, got "
                                    f"{element.tag}", sent
                                )
                            root_seen = True
                    elif element.tag == "update":
                        self._record_update(element)
                    elif element.tag == "reply":
                        raise _protocol_error(
                            "openMSX replied before a command was sent", sent
                        )

            document = f"<command>{escape(tcl, quote=False)}</command>\n"
            sent = True
            control.sendall(document.encode("utf-8"))

            while True:
                chunk = _receive(control, sent)
                parser.feed(chunk)
                reply = None
                for event, element in parser.read_events():
                    if event != "end":
                        continue
                    if element.tag == "update":
                        self._record_update(element)
                    elif element.tag == "reply":
                        if reply is not None:
                            raise _protocol_error(
                                "openMSX sent multiple replies for one command", sent
                            )
                        status = element.attrib.get("result")
                        if status not in ("ok", "nok"):
                            raise _protocol_error(
                                "openMSX reply has invalid or missing result", sent
                            )
                        text = "".join(element.itertext())
                        element.clear()
                        reply = TclReply(status, text)
                if reply is not None:
                    return reply, root_seen
        except socket.timeout as error:
            raise TargetTimeout(
                "timed out communicating with openMSX",
                "transport.request",
                outcome_unknown=sent,
            ) from error
        except (ConnectionError, OSError) as error:
            raise TargetUnavailable(
                f"cannot communicate with openMSX: {error}",
                "transport.request",
                outcome_unknown=sent,
            ) from error
        except ElementTree.ParseError as error:
            raise TargetProtocolError(
                f"invalid XML from openMSX: {error}",
                "transport.request",
                outcome_unknown=sent,
            ) from error

    def drain_events(self) -> Tuple[ProtocolEvent, ...]:
        events = []
        if self._dropped_events:
            events.append(ProtocolEvent("overflow", str(self._dropped_events)))
        events.extend(self._events)
        self._events.clear()
        self._dropped_events = 0
        return tuple(events)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._discard_persistent()

    def _discard_persistent(self) -> None:
        if self._control is not None:
            _close_socket(self._control)
        self._control = None
        self._parser = None
        self._root_seen = False

    def _append_event(self, event: ProtocolEvent) -> None:
        if len(self._events) == _EVENT_QUEUE_LIMIT:
            self._events.popleft()
            self._dropped_events += 1
        self._events.append(event)

    def _record_update(self, element: ElementTree.Element) -> None:
        self._append_event(ProtocolEvent(
            element.attrib.get("type", "unknown"),
            "".join(element.itertext()),
        ))
        element.clear()


def _connect_unix(path: Path, timeout_seconds: float) -> socket.socket:
    control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        control.settimeout(timeout_seconds)
        control.connect(str(path))
        return control
    except BaseException:
        control.close()
        raise


def _close_socket(control: socket.socket) -> None:
    try:
        control.close()
    except OSError:
        pass


def _receive(control: socket.socket, sent: bool) -> bytes:
    chunk = control.recv(_READ_SIZE)
    if not chunk:
        raise TargetProtocolError(
            "openMSX closed the control connection before replying",
            "transport.request",
            outcome_unknown=sent,
        )
    return chunk


def _protocol_error(message: str, sent: bool) -> TargetProtocolError:
    return TargetProtocolError(
        message, "transport.request", outcome_unknown=sent
    )


def discover_socket(explicit: Optional[Path]) -> Path:
    """Return an existing openMSX control socket without starting openMSX.

    Automatic discovery follows the legacy ``/tmp/openmsx-*/socket.*``
    convention.  Modification time selects the newest socket and the path is
    used as a deterministic tie breaker, rather than relying on filesystem
    iteration order.
    """
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        if _is_socket(candidate):
            return candidate
        raise TargetUnavailable(
            f"openMSX control socket is not available: {candidate}; "
            "msxdbg is attach-only and never starts openMSX",
            "discover_socket",
        )

    candidates = tuple(
        path
        for directory in _OPENMSX_RUNTIME_ROOT.glob("openmsx-*")
        if directory.is_dir()
        for path in directory.glob("socket.*")
        if _is_socket(path)
    )
    if not candidates:
        raise TargetUnavailable(
            "no openMSX control socket found under /tmp/openmsx-*/socket.*; "
            "msxdbg is attach-only and never starts openMSX",
            "discover_socket",
        )
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))


def _is_socket(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except OSError:
        return False


__all__ = ["ConnectionMode", "OpenMSXTransport", "ProtocolEvent", "TclReply",
           "TransportConfig", "TransportStats", "discover_socket"]
