"""store.py: the Red Queen study root's content-addressed store and its chunked cell archive.

~900k assays must not leave millions of loose files. A finished cell leaves two small records
(bundle.json, deterministic; done.json, its timings) in STUDY/work/<id>/; the runner packs them
into verified chunks and only then deletes the cell's working files. Everything bulky is
either content-addressed once (sources, common manifests, tools, the binary) or deleted with
its SHA-256 kept (checkpoints: they replay exactly).

STUDY/store/objects/<aa>/<sha256>      a blob: a snapshot or template (an independent, verified,
                                        read-only copy; a hard link only with --link-sources, and
                                        only into a finalized, read-only archive: see
                                        link_contract_problem), a tool version, the binary
STUDY/store/objects/<aa>/<sha256>.gz   a gzip-compressed JSON blob (common manifests): the name
                                        is the SHA-256 of the UNcompressed content
STUDY/chunks/chunk_<NNNNNN>.zip         members <id>/bundle.json and <id>/done.json, sorted by id
STUDY/chunks/index.jsonl                one line per COMMITTED chunk: its file, SHA-256, size and,
                                        per cell, the bundle's and done record's SHA-256, its common
                                        group and the common checkpoint's SHA-256 (and, for a /3
                                        bundle, pack()'s stamp that its complete age summary was
                                        verified, bound to the digest of the bytes checked:
                                        age_stamp, D8 v2 rule 48)

Pack protocol (pack()): (1) every candidate cell's bundle.json re-hashed against its done.json;
(2) the chunk written as a temporary file, fsync'd, renamed, the directory fsync'd; (3) the chunk
re-read: every member's compression method (DEFLATE, PACK_METHOD: any other is refused before it
is decoded, here, in every check and by every reader: read_member, and read_packed for collection
and replay), zip CRCs, and every member's SHA-256 against its record;
(4) the index line appended and fsync'd (the commit point); (5) only then the cells' working
directories deleted and work/ fsync'd. recover() (at every runner start) undoes a crash at any point, but first checks,
read-only: the committed chunks (in full where a packed cell's working directory is still there;
by SHA-256 when deep or when they hold a stamped /3 entry), every indexed /3 completion's age
summary (indexed_age_problems) and every leftover bundle. Any failure repairs, removes and
deletes nothing and stops the runner. Only then is a truncated last index line dropped and the
index fsync'd, a chunk file without an index line deleted (its cells still have their working
directories), and the leftover directories deleted.
Common-group consistency: every cell of one common group (prey world, time, replicate) must have
built the same common checkpoint (SHA-256); a disagreement is nondeterminism, and pack() refuses.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import struct
import zipfile
import zlib

try:                    # (zipfile's own guard: a Python built without liblzma has no lzma)
    import lzma
except ImportError:
    lzma = None

import rqlib

OBJECTS = os.path.join("store", "objects")
CHUNKS = "chunks"
INDEX = os.path.join(CHUNKS, "index.jsonl")
WORK = "work"
CHUNK_SCHEMA = "finfolk.redqueen.chunk/1"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_VERIFIED = set()   # (root, sha) verified by this process


class StoreError(Exception):
    pass


# ------------------------------------------------------------------ objects
def _obj(root, sha, gz=False):
    return os.path.join(root, OBJECTS, sha[:2], sha + (".gz" if gz else ""))


def _writable(p):
    return bool(os.stat(p).st_mode & 0o222)


_LINKS_ALLOWED = False   # set by a runner or worker started with --link-sources (allow_links)


def allow_links(flag):
    """The store policy of this process: False (the default) = every object must be an independent
    read-only copy; True (--link-sources) = read-only hard links into a finalized archive accepted."""
    global _LINKS_ALLOWED
    _LINKS_ALLOWED = bool(flag)


def _acceptable(p):
    """An object this policy may serve as it is: no write bit, and (unless links are allowed) no
    other name for its inode (link count 1)."""
    st = os.stat(p)
    if st.st_mode & 0o222:
        return False
    return st.st_nlink == 1 or _LINKS_ALLOWED


def _migrate(p, data):
    """Replace object p by an independent read-only copy of `data` (the bytes just read from p and
    verified against its name): a new file, fsync'd, 0444, renamed over p, the directory fsync'd.
    The old inode (a legacy hard link shares it with the archive) is left as it was: never
    chmod'ed, never written."""
    tmp = f"{p}.mig.tmp.{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o444)
    os.replace(tmp, p)
    rqlib.fsync_dir(os.path.dirname(p))


def has(root, sha):
    """The path of a verified blob with this content (raw or .gz), else None. Review round 3, P1-1:
    a blob the policy does not accept as it is (writable, or a hard link shared with an archive:
    an object a root made before round 2 can be either) is re-hashed from the bytes read and, if
    they are right, replaced by an independent read-only copy of THOSE bytes (_migrate) before it
    is served; a blob that no longer matches its name is not served."""
    if not rqlib.is_sha256(sha):
        return None
    for gz in (False, True):
        p = _obj(root, sha, gz)
        if not os.path.isfile(p):
            continue
        if (root, sha, gz) in _VERIFIED and _acceptable(p):
            return p
        try:
            data = rqlib.read_bytes(p)
            got = rqlib.sha256_bytes(gzip.decompress(data) if gz else data)
        except (OSError, EOFError, gzip.BadGzipFile):
            continue
        if got != sha:
            continue
        if not _acceptable(p):
            _migrate(p, data)
        _VERIFIED.add((root, sha, gz))
        return p
    return None


def migrate_all(root, log=print):
    """At a runner's start: every object the policy does not accept as it is goes through has()
    (migrated to an independent read-only copy if its content is still right). -> (migrated count,
    problems: objects whose content no longer matches their name)."""
    od = os.path.join(root, OBJECTS)
    n, probs = 0, []
    for dp, _, fs in os.walk(od) if os.path.isdir(od) else []:
        for f in sorted(fs):
            name = f[:-3] if f.endswith(".gz") else f
            if not rqlib.is_sha256(name):
                continue
            p = os.path.join(dp, f)
            if _acceptable(p):
                continue
            if has(root, name) is None:
                probs.append(f"store object {name[:12]} no longer matches its name (changed through a shared link?)")
            else:
                n += 1
    if n:
        log(f"store: {n} legacy object(s) replaced by independent read-only copies")
    return n, probs


