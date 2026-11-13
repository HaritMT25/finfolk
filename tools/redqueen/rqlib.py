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
import re

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


def mkdirs_durable(path, *, ancestors=False):
    """Create a directory chain and fsync each new entry's parent before returning.

    Call before launching workers: syncing files inside a cell does not persist
    the cell's own entry in work/, or a new study's entry in its parent. Startup
    uses ancestors=True to repair barriers left unfinished by an earlier attempt.
    """
    path = os.path.abspath(path)
    missing = []
    parent = path
    while not os.path.isdir(parent):
        missing.append(parent)
        parent = os.path.dirname(parent)
    os.makedirs(path, exist_ok=True)
    if ancestors:
        directory = path
        while True:
            fsync_dir(directory)
            parent = os.path.dirname(directory)
            if parent == directory:
                return
            directory = parent
    for directory in reversed(missing):
        fsync_dir(os.path.dirname(directory))


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


# ---------------------------------------------------------- seed reservations
class ReservationError(ValueError):
    """An inventory cannot establish a nonempty, validated reservation set."""


def load_reservations(path):
    """Return (distinct seeds, {path, sha256, seeds: distinct count}) from one byte read.

    See docs/redqueen_reservations.md for the complete input grammar. Flat
    inventories use all labels, not just seed-named ones. Structural records and
    every inventory-array record are interpreted independently; known metadata
    collections are traversed without requiring seeds in each element. Metadata integers
    are reserved only under the historical recursive seed-key policy. Argv seeds
    additionally obey the engine's unsigned 32-bit range.
    """
    context = "document 1"

    def fail(message, where=None):
        raise ReservationError(f"{path}: {where or context}: {message}")

    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                fail(f"duplicate JSON key {key!r}")
            obj[key] = value
        return obj

    try:
        raw = read_bytes(path)
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        fail(str(exc))
    lines = [(number, line.strip()) for number, line in enumerate(text.splitlines(), 1) if line.strip()]
    seeds = set()
    seed_flags = {"--seed", "--transplant-seed", "--reseed-after-load"}

    def argv_seeds(args, found, where):
        consumed = set()
        for index, arg in enumerate(args):
            if not isinstance(arg, str):
                continue
            flag = arg.split("=", 1)[0]
            if flag not in seed_flags:
                continue
            if arg != flag:
                fail(f"{flag} requires a separate decimal integer argument", where)
            if index + 1 == len(args):
                fail(f"{flag} is missing its seed argument", where)
            value = args[index + 1]
            if not ((type(value) is int and value >= 0)
                    or (isinstance(value, str) and re.fullmatch(r"[0-9]+", value))):
                fail(f"{flag} requires a nonnegative decimal integer (got {value!r})", where)
            # Bound the decimal text before conversion, including arbitrarily
            # long argv strings that strtoul would overflow or zero-pad.
            digits = str(value).lstrip("0") or "0"
            if len(digits) > 10 or (len(digits) == 10 and digits > "4294967295"):
                fail(f"{flag} seed must be in 0..4294967295 (got {value!r})", where)
            found.add(int(digits))
            consumed.update((index, index + 1))
        return consumed

    # These fields identify records, unlike arbitrary inventory labels such as
    # w01_seed or the seed-kind label reseed. Keep the distinction explicit.
    record_fields = {"seed", "seeds", "founder_seed", "seed_rederived", "transplant_seed", "reseed_after_load",
                     "slot_seed", "donor_seed", "pred_seed"}
    scalar_metadata = {"steps", "attempt", "replicate", "frame", "index"}
    inventory_fields = {"worlds", "reserved", "reservations", "records", "inventory"}
    # These are structural collections emitted by the study tools, not lists of
    # independent reservations. Still traverse their seed fields and argv: e.g.
    # receipt.seeds is historically reserved even when it is a count.
    metadata_fields = {
        "avoid", "avoided", "per_block", "block_allocations", "containers", "sources",
        "ages", "cores", "acceptance", "picked", "configchanges", "swapped", "state",
        "candidates", "segments", "pairs", "replicates", "rows", "results", "args",
        "schedule", "block_order", "horizons",
        "availability", "burn_in",
    }
    legacy_metadata = {
        "id", "design", "resident", "resident_name", "resident_sha256", "invader",
        "invader_name", "invader_sha256", "mode", "fraction", "state", "condition",
        "predators", "replicate", "steps", "checkpoint_every", "log_every",
        "keep_intermediate", "seed_namespace", "core", "assay", "h", "i", "j", "r",
        "_invader_read_sha256", "_resident_read_sha256",
    }
    world_metadata = {"id", "treatment", "sentinel", "attempt", "total", "frame",
                      "prey", "predators", "status", "block", "total_steps",
                      "world", "extinct_row", "guild", "utc"}
    metadata_schemas = {"finfolk.redqueen.recovery/1", "finfolk.redqueen.recoveryextra.result/1",
                        "finfolk.redqueen.noisebank.bank/2"}
    status_fields = {"archive_root", "availability", "burn_in", "counts", "root", "worlds"}
    seed_audit_fields = {"all_four_classes_disjoint", "avoid_count", "avoid_sha256",
                         "historical_retained", "historical_sha256", "new_distinct_seeds"}
    identity_fields = {"base", "head", "seed", "steps", "base_exit", "identical",
                       "base_sha256", "head_sha256", "elapsed_seconds", "head_artifact"}

    def metadata_keys(obj):
        """Resolve the few field names whose emitted metadata role is contextual."""
        keys = set(metadata_fields)
        schema = obj.get("schema")
        if schema in ("finfolk.redqueen.noisebank-reservations/1",
                      "finfolk.invasion.gate-protocol/1", *metadata_schemas) or status_fields <= obj.keys():
            keys.add("worlds")  # world labels / construction descriptions
        # The registry audit has a world COUNT, not a reservation collection.
        if {"registry_sha256", "registry_avoid_loader_count", "reserved_seeds", "ok"} <= obj.keys():
            keys.add("worlds")
        return keys

    def walk(obj, found, where, hint=False, strict=False, group_labels=False,
             inventory=False, provenance=False, metadata_tree=False, world_labels=False):
        if inventory and not hint and not group_labels and not provenance:
            metadata_tree = world_labels = False
        if inventory and not hint and not group_labels and not provenance and not isinstance(obj, list):
            if not isinstance(obj, dict):
                fail("inventory containers must be arrays or objects, not metadata scalars", where)
            if (isinstance(obj, dict) and obj
                    and "schema" not in obj
                    and not {key.lower() for key in obj} & record_fields
                    and not all(type(value) is int for value in obj.values())):
                for key, value in obj.items():
                    found.update(document(value, f"{where} record[{key!r}]"))
            else:
                found.update(document(obj, where))
            return
        if isinstance(obj, dict):
            known_metadata = metadata_keys(obj)
            report = obj.get("schema") in tuple(metadata_schemas) or status_fields <= obj.keys()
            metadata_tree |= report
            world_labels |= report
            archive = obj.get("schema") == "finfolk.invasion.archived-seeds/1"
            if archive:
                entries = obj.get("all")
                if (not isinstance(entries, dict) or not entries
                        or any(not re.fullmatch(r"[0-9]+", key) for key in entries)):
                    fail("archived-seeds/1 requires nonempty numeric seed keys under 'all'", where)
                found.update(int(key) for key in entries)
            for key, value in obj.items():
                label = key.lower()
                seed_hint = "seed" in label
                metadata = any(token in label for token in ("scheme", "namespace", "sha256", "hash", "rule", "note", "path"))
                labels = group_labels or label in ("groups", "seed_slot")
                seed_value = seed_hint and not metadata and not labels
                walk(value, found, f"{where}.{key}", hint or seed_hint,
                     strict or seed_value, labels,
                     label in inventory_fields and label not in known_metadata
                     and not (world_labels and label == "worlds"),
                     provenance or (archive and key == "all"),
                     metadata_tree or label in known_metadata,
                     world_labels or label == "args")
        elif isinstance(obj, list):
            consumed = argv_seeds(obj, found, where)
            # Only known metadata collections bypass per-record admission.
            # An actual inventory starts each record with a fresh context/set.
            records = (not hint and not group_labels and not provenance and not metadata_tree
                       and (inventory or any(isinstance(v, (dict, list)) for v in obj)))
            if records and not consumed:
                found.update(document(obj, where, flat=inventory))
            else:
                for index, value in enumerate(obj):
                    if index not in consumed:
                        if records and isinstance(value, (dict, list)):
                            found.update(document(value, f"{where} record[{index + 1}]", flat=inventory))
                        else:
                            walk(value, found, f"{where}[{index + 1}]", hint, strict,
                                 group_labels, provenance=provenance, metadata_tree=metadata_tree,
                                 world_labels=world_labels)
        elif type(obj) is int:
            if hint:
                if obj < 0:
                    fail("negative seed reservation", where)
                found.add(obj)
        elif strict and obj is not None:
            fail(f"seed reservations must be JSON integers (got {obj!r})", where)

    def document(doc, where, flat=True):
        # Validation must use a fresh set, including at dictionary-wrapped array
        # boundaries: a valid or repeated sibling cannot mask an invalid record.
        found = set()
        if isinstance(doc, list):
            if argv_seeds(doc, found, where):
                walk(doc, found, where)
            else:
                for index, value in enumerate(doc, 1):
                    if not flat and not isinstance(value, (dict, list)):
                        fail("ambiguous scalar in a metadata collection; use an explicit inventory container", f"{where} record[{index}]")
                    found.update(document(value, f"{where} record[{index}]", flat=flat))
        elif type(doc) is int and doc >= 0:
            found.add(doc)
        elif isinstance(doc, dict):
            labels = {key.lower() for key in doc}
            legacy = bool(labels & {"slot_seed", "donor_seed", "pred_seed"})
            record = bool(labels & record_fields)
            known_metadata = metadata_keys(doc)
            if legacy and any(key.lower() in {"slot_seed", "donor_seed", "pred_seed", "reseed"}
                              and value is not None and type(value) is not int
                              for key, value in doc.items()):
                fail("legacy plan seeds must be integers or null; ambiguous with inventory labels", where)
            if legacy and any(key.lower() == "id" and not isinstance(value, str)
                              for key, value in doc.items()):
                fail("legacy plan id must be a string; ambiguous with a flat inventory label", where)
            # Discriminators cannot double as arbitrary flat-inventory labels.
            # Check before shape classification, including dictionary records.
            for key, value in doc.items():
                if (key.lower() in inventory_fields and key.lower() not in known_metadata
                        and not isinstance(value, (dict, list))):
                    fail("inventory containers must be arrays or objects, not metadata scalars", f"{where}.{key}")
            if "schema" in doc and not isinstance(doc["schema"], str):
                fail("schema must be a string, not a flat-inventory label", f"{where}.schema")
            integers = bool(doc) and all(type(v) is int and v >= 0 for v in doc.values())
            if flat and integers and not record and not labels & (scalar_metadata | inventory_fields) and "schema" not in doc:
                found.update(doc.values())
            else:
                # Scalar-only maps without a schema cannot silently become
                # partial inventories. Structural field names plus known record
                # metadata establish the interpretation; other shapes must be
                # explicit wrappers or schema-bearing structured documents.
                scalar = all(not isinstance(v, (dict, list)) for v in doc.values())
                if scalar and "schema" not in doc:
                    allowed = scalar_metadata | (legacy_metadata if legacy else set())
                    if "seed" in labels or "reserved_seeds" in labels:
                        allowed |= world_metadata
                    if seed_audit_fields <= labels:
                        allowed |= seed_audit_fields
                    if identity_fields <= labels:
                        allowed |= identity_fields
                    # Named parameter records and analysis rows identify a run
                    # with strings, unlike an arbitrary mixed scalar inventory.
                    if ("seed" in labels and (isinstance(doc.get("name"), str)
                            or (isinstance(doc.get("run"), str)
                                and isinstance(doc.get("config"), str)))):
                        allowed |= labels
                    unknown = [key for key in doc if "seed" not in key.lower()
                               and key.lower() not in allowed]
                    if not any("seed" in label for label in labels) or unknown:
                        fail("ambiguous or unsupported scalar reservation map", where)
                walk(doc, found, where)
        else:
            fail("expected seed-keyed JSON, arrays of objects/integers, or decimal integers per line", where)
        if not found:
            fail("no seed reservations extracted; empty or unsupported inventory record", where)
        return found

    if lines and all(re.fullmatch(r"[0-9]+", line) for _, line in lines):
        seeds = {int(line) for _, line in lines}
    else:
        try:
            doc = json.loads(text, object_pairs_hook=unique_object,
                             parse_constant=lambda value: fail(f"invalid JSON constant {value}"))
            docs = [(context, doc)]
        except json.JSONDecodeError:
            try:
                docs = []
                for number, line in lines:
                    context = f"JSONL line {number}"
                    docs.append((context, json.loads(line, object_pairs_hook=unique_object,
                                                    parse_constant=lambda value: fail(f"invalid JSON constant {value}"))))
            except json.JSONDecodeError as exc:
                fail(f"unsupported reservation format ({exc})")
        for context, doc in docs:
            seeds.update(document(doc, context))
    if not seeds:
        fail("no seed reservations extracted; empty or unsupported inventory")
    return seeds, {"path": os.path.abspath(path), "sha256": sha256_bytes(raw), "seeds": len(seeds)}


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
