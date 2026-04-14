# pyright: reportMissingImports=false
"""Structural validation of install/setup scripts — no shell execution."""

import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_DIR = REPO_ROOT / "install"
SCRIPTS_DIR = REPO_ROOT / "scripts"
DOCS_DIR = REPO_ROOT / "docs"


# ---- Helpers ----


def _read(name):
    return (INSTALL_DIR / name).read_text()


# ---- Systemd service ----


class TestSystemdService:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("inkypi.service")

    def test_service_has_required_sections(self):
        for section in ["[Unit]", "[Service]", "[Install]"]:
            assert section in self.content

    def test_service_exec_start(self):
        assert "ExecStart=/usr/local/bin/inkypi run" in self.content

    def test_service_type_notify(self):
        assert "Type=notify" in self.content

    def test_service_restart_policy(self):
        assert "Restart=on-failure" in self.content
        assert "RestartSec=60" in self.content

    def test_service_resource_limits(self):
        assert "CPUQuota=40%" in self.content
        assert "MemoryHigh=250M" in self.content
        assert "MemoryMax=350M" in self.content

    def test_service_oom_score_adjust_prefers_inkypi_as_victim(self):
        # JTN-601: During memory crunch on Pi Zero 2 W, earlyoom was killing
        # sshd and making the Pi unreachable. Positive OOMScoreAdjust makes
        # inkypi the preferred OOM victim so we can still SSH in to debug.
        # Value MUST be positive (+500); a negative value would protect
        # inkypi and sacrifice sshd — the opposite of what we want.
        assert "OOMScoreAdjust=500" in self.content

        # The directive must live in the [Service] section, not [Unit] or
        # [Install]. Parse the section boundaries and verify placement.
        service_start = self.content.index("[Service]")
        install_start = self.content.index("[Install]", service_start)
        oom_pos = self.content.index("OOMScoreAdjust=500")
        assert (
            service_start < oom_pos < install_start
        ), "OOMScoreAdjust=500 must be inside the [Service] section"

        # Guard against someone accidentally re-introducing the wrong sign.
        # The issue title originally said -500 which would protect inkypi
        # and get sshd killed — exactly the opposite of what we want.
        assert "OOMScoreAdjust=-500" not in self.content

    def test_service_watchdog(self):
        assert "WatchdogSec=120" in self.content

    def test_service_execstartpre_checks_install_lockfile(self):
        # JTN-607: Defense-in-depth for JTN-600. If install.sh is running it
        # creates /var/lib/inkypi/.install-in-progress; the service must
        # refuse to start while the lockfile exists so systemd cannot thrash
        # the Pi with a start+crash+restart loop mid-install.
        assert "ExecStartPre=" in self.content, (
            "inkypi.service must have an ExecStartPre directive that checks "
            "the install-in-progress lockfile (JTN-607)"
        )
        assert "/var/lib/inkypi/.install-in-progress" in self.content, (
            "ExecStartPre must reference the /var/lib/inkypi/.install-in-progress "
            "lockfile path so the service refuses to start mid-install (JTN-607)"
        )
        # The directive must also produce a clear log message so operators
        # can tell why the service failed to start.
        assert "Install in progress" in self.content, (
            "ExecStartPre must echo a clear 'Install in progress' message "
            "so operators understand why the service refused to start"
        )
        # ExecStartPre must live in the [Service] section.
        service_start = self.content.index("[Service]")
        install_start = self.content.index("[Install]", service_start)
        pre_pos = self.content.index("ExecStartPre=")
        assert (
            service_start < pre_pos < install_start
        ), "ExecStartPre must be inside the [Service] section"
        # And it must come before ExecStart so systemd runs the check first.
        exec_start_pos = self.content.index("ExecStart=/usr/local/bin/inkypi")
        assert (
            pre_pos < exec_start_pos
        ), "ExecStartPre must appear before ExecStart in the service file"

    def test_service_working_directory(self):
        assert "RuntimeDirectory=inkypi" in self.content
        assert "WorkingDirectory=/run/inkypi" in self.content

    def test_service_start_limit_burst(self):
        # JTN-671: Without StartLimitBurst the JTN-665 incident demonstrated
        # that inkypi.service can restart 4,091+ times before detection (~68 h
        # @ 60 s apart). StartLimitBurst=5 caps that to 5 attempts in
        # StartLimitIntervalSec=1800 (30 min), after which systemd enters the
        # "start-limit-hit" state and stops retrying silently.
        assert "StartLimitBurst=5" in self.content, (
            "inkypi.service must set StartLimitBurst=5 in [Unit] to bound "
            "restart loops (JTN-671)"
        )
        assert "StartLimitIntervalSec=1800" in self.content, (
            "inkypi.service must set StartLimitIntervalSec=1800 in [Unit] to "
            "define the 30-min window for StartLimitBurst (JTN-671)"
        )

        # Both directives must live in the [Unit] section (before [Service]).
        unit_start = self.content.index("[Unit]")
        service_start = self.content.index("[Service]")
        burst_pos = self.content.index("StartLimitBurst=5")
        interval_pos = self.content.index("StartLimitIntervalSec=1800")
        assert (
            unit_start < burst_pos < service_start
        ), "StartLimitBurst=5 must be inside the [Unit] section"
        assert (
            unit_start < interval_pos < service_start
        ), "StartLimitIntervalSec=1800 must be inside the [Unit] section"

    def test_service_on_failure_references_failure_helper(self):
        # JTN-671: OnFailure= activates the sentinel-writer unit when the
        # start-limit is hit, making the failure detectable without parsing
        # journalctl (status LED, healthcheck, future webhook).
        assert "OnFailure=inkypi-failure.service" in self.content, (
            "inkypi.service must declare OnFailure=inkypi-failure.service in "
            "[Unit] so the failure sentinel is written on start-limit-hit (JTN-671)"
        )

        # OnFailure= must live in [Unit], not [Service].
        unit_start = self.content.index("[Unit]")
        service_start = self.content.index("[Service]")
        on_failure_pos = self.content.index("OnFailure=inkypi-failure.service")
        assert (
            unit_start < on_failure_pos < service_start
        ), "OnFailure=inkypi-failure.service must be inside the [Unit] section"


class TestSystemdFailureService:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("inkypi-failure.service")

    def test_failure_service_has_required_sections(self):
        # JTN-671: inkypi-failure.service is a oneshot helper activated by
        # OnFailure= in inkypi.service when the start-limit is hit.
        for section in ["[Unit]", "[Service]"]:
            assert (
                section in self.content
            ), f"inkypi-failure.service must contain a {section} section (JTN-671)"

    def test_failure_service_is_oneshot(self):
        assert (
            "Type=oneshot" in self.content
        ), "inkypi-failure.service must be Type=oneshot (JTN-671)"

    def test_failure_service_writes_sentinel_file(self):
        # The unit must touch /var/lib/inkypi/.start-limit-hit so the
        # healthcheck / status LED can detect the broken service state.
        assert "/var/lib/inkypi/.start-limit-hit" in self.content, (
            "inkypi-failure.service must write /var/lib/inkypi/.start-limit-hit "
            "so the failure is detectable without journalctl (JTN-671)"
        )


# ---- CLI wrapper ----


class TestCLIWrapper:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("inkypi")

    def test_cli_exports_required_vars(self):
        for var in ["APPNAME", "PROGRAM_PATH", "VENV_PATH", "PROJECT_DIR", "SRC_DIR"]:
            assert f"export {var}=" in self.content

    def test_cli_routes_run_command(self):
        assert "run)" in self.content
        assert "run_app" in self.content

    def test_cli_routes_plugin_command(self):
        assert "plugin)" in self.content
        assert "run_plugin_cli" in self.content

    def test_cli_routes_help(self):
        assert "-h|--help|help)" in self.content
        assert "usage" in self.content

    def test_cli_unknown_command_exits(self):
        assert "*)" in self.content
        assert "exit 1" in self.content


# ---- install.sh ----


