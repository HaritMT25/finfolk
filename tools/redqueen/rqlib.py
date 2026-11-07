"""rqlib.py: shared helpers for the Red Queen tournament tooling (Python 3 stdlib only).

Hashing, canonical JSON, durable writes, seed derivation and a version-independent
random generator. Everything here is deterministic across Python versions (3.10
to 3.14 are tested in CI): no `random` module, no multiprocessing.
"""
from __future__ import annotations

import datetime
import errno
import hashlib
import json
import os

SHA_PENDING = "pending"   # a plan registered before its snapshots exist (plan.py --pending)
MASK64 = (1 << 64) - 1


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _libc():
    try:
        import ctypes
        return ctypes.CDLL("libc.so.6", use_errno=True)
    except (OSError, ImportError):
        return None


_LIBC = _libc()        # loaded in the parent: the forked child only calls into it
PR_SET_PDEATHSIG = 1


def death_signal(expected_parent=None):
    """-> a preexec_fn for subprocess.Popen: the child gets SIGKILL when its parent dies, even by
    SIGKILL (Linux PR_SET_PDEATHSIG). Workers are plain subprocesses (no multiprocessing: Python
    3.14 changed its default start method), so this is the only process plumbing.
    SIGKILL, not SIGTERM (review round 3): a worker HANDLES SIGTERM (orderly shutdown: stop the
    engine, exit), and a handled signal stays pending while the process is stopped, so a SIGSTOPped
    worker would outlive its dead runner, and its engine (whose parent, the worker, is alive) with
    it. SIGKILL ends a stopped process; the worker's death then SIGKILLs its engine the same way.
    The runner's own orderly shutdown still goes through SIGTERM to each group (run.stop_groups).
    expected_parent: the spawning process's pid, taken BEFORE the fork. A parent that died between
    the fork and the prctl would not signal the child (it has been reparented already), so after
    a successful prctl the child compares getppid() with it and exits at once if they differ. A
    failing prctl raises in the child (Popen then raises in the parent: nothing runs unguarded).
    Without libc (not Linux) it is a no-op."""
    import signal
    parent = os.getpid() if expected_parent is None else expected_parent

    def pre():
        if _LIBC is None:
            return
        if _LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError("prctl(PR_SET_PDEATHSIG) failed")
        if os.getppid() != parent:
            os._exit(1)      # the parent is already gone: run nothing
    return pre


# ------------------------------------------------------------------- hashing
def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_sha256(s):
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


# ------------------------------------------------------------ canonical JSON
def canonical(obj):
    """The one byte encoding of a JSON value this tooling hashes: sorted keys, no spaces, ASCII,
    no NaN / Infinity, a trailing newline. Floats print as Python's repr (shortest round trip)."""
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
            + "\n").encode("ascii")


def canonical_sha(obj):
    return sha256_bytes(canonical(obj))


# ------------------------------------------------------------ durable writes
def fsync_dir(d):
    """fsync a directory, so a rename / unlink in it is durable. A filesystem that cannot fsync a
    directory (EINVAL / ENOTSUP / EBADF) is tolerated."""
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EBADF):
            raise
    finally:
        os.close(fd)


def fsync_file(p):
    fd = os.open(p, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_durable(path, data):
    """bytes or str -> a temporary file, fsync'd, renamed over path, then the directory fsync'd
    AFTER the rename (the rename itself is then durable)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(os.path.dirname(os.path.abspath(path)))


def write_json_durable(path, obj):
    write_durable(path, canonical(obj))


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_text(path):
    return read_bytes(path).decode("utf-8")


def read_json(path):
    return json.loads(read_text(path))


# ------------------------------------------------------------------- seeds
def derive_seed(*parts):
    """A 32-bit seed from printable parts (SHA-256; stable across runs and Python versions).
    32 bits because the engine parses --transplant-seed / --reseed-after-load as unsigned 32-bit."""
    h = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:4], "little")


def derive64(*parts):
    h = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "little")


class SplitMix64:
    """Steele, Lea & Flood's SplitMix64: a fixed, documented generator (the same numbers on every
    Python version and platform), with unbiased bounded draws by rejection."""

    def __init__(self, seed):
        self.s = int(seed) & MASK64

    def next64(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & MASK64
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def below(self, n):
        """Uniform integer in [0, n)."""
        if n <= 0:
            raise ValueError(f"below({n})")
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            x = self.next64()
            if x < limit:
                return x % n

    def sample(self, n, k):
        """k distinct indices of range(n), in draw order (partial Fisher-Yates)."""
        if not 0 <= k <= n:
            raise ValueError(f"cannot draw {k} distinct of {n}")
        idx = list(range(n))
        for i in range(k):
            j = i + self.below(n - i)
            idx[i], idx[j] = idx[j], idx[i]
        return idx[:k]

    def shuffle(self, xs):
        """In place, Fisher-Yates from the end."""
        for i in range(len(xs) - 1, 0, -1):
            j = self.below(i + 1)
            xs[i], xs[j] = xs[j], xs[i]
        return xs
