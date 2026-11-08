"""Progress output must not crash when stdout is not UTF-8.

Regression test: a three-repeat baseline run died after one task because the
progress line's tick mark could not be encoded to cp1252, which is what Python
picks on Windows when output is redirected rather than attached to a console.
"""

import io
import subprocess
import sys

from agent_reliability.cli import _force_utf8_output


def test_force_utf8_switches_a_legacy_stream(monkeypatch):
    legacy = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", legacy)
    monkeypatch.setattr(sys, "stderr", legacy)
    _force_utf8_output()
    assert legacy.encoding.lower().replace("-", "") == "utf8"
    print("[1/69] ✓ T01 r0", file=legacy)      # would raise before the fix


def test_force_utf8_tolerates_a_stream_it_cannot_reconfigure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())   # no .reconfigure
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    _force_utf8_output()                                # must not raise


def test_cli_prints_marks_through_a_cp1252_pipe():
    """End to end: the real entry point, output redirected, legacy codepage."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.argv=['x','list-tasks'];"
         "from agent_reliability.cli import main; main();"
         "print('\u2713 done')"],
        capture_output=True, env={"PYTHONIOENCODING": "cp1252", "PATH": ""},
    )
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert b"done" in out.stdout