def start_session(root, link_sources, log=print):
    """A runner's start (review round 4): migrate_all under the COPY policy first, so every object an
    earlier session left shared (a hard link, however read-only, whose archive contract nobody
    re-checked) or writable becomes a verified independent copy; only then this session's policy.
    With --link-sources, links therefore exist only for this session's insertions, each made
    through put_file's archive-contract check. -> migrate_all's (count, problems)."""
    allow_links(False)
    res = migrate_all(root, log)
    allow_links(link_sources)
    return res


FINALIZED ="FINALIZED"   # the marker a finished archive directory carries (the --link-sources contract)


def link_contract_problem(src):
    """Why src may NOT be hard-linked into the store (None = it may). Review round 2, P1-1: a hard
    link shares the archive's inode, so the archive must be immutable, not merely hashed once:
    the file has no write permission for anyone, its directory has none either (no entry can be
    replaced), and the directory holds the FINALIZED marker its archiver writes when the world is
    complete."""
    try:
        st = os.stat(src)
        d = os.path.dirname(os.path.abspath(src))
        dst = os.stat(d)
    except OSError as e:
        return f"{src}: {e}"
    if st.st_mode & 0o222:
        return f"{src} is writable (mode {st.st_mode & 0o777:o})"
    if dst.st_mode & 0o222:
        return f"its directory {d} is writable (mode {dst.st_mode & 0o777:o})"
    if not os.path.isfile(os.path.join(d, FINALIZED)):
        return f"its directory {d} has no {FINALIZED} marker"
    return None


def _publish(root, tmp, final):
    d = os.path.dirname(final)
    os.replace(tmp, final)
    rqlib.fsync_dir(d)


def _mkdirs(root, sha):
    d = os.path.dirname(_obj(root, sha))
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
        rqlib.fsync_dir(os.path.dirname(d))
    return d


def put_file(root, src, want=None, link=False):
    """src into the store under its SHA-256 -> sha. By default an INDEPENDENT copy: written to a
    temporary file, fsync'd, hashed (that hash is the object's name and must equal `want` when
    given), made read-only (0444), renamed, the directory fsync'd. link=True (the runner's
    --link-sources) hard-links instead, and only when link_contract_problem(src) is None (else
    StoreError): the archive must be finalized and read-only. Idempotent, atomic, durable, safe
    for concurrent workers."""
    if want is not None and has(root, want):
        return want
    if link:
        why = link_contract_problem(src)
        if why:
            raise StoreError(f"--link-sources refused: {why}")
    stage = os.path.join(root, OBJECTS)
    os.makedirs(stage, exist_ok=True)
    tmp = os.path.join(stage, f".put.tmp.{os.getpid()}")
    if os.path.lexists(tmp):
        os.remove(tmp)
    if link:
        os.link(src, tmp)
    else:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o444)
    rqlib.fsync_file(tmp)
    sha = rqlib.sha256_file(tmp)
    if want is not None and sha != want:
        os.remove(tmp)
        raise StoreError(f"{src} is {sha[:12]}, not the needed {want[:12]}")
    if link and _writable(tmp):
        os.remove(tmp)
        raise StoreError(f"--link-sources: {src} became writable")
    if link:
        allow_links(True)    # (the caller chose the link policy for this process)
    if has(root, sha):
        os.remove(tmp)
        return sha
    _mkdirs(root, sha)
    _publish(root, tmp, _obj(root, sha))
    _VERIFIED.add((root, sha, False))
    return sha


def put_bytes(root, data, compress=False):
    """bytes into the store (gzip level 9, mtime 0 when compress) -> sha of the raw bytes."""
    sha = rqlib.sha256_bytes(data)
    if has(root, sha):
        return sha
    _mkdirs(root, sha)
    final = _obj(root, sha, compress)
    tmp = f"{final}.tmp.{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(gzip.compress(data, compresslevel=9, mtime=0) if compress else data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o444)
    _publish(root, tmp, final)
    _VERIFIED.add((root, sha, compress))
    return sha


def get_bytes(root, sha):
    p = has(root, sha)
    if p is None:
        raise StoreError(f"no blob {sha[:12]} in {root}/{OBJECTS}")
    data = rqlib.read_bytes(p)
    return gzip.decompress(data) if p.endswith(".gz") else data


def materialize(root, sha, dst):
    """A verified blob as the file dst (a copy) -> dst."""
    data = get_bytes(root, sha)
    with open(dst, "wb") as f:
        f.write(data)
    return dst


def sync_objects(root, shas):
    """Durability barrier: the blobs' contents, their directories and the store's top directories."""
    dirs = set()
    for sha in shas:
        p = has(root, sha)
        if p is None:
            raise StoreError(f"blob {sha[:12]} missing at the durability barrier")
        rqlib.fsync_file(p)
        dirs.add(os.path.dirname(p))
    for d in sorted(dirs):
        rqlib.fsync_dir(d)
    for d in (os.path.join(root, OBJECTS), os.path.join(root, "store"), root):
        if os.path.isdir(d):
            rqlib.fsync_dir(d)


# ------------------------------------------------------------------- chunks
def load_index(root, repair=False):
    """-> (records list, {cell id: (chunk record, cell entry)}). A truncated last line (a crash while
    appending) is dropped; with repair the index is rewritten without it."""
    return _load_index(root, repair)[:2]


