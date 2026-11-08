"""Rules-only promo finder (no AI). Used as a comparison point.

Idea: start a clip ON a high-intensity line (so the hook is at 0 s), then end
it 20-60 s later on the most "open" moment available (a question, an
exclamation, or the episode's final beat, which these scripts write as
cliffhangers). Same verify() gates as the AI path.
"""
import re
from .verify import verify, MIN_S, MAX_S

HIGH_TAGS = {
    "screaming", "shouting", "furious", "outraged", "horrified", "gasping", "weeping",
    "desperate", "venomous", "threatening", "cruel", "crying out", "enraged", "panicked",
    "sobbing", "terrified", "shocked", "accusing", "seething", "roaring", "begging",
}
PHYSICAL = re.compile(
    r"\b(slap\w*|strike\w*|struck|shove\w*|grab\w*|seiz\w*|explo\w*|blood\w*|knife|blade|sword|"
    r"chain\w*|collaps\w*|kneel\w*|kiss\w*|throw\w*|threw|smash\w*|burn\w*|fire|flames|poison\w*)\b", re.I)


def intensity(l):
    s = 0
    if l["type"] == "dialogue":
        s += 2 * sum(1 for t in l["tags"] if t.lower() in HIGH_TAGS)
        s += 1 if "!" in l["text"] else 0
    if l["type"] in ("action", "camera") and PHYSICAL.search(l["text"]):
        s += 2
    return s


def ending_score(l, ep):
    if ep["duration"] - l["end"] <= 1.0:
        return 3  # episode's own final beat - written as a cliffhanger
    if l["type"] == "dialogue" and l["text"].rstrip().endswith("?"):
        return 2
    if l["type"] == "dialogue" and "!" in l["text"]:
        return 1
    return 0


def find(episodes, show, per_episode=2):
    kept, rejected = [], []
    for ep in episodes:
        lines = ep["lines"]
        speakable = [l for l in lines if l["type"] in ("dialogue", "action")]
        hooks = sorted((l for l in speakable if intensity(l) >= 2), key=lambda l: (-intensity(l), l["start"]))
        chosen = []
        for h in hooks:
            if len(chosen) >= per_episode:
                break
            if any(c["s"] - 5 <= h["start"] <= c["e"] for c in chosen):
                continue  # overlaps a clip we already took
            window = [l for l in speakable if h["start"] + MIN_S <= l["end"] <= h["start"] + MAX_S]
            if not window:
                continue
            end = max(window, key=lambda l: (ending_score(l, ep), l["end"]))
            cand = {
                "source": "rules",
                "segments": [{"start_id": h["id"], "end_id": end["id"]}],
                "hook_id": h["id"],
                "cliffhanger_id": end["id"],
                "why": f"Opens on high-intensity line (score {intensity(h)}); ends on "
                       + ["a plain line", "an exclamation", "a question", "the episode's final beat"][ending_score(end, ep)],
                "rule_score": intensity(h) + ending_score(end, ep),
            }
            v, r = verify(cand, show)
            if v:
                kept.append(v)
                chosen.append({"s": v["segments"][0]["start"], "e": v["segments"][-1]["end"]})
            else:
                rejected.append(r)
    kept.sort(key=lambda c: -c["rule_score"])
    return kept, rejected
