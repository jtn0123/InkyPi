# pyright: reportMissingImports=false
"""Structural validation of install/setup scripts — no shell execution."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_DIR = REPO_ROOT / "install"


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

    def test_service_working_directory(self):
        assert "RuntimeDirectory=inkypi" in self.content
        assert "WorkingDirectory=/run/inkypi" in self.content


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
        guard = 'grep -q "^/dev/zram" /proc/swaps'
        apt_install = "apt-get install -y zram-tools"
        assert guard in self.content
        assert "skipping zram-tools install" in self.content
        assert "return 0" in self.content

        fn_start = self.content.index("setup_zramswap_service() {")
        guard_pos = self.content.index(guard, fn_start)
        return_pos = self.content.index("return 0", fn_start)
        apt_pos = self.content.index(apt_install, fn_start)
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
        assert "11=Bullseye" in self.content
        assert "12=Bookworm" in self.content
        assert "13=Trixie" in self.content
        assert "Trixe" not in self.content  # typo guard

    def test_zramswap_regex_matches_codename_comment_parity(self):
        # JTN-531: The codename comment near get_os_version() and the version
        # regex in the zramswap branch must list the same integer keys.
        # If someone adds 14=Forky to one without updating the other this test
        # will catch it.

        # Parse "# Get OS release number, e.g. 11=Bullseye, 12=Bookworm, 13=Trixie"
        # Capture every "<digit(s)>=<Codename>" pair from the comment line
        # immediately above the get_os_version() function definition.
        comment_versions = set()
        lines = self.content.splitlines()
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
        regex_versions = set()
        for line in self.content.splitlines():
            m = re.search(r"\^\(([0-9|]+)\)\$", line)
            if m:
                for part in m.group(1).split("|"):
                    if part.strip().isdigit():
                        regex_versions.add(int(part.strip()))

        assert (
            comment_versions
        ), "Could not parse any version numbers from the get_os_version comment in install.sh"
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
        fn_start = self.content.index("stop_service() {")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]
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

    def test_stop_service_disable_tolerates_already_disabled(self):
        # JTN-600: The disable call must not fail if the service is already
        # disabled (e.g. fresh install). Must use '|| true' or '2>/dev/null'.
        fn_start = self.content.index("stop_service() {")
        fn_end = self.content.index("\n}", fn_start)
        fn_body = self.content[fn_start:fn_end]
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


# ---- update.sh ----


class TestUpdateScript:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = _read("update.sh")

    def test_update_rebuilds_css(self):
        assert "build_css" in self.content

    def test_update_restarts_service(self):
        assert "systemctl" in self.content
        assert "restart" in self.content

    def test_update_upgrades_pip_deps(self):
        assert "pip install" in self.content


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

SCRIPTS_DIR = REPO_ROOT / "scripts"
DOCS_DIR = REPO_ROOT / "docs"


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
