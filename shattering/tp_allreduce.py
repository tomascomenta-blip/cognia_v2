"""
shattering/tp_allreduce.py
==========================
Centralized all-reduce over plain TCP sockets, pure numpy + stdlib. No PyTorch,
no NCCL (forbidden on nodes), no extra deps.

This is the Phase 2 transport for Shattering v2 (see SHATTERING_V2_DESIGN.md,
Decision 5 = centralized reducer first). Each tensor-parallel rank holds a
partial (seq, hidden) tensor; an all-reduce sums the T partials and returns the
sum to every rank. The reducer is a barrier: it waits for all T contributions of
a round, sums them, then broadcasts the sum back.

Why centralized (not ring): the payload is tiny (a token's hidden state is a few
KB), so the regime is latency-bound, not bandwidth-bound. With few ranks the two
fixed hops of a central reducer beat the 2(N-1) hops of a ring. (Recursive-
doubling replaces this when N grows past ~8 — future work.)

Sanity checks (Decision 10): every received tensor is screened for NaN/inf and an
optional magnitude bound. A bad contribution is rejected with a visible ERROR to
the offending rank instead of silently corrupting everyone's output.

Wire frame (big-endian):
    magic   : 1 byte  = 0xC0
    msg_type: 1 byte  (1=DATA, 2=SUM, 3=ERROR)
    ndim    : 1 byte
    shape   : ndim * uint32
    nbytes  : uint32   (length of the float32 payload that follows)
    payload : nbytes   (float32, C-contiguous)
For ERROR frames the payload is a UTF-8 message (msg_type=3, ndim=0).
"""

from __future__ import annotations

import socket
import struct
import threading
from typing import List, Optional

import numpy as np

_MAGIC = 0xC0
_DATA, _SUM, _ERROR = 1, 2, 3

# Default magnitude guard: a token hidden state should never exceed this in a
# healthy forward pass. Generous so it only trips on real corruption / overflow.
DEFAULT_MAX_ABS = 1e6


# ── framing helpers ──────────────────────────────────────────────────────────

def _recvall(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed mid-frame")
        buf.extend(chunk)
    return bytes(buf)


def _send_tensor(sock: socket.socket, arr: np.ndarray, msg_type: int = _DATA) -> None:
    a = np.ascontiguousarray(arr, dtype=np.float32)
    hdr = struct.pack(">BBB", _MAGIC, msg_type, a.ndim)
    hdr += b"".join(struct.pack(">I", d) for d in a.shape)
    payload = a.tobytes()
    hdr += struct.pack(">I", len(payload))
    sock.sendall(hdr + payload)


def _send_error(sock: socket.socket, message: str) -> None:
    msg = message.encode("utf-8")
    hdr = struct.pack(">BBB", _MAGIC, _ERROR, 0) + struct.pack(">I", len(msg))
    sock.sendall(hdr + msg)


def _recv_frame(sock: socket.socket) -> "tuple[int, Optional[np.ndarray], str]":
    """Returns (msg_type, array_or_None, error_message)."""
    head = _recvall(sock, 3)
    magic, msg_type, ndim = struct.unpack(">BBB", head)
    if magic != _MAGIC:
        raise ConnectionError(f"bad magic byte: {magic:#x}")
    shape = tuple(struct.unpack(">I", _recvall(sock, 4))[0] for _ in range(ndim))
    nbytes = struct.unpack(">I", _recvall(sock, 4))[0]
    payload = _recvall(sock, nbytes) if nbytes else b""
    if msg_type == _ERROR:
        return msg_type, None, payload.decode("utf-8", "replace")
    arr = np.frombuffer(payload, dtype=np.float32).reshape(shape) if nbytes else np.zeros(shape, np.float32)
    return msg_type, arr.copy(), ""


# ── sanity check ─────────────────────────────────────────────────────────────

def is_sane(arr: np.ndarray, max_abs: float = DEFAULT_MAX_ABS) -> "tuple[bool, str]":
    """Cheap screen for a contributed tensor. Returns (ok, reason)."""
    if not np.isfinite(arr).all():
        n_nan = int(np.isnan(arr).sum())
        n_inf = int(np.isinf(arr).sum())
        return False, f"non-finite values (nan={n_nan}, inf={n_inf})"
    m = float(np.max(np.abs(arr))) if arr.size else 0.0
    if m > max_abs:
        return False, f"magnitude {m:.3e} exceeds max_abs {max_abs:.3e}"
    return True, ""


# ── server (the reducer / coordinator) ───────────────────────────────────────

class AllReduceServer:
    """Centralized barrier all-reduce for `world_size` ranks over TCP.

    Accepts `world_size` client connections, then for each round receives one
    tensor from every rank, screens each, sums them, and broadcasts the sum back.
    Runs the accept+reduce loop in a background thread.
    """

    def __init__(self, world_size: int, host: str = "127.0.0.1", port: int = 0,
                 max_abs: float = DEFAULT_MAX_ABS):
        self.world_size = world_size
        self.max_abs = max_abs
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((host, port))
        self._srv.listen(world_size)
        self.host, self.port = self._srv.getsockname()
        self._conns: List[socket.socket] = []
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[str] = None
        # rank index of the last culprit caught by sanity check (Decision 10)
        self.expelled_rank: Optional[int] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            for _ in range(self.world_size):
                conn, _addr = self._srv.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._conns.append(conn)
            while True:
                if not self._reduce_round():
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            for c in self._conns:
                try:
                    c.close()
                except OSError:
                    pass

    def _reduce_round(self) -> bool:
        partials: List[np.ndarray] = []
        for rank, conn in enumerate(self._conns):
            try:
                msg_type, arr, _ = _recv_frame(conn)
            except ConnectionError:
                return False  # a rank disconnected -> end of session
            if msg_type != _DATA:
                return False
            ok, reason = is_sane(arr, self.max_abs)
            if not ok:
                self.expelled_rank = rank
                self._error = f"rank {rank}: {reason}"
                for c in self._conns:
                    try:
                        _send_error(c, self._error)
                    except OSError:
                        pass
                return False
            partials.append(arr)
        total = partials[0].copy()
        for p in partials[1:]:
            total += p
        for conn in self._conns:
            _send_tensor(conn, total, _SUM)
        return True

    def close(self) -> None:
        try:
            self._srv.close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)


# ── client (a rank) ──────────────────────────────────────────────────────────

class AllReduceClient:
    """A tensor-parallel rank's handle to the reducer. all_reduce sums across ranks."""

    def __init__(self, host: str, port: int, rank: int = 0):
        self.rank = rank
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((host, port))
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def all_reduce(self, arr: np.ndarray) -> np.ndarray:
        """Send this rank's partial; return the element-wise sum over all ranks."""
        _send_tensor(self._sock, arr, _DATA)
        msg_type, out, err = _recv_frame(self._sock)
        if msg_type == _ERROR:
            raise RuntimeError(f"all-reduce rejected: {err}")
        return out

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
