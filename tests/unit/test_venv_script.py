"""scripts/venv.sh builds the dev venv with the supported Python, from any shell.

The interpreters here are stub scripts on an isolated PATH, so the tests
never build a real venv or depend on which Pythons the machine has.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VENV_SH = ROOT / "scripts/venv.sh"


def _supported_version() -> str:
    match = re.search(r'^INKYPI_PYTHON_VERSION="([0-9.]+)"$', VENV_SH.read_text(), re.M)
    assert match, "INKYPI_PYTHON_VERSION not found in scripts/venv.sh"
    return match.group(1)


def _write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _fake_python(path: Path, *, supported: bool, log: Path) -> None:
    """A python that answers the version check and can 'create' a venv.

    The venv it makes holds an activate script and a python3 that passes the
    version check and the dev_environment.py call, which is all venv.sh needs.
    """
    venv_python = (
        '#!/bin/bash\n[ "$1" = -c ] && exit 0\n'  # version check: supported
        'echo "dev_environment $*" >> "$INKYPI_TEST_LOG"\nexit 0\n'
    )
    _write_exe(
        path,
        f"""echo "$0 $*" >> "{log}"
if [ "$1" = -c ]; then exit {0 if supported else 1}; fi
if [ "$1" = -m ] && [ "$2" = venv ]; then
    /bin/mkdir -p "$3/bin"
    printf '%s' '{venv_python}' > "$3/bin/python3"
    /bin/chmod +x "$3/bin/python3"
    printf 'PATH="%s/bin:$PATH"\\n' "$3" > "$3/bin/activate"
    exit 0
fi
exit 1
""",
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """A repo copy holding only scripts/venv.sh, plus a PATH of stubs."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(VENV_SH, repo / "scripts/venv.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dirname = shutil.which("dirname")
    assert dirname
    (bin_dir / "dirname").symlink_to(dirname)
    log = tmp_path / "calls.log"
    log.touch()
    env = {
        "PATH": str(bin_dir),
        "HOME": str(tmp_path),
        "INKYPI_TEST_LOG": str(log),
    }
    return repo, bin_dir, env


def _run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(repo / "scripts/venv.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_refuses_to_build_a_venv_without_the_supported_python(
    sandbox: tuple[Path, Path, dict[str, str]],
) -> None:
    repo, bin_dir, env = sandbox
    log = Path(env["INKYPI_TEST_LOG"])
    _fake_python(bin_dir / "python3", supported=False, log=log)

    result = _run(repo, env)

    assert result.returncode == 1
    assert f"InkyPi needs Python {_supported_version()}" in result.stderr
    assert not (repo / ".venv").exists()


def test_prefers_the_versioned_interpreter_over_a_newer_python3(
    sandbox: tuple[Path, Path, dict[str, str]],
) -> None:
    repo, bin_dir, env = sandbox
    log = Path(env["INKYPI_TEST_LOG"])
    version = _supported_version()
    _fake_python(bin_dir / "python3", supported=False, log=log)
    _fake_python(bin_dir / f"python{version}", supported=True, log=log)

    result = _run(repo, env)

    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert f"python{version} -m venv {repo / '.venv'}" in calls
    assert "python3 -m venv" not in calls
    assert "dev_environment" in calls