class TestInstallScript:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("install.sh")
        # JTN-674: shared helpers (stop_service, setup_zramswap_service,
        # get_os_version, echo_*, show_loader) live in _common.sh and are
        # sourced by install.sh.  Tests that verify these shared functions
        # should use self.combined so they keep passing after the refactor.
        self.combined = self.content + "\n" + _read("_common.sh")

    def test_install_enables_spi(self):
        assert "dtparam=spi=" in self.content

    def test_install_enables_i2c(self):
        assert "dtparam=i2c_arm=" in self.content

    def test_install_creates_venv(self):
        assert "python3 -m venv" in self.content

    def test_install_installs_pip_requirements(self):
        assert "pip install" in self.content
        assert "requirements.txt" in self.content

    def test_install_copies_service_file(self):
        assert "systemctl" in self.content
        assert "enable" in self.content

    def test_install_builds_css(self):
        assert "build_css" in self.content

    def test_install_skips_zramtools_when_zram_swap_already_active(self):
        # JTN-569: Pi OS Trixie preinstalls zram-swap which configures /dev/zram0 at
        # boot. Installing zram-tools on top fights over /dev/zram0 and makes
        # `systemctl start zramswap` exit 1. The guard must run before apt-get.
        # JTN-674: setup_zramswap_service() now lives in _common.sh — check combined.
        guard = 'grep -q "^/dev/zram" /proc/swaps'
        apt_install = "apt-get install -y zram-tools"
        assert guard in self.combined
        assert "skipping zram-tools install" in self.combined
        assert "return 0" in self.combined

        fn_start = self.combined.index("setup_zramswap_service() {")
        guard_pos = self.combined.index(guard, fn_start)
        return_pos = self.combined.index("return 0", fn_start)
        apt_pos = self.combined.index(apt_install, fn_start)
        assert guard_pos < return_pos < apt_pos

    def test_install_enables_zramswap_on_bookworm_and_trixie(self):
        # JTN-528: zramswap must be enabled on Bullseye/Bookworm/Trixie so the
        # Pi Zero 2 W (512 MB RAM) doesn't OOM during pip install. The previous
        # check only matched Bookworm (12) exactly, leaving Trixie users broken.
        assert "os_version=$(get_os_version)" in self.content
        assert '[[ "$os_version" =~ ^(11|12|13)$ ]]' in self.content
        assert "setup_zramswap_service" in self.content
        # The skip branch should still exist for unknown future releases.
        assert "skipping zramswap setup" in self.content

    def test_install_waits_for_clock(self):
        # JTN-592: wait_for_clock function must be defined in install.sh
        assert "wait_for_clock() {" in self.content

    def test_install_calls_wait_for_clock_before_apt(self):
        # JTN-592: wait_for_clock must be called before install_debian_dependencies
        lines = self.content.splitlines()
        wait_line = None
        apt_line = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            is_call = stripped.startswith("wait_for_clock") and "() {" not in line
            if is_call and wait_line is None:
                wait_line = i
            if stripped == "install_debian_dependencies":
                apt_line = i
        assert wait_line is not None, "wait_for_clock call not found in install.sh"
        assert (
            apt_line is not None
        ), "install_debian_dependencies call not found in install.sh"
        assert wait_line < apt_line, (
            f"wait_for_clock (line {wait_line}) must come before "
            f"install_debian_dependencies (line {apt_line})"
        )

    def test_wait_for_clock_uses_timedatectl(self):
        # JTN-592: the function must reference timedatectl to check NTP sync
        assert "timedatectl show -p NTPSynchronized" in self.content

    def test_wait_for_clock_warns_but_does_not_fail_on_timeout(self):
        # JTN-592: on timeout the function must return 0, not exit 1
        # Find the function body between wait_for_clock() { and the closing }
        lines = self.content.splitlines()
        in_func = False
        depth = 0
        func_lines = []
        for line in lines:
            if "wait_for_clock() {" in line:
                in_func = True
                depth = 1
                func_lines.append(line)
                continue
            if in_func:
                func_lines.append(line)
                depth += line.count("{") - line.count("}")
                if depth <= 0:
                    break
        func_body = "\n".join(func_lines)
        # Must not have an exit (non-zero) after the loop
        assert "exit 1" not in func_body, "wait_for_clock must not exit 1 on timeout"
        # Must have return 0 after the timeout warning (don't block install)
        assert "return 0" in func_body

    def test_install_os_version_comment_lists_correct_codenames(self):
        # The comment near get_os_version should list 11/12/13 with correct
        # codenames — including the 'Trixie' typo fix from JTN-528.
        # JTN-674: get_os_version() now lives in _common.sh — check combined.
        assert "11=Bullseye" in self.combined
        assert "12=Bookworm" in self.combined
        assert "13=Trixie" in self.combined
        assert "Trixe" not in self.combined  # typo guard

    def test_zramswap_regex_matches_codename_comment_parity(self):
        # JTN-531: The codename comment near get_os_version() and the version
        # regex in the zramswap branch must list the same integer keys.
        # If someone adds 14=Forky to one without updating the other this test
        # will catch it.
        # JTN-674: get_os_version() now lives in _common.sh — check combined.

        # Parse "# Get OS release number, e.g. 11=Bullseye, 12=Bookworm, 13=Trixie"
        # Capture every "<digit(s)>=<Codename>" pair from the comment line
        # immediately above the get_os_version() function definition.
        comment_versions = set()
        lines = self.combined.splitlines()
        for i, line in enumerate(lines):
            if "get_os_version" in line and line.strip().startswith("get_os_version"):
                # Search backwards for the nearest preceding comment line with
                # version=Codename pairs (at most 5 lines back).
                for j in range(max(0, i - 5), i):
                    if "#" in lines[j]:
                        for m in re.finditer(r"(\d+)\s*=\s*[A-Za-z]+", lines[j]):
                            comment_versions.add(int(m.group(1)))

        # Parse the regex alternation in the zramswap if-branch:
        # [[ "$os_version" =~ ^(11|12|13)$ ]]
        # JTN-674: the regex lives in install.sh main body; check combined.
        regex_versions = set()
        for line in self.combined.splitlines():
            m = re.search(r"\^\(([0-9|]+)\)\$", line)
            if m:
                for part in m.group(1).split("|"):
                    if part.strip().isdigit():
                        regex_versions.add(int(part.strip()))

        assert (
            comment_versions
        ), "Could not parse any version numbers from the get_os_version comment in _common.sh"
        assert (
            regex_versions
        ), "Could not parse any version numbers from the zramswap regex in install.sh"
        assert comment_versions == regex_versions, (
            f"Codename comment versions {sorted(comment_versions)} do not match "
            f"zramswap regex versions {sorted(regex_versions)}. "
            "Update both the comment near get_os_version() and the regex in the "
            "zramswap branch when adding a new Debian release."
        )

    def test_install_disables_dphys_swapfile_when_zram_active(self):
        # JTN-593: maybe_disable_dphys_swapfile must be defined in install.sh
        # so it can reclaim /var/swap (~425 MB) when zram is already active.
        assert "maybe_disable_dphys_swapfile()" in self.content
        assert "dphys-swapfile" in self.content

    def test_install_calls_disable_dphys_after_zramswap(self):
        # JTN-593: The call to maybe_disable_dphys_swapfile must appear AFTER
        # the zramswap setup conditional and BEFORE setup_earlyoom_service so
        # we never attempt to reclaim /var/swap before zram is guaranteed active.
        zramswap_call = "setup_zramswap_service"
        disable_call = "maybe_disable_dphys_swapfile"
        earlyoom_call = "setup_earlyoom_service"

        # Use the main script body (after function definitions) for ordering.
        # Functions are defined before the main call site — find the call positions
        # that occur after the last function definition closing brace.
        fn_def_start = self.content.index("maybe_disable_dphys_swapfile() {")
        fn_def_end = self.content.index("}", fn_def_start)

        # All three calls must exist after the function definitions.
        zram_pos = self.content.index(zramswap_call, fn_def_end)
        disable_pos = self.content.index(disable_call, fn_def_end)
        earlyoom_pos = self.content.index(earlyoom_call, fn_def_end)

        assert zram_pos < disable_pos < earlyoom_pos, (
            "maybe_disable_dphys_swapfile() call must appear after setup_zramswap_service "
            "and before setup_earlyoom_service in install.sh"
        )

    def test_disable_dphys_only_runs_when_zram_active(self):
        # JTN-593: The function must check /proc/swaps for /dev/zram BEFORE
        # removing anything — it must be a no-op on systems without zram.
        fn_start = self.content.index("maybe_disable_dphys_swapfile() {")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]

        zram_guard = 'grep -q "^/dev/zram" /proc/swaps'
        rm_swap = "rm -f /var/swap"

        assert zram_guard in fn_body, (
            "maybe_disable_dphys_swapfile() must check /proc/swaps for /dev/zram "
            "before removing /var/swap (safety guard for non-zram systems)"
        )
        assert rm_swap in fn_body, "Function should remove /var/swap"

        guard_pos = fn_body.index(zram_guard)
        rm_pos = fn_body.index(rm_swap)
        assert (
            guard_pos < rm_pos
        ), "/dev/zram guard must appear before rm -f /var/swap in maybe_disable_dphys_swapfile()"

    def test_disable_dphys_does_not_fail_if_package_missing(self):
        # JTN-593: All dphys-swapfile commands must have || true guards so the
        # function is safe on systems where the package is already gone.
        fn_start = self.content.index("maybe_disable_dphys_swapfile() {")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]

        # Every line that calls dphys-swapfile binary commands should be guarded.
        dphys_cmd_lines = [
            line.strip()
            for line in fn_body.splitlines()
            if "dphys-swapfile" in line
            and line.strip().startswith("sudo dphys-swapfile")
        ]
        assert (
            dphys_cmd_lines
        ), "Expected sudo dphys-swapfile command lines in the function"
        for line in dphys_cmd_lines:
            assert "|| true" in line, (
                f"dphys-swapfile command must have '|| true' guard to avoid failures "
                f"when package is missing: {line!r}"
            )

    def test_install_disables_service_during_install(self):
        # JTN-600: stop_service() must DISABLE (not just stop) the service so
        # systemd cannot auto-restart the half-installed service during the ~15 min
        # install window and cause a memory-thrash cascade on the Pi Zero 2 W.
        # JTN-674: stop_service() now lives in _common.sh — check combined.
        fn_start = self.combined.index("stop_service() {")
        fn_end = self.combined.index("\n}", fn_start)
        fn_body = self.combined[fn_start:fn_end]
        assert 'systemctl disable "$SERVICE_FILE"' in fn_body, (
            "stop_service() must call 'systemctl disable \"$SERVICE_FILE\"' to "
            "prevent systemd from restarting the half-installed service"
        )

    def test_install_re_enables_service_at_end(self):
        # JTN-600: Regression guard — install_app_service() must re-enable the
        # service at the end of the install after stop_service() disabled it.
        fn_start = self.content.index("install_app_service() {")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]
        assert "systemctl enable" in fn_body, (
            "install_app_service() must call 'systemctl enable' to re-enable the "
            "service after stop_service() disabled it during the install window"
        )

    def test_install_app_service_installs_failure_helper(self):
        # JTN-671: install_app_service() must also copy inkypi-failure.service
        # into /etc/systemd/system/ so the OnFailure= directive can resolve.
        fn_start = self.content.index("install_app_service() {")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]
        assert "inkypi-failure.service" in fn_body, (
            "install_app_service() must install inkypi-failure.service so the "
            "OnFailure= directive in inkypi.service can resolve (JTN-671)"
        )

    def test_install_creates_lockfile_near_top(self):
        # JTN-607: install.sh must create /var/lib/inkypi/.install-in-progress
        # early in the main script body (after check_permissions) so any
        # concurrent systemctl start attempt hits the ExecStartPre guard.
        # Locate the call site — must appear after check_permissions and
        # before the later install steps (install_debian_dependencies etc.).
        assert (
            "/var/lib/inkypi" in self.content
        ), "install.sh must reference /var/lib/inkypi for the lockfile (JTN-607)"
        assert (
            ".install-in-progress" in self.content
        ), "install.sh must reference the .install-in-progress lockfile (JTN-607)"

        # The lockfile must be created (touch) in the main script body.
        # Find the first 'touch "$LOCKFILE"' outside function definitions by
        # searching after the last function closing brace before main flow.
        main_start = self.content.index('parse_arguments "$@"')
        main_body = self.content[main_start:]
        assert (
            'mkdir -p "$LOCKFILE_DIR"' in main_body
        ), "install.sh main body must mkdir -p the lockfile directory (JTN-607)"
        assert (
            'touch "$LOCKFILE"' in main_body
        ), "install.sh main body must touch the lockfile (JTN-607)"

        # Ordering: touch must come after check_permissions (so we only create
        # the lockfile once we know we're running as root) and before the
        # heavy install steps.
        check_pos = main_body.index("check_permissions")
        touch_pos = main_body.index('touch "$LOCKFILE"')
        install_deps_pos = main_body.index("install_debian_dependencies")
        assert check_pos < touch_pos < install_deps_pos, (
            'touch "$LOCKFILE" must run after check_permissions and before '
            "install_debian_dependencies (JTN-607)"
        )

    def test_install_removes_lockfile_at_end_on_success(self):
        # JTN-607: At the very end of install.sh, after every install step
        # has succeeded, remove the lockfile so the service is allowed to
        # start. The removal must come AFTER install_app_service and the CSS
        # build so a failure in any earlier step leaves the lockfile in place.
        # JTN-674: CSS build is now called via build_css_bundle (shared helper
        # in _common.sh). The call site is still in install.sh's main body.
        main_start = self.content.index('parse_arguments "$@"')
        main_body = self.content[main_start:]

        assert (
            'rm -f "$LOCKFILE"' in main_body
        ), "install.sh must remove the lockfile on success (JTN-607)"

        # Ordering: rm must come after install_app_service and after the CSS
        # build call so an earlier failure leaves the lockfile in place.
        rm_pos = main_body.index('rm -f "$LOCKFILE"')
        install_app_pos = main_body.index("install_app_service")
        # JTN-674: CSS build is invoked via build_css_bundle; the inline
        # "CSS bundle built" message now lives in _common.sh's function body.
        css_pos = main_body.index("build_css_bundle")
        assert (
            install_app_pos < rm_pos
        ), 'rm -f "$LOCKFILE" must come after install_app_service (JTN-607)'
        assert css_pos < rm_pos, (
            'rm -f "$LOCKFILE" must come after the build_css_bundle call '
            "so a CSS build failure leaves the lockfile in place (JTN-607)"
        )

    def test_install_lockfile_not_removed_by_error_trap(self):
        # JTN-607: On failure exit, the lockfile must be LEFT in place so the
        # user is forced to rerun install.sh (or manually rm the file) before
        # the service can start. This means there must be NO trap that
        # removes the lockfile on EXIT/ERR/INT/TERM — only the explicit
        # rm -f at the end of a successful run.
        trap_lines = [
            line
            for line in self.content.splitlines()
            if line.strip().startswith("trap ")
        ]
        for line in trap_lines:
            assert "$LOCKFILE" not in line and ".install-in-progress" not in line, (
                "install.sh must NOT register a trap that removes the lockfile "
                "on failure exit — leaving it in place forces the user to "
                f"rerun install.sh before the service can start (JTN-607): {line!r}"
            )

    def test_stop_service_disable_tolerates_already_disabled(self):
        # JTN-600: The disable call must not fail if the service is already
        # disabled (e.g. fresh install). Must use '|| true' or '2>/dev/null'.
        # JTN-674: stop_service() now lives in _common.sh — check combined.
        fn_start = self.combined.index("stop_service() {")
        fn_end = self.combined.index("\n}", fn_start)
        fn_body = self.combined[fn_start:fn_end]
        # Find the disable line and confirm it has an error-tolerant fallback.
        disable_lines = [
            line.strip() for line in fn_body.splitlines() if "systemctl disable" in line
        ]
        assert disable_lines, "No 'systemctl disable' line found in stop_service()"
        for line in disable_lines:
            assert "|| true" in line or "2>/dev/null" in line, (
                f"systemctl disable call must have '|| true' or '2>/dev/null' so "
                f"it doesn't fail when the service is already disabled: {line!r}"
            )

    def test_install_uses_no_cache_dir(self):
        # JTN-602: every pip install invocation in install.sh must include
        # --no-cache-dir to avoid wasting ~200 MB of SD card space and ~50 MB
        # of RAM on a Pi Zero 2 W (pip runs once per install cycle, cache is useless).
        pip_install_lines = [
            line.strip()
            for line in self.content.splitlines()
            if re.search(r"-m pip install", line) and not line.strip().startswith("#")
        ]
        assert pip_install_lines, "No 'pip install' invocations found in install.sh"
        for line in pip_install_lines:
            assert (
                "--no-cache-dir" in line
            ), f"pip install invocation is missing --no-cache-dir (JTN-602): {line!r}"

    def test_install_installs_uv_into_venv(self):
        # JTN-605: uv (Rust-based pip replacement) must be installed into the
        # venv BEFORE the main dependency install so the resolver uses ~10-20 MB
        # peak instead of pip's ~100-150 MB on a Pi Zero 2 W.
        lines = self.content.splitlines()

        # Find create_venv() function body.
        fn_start_idx = None
        for i, line in enumerate(lines):
            if "create_venv()" in line and "{" in line:
                fn_start_idx = i
                break
        assert fn_start_idx is not None, "create_venv() not found"

        depth = 0
        fn_lines = []
        for line in lines[fn_start_idx:]:
            fn_lines.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0 and fn_lines:
                break
        fn_body = "\n".join(fn_lines)

        # uv must be installed via the venv's pip.
        # Split into two asserts (PT018) for clearer failure diagnostics.
        assert (
            "-m pip install" in fn_body
        ), "create_venv() must contain a pip install call (JTN-605)"
        assert (
            " uv" in fn_body
        ), "create_venv() must install uv into the venv via 'pip install uv' (JTN-605)"

    def _logical_shell_lines(self, body: str) -> list[str]:
        """Join backslash-continued shell lines into single logical lines.

        Shell continuations ( \\ at EOL ) carry a single command across
        multiple source lines. Tests that grep for "flag X and argument Y
        on the same invocation" would otherwise miss them after a refactor
        wraps the command for readability.
        """
        out: list[str] = []
        buf = ""
        for raw in body.splitlines():
            # Preserve comment-only lines as-is (they never continue).
            stripped = raw.rstrip()
            if stripped.endswith("\\"):
                buf += stripped[:-1] + " "
            else:
                out.append(buf + stripped)
                buf = ""
        if buf:
            out.append(buf)
        return out

    def test_install_uses_uv_for_main_dependency_install(self):
        # JTN-605: the main dependency install should prefer uv when available.
        # Structural: there must be a `uv pip install ... -r ... requirements.txt`
        # invocation in create_venv() that carries --no-cache and --require-hashes.
        fn_start = self.content.index("create_venv(){")
        fn_end_marker = "\n}"
        fn_end = self.content.index(fn_end_marker, fn_start)
        fn_body = self.content[fn_start:fn_end]

        # The uv-based install command must reference uv pip install.
        assert (
            "uv pip install" in fn_body
        ), "create_venv() must use 'uv pip install' for the main dependency install (JTN-605)"

        # Locate the uv-based main install block after joining backslash
        # continuations so the single logical command (which spans several
        # source lines) is searched as one string.
        logical_lines = self._logical_shell_lines(fn_body)
        uv_main_install_lines = [
            line
            for line in logical_lines
            if "uv pip install" in line and "PIP_REQUIREMENTS_FILE" in line
        ]
        assert uv_main_install_lines, (
            "create_venv() must have a 'uv pip install ... -r "
            "$PIP_REQUIREMENTS_FILE' invocation (JTN-605)"
        )
        joined = "\n".join(uv_main_install_lines)
        # The uv-based main install must preserve hash enforcement.
        assert (
            "--require-hashes" in joined
        ), "uv pip install for main requirements must preserve --require-hashes (JTN-516)"
        # uv uses --no-cache (not --no-cache-dir) — equivalent savings.
        assert (
            "--no-cache" in joined
        ), "uv pip install must use --no-cache equivalent of --no-cache-dir (JTN-602)"

    def test_install_uv_pip_install_has_http_timeout(self):
        # JTN-605 / JTN-534: the pip fallback sets --retries 5 --timeout 60 to
        # survive flaky Wi-Fi on a Pi Zero 2 W. uv doesn't accept
        # --default-timeout as a CLI flag; it reads UV_HTTP_TIMEOUT from the
        # environment. Every `uv pip install` invocation must prefix
        # UV_HTTP_TIMEOUT (on the same source line as the command, so bash
        # scopes it to that subprocess only) otherwise uv can block
        # indefinitely on a network hiccup.
        fn_start = self.content.index("create_venv(){")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]

        lines = fn_body.splitlines()
        uv_install_line_indices = [
            i for i, line in enumerate(lines) if "-m uv pip install" in line
        ]
        assert (
            uv_install_line_indices
        ), "create_venv() must have at least one 'uv pip install' invocation (JTN-605)"
        for idx in uv_install_line_indices:
            line = lines[idx]
            assert "UV_HTTP_TIMEOUT=" in line, (
                "uv pip install invocation must prefix UV_HTTP_TIMEOUT so it "
                "has a finite network timeout and matches pip fallback "
                f"--timeout behavior (JTN-534): {line.strip()!r}"
            )

    def test_install_has_pip_fallback_path(self):
        # JTN-605: if uv cannot be installed or run (e.g. unsupported arch,
        # wheel download failure), install.sh must cleanly fall back to plain
        # pip. Structural grep: both a uv branch and a pip fallback branch must
        # exist inside create_venv(), and the pip fallback must still install
        # the main requirements.
        fn_start = self.content.index("create_venv(){")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]

        # A gating variable/conditional must exist.
        assert (
            "use_uv" in fn_body
        ), "create_venv() must gate the uv vs pip path on a use_uv flag (JTN-605)"
        # An else branch (pip fallback) must exist and must run pip install
        # against PIP_REQUIREMENTS_FILE with --require-hashes preserved.
        assert (
            "else" in fn_body
        ), "create_venv() must have an else branch for the pip fallback (JTN-605)"
        # The fallback must still use --no-cache-dir, --require-hashes, and
        # PIP_REQUIREMENTS_FILE. Join backslash-continued shell lines so the
        # multi-line pip invocation is matched as one logical command.
        logical_lines = self._logical_shell_lines(fn_body)
        pip_fallback_lines = [
            line
            for line in logical_lines
            if "-m pip install" in line
            and "PIP_REQUIREMENTS_FILE" in line
            and "uv pip install" not in line
        ]
        assert pip_fallback_lines, (
            "create_venv() must retain a pip-based install of PIP_REQUIREMENTS_FILE "
            "as a fallback when uv is unavailable (JTN-605)"
        )
        joined = "\n".join(pip_fallback_lines)
        assert "--require-hashes" in joined
        assert "--no-cache-dir" in joined

    def test_install_uv_path_available_before_main_install(self):
        # JTN-605: uv must be installed into the venv BEFORE the main
        # dependency install — otherwise the uv branch can never be taken.
        fn_start = self.content.index("create_venv(){")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]

        # Strip comments so we only look at executable shell lines.
        def _strip_comments(body: str) -> str:
            out = []
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    out.append("")
                else:
                    out.append(line)
            return "\n".join(out)

        code_only = _strip_comments(fn_body)

        # Position of the uv bootstrap (pip install uv).
        uv_bootstrap_pos = None
        for m in re.finditer(r"-m pip install[^\n]*\buv\b", code_only):
            uv_bootstrap_pos = m.start()
            break
        assert (
            uv_bootstrap_pos is not None
        ), "uv bootstrap (pip install uv) not found in create_venv()"

        # Position of the first actual `uv pip install` call (not in a comment).
        uv_main_pos = code_only.index("uv pip install")
        assert (
            uv_bootstrap_pos < uv_main_pos
        ), "uv must be installed into the venv before the first 'uv pip install' call"

    def test_install_no_cache_dir_in_all_venv_pip_calls(self):
        # JTN-602: parse the create_venv() function body and assert every
        # pip install call inside it carries --no-cache-dir.
        lines = self.content.splitlines()

        # Extract the create_venv() function body.
        fn_start_idx = None
        for i, line in enumerate(lines):
            if "create_venv()" in line and "{" in line:
                fn_start_idx = i
                break
        assert (
            fn_start_idx is not None
        ), "create_venv() function not found in install.sh"

        depth = 0
        fn_lines = []
        for line in lines[fn_start_idx:]:
            fn_lines.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0 and fn_lines:
                break
        fn_body = "\n".join(fn_lines)

        pip_calls = [
            line.strip()
            for line in fn_lines
            if re.search(r"-m pip install", line) and not line.strip().startswith("#")
        ]
        assert pip_calls, "No pip install calls found inside create_venv()"
        for call in pip_calls:
            assert (
                "--no-cache-dir" in call
            ), f"pip install inside create_venv() missing --no-cache-dir (JTN-602): {call!r}"
        # Sanity: all 3 call sites must be present (pip/setuptools/wheel upgrade,
        # main requirements, optional Waveshare requirements).
        assert (
            len(pip_calls) >= 2
        ), f"Expected at least 2 pip install calls in create_venv(), found {len(pip_calls)}"
        # Suppress unused variable warning — fn_body used as context in debugging
        _ = fn_body


