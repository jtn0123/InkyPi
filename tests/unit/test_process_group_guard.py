"""The suite refuses signals aimed at its own process group.

On CI the test run shares a process group with the GitHub runner, so a test
that signalled group 0 killed the runner and the job lost its log. These
checks use signal 0 and SIGCONT, which are harmless even if the guard from
``tests/conftest.py`` were missing.
"""

import os
import signal

import pytest


def test_killpg_on_group_zero_is_refused() -> None:
    with pytest.raises(RuntimeError, match="own group"):
        os.killpg(0, 0)


def test_killpg_on_the_runs_own_group_is_refused() -> None:
    with pytest.raises(RuntimeError, match="own group"):
        os.killpg(os.getpgid(0), 0)


def test_kill_with_a_group_pid_is_refused() -> None:
    with pytest.raises(RuntimeError, match="whole group"):
        os.kill(0, signal.SIGCONT)


def test_probing_a_real_pid_still_works() -> None:
    os.kill(os.getpid(), 0)
