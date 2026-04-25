"""Unit tests for the queue's status-transition branches.

Pure logic — no DB, no thread pool, no SQLite. Patches update_run_status
and hub.publish so we can assert what the queue's _execute() decides
based purely on handler return value / exception, isolated from
persistence.

The four documented branches:
  StageResult(ok=True)   → done, error=None
  StageResult(ok=False)  → failed, error from stderr_tail|stdout_tail|fallback
  raises Exception        → failed, error from str(exc) or type name
  None / non-StageResult → done, error=None
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from editor.server.pipeline.stages import StageResult
from editor.server.regen.queue import RegenJob, _RegenQueue
from editor.server.regen.runs import RegenRun


def _fake_run() -> RegenRun:
    return RegenRun(
        id=42, scope="stage_world_brief", song_id=1, scene_id=None,
        artefact_kind=None, status="pending", quality_mode=None,
        cost_estimate_usd=None, started_at=None, ended_at=None, error=None,
        created_at=0.0,
    )


def _drive_handler_inline(handler) -> list[tuple]:
    """Run _RegenQueue._execute synchronously with patched persistence and
    return the captured (run_id, status, error) tuples in call order."""
    captured: list[tuple] = []

    def fake_update(_conn, run_id, status, *, error=None):
        captured.append((run_id, status, error))

    queue = _RegenQueue(name="unit", concurrency=1)
    queue.configure(Path("/tmp/_unit_queue_unused.db"))

    with patch("editor.server.regen.queue.update_run_status", side_effect=fake_update), \
         patch("editor.server.regen.queue.connection") as fake_conn, \
         patch("editor.server.regen.queue.hub"):
        # connection() is used as a context manager; have it yield None and
        # ignore close — update_run_status doesn't actually touch the conn.
        fake_conn.return_value.__enter__.return_value = None
        fake_conn.return_value.__exit__.return_value = False
        queue._execute(RegenJob(run=_fake_run(), handler=handler))

    queue.shutdown(wait=True)
    return captured


def test_stage_result_ok_marks_done():
    async def h(_r):
        return StageResult(ok=True, returncode=0, new_keyframes=0,
                           new_prompts=0, stdout_tail="", stderr_tail="",
                           duration_s=0.0)
    calls = _drive_handler_inline(h)
    statuses = [(s, e) for (_id, s, e) in calls]
    assert ("running", None) in statuses
    assert ("done", None) in statuses
    assert all(s != "failed" for (s, _) in statuses)


def test_stage_result_not_ok_marks_failed_with_stderr():
    async def h(_r):
        return StageResult(ok=False, returncode=1, new_keyframes=0,
                           new_prompts=0, stdout_tail="",
                           stderr_tail="specific error message",
                           duration_s=0.0)
    calls = _drive_handler_inline(h)
    failed = [c for c in calls if c[1] == "failed"]
    assert len(failed) == 1
    assert failed[0][2] == "specific error message"


def test_stage_result_not_ok_falls_back_to_stdout_when_stderr_empty():
    async def h(_r):
        return StageResult(ok=False, returncode=2, new_keyframes=0,
                           new_prompts=0, stdout_tail="from stdout instead",
                           stderr_tail="", duration_s=0.0)
    calls = _drive_handler_inline(h)
    failed = [c for c in calls if c[1] == "failed"]
    assert len(failed) == 1
    assert "from stdout instead" in failed[0][2]


def test_stage_result_not_ok_falls_back_to_returncode_message_when_both_empty():
    async def h(_r):
        return StageResult(ok=False, returncode=137, new_keyframes=0,
                           new_prompts=0, stdout_tail="", stderr_tail="",
                           duration_s=0.0)
    calls = _drive_handler_inline(h)
    failed = [c for c in calls if c[1] == "failed"]
    assert len(failed) == 1
    assert "137" in failed[0][2]


def test_handler_raising_value_error_marks_failed():
    async def h(_r):
        raise ValueError("boom from handler")
    calls = _drive_handler_inline(h)
    failed = [c for c in calls if c[1] == "failed"]
    assert len(failed) == 1
    assert "boom from handler" in failed[0][2]


def test_handler_raising_no_message_uses_type_name():
    class _CustomErr(Exception):
        pass
    async def h(_r):
        raise _CustomErr()
    calls = _drive_handler_inline(h)
    failed = [c for c in calls if c[1] == "failed"]
    assert len(failed) == 1
    assert "_CustomErr" in failed[0][2]


def test_handler_returning_none_marks_done():
    async def h(_r):
        return None
    calls = _drive_handler_inline(h)
    statuses = [s for (_id, s, _e) in calls]
    assert "done" in statuses
    assert "failed" not in statuses


def test_handler_returning_non_stage_result_dict_marks_done():
    """Legacy fallback: anything that isn't a StageResult is treated as
    success — preserves scene-regen + final-render handlers."""
    async def h(_r):
        return {"new_takes": 1, "ok": True}
    calls = _drive_handler_inline(h)
    statuses = [s for (_id, s, _e) in calls]
    assert "done" in statuses
    assert "failed" not in statuses


@pytest.mark.parametrize(
    "stderr,stdout,returncode,expected_substring",
    [
        ("the actual reason", "noise", 1, "the actual reason"),
        ("", "stdout reason", 1, "stdout reason"),
        ("", "", 99, "99"),
    ],
)
def test_stage_result_error_source_priority(stderr, stdout, returncode, expected_substring):
    """stderr_tail wins; stdout_tail falls back; returncode-message is last."""
    async def h(_r):
        return StageResult(ok=False, returncode=returncode, new_keyframes=0,
                           new_prompts=0, stdout_tail=stdout, stderr_tail=stderr,
                           duration_s=0.0)
    calls = _drive_handler_inline(h)
    failed = [c for c in calls if c[1] == "failed"]
    assert len(failed) == 1
    assert expected_substring in failed[0][2]
