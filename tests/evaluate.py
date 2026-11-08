"""Evaluation - Prompt 11/12. Independent re-checks of the outputs, separate from verify.py.

Run: python tests/evaluate.py <episodes_folder> <outputs_folder>
Writes <outputs>/evaluation.md and <outputs>/manual_review.csv (blank columns for a human).
"""
import csv, json, os, sys, collections, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from promos.parse import load_show, fmt
from promos.verify import Show, clip_lines

folder, out = sys.argv[1], sys.argv[2]
show = Show(load_show(folder))
ai = json.load(open(os.path.join(out, "promos.json")))["promos"]
ai_rej = json.load(open(os.path.join(out, "rejected.json")))
rules = json.load(open(os.path.join(out, "rules-only.json")))["promos"]
meta = json.load(open(os.path.join(out, "run_meta.json")))
L = []
w = L.append

# ---------- 1. technical correctness, re-derived from the screenplay ----------
def tech(c):
    errs = []
    ep = show.eps[c["episode"]]
    dur = 0
    for s in c["segments"]:
        a, b = show.by_id[s["start_id"]][2], show.by_id[s["end_id"]][2]
        if s["start"] > a["start"] + 0.01 and s["start_id"] == a["id"] and abs(s["start"] - a["start"]) > 3:
            errs.append("start far from start line")
        for edge in (s["start"], s["end"]):
            for l in ep["lines"]:
                if l["type"] == "dialogue" and l["start"] + 0.01 < edge < l["end"] - 0.01:
                    errs.append(f"cut at {fmt(edge)} slices {l['id']}")
        dur += s["end"] - s["start"]
    if not 20 <= dur <= 60: errs.append(f"duration {dur:.1f}")
    hook = show.by_id[c["hook_id"]][2]
    if hook["start"] - c["segments"][0]["start"] > 3.0: errs.append("hook after 3s")
    if any(c["segments"][i]["start"] < c["segments"][i-1]["end"] for i in range(1, len(c["segments"]))): errs.append("segments out of order")
    return errs

w(f"# Evaluation - {meta.get('model')}\n")
w("## 1. Technical correctness (re-checked from the screenplay, independent of verify.py)\n")
for name, cs in (("AI", ai), ("Rules", rules)):
    bad = [(c["cand_id"], tech(c)) for c in cs if tech(c)]
    w(f"- {name}: {len(cs)} clips, {len(cs)-len(bad)} pass all checks (20-60 s, hook <= 3 s, no mid-line cut, order)." + (f" Failures: {bad}" if bad else ""))

# ---------- 2. what the code caught ----------
w("\n## 2. Model mistakes caught or fixed by code\n")
proposed = len(ai) + len(ai_rej)
w(f"- Proposed by model: {proposed}. Kept: {len(ai)}. Thrown out: {len(ai_rej)}.")
reasons = collections.Counter(r["reject_reason"].split(" (")[0].split(" [")[0] for r in ai_rej)
for r, n in reasons.most_common(): w(f"  - {n} x {r}")
rep = collections.Counter()
for c in ai:
    for r in c["repairs"]:
        rep["trimmed setup to open on hook" if "trimmed" in r else "moved cut off mid-dialogue"] += 1
w(f"- Repairs on kept clips: {dict(rep) or 'none'}")
w(f"- Clips with warnings (e.g. footage after the cliffhanger line): {sum(1 for c in ai if c['warnings'])}")
empty = [e for e in range(1, show.last_ep + 1) if not any(c.get("proposed_in_episode") == e for c in ai + ai_rej)]
w(f"- Episodes where the model proposed nothing: {empty or 'none'}")

# ---------- 3. AI vs rules ----------
def ends_at_end(cs): return sum(1 for c in cs if c["ends_at_episode_end"])
def overlap(a, b):
    if a["episode"] != b["episode"]: return 0
    i = sum(max(0, min(x["end"], y["end"]) - max(x["start"], y["start"])) for x in a["segments"] for y in b["segments"])
    return i / min(a["duration"], b["duration"])
