"""Tests for socrates120x atomic helpers — the shared atomic-write + lock helpers."""

from __future__ import annotations

import sys
import time
from multiprocessing import Process
from pathlib import Path

import pytest

from socrates120x import atomic_write_text, locked_read_modify_write

# ---------------------------------------------------------------------------
# atomic_write_text
# ---------------------------------------------------------------------------


def test_atomic_write_text_writes_full_content(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello world\nline two\n")
    assert target.read_text(encoding="utf-8") == "hello world\nline two\n"


def test_atomic_write_text_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old contents", encoding="utf-8")
    atomic_write_text(target, "new contents")
    assert target.read_text(encoding="utf-8") == "new contents"


def test_atomic_write_text_leaves_no_tempfile_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "ok")
    assert not (tmp_path / "out.txt.tmp").exists()


def test_atomic_write_text_does_not_clobber_on_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If os.replace fails, the pre-existing target must survive intact."""
    target = tmp_path / "out.txt"
    target.write_text("ORIGINAL — do not lose me", encoding="utf-8")

    import socrates120x as atomic_mod

    def boom(src: object, dst: object) -> None:
        raise OSError("simulated replace failure")
    monkeypatch.setattr(atomic_mod.os, "replace", boom)

    with pytest.raises(OSError):
        atomic_write_text(target, "would-be-new-content")

    # Pre-existing data is untouched.
    assert target.read_text(encoding="utf-8") == "ORIGINAL — do not lose me"
    # Tempfile cleaned up.
    assert not (tmp_path / "out.txt.tmp").exists()


def test_atomic_write_text_writes_non_ascii_utf8_by_default(tmp_path: Path) -> None:
    """UTF-8 default lets em-dashes, smart quotes, and non-Latin scripts
    round-trip without explicit encoding= at every call site."""
    target = tmp_path / "out.txt"
    payload = "decision — Café — 漢字 — “smart” quotes"
    atomic_write_text(target, payload)
    assert target.read_text(encoding="utf-8") == payload


# ---------------------------------------------------------------------------
# locked_read_modify_write — single-process semantics
# ---------------------------------------------------------------------------


def test_locked_rmw_runs_mutate_with_current_text(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("before", encoding="utf-8")
    seen: dict[str, str] = {}

    def mutate(current: str) -> str:
        seen["value"] = current
        return current + "—after"

    locked_read_modify_write(target, mutate)
    assert seen["value"] == "before"
    assert target.read_text(encoding="utf-8") == "before—after"


def test_locked_rmw_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        locked_read_modify_write(tmp_path / "ghost.txt", lambda s: s)


# ---------------------------------------------------------------------------
# locked_read_modify_write — concurrent write serialization
# ---------------------------------------------------------------------------


def _concurrent_decide_worker(target_str: str, append: str, hold_ms: int) -> None:
    """Helper: read target, sleep (to expose the race window), append, write
    back — all under the lock. Two of these racing must NOT lose appends."""
    from socrates120x import locked_read_modify_write as rmw
    target = Path(target_str)

    def mutate(current: str) -> str:
        # Sleep INSIDE the locked region; if locking is broken, two
        # processes both read the same pre-state and the second clobbers.
        time.sleep(hold_ms / 1000)
        return current + append

    rmw(target, mutate)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX fcntl-based locking; Windows path is a graceful no-op",
)
def test_locked_rmw_serializes_concurrent_writers_no_lost_updates(
    tmp_path: Path,
) -> None:
    """Spawn two processes that each read-modify-write the same file with
    a 300ms hold inside the locked region. Without the lock, the second
    writer would clobber the first (both saw the empty initial state).
    With the lock, both appends land — total content has BOTH markers."""
    target = tmp_path / "shared.txt"
    target.write_text("", encoding="utf-8")

    p1 = Process(
        target=_concurrent_decide_worker,
        args=(str(target), "A\n", 300),
    )
    p2 = Process(
        target=_concurrent_decide_worker,
        args=(str(target), "B\n", 300),
    )
    start = time.monotonic()
    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)
    elapsed = time.monotonic() - start

    assert p1.exitcode == 0, "worker 1 crashed"
    assert p2.exitcode == 0, "worker 2 crashed"

    final = target.read_text(encoding="utf-8")
    assert "A\n" in final, f"worker 1's update was lost: {final!r}"
    assert "B\n" in final, f"worker 2's update was lost: {final!r}"
    assert len(final.splitlines()) == 2, f"unexpected content: {final!r}"
    # Two 300ms holds with serialization should take >= 600ms total. If
    # locks didn't work the test would still pass on content (above), but
    # the timing sanity-checks that the lock actually blocked.
    assert elapsed >= 0.5, (
        f"elapsed {elapsed:.3f}s suggests the lock did NOT serialize; "
        "expected ~600ms when two 300ms holds are sequenced"
    )
