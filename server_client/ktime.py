"""
Kernel receive timestamps (SO_TIMESTAMPNS) for the UDP time server and client.

The kernel stamps a datagram with CLOCK_REALTIME when it arrives, before Python
is scheduled to read it. Taking T2 (server) and T4 (client) from that stamp
removes the user-space wake-up delay from the offset estimate. If a stamp is
missing the receive falls back to time.time_ns(); every fallback is counted so a
result can say how many samples used user-space time.
"""
import socket
import struct
import time

SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)   # Linux value
SCM_TIMESTAMPNS = SO_TIMESTAMPNS
_TS = struct.Struct("ll")                                 # struct timespec
_ANC = socket.CMSG_SPACE(_TS.size) if hasattr(socket, "CMSG_SPACE") else 0

KERNEL, USER, FALLBACK = "kernel", "user", "user-fallback"


def enable(sock):
    """Ask the kernel to attach a receive timestamp. False if unsupported."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
        return True
    except (OSError, AttributeError):
        return False


class Stamper:
    """recv() returns (data, addr, rx_time_ns, source) with source in
    kernel / user / user-fallback. use_kernel=False forces plain user-space time
    (used by the sandbox comparison) and is not counted as a fallback."""

    def __init__(self, sock, use_kernel=True):
        self.sock = sock
        self.use_kernel = use_kernel
        self.kernel_enabled = enable(sock) if use_kernel else False
        self.kernel = 0
        self.user = 0
        self.fallbacks = 0

    def recv(self, bufsize=2048):
        if not self.use_kernel:
            data, addr = self.sock.recvfrom(bufsize)
            self.user += 1
            return data, addr, time.time_ns(), USER
        data, anc, _flags, addr = self.sock.recvmsg(bufsize, _ANC)
        for level, typ, cdata in anc:
            if level == socket.SOL_SOCKET and typ == SCM_TIMESTAMPNS and len(cdata) >= _TS.size:
                sec, nsec = _TS.unpack(cdata[:_TS.size])
                self.kernel += 1
                return data, addr, sec * 1_000_000_000 + nsec, KERNEL
        self.fallbacks += 1
        return data, addr, time.time_ns(), FALLBACK

    def summary(self):
        return (f"rx timestamps: kernel={self.kernel} user-space-fallback={self.fallbacks}"
                + (f" user-mode={self.user}" if self.user else ""))
