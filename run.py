"""Find the Promos - command line.

  python run.py --episodes "path/to/show" --out outputs/
  python run.py --episodes "path/to/show" --provider openai --model llama-3.3-70b-versatile   # e.g. Groq
  python run.py --episodes "path/to/show" --rules-only                                       # no API key needed

See README.md for setup.
"""
import argparse
import json
import os
import time
from datetime import datetime

from promos import baseline, pipeline, report
from promos.prompts import PROMPT_VERSION
from promos.llm import LLM
from promos.parse import load_show
from promos.verify import Show


def main():
    ap = argparse.ArgumentParser(description="Find promo clips in a microdrama screenplay.")
    ap.add_argument("--episodes", required=True, help="folder with one .txt screenplay per episode")
    ap.add_argument("--out", default="outputs", help="output folder")
    ap.add_argument("--name", help="show name (default: folder name)")
    ap.add_argument("--provider", default=os.environ.get("PROMO_PROVIDER", "gemini"), choices=["gemini", "openai", "anthropic", "file"])
    ap.add_argument("--model", default=os.environ.get("PROMO_MODEL", "gemini-flash-latest"))
    ap.add_argument("--stranger-top", type=int, default=15, help="blind-test this many top clips (0 = off)")
    ap.add_argument("--free-episodes", type=int, default=10, help="assumed number of free episodes before a paywall")
    ap.add_argument("--min-interval", type=float, default=4.0, help="seconds between live API calls (free-tier limits)")
    ap.add_argument("--only-episodes", help="e.g. 1-5 to test on a few episodes first")
    ap.add_argument("--rules-only", action="store_true", help="skip the LLM, run the rules version only")
    a = ap.parse_args()

    t0 = time.time()
    name = a.name or os.path.basename(os.path.normpath(a.episodes))
    episodes = load_show(a.episodes)
    show = Show(episodes)  # full show, so the LLM always gets the whole story context
    run_eps = episodes
    if a.only_episodes:
        lo, hi = (int(x) for x in a.only_episodes.split("-"))
        run_eps = [e for e in episodes if lo <= e["episode"] <= hi]
    print(f"Loaded {len(episodes)} episodes ({sum(len(e['lines']) for e in episodes)} lines). Running on {len(run_eps)}.")

    # Rules version - always produced, costs nothing.
    rk, rr = baseline.find(run_eps, show)
    _finish_rules(rk, a.free_episodes)
    report.write_all(a.out, name + " (rules only)", rk, rr, show,
                     {"model": "rules (no AI)", "generated": _now(), "proposed": len(rk) + len(rr), "episodes_run": len(run_eps)}, filename="rules-only.html")
    print(f"Rules version: {len(rk)} clips -> {a.out}/rules-only.html")
    if a.rules_only:
        return

    llm = LLM(a.provider, a.model, cache_dir=os.path.join(a.out, "llm_raw"), min_interval=a.min_interval)
    print(f"AI version with {a.provider}:{a.model}")
    kept, rejected = pipeline.propose_all(run_eps, show, llm)
    proposed = len(kept) + len(rejected)
    if llm.stats.get("pending"):
        print(f"{llm.stats['pending']} prompts waiting in {a.out}/handoff/requests. Answer them, then run again.")
        return
    if a.stranger_top:
        ranked = pipeline.rank_with_blind_test(kept, show, llm, top_n=a.stranger_top, free_episodes=a.free_episodes)
        if ranked is None:
            print(f"{llm.stats['pending']} blind-test prompts waiting in {a.out}/handoff/requests. Answer them, then run again.")
            return
    else:
        ranked = pipeline.rank(kept, free_episodes=a.free_episodes)
    meta = {"model": f"{a.provider}:{a.model}", "generated": _now(), "proposed": proposed, "episodes_run": len(run_eps), "prompt_version": PROMPT_VERSION,
            "model_version": llm.model_version, "llm_stats": llm.stats, "seconds": round(time.time() - t0, 1),
            "note": f"free-episode assumption = {a.free_episodes}; blind test on top {a.stranger_top}"}
    report.write_all(a.out, name, ranked, rejected, show, meta)
    json.dump(meta, open(os.path.join(a.out, "run_meta.json"), "w"), indent=1)
    print(f"Done in {meta['seconds']}s. {len(ranked)} clips kept, {len(rejected)} thrown out. "
          f"LLM: {llm.stats}. Open {a.out}/report.html")


def _finish_rules(kept, free_episodes):
    seen = set()
    for i, c in enumerate(kept, 1):
        c.update({"cand_id": f"R{i:02d}", "tier": "R", "rank": i, "in_free_window": c["payoff_episode"] <= free_episodes,
                  "rank_reason": f"Rules score {c['rule_score']} (intensity of opening line + type of ending)",
                  "post_first": c["episode"] not in seen and len(seen) < 10})
        if c["post_first"]:
            seen.add(c["episode"])


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    main()