# ---- Wheelhouse release asset (JTN-604 / JTN-669) ----


class TestCommonWheelhouseFunctions:
    """JTN-669: fetch_wheelhouse / cleanup_wheelhouse now live in _common.sh
    so both install.sh and update.sh can share them without duplication.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("_common.sh")

    def _fetch_fn_body(self):
        fn_start = self.content.index("fetch_wheelhouse() {")
        # Function body ends at the first matching closing brace at depth 0.
        depth = 0
        i = fn_start
        while i < len(self.content):
            ch = self.content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return self.content[fn_start : i + 1]
            i += 1
        raise AssertionError("fetch_wheelhouse() body not terminated")

    def test_fetch_wheelhouse_function_defined(self):
        assert "fetch_wheelhouse() {" in self.content
        assert "cleanup_wheelhouse() {" in self.content

    def test_respects_skip_opt_out_env_var(self):
        # INKYPI_SKIP_WHEELHOUSE=1 must short-circuit the fetch before any
        # network call. The check must live near the top of the function.
        body = self._fetch_fn_body()
        assert "INKYPI_SKIP_WHEELHOUSE:-0" in body or "INKYPI_SKIP_WHEELHOUSE" in body
        skip_pos = body.index("INKYPI_SKIP_WHEELHOUSE")
        curl_pos = (
            body.index("curl", skip_pos) if "curl" in body[skip_pos:] else len(body)
        )
        assert (
            skip_pos < curl_pos
        ), "INKYPI_SKIP_WHEELHOUSE check must precede the curl download"

    def test_uses_uname_to_pick_arch(self):
        body = self._fetch_fn_body()
        assert "uname -m" in body
        # Must support both Pi Zero 2 W (armv7l) and Pi 4/5 (aarch64/arm64).
        assert "armv7l" in body
        assert "aarch64" in body

    def test_downloads_from_jtn0123_fork(self):
        # The wheelhouse download URL must target the fork, not upstream,
        # since that's where our release workflow publishes artifacts.
        body = self._fetch_fn_body()
        # Default repo value lives just above the function definition.
        assert "jtn0123/InkyPi" in self.content
        # URL is assembled from the repo variable so it tracks overrides.
        assert "WHEELHOUSE_REPO" in body
        assert "releases/download" in body
        assert "fatihak/InkyPi" not in body

    def test_fetch_reads_version_file(self):
        body = self._fetch_fn_body()
        # Must derive the tag from the VERSION file rather than hard-coding it.
        assert "VERSION" in body
        assert "$SCRIPT_DIR/../VERSION" in body

    def test_fetch_is_graceful_on_curl_failure(self):
        body = self._fetch_fn_body()
        # On curl failure we must return 1 (not exit) and clean up the temp dir
        # so the caller can continue with the normal source install.
        assert "curl --fail" in body
        assert "return 1" in body
        assert "rm -rf" in body  # temp dir cleanup path
        # The body must reference a "falling back" message so operators can
        # see in logs which path was taken.
        assert "falling back" in body.lower()

    def test_fetch_verifies_optional_checksum(self):
        body = self._fetch_fn_body()
        # Checksum verification must be opportunistic — a missing sha256 file
        # is OK (continues), but a mismatch must fail and fall back.
        assert ".sha256" in body
        assert "sha256sum" in body or "shasum -a 256" in body
        assert "checksum mismatch" in body.lower()

    def test_fetch_checks_tarball_has_wheels(self):
        # Guard against an empty or corrupted tarball masquerading as a
        # successful bundle — at least one .whl must exist after extract.
        body = self._fetch_fn_body()
        assert "*.whl" in body

    def test_fetch_sets_temp_dir_and_cleans_on_failure(self):
        body = self._fetch_fn_body()
        # mktemp must be used so parallel invocations don't collide, and
        # every failure path must rm -rf the temp dir.
        assert "mktemp" in body
        assert 'rm -rf "$tmp_dir"' in body


class TestInstallWheelhouseFetch:
    """JTN-604: install.sh sources _common.sh for wheelhouse helpers and
    wires them into create_venv.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("install.sh")

    def test_install_sources_common(self):
        # JTN-669: functions live in _common.sh now; install.sh must source it.
        assert "_common.sh" in self.content
        assert 'source "$SCRIPT_DIR/_common.sh"' in self.content

    def test_create_venv_calls_fetch_wheelhouse(self):
        # fetch_wheelhouse must be invoked from inside create_venv so the
        # bundle is downloaded before the main pip install runs.
        fn_start = self.content.index("create_venv(){")
        lines = self.content[fn_start:].splitlines()
        depth = 0
        body_lines: list[str] = []
        for line in lines:
            body_lines.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0 and body_lines:
                break
        body = "\n".join(body_lines)
        assert "fetch_wheelhouse" in body
        assert "cleanup_wheelhouse" in body

    def test_pip_install_uses_find_links_when_available(self):
        # create_venv must pass --find-links $WHEELHOUSE_DIR --prefer-binary
        # to the main pip install so local wheels take precedence.
        fn_start = self.content.index("create_venv(){")
        depth = 0
        body_lines: list[str] = []
        for line in self.content[fn_start:].splitlines():
            body_lines.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0 and body_lines:
                break
        body = "\n".join(body_lines)
        assert "--find-links" in body
        assert "--prefer-binary" in body
        assert "WHEELHOUSE_DIR" in body

    def test_no_cache_dir_still_present_after_wheelhouse_change(self):
        # Regression guard for JTN-602 — the wheelhouse change must not
        # accidentally drop --no-cache-dir from create_venv's pip calls.
        fn_start = self.content.index("create_venv(){")
        depth = 0
        body_lines: list[str] = []
        for line in self.content[fn_start:].splitlines():
            body_lines.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0 and body_lines:
                break
        pip_lines = [
            line
            for line in body_lines
            if re.search(r"-m pip install", line) and not line.strip().startswith("#")
        ]
        assert pip_lines, "no pip install calls found in create_venv()"
        for line in pip_lines:
            assert (
                "--no-cache-dir" in line
            ), f"JTN-602 regression — pip install missing --no-cache-dir: {line!r}"


