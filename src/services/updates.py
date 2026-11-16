"""Update and rollback runner for the settings page.

Finds and validates the install scripts, launches them in a transient systemd
unit (or a simulated fallback thread off-device), and owns the update state:
whether a run is going, which unit it is, when it ends, and whether a
rollback may start. The routes in ``blueprints/settings/_updates.py`` only
parse requests and map the results here to responses:

* ``start_update`` / ``start_rollback`` check, claim and launch a run, and
  return a ``LaunchResult`` (started, or refused with a reason);
* ``status`` reports the run, the last failure and rollback eligibility;
* ``is_running`` and ``current_unit`` serve the version and logs routes.

Tests patch names here (``services.updates.<name>``), so every function looks
its collaborators up on this module at call time.
"""

import datetime as _dt
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from utils.json_types import JsonObject
from utils.progress_events import get_progress_bus

logger = logging.getLogger(__name__)

UpdateKind = Literal["update", "rollback"]

UPDATE_SCRIPT_NAMES = ("do_update.sh", "update.sh")
# JTN-708: rollback.sh reverts to the tag recorded in /var/lib/inkypi/prev_version.
# It's gated separately from the forward-update path because rollback.sh only
# runs after a failed update (guard enforced at the Flask route level) and
# delegates to update.sh internally.
ROLLBACK_SCRIPT_NAME = "rollback.sh"

# Strict allow-lists for systemd-run command construction (JTN-319).
# CodeQL py/command-line-injection flagged _start_update_via_systemd because
# the validation was not visible to static analysis. The regexes below make
# the validation explicit so both CodeQL and human reviewers can see it.
#
# Script basenames that are allowed to be executed by _start_update_via_systemd.
# The full path is additionally required to be an absolute, canonicalised
# (realpath-resolved) path that lives under one of the trusted install roots
# below — see _validate_update_script_path. Inline ``re.fullmatch`` guards at
# every Popen call site are intentionally not pre-compiled so CodeQL can
# constant-fold them for sanitiser recognition.
_ALLOWED_UPDATE_SCRIPT_BASENAMES = frozenset(UPDATE_SCRIPT_NAMES)
# JTN-708: the rollback script is validated through the same trusted-root /
# basename allow-list machinery as do_update.sh / update.sh.  Keeping a
# dedicated frozenset (rather than adding rollback.sh to
# _ALLOWED_UPDATE_SCRIPT_BASENAMES) means an accidental call to
# _start_update_via_systemd cannot resolve to rollback.sh and vice-versa.
_ALLOWED_ROLLBACK_SCRIPT_BASENAMES = frozenset((ROLLBACK_SCRIPT_NAME,))

# Trusted install roots for update scripts. The realpath of any script we are
# willing to exec via subprocess.Popen MUST be inside one of these directories.
# Repo-relative developer environments are added at runtime via
# ``_trusted_update_dirs()`` so this constant remains a hardcoded literal.
_TRUSTED_UPDATE_DIRS: tuple[str, ...] = (
    "/usr/local/inkypi/install",
    "/opt/inkypi/install",
)

# Hardcoded literal prefix for the transient systemd unit. The dynamic suffix
# is appended in-function from a Python int (time.time()) so the final string
# is provably not user-influenced.
_UPDATE_UNIT_PREFIX = "inkypi-update"
# JTN-708: distinct prefix for rollback transient units so operators (and the
# status endpoint) can distinguish a rollback from a forward update via
# ``systemctl list-units 'inkypi-rollback-*'``.
_ROLLBACK_UNIT_PREFIX = "inkypi-rollback"

# S1192: the canonical PROJECT_DIR + bash interpreter are referenced from
# multiple Popen call sites (_start_update_via_systemd / _start_rollback_via_systemd
# / _get_*_script_path fallbacks), so pull them to module-level constants.
_DEFAULT_PROJECT_DIR = "/usr/local/inkypi"
_BASH_INTERPRETER = "/bin/bash"
_UPDATE_TARGET_VERSION_FILENAME = "update-target-version"

# Strict semver pattern for update target tags (e.g. "v1.2.3", "1.0.0-rc1").
# IMPORTANT: this MUST stay byte-for-byte equivalent to the bash regex used in
# install/do_update.sh — both validators only accept ``v?\d+\.\d+\.\d+`` with
# an optional ``-[A-Za-z0-9.]+`` suffix (no underscores; \w in Python would
# diverge from POSIX bracket classes). ``re.ASCII`` keeps ``\d`` limited to
# ``[0-9]`` so Unicode digit spoofing (e.g. Arabic-Indic numerals) cannot
# smuggle a value past the validator.
_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$", re.ASCII)


