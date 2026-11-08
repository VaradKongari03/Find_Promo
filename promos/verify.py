"""Stage 2 - Verify candidates with plain code.

Every candidate (from the rules baseline OR the LLM) is described by LINE IDs,
never by timestamps. This module turns IDs into exact times and applies the
hard rules from the brief. Anything that fails is rejected WITH a reason,
so the editor (and we) can see what the tool threw away and why.

Gates (pass/fail):
  - all IDs exist, same episode, segments in order and not overlapping
  - total duration 20-60 s
  - hook line is in segment 1 and starts <= 3.0 s after the clip starts
  - cliffhanger line is in the last segment
Auto-repairs (logged, not hidden):
  - a cut that would slice through a line of dialogue is moved to the edge
    of that line, so nobody is cut off mid-sentence
"""
from .parse import fmt

MIN_S, MAX_S, HOOK_WINDOW_S = 20.0, 60.0, 3.0
TAIL_WARN_S = 6.0
JUMP_WARN_S = 20.0  # a join that skips more story than this gets flagged for the editor  # cliffhanger line ends this long before the cut -> warn


class Show:
    """Fast lookups over a parsed show."""

    def __init__(self, episodes):
        self.eps = {e["episode"]: e for e in episodes}
        self.by_id = {}
        for e in episodes:
            for idx, l in enumerate(e["lines"]):
                self.by_id[l["id"]] = (e["episode"], idx, l)
        self.last_ep = max(self.eps)


def _inside(t, lines):
    return next((l for l in lines if l["type"] == "dialogue" and l["start"] < t < l["end"]), None)


def _snap_start(t, lines):
    """If t falls inside a dialogue line, move it back to that line's start.
    Repeat: dialogue lines can overlap (people talk over each other), so one
    move can land inside another line."""
    t0, moved = t, []
    while (l := _inside(t, lines)):
        t = l["start"]
        moved.append(l["id"])
    if not moved:
        return t, None
    return t, f"start moved {fmt(t0)}->{fmt(t)} to avoid cutting into dialogue {', '.join(moved)}"


def _snap_end(t, lines):
    """If t falls inside a dialogue line, extend to that line's end (repeat for overlaps)."""
    t0, moved = t, []
    while (l := _inside(t, lines)):
        t = l["end"]
        moved.append(l["id"])
    if not moved:
        return t, None
    return t, f"end moved {fmt(t0)}->{fmt(t)} so dialogue {', '.join(moved)} finishes"