class TestWheelhouseBuildWorkflow:
    """JTN-604: the release-time workflow that produces the wheelhouse asset."""

    WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "build-wheelhouse.yml"

    @pytest.fixture(autouse=True)
    def _load(self):
        assert (
            self.WORKFLOW_PATH.exists()
        ), f"Expected workflow file at {self.WORKFLOW_PATH}"
        self.content = self.WORKFLOW_PATH.read_text()

    def test_workflow_triggers_on_release_published(self):
        # The workflow must run on release publish so every tagged release
        # automatically gets a wheelhouse attached.
        assert "release:" in self.content
        assert "published" in self.content

    def test_workflow_supports_manual_rebuild(self):
        # workflow_dispatch lets maintainers rebuild a wheelhouse for an
        # existing tag without cutting a new release.
        assert "workflow_dispatch:" in self.content

    def test_workflow_builds_both_target_architectures(self):
        # Pi Zero 2 W (armv7) + Pi 4/5 (aarch64) are the two supported
        # InkyPi targets — both must be built.
        assert "linux_armv7l" in self.content
        assert "linux_aarch64" in self.content
        assert "linux/arm/v7" in self.content
        assert "linux/arm64" in self.content

    def test_workflow_uses_qemu_and_docker(self):
        # The wheels are built inside a QEMU-emulated Debian Trixie container
        # so wheel tags match what the Pi will install them against.
        assert "docker/setup-qemu-action" in self.content
        assert "debian:trixie" in self.content

    def test_workflow_runs_pip_wheel_against_requirements(self):
        assert "pip wheel" in self.content
        assert "install/requirements.txt" in self.content

    def test_workflow_produces_expected_tarball_name(self):
        # Name must exactly match the format install.sh downloads.
        assert "inkypi-wheels-" in self.content
        assert ".tar.gz" in self.content

    def test_workflow_uploads_release_asset(self):
        assert "softprops/action-gh-release" in self.content

    def test_workflow_attaches_sha256_alongside_tarball(self):
        # sha256 checksum must travel with the tarball so install.sh can
        # verify the download.
        assert "sha256sum" in self.content
        assert ".sha256" in self.content