w("\n## 3. AI vs rules-only\n")
w("| | AI | Rules |\n|---|---|---|")
w(f"| Clips | {len(ai)} | {len(rules)} |")
w(f"| Episodes covered | {len({c['episode'] for c in ai})} | {len({c['episode'] for c in rules})} |")
w(f"| Clips that end at the episode's end | {ends_at_end(ai)} ({ends_at_end(ai)*100//max(1,len(ai))}%) | {ends_at_end(rules)} ({ends_at_end(rules)*100//max(1,len(rules))}%) |")
w(f"| Multi-segment clips | {sum(1 for c in ai if len(c['segments'])>1)} | 0 |")
w(f"| Median length (s) | {sorted(c['duration'] for c in ai)[len(ai)//2]:.0f} | {sorted(c['duration'] for c in rules)[len(rules)//2]:.0f} |")
top_ai = [c for c in ai if c.get("post_first")]
shared = [c["cand_id"] for c in top_ai if any(overlap(c, r) > 0.5 for r in rules)]
w(f"\n{len(shared)} of the AI's {len(top_ai)} 'post first' clips substantially overlap (>50%) a rules clip: {shared}")

# ---------- 4. calibration: self-score vs blind stranger ----------
w("\n## 4. Does the model grade its own picks too kindly?\n")
pairs = [(c["scores"].get("standalone", 0), c["stranger"]["standalone_score"], c["cand_id"]) for c in ai if c.get("stranger")]
if pairs:
    gap = [a - b for a, b, _ in pairs]
    w(f"- Blind-tested clips: {len(pairs)}. Self-rated 'makes sense alone' avg {sum(a for a,_,_ in pairs)/len(pairs):.2f} vs blind stranger avg {sum(b for _,b,_ in pairs)/len(pairs):.2f}.")
    w(f"- Self-score higher than stranger on {sum(1 for g in gap if g>0)}, equal on {sum(1 for g in gap if g==0)}, lower on {sum(1 for g in gap if g<0)}.")
    worst = sorted(pairs, key=lambda p: p[1]-p[0])[:3]
    w(f"- Biggest gaps (self, stranger): {[(i, a, b) for a, b, i in worst]}")
    resolved = [c["cand_id"] for c in ai if c.get("stranger") and str(c["stranger"].get("open_question","")).lower().startswith("none")]
    w(f"- Blind stranger said the ending felt resolved: {resolved or 'none'}")
sc = collections.Counter((c["scores"].get("hook"), c["scores"].get("cliffhanger")) for c in ai)
w(f"- Distribution of self-scores (hook, cliffhanger): {dict(sc.most_common(6))}")
w(f"- Tiers: {dict(collections.Counter(c['tier'] for c in ai))}")

# ---------- 5. cost & time ----------
st = meta.get("llm_stats", {})
w("\n## 5. Calls\n")
w(f"- Calls: {st}. Wall time: {meta.get('seconds')}s (file handoff, so time is not representative of an API run).")

open(os.path.join(out, "evaluation.md"), "w").write("\n".join(L) + "\n")

# ---------- manual review sheet: AI top 10 + rules top 10, shuffled, source hidden ----------
rows = [("AI", c) for c in top_ai] + [("Rules", c) for c in [r for r in rules if r.get("post_first")]]
random.Random(7).shuffle(rows)
with open(os.path.join(out, "manual_review.csv"), "w", newline="") as f, open(os.path.join(out, "manual_review_key.csv"), "w", newline="") as k:
    a, b = csv.writer(f), csv.writer(k)
    a.writerow(["item", "episode", "timecodes", "transcript", "hook_in_first_3s (Y/N)", "ends_unresolved (Y/N)", "makes_sense_alone (1-5)", "would_post (Y/N)", "notes"])
    b.writerow(["item", "source", "cand_id"])
    for i, (src, c) in enumerate(rows, 1):
        tr = " / ".join((f'{l["speaker"]}: {l["text"]}' if l["type"] == "dialogue" else f'[{l["text"]}]') for l in clip_lines(c, show) if l["type"] != "camera")
        a.writerow([i, c["episode"], " + ".join(f"{s['start_ts']}-{s['end_ts']}" for s in c["segments"]), tr, "", "", "", "", ""])
        b.writerow([i, src, c["cand_id"]])
print("\n".join(L))
