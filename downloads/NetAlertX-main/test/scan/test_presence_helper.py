"""
Tests for server/scan/presence.py's current_scan_presence_condition() -
the shared predicate helper from scan-pipeline-hardening.md Design §1.

Two things are tested:
1. The helper itself: correct SQL fragment, and rejects anything that isn't
   a plain SQL identifier (the trust-boundary check - this function does raw
   string interpolation, never parameterized SQL).
2. A positive, AST-based guard (not a grep for one hand-written spelling,
   which is trivially defeated by an equivalent one - scanPresence <> 0,
   bare scanPresence, NOT scanPresence = 0, etc.) that each migrated
   consumer function's source actually calls the helper the expected number
   of times. This is what stops a future change from quietly reintroducing
   a hand-written predicate instead of calling the shared one.

Not covered here on purpose: "New Connections" (session_events.py) and the
raw Sessions insert (device_handling.py's create_new_devices()) - both need
the actual scanLastIP/scanVendor *values* off the presence-asserting row via
MIN()/GROUP BY, not just a boolean, so they keep their own hand-written
aggregation - see scan-pipeline-hardening.md Design §1's correction.
"""

import ast
import inspect
import os
import sqlite3
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "server"))

from scan.presence import current_scan_presence_condition  # noqa: E402
from scan import device_handling  # noqa: E402
from scan import session_events  # noqa: E402


class TestHelperCorrectness:
    def test_returns_expected_sql_fragment(self):
        result = current_scan_presence_condition("devMac")
        assert "EXISTS (" in result
        assert "SELECT 1 FROM CurrentScan" in result
        assert "scanMac = devMac" in result
        assert "scanPresence = 1" in result

    def test_accepts_qualified_column_reference(self):
        result = current_scan_presence_condition("CurrentScan.scanMac")
        assert "scanMac = CurrentScan.scanMac" in result

    @pytest.mark.parametrize("bad_value", [
        "devMac; DROP TABLE Devices--",
        "devMac OR 1=1",
        "'; DELETE FROM Devices; --",
        "devMac)",
        "",
        "123devMac",
    ])
    def test_rejects_non_identifier_input(self, bad_value):
        with pytest.raises(ValueError):
            current_scan_presence_condition(bad_value)

    @pytest.mark.parametrize("bad_value", ["presence_scan", "presence_scan.scanMac"])
    def test_rejects_presence_scan_qualifier(self, bad_value):
        """presence_scan is this helper's own internal subquery alias."""
        with pytest.raises(ValueError):
            current_scan_presence_condition(bad_value)


class TestQualifiedColumnExecutesCorrectly:
    """Executes the fragment, not just checks the generated SQL text - proves
    a qualified mac_column ("CurrentScan.scanMac") still discriminates
    per-row rather than collapsing into "does any row assert presence"."""

    def test_only_the_present_mac_matches(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE CurrentScan (scanMac TEXT, scanPresence INTEGER)")
        conn.execute("INSERT INTO CurrentScan VALUES ('aa', 1)")  # present
        conn.execute("INSERT INTO CurrentScan VALUES ('bb', 0)")  # row exists, not present
        conn.commit()

        condition = current_scan_presence_condition("CurrentScan.scanMac")
        rows = conn.execute(
            f"SELECT scanMac, {condition} AS is_present FROM CurrentScan"
        ).fetchall()

        assert dict(rows) == {"aa": 1, "bb": 0}, (
            "each row must be checked against its own scanMac, not collapse "
            "into a table-wide 'does anything assert presence' check"
        )


def _call_count(func, target_name="current_scan_presence_condition"):
    """Count calls to target_name within func's own source (AST-based, not
    a text grep - resilient to reformatting, doesn't care how a bypass
    might be spelled, only whether the actual call is present)."""
    source = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(source)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == target_name:
            count += 1
    return count


class TestConsumersCallTheHelper:
    """Guards the five sites that were migrated to the shared predicate."""

    def test_update_presence_from_current_scan_calls_helper_twice(self):
        assert _call_count(device_handling.update_presence_from_CurrentScan) == 2, (
            "update_presence_from_CurrentScan() has two statements (present/not-present) "
            "- both must call current_scan_presence_condition()"
        )

    def test_update_dev_last_connection_calls_helper_once(self):
        assert _call_count(device_handling.update_devLastConnection_from_CurrentScan) == 1

    def test_insert_events_calls_helper_at_least_three_times(self):
        """insert_events() contains four queries total - Device Down (x2),
        Disconnected, and New Connections. Only the first three are plain
        boolean-predicate sites; New Connections keeps its own present_agg/
        MIN(scanLastIP) aggregation on purpose (see module docstring), so
        this asserts >= 3, not == 4."""
        assert _call_count(session_events.insert_events) >= 3