class TestPiImageBuildWorkflow:
    """JTN-533: release-time workflow that builds a pre-installed .img.xz."""

    WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "build-pi-image.yml"

    @pytest.fixture(autouse=True)
    def _load(self):
        assert (
            self.WORKFLOW_PATH.exists()
        ), f"Expected workflow file at {self.WORKFLOW_PATH}"
        self.content = self.WORKFLOW_PATH.read_text()

    def test_workflow_is_valid_yaml(self):
        import yaml

        doc = yaml.safe_load(self.content)
        assert isinstance(doc, dict)
        # 'on' is parsed as Python True in PyYAML 5.x — accept either key
        assert "on" in doc or True in doc
        assert "jobs" in doc

    def test_workflow_triggers_on_release_published(self):
        # Must run on every tagged release so each release ships an image.
        assert "release:" in self.content
        assert "published" in self.content

    def test_workflow_supports_manual_rebuild(self):
        # workflow_dispatch lets maintainers rebuild an image for an existing
        # tag without cutting a new release (same pattern as JTN-604).
        assert "workflow_dispatch:" in self.content

    def test_workflow_pins_pi_os_image_url_in_env_block(self):
        # The Pi OS base image URL must live in a clearly-labeled top-of-file
        # variable so bumping the base image is a single-line change.
        match = re.search(r"PI_OS_IMAGE_URL:\s*(https?://\S+)", self.content)
        assert match is not None, "build-pi-image.yml must define PI_OS_IMAGE_URL"
        parsed = urlparse(match.group(1))
        assert parsed.hostname == "downloads.raspberrypi.org"
        assert "PIN POINT" in self.content, (
            "build-pi-image.yml must have a PIN POINT comment block so future "
            "maintainers know exactly how to bump the Pi OS image"
        )

    def test_workflow_pins_pi_os_image_sha256(self):
        # Defense against a compromised CDN — SHA must travel with the URL.
        assert "PI_OS_IMAGE_SHA256:" in self.content
        # A real 64-char lowercase hex sha256 must be present in the env
        # block (defense against an empty placeholder slipping through).
        sha_match = re.search(r"PI_OS_IMAGE_SHA256:\s*([0-9a-f]{64})", self.content)
        assert (
            sha_match is not None
        ), "PI_OS_IMAGE_SHA256 must be a 64-char lowercase hex digest"

    def test_workflow_verifies_base_image_checksum(self):
        # The downloaded base image must be checksum-verified before use.
        assert "sha256sum -c" in self.content

    def test_workflow_uses_qemu_user_static_and_chroot(self):
        # Building arm64 binaries on an x86_64 runner requires
        # qemu-user-static for binfmt + chroot + copy of qemu-aarch64-static
        # into the mounted rootfs.
        assert "qemu-user-static" in self.content
        assert "qemu-aarch64-static" in self.content
        assert "chroot" in self.content

    def test_workflow_bind_mounts_proc_sys_dev(self):
        # chroot needs /proc, /sys, /dev visible for install.sh to succeed.
        assert "/proc" in self.content
        assert "/sys" in self.content
        assert "/dev" in self.content
        assert "mount --bind" in self.content

    def test_workflow_clones_at_release_tag_not_main(self):
        # Must build from the release tag so install.sh/requirements match
        # the shipped version.
        assert "--branch" in self.content
        assert "tag_name" in self.content or "inputs.tag" in self.content
        # Never pin to main/HEAD
        assert "--branch main" not in self.content
        assert "--branch master" not in self.content

    def test_workflow_runs_install_sh_in_chroot(self):
        # The whole point — chroot + install.sh is what produces the image.
        assert "install/install.sh" in self.content or "install.sh" in self.content

    def test_workflow_does_not_modify_install_sh(self):
        # JTN-533 constraint: install.sh must stay self-contained for
        # source-install users. The workflow uses PATH stubs, not a patched
        # install.sh, to deal with raspi-config/systemctl in a chroot.
        # Detect a modification by looking for sed/patch/awk rewrites of
        # install.sh content — `checkout` of a workflow file itself is fine.
        lowered = self.content.lower()
        assert (
            "sed -i" not in lowered
            or "install.sh" not in lowered
            or (
                # Allow sed usage as long as it does not target install.sh.
                "install.sh"
                not in self.content.split("sed -i")[-1][:200]
            )
        )

    def test_workflow_pishrink_pinned_by_commit(self):
        # pishrink.sh has no tagged releases — must be pinned by full SHA.
        assert "PISHRINK_COMMIT:" in self.content
        sha_match = re.search(r"PISHRINK_COMMIT:\s*([0-9a-f]{40})", self.content)
        assert (
            sha_match is not None
        ), "PISHRINK_COMMIT must be a 40-char lowercase hex commit SHA"

    def test_workflow_runs_pishrink(self):
        assert "pishrink.sh" in self.content

    def test_workflow_zero_fills_free_space_before_compression(self):
        # Better xz ratio — zero-fill unused blocks so they compress away.
        assert "dd if=/dev/zero" in self.content

    def test_workflow_recompresses_with_xz(self):
        assert "xz -9" in self.content

    def test_workflow_produces_expected_image_name(self):
        assert "inkypi-" in self.content
        assert "pi-zero-2-w.img" in self.content

    def test_workflow_generates_sha256_sidecar(self):
        assert "sha256sum" in self.content
        assert ".sha256" in self.content

    def test_workflow_has_boot_verification_job(self):
        # JTN-533: unverified images must not ship. A separate job boots the
        # image in qemu and grep's for "login:" before attach-release runs.
        assert "verify-boot" in self.content or "boot-verify" in self.content
        assert (
            "qemu-system-aarch64" in self.content or "qemu-system-arm" in self.content
        )
        assert "login:" in self.content

    def test_workflow_attach_release_requires_boot_verification(self):
        # The attach job must `needs: verify-boot` AND gate on its verified
        # output so a failed boot cannot silently upload an image.
        assert "needs: [build-image, verify-boot]" in self.content or (
            "needs:" in self.content and "verify-boot" in self.content
        )
        assert "verify-boot.outputs.verified" in self.content

    def test_workflow_uses_pinned_action_versions(self):
        # Supply-chain: every external action must be pinned by major version.
        # (SHA pinning is stronger but the rest of the repo uses @v4/@v2.)
        assert "actions/checkout@v4" in self.content
        assert "softprops/action-gh-release@v2" in self.content
        assert "actions/upload-artifact@v4" in self.content
        assert "actions/download-artifact@v4" in self.content

    def test_workflow_uploads_release_asset(self):
        assert "softprops/action-gh-release" in self.content

    def test_workflow_attach_gated_on_release_event(self):
        # attach-release step must only fire on `release` events, never on
        # workflow_dispatch (which is a dry run).
        assert "github.event_name == 'release'" in self.content


class TestInstallationDocPreBuiltImage:
    """JTN-533: docs/installation.md must surface the pre-built image path."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = (DOCS_DIR / "installation.md").read_text()

    def test_documents_prebuilt_image_option(self):
        # Users should see the .img.xz option front and center.
        assert "Pre-built image" in self.content or "pre-built image" in self.content

    def test_documents_image_file_extension(self):
        assert ".img.xz" in self.content

    def test_documents_sha256_verification(self):
        assert ".sha256" in self.content

    def test_documents_pi_zero_2_w_only_scope(self):
        # Callers on other Pi models must be pointed at install.sh instead.
        assert "Pi Zero 2 W" in self.content

    def test_references_jtn_533(self):
        assert "JTN-533" in self.content


# ---- update_vendors.sh ----


class TestUpdateVendorsScript:
    """JTN-615: update_vendors.sh must anchor cwd to repo root before writing.

    install.sh invokes it via `bash "$SCRIPT_DIR/update_vendors.sh"` without
    changing cwd. Vendor destinations are specified relative to the repo root
    (e.g. `src/static/styles/select2.min.css`), so the script must `cd` to
    the repo root itself — otherwise curl writes to `$PWD/src/static/...`,
    which in CI (container WORKDIR=/InkyPi/install) is a non-existent path and
    every download fails with `curl: (23) Failure writing output to destination`.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("update_vendors.sh")

    def test_script_anchors_cwd_to_repo_root(self):
        # The fix uses BASH_SOURCE + cd. Assert both pieces are present so
        # a future refactor can't accidentally drop the cd without tripping
        # this regression gate.
        assert "BASH_SOURCE" in self.content, (
            "update_vendors.sh must derive its own location via BASH_SOURCE "
            "so relative vendor paths resolve correctly regardless of caller cwd"
        )
        assert (
            "cd " in self.content
        ), "update_vendors.sh must cd to the repo root before invoking curl"

    def test_script_mentions_jtn_615(self):
        assert "JTN-615" in self.content, (
            "update_vendors.sh should reference JTN-615 in a comment explaining "
            "the cwd-anchoring requirement so the intent survives future edits"
        )

    def test_vendor_destinations_are_repo_root_relative(self):
        # Every VENDORS entry has the form "name|url|output_path" on its own
        # line inside the `declare -a VENDORS=( ... )` block. The output paths
        # must still start with `src/static/` (not `../src/static/` or an
        # absolute path) — the fix is to cd *into* the repo root, not to
        # rewrite every destination.
        import re

        # Match lines like: `  "Select2 CSS|https://.../x.css|src/static/..."`
        vendor_lines = re.findall(
            r'^\s*"[^"|]+\|https?://[^"|]+\|([^"|]+)"', self.content, re.MULTILINE
        )
        assert vendor_lines, "No vendor entries found in update_vendors.sh"
        for path in vendor_lines:
            assert path.startswith("src/static/"), (
                f"Vendor destination {path!r} must be relative to the repo "
                f"root (start with 'src/static/'); update_vendors.sh now "
                f"anchors cwd to the repo root so this works."
            )

    def test_install_sh_invokes_update_vendors(self):
        # Sanity check that install.sh still actually calls update_vendors.sh
        # (the consumer side of the contract this test exists to protect).
        install_sh = _read("install.sh")
        assert "update_vendors.sh" in install_sh


