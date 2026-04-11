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
