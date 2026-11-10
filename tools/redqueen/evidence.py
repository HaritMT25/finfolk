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
  chain     a history's segments in creation order, each with its start frame (a fresh one at the base frame).
            The chain runs back from the NEWEST segment: each earlier chain segment covers (its start, the next
            chain segment's start]; a segment whose start is at or after the next chain segment's start is
            superseded entirely (a rollback to an earlier checkpoint) and skipped; the chain must reach a fresh
            segment. A continuation is never chosen by its length: only the newest line of descent is evidence,
            every other continuation is superseded.
  terminal  the FIRST sampled zero of either considered guild is the first absorbing terminal boundary: the
            observation ends at that sample (both guilds zero in it: a joint event; one guild: its event, the
            other's later status unresolved; later overshoot rows never resolve a competing outcome).
  refills   a sample whose cumulative refill counter exceeds the founder baseline is a protocol-integrity
            event: the observation ends at the sample before it (later rows never establish natural
            coexistence); the event is returned for the investigation record.
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
    """The validated rows of one segment's main-CSV bytes (see rows, records) from `start`, through `upto` (None:
    to the end) -> (rows, stop): rows [(frame, {column: value})] with the guild columns (integers) and the
    requested `cols` (numbers, None when unparsable or absent); stop None when the rows reach `upto` (or, with
    upto None, the bytes' end), else why the evidence stops there (the earlier rows kept)."""
    lines = complete(raw).split(b"\n")[:-1]
    if not lines:
        return [], "an empty main CSV"
    hdr = lines[0].decode("utf-8", "replace").strip().split(",")
    if any(c not in hdr for _, c in GUILD_COLS):
        raise EvidenceError("no population / predator_pop columns")
    gi = [hdr.index(c) for _, c in GUILD_COLS]
    ci = {c: hdr.index(c) for c in cols if c in hdr}
    rows, prev = [], start
    for n, ln in enumerate(lines[1:], 2):
        p = ln.decode("utf-8", "replace").strip().split(",")
        ok = len(p) == len(hdr) and bool(_INT.match(p[0])) and all(_INT.match(p[i]) for i in gi)
        if ok and upto is not None and int(p[0]) > upto:
            return rows, None                              # (past the frame the next chain segment resumed from)
        if not ok or int(p[0]) != prev + log_every:
            return rows, f"line {n}: a damaged or out-of-sequence row after frame {prev}"
        prev = int(p[0])
        v = {c: int(p[i]) for (_, c), i in zip(GUILD_COLS, gi)}
        for c, i in ci.items():
            v.setdefault(c, _num(p[i]))
        rows.append((prev, v))
    if upto is not None and prev < upto:
        return rows, f"its rows end at frame {prev}, before frame {upto} (where the next chain segment resumed)"
    return rows, None


def chain_cuts(segments, base=0):
    """segments [(key, start frame)] in creation order -> (chain [(key, start, upto)], problem): the newest line of
    descent back to a fresh segment (see chain); upto None for the newest. problem: why the chain is incomplete
    (no segment; it does not reach a fresh segment), else None."""
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


def terminal(samples, guilds=GUILD_COLS, base=0, refill_col=REFILL_COL, refill_base=0):
    """Apply the terminal and refill rules to a chain's validated samples [(frame, {column: value})] -> {"samples"
    (truncated), "events" {guild: {"frame", "previous_sample"} | None}, "first_terminal" {"frame", "kind"} | None,
    "joint", "refill" {"frame", "value", "baseline"} | None, "frontier"}. guilds: the (guild, column) pairs
    considered (A's fixed predators: the prey only); refill_base None: no founder baseline (unchecked)."""
    out, prev, refill, first = [], base, None, None
    events = {g: None for g, _ in guilds}
    for f, v in samples:
        r = v.get(refill_col) if refill_col else None
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
