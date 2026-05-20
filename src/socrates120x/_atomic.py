"""Small file I/O helpers shared across socrates modules.

Two recurring patterns motivate this module:

1. **Atomic writes.** ``Path.write_text`` opens, truncates, then writes.
   A SIGINT (or OOM, or power loss) anywhere between the truncate and
   the final byte leaves the file half-written. The next consumer
   (``json.loads`` on resume, the operator's next ``socrates decide``,
   etc.) sees corrupt content. ``atomic_write_text`` writes to a
   same-directory ``<name>.tmp`` then ``os.replace`` onto the final
   path — POSIX rename is atomic, and ``os.replace`` is atomic on
   Windows too since Python 3.3.

2. **Exclusive read-modify-write.** Several subcommands
   (``socrates decide``, ``socrates journal``) read a file, mutate
   its content, and write it back. If two processes do this at the
   same time, the second writer clobbers the first — data loss with
   no error. ``locked_read_modify_write`` wraps the pattern with an
   advisory ``fcntl.flock`` (POSIX only) so concurrent invocations
   serialize. On platforms without ``fcntl`` (Windows) the lock
   silently no-ops — matching the prior, unlocked behavior, so this
   is never a regression — but the atomic-write half still applies.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from pathlib import Path

__all__ = ["atomic_write_text", "locked_read_modify_write"]


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically.

    Writes to a same-directory ``<name>.tmp`` then ``os.replace`` onto
    the final path. The tempfile lives in the same directory so the
    rename is always within the same filesystem (i.e. always atomic).
    Cleans up the tempfile on both the happy path and the exception
    path so we never leave a stranded ``.tmp`` for the next run to
    wonder about.

    Encoding defaults to UTF-8 to match the project-wide
    locale-independence policy.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def locked_read_modify_write(
    path: Path,
    mutate: Callable[[str], str],
    *,
    encoding: str = "utf-8",
) -> None:
    """Exclusive read-modify-write on *path*, atomic on write.

    ``mutate`` is called with the file's current text; its return value
    gets written back via :func:`atomic_write_text`.

    Lock strategy. We can NOT lock *path* directly: atomic_write_text
    renames a tempfile onto *path*, which orphans the old inode and the
    flock with it. A second worker would acquire the (now-stale)
    old-inode lock and read pre-rename content, producing a silent
    lost-update — the exact bug we're trying to prevent.

    Instead we lock a sibling ``.<name>.lock`` file whose inode is
    stable across renames. Both workers ``open(lockfile, O_CREAT)`` and
    ``flock(LOCK_EX)`` on it; the second blocks until the first releases.
    The lock is held for the ENTIRE read → mutate → atomic-write cycle,
    so the second worker always reads what the first one wrote.

    Non-POSIX: ``fcntl`` is unavailable; the lock silently no-ops,
    matching the pre-fix unlocked behavior — no regression. The atomic
    write half still applies, so a mid-write SIGINT doesn't corrupt
    *path* even without serialization.

    *path* must exist; the caller's existence check + actionable error
    is much better UX than a stat error from inside the lock attempt.
    """
    if not path.is_file():
        raise FileNotFoundError(path)

    lock_path = path.with_name("." + path.name + ".lock")
    # O_CREAT so the first invocation can create it; subsequent runs
    # open the same inode and the lock contends naturally.
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _flock_exclusive_or_noop_fd(lock_fd)
        try:
            # Read AFTER acquiring the lock — if a previous holder just
            # released, we want the content they wrote, not whatever
            # was there when we started waiting.
            current = path.read_text(encoding=encoding)
            new_text = mutate(current)
            atomic_write_text(path, new_text, encoding=encoding)
        finally:
            _flock_release_or_noop_fd(lock_fd)
    finally:
        os.close(lock_fd)


# ---------------------------------------------------------------------------
# POSIX flock — silently no-ops where unavailable. Module-private.
# Operate on raw file descriptors so we can avoid keeping a Python file
# object alive around the locked region (cleaner cleanup).
# ---------------------------------------------------------------------------


def _flock_exclusive_or_noop_fd(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover — Windows / embedded Pythons
        return
    fcntl.flock(fd, fcntl.LOCK_EX)


def _flock_release_or_noop_fd(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover
        return
    fcntl.flock(fd, fcntl.LOCK_UN)