# In-memory update state for coordinating UI status and logs. Only the
# functions in this module write it, always under ``_update_lock``.
_UPDATE_STATE: dict[str, object] = {
    "running": False,
    "unit": None,
    "started_at": None,  # epoch seconds
    "last_unit": None,  # preserved after update completes for log retrieval
    "kind": None,  # "update" or "rollback" while a run is going
}

_UPDATE_TIMEOUT_SECONDS = 1800  # 30 minutes
_update_lock = threading.Lock()

# A run's transient unit, as _start_update_via_systemd and
# _start_rollback_via_systemd name it: prefix, launch time, ".service".
_RUN_UNIT_RE = re.compile(r"inkypi-(update|rollback)-(\d{1,12})\.service", re.ASCII)

# Breadcrumbs the install scripts leave in the state directory.
_DEFAULT_STATE_DIR = "/var/lib/inkypi"
_FAILURE_FILENAME = ".last-update-failure"
_PREV_VERSION_FILENAME = "prev_version"
# Cap how much of the failure record is ever returned to a browser so a
# runaway journal capture can't blow up the response body.
_MAX_FAILURE_BYTES = 64 * 1024


def _get_update_script_path() -> str | None:
    """Return absolute path to the best update script available on this host.

    Looks for ``do_update.sh`` first (git pull + deps), then ``update.sh`` (deps only).

    Priorities:
    1. Follow the ``$PROJECT_DIR/src`` symlink back to the repo for ``install/do_update.sh``
    2. ``$PROJECT_DIR/install/do_update.sh``
    3. Repo-relative ``../../install/do_update.sh`` (developer environment)
    4. Same cascade for ``update.sh`` as fallback
    """
    candidates: list[str] = []
    project_dir = os.getenv("PROJECT_DIR")

    def add_install_candidates(base_dir: str) -> None:
        install_dir = os.path.join(base_dir, "install")
        candidates.extend(
            [
                os.path.join(install_dir, script_name)
                for script_name in UPDATE_SCRIPT_NAMES
            ]
        )

    # Resolve the real repo root by following the src symlink (production layout)
    if project_dir:
        src_link = os.path.join(project_dir, "src")
        if os.path.islink(src_link):
            repo_root = os.path.dirname(os.path.realpath(src_link))
            add_install_candidates(repo_root)
        # Direct PROJECT_DIR/install paths
        add_install_candidates(project_dir)

    # Repo-relative path (this file: src/services/updates.py → repo_root/install/)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_install = os.path.abspath(os.path.join(here, "..", "..", "install"))
    candidates.extend(
        [os.path.join(repo_install, script_name) for script_name in UPDATE_SCRIPT_NAMES]
    )

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _get_rollback_script_path() -> str | None:
    """Return absolute path to ``install/rollback.sh`` (JTN-708).

    Uses the same candidate cascade as ``_get_update_script_path`` so a
    developer running the Flask app from a repo checkout sees the in-repo
    rollback.sh, while a production install picks up the
    ``/usr/local/inkypi/install/rollback.sh`` copy.
    """
    candidates: list[str] = []
    project_dir = os.getenv("PROJECT_DIR")

    def add_install_candidate(base_dir: str) -> None:
        candidates.append(os.path.join(base_dir, "install", ROLLBACK_SCRIPT_NAME))

    if project_dir:
        src_link = os.path.join(project_dir, "src")
        if os.path.islink(src_link):
            repo_root = os.path.dirname(os.path.realpath(src_link))
            add_install_candidate(repo_root)
        add_install_candidate(project_dir)

    here = os.path.dirname(os.path.abspath(__file__))
    repo_install = os.path.abspath(os.path.join(here, "..", "..", "install"))
    candidates.append(os.path.join(repo_install, ROLLBACK_SCRIPT_NAME))

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _systemd_available() -> bool:
    try:
        return shutil.which("systemd-run") is not None
    except Exception:
        return False


def _kind_for_unit(unit: str | None) -> UpdateKind:
    if unit and unit.startswith(f"{_ROLLBACK_UNIT_PREFIX}-"):
        return "rollback"
    return "update"


def _clear_run_locked() -> None:
    """End the current run. The caller holds ``_update_lock``."""
    unit = _UPDATE_STATE.get("unit")
    if unit:
        _UPDATE_STATE["last_unit"] = unit
    _UPDATE_STATE["running"] = False
    _UPDATE_STATE["unit"] = None
    _UPDATE_STATE["started_at"] = None
    _UPDATE_STATE["kind"] = None


def _set_update_state(running: bool, unit: str | None) -> None:
    """Set the run state outright (the fallback runner's end, and tests)."""
    with _update_lock:
        if not running:
            _clear_run_locked()
            return
        _UPDATE_STATE["running"] = True
        _UPDATE_STATE["unit"] = unit
        _UPDATE_STATE["started_at"] = float(time.time())
        _UPDATE_STATE["kind"] = _kind_for_unit(unit)