def test_refuses_an_existing_venv_on_another_python(
    sandbox: tuple[Path, Path, dict[str, str]],
) -> None:
    repo, _, env = sandbox
    venv_bin = repo / ".venv/bin"
    venv_bin.mkdir(parents=True)
    _write_exe(venv_bin / "python3", 'echo "Python 3.15.2"; exit 1\n')
    (venv_bin / "activate").write_text(f'PATH="{venv_bin}:$PATH"\n')

    result = _run(repo, env)

    assert result.returncode == 1
    assert f"needs Python {_supported_version()}" in result.stderr
    assert "rm -rf" in result.stderr
    assert "dev_environment" not in Path(env["INKYPI_TEST_LOG"]).read_text()


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_sourcing_sets_pythonpath_from_any_shell(shell: str, tmp_path: Path) -> None:
    """zsh has no BASH_SOURCE; the repo root used to resolve one level up."""
    shell_path = shutil.which(shell)
    if shell_path is None:
        pytest.skip(f"{shell} is not installed")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["INKYPI_PYTHONPATH_ONLY"] = "1"
    flags = ["-f"] if shell == "zsh" else ["--noprofile", "--norc"]
    result = subprocess.run(
        [shell_path, *flags, "-c", f'source "{VENV_SH}"; echo "$PYTHONPATH"'],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().split(os.pathsep) == [str(ROOT), str(ROOT / "src")]


def _main_checkout(
    tmp_path: Path, bin_dir: Path, *, stamp_rc: int, check_rc: int = 0
) -> Path:
    """A main checkout whose venv answers dev_environment.py as told.

    A stub git reports it as the repo's common dir, as `git worktree` does.
    """
    main = tmp_path / "main"
    venv_bin = main / ".venv/bin"
    venv_bin.mkdir(parents=True)
    _write_exe(
        venv_bin / "python3",
        f"""echo "main-python $*" >> "$INKYPI_TEST_LOG"
[ "$1" = -c ] && exit 0
case " $* " in
    *" --require-stamp "*) exit {stamp_rc} ;;
    *" --sync "*) exit 0 ;;
esac
exit {check_rc}
""",
    )
    (venv_bin / "activate").write_text(f'PATH="{venv_bin}:$PATH"\n')
    _write_exe(bin_dir / "git", f'echo "{main}/.git"\n')
    return main


def test_a_worktree_shares_the_main_checkouts_matching_venv(
    sandbox: tuple[Path, Path, dict[str, str]], tmp_path: Path
) -> None:
    repo, bin_dir, env = sandbox
    main = _main_checkout(tmp_path, bin_dir, stamp_rc=0)

    result = _run(repo, env)

    assert result.returncode == 0, result.stderr
    assert f"Using the main checkout's virtual environment ({main}/.venv)" in (
        result.stdout
    )
    calls = Path(env["INKYPI_TEST_LOG"]).read_text()
    # The main venv vouches for *this* worktree's lock, not its own.
    assert f"main-python {repo}/scripts/dev_environment.py --require-stamp" in calls
    assert "-m venv" not in calls and "--sync" not in calls
    assert not (repo / ".venv").exists()


def test_a_worktree_builds_its_own_venv_when_the_main_one_differs(
    sandbox: tuple[Path, Path, dict[str, str]], tmp_path: Path
) -> None:
    repo, bin_dir, env = sandbox
    log = Path(env["INKYPI_TEST_LOG"])
    _main_checkout(tmp_path, bin_dir, stamp_rc=1)
    _fake_python(bin_dir / "python3", supported=True, log=log)

    result = _run(repo, env)

    assert result.returncode == 0, result.stderr
    assert "Using the main checkout's" not in result.stdout
    assert f"python3 -m venv {repo / '.venv'}" in log.read_text()


def test_own_venv_opt_out_skips_the_main_checkout(
    sandbox: tuple[Path, Path, dict[str, str]], tmp_path: Path
) -> None:
    repo, bin_dir, env = sandbox
    log = Path(env["INKYPI_TEST_LOG"])
    _main_checkout(tmp_path, bin_dir, stamp_rc=0)
    _fake_python(bin_dir / "python3", supported=True, log=log)

    result = _run(repo, {**env, "INKYPI_OWN_VENV": "1"})

    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "--require-stamp" not in calls
    assert f"python3 -m venv {repo / '.venv'}" in calls


def test_a_shared_venv_is_never_synced_from_the_worktree(
    sandbox: tuple[Path, Path, dict[str, str]], tmp_path: Path
) -> None:
    repo, bin_dir, env = sandbox
    # Matched a moment ago, drifted by the time of the full check.
    _main_checkout(tmp_path, bin_dir, stamp_rc=0, check_rc=1)

    result = _run(repo, env)

    assert result.returncode == 1
    assert "left alone" in result.stderr
    assert "INKYPI_OWN_VENV=1" in result.stderr
    assert "--sync" not in Path(env["INKYPI_TEST_LOG"]).read_text()


def test_the_main_checkout_never_shares_with_itself(
    sandbox: tuple[Path, Path, dict[str, str]],
) -> None:
    repo, bin_dir, env = sandbox
    log = Path(env["INKYPI_TEST_LOG"])
    _write_exe(bin_dir / "git", f'echo "{repo}/.git"\n')
    _fake_python(bin_dir / "python3", supported=True, log=log)

    result = _run(repo, env)

    assert result.returncode == 0, result.stderr
    assert f"python3 -m venv {repo / '.venv'}" in log.read_text()
