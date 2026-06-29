"""Daemon-side tests: STATE/CLEAR/TRANSIENT dispatch, priority aggregation,
transient TTL expiry, malformed-line safety.

Run: python3 -m unittest tests.test_daemon   (from repo root)
  or: python3 tests/test_daemon.py
"""

from __future__ import annotations

import os
import sys
import time
import unittest

# Make driver/ importable when running from repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))

from led_daemon import Daemon, TransientEntry


class _CapturingDaemon(Daemon):
    """Daemon subclass that captures serial writes instead of touching hardware."""

    def __init__(self):
        super().__init__(port_override=None, log=__import__("logging").getLogger("test"))
        # Pretend serial is connected; capture writes into a list.
        self.disconnected = False
        self._writes: list[str] = []
        self.serial = type("FakeSerial", (), {
            "write": lambda _self, data: self._writes.append(data.decode("utf-8", errors="replace")),
            "flush": lambda _self: None,
            "close": lambda _self: None,
            "port": "FAKE",
        })()

    @property
    def writes(self) -> list[str]:
        return [w.rstrip() for w in self._writes]


class AggregationTest(unittest.TestCase):
    def setUp(self):
        self.d = _CapturingDaemon()

    def _last(self) -> str | None:
        return self.d.writes[-1] if self.d.writes else None

    def test_state_creates_session_and_emits(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        self.assertEqual(self._last(), "scanner 90 0 170 1600 100")
        self.assertIn("A", self.d.sessions)
        self.assertEqual(self.d.sessions["A"].priority, 60)

    def test_lower_priority_does_not_override(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        self.d.dispatch_line("STATE B 10 breathe 0 50 220 3500 100")
        self.assertEqual(self._last(), "scanner 90 0 170 1600 100")

    def test_higher_priority_overrides(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        self.d.dispatch_line("STATE B 100 blink 180 0 0 300 100")
        self.assertEqual(self._last(), "blink 180 0 0 300 100")

    def test_clear_reverts_to_next_highest(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        self.d.dispatch_line("STATE B 100 blink 180 0 0 300 100")
        self.d.dispatch_line("CLEAR B")
        self.assertEqual(self._last(), "scanner 90 0 170 1600 100")

    def test_clear_last_session_emits_off(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        self.d.dispatch_line("CLEAR A")
        self.assertEqual(self._last(), "off")

    def test_clear_unknown_session_is_noop(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        before = list(self.d.writes)
        self.d.dispatch_line("CLEAR does-not-exist")
        self.assertEqual(self.d.writes, before)

    def test_priority_tie_last_write_wins(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        time.sleep(0.01)
        self.d.dispatch_line("STATE B 60 breathe 0 50 220 3500 100")
        self.assertEqual(self._last(), "breathe 0 50 220 3500 100")


class TransientTest(unittest.TestCase):
    def setUp(self):
        self.d = _CapturingDaemon()

    def _last(self) -> str | None:
        return self.d.writes[-1] if self.d.writes else None

    def test_transient_overrides_session(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        self.d.dispatch_line("TRANSIENT 3000 blink 180 0 0 300 100")
        self.assertEqual(self._last(), "blink 180 0 0 300 100")

    def test_transient_expiry_reverts_to_session(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        self.d.dispatch_line("TRANSIENT 3000 blink 180 0 0 300 100")
        # Force expiry
        self.d.transient = TransientEntry(self.d.transient.wire, time.monotonic() - 0.001)
        self.d.recompute_and_emit()
        self.assertEqual(self._last(), "scanner 90 0 170 1600 100")

    def test_transient_with_no_sessions_emits_off_after_expiry(self):
        self.d.dispatch_line("TRANSIENT 3000 blink 180 0 0 300 100")
        self.d.transient = TransientEntry(self.d.transient.wire, time.monotonic() - 0.001)
        self.d.recompute_and_emit()
        self.assertEqual(self._last(), "off")

    def test_strobe_transient_preserves_all_fields(self):
        # Strobe has 9 tokens — wire-line must pass through opaquely.
        self.d.dispatch_line("TRANSIENT 500 strobe 180 0 0 0 0 180 300 100")
        self.assertEqual(self._last(), "strobe 180 0 0 0 0 180 300 100")


class OpaqueWireTest(unittest.TestCase):
    """The daemon must not parse or interpret the wire-line at all — it just
    stores and forwards it. Strobe (9 tokens) and off (1 token) are the
    edge cases that would break a fixed-field parser.
    """

    def setUp(self):
        self.d = _CapturingDaemon()

    def _last(self) -> str | None:
        return self.d.writes[-1] if self.d.writes else None

    def test_off_one_token(self):
        self.d.dispatch_line("STATE A 0 off")
        self.assertEqual(self._last(), "off")

    def test_strobe_nine_tokens(self):
        self.d.dispatch_line("STATE A 100 strobe 180 0 0 0 0 180 300 100")
        self.assertEqual(self._last(), "strobe 180 0 0 0 0 180 300 100")

    def test_solid_four_tokens(self):
        self.d.dispatch_line("STATE A 50 solid 0 0 255 30")
        self.assertEqual(self._last(), "solid 0 0 255 30")


class RedundantEmitSuppressionTest(unittest.TestCase):
    def setUp(self):
        self.d = _CapturingDaemon()

    def test_re_sending_same_state_does_not_emit(self):
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        count_before = len(self.d.writes)
        self.d.dispatch_line("STATE A 60 scanner 90 0 170 1600 100")
        self.assertEqual(len(self.d.writes), count_before)


class MalformedLineTest(unittest.TestCase):
    """The daemon must never crash on bad input — it logs and drops."""

    def setUp(self):
        self.d = _CapturingDaemon()

    def test_each_malformed_variant_is_dropped(self):
        bad_lines = [
            "GARBAGE",
            "STATE",                  # missing fields
            "STATE onlysid",          # missing priority + wire
            "STATE A notanum wire",   # priority not int
            "CLEAR",                  # missing sid
            "TRANSIENT",              # missing fields
            "TRANSIENT notanum wire", # ttl not int
            "UNKNOWNVerb x y z",
            "",                       # empty (dispatch_line receives non-empty from handle_client but test directly)
        ]
        for line in bad_lines:
            try:
                self.d.dispatch_line(line)
            except Exception as e:
                self.fail(f"dispatch_line({line!r}) raised {e!r}")
        # None of these should have produced any serial writes.
        self.assertEqual(self.d.writes, [])


if __name__ == "__main__":
    unittest.main()
