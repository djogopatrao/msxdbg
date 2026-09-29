"""Phase 6 per-command transport tests without a live openMSX process."""

from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from msxdbg.target.api import (
    TargetProtocolError,
    TargetTimeout,
    TargetUnavailable,
)
from msxdbg.target.transport import (
    ConnectionMode,
    OpenMSXTransport,
    TransportConfig,
)


class ScriptedSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.closed = False

    def recv(self, size):
        if not self.chunks:
            return b""
        item = self.chunks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


def transport(mode=ConnectionMode.PER_COMMAND):
    return OpenMSXTransport(TransportConfig(Path("control.sock"), 0.25, mode))


class PerCommandTransportTests(unittest.TestCase):
    def execute(self, scripted, command="set x {<>&}"):
        client = transport()
        with patch("msxdbg.target.transport._connect_unix", return_value=scripted):
            reply = client.request(command)
        return client, reply

    def test_ok_reply_and_xml_escaping(self):
        scripted = ScriptedSocket([
            b'<?xml version="1.0"?>\n<openmsx-output>\n',
            b'<reply result="ok">A &amp; B</reply>\n',
        ])

        client, reply = self.execute(scripted)

        self.assertEqual("ok", reply.status)
        self.assertEqual("A & B", reply.text)
        self.assertEqual(
            b"<command>set x {&lt;&gt;&amp;}</command>\n", scripted.sent[0]
        )
        self.assertTrue(scripted.closed)
        self.assertEqual((), client.drain_events())

    def test_reply_can_be_fragmented_at_every_byte(self):
        document = (
            b'<openmsx-output><update type="status">paused</update>'
            b'<reply result="nok">bad command</reply>'
        )
        scripted = ScriptedSocket([bytes((byte,)) for byte in document])

        client, reply = self.execute(scripted, "bad")

        self.assertEqual(("nok", "bad command"), (reply.status, reply.text))
        self.assertEqual("status", client.drain_events()[0].kind)
        self.assertEqual((), client.drain_events())

    def test_event_may_share_handshake_or_reply_chunk(self):
        scripted = ScriptedSocket([
            b'<openmsx-output><update type="boot">ready</update>',
            b'<reply result="ok">done</reply>'
            b'<update type="status">paused</update>',
        ])

        client, reply = self.execute(scripted, "noop")

        self.assertEqual("done", reply.text)
        self.assertEqual(
            (("boot", "ready"), ("status", "paused")),
            tuple((event.kind, event.text) for event in client.drain_events()),
        )

    def test_events_are_ordered_and_overflow_is_observable(self):
        updates = b"".join(
            f'<update type="log">{number}</update>'.encode()
            for number in range(258)
        )
        scripted = ScriptedSocket([
            b"<openmsx-output>",
            updates + b'<reply result="ok"/>',
        ])

        client, _ = self.execute(scripted, "noop")
        events = client.drain_events()

        self.assertEqual(("overflow", "2"), (events[0].kind, events[0].text))
        self.assertEqual("2", events[1].text)
        self.assertEqual("257", events[-1].text)

    def test_timeout_before_send_has_known_outcome(self):
        scripted = ScriptedSocket([socket.timeout("late handshake")])

        with patch("msxdbg.target.transport._connect_unix", return_value=scripted):
            with self.assertRaises(TargetTimeout) as raised:
                transport().request("debug cont")

        self.assertFalse(raised.exception.outcome_unknown)
        self.assertTrue(scripted.closed)

    def test_timeout_after_send_has_unknown_outcome(self):
        scripted = ScriptedSocket([
            b"<openmsx-output>", socket.timeout("late reply")
        ])

        with patch("msxdbg.target.transport._connect_unix", return_value=scripted):
            with self.assertRaises(TargetTimeout) as raised:
                transport().request("debug cont")

        self.assertTrue(raised.exception.outcome_unknown)
        self.assertEqual(1, len(scripted.sent))

    def test_eof_and_malformed_xml_are_protocol_errors(self):
        cases = (
            ([b"<openmsx-output>", b""], True),
            ([b"<wrong-root>"], False),
            ([b"<openmsx-output>", b"<reply>missing result</reply>"], True),
            ([b"<openmsx-output>", b"<reply result=oops>"], True),
        )
        for chunks, unknown in cases:
            with self.subTest(chunks=chunks):
                scripted = ScriptedSocket(chunks)
                with patch("msxdbg.target.transport._connect_unix",
                           return_value=scripted):
                    with self.assertRaises(TargetProtocolError) as raised:
                        transport().request("noop")
                self.assertEqual(unknown, raised.exception.outcome_unknown)

    def test_connect_failure_is_target_unavailable(self):
        with patch("msxdbg.target.transport._connect_unix",
                   side_effect=FileNotFoundError("gone")):
            with self.assertRaises(TargetUnavailable) as raised:
                transport().request("noop")

        self.assertFalse(raised.exception.outcome_unknown)

    def test_close_is_idempotent_and_prevents_requests(self):
        client = transport()
        client.close()
        client.close()

        with self.assertRaises(TargetUnavailable):
            client.request("noop")

    def test_persistent_mode_reuses_connection_and_reports_stats(self):
        scripted = ScriptedSocket([
            b"<openmsx-output>",
            b'<reply result="ok">first</reply>',
            b'<update type="status">paused</update>'
            b'<reply result="ok">second</reply>',
        ])
        client = transport(ConnectionMode.PERSISTENT)

        with patch("msxdbg.target.transport._connect_unix", return_value=scripted):
            self.assertEqual("first", client.request("one").text)
            self.assertEqual("second", client.request("two").text)

        self.assertEqual((2, 1), (client.stats.requests, client.stats.connections))
        self.assertFalse(scripted.closed)
        self.assertEqual("status", client.drain_events()[0].kind)
        client.close()
        self.assertTrue(scripted.closed)

    def test_per_command_stats_show_one_connection_per_request(self):
        sockets = [
            ScriptedSocket([b"<openmsx-output>", b'<reply result="ok">1</reply>']),
            ScriptedSocket([b"<openmsx-output>", b'<reply result="ok">2</reply>']),
        ]
        client = transport()

        with patch("msxdbg.target.transport._connect_unix", side_effect=sockets):
            client.request("one")
            client.request("two")

        self.assertEqual((2, 2), (client.stats.requests, client.stats.connections))
        self.assertTrue(all(item.closed for item in sockets))

    def test_persistent_error_discards_connection_without_retry(self):
        scripted = ScriptedSocket([
            b"<openmsx-output>", b'<reply result="ok">first</reply>', b"",
        ])
        client = transport(ConnectionMode.PERSISTENT)

        with patch("msxdbg.target.transport._connect_unix", return_value=scripted):
            client.request("one")
            with self.assertRaises(TargetProtocolError) as raised:
                client.request("mutation")

        self.assertTrue(raised.exception.outcome_unknown)
        self.assertEqual(2, len(scripted.sent))
        self.assertTrue(scripted.closed)


if __name__ == "__main__":
    unittest.main()