def _load_index(root, repair=False):
    """load_index -> (records, cells, whether a truncated last line was dropped)."""
    p = os.path.join(root, INDEX)
    recs, cells, dropped = [], {}, False
    if os.path.isfile(p):
        raw = rqlib.read_bytes(p)
        lines = raw.split(b"\n")
        for k, ln in enumerate(lines):
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln.decode())
            except ValueError:
                if k == len(lines) - 1 or all(not x.strip() for x in lines[k + 1:]):
                    dropped = True
                    break
                raise StoreError(f"{p}: corrupt line {k + 1} (not the last)")
            if k == len(lines) - 1:      # complete JSON but no newline: the append may not be durable
                dropped = True
                break
            recs.append(rec)
        if dropped and repair:
            rqlib.write_durable(p, b"".join(rqlib.canonical(r) for r in recs))
    for rec in recs:
        for cid, e in rec["cells"].items():
            if cid in cells:
                raise StoreError(f"cell {cid} is in two chunks ({cells[cid][0]['chunk']}, {rec['chunk']})")
            cells[cid] = (rec, e)
    return recs, cells, dropped


def common_groups(cells):
    """{common group: common sha256} over indexed cells (raises on a disagreement)."""
    out = {}
    for cid, (_, e) in cells.items():
        g, h = e.get("common_group"), e.get("common_sha256")
        if g and h:
            if out.setdefault(g, h) != h:
                raise StoreError(f"common group {g}: two different common checkpoints ({out[g][:12]}, {h[:12]})")
    return out


def pair_groups(cells):
    """{pair group (reseed group | prey policy | assay): the arena's prey-config sha256} over indexed
    cells: a challenge and its predator-free control run on the same prey settings (raises if not)."""
    out = {}
    for cid, (_, e) in cells.items():
        g, h = e.get("pair_group"), e.get("prey_config_sha256")
        if g and h:
            if out.setdefault(g, h) != h:
                raise StoreError(f"pair group {g}: two different prey settings ({out[g][:12]}, {h[:12]})")
    return out


SHARING_SCHEMA = "finfolk.redqueen.sharing/1"
BUNDLE_V2 = "finfolk.redqueen.bundle/2"
BUNDLE_V3 = "finfolk.redqueen.bundle/3"


AGE_DIAGNOSTICS_SCHEMA = "finfolk.redqueen.agediagnostics/1"
AGE_SUMMARY_TAG = "the age summary (D8 rule 48)"    # in every age-summary problem (run.py tells the operator)
# (Codex re-reviews of 5ecffb5 and e82ed4e, P2) the index entry's stamp that pack() verified the /3
# bundle's complete age summary under THIS contract (age_summary_problems) before the commit point,
# bound to the bytes it checked: age_stamp = "<AGE_SUMMARY_CHECKED>:<the SHA-256 of exactly those
# bundle bytes>". It counts only when it names this contract and the entry's
# OWN bundle digest (age_stamp_bound), and only once the chunk holding the entry still matches the
# SHA-256 its index line records (indexed_age_problems). Anything else is unchecked and its packed
# bundle is read and checked in full: no stamp (packed by b83a029..870daa6, which did not check, or
# by 5ecffb5), e82ed4e's bare marker (the constant alone: it bound nothing), a stamp copied from
# another entry, an older contract's once this one is versioned up, or a chunk changed since.
AGE_SUMMARY_KEY = "age_summary"
AGE_SUMMARY_CHECKED = "finfolk.redqueen.agesummary/1"     # the contract's version (age_summary_problems)
# (Codex re-review of a5c366c, P2) pack() writes every chunk member DEFLATE-compressed, and only so (every
# packer since 58c9592): a member whose central directory names any other compression method (a damaged
# byte: STORED, BZIP2, LZMA, Python 3.14's Zstandard, or one zipfile does not know) is refused BEFORE a
# decoder runs on it (packed_member; verify_chunk refuses its chunk), so validation never hands chunk
# bytes to a decoder the packer does not use. (Codex re-review of 6407f80, P2) Nor does any consumer:
# read_member is always gated, and collection and replay read through read_packed, whose damaged
# members are a StoreError naming the root, chunk and cell (a refusal, never a codec's traceback).
PACK_METHOD = zipfile.ZIP_DEFLATED


def _codec_errors():
    """The decoders' own exceptions that zipfile lets through on damaged bytes (defence in depth behind
    PACK_METHOD): lzma's and, on Python 3.14+, Zstandard's (bz2 raises OSError, EOFError, ValueError)."""
    out = [lzma.LZMAError] if lzma is not None else []
    try:
        from compression import zstd
        out.append(zstd.ZstdError)
    except ImportError:
        pass
    return tuple(out)


# reading damaged chunk bytes can raise any of these (zlib.error: a corrupt deflate stream; EOFError: a
# short member; NotImplementedError / RuntimeError: a damaged method, version or flag; struct.error,
# zipfile.LargeZipFile: zipfile's own; _codec_errors: a codec's): never accepted, never a crash
UNREADABLE = (KeyError, ValueError, OSError, EOFError, RuntimeError, NotImplementedError, zipfile.BadZipFile,
              zipfile.LargeZipFile, struct.error, zlib.error) + _codec_errors()


def method_problem(zi):
    """Why the chunk member `zi` (a ZipInfo) must not be decoded -> str, or None: its compression method
    is not the one pack() writes (PACK_METHOD)."""
    if zi.compress_type == PACK_METHOD:
        return None
    return (f"{zi.filename}: compression method {zi.compress_type}, not the DEFLATE ({PACK_METHOD}) pack() "
            "writes: refused before decoding")


def packed_member(z, arc):
    """Member `arc` of the open chunk `z`, decoded only if it is compressed as pack() writes it -> bytes;
    any other method raises zipfile.BadZipFile (one of UNREADABLE) before a decoder runs."""
    zi = z.getinfo(arc)
    why = method_problem(zi)
    if why:
        raise zipfile.BadZipFile(why)
    return z.read(zi)


def sharing_required(bundle_schema, plan_schema):
    """/2 always used plan/2; /3 adds age diagnostics for both plan/1 and plan/2."""
    return bundle_schema == BUNDLE_V2 or (bundle_schema == BUNDLE_V3 and
                                        plan_schema == "finfolk.redqueen.plan/2")


