"""Plumbing test with a FAKE model (no API). Checks that verify() catches bad
model output and that the full pipeline + report run. Says nothing about
prompt quality - that needs the real model.

Run: python tests/fake_llm_test.py <episodes_folder> <out_folder>
"""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from promos import pipeline, report
from promos.llm import LLM
from promos.parse import load_show
from promos.verify import Show

folder, out = sys.argv[1], sys.argv[2]
episodes = load_show(folder)[:6]
show = Show(load_show(folder))


def fake(self, system, user):
    if "NEVER seen this show" in system:
        return json.dumps({"who_is_who": "a bride and her family", "what_is_happening": "she is jilted",
                           "what_is_at_stake": "her honour", "open_question": "what will she do?",
                           "confusing": [], "standalone_score": 4, "keep_watching_score": 4}), {"in": 500, "out": 80}
    ep = int(re.search(r"Find the best promos in Episode (\d+)", user).group(1))
    lines = [l for l in show.eps[ep]["lines"] if l["type"] == "dialogue"]
    a, b = lines[2], next(l for l in lines if l["start"] >= lines[2]["start"] + 35)
    good = {"segments": [{"start_id": a["id"], "end_id": b["id"]}], "hook_id": a["id"], "cliffhanger_id": b["id"],
            "hook_type": "shock_line", "open_question": "q?", "why": "fake good", "scores": {"hook": 5, "cliffhanger": 4, "standalone": 4},
            "evidence": {"hook": "e", "cliffhanger": "e", "standalone": "e"}, "context_a_stranger_lacks": "none", "reveals_major_twist": ep == 3}
    late = dict(good, why="fake hook late", hook_id=lines[5]["id"])                         # should get trimmed or rejected
    invented = dict(good, why="fake invented id", hook_id=f"E{ep:02d}-L999")                # must be rejected
    long_ = dict(good, why="fake too long", segments=[{"start_id": lines[0]["id"], "end_id": lines[-1]["id"]}],
                 hook_id=lines[0]["id"], cliffhanger_id=lines[-1]["id"])                    # must be rejected (>60s)
    text = json.dumps({"promos": [good, late, invented, long_]})
    if ep == 2:
        text = "```json\n" + text + "\n```"                                               # fenced output -> repair path
    if ep == 4:
        text = "Sorry, here you go: not json"                                              # unparseable -> logged rejection
    return text, {"in": 6000, "out": 900}


LLM._with_retries = fake
llm = LLM("gemini", "fake-model", cache_dir=os.path.join(out, "llm_raw"), min_interval=0)
kept, rejected = pipeline.propose_all(episodes, show, llm, log=lambda *_: None)
pipeline.stranger_test(kept, show, llm, top_n=3, log=lambda *_: None)
ranked = pipeline.rank(kept)
report.write_all(out, "FAKE MODEL TEST", ranked, rejected, show, {"model": "fake", "generated": "test", "proposed": 24})

print("kept:", [(c["cand_id"], c["why"], c["duration"], c["hook_at"], c["tier"], c["repairs"][:1]) for c in ranked])
print("rejected:", [(r.get("cand_id"), r.get("why"), r["reject_reason"]) for r in rejected])
print("stats:", llm.stats)
assert all("invented" not in c["why"] and "too long" not in c["why"] for c in ranked), "gate failed"
assert any(r["reject_reason"] == "model returned unparseable output" for r in rejected)
assert llm.stats["json_repairs"] >= 1
print("ALL PLUMBING CHECKS PASSED")
