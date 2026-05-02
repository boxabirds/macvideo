"""Integration tests for queue run-status fidelity.

Story 12 bug: handlers returning StageResult(ok=False) (e.g. preflight
failure, subprocess non-zero exit) were silently marked status='done' with
error=None — the failure never reached the user. These tests pin the
contract for every handler return shape:

    return value             | run.status | run.error
    -------------------------|------------|-----------------------------
    StageResult(ok=True)     | done       | NULL
    StageResult(ok=False)    | failed     | stderr_tail / stdout_tail
    raises Exception         | failed     | str(exc) / type name
    None / non-StageResult   | done       | NULL  (legacy paths)
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from editor.server.pipeline.result import StageResult
from editor.server.regen.queue import RegenJob, _RegenQueue
from editor.server.regen.runs import RegenRun, create_run, get_run, update_run_status
from editor.server.store import connection


def _make_run(db_path: Path) -> RegenRun:
    """Create a minimal song + regen_runs row for the queue to drive."""
    with connection(db_path) as c:
        now = time.time()
        c.execute(
            "INSERT INTO songs (slug, audio_path, duration_s, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("queue-test-song", "/tmp/queue-test.wav", 1.0, now, now),
        )
        song_id = c.execute(
            "SELECT id FROM songs WHERE slug = 'queue-test-song'",
        ).fetchone()["id"]
        run_id = create_run(c, scope="stage_world_brief", song_id=song_id)
        return get_run(c, run_id)


def _drain(queue: _RegenQueue, run_id: int, db_path: Path, timeout=3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with connection(db_path) as c:
            row = c.execute(
                "SELECT status, error, ended_at FROM regen_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row and row["status"] in ("done", "failed", "cancelled"):
            return dict(row)
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach terminal state in {timeout}s")


def _new_queue(db_path: Path) -> _RegenQueue:
    q = _RegenQueue(name="test-queue", concurrency=1)
    q.configure(db_path)
    return q


def test_handler_returning_stage_result_ok_marks_done(tmp_env):
    """Baseline: ok=True StageResult → status=done, error=None."""
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])

    async def handler(_r):
        return StageResult(ok=True, returncode=0, new_keyframes=0,
                           new_prompts=0, stdout_tail="ok", stderr_tail="",
                           duration_s=0.1)

    queue.submit(RegenJob(run=run, handler=handler))
    final = _drain(queue, run.id, tmp_env["db"])
    assert final["status"] == "done"
    assert final["error"] is None
    assert final["ended_at"] is not None
    queue.shutdown(wait=True)


def test_handler_returning_stage_result_not_ok_marks_failed_with_stderr(tmp_env):
    """The bug: ok=False StageResult must mark run failed with non-null error."""
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])

    async def handler(_r):
        return StageResult(
            ok=False, returncode=1, new_keyframes=0, new_prompts=0,
            stdout_tail="", stderr_tail="expected music/foo.wav to exist",
            duration_s=0.0,
        )

    queue.submit(RegenJob(run=run, handler=handler))
    final = _drain(queue, run.id, tmp_env["db"])
    assert final["status"] == "failed"
    assert final["error"] is not None
    assert "expected music/foo.wav" in final["error"]
    queue.shutdown(wait=True)


def test_handler_returning_stage_result_not_ok_falls_back_to_stdout(tmp_env):
    """When stderr is empty, error is sourced from stdout_tail instead."""
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])

    async def handler(_r):
        return StageResult(
            ok=False, returncode=2, new_keyframes=0, new_prompts=0,
            stdout_tail="some stdout context", stderr_tail="",
            duration_s=0.0,
        )

    queue.submit(RegenJob(run=run, handler=handler))
    final = _drain(queue, run.id, tmp_env["db"])
    assert final["status"] == "failed"
    assert "some stdout context" in final["error"]
    queue.shutdown(wait=True)


def test_handler_raising_exception_marks_failed(tmp_env):
    """Existing behaviour preserved: raised exception → status=failed."""
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])

    async def handler(_r):
        raise RuntimeError("boom")

    queue.submit(RegenJob(run=run, handler=handler))
    final = _drain(queue, run.id, tmp_env["db"])
    assert final["status"] == "failed"
    assert "boom" in final["error"]
    queue.shutdown(wait=True)


def test_external_cancel_is_not_overwritten_by_late_stage_result_failure(tmp_env):
    """Cancel endpoint writes status=cancelled while the worker is still inside
    the subprocess. When the killed subprocess returns later, the queue must not
    overwrite that terminal state with failed/raw stderr output.
    """
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])
    entered = threading.Event()
    release = threading.Event()

    async def handler(_r):
        entered.set()
        assert release.wait(timeout=3.0)
        return StageResult(
            ok=False, returncode=-15, new_keyframes=0, new_prompts=0,
            stdout_tail="", stderr_tail="raw subprocess progress spam",
            duration_s=0.0,
        )

    queue.submit(RegenJob(run=run, handler=handler))
    assert entered.wait(timeout=3.0)

    with connection(tmp_env["db"]) as c:
        update_run_status(c, run.id, "cancelled")

    release.set()
    final = _drain(queue, run.id, tmp_env["db"])
    queue.shutdown(wait=True)

    assert final["status"] == "cancelled"
    assert final["error"] is None


def test_pending_cancel_is_not_overwritten_when_worker_starts(tmp_env):
    """If the cancel endpoint marks a queued-but-not-yet-running job cancelled,
    the worker must not later revive it as running/done.
    """
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])
    called = threading.Event()

    async def handler(_r):
        called.set()
        return StageResult(
            ok=True, returncode=0, new_keyframes=0, new_prompts=0,
            stdout_tail="", stderr_tail="", duration_s=0.0,
        )

    with connection(tmp_env["db"]) as c:
        update_run_status(c, run.id, "cancelled")

    queue.submit(RegenJob(run=run, handler=handler))
    time.sleep(0.2)
    queue.shutdown(wait=True)

    with connection(tmp_env["db"]) as c:
        row = c.execute(
            "SELECT status, error FROM regen_runs WHERE id = ?", (run.id,),
        ).fetchone()

    assert called.is_set() is False
    assert row["status"] == "cancelled"
    assert row["error"] is None


def test_external_cancel_is_not_overwritten_by_late_success(tmp_env):
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])
    entered = threading.Event()
    release = threading.Event()

    async def handler(_r):
        entered.set()
        assert release.wait(timeout=3.0)
        return StageResult(
            ok=True, returncode=0, new_keyframes=0, new_prompts=0,
            stdout_tail="", stderr_tail="", duration_s=0.0,
        )

    queue.submit(RegenJob(run=run, handler=handler))
    assert entered.wait(timeout=3.0)

    with connection(tmp_env["db"]) as c:
        update_run_status(c, run.id, "cancelled")

    release.set()
    final = _drain(queue, run.id, tmp_env["db"])
    queue.shutdown(wait=True)

    assert final["status"] == "cancelled"
    assert final["error"] is None


def test_external_cancel_is_not_overwritten_by_late_exception(tmp_env):
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])
    entered = threading.Event()
    release = threading.Event()

    async def handler(_r):
        entered.set()
        assert release.wait(timeout=3.0)
        raise RuntimeError("late worker exception")

    queue.submit(RegenJob(run=run, handler=handler))
    assert entered.wait(timeout=3.0)

    with connection(tmp_env["db"]) as c:
        update_run_status(c, run.id, "cancelled")

    release.set()
    final = _drain(queue, run.id, tmp_env["db"])
    queue.shutdown(wait=True)

    assert final["status"] == "cancelled"
    assert final["error"] is None


def test_handler_returning_none_marks_done(tmp_env):
    """Legacy contract: None / non-StageResult return value → done.
    Preserves scene-regen + final-render handlers that don't return anything."""
    from editor.server.store.schema import init_db
    init_db(tmp_env["db"])
    run = _make_run(tmp_env["db"])
    queue = _new_queue(tmp_env["db"])

    async def handler(_r):
        return None

    queue.submit(RegenJob(run=run, handler=handler))
    final = _drain(queue, run.id, tmp_env["db"])
    assert final["status"] == "done"
    assert final["error"] is None
    queue.shutdown(wait=True)