def verify(cand, show):
    """Return (verified_candidate, None) or (None, rejection_dict)."""
    notes, warnings = [], []

    def reject(reason):
        return None, {**cand, "reject_reason": reason}

    segs_in = cand.get("segments") or []
    if not segs_in:
        return reject("no segments")
    ids = [x for s in segs_in for x in (s.get("start_id"), s.get("end_id"))] + [cand.get("hook_id"), cand.get("cliffhanger_id")]
    missing = [x for x in ids if x not in show.by_id]
    if missing:
        return reject(f"unknown line IDs {missing} (model invented or mistyped them)")
    ep_set = {show.by_id[x][0] for x in ids}
    if len(ep_set) != 1:
        return reject(f"segments span episodes {sorted(ep_set)} - cross-episode joins are out of scope for v1")
    ep_num = ep_set.pop()
    ep = show.eps[ep_num]
    lines = ep["lines"]

    segs, prev_end = [], -1.0
    for n, s in enumerate(segs_in, 1):
        a, b = show.by_id[s["start_id"]][2], show.by_id[s["end_id"]][2]
        start, end = a["start"], max(b["end"], a["end"])
        start, note = _snap_start(start, lines)
        if note: notes.append(f"seg {n}: {note}")
        end, note = _snap_end(end, lines)
        if note: notes.append(f"seg {n}: {note}")
        if end <= start:
            return reject(f"segment {n} ends before it starts ({s['start_id']}..{s['end_id']})")
        if start < prev_end:
            return reject(f"segment {n} overlaps or comes before segment {n-1}")
        segs.append({"start": start, "end": end, "start_id": s["start_id"], "end_id": s["end_id"]})
        prev_end = end

    hook = show.by_id[cand["hook_id"]][2]
    s1 = segs[0]
    if not (s1["start"] <= hook["start"] < s1["end"]):
        return reject(f"hook line {hook['id']} is not inside segment 1")
    trimmed = False
    if hook["start"] - s1["start"] > HOOK_WINDOW_S:
        # Editor move: trim the slow setup so the clip opens on the hook.
        new_start, _ = _snap_start(hook["start"], lines)
        notes.append(f"seg 1: trimmed {hook['start'] - s1['start']:.1f}s of setup so the clip opens on the hook "
                     f"({fmt(s1['start'])}->{fmt(new_start)})")
        s1["start"] = new_start
        s1["start_id"] = hook["id"]
        trimmed = True
    hook_at = round(hook["start"] - s1["start"], 2)
    if hook_at > HOOK_WINDOW_S:
        return reject(f"hook starts {hook_at:.1f}s into the clip (must be <= {HOOK_WINDOW_S:.0f}s)")

    for n in range(1, len(segs)):
        skip = segs[n]["start"] - segs[n-1]["end"]
        if skip > JUMP_WARN_S:
            warnings.append(f"join skips {skip:.0f}s of story between segments {n} and {n+1} - check it still reads as one moment")

    duration = round(sum(s["end"] - s["start"] for s in segs), 2)
    if duration < MIN_S:
        return reject(f"too short ({duration:.1f}s < {MIN_S:.0f}s)" + (" after trimming setup" if trimmed else ""))
    if duration > MAX_S:
        return reject(f"too long ({duration:.1f}s > {MAX_S:.0f}s)")

    cliff = show.by_id[cand["cliffhanger_id"]][2]
    last = segs[-1]
    if not (last["start"] <= cliff["start"] <= last["end"]):
        return reject(f"cliffhanger line {cliff['id']} is not inside the last segment")
    tail = round(last["end"] - cliff["end"], 2)
    if tail > TAIL_WARN_S:
        warnings.append(f"{tail:.1f}s of footage after the cliffhanger line - may feel like it resolves")

    # What the viewer does NOT get to see: the first lines right after the cut.
    after_idx = show.by_id[last["end_id"]][1] + 1
    after = [l for l in lines[after_idx:] if l["type"] == "dialogue" and l["start"] >= last["end"] - 0.01][:2]
    at_episode_end = ep["duration"] - last["end"] <= 1.0
    payoff_ep = min(ep_num + 1, show.last_ep) if at_episode_end else ep_num
    if at_episode_end and ep_num == show.last_ep:
        warnings.append("cuts at the end of the last available episode - payoff not in this pack")

    out = dict(cand)
    out["scores"] = {k: _as_int(v) for k, v in (cand.get("scores") or {}).items()}
    out["hook_type"] = str(cand.get("hook_type") or "other")
    out.update({
        "episode": ep_num,
        "segments": [{**s, "start_ts": fmt(s["start"]), "end_ts": fmt(s["end"])} for s in segs],
        "duration": duration,
        "hook_at": hook_at,
        "hook_text": _say(hook),
        "cliffhanger_text": _say(cliff),
        "after_cut": [_say(l) for l in after] if not at_episode_end else [f"(episode ends - continues in Episode {payoff_ep})"],
        "ends_at_episode_end": at_episode_end,
        "payoff_episode": payoff_ep,
        "repairs": notes,
        "warnings": warnings,
    })
    return out, None


def _as_int(v):
    """Models sometimes return "4" or 4.0 instead of 4."""
    try:
        return max(0, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _say(l):
    if l["type"] == "dialogue":
        return f'{l["speaker"]}: "{l["text"]}"'
    return f'[{l["type"]}] {l["text"]}'


def clip_lines(c, show):
    """All lines that fall inside a verified candidate's segments (for display / stranger test)."""
    ep = show.eps[c["episode"]]
    out = []
    for s in c["segments"]:
        out += [l for l in ep["lines"] if l["start"] >= s["start"] - 0.01 and l["end"] <= s["end"] + 0.01]
    return out