def age_summary_problems(bundle):
    """(D8 v2 rule 48) Why a /3 bundle lacks its complete age-stratified summary -> problems: its
    score must cover exactly its cell's registered horizons, each with an age_strata that meets
    score.py's contract (score.age_strata_problems). /1 and /2 bundles predate the summary: no
    problem here; ingestion lists them as explicitly unavailable (age_diagnostics_entry)."""
    if bundle.get("schema") != BUNDLE_V3:
        return []
    import score
    hs = (bundle.get("cell") or {}).get("horizons")
    if not isinstance(hs, list) or not hs:
        return [f"{AGE_SUMMARY_TAG}: the cell names no registered horizons to cover"]
    return [f"{AGE_SUMMARY_TAG}: {p}" for p in score.age_strata_problems(bundle.get("score"), hs)]


def age_stamp(bundle_sha256):
    """pack()'s stamp on a /3 index entry whose bundle bytes (SHA-256 `bundle_sha256`) passed
    age_summary_problems under this contract (D8 v2 rule 48): "<contract>:<that digest>" (one string:
    a 2-key object costs about 300 more bytes per parsed index entry, at 900k entries per parse)."""
    return f"{AGE_SUMMARY_CHECKED}:{bundle_sha256}"


def age_stamp_bound(e):
    """Whether an index entry is a /3 completion whose stamp names this contract and the entry's OWN
    bundle digest (index level: the bytes are matched by indexed_age_problems). /1 and /2 entries
    predate the summary and carry no stamp."""
    d = e.get("bundle_sha256")
    return (e.get("bundle_schema") == BUNDLE_V3 and type(d) is str and len(d) == 64
            and e.get(AGE_SUMMARY_KEY) == age_stamp(d))


def age_stamped_chunks(cells):
    """The chunks holding a /3 entry with a bound stamp: their bytes vouch for those stamps, so they
    are matched against their recorded SHA-256 even by a verification that is not deep."""
    return {rec["chunk"] for rec, e in cells.values() if age_stamp_bound(e)}


def chunk_matches(root, rec):
    """Whether a committed chunk's file exists with the size and SHA-256 its index line records."""
    p = os.path.join(root, CHUNKS, rec["chunk"])
    try:
        return (os.path.isfile(p) and os.path.getsize(p) == rec.get("bytes")
                and rqlib.sha256_file(p) == rec.get("sha256"))
    except OSError:
        return False


def indexed_age_problems(root, cells=None, sound=None):
    """(Codex re-reviews of 5ecffb5 and e82ed4e, P2; D8 v2 rule 48) INDEXED completions keep the
    age-summary contract too: every /3 entry (either plan version) -> problems (each naming
    AGE_SUMMARY_TAG). An entry with a bound stamp (age_stamp_bound) is accepted WITHOUT decoding its
    bundle once the chunk holding it matches the size and SHA-256 its index line records: pack()
    matched every member against its entry (so the stamped bytes) before writing that line, so the
    chunk's current bytes are the bytes checked. `sound`: the chunks the caller has just matched
    (verify_all, recover), not hashed again, and a stamped entry in any other chunk is unchecked;
    without it, each chunk holding a bound stamp is hashed here, once. pack() runs this over the whole
    index before every chunk: hashing a chunk costs about as much per cell as parsing its index
    entries, while decoding every bundle each time would grow with the square of the study. Every
    other /3 entry (no stamp, a stamp not bound to it, or a chunk missing or changed since, of the
    same size or not) has its packed bundle read from its chunk (each chunk opened once) and checked
    against the index hash and the contract; an unreadable one is a problem, never accepted, and one
    whose compression method is not pack()'s is refused before it is decoded (packed_member: Codex
    re-review of a5c366c, P2)."""
    if cells is None:
        _, cells = load_index(root)
    stamped, todo = {}, {}
    for cid, (rec, e) in cells.items():
        if e.get("bundle_schema") == BUNDLE_V3:
            (stamped if age_stamp_bound(e) else todo).setdefault(rec["chunk"], [rec, []])[1].append(cid)
    for chunk, (rec, ids) in stamped.items():
        if not (chunk in sound if sound is not None else chunk_matches(root, rec)):
            todo.setdefault(chunk, [rec, []])[1].extend(ids)
    probs = []
    for chunk in sorted(todo):
        ids = sorted(todo[chunk][1])
        try:
            with zipfile.ZipFile(os.path.join(root, CHUNKS, chunk)) as z:
                for cid in ids:
                    where = f"{cid} (packed in {chunk})"
                    try:
                        data = packed_member(z, f"{cid}/bundle.json")
                        if rqlib.sha256_bytes(data) != cells[cid][1].get("bundle_sha256"):
                            probs.append(f"{where}: {AGE_SUMMARY_TAG} cannot be checked (its packed bundle "
                                         "does not match the index)")
                            continue
                        b = json.loads(data)
                    except UNREADABLE as x:
                        probs.append(f"{where}: {AGE_SUMMARY_TAG} cannot be checked ({x})")
                        continue
                    if not isinstance(b, dict) or b.get("schema") != BUNDLE_V3:
                        probs.append(f"{where}: {AGE_SUMMARY_TAG} cannot be checked (its packed bundle is not "
                                     "the /3 bundle its index entry names)")
                        continue
                    probs += [f"{where}: {p}" for p in age_summary_problems(b)]
        except UNREADABLE as x:
            probs += [f"{cid} (packed in {chunk}): {AGE_SUMMARY_TAG} cannot be checked ({x})" for cid in ids]
    return probs


def age_diagnostics_entry(cid, bundle):
    """One collected cell's age-stratified diagnostics (D8 v2 rule 48) at ingestion -> entry. A /3
    bundle gives its summary per horizon; one without a complete summary raises StoreError (a
    recording omission to repair or record as a deviation, never zero survival). An older bundle's
    are explicitly unavailable, with the reason (never inferred from its totals)."""
    schema = bundle.get("schema")
    if schema == BUNDLE_V3:
        probs = age_summary_problems(bundle)
        if probs:
            raise StoreError(f"{cid}: a bundle/3 without its complete age summary: " + "; ".join(probs[:3]))
        return {"cell": cid, "bundle_schema": schema, "available": True,
                "horizons": {str(h["steps"]): h["age_strata"] for h in bundle["score"]["horizons"]}}
    return {"cell": cid, "bundle_schema": schema, "available": False,
            "reason": f"bundle schema {schema!r} predates the age-stratified summary (D8 rule 48)"}


