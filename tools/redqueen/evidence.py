#!/usr/bin/env python3
"""evidence.py: the ONE evidence-chain rule for a history's sampled populations (Annex H D6 rule 24), shared by
val_block.py (runner_val.py's validation layout) and worlds.py's ecology export (the supervisor's layout), so the
two agree on what is evidence. Stdlib only.

THE RULES.
  records   only COMPLETE records count: the bytes after the last newline (an unterminated trailing record,
            whatever its width) are discarded before parsing.
  rows      a row is evidence when it has the header's width, an integral frame exactly on the segment's
            log_every sequence (start + log_every, start + 2 log_every, ...) and integral non-negative guild
            counts. A segment's evidence STOPS at its first row that is not; the validated rows before it are
            kept, and the reason is returned (technical censoring at the last verified observation).
  cuts      a chain segment that a later one resumed is read only up to its CUT (the frame the next chain
            segment resumed from): reading stops the moment its validated rows reach the cut (no row beyond it
            is ever validated: a superseded tail, well formed or not, never affects the retained prefix or its
            continuation), and its rows must REACH the cut exactly (rows that end before it, or skip past it
            without a sample at it, stop the chain there: the next segment is not admitted).
  chain     the NEWEST segment's line of descent. Where segments record their parent link (worlds.py: the
            acceptance record a segment resumed), chain_links follows those links back to a fresh segment
            (start at the base frame) and derives the cuts from them. Where no link is recorded (runner_val.py,
            which always resumes the latest good checkpoint of its attempt), chain_cuts infers it: each earlier
            chain segment covers (its start, the next chain segment's start], a segment whose start is at or
            after that is superseded entirely (a rollback) and skipped; the reach rule above catches an
            inferred parent that did not reach its cut. A continuation is never chosen by its length.
  terminal  the FIRST sampled zero of either considered guild is the first absorbing terminal boundary: the
            observation ends at that sample (both guilds zero in it: a joint event; one guild: its event, the
            other's later status unresolved; later overshoot rows never resolve a competing outcome).
  refills   a sample whose cumulative refill counter exceeds the founder baseline is a protocol-integrity
            event: the observation ends at the sample before it (later rows never establish natural
            coexistence); the event is returned for the investigation record. A refill counter that is present
            but unreadable is a technical stop at the sample before it (the check never silently lapses).
"""
from __future__ import annotations

import re

GUILD_COLS = (("prey", "population"), ("predators", "predator_pop"))
REFILL_COL = "predator_reseeds_cum"
_INT = re.compile(r"^[0-9]+$")


class EvidenceError(Exception):
    pass


def complete(raw):
    """The complete records of a log's bytes: everything after the last newline is discarded."""
    return raw[: raw.rfind(b"\n") + 1]


def _num(text):
    if _INT.match(text):
        return int(text)
    try:
        x = float(text)
    except ValueError:
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def segment_rows(raw, start, log_every, upto=None, cols=()):
    """The validated rows of one segment's main-CSV bytes (see rows, records, cuts) from `start`, through its cut
    `upto` (None: to the end) -> (rows, stop): rows [(frame, {column: value})] with the guild columns (integers)
    and the requested `cols` present in the header (numbers; None when unparsable; absent columns absent); stop
    None when the rows reach `upto` exactly (reading stops there) or, with upto None, the bytes' end; else why the
    evidence stops (the earlier rows kept)."""
    lines = complete(raw).split(b"\n")[:-1]
    if not lines:
        return [], "an empty main CSV"
    hdr = lines[0].decode("utf-8", "replace").strip().split(",")
    if any(c not in hdr for _, c in GUILD_COLS):
        raise EvidenceError("no population / predator_pop columns")
    gi = [hdr.index(c) for _, c in GUILD_COLS]
    ci = {c: hdr.index(c) for c in cols if c in hdr}
    rows, prev = [], start
    if upto is not None and upto <= start:
        return rows, f"its cut {upto} is not after its start {start}"
    for n, ln in enumerate(lines[1:], 2):
        p = ln.decode("utf-8", "replace").strip().split(",")
        ok = len(p) == len(hdr) and bool(_INT.match(p[0])) and all(_INT.match(p[i]) for i in gi)
        if not ok or int(p[0]) != prev + log_every:
            return rows, f"line {n}: a damaged or out-of-sequence row after frame {prev}"
        if upto is not None and int(p[0]) > upto:
            return rows, f"line {n}: its rows pass frame {upto} (where the next chain segment resumed) without a sample at it"
        prev = int(p[0])
        v = {c: int(p[i]) for (_, c), i in zip(GUILD_COLS, gi)}
        for c, i in ci.items():
            v.setdefault(c, _num(p[i]))
        rows.append((prev, v))
        if upto is not None and prev == upto:
            return rows, None                              # (the cut reached: nothing beyond it is read)
    if upto is not None:
        return rows, f"its rows end at frame {prev}, before frame {upto} (where the next chain segment resumed)"
    return rows, None


