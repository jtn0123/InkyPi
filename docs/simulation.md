# Simulating the device off-device

InkyPi runs on a Raspberry Pi, under systemd, driving an SPI e-paper panel.
Development happens on machines with none of those things. This page records
what can be verified anyway, what needs a container, and what genuinely needs
the Pi — so the boundary is written down instead of rediscovered each time.

The short version: **more is testable off-device than it first appears**, and
the parts that aren't should be named rather than hand-waved.

## The tiers

| Tier | Where | What it proves | Cost |
| --- | --- | --- | --- |
| Unit | anywhere | logic in isolation | milliseconds |
| **Simulation** (`tests/simulation/`) | anywhere with bash | our code against real protocols and real scripts | seconds |
| **Container** (`tests/integration/`) | any machine running colima/Docker | systemd's *own* behaviour — `Restart=`, `OnFailure=`, `StartLimitBurst`, cgroups | ~1 min |
| Hardware | the Pi | SPI, panel timing, real memory pressure | a trip to the shelf |

Only the last row genuinely needs the device. Everything above it runs on a
laptop, including the auto-rollback chain that is hardest to test precisely
because it only fires when the device is already broken.

## What simulation covers

`tests/simulation/fake_systemd.py` provides the shared harness.

**The systemd notification socket is not mocked — it is reproduced.** `sd_notify`
is a unix datagram sent to the path in `$NOTIFY_SOCKET`; that is the entire
protocol. `NotifySocket` binds a real socket, the code under test sends real
datagrams, and the tests assert on the bytes that arrive. The only thing
missing is `cysystemd`, the Linux-only C wrapper, which
`tests/simulation/fake_systemd.sd_notify` replaces with the same six lines in
Python.

That is enough to prove the watchdog end to end:

- the ping interval is derived correctly from `WATCHDOG_USEC` (and floors at 1 s)
- an idle refresh loop keeps pinging however long the cycle interval is
- a refresh wedged past its stall budget **stops** the pings, which is what lets
  `WatchdogSec` expire and restart the unit
- pings resume once the refresh completes

**`systemctl` is a recording shim on `PATH`**, so `update.sh`, `boot-health.sh`
and `rollback.sh` run unmodified and their invocations and ordering can be
asserted. Paired with a small HTTP server standing in for the app, the whole
update chain is rehearsable: confirmed / unconfirmed / dark verdicts, the
failure streak accumulating, rollback firing exactly once at the threshold, and
a confirmed version refusing to roll back.

**Plugin rendering is fully real.** The HTML → headless-Chrome path works on
macOS, so a plugin can be rendered to a PNG and looked at. That is how the
weather icon-path bug was confirmed fixed: seven icons pointed at files that did
not exist and rendered as broken-image boxes; the same fixture after the fix
renders actual icons.

```bash
SKIP_BROWSER=1 PYTHONPATH=src:. .venv/bin/python -m pytest tests/simulation/ -q
```

## What simulation does *not* cover

Be honest about this when reading a green run:

- **systemd's own behaviour.** Unit ordering, `Restart=on-failure`,
  `StartLimitBurst`, `OnFailure=` activation, `MemoryMax` cgroup kills. The
  simulation proves `boot-health.sh` does the right thing *when invoked*; it
  does not prove systemd invokes it. That is the container tier's job — see
  below.
- **The SPI panel.** `waveshare_display` is exercised against fake EPD objects
  shaped like the vendor drivers (including the `epd3in7` mode-driven variant).
  Timing, busy-waits, partial refresh and actual pixels are hardware only.
- **Real memory pressure.** The Pi Zero 2 W's 512 MB is where the OOM paths and
  the low-resource image loader actually matter.
- **Whether the device's port and network assumptions hold.** The rehearsal
  fixes `INKYPI_PORT`; the real device might not match.

## The container tier

Two gates need a real init and run in a privileged systemd container:

- `tests/integration/test_install_crash_loop.py` — the Pi-thrash regression gate.
- `tests/integration/test_boot_health_under_systemd.py` — proves systemd
  actually drives `OnFailure=` → `inkypi-failure.service` → `boot-health.sh` →
  rollback, using the units verbatim with only timing shortened by drop-ins.
  This is the half the simulation tier cannot reach, and it matters
  disproportionately because the code only ever runs when the device is already
  failing to start.

### cgroup v1 vs v2

Getting this wrong produces no useful error — systemd exits 255 with empty
logs, and the test skips with "systemd did not reach a running state". A
skipped gate looks exactly like a passing one in CI output, which is how the
crash-loop gate went unnoticed-but-not-running on every modern host.

- **cgroup v1** wants the host hierarchy bind-mounted at `/sys/fs/cgroup`.
- **cgroup v2** wants `--cgroupns=host` and *no* bind mount; adding the v1
  mount on top actively breaks it.

Both gates now detect the version via `docker info` and pick the right flags.

They carry the `container` marker and are excluded from the pytest matrix —
systemd behaviour does not vary by Python version, so running them across three
interpreters only triples the cost (it pushed 3.13 past its 20-minute cap). CI
runs them once in the `Systemd container gates` job; locally, use
`pytest -m container`.
If you add another systemd container test, reuse `_cgroup_run_args()` rather
than hardcoding either recipe.

### Local setup (colima)

The VM disk grows without bound as images accumulate, so on a machine with a
tight internal disk it belongs on external storage:

```bash
brew install colima
source scripts/container-env.sh     # points COLIMA_HOME / LIMA_HOME off-disk
colima start --cpu 2 --memory 4 --disk 60
```

`colima start` registers a docker context, so the `docker` CLI works from any
shell afterwards without environment variables. Only the `colima` lifecycle
commands need `scripts/container-env.sh` sourced — which is also why a fresh
terminal reports "colima is not running" until you source it.

Storage layout is controlled by `INKYPI_CONTAINER_ROOT` (default
`/Volumes/512Flash/inkypi-dev`). Override it for a different machine:

```bash
INKYPI_CONTAINER_ROOT=/path/to/storage source scripts/container-env.sh
```

**If the storage is a removable volume**, mount it before `colima start`, and
stop the VM (`colima stop`) before ejecting. The VM disk is sparse — 21 GB
apparent, ~1.4 GB actual for a fresh install.

## Adding to the simulation tier

Put shared fakes in `tests/simulation/fake_systemd.py`, mark test modules with
`pytest.mark.simulation`, and prefer reproducing a protocol over mocking an
interface — a real socket or a real script invocation catches ordering and
environment bugs that a `MagicMock` cannot. When something genuinely cannot be
simulated, say so in the module docstring rather than testing a weaker property
and implying the stronger one.

Select or skip the tier with the marker:

```bash
# only the simulation tier
.venv/bin/python -m pytest -m simulation

# everything except it
.venv/bin/python -m pytest -m "not simulation"
```