def age_diagnostics_doc(obs, entries):
    """The separately versioned age-diagnostics output of a collection, beside its observations
    `obs` (whose bytes it leaves unchanged): bound to them by hash and to their design and plan,
    with every collected cell's entry (age_diagnostics_entry), how many are available and
    unavailable, and the plan cells the observations declare missing."""
    return {"schema": AGE_DIAGNOSTICS_SCHEMA, "observations_schema": obs.get("schema"),
            "observations_sha256": rqlib.canonical_sha(obs), "design_sha256": obs.get("design_sha256"),
            "plan_sha256": obs.get("plan_sha256"), "missing": obs.get("missing"),
            "available": sum(1 for e in entries if e["available"]),
            "unavailable": sum(1 for e in entries if not e["available"]),
            "cells": sorted(entries, key=lambda e: e["cell"])}


def summary_of(bundle):
    """The summaries done.json and the index carry, as the bundle (the authority) determines them:
    the cell's kind and row hash, its common group and the common checkpoint it built, its pair
    group and the arena's prey settings (run.py writes them from the same bundle)."""
    c = bundle.get("cell") or {}
    g = c.get("groups") or {}
    return {"kind": c.get("kind"), "row_sha256": rqlib.canonical_sha(c) if c else None,
            "common_group": g.get("common") if c.get("prey_policy") == "common" else None,
            "common_sha256": (bundle.get("files") or {}).get("common.json"),
            "pair_group": f"{g.get('reseed')}|{c.get('prey_policy')}|{c.get('assay')}",
            "prey_config_sha256": bundle.get("arena_prey_config_sha256")}


def completion_problems(done, bundle):
    """How a completion's done.json disagrees with its (hash-valid) bundle. Every summary the store
    indexes is the bundle's (summary_of: kind, row hash, common group and checkpoint, pair group,
    prey settings), whatever the schema. A plan/2 bundle (/2 or /3) must carry its sharing record
    (one completed before 03a608b: refused, never mixed in) whose keys, seeds and realized common checkpoint are
    the cell's and the bundle's; done.json's role, families, transplant group and realized draw
    must be the bundle's (an assay's realized draw is required). A /3 bundle, of either plan
    version, must carry its complete age summary (age_summary_problems: D8 v2 rule 48)."""
    if not isinstance(bundle.get("cell"), dict):
        return ["the bundle carries no cell"]
    want = summary_of(bundle)
    probs = [f"done.json's {k} ({str(done.get(k))[:24]}) is not the bundle's ({str(v)[:24]})"
             for k, v in want.items() if done.get(k) != v]
    if bundle.get("schema") == BUNDLE_V3 and bundle["cell"].get("schema") not in (
            "finfolk.redqueen.plan/1", "finfolk.redqueen.plan/2"):
        return probs + ["a /3 bundle without a supported plan schema"]
    probs += age_summary_problems(bundle)
    if not sharing_required(bundle.get("schema"), bundle["cell"].get("schema")):
        return probs + (["a plan/1 bundle with a plan/2 transplant group"] if done.get("transplant_group") else [])
    c, sh = bundle.get("cell") or {}, bundle.get("sharing")
    if not isinstance(sh, dict) or sh.get("schema") != SHARING_SCHEMA:
        return probs + ["a plan/2 bundle without its sharing record (completed before 03a608b): rerun it in a new root"]
    if sh.get("keys") != c.get("groups") or sh.get("seeds") != c.get("seeds"):
        probs.append("the sharing record's keys or seeds are not the cell's")
    if (sh.get("realized") or {}).get("common_sha256") != want["common_sha256"]:
        probs.append("the sharing record's realized common checkpoint is not the bundle's")
    if done.get("role") != c.get("role") or done.get("families") != c.get("families"):
        probs.append(f"done.json's role / families ({done.get('role')}, {done.get('families')}) are not the "
                     f"bundle's ({c.get('role')}, {c.get('families')})")
    tg = f"{(c.get('groups') or {}).get('transplant')}|k{c.get('k')}" if c.get("kind") == "assay" else None
    th = (sh.get("realized") or {}).get("transplant_realized_sha256") if tg else None
    if tg and not th:
        probs.append("a plan/2 assay whose sharing record lacks its realized transplant draw")
    if done.get("transplant_group") != tg or done.get("transplant_realized_sha256") != th:
        probs.append(f"done.json's transplant group / realized draw ({done.get('transplant_group')}) are not the "
                     f"bundle's ({tg})")
    return probs


def index_problems(root, cells=None):
    """(Review of d4dc4b7, P2 1) Every indexed cell, not only those of the plan being run or packed:
    a plan/2 entry (/2 or /3 bundle) must carry its sharing summary (role, transplant group);
    /3 entries record the plan schema too, and keep their complete age summary (indexed_age_problems:
    pack()'s bound stamp over a chunk whose bytes still match, or else the packed bundle; Codex
    re-reviews of 5ecffb5 and e82ed4e). An older entry (no
    "bundle_schema") is checked against its chunk's bundle and
    done.json (completion_problems): a root holding a /2 completion without sharing records, or with
    summaries its bundle contradicts, is refused (a /2 study is rerun in a new root) -> problems."""
    if cells is None:
        _, cells = load_index(root)
    probs = indexed_age_problems(root, cells)
    for cid, (rec, e) in sorted(cells.items()):
        if "bundle_schema" in e:
            if e["bundle_schema"] == BUNDLE_V3 and e.get("plan_schema") not in (
                    "finfolk.redqueen.plan/1", "finfolk.redqueen.plan/2"):
                probs.append(f"{cid}: a /3 completion indexed without its plan schema")
            if sharing_required(e["bundle_schema"], e.get("plan_schema")) and (
                    "transplant_group" not in e or not e.get("role")):
                probs.append(f"{cid}: a plan/2 completion indexed without its sharing summary")
            continue
        try:        # (Codex re-review of a5c366c, P2: refused before decoding; damaged bytes, never a crash)
            b = json.loads(read_member(root, cid, "bundle.json", cells))
            d = json.loads(read_member(root, cid, "done.json", cells))
        except UNREADABLE + (StoreError,) as x:
            probs.append(f"{cid}: its packed bundle cannot be checked ({x})")
            continue
        if not (isinstance(b, dict) and isinstance(d, dict)):
            probs.append(f"{cid}: its packed bundle or done.json is not a JSON object")
            continue
        probs += [f"{cid} (packed in {rec['chunk']}): {p}" for p in completion_problems(d, b)]
        if sharing_required(b.get("schema"), (b.get("cell") or {}).get("schema")) and "transplant_group" not in e:
            probs.append(f"{cid} (packed in {rec['chunk']}): a plan/2 completion indexed without its sharing summary")
    return probs