def chain_cuts(segments, base=0):
    """segments [(key, start frame)] in creation order, WITHOUT recorded parent links -> (chain [(key, start,
    upto)], problem): the newest segment's line of descent inferred from the start frames (see chain); upto None
    for the newest. problem: why the chain is incomplete (no segment; it does not reach a fresh segment), else None."""
    chain, upto = [], None
    for key, s in reversed(list(segments)):
        if upto is not None and s >= upto:
            continue                                       # (superseded: a later resume from an earlier frame)
        chain.append((key, s, upto))
        upto = s
        if s == base:
            break
    chain.reverse()
    if not chain:
        return [], "no segment"
    if chain[0][1] != base:
        return chain, f"the chain does not reach a fresh segment ({chain[0][0]} resumed from frame {chain[0][1]})"
    return chain, None


def chain_links(segments, base=0):
    """segments [(key, start frame, parent key or None)] in creation order, each non-fresh one with its RECORDED
    parent (the segment whose record it resumed) -> (chain [(key, start, upto)], problem): the newest segment's line
    of descent through those links back to a fresh segment (no parent, start at the base frame), each ancestor cut
    at its child's start; upto None for the newest. problem: why the chain is incomplete (no segment; a parent that
    is not an earlier segment, or starts at or after its child's resume frame; a parentless segment not at the
    base frame), else None; the chain returned is then the part that could be linked."""
    segs = list(segments)
    if not segs:
        return [], "no segment"
    pos = {k: i for i, (k, _, _) in enumerate(segs)}
    chain, (key, start, parent), upto = [], segs[-1], None
    while True:
        chain.append((key, start, upto))
        if parent is None:
            chain.reverse()
            return chain, (None if start == base else
                           f"{key} records no parent but starts at frame {start}, not the base frame {base}")
        if parent not in pos or pos[parent] >= pos[key]:
            chain.reverse()
            return chain, f"{key}'s recorded parent {parent} is not an earlier segment"
        upto = start
        key, start, parent = segs[pos[parent]]
        if start >= upto:
            chain.reverse()
            return chain, f"{key} (start {start}) cannot be the parent of a segment resuming at frame {upto}"


def terminal(samples, guilds=GUILD_COLS, base=0, refill_col=REFILL_COL, refill_base=0):
    """Apply the terminal and refill rules to a chain's validated samples [(frame, {column: value})] -> {"samples"
    (truncated), "events" {guild: {"frame", "previous_sample"} | None}, "first_terminal" {"frame", "kind"} | None,
    "joint", "refill" {"frame", "value", "baseline"[, "unreadable"]} | None, "frontier"}. guilds: the (guild,
    column) pairs considered (A's fixed predators: the prey only); refill_base None: no founder baseline
    (unchecked)."""
    out, prev, refill, first = [], base, None, None
    events = {g: None for g, _ in guilds}
    for f, v in samples:
        r = v.get(refill_col) if refill_col else None
        if refill_base is not None and refill_col in v and r is None:
            refill = {"frame": f, "value": None, "baseline": refill_base, "unreadable": True}
            break                                          # (a present but unreadable counter: technical)
        if refill_base is not None and isinstance(r, (int, float)) and r > refill_base:
            refill = {"frame": f, "value": r, "baseline": refill_base}
            break                                          # (no later row establishes natural coexistence)
        zeros = [g for g, c in guilds if v.get(c) == 0]
        out.append((f, v))
        if zeros:
            for g in zeros:
                events[g] = {"frame": f, "previous_sample": prev}
            first = {"frame": f, "kind": "joint" if len(zeros) == len(guilds) and len(guilds) > 1 else zeros[0]}
            break                                          # (the first absorbing terminal boundary)
        prev = f
    return {"samples": out, "events": events, "first_terminal": first,
            "joint": bool(first and first["kind"] == "joint"), "refill": refill,
            "frontier": out[-1][0] if out else base}