# ---------------------------------------------------------------------------
# Run ownership: one run at a time, and only its owner ends it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunTicket:
    """Proof that one caller began the current run.

    ``finish`` and ``_record_unit`` act only while the state still holds this
    run, so a request that fails after claiming the run can undo its own
    claim without ever touching a run someone else started.
    """

    kind: UpdateKind
    started_at: float


def try_begin(kind: UpdateKind) -> RunTicket | None:
    """Claim the run for ``kind``, or return None when one is already going.

    The check and the claim happen under one lock acquisition, so two
    concurrent requests can't both pass.
    """
    with _update_lock:
        if _UPDATE_STATE.get("running"):
            return None
        started_at = float(time.time())
        _UPDATE_STATE["running"] = True
        _UPDATE_STATE["unit"] = None
        _UPDATE_STATE["started_at"] = started_at
        _UPDATE_STATE["kind"] = kind
        return RunTicket(kind=kind, started_at=started_at)


def _owns_run_locked(ticket: RunTicket) -> bool:
    return bool(_UPDATE_STATE.get("running")) and (
        _UPDATE_STATE.get("started_at") == ticket.started_at
    )


def _record_unit(ticket: RunTicket, unit: str) -> None:
    with _update_lock:
        if _owns_run_locked(ticket):
            _UPDATE_STATE["unit"] = unit


def finish(ticket: RunTicket) -> bool:
    """End the run ``ticket`` began. Returns False, changing nothing, when the
    state now belongs to another run (or to none)."""
    with _update_lock:
        if not _owns_run_locked(ticket):
            return False
        _clear_run_locked()
        return True


def is_running() -> bool:
    return bool(_UPDATE_STATE.get("running"))


def current_unit() -> str | None:
    """The transient unit of the run going now, if it has one."""
    unit = _UPDATE_STATE.get("unit")
    return unit if isinstance(unit, str) and unit else None


# ---------------------------------------------------------------------------
# JTN-319: command-line-injection sanitisers.
#
# CodeQL's py/command-line-injection taint tracker does not propagate sanitiser
# recognition across helper boundaries — the regex guard MUST be visible in
# the same function that calls subprocess.Popen.  We therefore:
#
#   1. Drop ``unit_name``/``script_path`` parameters from
#      ``_start_update_via_systemd`` entirely.  The unit name is built from a
#      hardcoded literal prefix plus a Python int, and the script path is
#      resolved internally via ``_get_update_script_path`` (which itself only
#      walks a fixed candidate list under PROJECT_DIR).
#   2. Validate the resolved script path against a hardcoded list of trusted
#      install roots via ``os.path.realpath`` so symlinks/path-traversal can
#      not escape the allow-list.
#   3. The only parameter that survives is ``target_tag``, and it is matched
#      against ``_TAG_RE`` inline immediately above the Popen call so CodeQL
#      sees the regex sanitiser in the same frame.
# ---------------------------------------------------------------------------