def transplant_groups(cells):
    """{transplant group (predator snapshot x replicate x K, plan/2): the realized donor draw and
    placement} over indexed cells. Raises on a disagreement (design v4 §3.5), and on an entry it
    cannot place: a group without its realized draw (or a draw without a group), or a /2 assay
    entry without either (never silently skipped)."""
    out = {}
    for cid, (_, e) in cells.items():
        g, h = e.get("transplant_group"), e.get("transplant_realized_sha256")
        if bool(g) != bool(h) or (not g and sharing_required(e.get("bundle_schema"), e.get("plan_schema")) and
                                  e.get("kind") == "assay"):
            raise StoreError(f"cell {cid}: an indexed transplant summary without its group or realized draw "
                             f"({g}, {h})")
        if g:
            if out.setdefault(g, h) != h:
                raise StoreError(f"transplant group {g}: two different realized donor draws / placements "
                                 f"({out[g][:12]}, {h[:12]})")
    return out


def next_chunk_name(root, recs):
    used = {r["chunk"] for r in recs}
    k = len(recs) + 1
    while f"chunk_{k:06d}.zip" in used or os.path.exists(os.path.join(root, CHUNKS, f"chunk_{k:06d}.zip")):
        k += 1
    return f"chunk_{k:06d}.zip"


def finished_cells(root):
    """Working directories with a done.json: {id: done dict}."""
    wd = os.path.join(root, WORK)
    out = {}
    for x in sorted(os.listdir(wd)) if os.path.isdir(wd) else []:
        p = os.path.join(wd, x, "done.json")
        if os.path.isfile(p):
            out[x] = rqlib.read_json(p)
    return out


def pack(root, ids=None, log=print):
    """Pack finished cells (all, or `ids`) into one new chunk, verify it, commit it, delete the cells'
    working directories -> (chunk name or None, cells packed). Raises StoreError before the commit
    on any mismatch (nothing deleted)."""
    recs, cells = load_index(root, repair=True)
    fin = finished_cells(root)
    todo = sorted(c for c in (fin if ids is None else ids) if c in fin and c not in cells)
    if not todo:
        return None, 0
    probs = index_problems(root, cells)        # (every indexed cell, not only the new ones)
    if probs:
        raise StoreError("the root's index holds completions that cannot be extended: " + "; ".join(probs[:3]))
    groups = common_groups(cells)
    pairs = pair_groups(cells)
    tgroups = transplant_groups(cells)
    members, entries = [], {}
    for cid in todo:
        d = os.path.join(root, WORK, cid)
        done = fin[cid]
        b = rqlib.read_bytes(os.path.join(d, "bundle.json"))
        bsha = rqlib.sha256_bytes(b)
        if bsha != done.get("bundle_sha256"):
            raise StoreError(f"{cid}: bundle.json does not match its done.json")
        dn = rqlib.read_bytes(os.path.join(d, "done.json"))
        try:
            bjson = json.loads(b)
        except ValueError:
            raise StoreError(f"{cid}: bundle.json is not JSON")
        probs = completion_problems(done, bjson) if isinstance(bjson, dict) else ["bundle.json is not a JSON object"]
        if probs:
            raise StoreError(f"{cid}: " + "; ".join(probs))
        g, h = done.get("common_group"), done.get("common_sha256")
        if g and h and groups.setdefault(g, h) != h:
            raise StoreError(f"{cid}: common group {g} built {h[:12]}, other cells built {groups[g][:12]} "
                             "(nondeterministic common checkpoint)")
        pg, ph = done.get("pair_group"), done.get("prey_config_sha256")
        if pg and ph and pairs.setdefault(pg, ph) != ph:
            raise StoreError(f"{cid}: its arena's prey settings differ from those of the other cells of {pg} "
                             "(a challenge and its predator-free control must share them)")
        tg, th = done.get("transplant_group"), done.get("transplant_realized_sha256")
        if tg and th and tgroups.setdefault(tg, th) != th:
            raise StoreError(f"{cid}: transplant group {tg} realized {th[:12]}, other cells {tgroups[tg][:12]}: the "
                             "shared donor draw / placement differs (design v4 §3.5)")
        members.append((f"{cid}/bundle.json", b))
        members.append((f"{cid}/done.json", dn))
        entries[cid] = {"bundle_sha256": done["bundle_sha256"], "done_sha256": rqlib.sha256_bytes(dn),
                        "row_sha256": done.get("row_sha256"), "common_group": g, "common_sha256": h,
                        "pair_group": pg, "prey_config_sha256": ph, "kind": done.get("kind"),
                        "role": done.get("role"), "transplant_group": tg, "transplant_realized_sha256": th,
                        "bundle_schema": bjson.get("schema")}
        if bjson.get("schema") == BUNDLE_V3:
            entries[cid]["plan_schema"] = bjson["cell"].get("schema")
            aprobs = age_summary_problems(bjson)    # (completion_problems refused it above; the stamp is THIS check's)
            if aprobs:
                raise StoreError(f"{cid}: " + "; ".join(aprobs))
            # bound to the very bytes checked, which verify_chunk below matches in the chunk before the commit
            entries[cid][AGE_SUMMARY_KEY] = age_stamp(bsha)
    cdir = os.path.join(root, CHUNKS)
    if not os.path.isdir(cdir):
        os.makedirs(cdir, exist_ok=True)
        rqlib.fsync_dir(root)
    name = next_chunk_name(root, recs)
    final = os.path.join(cdir, name)
    tmp = final + ".tmp"
    with zipfile.ZipFile(tmp, "w", compression=PACK_METHOD, compresslevel=6) as z:
        for arc, data in members:
            zi = zipfile.ZipInfo(arc, date_time=ZIP_TIME)
            zi.compress_type = PACK_METHOD
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)
    rqlib.fsync_file(tmp)
    os.replace(tmp, final)
    rqlib.fsync_dir(cdir)
    probs = verify_chunk(final, entries)
    if probs:
        os.remove(final)
        rqlib.fsync_dir(cdir)
        raise StoreError(f"chunk {name} failed verification: {probs[:3]}")
    rec = {"schema": CHUNK_SCHEMA, "chunk": name, "sha256": rqlib.sha256_file(final),
           "bytes": os.path.getsize(final), "cells": entries}
    ip = os.path.join(root, INDEX)
    with open(ip, "ab") as f:          # the commit point
        f.write(rqlib.canonical(rec))
        f.flush()
        os.fsync(f.fileno())
    rqlib.fsync_dir(cdir)
    for cid in todo:
        shutil.rmtree(os.path.join(root, WORK, cid))
    rqlib.fsync_dir(os.path.join(root, WORK))
    log(f"packed {len(todo)} cells into {name} ({rec['bytes'] / 1e6:.2f} MB)")
    return name, len(todo)


