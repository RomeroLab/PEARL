"""Run pytest with inherited, kernel-enforced network isolation (Linux).

Usage: python tests/offline.py [pytest arguments]
No credentials are printed. The seccomp filter persists in subprocesses even
when tests replace their environment or start another interpreter.
"""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import socket
import sys


def isolate() -> None:
    for key in tuple(os.environ):
        if any(part in key.upper() for part in ("API_KEY", "ACCESS_TOKEN", "SECRET_KEY")):
            os.environ.pop(key, None)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"

    lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("Cannot initialize offline network isolation")
    try:
        # Deny connections and datagram sends, including inherited sockets.
        for name in (b"connect", b"sendto", b"sendmsg", b"sendmmsg"):
            syscall = lib.seccomp_syscall_resolve_name(name)
            if syscall < 0 or lib.seccomp_rule_add(context, 0x00050000 | errno.EPERM, syscall, 0):
                raise RuntimeError(f"Cannot block {name.decode()}")
        if lib.seccomp_load(context):
            raise RuntimeError("Cannot activate offline network isolation")
    finally:
        lib.seccomp_release(context)

    def deny_devices(event: str, args: tuple) -> None:
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = os.fsdecode(args[0])
            if path.startswith(("/dev/ttyUSB", "/dev/ttyACM", "/dev/video", "/dev/i2c", "/dev/spidev", "/dev/bus/usb")):
                raise PermissionError("Physical hardware is disabled in offline tests")
        if event == "import" and args[0] == "opentrons.execute":
            raise PermissionError("Physical robot execution is disabled in offline tests")

    sys.addaudithook(deny_devices)
    with socket.socket() as probe:
        try:
            probe.connect(("127.0.0.1", 9))
        except PermissionError:
            pass
        else:
            raise RuntimeError("Offline network guard did not block the probe")


if __name__ == "__main__":
    isolate()
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "src"), str(root)]
    import pytest

    print("OFFLINE: credentials removed; dotenv disabled; kernel network guard active; physical device guard active", flush=True)
    raise SystemExit(pytest.main(sys.argv[1:]))