# ---- update.sh ----


class TestUpdateScript:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("update.sh")
        # JTN-674: shared helpers (stop_service, setup_zramswap_service,
        # get_os_version, echo_*, show_loader) live in _common.sh and are
        # sourced by update.sh.  Tests that verify these shared functions
        # should use self.combined so they keep passing after the refactor.
        self.combined = self.content + "\n" + _read("_common.sh")

    def test_update_rebuilds_css(self):
        assert "build_css" in self.content

    def test_update_restarts_service(self):
        # JTN-666: update.sh now stops first then starts (not restart), because
        # stop_service is called before any file changes and update_app_service
        # re-enables + starts the service at the end.
        assert "systemctl" in self.content
        assert "systemctl start" in self.content

    def test_update_stop_service_before_pip(self):
        # JTN-666: stop_service() must be called before pip install to prevent
        # systemd from restart-looping the half-installed venv during update.
        # JTN-674: stop_service() now lives in _common.sh — check combined.
        assert "stop_service" in self.content
        # stop_service() must DISABLE (not just stop) so systemd cannot auto-restart.
        fn_start = self.combined.index("stop_service() {")
        fn_end = self.combined.index("}", fn_start) + 1
        fn_body = self.combined[fn_start:fn_end]
        assert (
            "systemctl disable" in fn_body
        ), "stop_service() must call 'systemctl disable' to prevent auto-restart mid-update"
        # stop_service call must appear before pip install in main script body
        main_call = self.content.index("stop_service\n")
        pip_pos = self.content.index("pip install")
        assert (
            main_call < pip_pos
        ), "stop_service must be called before pip install to prevent mid-update thrash"

    def test_update_lockfile_created_before_stop_service(self):
        # JTN-666: The install-in-progress lockfile (JTN-607 parity) must be
        # created before stop_service is called, providing defense-in-depth so
        # that even a manual `systemctl start` cannot start mid-update.
        assert 'LOCKFILE_DIR="/var/lib/inkypi"' in self.content
        assert 'LOCKFILE="$LOCKFILE_DIR/.install-in-progress"' in self.content
        # Use the stop_service call position to find main body start
        stop_call_pos = self.content.rindex("stop_service\n")
        main_body = self.content[self.content.rindex("EUID", 0, stop_call_pos) :]
        assert 'mkdir -p "$LOCKFILE_DIR"' in main_body
        assert 'touch "$LOCKFILE"' in main_body
        touch_pos = main_body.index('touch "$LOCKFILE"')
        stop_pos = main_body.index("stop_service\n")
        assert (
            touch_pos < stop_pos
        ), "Lockfile must be created before stop_service is called"

    def test_update_lockfile_removed_before_service_start(self):
        # JTN-685: The lockfile must be removed BEFORE update_app_service() is
        # called so that ExecStartPre does not see the lockfile and reject the
        # `systemctl start` invocation.  The old ordering (rm after start) caused
        # the first service-start after every update to fail.
        assert 'rm -f "$LOCKFILE"' in self.content
        # rm must come BEFORE update_app_service call (last occurrence, which is
        # the actual call site — the function definition also has the identifier)
        update_service_call_pos = self.content.rindex("\nupdate_app_service\n")
        rm_pos = self.content.rindex('rm -f "$LOCKFILE"')
        assert (
            rm_pos < update_service_call_pos
        ), "Lockfile removal must come BEFORE update_app_service call (JTN-685)"

    def test_update_has_exit_trap_for_lockfile(self):
        # JTN-685: Defense-in-depth EXIT trap so SIGTERM / unhandled exits clean
        # up the lockfile and don't permanently block the service.  Intentional
        # failure paths set _lockfile_keep=1 before exit so the lockfile is
        # preserved (forcing a manual rerun) while unhandled exits clear it.
        assert "trap " in self.content, "update.sh must set a trap for EXIT"
        assert "_lockfile_keep" in self.content, (
            "update.sh must use _lockfile_keep sentinel to distinguish "
            "intentional failure exits (keep lockfile) from abnormal exits (clear it)"
        )
        # The trap must be set after the lockfile is created
        lockfile_pos = self.content.index('touch "$LOCKFILE"')
        trap_pos = self.content.index("trap ")
        assert (
            trap_pos > lockfile_pos
        ), "EXIT trap must be set after the lockfile is created"

    def test_update_upgrades_pip_deps(self):
        assert "pip install" in self.content

    def test_update_enables_zramswap_on_bullseye_bookworm_trixie(self):
        # JTN-667: update.sh must use the same multi-release zramswap guard as
        # install.sh — previously it only matched Bookworm (12) so Trixie (13)
        # and Bullseye (11) users would OOM during pip install on update.
        assert "os_version=$(get_os_version)" in self.content
        assert '[[ "$os_version" =~ ^(11|12|13)$ ]]' in self.content
        assert "setup_zramswap_service" in self.content
        # The skip branch should still exist for unknown future releases.
        assert "skipping zramswap setup" in self.content

    def test_update_skips_zramtools_when_zram_swap_already_active(self):
        # JTN-667: setup_zramswap_service in update.sh must guard against
        # Trixie's preinstalled zram-swap to avoid /dev/zram0 conflicts.
        # JTN-674: setup_zramswap_service() now lives in _common.sh — check combined.
        guard = 'grep -q "^/dev/zram" /proc/swaps'
        apt_install = "apt-get install -y zram-tools"
        assert guard in self.combined
        assert "skipping zram-tools install" in self.combined
        assert "return 0" in self.combined

        fn_start = self.combined.index("setup_zramswap_service() {")
        guard_pos = self.combined.index(guard, fn_start)
        return_pos = self.combined.index("return 0", fn_start)
        apt_pos = self.combined.index(apt_install, fn_start)
        assert guard_pos < return_pos < apt_pos

    def test_update_codename_comment_has_no_trixie_typo(self):
        # JTN-667: The comment near get_os_version must spell Trixie correctly.
        # JTN-674: get_os_version() now lives in _common.sh — check combined.
        assert "13=Trixie" in self.combined
        assert "Trixe" not in self.combined  # typo guard

    def test_update_sources_common(self):
        # JTN-669: update.sh must source _common.sh to gain access to
        # fetch_wheelhouse / cleanup_wheelhouse so every update can use
        # pre-built wheels instead of source-compiling on the Pi.
        assert "_common.sh" in self.content
        assert 'source "$SCRIPT_DIR/_common.sh"' in self.content

    def test_update_calls_fetch_wheelhouse(self):
        # JTN-669: fetch_wheelhouse must be called before the pip upgrade
        # so the pre-built bundle is available when pip resolves packages.
        assert "fetch_wheelhouse" in self.content

    def test_update_calls_cleanup_wheelhouse(self):
        # The temp wheelhouse dir must always be cleaned up after install.
        assert "cleanup_wheelhouse" in self.content

    def test_update_pip_uses_find_links_when_available(self):
        # When the wheelhouse is available, pip must be pointed at it via
        # --find-links so binary wheels are preferred over source builds.
        assert "--find-links" in self.content
        assert "--prefer-binary" in self.content
        assert "WHEELHOUSE_DIR" in self.content

    def test_update_pip_uses_no_cache_dir(self):
        # JTN-602 parity: --no-cache-dir saves ~200 MB on the SD card.
        # The pip install line in update.sh must carry the flag.
        pip_lines = [
            line
            for line in self.content.splitlines()
            if re.search(r"-m pip install", line) and not line.strip().startswith("#")
        ]
        assert pip_lines, "no pip install calls found in update.sh"
        for line in pip_lines:
            assert (
                "--no-cache-dir" in line
            ), f"JTN-602 parity — pip install in update.sh missing --no-cache-dir: {line!r}"

    def test_update_installs_uv_into_venv(self):
        # JTN-670 / JTN-605 parity: uv must be installed into the venv so that
        # every update uses the low-memory uv resolver (~10-20 MB peak vs pip's
        # ~100-150 MB). This prevents OOM thrashing on Pi Zero 2 W updates.
        uv_install_lines = [
            line
            for line in self.content.splitlines()
            if re.search(r"-m pip install", line)
            and " uv" in line
            and not line.strip().startswith("#")
        ]
        assert (
            uv_install_lines
        ), "update.sh must have a 'pip install ... uv' call (JTN-670)"
        for line in uv_install_lines:
            assert (
                "--no-cache-dir" in line
            ), f"pip install uv in update.sh missing --no-cache-dir: {line!r}"

    def test_update_uses_uv_pip_install_for_requirements(self):
        # JTN-670 / JTN-605 parity: update.sh must prefer uv pip install when uv
        # is available, mirroring install.sh's create_venv() pattern.
        assert (
            "uv pip install" in self.content
        ), "update.sh must use 'uv pip install' for dependency install (JTN-670)"

    def test_update_uses_require_hashes(self):
        # JTN-670 / JTN-516 parity: supply-chain integrity must be enforced on
        # every update, not just fresh installs. Both the uv path and the pip
        # fallback must carry --require-hashes.
        lines = self.content.splitlines()
        # Collect joined continuation blocks that are install commands referencing
        # requirements (contains pip/uv install and PIP_REQUIREMENTS_FILE, but not
        # a bare variable assignment like PIP_REQUIREMENTS_FILE="...").
        install_blocks: list[str] = []
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            current.append(stripped.rstrip("\\").strip())
            if not stripped.endswith("\\"):
                block = " ".join(current)
                if "PIP_REQUIREMENTS_FILE" in block and (
                    "pip install" in block or "uv pip install" in block
                ):
                    install_blocks.append(block)
                current = []

        assert (
            install_blocks
        ), "update.sh must have an install invocation referencing PIP_REQUIREMENTS_FILE"
        for block in install_blocks:
            assert "--require-hashes" in block, (
                f"update.sh requirements install block missing --require-hashes "
                f"(JTN-670/JTN-516): {block!r}"
            )

    def test_update_uv_install_has_http_timeout(self):
        # JTN-670 / JTN-534 parity: uv pip install invocations must prefix
        # UV_HTTP_TIMEOUT=60 to survive flaky Wi-Fi on Pi Zero 2 W.
        # uv doesn't accept --default-timeout as a CLI flag; the env var scopes
        # the timeout to that subprocess only and doesn't leak.
        lines = self.content.splitlines()
        uv_install_indices = [
            i for i, line in enumerate(lines) if "-m uv pip install" in line
        ]
        assert (
            uv_install_indices
        ), "update.sh must have at least one 'uv pip install' invocation (JTN-670)"
        for idx in uv_install_indices:
            prev = lines[idx - 1] if idx > 0 else ""
            assert "UV_HTTP_TIMEOUT" in lines[idx] or "UV_HTTP_TIMEOUT" in prev, (
                "uv pip install in update.sh must prefix UV_HTTP_TIMEOUT "
                "for Wi-Fi resilience (JTN-534)"
            )

    def test_update_has_uv_pip_fallback_with_require_hashes(self):
        # JTN-670 / JTN-605 parity: if uv is unavailable, update.sh must fall
        # back to pip with --require-hashes preserved. The pip install and the
        # -r <requirements> flag are on separate continuation lines, so join them.
        assert (
            "use_uv" in self.content
        ), "update.sh must gate uv vs pip path on a use_uv flag (JTN-670)"
        lines = self.content.splitlines()
        # Collect joined continuation blocks: a block that contains `-m pip install`
        # AND references the requirements file (via -r "$PIP_REQUIREMENTS_FILE"),
        # but NOT via the uv installer.
        current: list[str] = []
        pip_fallback_blocks: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            current.append(stripped.rstrip("\\").strip())
            if not stripped.endswith("\\"):
                block = " ".join(current)
                if (
                    re.search(r"-m pip install", block)
                    and "PIP_REQUIREMENTS_FILE" in block
                    and "uv pip install" not in block
                ):
                    pip_fallback_blocks.append(block)
                current = []

        assert (
            pip_fallback_blocks
        ), "update.sh must retain a pip-based fallback install of PIP_REQUIREMENTS_FILE (JTN-670)"
        for block in pip_fallback_blocks:
            assert (
                "--require-hashes" in block
            ), "pip fallback in update.sh must preserve --require-hashes (JTN-670/JTN-516)"
            assert (
                "--no-cache-dir" in block
            ), "pip fallback in update.sh must preserve --no-cache-dir (JTN-670/JTN-602)"

    def test_update_uv_install_uses_no_cache(self):
        # JTN-670 / JTN-602 parity: uv pip install must use --no-cache (uv's
        # equivalent of pip's --no-cache-dir) to avoid wasting SD space on updates.
        lines = self.content.splitlines()
        current: list[str] = []
        uv_req_blocks: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            current.append(stripped.rstrip("\\").strip())
            if not stripped.endswith("\\"):
                block = " ".join(current)
                if "uv pip install" in block and "PIP_REQUIREMENTS_FILE" in block:
                    uv_req_blocks.append(block)
                current = []
        assert (
            uv_req_blocks
        ), "update.sh must have a 'uv pip install ... -r PIP_REQUIREMENTS_FILE' block"
        for block in uv_req_blocks:
            assert (
                "--no-cache" in block
            ), f"uv pip install in update.sh missing --no-cache (JTN-602 parity): {block!r}"