def verify_chunk(path, entries):
    """Problems of a chunk against its cell entries (every member compressed as pack() writes it, CRCs,
    every member's SHA-256, no extras). (Codex re-review of a5c366c, P2) A member of any other
    compression method refuses the chunk before anything in it is decoded, and damaged bytes are
    problems (UNREADABLE), never a crash."""
    probs = []
    try:
        with zipfile.ZipFile(path) as z:
            odd = [w for w in map(method_problem, z.infolist()) if w]
            if odd:
                return odd
            bad = z.testzip()
            if bad:
                probs.append(f"CRC error in {bad}")
            names = set(z.namelist())
            want = {f"{c}/{m}" for c in entries for m in ("bundle.json", "done.json")}
            if names != want:
                probs.append(f"members differ from the record ({len(names ^ want)} names)")
            for cid, e in entries.items():
                for m, key in (("bundle.json", "bundle_sha256"), ("done.json", "done_sha256")):
                    arc = f"{cid}/{m}"
                    if arc in names and rqlib.sha256_bytes(packed_member(z, arc)) != e[key]:
                        probs.append(f"{arc} does not match its record")
    except UNREADABLE as e:
        probs.append(f"unreadable ({e})")
    return probs


def read_member(root, cid, member="bundle.json", cells=None):
    """A packed cell's member bytes, checked against the index -> bytes (or None if not packed). A
    member not compressed as pack() writes it raises zipfile.BadZipFile before it is decoded
    (packed_member), on every path (Codex re-review of 6407f80, P2: there is no ungated read); other
    damaged bytes raise one of UNREADABLE, a member that does not match the index StoreError
    (consumers: read_packed)."""
    if cells is None:
        _, cells = load_index(root)
    if cid not in cells:
        return None
    rec, e = cells[cid]
    with zipfile.ZipFile(os.path.join(root, CHUNKS, rec["chunk"])) as z:
        data = packed_member(z, f"{cid}/{member}")
    key = "bundle_sha256" if member == "bundle.json" else "done_sha256"
    if rqlib.sha256_bytes(data) != e[key]:
        raise StoreError(f"{cid}/{member} in {rec['chunk']} does not match the index")
    return data


def read_packed(root, cid, member="bundle.json", cells=None):
    """read_member for the store's consumers (noise-bank and reference-selection collection, replay:
    Codex re-review of 6407f80, P2) -> bytes (or None if not packed). A packed member that cannot be
    read as pack() wrote it (a compression method pack() never writes, refused before decoding;
    damaged bytes, UNREADABLE; bytes that do not match the index) raises StoreError naming the root,
    the chunk and the cell, never a codec's or zipfile's own exception."""
    if cells is None:
        _, cells = load_index(root)
    if cid not in cells:
        return None
    try:
        return read_member(root, cid, member, cells)
    except UNREADABLE + (StoreError,) as x:
        raise StoreError(f"{cid} (packed in {cells[cid][0].get('chunk')} of {root}): its packed {member} "
                         f"cannot be read ({x})") from x


def collect_refusal(err, in_plan):
    """A collection's refusal (noisebank / refsel collect) of an indexed bundle read_packed cannot read
    (`err`; in_plan: its cell id is one of the final plan's) -> the operator's message. The WHOLE
    collection is refused, never the cell skipped, even one of another design (Codex re-review of
    6407f80, P2): a collector reads every indexed bundle because a cell's design is recorded only
    inside it, so an unreadable one may be a cell of this design (in the plan, or one the plan does not
    hold, which the collector must refuse), and skipping it would leave a silent gap (D8 v2 rule 48: an
    omission needs a repair or an explicit deviation record)."""
    whose = ("a cell of this plan" if in_plan else "not one of this plan's cell ids, but its design is recorded "
             "only in the bundle that cannot be read, so it is not skipped")
    return (f"collection refused: {err} ({whose}); nothing was written: the chunk needs a repair or an "
            "explicit deviation record")


