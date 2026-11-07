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
                                        group and the common checkpoint's SHA-256

Pack protocol (pack()): (1) every candidate cell's bundle.json re-hashed against its done.json;
(2) the chunk written as a temporary file, fsync'd, renamed, the directory fsync'd; (3) the chunk
re-read: zip CRCs, and every member's SHA-256 against its record; (4) the index line appended
and fsync'd (the commit point); (5) only then the cells' working directories deleted and
work/ fsync'd. recover() (at every runner start) undoes a crash at any point: a truncated last
index line is dropped and the index fsync'd, a chunk file without an index line is deleted (its
cells still have their working directories), the committed chunks are verified (in full where a
packed cell's working directory is still there), and only then are those leftover directories
deleted; a chunk that fails verification keeps them and stops the runner.
Common-group consistency: every cell of one common group (prey world, time, replicate) must have
built the same common checkpoint (SHA-256); a disagreement is nondeterminism, and pack() refuses.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import zipfile

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
    return recs, cells


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
    prey settings), whatever the schema. A /2 bundle must carry its sharing record (one completed
    before 03a608b: refused, never mixed in) whose keys, seeds and realized common checkpoint are
    the cell's and the bundle's; done.json's role, families, transplant group and realized draw
    must be the bundle's (an assay's realized draw is required)."""
    if not isinstance(bundle.get("cell"), dict):
        return ["the bundle carries no cell"]
    want = summary_of(bundle)
    probs = [f"done.json's {k} ({str(done.get(k))[:24]}) is not the bundle's ({str(v)[:24]})"
             for k, v in want.items() if done.get(k) != v]
    if bundle.get("schema") != BUNDLE_V2:
        return probs + (["a /1 bundle with a /2 transplant group"] if done.get("transplant_group") else [])
    c, sh = bundle.get("cell") or {}, bundle.get("sharing")
    if not isinstance(sh, dict) or sh.get("schema") != SHARING_SCHEMA:
        return probs + ["a /2 bundle without its sharing record (completed before 03a608b): rerun it in a new root"]
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
        probs.append("a /2 assay whose sharing record lacks its realized transplant draw")
    if done.get("transplant_group") != tg or done.get("transplant_realized_sha256") != th:
        probs.append(f"done.json's transplant group / realized draw ({done.get('transplant_group')}) are not the "
                     f"bundle's ({tg})")
    return probs


def index_problems(root, cells=None):
    """(Review of d4dc4b7, P2 1) Every indexed cell, not only those of the plan being run or packed:
    an entry packed with its bundle's schema recorded must, if /2, carry its sharing summary (role,
    transplant group); an older entry (no "bundle_schema") is checked against its chunk's bundle and
    done.json (completion_problems): a root holding a /2 completion without sharing records, or with
    summaries its bundle contradicts, is refused (a /2 study is rerun in a new root) -> problems."""
    if cells is None:
        _, cells = load_index(root)
    probs = []
    for cid, (rec, e) in sorted(cells.items()):
        if "bundle_schema" in e:
            if e["bundle_schema"] == BUNDLE_V2 and ("transplant_group" not in e or not e.get("role")):
                probs.append(f"{cid}: a /2 completion indexed without its sharing summary")
            continue
        try:
            b = json.loads(read_member(root, cid, "bundle.json", cells))
            d = json.loads(read_member(root, cid, "done.json", cells))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, StoreError) as x:
            probs.append(f"{cid}: its packed bundle cannot be checked ({x})")
            continue
        if not (isinstance(b, dict) and isinstance(d, dict)):
            probs.append(f"{cid}: its packed bundle or done.json is not a JSON object")
            continue
        probs += [f"{cid} (packed in {rec['chunk']}): {p}" for p in completion_problems(d, b)]
        if b.get("schema") == BUNDLE_V2 and "transplant_group" not in e:
            probs.append(f"{cid} (packed in {rec['chunk']}): a /2 completion indexed without its sharing summary")
    return probs


def transplant_groups(cells):
    """{transplant group (predator snapshot x replicate x K, plan/2): the realized donor draw and
    placement} over indexed cells. Raises on a disagreement (design v4 §3.5), and on an entry it
    cannot place: a group without its realized draw (or a draw without a group), or a /2 assay
    entry without either (never silently skipped)."""
    out = {}
    for cid, (_, e) in cells.items():
        g, h = e.get("transplant_group"), e.get("transplant_realized_sha256")
        if bool(g) != bool(h) or (not g and e.get("bundle_schema") == BUNDLE_V2 and e.get("kind") == "assay"):
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
        if rqlib.sha256_bytes(b) != done.get("bundle_sha256"):
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
    cdir = os.path.join(root, CHUNKS)
    if not os.path.isdir(cdir):
        os.makedirs(cdir, exist_ok=True)
        rqlib.fsync_dir(root)
    name = next_chunk_name(root, recs)
    final = os.path.join(cdir, name)
    tmp = final + ".tmp"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for arc, data in members:
            zi = zipfile.ZipInfo(arc, date_time=ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
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
    """Problems of a chunk against its cell entries (CRCs, every member's SHA-256, no extras)."""
    probs = []
    try:
        with zipfile.ZipFile(path) as z:
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
                    if arc in names and rqlib.sha256_bytes(z.read(arc)) != e[key]:
                        probs.append(f"{arc} does not match its record")
    except (OSError, zipfile.BadZipFile) as e:
        probs.append(f"unreadable ({e})")
    return probs


def read_member(root, cid, member="bundle.json", cells=None):
    """A packed cell's member bytes, checked against the index -> bytes (or None if not packed)."""
    if cells is None:
        _, cells = load_index(root)
    if cid not in cells:
        return None
    rec, e = cells[cid]
    with zipfile.ZipFile(os.path.join(root, CHUNKS, rec["chunk"])) as z:
        data = z.read(f"{cid}/{member}")
    key = "bundle_sha256" if member == "bundle.json" else "done_sha256"
    if rqlib.sha256_bytes(data) != e[key]:
        raise StoreError(f"{cid}/{member} in {rec['chunk']} does not match the index")
    return data


def verify_all(root, deep=True):
    """Every committed chunk exists with its recorded size (and, deep, SHA-256) -> problems."""
    recs, _ = load_index(root)
    probs = []
    for r in recs:
        p = os.path.join(root, CHUNKS, r["chunk"])
        if not os.path.isfile(p) or os.path.getsize(p) != r["bytes"]:
            probs.append(f"{r['chunk']} missing or of the wrong size")
        elif deep and rqlib.sha256_file(p) != r["sha256"]:
            probs.append(f"{r['chunk']} does not match its SHA-256")
    return probs


def recover(root, log=print, deep=True):
    """Finish or undo whatever a crash interrupted -> (actions taken, problems). Review round 2,
    P1-2: the order is (1) repair a torn index tail and fsync the index and its directory WHATEVER
    (a record written but not yet fsync'd when the runner died is made durable before anything
    relies on it); (2) delete uncommitted chunk files and temporaries (their cells still have
    their working directories); (3) verify the committed chunks: every chunk holding a cell whose
    working directory is still there in full (its SHA-256, CRCs and every member against the
    index), the others by SHA-256 (deep) or by size; (4) check EVERY leftover bundle against the
    index (round 3: all of them before any deletion); (5) only if all of that passed, delete those
    leftover working directories. Any problem keeps every working directory and is returned for
    the caller to stop on."""
    acts, probs = [], []
    cdir = os.path.join(root, CHUNKS)
    recs, cells = load_index(root, repair=True)
    ip = os.path.join(root, INDEX)
    if os.path.isfile(ip):
        rqlib.fsync_file(ip)
        rqlib.fsync_dir(cdir)
    committed = {r["chunk"] for r in recs}
    if os.path.isdir(cdir):
        for f in sorted(os.listdir(cdir)):
            p = os.path.join(cdir, f)
            if f.endswith(".tmp") or (f.startswith("chunk_") and f.endswith(".zip") and f not in committed):
                os.remove(p)
                acts.append(f"removed uncommitted {f}")
        rqlib.fsync_dir(cdir)
    wd = os.path.join(root, WORK)
    leftovers = [x for x in (sorted(os.listdir(wd)) if os.path.isdir(wd) else []) if x in cells]
    need_full = {cells[x][0]["chunk"] for x in leftovers}
    for r in recs:
        p = os.path.join(cdir, r["chunk"])
        if not os.path.isfile(p) or os.path.getsize(p) != r["bytes"]:
            probs.append(f"{r['chunk']} missing or of the wrong size")
        elif (deep or r["chunk"] in need_full) and rqlib.sha256_file(p) != r["sha256"]:
            probs.append(f"{r['chunk']} does not match its SHA-256")
        elif r["chunk"] in need_full:
            probs += [f"{r['chunk']}: {x}" for x in verify_chunk(p, r["cells"])]
    if probs:
        if leftovers:
            log(f"recover: {len(leftovers)} packed cells' working directories KEPT (the chunks failed verification)")
        return acts, probs
    for x in leftovers:     # (review round 3) every bundle checked first: one mismatch keeps them all
        bp = os.path.join(wd, x, "bundle.json")
        if os.path.isfile(bp) and rqlib.sha256_file(bp) != cells[x][1]["bundle_sha256"]:
            probs.append(f"work/{x} is packed, but its bundle.json differs from the packed one")
    if probs:
        log(f"recover: {len(leftovers)} packed cells' working directories KEPT (a bundle differs from its chunk)")
        return acts, probs
    for x in leftovers:
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
