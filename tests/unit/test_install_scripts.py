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

    def test_service_has_no_memory_caps_in_base_unit(self):
        # JTN-785: The base unit must NOT hardcode MemoryHigh/MemoryMax.
        # install.sh and update.sh write device-specific caps to a drop-in at
        # /etc/systemd/system/inkypi.service.d/memory.conf so Pi Zero 2 W
        # (512 MB) gets a 350M/500M tier while ≥1 GB Pis keep the 250M/350M
        # tier. Baking caps into the git-tracked unit file was the root cause
        # of the chromium OOM-kill incident on 512 MB boards.
        assert "MemoryHigh=" not in self.content, (
            "MemoryHigh must live in the drop-in memory.conf (JTN-785), "
            "not the base unit, so per-device scaling works"
        )
        assert "MemoryMax=" not in self.content, (
            "MemoryMax must live in the drop-in memory.conf (JTN-785), "
            "not the base unit, so per-device scaling works"
        )

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

    def test_install_configures_persistent_journal_via_shared_helper(self):
        assert "configure_persistent_journal() {" in self.combined
        assert "Storage=persistent" in self.combined
        assert "SystemMaxUse=50M" in self.combined
        assert "RuntimeMaxUse=50M" in self.combined
        assert "/var/log/journal" in self.combined
        assert "systemctl restart systemd-journald" in self.combined

        earlyoom_pos = self.content.index("setup_earlyoom_service")
        journal_pos = self.content.index("configure_persistent_journal", earlyoom_pos)
        install_src_pos = self.content.index("install_src", journal_pos)
        assert earlyoom_pos < journal_pos < install_src_pos, (
            "install.sh must configure persistent journald after earlyoom setup "
            "and before copying the repo into place"
        )

    def test_install_disables_wifi_powersave_via_shared_helper(self):
        assert "disable_wifi_powersave() {" in self.combined
        assert "iw dev wlan0 set power_save off" in self.combined
        assert "100-inkypi-wifi-powersave.conf" in self.combined
        assert "wifi.powersave = 2" in self.combined
        assert "nmcli -g GENERAL.CONNECTION device show wlan0" in self.combined
        assert "802-11-wireless.powersave 2" in self.combined

        journal_pos = self.content.index("configure_persistent_journal")
        wifi_pos = self.content.index("disable_wifi_powersave", journal_pos)
        install_src_pos = self.content.index("install_src", wifi_pos)
        assert journal_pos < wifi_pos < install_src_pos, (
            "install.sh must harden Wi-Fi powersave after journald setup and "
            "before the source/venv work begins"
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

    def test_service_enable_gated_on_css_build(self):
        # JTN-695: systemctl enable / install_app_service must only run AFTER
        # vendor download + CSS build both succeed. If either step fails, the
        # service must be left untouched so `systemctl is-enabled inkypi`
        # reflects reality (not "enabled but main.css missing").
        main_start = self.content.index('parse_arguments "$@"')
        main_body = self.content[main_start:]

        # Use rindex for install_app_service so we locate the actual call site
        # at the bottom of the script rather than an earlier comment/reference.
        vendor_pos = main_body.index("update_vendors.sh")
        css_pos = main_body.index("build_css_bundle")
        install_app_pos = main_body.rindex("install_app_service")

        assert vendor_pos < install_app_pos, (
            "install.sh must invoke update_vendors.sh BEFORE install_app_service "
            "so a vendor-download failure exits before the systemd unit is "
            "enabled (JTN-695)"
        )
        assert css_pos < install_app_pos, (
            "install.sh must call build_css_bundle BEFORE install_app_service "
            "so a CSS build failure exits before the systemd unit is enabled "
            "(JTN-695)"
        )

    def test_install_asserts_main_css_exists_before_service_enable(self):
        # JTN-695: After build_css_bundle, install.sh must assert that
        # src/static/styles/main.css exists AND is non-empty (`-s`) before the
        # service is enabled. This catches silent truncation where the file
        # exists (so `-f` passes) but is zero bytes — which would otherwise
        # slip past build_css_bundle's existence-only check and leave the
        # service enabled against an unusable stylesheet.
        main_start = self.content.index('parse_arguments "$@"')
        main_body = self.content[main_start:]

        # A reference to main.css must appear in the main body, with an
        # accompanying non-empty-file test (`-s`) on the same variable.
        assert "main.css" in main_body, (
            "install.sh main body must reference src/static/styles/main.css "
            "for the post-build assertion (JTN-695)"
        )
        assert "-s " in main_body and '-s "$MAIN_CSS"' in main_body, (
            "install.sh must assert the CSS bundle is non-empty via '-s' "
            "before enabling the systemd unit (JTN-695)"
        )

        # Ordering: the main.css assertion must come AFTER build_css_bundle and
        # BEFORE install_app_service so a zero-byte stylesheet blocks enable.
        css_pos = main_body.index("build_css_bundle")
        assert_pos = main_body.index("MAIN_CSS=")
        install_app_pos = main_body.rindex("install_app_service")
        assert css_pos < assert_pos < install_app_pos, (
            "main.css existence/non-empty assertion must appear after "
            "build_css_bundle and before install_app_service (JTN-695)"
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

    def test_install_uses_flock_concurrent_guard(self):
        # JTN-696: install.sh must acquire an `flock -n` on a well-known lock
        # path before running the real install steps, so two simultaneous
        # `sudo bash install.sh` invocations fail fast instead of racing
        # each other through the rm/repopulate sequence.
        assert "FLOCK_PATH=" in self.content, (
            "install.sh must define FLOCK_PATH for the concurrent-install "
            "lock (JTN-696)"
        )
        assert "/var/lock/inkypi.install" in self.content, (
            "install.sh must use /var/lock/inkypi.install* as the concurrent "
            "install lock path (JTN-696)"
        )
        assert "flock -n" in self.content, (
            "install.sh must call 'flock -n' (non-blocking) to fail fast "
            "when the concurrent-install lock is already held (JTN-696)"
        )

        # The flock guard must appear before the main install steps (before
        # touching $LOCKFILE or running install_debian_dependencies).
        main_start = self.content.index('parse_arguments "$@"')
        main_body = self.content[main_start:]
        flock_pos = main_body.index("flock -n")
        touch_pos = main_body.index('touch "$LOCKFILE"')
        assert flock_pos < touch_pos, (
            "flock -n guard must run before the install-in-progress lockfile "
            "is created so a second caller is rejected before mutating any "
            "shared state (JTN-696)"
        )

        # Helpful error message when the lock is already held — users need to
        # understand why their second install attempt bailed out.
        assert "Another install/update is already running" in self.content, (
            "install.sh must print a clear error message when the "
            "concurrent-install lock is held (JTN-696)"
        )

    def test_install_uses_atomic_swap_not_in_place_rm(self):
        # JTN-696: install_src() must NOT do an in-place `rm -rf
        # "$INSTALL_PATH"` — that pattern left dangling symlinks / a
        # half-populated directory if the user hit Ctrl+C mid-delete.
        # The replacement pattern stages the new tree, then swaps it in
        # atomically with `mv -T`.
        fn_start = self.content.index("install_src() {")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]

        # Negative assertion: the old in-place delete pattern is gone.
        assert 'rm -rf "$INSTALL_PATH"' not in fn_body, (
            'install_src() must NOT `rm -rf "$INSTALL_PATH"` in place — '
            "use an atomic mv -T swap via a staging dir instead so Ctrl+C "
            "mid-install leaves the prior tree intact (JTN-696)"
        )

        # Positive assertion: staging + mv -T pattern is present.
        assert (
            "mv -T" in fn_body
        ), "install_src() must use `mv -T` for the atomic dir swap (JTN-696)"
        assert ".new" in fn_body, (
            "install_src() must build the new tree in a `$INSTALL_PATH.new` "
            "staging dir before the swap (JTN-696)"
        )

    def test_install_exit_trap_cleans_staging_not_lockfile(self):
        # JTN-696: The EXIT trap added to clean up staging dirs on an
        # interrupted install must NOT touch $LOCKFILE (that would defeat
        # JTN-607) and must NOT rm -rf $INSTALL_PATH itself (that would
        # destroy the prior install we're trying to protect).
        trap_lines = [
            line
            for line in self.content.splitlines()
            if line.strip().startswith("trap ") and "EXIT" in line
        ]
        assert trap_lines, (
            "install.sh must register at least one EXIT trap to clean up "
            "staging dirs after an interrupted install (JTN-696)"
        )
        for line in trap_lines:
            assert (
                "$LOCKFILE" not in line
            ), f"JTN-696 EXIT trap must not remove $LOCKFILE: {line!r}"

        # Locate the cleanup function body and verify it doesn't do a bare
        # `rm -rf "$INSTALL_PATH"` that would nuke a healthy prior install.
        fn_start = self.content.index("_cleanup_staging() {")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]
        for line in fn_body.splitlines():
            stripped = line.strip()
            if 'rm -rf "$INSTALL_PATH"' in stripped:
                pytest.fail(
                    '_cleanup_staging must not `rm -rf "$INSTALL_PATH"` '
                    "directly — that destroys a healthy prior install "
                    f"(JTN-696): {line!r}"
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

    def test_fetch_wheelhouse_verifies_integrity(self):
        # JTN-697: After extraction, every wheel must be integrity-checked.
        # The original "at least one .whl exists" gate let truncated bundles
        # (zero-byte numpy wheels, corrupt zips) pass, with ImportError only
        # surfacing on first display refresh.
        body = self._fetch_fn_body()

        # Guard 1: empty-wheel rejection must exist and appear AFTER the
        # "at least one .whl" existence check so we actually iterate every
        # extracted wheel rather than just checking presence.
        assert (
            "[ ! -s " in body or '! -s "$whl"' in body
        ), "fetch_wheelhouse must reject empty (zero-byte) wheels"

        # Guard 2: structural zip check using python -m zipfile — pip refuses
        # to install malformed zips and we want to catch them before pip sees
        # them so the fallback is cleaner.
        assert (
            "python3 -m zipfile" in body
        ), "fetch_wheelhouse must validate each wheel is a readable zip"

        # Guard 3 (preferred): per-wheel sha256 manifest verification.
        # Accept either `sha256sum -c` or the shasum fallback.
        assert ".manifest.sha256" in body
        assert "sha256sum -c" in body or "shasum -a 256 -c" in body, (
            "fetch_wheelhouse must verify wheels against the published "
            "per-wheel sha256 manifest when available"
        )

        # The new integrity gate must precede WHEELHOUSE_DIR assignment so
        # callers never see a populated dir on corrupt input.
        integrity_pos = body.index("python3 -m zipfile")
        set_pos = body.index('WHEELHOUSE_DIR="$extract_dir"')
        assert (
            integrity_pos < set_pos
        ), "integrity checks must run before WHEELHOUSE_DIR is exposed"

        # Failure paths must still rm -rf and return 1 so the caller falls
        # back to source install.
        # (Covered structurally by test_fetch_is_graceful_on_curl_failure;
        # here we assert the new fail messages route through the same path.)
        assert "Wheelhouse integrity check failed" in body
        assert "manifest sha256 mismatch" in body.lower()

    def test_fetch_wheelhouse_rejects_empty_wheel_integration(self, tmp_path):
        # JTN-697 integration: craft a wheelhouse tarball containing a
        # zero-byte .whl, then invoke fetch_wheelhouse with curl stubbed
        # to serve it from disk. Expect non-zero exit + empty WHEELHOUSE_DIR.
        import shutil
        import subprocess
        import zipfile as _zipfile

        if not shutil.which("bash") or not shutil.which("tar"):
            pytest.skip("bash/tar not available")

        wheels_src = tmp_path / "wheels_src"
        wheels_src.mkdir()
        # Zero-byte wheel → the exact failure mode in the issue.
        (wheels_src / "numpy-1.0.0-cp313-cp313-linux_armv7l.whl").write_bytes(b"")
        # Also drop a valid zip so the "at least one .whl" gate passes.
        good = wheels_src / "pillow-10.0.0-cp313-cp313-linux_armv7l.whl"
        with _zipfile.ZipFile(good, "w") as zf:
            zf.writestr("pillow-10.0.0.dist-info/METADATA", "Name: pillow\n")

        tarball = tmp_path / "inkypi-wheels-9.9.9-linux_armv7l.tar.gz"
        subprocess.run(
            ["tar", "-czf", str(tarball), "-C", str(wheels_src), "."],
            check=True,
        )

        # Stub curl: serve tarball, 404 for sha/manifest (exercises structural
        # guard, not manifest-mismatch guard).
        stub_dir = tmp_path / "stub_bin"
        stub_dir.mkdir()
        stub_curl = stub_dir / "curl"
        stub_curl.write_text(f"""#!/usr/bin/env bash
out=""
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output) out="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
case "$url" in
  *.tar.gz) cp {tarball} "$out" ;;
  *) exit 22 ;;
esac
""")
        stub_curl.chmod(0o755)

        stub_uname = stub_dir / "uname"
        stub_uname.write_text("""#!/usr/bin/env bash
if [ "$1" = "-m" ]; then echo armv7l; else /usr/bin/uname "$@"; fi
""")
        stub_uname.chmod(0o755)

        script_dir = tmp_path / "install"
        script_dir.mkdir()
        (tmp_path / "VERSION").write_text("9.9.9\n")
        shutil.copy(INSTALL_DIR / "_common.sh", script_dir / "_common.sh")

        harness = tmp_path / "run.sh"
        harness.write_text(f"""#!/usr/bin/env bash
set +e
export PATH="{stub_dir}:$PATH"
SCRIPT_DIR="{script_dir}"
source "$SCRIPT_DIR/_common.sh"
fetch_wheelhouse
rc=$?
echo "RC=$rc"
echo "DIR=[$WHEELHOUSE_DIR]"
""")
        harness.chmod(0o755)

        result = subprocess.run(
            ["bash", str(harness)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        combined = result.stdout + result.stderr
        assert "RC=1" in combined, f"expected rc=1, got:\n{combined}"
        assert (
            "DIR=[]" in combined
        ), f"WHEELHOUSE_DIR must be empty on failure, got:\n{combined}"
        assert "integrity check failed" in combined.lower()


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

    def test_workflow_supports_reusable_invocation(self):
        # JTN-745: release.yml calls this workflow directly so a failed
        # wheelhouse upload makes the main Release workflow fail too.
        assert "workflow_call:" in self.content
        assert "inputs:" in self.content
        assert "required: true" in self.content

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

    def test_workflow_installs_native_build_dependencies(self):
        # JTN-745 regression guards: armv7l source builds need libsystemd-dev
        # for cysystemd and libheif-dev for pi-heif when PyPI lacks a wheel.
        assert "libsystemd-dev" in self.content
        assert "libheif-dev" in self.content

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

    def test_workflow_publishes_per_wheel_manifest(self):
        # JTN-697: In addition to the tarball-level sha256, publish a
        # per-wheel sha256 manifest so install.sh can detect individual
        # truncated/corrupt wheels hiding inside an otherwise-valid tarball.
        assert ".manifest.sha256" in self.content
        # Manifest must be produced from the built wheels and uploaded as
        # a release asset alongside the tarball.
        assert "sha256sum *.whl" in self.content


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


class TestReleaseWorkflow:
    """JTN-745: release.yml must fail when wheelhouse publication fails."""

    WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"

    @pytest.fixture(autouse=True)
    def _load(self):
        assert (
            self.WORKFLOW_PATH.exists()
        ), f"Expected workflow file at {self.WORKFLOW_PATH}"
        self.content = self.WORKFLOW_PATH.read_text()

    def test_release_exports_tag_for_downstream_jobs(self):
        assert "outputs:" in self.content
        assert "steps.resolve_tag.outputs.tag" in self.content
        assert "steps.resolve_tag.outputs.released" in self.content

    def test_release_invokes_reusable_wheelhouse_workflow(self):
        assert "uses: ./.github/workflows/build-wheelhouse.yml" in self.content
        assert "needs: release" in self.content
        assert "needs.release.outputs.released == 'true'" in self.content
        assert "tag: ${{ needs.release.outputs.tag }}" in self.content


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
        # JTN-704: EXIT trap unconditionally removes the lockfile on every exit
        # (success, explicit exit N, errexit, SIGINT, SIGTERM, SIGHUP) so a
        # failed update never leaves the service permanently blocked by a
        # stale /var/lib/inkypi/.install-in-progress. On non-zero exit the
        # trap also writes /var/lib/inkypi/.last-update-failure with
        # structured metadata (timestamp, exit_code, last_command,
        # recent_journal_lines) for UI surfacing and diagnostics.
        assert "trap " in self.content, "update.sh must set a trap for EXIT"
        # The new policy must not keep the lockfile on failure — the stale
        # _lockfile_keep sentinel from the old JTN-685 implementation must be
        # gone (or we will regress back to the JTN-704 problem).
        assert "_lockfile_keep" not in self.content, (
            "update.sh must NOT use _lockfile_keep sentinel under JTN-704; "
            "the trap unconditionally clears the lockfile on every exit."
        )
        # Must register an EXIT trap that references the lockfile cleanup.
        assert "trap _inkypi_update_exit_trap EXIT" in self.content, (
            "update.sh must register an EXIT trap that cleans the lockfile "
            "and records failure metadata (JTN-704)"
        )
        # Trap body must remove the lockfile unconditionally on EXIT.
        assert (
            'rm -f "$LOCKFILE"' in self.content
        ), "update.sh EXIT trap must rm the lockfile on every exit (JTN-704)"
        # Trap body must write .last-update-failure on non-zero exit.
        assert "FAILURE_FILE=" in self.content, (
            "update.sh must define FAILURE_FILE for the failure-recording "
            "trap (JTN-704)"
        )
        assert ".last-update-failure" in self.content, (
            "update.sh must reference /var/lib/inkypi/.last-update-failure "
            "so the EXIT trap can persist the reason for a failed update "
            "(JTN-704)"
        )
        # Required JSON keys in the failure record for downstream parsers.
        for key in ("timestamp", "exit_code", "last_command", "recent_journal_lines"):
            assert (
                f'"{key}"' in self.content
            ), f"update.sh failure JSON must include {key!r} key (JTN-704)"
        # Trap must also fire on SIGINT / SIGTERM / SIGHUP.
        assert (
            "trap 'exit 130' INT" in self.content
        ), "update.sh must trap SIGINT so Ctrl-C still cleans the lockfile"
        assert (
            "trap 'exit 143' TERM" in self.content
        ), "update.sh must trap SIGTERM so systemd-stop still cleans the lockfile"
        # The trap must be set after the lockfile is created.
        lockfile_pos = self.content.index('touch "$LOCKFILE"')
        trap_pos = self.content.index("trap _inkypi_update_exit_trap EXIT")
        assert (
            trap_pos > lockfile_pos
        ), "EXIT trap must be registered after the lockfile is created"

    def test_update_exposes_test_failure_injection_env_var(self):
        # JTN-704: The integration test needs a guarded env-var hook to
        # simulate a mid-update failure without touching production paths.
        # The hook is a no-op unless INKYPI_UPDATE_TEST_FAIL_AT is set.
        assert "INKYPI_UPDATE_TEST_FAIL_AT" in self.content, (
            "update.sh must expose an env-var-guarded test failure "
            "injection hook (INKYPI_UPDATE_TEST_FAIL_AT) so the regression "
            "test can simulate failure at a named step (JTN-704)"
        )

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

    def test_update_configures_persistent_journal_via_shared_helper(self):
        assert "configure_persistent_journal() {" in self.combined
        assert "Storage=persistent" in self.combined
        assert "RuntimeMaxUse=50M" in self.combined

        earlyoom_pos = self.content.index("setup_earlyoom_service")
        journal_pos = self.content.index("configure_persistent_journal", earlyoom_pos)
        venv_pos = self.content.index('_current_step="venv_check"')
        assert earlyoom_pos < journal_pos < venv_pos, (
            "update.sh must configure persistent journald after earlyoom setup "
            "and before venv / pip work starts"
        )

    def test_update_disables_wifi_powersave_via_shared_helper(self):
        assert "disable_wifi_powersave() {" in self.combined
        assert "iw dev wlan0 set power_save off" in self.combined
        assert "100-inkypi-wifi-powersave.conf" in self.combined
        assert "802-11-wireless.powersave 2" in self.combined

        journal_pos = self.content.index("configure_persistent_journal")
        wifi_pos = self.content.index("disable_wifi_powersave", journal_pos)
        venv_pos = self.content.index('_current_step="venv_check"')
        assert journal_pos < wifi_pos < venv_pos, (
            "update.sh must harden Wi-Fi powersave after journald setup and "
            "before dependency updates begin"
        )

    def test_update_calls_fetch_wheelhouse(self):
        # JTN-669: fetch_wheelhouse must be called before the pip upgrade
        # so the pre-built bundle is available when pip resolves packages.
        assert "fetch_wheelhouse" in self.content

    def test_update_calls_cleanup_wheelhouse(self):
        # The temp wheelhouse dir must always be cleaned up after install.
        assert "cleanup_wheelhouse" in self.content

    def test_update_reports_version_from_checked_out_repo(self):
        assert "$SCRIPT_DIR/../VERSION" in self.content
        assert "$INSTALL_PATH/VERSION" not in self.content

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

    def test_update_refreshes_apt_index_before_install(self):
        # JTN-788: update.sh must run `apt-get update` synchronously before
        # `apt-get install` so a stale /var/lib/apt/lists/ cache does not
        # abort the update when the Raspberry Pi archive has published a
        # package point-release since the last update. The previous
        # implementation backgrounded `apt-get update` (with `&`), which
        # raced against the install and left it reading a stale index in
        # practice.
        apt_update_lines = [
            line
            for line in self.content.splitlines()
            if re.search(r"\bapt-get update\b", line)
            and not line.strip().startswith("#")
        ]
        assert apt_update_lines, (
            "update.sh must call apt-get update before apt-get install " "(JTN-788)"
        )
        for line in apt_update_lines:
            assert not line.rstrip().endswith("&"), (
                "JTN-788: apt-get update must run synchronously; "
                f"backgrounded invocation is the bug: {line!r}"
            )
        # apt-get update must precede apt-get install in the main script
        # body so the install sees a freshly-refreshed index.
        update_pos = self.content.index("apt-get update")
        install_pos = self.content.index("apt-get install")
        assert (
            update_pos < install_pos
        ), "JTN-788: apt-get update must run before apt-get install"
        # The exit code of apt-get update must be observed/logged so a
        # transient failure is visible in the journal for later debugging,
        # per the issue's "Log the update result" requirement.
        assert (
            "apt_update_rc" in self.content
        ), "JTN-788: update.sh must capture apt-get update's exit code"

    def test_update_does_not_abort_on_apt_update_failure(self):
        # JTN-788: A transient apt-get update failure (offline, DNS, mirror
        # hiccup) must NOT abort a bugfix-only update. The failure path
        # should warn and continue; the subsequent apt-get install decides
        # whether the stale index is actually fatal.
        assert "WARNING: apt-get update" in self.content, (
            "JTN-788: update.sh must warn (not abort) when apt-get update "
            "fails so transient index refresh errors do not block updates"
        )
        # Sanity: the JTN-704 /settings/update_status contract requires the
        # apt-get install abort message format to remain unchanged.
        assert (
            "ERROR: apt-get install failed — aborting update." in self.content
        ), "JTN-704 contract — apt-get install abort message must not change"

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

    def test_update_app_service_checks_is_active_after_start(self):
        # JTN-684: update_app_service() must verify the service reached active
        # state after systemctl start. systemctl start exits 0 even when the
        # service subsequently fails, so an explicit is-active check is required.
        fn_start = self.content.index("update_app_service() {")
        fn_end = self.content.index("\n}", fn_start) + 2
        fn_body = self.content[fn_start:fn_end]
        assert (
            "systemctl start" in fn_body
        ), "update_app_service must call systemctl start"
        start_pos = fn_body.index("systemctl start")
        assert (
            "is-active" in fn_body
        ), "update_app_service must check 'systemctl is-active' after start (JTN-684)"
        is_active_pos = fn_body.index("is-active")
        assert (
            is_active_pos > start_pos
        ), "'systemctl is-active' check must appear after 'systemctl start' (JTN-684)"

    def test_update_app_service_exits_nonzero_on_start_failure(self):
        # JTN-684: if the service is not active after starting, the script must
        # exit non-zero so callers know the update failed.
        fn_start = self.content.index("update_app_service() {")
        fn_end = self.content.index("\n}", fn_start) + 2
        fn_body = self.content[fn_start:fn_end]
        assert (
            "exit 1" in fn_body
        ), "update_app_service must 'exit 1' when service fails to start (JTN-684)"

    def test_update_app_service_dumps_journal_on_start_failure(self):
        # JTN-684: on service-start failure, the user must see journal output
        # instead of a misleading "Update completed" success message.
        fn_start = self.content.index("update_app_service() {")
        fn_end = self.content.index("\n}", fn_start) + 2
        fn_body = self.content[fn_start:fn_end]
        assert (
            "journalctl" in fn_body
        ), "update_app_service must dump journalctl output when service fails to start (JTN-684)"
        assert (
            "--no-pager" in fn_body
        ), "journalctl in update_app_service must use --no-pager for non-interactive output (JTN-684)"

    def test_update_service_wait_uses_timeout_bound(self):
        # JTN-706: the 3-attempt sleep 1 loop (total cap 3s) was replaced with
        # a bounded wait via `timeout 45` so slow boots on Pi Zero 2 W (which
        # routinely take 5-8s) no longer trigger false-failure reports.
        fn_start = self.content.index("update_app_service() {")
        fn_end = self.content.index("\n}", fn_start) + 2
        fn_body = self.content[fn_start:fn_end]

        # Old pattern must be gone.
        assert (
            "max_attempts=3" not in fn_body
        ), "update_app_service must no longer use 3-attempt loop (JTN-706)"
        assert (
            "max_attempts" not in fn_body
        ), "update_app_service must not reintroduce max_attempts counting (JTN-706)"

        # New pattern must be present: a `timeout <N>` bounded wait wrapping
        # the systemctl is-active poll.
        assert (
            "timeout" in fn_body and "is-active" in fn_body
        ), "update_app_service must wrap is-active poll with a `timeout` bound (JTN-706)"
        # Look for an actual 45-second timeout assignment, not just any "45" in
        # a comment or URL. Match either `wait_seconds=...45` (with optional
        # env-override expansion) or a literal `timeout 45` invocation.
        assert re.search(
            r"(wait_seconds\s*=\s*(?:\"|\')?\$?\{?[^}]*:?-?\s*45|timeout\s+(?:\"[^\"]*\"|'[^']*'|45))",
            fn_body,
        ), "update_app_service must use a 45-second timeout ceiling (JTN-706)"

        # Timeout and failed states must be distinguished so users know whether
        # to investigate the service or just be patient.
        assert (
            "is-failed" in fn_body
        ), "update_app_service must check is-failed to distinguish failure from slow start (JTN-706)"
        assert (
            "timed out" in fn_body.lower() or "timeout" in fn_body.lower()
        ), "update_app_service must log timeout distinctly from failed state (JTN-706)"


# ---- uninstall.sh ----


class TestRollbackScript:
    """JTN-708: structural hygiene for install/rollback.sh.

    The rich coverage lives in tests/unit/test_rollback_script.py; this class
    keeps the "matches the rest of install/" contract (strict mode + trap/exit
    hygiene) parallel with TestUpdateScript / TestInstallScript so future
    drift is caught here alongside the other install scripts.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("rollback.sh")

    def test_rollback_sets_strict_mode(self):
        # set -euo pipefail is the only acceptable shape — `set -e` alone
        # silently drops unset-var errors, which we must not allow for a
        # script that touches prev_version / git refs.
        assert (
            "set -euo pipefail" in self.content
        ), "rollback.sh must use 'set -euo pipefail'"

    def test_rollback_shebang_is_bash(self):
        assert self.content.startswith(
            "#!/bin/bash"
        ), "rollback.sh must have a bash shebang"

    def test_rollback_uses_distinct_exit_codes(self):
        # Exit code hygiene: operators must be able to tell "no breadcrumb"
        # from "invalid breadcrumb" from "tag unavailable" from generic errors.
        for code in ("exit 10", "exit 11", "exit 12"):
            assert (
                code in self.content
            ), f"rollback.sh must use {code!r} for a distinct failure mode"

    def test_rollback_delegates_to_update_sh(self):
        # exec'ing update.sh lets its EXIT trap (JTN-704) record any failure
        # during the rollback to .last-update-failure for UI surfacing — the
        # same recovery path as a forward update.
        assert (
            'exec bash "$UPDATE_SCRIPT"' in self.content
        ), "rollback.sh must exec update.sh so JTN-704 failure recording applies"


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


def test_debian_requirements_includes_build_headers_for_pinned_python_deps():
    """Regression: JTN-675.

    `install/requirements.txt` pins `cffi` and `cysystemd`, which need native
    headers when built from source (piwheels has no prebuilt wheels for
    Python 3.13 armv7 / Trixie). Without `libffi-dev` / `libsystemd-dev` in the
    apt preflight list, `pip install` dies with:

        fatal error: ffi.h: No such file or directory
        fatal error: systemd/sd-daemon.h: No such file or directory

    Keep these two apt packages wired to their Python dependencies so we don't
    regress this on a future requirements refresh.
    """
    py_reqs = (INSTALL_DIR / "requirements.txt").read_text()
    deb_reqs = (INSTALL_DIR / "debian-requirements.txt").read_text().splitlines()
    deb_pkgs = {
        line.strip() for line in deb_reqs if line.strip() and not line.startswith("#")
    }

    # cffi needs libffi-dev
    if re.search(r"(?m)^cffi(==|>=|~=|\s|$)", py_reqs):
        assert "libffi-dev" in deb_pkgs, (
            "install/requirements.txt pins `cffi` but install/debian-requirements.txt "
            "is missing `libffi-dev` — source builds will fail on armv7/py3.13."
        )

    # cysystemd needs libsystemd-dev
    if re.search(r"(?m)^cysystemd(==|>=|~=|\s|;|$)", py_reqs):
        assert "libsystemd-dev" in deb_pkgs, (
            "install/requirements.txt pins `cysystemd` but install/debian-requirements.txt "
            "is missing `libsystemd-dev` — source builds will fail on armv7/py3.13."
        )


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
        # JTN-616: the install matrix now lives in a reusable workflow that
        # ci.yml calls via `workflow_call`. Structural assertions about the
        # matrix body (codenames, arm64 platform, 512 MB cap, verify script)
        # must inspect install-matrix.yml directly, while ci.yml is only
        # asserted to wire the reusable workflow in as a required gate.
        self.install_matrix_yaml = (WORKFLOWS_DIR / "install-matrix.yml").read_text()
        self.dockerfile = (SCRIPTS_DIR / "Dockerfile.install-matrix").read_text()
        self.verify_script = (SCRIPTS_DIR / "ci_install_matrix_verify.sh").read_text()

    def test_install_matrix_job_defined(self):
        assert "install-matrix:" in self.ci_yaml

    def test_install_matrix_wired_as_reusable_workflow(self):
        # JTN-616: ci.yml must call the reusable install-matrix workflow so
        # the PR gate and manual reruns share a single implementation.
        import yaml

        data = yaml.safe_load(self.ci_yaml)
        job = data["jobs"]["install-matrix"]
        assert job.get("uses") == "./.github/workflows/install-matrix.yml"

    def test_install_matrix_references_supported_os_bases(self):
        # JTN-615: bullseye was removed from the install-matrix because
        # Debian 11 ships Python 3.9.2 while InkyPi's requirements pin
        # packages that need Python>=3.10 (anyio==4.13.0 is the first to
        # bomb the uv resolver). pyproject.toml also targets py311. The
        # standalone Install matrix (arm64 e2e) workflow still exercises
        # bullseye via test_install_memcap.sh because that path uses a
        # python:3.12-slim base image and therefore isn't blocked by the
        # codename's own interpreter version.
        import yaml

        data = yaml.safe_load(self.install_matrix_yaml)
        job = data["jobs"]["install-matrix"]
        codenames = job["strategy"]["matrix"]["codename"]
        assert set(codenames) == {"bookworm", "trixie"}

    def test_install_matrix_runs_on_arm64(self):
        assert "linux/arm64" in self.install_matrix_yaml
        assert "setup-qemu-action" in self.install_matrix_yaml

    def test_install_matrix_uses_512m_memory_cap(self):
        assert "--memory=512m" in self.install_matrix_yaml
        assert "--memory-swap=512m" in self.install_matrix_yaml

    def test_install_matrix_invokes_verify_script(self):
        assert "ci_install_matrix_verify.sh" in self.install_matrix_yaml

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

    def test_workflow_uses_same_helper_for_base_and_pr_measurements(self):
        assert "cp /tmp/memdiff-scripts/memory_diff.py /tmp/base-tree/scripts/" in (
            self.content
        )
        assert (
            "cp /tmp/memdiff-scripts/format_memory_diff.py /tmp/base-tree/scripts/"
            in self.content
        )

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


# ---- JTN-701: pinned Waveshare driver + safe device.json mutation ----


class TestWaveshareManifest:
    """JTN-701: install/waveshare-manifest.txt must sha-pin every supported
    Waveshare display. install.sh refuses to install any driver not listed
    here so a silent upstream change cannot break a working device."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.manifest_path = INSTALL_DIR / "waveshare-manifest.txt"
        assert self.manifest_path.exists(), (
            f"{self.manifest_path} must exist — install.sh reads it to verify "
            "Waveshare drivers at a pinned commit sha."
        )
        self.rows = []
        for line in self.manifest_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.rows.append(stripped.split())

    def test_manifest_has_entries(self):
        assert len(self.rows) > 0, "manifest must contain at least one pinned driver"

    def test_waveshare_manifest_is_sha_pinned(self):
        """Every row: <driver_name> <40-char git sha> <64-char sha256>."""
        sha_re = re.compile(r"^[0-9a-f]{40}$")
        hash_re = re.compile(r"^[0-9a-f]{64}$")
        for parts in self.rows:
            assert (
                len(parts) == 3
            ), f"manifest row must have 3 columns (name, commit sha, sha256); got: {parts}"
            name, commit_sha, sha256 = parts
            assert name.endswith(".py"), f"driver name must end in .py: {name}"
            assert sha_re.match(
                commit_sha
            ), f"commit sha for {name} must be 40 lowercase hex chars; got: {commit_sha}"
            assert hash_re.match(
                sha256
            ), f"sha256 for {name} must be 64 lowercase hex chars; got: {sha256}"

    def test_manifest_covers_common_displays(self):
        """Regression guard: drop a widely-used display out of the manifest
        only intentionally. epd7in3e (main InkyPi target) + epdconfig must stay."""
        names = {parts[0] for parts in self.rows}
        required = {"epd7in3e.py", "epdconfig.py"}
        missing = required - names
        assert not missing, f"manifest missing required drivers: {sorted(missing)}"

    def test_manifest_has_no_duplicate_entries(self):
        names = [parts[0] for parts in self.rows]
        assert len(names) == len(set(names)), (
            "duplicate driver entries in manifest: "
            f"{sorted(n for n in names if names.count(n) > 1)}"
        )


class TestInstallShUsesPinManifestAndJsonHelper:
    """JTN-701: install.sh must consult the manifest and must not mutate
    device.json with sed."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("install.sh")

    def test_install_references_waveshare_manifest(self):
        assert (
            "waveshare-manifest.txt" in self.content
        ), "install.sh must read the pin manifest to verify Waveshare drivers."

    def test_install_verifies_sha256_of_downloaded_drivers(self):
        # The pin verification must actually compare hashes, not just look them up.
        assert "sha256" in self.content.lower()
        assert (
            "sha256sum" in self.content or "shasum -a 256" in self.content
        ), "install.sh must compute the downloaded driver's sha256 to verify the pin."

    def test_install_pins_waveshare_url_to_commit_sha_not_master(self):
        """The old URL hard-coded `/master/` — a rolling tag. The pinned version
        must interpolate the commit sha from the manifest instead."""
        old_url = (
            "https://raw.githubusercontent.com/waveshareteam/e-Paper/master/"
            "RaspberryPi_JetsonNano/python/lib/waveshare_epd/"
        )
        assert (
            old_url not in self.content
        ), "install.sh must not hard-code the `master` branch — that defeats the pin."

    def test_device_json_mutation_uses_python_helper(self):
        """update_config must NOT sed device.json. Must call the Python helper."""
        match = re.search(
            r"^update_config\(\)\s*\{(.*?)^\}",
            self.content,
            re.DOTALL | re.MULTILINE,
        )
        assert match, "update_config function not found in install.sh"
        body = match.group(1)

        # Strip comments so a mention like "previous sed-based" doesn't false-positive.
        code_lines = [
            line for line in body.splitlines() if not line.lstrip().startswith("#")
        ]
        code_only = "\n".join(code_lines)
        assert not re.search(r"\bsed\b", code_only), (
            "update_config must not run sed on device.json (JTN-701). "
            "Use install/_device_json.py instead."
        )
        assert (
            "_device_json.py" in body
        ), "update_config must delegate to install/_device_json.py."
        assert (
            "set-display" in body
        ), "update_config must call the set-display subcommand."


class TestDeviceJsonHelper:
    """JTN-701: install/_device_json.py is the sole supported device.json
    mutation path. Must preserve unrelated keys and refuse malformed input."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.helper_path = INSTALL_DIR / "_device_json.py"
        assert self.helper_path.exists(), f"{self.helper_path} must exist (JTN-701)"

    def test_helper_is_valid_python(self):
        compile(self.helper_path.read_text(), str(self.helper_path), "exec")

    def _run(self, device_json_path, display_type):
        import subprocess
        import sys as _sys

        cmd = [
            _sys.executable,
            str(self.helper_path),
            "set-display",
            display_type,
            "--path",
            str(device_json_path),
        ]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_device_json_helper_preserves_unrelated_keys(self, tmp_path):
        """Unit: load → set display → dump — every other key stays exactly
        as-is (including ordering)."""
        import json as _json

        device_json = tmp_path / "device.json"
        original = {
            "name": "InkyPi",
            "orientation": "horizontal",
            "inverted_image": False,
            "scheduler_sleep_time": 60,
            "startup": True,
        }
        device_json.write_text(_json.dumps(original, indent=2))

        result = self._run(device_json, "epd7in3e")
        assert result.returncode == 0, f"helper failed: {result.stderr}"

        loaded = _json.loads(device_json.read_text())
        for k, v in original.items():
            assert (
                loaded[k] == v
            ), f"helper clobbered key {k!r}: expected {v!r}, got {loaded.get(k)!r}"
        assert loaded["display_type"] == "epd7in3e"
        keys = list(loaded.keys())
        assert keys[: len(original)] == list(
            original.keys()
        ), f"helper reordered existing keys; got {keys}"
        assert keys[-1] == "display_type"

    def test_device_json_helper_updates_existing_display_type_in_place(self, tmp_path):
        """When display_type already exists, its position must not move."""
        import json as _json

        device_json = tmp_path / "device.json"
        original = {
            "name": "InkyPi",
            "display_type": "epd7in3f",
            "orientation": "horizontal",
            "startup": True,
        }
        device_json.write_text(_json.dumps(original, indent=2))

        result = self._run(device_json, "epd7in3e")
        assert result.returncode == 0, result.stderr

        loaded = _json.loads(device_json.read_text())
        assert loaded["display_type"] == "epd7in3e"
        assert list(loaded.keys()) == list(
            original.keys()
        ), "existing display_type position must be preserved"

    def test_device_json_helper_rejects_malformed_json(self, tmp_path):
        """Malformed input must produce a clean non-zero exit, not a silently
        corrupted file."""
        device_json = tmp_path / "device.json"
        bad = '{"name": "InkyPi", "orientation":'  # truncated
        device_json.write_text(bad)

        result = self._run(device_json, "epd7in3e")
        assert result.returncode != 0, "helper must fail on malformed JSON, got success"
        assert "not valid JSON" in result.stderr or "JSON" in result.stderr
        assert (
            device_json.read_text() == bad
        ), "malformed input file was mutated — helper must be atomic"

    def test_device_json_helper_rejects_non_object_root(self, tmp_path):
        """A JSON array or scalar at the root is not a valid device.json."""
        device_json = tmp_path / "device.json"
        device_json.write_text("[1, 2, 3]")

        result = self._run(device_json, "epd7in3e")
        assert result.returncode != 0
        assert "object" in result.stderr.lower()

    def test_device_json_helper_rejects_missing_file(self, tmp_path):
        result = self._run(tmp_path / "does-not-exist.json", "epd7in3e")
        assert result.returncode != 0
        assert "not a file" in result.stderr.lower()

    def test_device_json_helper_rejects_empty_display_type(self, tmp_path):
        import json as _json

        device_json = tmp_path / "device.json"
        device_json.write_text(_json.dumps({"name": "InkyPi"}))
        result = self._run(device_json, "")
        assert result.returncode != 0

    def test_device_json_helper_atomic_write_uses_tempfile_and_replace(self):
        """Source inspection: the helper must write via a tempfile + os.replace
        so Ctrl+C / power loss cannot leave device.json partially written."""
        src = self.helper_path.read_text()
        assert "tempfile" in src
        assert "os.replace" in src
        assert "os.fsync" in src, (
            "atomic write must fsync before replace so contents hit disk "
            "before the rename is recorded in the directory inode."
        )


# ---- JTN-699: install.sh preflight sanity checks ----------------------------
#
# install.sh previously had no early validation; the user discovered
# "Permission denied" / "No space left on device" 5–10 minutes into a run
# with $INSTALL_PATH half-populated. JTN-699 adds a preflight block that runs
# BEFORE any apt/pip/git work and fails fast with actionable messages.
#
# Each failure path below simulates one broken precondition by pointing the
# preflight env-var hooks at a tmp dir and asserting the exit code + error
# message. The INKYPI_PREFLIGHT_TEST hook skips the EUID root check, and
# INKYPI_PREFLIGHT_TEST_EXIT_AFTER short-circuits before real install work —
# both are no-ops in production where those vars are never set.


class TestInstallPreflight:
    """Subprocess-runs install/install.sh with preflight env hooks and asserts
    each check fails fast with a specific message (JTN-699)."""

    INSTALL_SH = REPO_ROOT / "install" / "install.sh"

    def _base_env(self, tmp_path):
        """Build a valid set of preflight env vars pointing at tmp dirs.

        Individual tests then override ONE var to simulate one failure, so
        other preflight checks keep passing and only the targeted branch
        trips. This mirrors how test_update_failure_recovery.py injects a
        single failure at a time rather than a combined broken state.
        """
        import subprocess as _sp

        usr_local = tmp_path / "usr_local"
        install_parent = tmp_path / "install_parent"
        systemd_dir = tmp_path / "systemd"
        state_dir = tmp_path / "state"
        src_path = tmp_path / "src"
        for d in (usr_local, install_parent, systemd_dir, state_dir, src_path):
            d.mkdir()
        # Make $src_path a real git repo so the git-rev-parse check passes
        # by default. Individual tests override this.
        _sp.run(["git", "init", "-q", str(src_path)], check=True)
        return {
            "INKYPI_PREFLIGHT_TEST": "1",
            "INKYPI_PREFLIGHT_TEST_EXIT_AFTER": "1",
            "INKYPI_PREFLIGHT_USR_LOCAL": str(usr_local),
            "INKYPI_PREFLIGHT_INSTALL_PARENT": str(install_parent),
            "INKYPI_PREFLIGHT_SYSTEMD_DIR": str(systemd_dir),
            "INKYPI_PREFLIGHT_STATE_DIR": str(state_dir),
            "INKYPI_PREFLIGHT_SRC_PATH": str(src_path),
        }

    def _run(self, env_overrides):
        import os as _os
        import shutil as _shutil
        import subprocess as _sp

        if not _shutil.which("bash"):
            pytest.skip("bash is not available on this host")
        if not _shutil.which("git"):
            pytest.skip("git is not available on this host")
        env = dict(_os.environ)
        env.update(env_overrides)
        return _sp.run(
            ["bash", str(self.INSTALL_SH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    # --- Happy path ---------------------------------------------------------

    def test_preflight_passes_when_all_checks_satisfied(self, tmp_path):
        """Baseline: with every precondition valid, preflight returns 0 and
        the test short-circuit exits cleanly. This gates every failure test
        below — if the baseline regresses, the failure-path assertions would
        be meaningless."""
        proc = self._run(self._base_env(tmp_path))
        assert proc.returncode == 0, (
            f"preflight must exit 0 when all checks pass; got {proc.returncode}. "
            f"stdout: {proc.stdout!r} stderr: {proc.stderr!r}"
        )
        # Success message must be printed so operators see what was verified.
        combined = proc.stdout + proc.stderr
        assert (
            "Preflight checks passed" in combined
        ), f"preflight must announce success; output: {combined!r}"

    # --- Disk-space failures ------------------------------------------------

    def test_preflight_fails_when_usr_local_below_min_free(self, tmp_path):
        """Simulate <500 MB free on /usr/local by bumping the threshold above
        what any real filesystem would have free. A threshold of 10 PB (~10M
        MB) is guaranteed to exceed actual free space on any test host."""
        env = self._base_env(tmp_path)
        env["INKYPI_PREFLIGHT_MIN_FREE_MB"] = str(10_000_000)  # 10 TB
        proc = self._run(env)
        assert (
            proc.returncode != 0
        ), "preflight must fail when free space is below the min threshold"
        combined = proc.stdout + proc.stderr
        assert (
            "insufficient free disk space" in combined
        ), f"error message must name the disk-space check; got: {combined!r}"
        # The path that failed must appear in the error so the user knows
        # which filesystem is the problem.
        assert (
            str(env["INKYPI_PREFLIGHT_USR_LOCAL"]) in combined
            or "usr_local" in combined
        )

    def test_preflight_disk_error_includes_remediation(self, tmp_path):
        """Actionable error messages are in the acceptance criteria — every
        failure must include a 'remediation:' suggestion."""
        env = self._base_env(tmp_path)
        env["INKYPI_PREFLIGHT_MIN_FREE_MB"] = str(10_000_000)
        proc = self._run(env)
        combined = proc.stdout + proc.stderr
        assert (
            "remediation" in combined.lower()
        ), f"disk-space failure must suggest a remediation; got: {combined!r}"

    # --- Writable-target failures ------------------------------------------

    def test_preflight_fails_when_install_parent_not_writable(self, tmp_path):
        """A RO install parent is the exact permission mode this preflight is
        designed to catch. chmod 0o500 (r-x------) removes write for the
        owner so even the EUID running the script cannot create $INSTALL_PATH."""
        import os as _os

        env = self._base_env(tmp_path)
        install_parent = env["INKYPI_PREFLIGHT_INSTALL_PARENT"]
        _os.chmod(install_parent, 0o500)
        try:
            proc = self._run(env)
        finally:
            # Restore so tmp_path teardown doesn't fail on macOS.
            _os.chmod(install_parent, 0o755)
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert (
            "not writable" in combined
        ), f"error must name the writability check; got: {combined!r}"
        assert (
            install_parent in combined
        ), f"error must name the failing path; got: {combined!r}"

    def test_preflight_fails_when_systemd_dir_not_writable(self, tmp_path):
        import os as _os

        env = self._base_env(tmp_path)
        systemd_dir = env["INKYPI_PREFLIGHT_SYSTEMD_DIR"]
        _os.chmod(systemd_dir, 0o500)
        try:
            proc = self._run(env)
        finally:
            _os.chmod(systemd_dir, 0o755)
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert "not writable" in combined
        assert systemd_dir in combined

    def test_preflight_fails_when_systemd_dir_missing(self, tmp_path):
        """A missing /etc/systemd/system means we are not on a systemd host.
        Preflight should abort rather than silently try to copy a unit file
        to a nonexistent directory."""
        env = self._base_env(tmp_path)
        # Point at a path that does not exist AND cannot be auto-created as a
        # systemd dir (the systemd check intentionally does not mkdir -p).
        env["INKYPI_PREFLIGHT_SYSTEMD_DIR"] = str(tmp_path / "no-systemd-here")
        proc = self._run(env)
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert "does not exist" in combined
        assert "systemd" in combined.lower()

    def test_preflight_fails_when_state_dir_not_writable(self, tmp_path):
        import os as _os

        env = self._base_env(tmp_path)
        state_dir = env["INKYPI_PREFLIGHT_STATE_DIR"]
        _os.chmod(state_dir, 0o500)
        try:
            proc = self._run(env)
        finally:
            _os.chmod(state_dir, 0o755)
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert "not writable" in combined
        assert state_dir in combined

    # --- git-repo failure ---------------------------------------------------

    def test_preflight_fails_when_src_is_not_a_git_repo(self, tmp_path):
        """A downloaded tarball (no .git dir) would silently break
        git-describe-based version reporting and waveshare pin verification.
        Abort early with a clear message."""
        import shutil as _shutil

        env = self._base_env(tmp_path)
        # Remove the .git dir so the rev-parse check fails.
        _shutil.rmtree(Path(env["INKYPI_PREFLIGHT_SRC_PATH"]) / ".git")
        proc = self._run(env)
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert (
            "not a git repository" in combined
        ), f"error must name the git-repo check; got: {combined!r}"
        assert env["INKYPI_PREFLIGHT_SRC_PATH"] in combined
        assert "remediation" in combined.lower()

    def test_preflight_fails_when_src_path_missing(self, tmp_path):
        import shutil as _shutil

        env = self._base_env(tmp_path)
        _shutil.rmtree(env["INKYPI_PREFLIGHT_SRC_PATH"])
        proc = self._run(env)
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert "does not exist" in combined
        assert env["INKYPI_PREFLIGHT_SRC_PATH"] in combined

    # --- Runs early: no apt/pip side effects -------------------------------

    def test_preflight_fails_before_any_install_work(self, tmp_path):
        """Acceptance: preflight must run BEFORE any apt/pip work. If it
        trips on a failure, nothing downstream should have run — no vendor
        download, no wheelhouse, no zramswap setup."""
        env = self._base_env(tmp_path)
        env["INKYPI_PREFLIGHT_MIN_FREE_MB"] = str(10_000_000)  # force fail
        # Drop the exit-after hook so we'd fall through IF preflight didn't
        # abort — any "Installing system dependencies" output would prove
        # it reached apt-get. It MUST NOT.
        env.pop("INKYPI_PREFLIGHT_TEST_EXIT_AFTER", None)
        proc = self._run(env)
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        # Look for strings that would only appear if a real install step
        # ran. The disk-space remediation message mentions "apt-get clean"
        # so we cannot match on a bare "apt-get" substring — use whole-word
        # headings that only the install steps themselves print.
        for forbidden in (
            "Installing system dependencies",
            "Fetch available system dependencies",
            "Creating python virtual environment",
            "Installing python dependencies",
            "setting up zramswap",
            "Enabling interfaces required for",
            "Installing inkypi systemd service",
        ):
            assert forbidden not in combined, (
                f"preflight failure must short-circuit before {forbidden!r} runs; "
                f"found it in output: {combined!r}"
            )

    # --- git dubious-ownership regression (CodeRabbit review #546) ---------

    def test_preflight_git_check_survives_dubious_ownership(self, tmp_path):
        """Regression gate for CodeRabbit review on PR #546.

        Canonical production flow:
            git clone https://github.com/fatihak/InkyPi.git ~/inkypi
            sudo bash ~/inkypi/install/install.sh

        After CVE-2022-24765 (fixed in git 2.35.2+), git refuses to operate on
        a repo whose .git ownership differs from the effective uid, failing
        with "fatal: detected dubious ownership". `git rev-parse --git-dir
        2>/dev/null` would mask this and the preflight would emit the
        misleading 'source tree … is not a git repository' message, sending
        users to re-clone a repo that's already fine.

        We can't actually run install.sh as root from pytest, so this test
        simulates the condition by forcing git's ownership guard to trip via
        GIT_TEST_ASSUME_DIFFERENT_OWNER=1 (a test-only knob shipped in git's
        own setup.c). If the preflight invocation handles dubious-ownership
        correctly (scoped safe.directory override) the repo is still
        recognised and preflight passes. If somebody reverts that fix, this
        test fails with the same 'not a git repository' message users would
        see in the field.
        """
        import os as _os
        import shutil as _shutil
        import subprocess as _sp

        if not _shutil.which("git"):
            pytest.skip("git is not available on this host")
        # Verify the env knob actually trips this git build before relying on
        # it for the negative assertion — old gits, msysgit etc. may ignore
        # it. The knob was added alongside the CVE-2022-24765 fix.
        src_path = tmp_path / "probe-repo"
        src_path.mkdir()
        _sp.run(["git", "init", "-q", str(src_path)], check=True)
        probe = _sp.run(
            ["git", "-C", str(src_path), "rev-parse", "--git-dir"],
            env={**_os.environ, "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"},
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            pytest.skip(
                "this git build ignores GIT_TEST_ASSUME_DIFFERENT_OWNER; "
                "cannot simulate sudo-on-user-owned-clone here"
            )
        # Sanity: the knob really did raise the expected dubious-ownership
        # error so our negative assertion below isn't a false positive.
        assert "dubious ownership" in (probe.stderr + probe.stdout).lower()

        env = self._base_env(tmp_path)
        # Switch $src_path over to the probe repo AND turn on the ownership
        # simulation for install.sh itself. install.sh's scoped
        # `safe.directory=*` override should let rev-parse succeed, so
        # preflight must still pass cleanly.
        env["INKYPI_PREFLIGHT_SRC_PATH"] = str(src_path)
        env["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"
        proc = self._run(env)
        combined = proc.stdout + proc.stderr
        assert proc.returncode == 0, (
            "preflight must tolerate EUID != .git owner via a scoped "
            f"safe.directory override (CVE-2022-24765 regression). "
            f"rc={proc.returncode} output={combined!r}"
        )
        assert "not a git repository" not in combined, (
            "dubious-ownership must not be masked as 'not a git repository'; "
            f"output: {combined!r}"
        )

    # --- Source inspection: env-var override contract ---------------------

    def test_install_sh_declares_preflight_env_hooks(self):
        """Source inspection: the preflight env-var contract documented in
        the module header must actually exist in install.sh. Guards against
        a future refactor that drops a hook without updating the tests."""
        content = (REPO_ROOT / "install" / "install.sh").read_text()
        for var in (
            "INKYPI_PREFLIGHT_TEST",
            "INKYPI_PREFLIGHT_TEST_EXIT_AFTER",
            "INKYPI_PREFLIGHT_USR_LOCAL",
            "INKYPI_PREFLIGHT_INSTALL_PARENT",
            "INKYPI_PREFLIGHT_SYSTEMD_DIR",
            "INKYPI_PREFLIGHT_STATE_DIR",
            "INKYPI_PREFLIGHT_SRC_PATH",
            "INKYPI_PREFLIGHT_MIN_FREE_MB",
        ):
            assert (
                var in content
            ), f"install.sh must reference preflight env hook {var} (JTN-699)"

    def test_install_sh_runs_preflight_before_lockfile_setup(self):
        """Preflight must be called BEFORE the $LOCKFILE touch, because an
        unwritable $LOCKFILE_DIR should surface as a clean preflight error,
        not as a cryptic `touch: cannot touch ...` message."""
        content = (REPO_ROOT / "install" / "install.sh").read_text()
        preflight_pos = content.index("preflight_checks\n")
        # The lockfile `touch "$LOCKFILE"` is the first place we'd trip on
        # an unwritable state dir.
        lockfile_pos = content.index('touch "$LOCKFILE"')
        assert preflight_pos < lockfile_pos, (
            'preflight_checks must run before `touch "$LOCKFILE"` so an '
            "unwritable $LOCKFILE_DIR produces a clean preflight error "
            "(JTN-699)"
        )


# ---- JTN-785: per-device memory cap tiering -------------------------------


class TestMemoryCapTiering:
    """JTN-785: install.sh/update.sh must scale MemoryHigh/MemoryMax to the
    device's total RAM via a drop-in at
    /etc/systemd/system/inkypi.service.d/memory.conf.

    These tests exercise the `pick_memory_caps` and `install_memory_dropin`
    helpers in install/_common.sh end-to-end via `bash -c`, so a future
    refactor that silently breaks the tier thresholds fails loudly here.
    """

    COMMON_SH = INSTALL_DIR / "_common.sh"

    def _invoke_pick(self, meminfo_body: str, tmp_path):
        """Write a stub /proc/meminfo body to tmp_path and shell out to
        pick_memory_caps with INKYPI_MEMINFO_PATH pointing at it."""
        import subprocess

        stub = tmp_path / "meminfo"
        stub.write_text(meminfo_body)
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{self.COMMON_SH}" && pick_memory_caps',
            ],
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "INKYPI_MEMINFO_PATH": str(stub),
            },
        )
        assert result.returncode == 0, (
            f"pick_memory_caps exited non-zero:\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        return result.stdout.strip()

    def test_pick_caps_512mb_pi_zero_2w(self, tmp_path):
        # Pi Zero 2 W reports ~498 MB MemTotal after kernel + GPU carveout.
        out = self._invoke_pick("MemTotal:         498064 kB\n", tmp_path)
        assert (
            out == "350 500 low-mem"
        ), f"512 MB Pi must get low-mem tier (350M/500M); got {out!r}"

    def test_pick_caps_1gb_pi3(self, tmp_path):
        # Pi 3B reports ~920 MB.
        out = self._invoke_pick("MemTotal:         940000 kB\n", tmp_path)
        assert (
            out == "250 350 standard"
        ), f"1 GB Pi must get standard tier (250M/350M); got {out!r}"

    def test_pick_caps_4gb_pi4(self, tmp_path):
        out = self._invoke_pick("MemTotal:        3900000 kB\n", tmp_path)
        assert out == "250 350 standard"

    def test_pick_caps_missing_meminfo_defaults_to_standard(self, tmp_path):
        # Safer to under-cap a fast Pi than to wrongly raise caps on an
        # unidentified device. No MemTotal line → default to standard tier.
        out = self._invoke_pick("Buffers: 0 kB\n", tmp_path)
        assert out == "250 350 standard"

    def test_pick_caps_threshold_boundary(self, tmp_path):
        # Exactly 700000 kB (the threshold) → low-mem. 700001 kB → standard.
        out_at = self._invoke_pick("MemTotal:         700000 kB\n", tmp_path)
        out_over = self._invoke_pick("MemTotal:         700001 kB\n", tmp_path)
        assert out_at == "350 500 low-mem"
        assert out_over == "250 350 standard"

    def test_install_memory_dropin_writes_low_mem_tier(self, tmp_path):
        import subprocess

        meminfo = tmp_path / "meminfo"
        meminfo.write_text("MemTotal:         498064 kB\n")
        dropin_dir = tmp_path / "inkypi.service.d"
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{self.COMMON_SH}" && install_memory_dropin',
            ],
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "INKYPI_MEMINFO_PATH": str(meminfo),
                "INKYPI_DROPIN_DIR": str(dropin_dir),
            },
        )
        assert (
            result.returncode == 0
        ), f"install_memory_dropin failed:\nstderr={result.stderr!r}"
        dropin = dropin_dir / "memory.conf"
        assert dropin.exists(), "memory.conf drop-in must be written"
        body = dropin.read_text()
        assert "[Service]" in body
        assert "MemoryHigh=350M" in body
        assert "MemoryMax=500M" in body
        # Filename must NOT collide with the JTN-783 plugin-isolation drop-in.
        assert dropin.name == "memory.conf"

    def test_install_memory_dropin_writes_standard_tier(self, tmp_path):
        import subprocess

        meminfo = tmp_path / "meminfo"
        meminfo.write_text("MemTotal:        3900000 kB\n")
        dropin_dir = tmp_path / "inkypi.service.d"
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{self.COMMON_SH}" && install_memory_dropin',
            ],
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "INKYPI_MEMINFO_PATH": str(meminfo),
                "INKYPI_DROPIN_DIR": str(dropin_dir),
            },
        )
        assert result.returncode == 0
        body = (dropin_dir / "memory.conf").read_text()
        assert "MemoryHigh=250M" in body
        assert "MemoryMax=350M" in body

    def test_install_memory_dropin_is_idempotent(self, tmp_path):
        """Rewriting the same caps on every install/update must be safe."""
        import subprocess

        meminfo = tmp_path / "meminfo"
        meminfo.write_text("MemTotal:         498064 kB\n")
        dropin_dir = tmp_path / "inkypi.service.d"
        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "INKYPI_MEMINFO_PATH": str(meminfo),
            "INKYPI_DROPIN_DIR": str(dropin_dir),
        }
        cmd = [
            "bash",
            "-c",
            f'source "{self.COMMON_SH}" && install_memory_dropin',
        ]
        first = subprocess.run(cmd, capture_output=True, text=True, env=env)
        second = subprocess.run(cmd, capture_output=True, text=True, env=env)
        assert first.returncode == 0 and second.returncode == 0
        # Content must be identical across repeat invocations.
        body = (dropin_dir / "memory.conf").read_text()
        assert "MemoryHigh=350M" in body
        assert "MemoryMax=500M" in body

    def test_install_sh_calls_install_memory_dropin(self):
        content = (REPO_ROOT / "install" / "install.sh").read_text()
        assert "install_memory_dropin" in content, (
            "install.sh must call install_memory_dropin so fresh installs "
            "get device-scaled caps (JTN-785)"
        )

    def test_update_sh_calls_install_memory_dropin(self):
        content = (REPO_ROOT / "install" / "update.sh").read_text()
        assert "install_memory_dropin" in content, (
            "update.sh must call install_memory_dropin so existing installs "
            "pick up the per-device caps on next update (JTN-785)"
        )

    def test_do_update_reads_target_version_file(self):
        content = (REPO_ROOT / "install" / "do_update.sh").read_text()
        assert 'TARGET_VERSION_FILE="$LOCKFILE_DIR/update-target-version"' in content
        assert '[ -r "$TARGET_VERSION_FILE" ]' in content
        assert 'head -n 1 "$TARGET_VERSION_FILE"' in content

    def test_dropin_filename_does_not_collide_with_plugin_isolation(self, tmp_path):
        """JTN-783 ships a plugin-isolation.conf drop-in. The JTN-785 drop-in
        must use a distinct filename (memory.conf) so both coexist in
        inkypi.service.d/ without stomping."""
        import subprocess

        meminfo = tmp_path / "meminfo"
        meminfo.write_text("MemTotal:         498064 kB\n")
        dropin_dir = tmp_path / "inkypi.service.d"
        subprocess.run(
            [
                "bash",
                "-c",
                f'source "{self.COMMON_SH}" && install_memory_dropin',
            ],
            check=True,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "INKYPI_MEMINFO_PATH": str(meminfo),
                "INKYPI_DROPIN_DIR": str(dropin_dir),
            },
        )
        # Only memory.conf must be written — never plugin-isolation.conf.
        written = sorted(p.name for p in dropin_dir.iterdir())
        assert written == [
            "memory.conf"
        ], f"install_memory_dropin wrote unexpected files: {written}"

    def test_common_sh_syntax_valid(self):
        import subprocess

        result = subprocess.run(
            ["bash", "-n", str(self.COMMON_SH)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"