def verify_all(root, deep=True):
    """Every committed chunk exists with its recorded size and (deep) SHA-256, and every indexed /3
    completion keeps its complete age summary (indexed_age_problems over the chunks matched here)
    -> problems. Not deep, a chunk holding a /3 entry with a bound age stamp is still matched by
    SHA-256 (Codex re-review of e82ed4e: the stamp vouches for its bytes, and a size cannot); chunks
    of /1 and /2 entries only, by size as before."""
    recs, cells = load_index(root)
    hashed = None if deep else age_stamped_chunks(cells)
    probs, sound = [], set()
    for r in recs:
        p = os.path.join(root, CHUNKS, r["chunk"])
        if not os.path.isfile(p) or os.path.getsize(p) != r["bytes"]:
            probs.append(f"{r['chunk']} missing or of the wrong size")
        elif hashed is None or r["chunk"] in hashed:
            if rqlib.sha256_file(p) != r["sha256"]:
                probs.append(f"{r['chunk']} does not match its SHA-256")
            else:
                sound.add(r["chunk"])
    return probs + indexed_age_problems(root, cells, sound=sound)


def recover(root, log=print, deep=True):
    """Finish or undo whatever a crash interrupted -> (actions taken, problems). (Codex re-review of
    e82ed4e, P2) EVERY check runs first, read-only, on one parse of the index (a torn last line is
    dropped in memory only), and a problem is returned with NOTHING repaired, removed or deleted
    (not the torn tail, not an uncommitted chunk or temporary, not a leftover working directory):
    (1) the committed chunks: each exists with its recorded size; its SHA-256 is matched when deep,
    when it holds a cell whose working directory is still there (and then, in full, its CRCs and
    every member against the index: review round 2, P1-2), and when it holds a /3 entry with a bound
    age stamp, deep or not (the stamp vouches for those bytes; a size cannot);
    (2) every indexed /3 completion's age summary (indexed_age_problems over the chunks matched in
    (1); D8 v2 rule 48, Codex re-review of 5ecffb5): a failure is a recording omission to repair or
    record as a deviation (the runner exits 2);
    (3) EVERY leftover bundle against the index (review round 3: all of them before any deletion).
    Only if all of that passed, in review round 2's order (P1-2): (4) the torn index tail repaired
    and the index and its directory fsync'd (the index is fsync'd as it stands before (1) too,
    whatever follows: a record written but not yet fsync'd when the runner died is made durable
    before anything relies on it; an fsync changes no byte); (5) uncommitted chunk files and
    temporaries deleted (their cells still have their working directories); (6) the leftover
    working directories deleted; (7) the store's temporary files removed."""
    acts, probs = [], []
    cdir = os.path.join(root, CHUNKS)
    ip = os.path.join(root, INDEX)
    wd = os.path.join(root, WORK)
    if os.path.isfile(ip):
        rqlib.fsync_file(ip)
        rqlib.fsync_dir(cdir)
    recs, cells, torn = _load_index(root)         # read-only: ONE parse, the torn tail dropped in memory
    leftovers = [x for x in (sorted(os.listdir(wd)) if os.path.isdir(wd) else []) if x in cells]
    need_full = {cells[x][0]["chunk"] for x in leftovers}
    hashed = need_full | age_stamped_chunks(cells)
    sound = set()
    for r in recs:                                                       # (1)
        p = os.path.join(cdir, r["chunk"])
        if not os.path.isfile(p) or os.path.getsize(p) != r["bytes"]:
            probs.append(f"{r['chunk']} missing or of the wrong size")
        elif deep or r["chunk"] in hashed:
            if rqlib.sha256_file(p) != r["sha256"]:
                probs.append(f"{r['chunk']} does not match its SHA-256")
                continue
            bad = verify_chunk(p, r["cells"]) if r["chunk"] in need_full else []
            probs += [f"{r['chunk']}: {x}" for x in bad]
            if not bad:
                sound.add(r["chunk"])
    aprobs = indexed_age_problems(root, cells, sound=sound)              # (2)
    if aprobs or probs:
        n = len(os.listdir(wd)) if os.path.isdir(wd) else 0
        if aprobs:
            log(f"recover: {len({p.split(' ', 1)[0] for p in aprobs})} indexed /3 completions without a verifiable "
                f"complete age summary (D8 v2 rule 48): nothing repaired or deleted ({n} working directories kept)")
        if probs:
            log(f"recover: the committed chunks failed verification: nothing repaired or deleted ({n} working "
                f"directories kept, {len(leftovers)} of them packed cells')")
        return acts, aprobs + probs
    for x in leftovers:     # (3) (review round 3) every bundle checked first: one mismatch keeps them all
        bp = os.path.join(wd, x, "bundle.json")
        if os.path.isfile(bp) and rqlib.sha256_file(bp) != cells[x][1]["bundle_sha256"]:
            probs.append(f"work/{x} is packed, but its bundle.json differs from the packed one")
    if probs:
        log(f"recover: {len(leftovers)} packed cells' working directories KEPT (a bundle differs from its chunk): "
            "nothing repaired or deleted")
        return acts, probs
    if torn:                                                             # (4)
        rqlib.write_durable(ip, b"".join(rqlib.canonical(r) for r in recs))
    if os.path.isfile(ip):
        rqlib.fsync_file(ip)
        rqlib.fsync_dir(cdir)
    committed = {r["chunk"] for r in recs}
    if os.path.isdir(cdir):                                              # (5)
        for f in sorted(os.listdir(cdir)):
            p = os.path.join(cdir, f)
            if f.endswith(".tmp") or (f.startswith("chunk_") and f.endswith(".zip") and f not in committed):
                os.remove(p)
                acts.append(f"removed uncommitted {f}")
        rqlib.fsync_dir(cdir)
    for x in leftovers:                                                  # (6)
        shutil.rmtree(os.path.join(wd, x))
        acts.append(f"deleted the packed cell's working directory {x}")
    if leftovers and os.path.isdir(wd):
        rqlib.fsync_dir(wd)
    od = os.path.join(root, OBJECTS)
    for dp, _, fs in os.walk(od) if os.path.isdir(od) else []:
        for f in fs:
            if ".tmp." in f:
                os.remove(os.path.join(dp, f))
                acts.append(f"removed a temporary store file {f}")
    for a in acts:
        log(f"recover: {a}")
    return acts, probs