def _trusted_update_dirs() -> tuple[str, ...]:
    """Return the canonical list of directories whose update scripts are exec-allowed.

    The hardcoded ``_TRUSTED_UPDATE_DIRS`` constants are joined with the
    repo-relative ``install/`` directory (developer environments) and the
    realpath of ``$PROJECT_DIR/install`` if PROJECT_DIR is set.  All entries
    are passed through ``os.path.realpath`` so the comparison in
    ``_validate_update_script_path`` is symlink-safe.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    repo_install = os.path.abspath(os.path.join(here, "..", "..", "install"))
    dirs = list(_TRUSTED_UPDATE_DIRS) + [repo_install]
    project_dir = os.getenv("PROJECT_DIR")
    if project_dir and project_dir.startswith("/"):
        dirs.append(os.path.join(project_dir, "install"))
        # Follow the src→repo symlink production install layout uses.
        src_link = os.path.join(project_dir, "src")
        if os.path.islink(src_link):
            try:
                repo_root = os.path.dirname(os.path.realpath(src_link))
                dirs.append(os.path.join(repo_root, "install"))
            except OSError:
                pass
    return tuple(os.path.realpath(d) for d in dirs)


def _validate_update_script_path(script_path: str) -> str:
    """Resolve and validate an update script path against trusted install roots.

    Returns the canonical (realpath-resolved) path on success.  Raises
    ``ValueError`` if the path is empty, has a disallowed
    basename, or — after symlink resolution — does not live under one of
    the trusted install directories from ``_trusted_update_dirs``.
    """
    if not script_path:
        raise ValueError(f"Invalid update script path: {script_path!r}")
    real = os.path.realpath(script_path)
    # Symlink-safe trusted-root enforcement: ``commonpath`` is the canonical
    # primitive for "is X under directory Y" without TOCTOU prefix-string
    # tricks.  Both arguments are absolute realpaths so commonpath cannot
    # raise on differing drives (POSIX-only project).
    trusted = _trusted_update_dirs()
    in_trusted_root = False
    for root in trusted:
        try:
            if os.path.commonpath([real, root]) == root:
                in_trusted_root = True
                break
        except ValueError:
            # Different filesystem roots; not a match.
            continue
    if not in_trusted_root:
        raise ValueError(
            f"Invalid update script path (not under trusted root): {script_path!r}"
        )
    if os.path.basename(real) not in _ALLOWED_UPDATE_SCRIPT_BASENAMES:
        raise ValueError(f"Invalid update script basename: {script_path!r}")
    return real


def _validate_target_tag_arg(target_tag: str | None) -> str | None:
    if target_tag is None:
        return None
    if not target_tag:
        raise ValueError(f"Invalid target tag format: {target_tag!r}")

    version = target_tag[1:] if target_tag.startswith("v") else target_tag
    core, separator, suffix = version.partition("-")
    parts = core.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Invalid target tag format: {target_tag!r}")
    if separator and (
        not suffix or any(not (ch.isalnum() or ch == ".") for ch in suffix)
    ):
        raise ValueError(f"Invalid target tag format: {target_tag!r}")
    return target_tag


def _update_target_version_path() -> str:
    base = os.environ.get("INKYPI_LOCKFILE_DIR") or "/var/lib/inkypi"
    return os.path.join(base, _UPDATE_TARGET_VERSION_FILENAME)


def _write_update_target_version(target_tag: str | None) -> None:
    path = _update_target_version_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if target_tag is None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"{target_tag}\n")


def _start_update_via_systemd(target_tag: str | None = None) -> str:
    """Launch the update script in a transient systemd unit.

    Returns the ``inkypi-update-<ts>`` unit name actually passed to
    systemd-run so the caller can record the real value in
    ``_UPDATE_STATE["unit"]`` — previously the caller generated its own
    ``int(time.time())`` unit breadcrumb and the two could differ by a
    second, causing the reaper's ``systemctl is-active`` probe to query
    a non-existent unit.

    Security (JTN-319 / CodeQL py/command-line-injection):
        All argv elements passed to ``subprocess.Popen`` are either string
        literals, values derived from hardcoded constants, or — for
        ``target_tag`` — matched against the strict ``_TAG_RE`` semver regex
        in the same function frame so CodeQL's built-in regex sanitiser
        recognition can see the guard.
    """
    sanitized_target_tag = _validate_target_tag_arg(target_tag)
    _write_update_target_version(sanitized_target_tag)

    # 2. Resolve PROJECT_DIR from a hardcoded default and validate it has the
    #    shape of an absolute POSIX path.  Anything user-controlled (env var)
    #    falls back to the literal default.
    project_dir = os.getenv("PROJECT_DIR", "/usr/local/inkypi")
    project_dir_match = re.fullmatch(r"^/[A-Za-z0-9_./-]{1,255}$", project_dir)
    if project_dir_match is None or ".." in project_dir.split("/"):
        project_dir = "/usr/local/inkypi"
    else:
        project_dir = project_dir_match.group(0)

    # 3. Resolve the script path purely from internal candidates (the helper
    #    walks a fixed list under PROJECT_DIR / repo-relative install/) and
    #    re-validate against the trusted-root allow-list.  No caller can
    #    influence this string.
    candidate = _get_update_script_path() or "/usr/local/inkypi/install/do_update.sh"
    script_path = _validate_update_script_path(candidate)

    # 4. Build the unit name from a hardcoded literal prefix + a fresh int.
    unit_name = f"{_UPDATE_UNIT_PREFIX}-{int(time.time())}"

    # 5. E10: do_update.sh refuses an origin other than the repo the version
    #    check reads releases from (services.version_check). Pass an
    #    INKYPI_GITHUB_REPO override through, so a device that follows another
    #    fork on purpose can still update. Only an owner/name value is passed.
    repo_env: list[str] = []
    repo_match = re.fullmatch(
        r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}",
        os.getenv("INKYPI_GITHUB_REPO", ""),
    )
    if repo_match is not None:
        repo_env.append(f"--setenv=INKYPI_GITHUB_REPO={repo_match.group(0)}")

    cmd: list[str] = [
        "systemd-run",
        "--collect",
        f"--unit={unit_name}",
        "--property=StandardOutput=journal",
        "--property=StandardError=journal",
        f"--setenv=PROJECT_DIR={project_dir}",
        *repo_env,
        "/bin/bash",
        script_path,
    ]
    # All argv elements above are literals or trusted paths. The optional target
    # tag is passed via a fixed breadcrumb file read by do_update.sh.
    subprocess.Popen(cmd)
    return f"{unit_name}.service"


def _validate_rollback_script_path(script_path: str) -> str:
    """JTN-708 — mirror ``_validate_update_script_path`` for rollback.sh.

    Same trusted-root machinery as the update-script validator; the only
    difference is the allowed basename, so a mis-wired caller cannot exec
    do_update.sh through the rollback path or vice-versa.
    """
    if not script_path:
        raise ValueError(f"Invalid rollback script path: {script_path!r}")
    real = os.path.realpath(script_path)
    trusted = _trusted_update_dirs()
    in_trusted_root = False
    for root in trusted:
        try:
            if os.path.commonpath([real, root]) == root:
                in_trusted_root = True
                break
        except ValueError:
            continue
    if not in_trusted_root:
        raise ValueError(
            f"Invalid rollback script path (not under trusted root): {script_path!r}"
        )
    if os.path.basename(real) not in _ALLOWED_ROLLBACK_SCRIPT_BASENAMES:
        raise ValueError(f"Invalid rollback script basename: {script_path!r}")
    return real


def _start_rollback_via_systemd() -> str:
    """Launch rollback.sh in a transient systemd unit (JTN-708).

    Returns the ``inkypi-rollback-<ts>.service`` unit name so callers can
    record the real value in ``_UPDATE_STATE["unit"]`` instead of a
    separately-generated breadcrumb (same fix as _start_update_via_systemd).

    Security posture mirrors ``_start_update_via_systemd``:
        * No caller-controlled values flow into argv — the script path is
          resolved internally via ``_get_rollback_script_path`` and then
          canonicalised + trusted-root-checked via
          ``_validate_rollback_script_path``.
        * The transient unit name is a hardcoded literal prefix plus a fresh
          ``int(time.time())`` so CodeQL can statically prove the value is not
          user-influenced.
        * PROJECT_DIR defaults to the hardcoded ``/usr/local/inkypi``; any
          environment override is re-validated against a strict absolute-POSIX
          path regex before being passed through.
    """
    project_dir = os.getenv("PROJECT_DIR", _DEFAULT_PROJECT_DIR)
    if not re.fullmatch(r"^/[A-Za-z0-9_./-]{1,255}$", project_dir) or (
        ".." in project_dir.split("/")
    ):
        project_dir = _DEFAULT_PROJECT_DIR

    candidate = (
        _get_rollback_script_path()
        or f"{_DEFAULT_PROJECT_DIR}/install/{ROLLBACK_SCRIPT_NAME}"
    )
    script_path = _validate_rollback_script_path(candidate)

    unit_name = f"{_ROLLBACK_UNIT_PREFIX}-{int(time.time())}"

    cmd: list[str] = [
        "systemd-run",
        "--collect",
        f"--unit={unit_name}",
        "--property=StandardOutput=journal",
        "--property=StandardError=journal",
        f"--setenv=PROJECT_DIR={project_dir}",
        _BASH_INTERPRETER,
        script_path,
    ]
    # All argv elements above are string literals or validated internal values.
    subprocess.Popen(cmd)  # all inputs sanitized; shell=False
    return f"{unit_name}.service"


def _log_and_publish(msg: str, level: str = "info") -> None:
    """Log and publish update progress to the SSE bus."""
    getattr(logger, level)("update | %s", msg)
    try:
        bus = get_progress_bus()
        bus.publish({"type": "update_log", "line": msg})
    except Exception:
        pass


def _run_real_update(script_path: str, target_tag: str | None = None) -> None:
    sanitized_target_tag = _validate_target_tag_arg(target_tag)
    # ``_validate_update_script_path`` returns the canonicalised realpath; the
    # original (possibly symlinked) input is dropped so the value flowing into
    # Popen is provably under a trusted install root.
    script_path = _validate_update_script_path(script_path)

    cmd: list[str] = ["/bin/bash", script_path]
    if sanitized_target_tag is not None:
        cmd.append(sanitized_target_tag)
    proc = subprocess.Popen(  # shell=False; trusted path/validated tag.
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    for line in proc.stdout or []:
        _log_and_publish(line.rstrip())
    proc.wait()
    rc = proc.returncode if proc.returncode is not None else 0
    if rc == 0:
        _log_and_publish("web_update: completed successfully")
    else:
        _log_and_publish(f"web_update: failed with return code {rc}", "error")


def _run_simulated_update(target_tag: str | None = None) -> None:
    messages = ["Simulated update starting..."]
    if target_tag:
        messages.append(f"Requested target version: {target_tag}")
    messages.extend(
        [
            "Checking connectivity...",
            "Fetching latest dependencies...",
            "Updating application files...",
            "Restarting service...",
            "Update completed.",
        ]
    )
    for msg in messages:
        _log_and_publish(msg)
        time.sleep(0.5)


def _update_runner(script_path: str | None, target_tag: str | None = None) -> None:
    try:
        _log_and_publish("web_update: starting")
        if (
            script_path
            and os.path.isfile(script_path)
            and os.access(script_path, os.X_OK)
        ):
            # Do not run the real script unless explicitly enabled
            allow_real = os.getenv("INKYPI_ALLOW_REAL_UPDATE", "0").strip() in (
                "1",
                "true",
                "yes",
            )
            if allow_real:
                _run_real_update(script_path, target_tag=target_tag)
            else:
                _run_simulated_update(target_tag=target_tag)
        else:
            for i in range(6):
                _log_and_publish(f"step {i + 1}/6")
                time.sleep(0.5)
            if target_tag:
                _log_and_publish(f"Requested target version: {target_tag}")
            _log_and_publish("done (simulated)")
    except Exception:
        logger.exception("web_update: exception while running update")
    finally:
        _set_update_state(False, None)


def _start_update_fallback_thread(
    script_path: str | None, target_tag: str | None = None
) -> None:
    # Development/macOS path: run a simulated update and pipe output into our logger
    # to make it visible in inkypi.service logs and the UI viewer.
    t = threading.Thread(
        target=_update_runner,
        args=(script_path, target_tag),
        name="update-fallback",
        daemon=True,
    )
    t.start()


# ---------------------------------------------------------------------------
# Breadcrumbs the install scripts leave in the state directory
# ---------------------------------------------------------------------------


def _state_dir() -> Path:
    """The scripts' state directory; ``INKYPI_LOCKFILE_DIR`` redirects it in
    tests, as it does for the scripts themselves."""
    return Path(os.environ.get("INKYPI_LOCKFILE_DIR") or _DEFAULT_STATE_DIR)


def read_last_update_failure() -> JsonObject | None:
    """Return the ``.last-update-failure`` record the scripts' EXIT traps write.

    * ``None``: no record (no failure yet, or a later successful update
      removed it).
    * the parsed JSON object: keys are whatever the trap wrote
      (``timestamp``, ``exit_code``, ``last_command``,
      ``recent_journal_lines``); partial records are returned as they are.
    * ``{"parse_error": True}``: the file exists but can't be read or parsed,
      so callers still see that the last update failed.
    """
    path = _state_dir() / _FAILURE_FILENAME
    try:
        if not path.is_file():
            return None
    except OSError:
        # e.g. permission denied on the parent dir: treat as "no record"
        # rather than show an error banner for an unreadable state dir.
        logger.debug("Could not stat %s", path, exc_info=True)
        return None

    try:
        raw = path.read_bytes()
    except OSError:
        logger.warning("Failed to read %s", path, exc_info=True)
        return {"parse_error": True}

    if len(raw) > _MAX_FAILURE_BYTES:
        raw = raw[:_MAX_FAILURE_BYTES]

    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        logger.warning("Malformed JSON in %s", path)
        return {"parse_error": True}

    if not isinstance(data, dict):
        logger.warning("Unexpected JSON shape in %s: %r", path, type(data).__name__)
        return {"parse_error": True}

    return data


def read_prev_version() -> str | None:
    """Return the tag do_update.sh recorded in ``prev_version``, or None.

    A record that fails the strict semver check counts as missing, so a
    corrupt breadcrumb hides the Roll back button instead of offering an
    unusable target.
    """
    try:
        raw = (_state_dir() / _PREV_VERSION_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return None
    tag = raw.strip()
    if not tag or not _TAG_RE.fullmatch(tag):
        return None
    return tag


# ---------------------------------------------------------------------------
# Rollback eligibility: one rule for the Roll back button and the route
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Refusal:
    """Why a run can't start. ``code`` is the stable reason clients read."""

    code: str
    message: str


