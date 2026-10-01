"""Bounded QEMU userspace boot verification; this does not test Pi hardware."""

import argparse
import re
import subprocess
import time
from pathlib import Path


def verify_boot(command: list[str], log: Path, timeout: float) -> bool:
    """Require a serial login prompt and always reap the owned emulator."""
    deadline = time.monotonic() + timeout
    with log.open("wb") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        try:
            while True:
                serial = log.read_bytes()
                if re.search(rb"(?:^|\n)[A-Za-z0-9._-]+ login:[ \t\r\n]*$", serial):
                    return True
                if process.poll() is not None or time.monotonic() >= deadline:
                    return False
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("image", "kernel", "initrd"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--log", type=Path, default=Path("qemu-boot.log"))
    args = parser.parse_args()
    for path in (args.image, args.kernel, args.initrd):
        if not path.is_file():
            parser.error(f"missing boot input: {path}")
    command = [
        "qemu-system-aarch64",
        "-M",
        "virt",
        "-cpu",
        "cortex-a72",
        "-m",
        "1024",
        "-smp",
        "2",
        "-nographic",
        "-nic",
        "none",
        "-kernel",
        str(args.kernel),
        "-initrd",
        str(args.initrd),
        "-drive",
        f"file={args.image},format=raw,if=none,id=hd0",
        "-device",
        "virtio-blk-device,drive=hd0",
        "-append",
        "root=/dev/vda2 rootfstype=ext4 rw console=ttyAMA0",
    ]
    if verify_boot(command, args.log, 240):
        print("Boot verified: serial login prompt observed")
        return 0
    print("Boot failed or timed out without a serial login prompt")
    print(args.log.read_text(errors="replace")[-20000:])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