# ---- uninstall.sh ----


class TestUninstallScript:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("uninstall.sh")

    def test_uninstall_stops_service(self):
        assert "systemctl stop" in self.content or "systemctl is-active" in self.content

    def test_uninstall_disables_service(self):
        assert "systemctl disable" in self.content

    def test_uninstall_removes_install_dir(self):
        assert "rm -rf" in self.content


# ---- Cross-file consistency ----


def test_requirements_files_exist():
    assert (INSTALL_DIR / "requirements.txt").exists()
    assert (INSTALL_DIR / "debian-requirements.txt").exists()


def test_service_exec_matches_cli_wrapper():
    service = _read("inkypi.service")
    # ExecStart references /usr/local/bin/inkypi
    assert "/usr/local/bin/inkypi" in service
    cli = _read("inkypi")
    # CLI installs to PROGRAM_PATH=/usr/local/inkypi
    assert "PROGRAM_PATH=/usr/local/inkypi" in cli


def test_install_references_valid_config_base():
    assert (INSTALL_DIR / "config_base").is_dir()


# ---- cloud_init_clean.sh (JTN-591) ----


class TestCloudInitCleanScript:
    """Structural validation for the cloud-init cleanup helper (JTN-591)."""

    def test_script_exists(self):
        assert (SCRIPTS_DIR / "cloud_init_clean.sh").exists()

    def test_script_is_executable(self):
        import stat

        path = SCRIPTS_DIR / "cloud_init_clean.sh"
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, "cloud_init_clean.sh is not user-executable"

    def test_script_syntax_valid(self):
        import subprocess

        result = subprocess.run(
            ["bash", "-n", str(SCRIPTS_DIR / "cloud_init_clean.sh")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"

    def test_script_has_set_euo_pipefail(self):
        content = (SCRIPTS_DIR / "cloud_init_clean.sh").read_text()
        assert "set -euo pipefail" in content

    def test_script_checks_cloud_init_installed(self):
        content = (SCRIPTS_DIR / "cloud_init_clean.sh").read_text()
        assert "command -v cloud-init" in content

    def test_script_calls_cloud_init_clean(self):
        content = (SCRIPTS_DIR / "cloud_init_clean.sh").read_text()
        assert "cloud-init clean" in content


class TestInstallationDocCloudInit:
    """Verify the cloud-init runcmd one-shot trap is documented (JTN-591)."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = (DOCS_DIR / "installation.md").read_text()

    def test_cloud_init_re_edit_section_exists(self):
        # The section header must mention both cloud-init and re-editing user-data.
        assert "Re-editing user-data after first boot" in self.content

    def test_documents_per_instance_one_shot_behaviour(self):
        assert "per-instance" in self.content

    def test_documents_instance_id_file_path(self):
        assert "/var/lib/cloud/data/instance-id" in self.content

    def test_documents_clean_logs_recovery_command(self):
        assert "cloud-init clean --logs" in self.content

    def test_documents_reboot_after_clean(self):
        assert "sudo reboot" in self.content

    def test_references_jtn_591(self):
        assert "JTN-591" in self.content


# ---- test_install_memcap.sh Phase 4 RSS budgets (JTN-608 / JTN-613) ----


class TestInstallMemcapSmoke:
    """Structural guards for scripts/test_install_memcap.sh Phase 4.

    JTN-608 added idle/peak RSS budgets but the first Phase 4 run reported
    peak == idle because the /update_now POST was blocked by CSRF before any
    render code ran. JTN-613 fixes the measurement by (a) hitting a CSRF-exempt
    opt-in /__smoke/render endpoint and (b) asserting peak > idle + floor so a
    broken harness fails loudly instead of silently green-lighting.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.path = SCRIPTS_DIR / "test_install_memcap.sh"
        self.content = self.path.read_text()

    def test_script_exists_and_is_executable(self):
        import stat

        assert self.path.exists()
        assert self.path.stat().st_mode & stat.S_IXUSR

    def test_script_syntax_valid(self):
        import subprocess

        result = subprocess.run(
            ["bash", "-n", str(self.path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"

    def test_phase4_hard_budgets_unchanged(self):
        # JTN-613 must not regress the JTN-608 thresholds.
        assert "IDLE_RSS_HARD_MB=200" in self.content
        assert "PEAK_RSS_HARD_MB=300" in self.content

    def test_phase4_enables_smoke_force_render_env_var(self):
        # The Phase 3 Dockerfile must set the opt-in env var so the smoke
        # render endpoint actually registers inside the container.
        assert "INKYPI_SMOKE_FORCE_RENDER=1" in self.content, (
            "Phase 3 Dockerfile must export INKYPI_SMOKE_FORCE_RENDER=1 so "
            "the /__smoke/render endpoint is registered (JTN-613)."
        )

    def test_phase4_hits_smoke_render_endpoint(self):
        # The render-exercise loop must call the opt-in endpoint.
        assert "/__smoke/render" in self.content, (
            "Phase 4 must POST to /__smoke/render so the render path is "
            "actually exercised (JTN-613)."
        )

    def test_phase4_posts_clock_plugin_to_smoke_render(self):
        # We stress the clock plugin because it has no external HTTP deps.
        assert "plugin_id=clock" in self.content

    def test_phase4_no_longer_uses_update_now_to_trigger_render(self):
        # JTN-613 root cause: POST /update_now was blocked by CSRF in web-only
        # mode so the render path never ran. The smoke test must no longer
        # rely on /update_now for peak RSS measurement.
        #
        # We allow the string "update_now" in comments that explain WHY it was
        # removed, but it must not appear as an actual curl target.
        lines = self.content.splitlines()
        curl_lines = [
            ln
            for ln in lines
            if "curl" in ln and "update_now" in ln and not ln.strip().startswith("#")
        ]
        assert not curl_lines, (
            "scripts/test_install_memcap.sh must not curl /update_now for the "
            "render exercise — it was CSRF-blocked before reaching render code "
            "(JTN-613). Use /__smoke/render instead. Offending lines: "
            f"{curl_lines}"
        )

    def test_phase4_asserts_peak_greater_than_idle(self):
        # JTN-613 sanity gate: a valid Phase 4 run must show peak > idle. If
        # they're equal, the render exercise never ran and we must fail loud.
        assert "PEAK_RSS_MIN_DELTA_MB" in self.content, (
            "Phase 4 must define a minimum delta floor (PEAK_RSS_MIN_DELTA_MB) "
            "between idle and peak RSS (JTN-613)."
        )
        assert "RSS_DELTA_MB" in self.content, (
            "Phase 4 must compute and log the idle-to-peak RSS delta " "(JTN-613)."
        )
        # And the check must actually exit on failure — not just log.
        assert (
            '${RSS_DELTA_MB}" -lt "${PEAK_RSS_MIN_DELTA_MB}' in self.content
            or "RSS_DELTA_MB < PEAK_RSS_MIN_DELTA_MB" in self.content
        ), "Phase 4 must compare delta against the minimum and exit on failure."

    def test_phase4_smoke_render_failure_aborts_the_script(self):
        # If /__smoke/render returns anything other than 200, the harness is
        # broken and we must fail loud — not silently skip the peak budget.
        assert '${SMOKE_RENDER_STATUS}" != "200"' in self.content, (
            "Phase 4 must abort when /__smoke/render returns a non-200 status "
            "(JTN-613)."
        )

    def test_phase4_renders_multiple_times_for_sustained_working_set(self):
        # Rendering once can get optimised away by Python's allocator; we hit
        # the endpoint repeatedly so peak RSS reflects the sustained footprint.
        # The exact count is not load-bearing — just assert there is a loop.
        import re

        # Match either a `for ... in 1 2 3` or similar looping construct in
        # proximity to the smoke render curl call.
        assert re.search(
            r"for\s+\w+\s+in\s+[0-9]+\s+[0-9]+",
            self.content,
        ), (
            "Phase 4 must render the plugin in a loop so peak RSS reflects "
            "the sustained working set, not a transient single allocation "
            "(JTN-613)."
        )

    def test_phase4_references_jtn_613(self):
        # Traceability: the JTN-613 fix must be discoverable by grepping.
        assert "JTN-613" in self.content


# ---- install-matrix CI workflow (JTN-530) ----

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


class TestInstallMatrixWorkflow:
    """Structural guards for the arm64 install.sh matrix CI job (JTN-530)."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.ci_yaml = (WORKFLOWS_DIR / "ci.yml").read_text()
        self.dockerfile = (SCRIPTS_DIR / "Dockerfile.install-matrix").read_text()
        self.verify_script = (SCRIPTS_DIR / "ci_install_matrix_verify.sh").read_text()

    def test_install_matrix_job_defined(self):
        assert "install-matrix:" in self.ci_yaml

    def test_install_matrix_references_supported_os_bases(self):
        # JTN-615: bullseye was removed from the ci.yml install-matrix
        # because Debian 11 ships Python 3.9.2 while InkyPi's requirements
        # pin packages that need Python>=3.10 (anyio==4.13.0 is the first
        # to bomb the uv resolver). pyproject.toml also targets py311. The
        # standalone Install matrix (arm64 e2e) workflow still exercises
        # bullseye via test_install_memcap.sh because that path uses a
        # python:3.12-slim base image and therefore isn't blocked by the
        # codename's own interpreter version.
        import yaml

        data = yaml.safe_load(self.ci_yaml)
        job = data["jobs"]["install-matrix"]
        codenames = job["strategy"]["matrix"]["codename"]
        assert set(codenames) == {"bookworm", "trixie"}

    def test_install_matrix_runs_on_arm64(self):
        assert "linux/arm64" in self.ci_yaml
        assert "setup-qemu-action" in self.ci_yaml

    def test_install_matrix_uses_512m_memory_cap(self):
        assert "--memory=512m" in self.ci_yaml
        assert "--memory-swap=512m" in self.ci_yaml

    def test_install_matrix_invokes_verify_script(self):
        assert "ci_install_matrix_verify.sh" in self.ci_yaml

    def test_install_matrix_feeds_ci_gate(self):
        import yaml

        data = yaml.safe_load(self.ci_yaml)
        gate = data["jobs"]["ci-gate"]
        assert "install-matrix" in gate["needs"]
        gate_steps_raw = yaml.safe_dump(gate["steps"])
        assert "install-matrix" in gate_steps_raw

    def test_dockerfile_uses_plain_debian_codename(self):
        assert "FROM debian:${CODENAME}" in self.dockerfile
        assert "CODENAME=trixie" in self.dockerfile

    def test_dockerfile_adds_pi_os_apt_repo(self):
        assert "archive.raspberrypi.com/debian" in self.dockerfile

    def test_dockerfile_ships_raspi_config_shim(self):
        assert "/usr/sbin/raspi-config" in self.dockerfile

    def test_dockerfile_ships_systemctl_shim(self):
        assert "/usr/bin/systemctl" in self.dockerfile

    def test_dockerfile_installs_systemd_package(self):
        assert "systemd" in self.dockerfile

    def test_dockerfile_creates_boot_config_stub(self):
        assert "/boot/firmware/config.txt" in self.dockerfile

    def test_verify_script_asserts_install_exit_zero(self):
        assert "./install.sh" in self.verify_script
        assert "exit" in self.verify_script

    def test_verify_script_asserts_venv_created(self):
        assert "/usr/local/inkypi/venv_inkypi" in self.verify_script

    def test_verify_script_asserts_required_imports(self):
        # JTN-615: the check was rewritten to use importlib.metadata.version()
        # because waitress has no module-level __version__ attribute and Flask
        # 3.2 deprecates its own `__version__`. The test now asserts the three
        # distribution names are still covered rather than pinning a specific
        # import-statement string.
        for dist in ("flask", "waitress", "Pillow"):
            assert (
                dist in self.verify_script
            ), f"Phase 3 verification script must still check {dist}"
        # And the three module names that correspond to those distributions.
        for mod in ("flask", "waitress", "PIL"):
            assert mod in self.verify_script

    def test_verify_script_runs_systemd_analyze(self):
        assert "systemd-analyze verify" in self.verify_script
        assert "inkypi.service" in self.verify_script

    def test_verify_script_skips_wheelhouse(self):
        assert "INKYPI_SKIP_WHEELHOUSE=1" in self.verify_script

    def test_verify_script_has_shebang_and_strict_mode(self):
        assert self.verify_script.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in self.verify_script

    def test_verify_script_is_executable(self):
        import stat

        path = SCRIPTS_DIR / "ci_install_matrix_verify.sh"
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR


# ---- OS drift nightly workflow (JTN-535) ----


class TestOsDriftNightlyWorkflow:
    """Structural assertions for the nightly OS-drift detector (JTN-535)."""

    WORKFLOW_PATH = WORKFLOWS_DIR / "os-drift-nightly.yml"

    @pytest.fixture(autouse=True)
    def _load(self):
        assert self.WORKFLOW_PATH.exists(), (
            "os-drift-nightly.yml is missing — the JTN-535 drift detector "
            "must not be deleted without an explicit follow-up issue."
        )
        self.content = self.WORKFLOW_PATH.read_text()

    def test_workflow_file_exists(self):
        assert self.WORKFLOW_PATH.is_file()

    def test_has_schedule_block(self):
        assert re.search(r"^\s*schedule:", self.content, flags=re.MULTILINE)
        assert re.search(r"cron:\s*['\"]0 8 \* \* \*['\"]", self.content)

    def test_has_workflow_dispatch(self):
        assert "workflow_dispatch:" in self.content

    def test_is_not_a_pr_gate(self):
        assert "pull_request:" not in self.content

    def test_matrix_covers_all_three_codenames(self):
        for codename in ("trixie", "bookworm", "bullseye"):
            assert codename in self.content

    def test_uses_unpinned_debian_images(self):
        assert re.search(
            r"image:\s*debian:\$\{\{\s*matrix\.codename\s*\}\}",
            self.content,
        )

    def test_asserts_debian_and_pip_requirements(self):
        assert "install/debian-requirements.txt" in self.content
        assert "install/requirements.txt" in self.content
        assert "apt-cache show" in self.content
        assert "--dry-run" in self.content

    def test_runs_end_to_end_install_sim(self):
        assert "scripts/sim_install.sh" in self.content

    def test_files_issue_on_failure(self):
        assert "actions/github-script" in self.content
        assert "os-drift" in self.content
        assert "issues.create" in self.content

    def test_references_jtn_535(self):
        assert "JTN-535" in self.content

    def test_workflow_parses_as_yaml(self):
        parsed = yaml.safe_load(self.content)
        assert isinstance(parsed, dict)
        assert "on" in parsed or True in parsed
        assert "jobs" in parsed

        jobs = parsed["jobs"]
        assert isinstance(jobs, dict)
        matrix = jobs["drift-check"]["strategy"]["matrix"]
        assert isinstance(matrix, dict)
        assert isinstance(matrix["codename"], list)


# ---- memory-diff workflow ----


class TestMemoryDiffWorkflow:
    """JTN-610: per-PR memory diff sticky comment."""

    WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "memory-diff.yml"
    SCRIPTS_DIR = REPO_ROOT / "scripts"

    @pytest.fixture(autouse=True)
    def _load(self):
        assert self.WORKFLOW_PATH.exists(), (
            f"Expected memory-diff workflow at {self.WORKFLOW_PATH}. "
            "See JTN-610 for the per-PR memory diff comment design."
        )
        self.content = self.WORKFLOW_PATH.read_text()

    def test_workflow_runs_on_pull_requests(self):
        assert "pull_request:" in self.content

    def test_workflow_cancels_superseded_runs(self):
        assert "concurrency:" in self.content
        assert "cancel-in-progress: true" in self.content

    def test_workflow_references_memray(self):
        assert "memray" in self.content

    def test_workflow_is_non_blocking(self):
        assert "continue-on-error: true" in self.content

    def test_workflow_invokes_helper_scripts(self):
        assert "scripts/memory_diff.py" in self.content
        assert "scripts/format_memory_diff.py" in self.content

    def test_workflow_posts_sticky_comment(self):
        assert "github-script" in self.content or "comment-pull-request" in self.content
        assert "memory-diff:jtn-610" in self.content

    def test_workflow_grants_pr_write_permission(self):
        assert "pull-requests: write" in self.content

    def test_workflow_checks_out_base_branch(self):
        assert "github.base_ref" in self.content

    def test_capture_helper_exists_and_is_valid_python(self):
        helper = self.SCRIPTS_DIR / "memory_diff.py"
        assert helper.exists(), f"Missing {helper}"
        compile(helper.read_text(), str(helper), "exec")

    def test_formatter_helper_exists_and_is_valid_python(self):
        helper = self.SCRIPTS_DIR / "format_memory_diff.py"
        assert helper.exists(), f"Missing {helper}"
        compile(helper.read_text(), str(helper), "exec")

    def test_formatter_uses_stable_sticky_marker(self):
        formatter = (self.SCRIPTS_DIR / "format_memory_diff.py").read_text()
        assert 'STICKY_MARKER = "<!-- memory-diff:jtn-610 -->"' in formatter

    def test_capture_helper_supports_both_backends(self):
        capture = (self.SCRIPTS_DIR / "memory_diff.py").read_text()
        assert "memray" in capture
        assert "tracemalloc" in capture

    def test_memray_listed_in_requirements_dev_in(self):
        content = (INSTALL_DIR / "requirements-dev.in").read_text()
        assert "memray" in content, (
            "memray must be declared in install/requirements-dev.in so the "
            "memory-diff workflow can install it from the lockfile."
        )