ALREADY_RUNNING = "already_running"


def rollback_eligibility(
    last_failure: Mapping[str, object] | None, prev_version: str | None
) -> Refusal | None:
    """Return why a rollback can't start, or None when it can.

    * A ``.last-update-failure`` record must exist. A rollback is a recovery
      path, not a time machine; to move a healthy install, update to a
      chosen version instead. A failure synthesized from the journal has no
      record, so it doesn't count.
    * The failure must not be a pre-flight abort: those stop before anything
      is checked out, so the device is still on the version it was on.
    * ``prev_version`` must hold a valid tag to go back to.
    """
    if not last_failure:
        return Refusal("no_failure", "No failed update recorded; nothing to roll back.")
    step = last_failure.get("last_command")
    if isinstance(step, str) and step.startswith("preflight:"):
        return Refusal(
            "preflight_abort",
            "The last update stopped in its pre-flight checks before changing "
            "anything, so there is nothing to roll back.",
        )
    if not prev_version:
        return Refusal(
            "no_prev_version", "No previous version recorded; cannot roll back."
        )
    return None


# ---------------------------------------------------------------------------
# Keeping the in-memory state in line with systemd
# ---------------------------------------------------------------------------


def _probe_finished_unit(unit: str) -> tuple[bool, bool]:
    """Return ``(finished, failed)`` for a run's transient unit.

    ``finished`` is True once the unit is in any state other than
    ``active``/``activating``; ``failed`` only when systemd says ``failed``
    (JTN-787 then synthesizes a failure record from the journal). Errors
    count as "still running": probing must never fail the status endpoint.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        state = result.stdout.strip()
        if state in ("active", "activating"):
            return (False, False)
        return (True, state == "failed")
    except Exception:
        return (False, False)


def _synthesize_failure_from_journal(unit: str) -> dict[str, object] | None:
    """JTN-787: build a failure record from ``journalctl -u <unit>``.

    Covers a unit that failed without writing ``.last-update-failure`` (for
    example an old do_update.sh that aborts before delegating to update.sh).
    The shape mirrors the trap's record plus ``synthesized: True``. Returns
    None when the journal has nothing or can't be read.
    """
    try:
        journal_result = subprocess.run(
            ["journalctl", "-u", unit, "-n", "20", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        logger.debug("Failed to synthesize last_failure from journalctl", exc_info=True)
        return None
    journal_tail = (journal_result.stdout or "").strip()
    if not journal_tail:
        return None
    return {
        "timestamp": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exit_code": None,
        "last_command": "systemd_unit_failed",
        "recent_journal_lines": journal_tail,
        "unit": unit,
        "synthesized": True,
    }


def _compare_and_clear_update_state(unit: object, started_at: object) -> bool:
    """Clear the run iff ``(unit, started_at)`` still matches.

    Returns False when a concurrent start replaced the run since the caller
    took its snapshot, so the reaper leaves the new run alone (JTN-K3).
    """
    with _update_lock:
        if (
            _UPDATE_STATE.get("running")
            and _UPDATE_STATE.get("unit") == unit
            and _UPDATE_STATE.get("started_at") == started_at
        ):
            _clear_run_locked()
            return True
        return False


def _reap_finished_run() -> str | None:
    """End the recorded run when its unit has finished or it has timed out.

    Returns the unit's name only when the unit ended ``failed`` (for the
    journal fallback). The slow ``systemctl`` probe runs outside the lock,
    and the clear is compare-and-clear, so a run started meanwhile survives.
    """
    unit = _UPDATE_STATE.get("unit")
    started_at = _UPDATE_STATE.get("started_at")

    if isinstance(unit, str) and unit and _systemd_available():
        finished, failed = _probe_finished_unit(unit)
        if finished and _compare_and_clear_update_state(unit, started_at):
            return unit if failed else None

    # Timeout fallback: a run started more than 30 minutes ago is over.
    if (
        isinstance(started_at, (int, float, str))
        and (time.time() - float(started_at)) > _UPDATE_TIMEOUT_SECONDS
    ):
        _compare_and_clear_update_state(unit, started_at)
    return None


def _find_active_run_unit() -> tuple[str, float] | None:
    """Return the newest active update or rollback unit and its launch time.

    systemd keeps a run's transient unit going while this service restarts,
    which every real update does. Errors and unexpected output mean "none".
    """
    try:
        result = subprocess.run(
            [
                "systemctl",
                "list-units",
                "--type=service",
                "--state=active,activating",
                "--no-legend",
                "--plain",
                "--no-pager",
                f"{_UPDATE_UNIT_PREFIX}-*",
                f"{_ROLLBACK_UNIT_PREFIX}-*",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = str(result.stdout).splitlines()
    except Exception:
        logger.debug("Could not list update units", exc_info=True)
        return None
    newest: tuple[str, float] | None = None
    for line in lines:
        fields = line.split()
        match = _RUN_UNIT_RE.fullmatch(fields[0]) if fields else None
        if match is None:
            continue
        launched_at = float(match.group(2))
        if newest is None or launched_at > newest[1]:
            newest = (match.group(0), launched_at)
    return newest


def _adopt_running_unit() -> None:
    """Track a run this process didn't start, so status reports it running.

    An update stops this service and starts it again, then keeps checking
    the new build is serving; the restarted process has no memory of the
    run. Without this, status would say "not running" while update.sh is
    still working, and the page would report a result too early.
    """
    if not _systemd_available():
        return
    found = _find_active_run_unit()
    if found is None:
        return
    unit, launched_at = found
    if time.time() - launched_at > _UPDATE_TIMEOUT_SECONDS:
        # Past the reaper's timeout: adopting it would only be cleared again.
        return
    with _update_lock:
        if _UPDATE_STATE.get("running"):
            return
        _UPDATE_STATE["running"] = True
        _UPDATE_STATE["unit"] = unit
        _UPDATE_STATE["started_at"] = launched_at
        _UPDATE_STATE["kind"] = _kind_for_unit(unit)
    logger.info("update | %s is still running; tracking it", unit)


def _reconcile() -> str | None:
    """Bring the in-memory run state in line with systemd.

    A recorded run whose unit has finished (or timed out) is ended; with no
    recorded run, a still-active unit is adopted. Returns the unit's name
    when a run just ended ``failed``.
    """
    if _UPDATE_STATE.get("running"):
        return _reap_finished_run()
    _adopt_running_unit()
    return None


# ---------------------------------------------------------------------------
# What the routes call
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LaunchResult:
    """The outcome of ``start_update`` / ``start_rollback``.

    ``refusal`` is None when the run started. On a refusal nothing changed;
    ``unit`` is then the unit of the run already going, if any.
    """

    refusal: Refusal | None = None
    unit: str | None = None
    target_version: str | None = None


def _already_running() -> LaunchResult:
    return LaunchResult(
        refusal=Refusal(
            ALREADY_RUNNING, "An update or rollback is already in progress."
        ),
        unit=current_unit(),
    )


def start_update(target_tag: str | None = None) -> LaunchResult:
    """Start an update to ``target_tag`` (None: the newest release tag).

    ``target_tag`` must already have passed ``_TAG_RE``. Off systemd, or if
    systemd-run fails, the simulated fallback runner takes over. If the
    launch itself raises, this run's claim is undone before the error
    propagates; a run someone else started is never touched.
    """
    _reconcile()
    script_path = _get_update_script_path()
    use_systemd = _systemd_available()
    ticket = try_begin("update")
    if ticket is None:
        return _already_running()
    try:
        if use_systemd:
            try:
                unit = _start_update_via_systemd(target_tag=target_tag)
            except Exception:
                logger.exception("systemd-run failed; falling back to thread runner")
                _start_update_fallback_thread(script_path, target_tag=target_tag)
            else:
                # Tests stub the launcher; record only a real unit name so
                # the reaper probes a unit that exists.
                if isinstance(unit, str):
                    _record_unit(ticket, unit)
        else:
            _start_update_fallback_thread(script_path, target_tag=target_tag)
    except BaseException:
        finish(ticket)
        raise
    return LaunchResult(unit=current_unit(), target_version=target_tag)


def start_rollback() -> LaunchResult:
    """Roll back to the version in ``prev_version`` (JTN-708).

    Refused, with nothing changed, unless ``rollback_eligibility`` allows it
    and no other run is going. rollback.sh checks out the tag and hands over
    to update.sh, whose EXIT trap records a failed rollback like any update.
    """
    _reconcile()
    prev_version = read_prev_version()
    refusal = rollback_eligibility(read_last_update_failure(), prev_version)
    if refusal is not None:
        return LaunchResult(refusal=refusal, unit=current_unit())
    use_systemd = _systemd_available()
    ticket = try_begin("rollback")
    if ticket is None:
        return _already_running()
    try:
        if use_systemd:
            unit = _start_rollback_via_systemd()
            if isinstance(unit, str):
                _record_unit(ticket, unit)
        else:
            # Dev / macOS: the simulated runner still shows log output.
            _start_update_fallback_thread(None, target_tag=prev_version)
    except BaseException:
        finish(ticket)
        raise
    return LaunchResult(unit=current_unit(), target_version=prev_version)


@dataclass(frozen=True)
class UpdateStatus:
    """What ``GET /settings/update_status`` reports."""

    running: bool
    kind: UpdateKind | None
    unit: str | None
    started_at: float | None
    last_failure: JsonObject | None
    prev_version: str | None
    rollback_eligible: bool


def _kind_or_none(value: object) -> UpdateKind | None:
    if value == "update":
        return "update"
    if value == "rollback":
        return "rollback"
    return None


def status() -> UpdateStatus:
    """Report the current run, the last failure, and whether a rollback may
    start now (it may not while a run is going)."""
    failed_unit = _reconcile()
    with _update_lock:
        running = bool(_UPDATE_STATE.get("running"))
        unit = _UPDATE_STATE.get("unit")
        started_at = _UPDATE_STATE.get("started_at")
        kind = _kind_or_none(_UPDATE_STATE.get("kind"))
    unit_name = unit if isinstance(unit, str) and unit else None
    if running and kind is None:
        kind = _kind_for_unit(unit_name)

    recorded_failure = read_last_update_failure()
    last_failure = recorded_failure
    if last_failure is None and failed_unit:
        last_failure = _synthesize_failure_from_journal(failed_unit)
    prev_version = read_prev_version()
    eligible = (
        not running and rollback_eligibility(recorded_failure, prev_version) is None
    )
    return UpdateStatus(
        running=running,
        kind=kind,
        unit=unit_name,
        started_at=float(started_at) if isinstance(started_at, (int, float)) else None,
        last_failure=last_failure,
        prev_version=prev_version,
        rollback_eligible=eligible,
    )
