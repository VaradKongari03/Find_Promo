"""Stage 4 - Glue: propose (LLM) -> verify (code) -> dedupe -> stranger test (LLM) -> rank (code)."""
from . import prompts
from .verify import verify, clip_lines


def propose_all(episodes, show, llm, log=print):
    brief = prompts.show_brief(episodes)
    kept, rejected = [], []
    for ep in episodes:
        log(f"  proposing Ep {ep['episode']:>2} ...")
        res = llm.call(prompts.PROPOSE_SYSTEM, prompts.propose_user(brief, ep), tag=f"propose-ep{ep['episode']:02d}")
        if res.get("_pending"):
            continue
        if res.get("_unparseable") or not isinstance(res.get("promos"), list):
            rejected.append({"episode": ep["episode"], "source": "llm", "reject_reason": "model returned unparseable output"})
            continue
        if not res["promos"]:
            log(f"     Ep {ep['episode']}: model found no promo-worthy moment")
        for n, p in enumerate(res["promos"], 1):
            cand = {**p, "source": "llm", "proposed_in_episode": ep["episode"], "cand_id": f"E{ep['episode']:02d}-P{n}"}
            v, r = verify(cand, show)
            (kept if v else rejected).append(v or r)
    kept, dups = dedupe(kept)
    return kept, rejected + dups


def _score_sum(c):
    s = c.get("scores", {})
    return s.get("hook", 0) + s.get("cliffhanger", 0) + _standalone(c)


def _standalone(c):
    st = c.get("stranger")
    return st["standalone_score"] if st else c.get("scores", {}).get("standalone", 0)


def _overlap(a, b):
    if a["episode"] != b["episode"]:
        return 0.0
    inter = sum(max(0, min(x["end"], y["end"]) - max(x["start"], y["start"])) for x in a["segments"] for y in b["segments"])
    return inter / min(a["duration"], b["duration"])


def dedupe(cands):
    """Drop near-duplicates (>50% overlap with a better clip from the same episode)."""
    out, dups = [], []
    for c in sorted(cands, key=lambda c: -_score_sum(c)):
        twin = next((k for k in out if _overlap(c, k) > 0.5), None)
        if twin is None:
            out.append(c)
        else:
            dups.append({**c, "reject_reason": f"near-duplicate of {twin['cand_id']} (>50% overlap, lower score)"})
    return out, dups


def stranger_test(cands, show, llm, top_n=15, log=print, order=None):
    """Blind check: a fresh model call sees ONLY the clip and says what it understood.
    `order` = clips in ranked order; defaults to score order."""
    queue = order if order is not None else sorted(cands, key=lambda c: -_score_sum(c))
    for c in [c for c in queue if not c.get("stranger")][:top_n]:
        log(f"  stranger test {c['cand_id']} ...")
        res = llm.call(prompts.STRANGER_SYSTEM, prompts.stranger_user(clip_lines(c, show)), tag=f"stranger-{c['cand_id']}")
        if res.get("_pending"):
            continue
        try:
            res["standalone_score"] = int(round(float(res.get("standalone_score"))))
            c["stranger"] = res
        except (TypeError, ValueError):
            c["stranger_error"] = "blind test returned no usable score"


def rank_with_blind_test(cands, show, llm, top_n=15, free_episodes=10, log=print):
    """Rank, blind-test in RANKED order, re-rank. Repeat so every 'post first' clip is blind-tested
    (v1 tested the top-15 by score, but the funnel factor then promoted untested clips to #1-#2)."""
    ranked = rank(cands, free_episodes)
    budget = top_n
    for _ in range(4):
        untested_first = [c for c in ranked if c["post_first"] and not c.get("stranger")]
        if not untested_first and budget <= 0:
            break
        order = untested_first + [c for c in ranked if not c["post_first"]]
        n = max(len(untested_first), budget)
        before = llm.stats.get("pending", 0)
        stranger_test(cands, show, llm, top_n=n, log=log, order=order)
        if llm.stats.get("pending", 0) > before:
            return None  # waiting on answers (file provider)
        budget -= n
        ranked = rank(cands, free_episodes)
        if not any(c["post_first"] and not c.get("stranger") for c in ranked):
            break
    return ranked


def tier(c):
    s = c.get("scores", {})
    hook, cliff, alone = s.get("hook", 0), s.get("cliffhanger", 0), _standalone(c)
    st = c.get("stranger") or {}
    # Prompt asks for "none - it feels resolved" when nothing is left open. Match the start, not the
    # substring: "unresolved" contains "resolved".
    feels_resolved = str(st.get("open_question", "")).strip().lower().startswith("none")
    if hook >= 4 and cliff >= 4 and alone >= 4 and not feels_resolved:
        return "A"
    if min(hook, cliff, alone) >= 3 and not feels_resolved:
        return "B"
    return "C"


def rank(cands, free_episodes=10, post_first_n=10):
    for c in cands:
        c["tier"] = tier(c)
        c["in_free_window"] = c["payoff_episode"] <= free_episodes
    cands.sort(key=lambda c: (c["tier"], not c["in_free_window"], -_score_sum(c), c["payoff_episode"]))

    # "Post first" list: best clip per episode, so the first posts aren't 3 cuts of one scene.
    seen, n = set(), 0
    for c in cands:
        c["post_first"] = False
        if c["tier"] in ("A", "B") and c["episode"] not in seen and n < post_first_n:
            c["post_first"], n = True, n + 1
            seen.add(c["episode"])
    for i, c in enumerate(cands, 1):
        c["rank"] = i
        c["rank_reason"] = _reason(c, free_episodes)
    return cands


def _reason(c, free_episodes):
    s = c.get("scores", {})
    st = c.get("stranger")
    parts = [f"Tier {c['tier']}: hook {s.get('hook','?')}/5, cliffhanger {s.get('cliffhanger','?')}/5"]
    if st:
        parts.append(f"blind stranger understood it {st['standalone_score']}/5")
    else:
        parts.append(f"standalone {s.get('standalone','?')}/5 (self-rated, not blind-tested)")
    where = "inside" if c["in_free_window"] else "outside"
    parts.append(f"payoff in Ep {c['payoff_episode']} ({where} first {free_episodes} episodes)")
    return "; ".join(parts)
