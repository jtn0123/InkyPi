"""Stand-ins for the systemd interfaces InkyPi depends on.

The device runs under systemd; development machines mostly do not, and macOS
never will. That gap is why the watchdog and the update/rollback paths were
previously only reasoned about rather than exercised.

Two of the three interfaces we depend on are simple enough to reproduce
faithfully rather than mock:

* **the notification socket** — ``sd_notify`` is a unix datagram sent to the
  path in ``$NOTIFY_SOCKET``. That is the whole protocol, so :class:`NotifySocket`
  plus :func:`sd_notify` here is not an approximation of systemd, it *is* the
  wire format. Only the C convenience wrapper (``cysystemd``, Linux-only) is
  missing.
* **systemctl** — a command-line surface, so :func:`install_fake_systemctl`
  puts a recording shim on ``PATH``. Scripts under test call it exactly as they
  would on the device.

What this deliberately does *not* simulate is systemd's own behaviour: unit
ordering, ``Restart=``, ``OnFailure=`` activation and cgroup limits. Those need
a real init, which is what ``tests/integration/test_install_crash_loop.py``
uses a privileged container for. Keep that boundary in mind when reading a
passing simulation test — see ``docs/simulation.md``.
"""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class NotifySocket:
    """A bound unix datagram socket standing in for systemd's listener.

    Non-blocking, so :meth:`drain` never stalls a test that is asserting the
    *absence* of notifications — which is the interesting case for the
    watchdog.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._sock.bind(str(path))
        self._sock.setblocking(False)
        self.received: list[str] = []

    def drain(self) -> list[str]:
        """Read everything queued and append it to :attr:`received`."""
        while True:
            try:
                data = self._sock.recv(4096)
            except BlockingIOError:
                break
            except OSError:
                break
            self.received.append(data.decode("utf-8", errors="replace"))
        return self.received

    def count(self, message: str) -> int:
        """How many *message* datagrams have arrived so far."""
        self.drain()
        return sum(1 for item in self.received if item == message)

    def close(self) -> None:
        try:
            self._sock.close()
        finally:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


def sd_notify(message: str) -> None:
    """Send *message* to ``$NOTIFY_SOCKET`` — the real protocol, in Python.

    This is what ``cysystemd.daemon.notify`` does natively; reimplementing the
    datagram here is what lets the watchdog be exercised off-Linux.
    """
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    # systemd also supports abstract sockets (a leading NUL), which are Linux
    # only. Path-based sockets work everywhere and are what we bind above.
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.sendto(message.encode("utf-8"), address)


@contextmanager
def systemd_notify_environment(
    tmp_path: Path, watchdog_usec: int
) -> Iterator[NotifySocket]:
    """Run a block as though under ``Type=notify`` with ``WatchdogSec=`` set.

    Args:
        tmp_path: Directory to place the socket in. Kept short — unix socket
            paths have a ~100 character limit and pytest tmpdirs are long.
        watchdog_usec: The value systemd would export; the app pings at half
            this interval.
    """
    # mkdtemp under the system temp root rather than tmp_path: pytest's nested
    # tmpdir names routinely exceed the sockaddr_un limit.
    short_dir = Path(tempfile.mkdtemp(prefix="inkynotify"))
    sock = NotifySocket(short_dir / "n.sock")
    previous = {
        "NOTIFY_SOCKET": os.environ.get("NOTIFY_SOCKET"),
        "WATCHDOG_USEC": os.environ.get("WATCHDOG_USEC"),
    }
    os.environ["NOTIFY_SOCKET"] = str(sock.path)
    os.environ["WATCHDOG_USEC"] = str(watchdog_usec)
    try:
        yield sock
    finally:
        sock.close()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            short_dir.rmdir()
        except OSError:
            pass


_FAKE_SYSTEMCTL = """#!/bin/bash
# Recording systemctl shim. Appends every invocation to $SYSTEMCTL_LOG and
# answers state queries from $SYSTEMCTL_STATE (default: active).
echo "$@" >> "$SYSTEMCTL_LOG"
state="$(cat "$SYSTEMCTL_STATE" 2>/dev/null || echo active)"
case "$1" in
  is-active)
    [ "$state" = "active" ] && exit 0 || exit 3
    ;;
  is-failed)
    [ "$state" = "failed" ] && exit 0 || exit 1
    ;;
  show)
    echo "ActiveState=$state"
    ;;
esac
exit 0
"""


def install_fake_systemctl(
    bin_dir: Path, log: Path, state_file: Path
) -> dict[str, str]:
    """Put a recording ``systemctl`` on ``PATH`` and return the env to use.

    Returns:
        Environment overlay to merge into a subprocess call: a ``PATH`` with
        *bin_dir* first, plus the log/state locations the shim reads.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "systemctl"
    script.write_text(_FAKE_SYSTEMCTL)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # update.sh calls `sudo systemctl ...`; a passthrough sudo keeps the real
    # scripts unmodified while running unprivileged.
    sudo = bin_dir / "sudo"
    # Skip sudo's own flags (-n, -E, ...) before exec'ing the command, so a
    # caller using `sudo -n journalctl` does not try to run `-n` as a program.
    sudo.write_text(
        "#!/bin/bash\n"
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in\n'
        "    -*) shift ;;\n"
        "    *) break ;;\n"
        "  esac\n"
        "done\n"
        'exec "$@"\n'
    )
    sudo.chmod(sudo.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    log.touch()
    if not state_file.exists():
        state_file.write_text("active")

    return {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "SYSTEMCTL_LOG": str(log),
        "SYSTEMCTL_STATE": str(state_file),
    }


def wait_until(predicate: Any, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Poll *predicate* until it is true or *timeout* elapses.

    Returns whether it became true. Polling rather than sleeping a fixed span
    keeps these tests fast without making them timing-fragile.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def run_bash(script: str, env: dict[str, str], timeout: int = 120) -> Any:
    """Run *script* under bash with *env* overlaid on the current environment."""
    merged = {**os.environ, **env}
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=merged,
        timeout=timeout,
    )
