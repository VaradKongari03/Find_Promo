# Working log (feeds the solution doc)

## How the submitted outputs were produced
- My sandbox could not reach the Gemini API, so the tool's `file` provider was used: the tool wrote its exact prompts to `handoff/requests/`, Claude (Opus 5.5) answered each one as the model (one fresh agent per 5 episodes for proposals; one fresh agent PER CLIP for the blind test so it stayed blind), and the tool read the answers back. Same prompts, same parsing, same checks as an API run.
- The Gemini / OpenAI-compatible / Anthropic code paths are written and plumbing-tested with a fake model, but were NOT run against a live API before submission. [Update this line if a Gemini smoke test is done.]
- Two full runs: v1 (`outputs_v1/`) and v2 (`outputs/`, submitted). Both raw-output folders kept.

## Assumptions (brief was silent)
- Screenplay timestamps match the final cut. If the edit drifted, the editor nudges timecodes.
- The series is linear: a cut at an episode's end pays off in the next episode. (True here per continuity notes; check on new shows.)
- First ~10 episodes are free before a paywall (configurable). Only used for the "payoff lands early" factor.
- TikTok / Reels / Shorts treated the same.
- "Best" = stops a scroller and makes them want to start the show. No performance data exists to check this.
- Twists are flagged, not filtered. This show's title already gives away the main twist.
- v1 joins segments within one episode only; no cross-episode stitching.

## Decisions
- LLM cites line IDs, code converts to timestamps -> invented timestamps impossible by design.
- Code gates: 20-60 s, hook <= 3 s from start, no mid-dialogue cuts, IDs exist. Rejections kept with reasons.
- Deterministic repair: hook later than 3 s -> trim setup so the clip opens on the hook (logged).
- Blind "stranger test": separate call sees only the clip. Run in ranked order until every "post first" clip is tested.
- Tiers instead of decimal scores. Funnel factor visible, not hidden.
- Standard library only; one adapter for models; disk cache = raw outputs + reproducibility.

## Results (v2, full show)
- 88 proposed -> 77 kept, 11 thrown out (10 near-duplicates the model offered as alternatives, 1 too short at 19.6 s).
- All 77 pass an independent re-check (duration, hook <= 3 s, no mid-line cut, order).
- Code repairs on kept clips: 3 cuts moved off mid-dialogue, 3 setups trimmed so the clip opens on the hook.
- Model proposed nothing for Eps 6, 8, 14, 17 (quiet, tender episodes) - correct, in my reading.
- 46/50 episodes covered (rules: 41). Median 41 s.
- Blind stranger: avg 3.8/5 "understood it"; never said an ending felt resolved; self-rated standalone higher than the stranger on 5 of 16, never lower.
- Blind A/B (one fresh judge, order randomised, source hidden), AI top-10 vs the matching rules clip from the same episode: AI won 10/10; better hook 9/10, better ending 8/10 (2 ties).
  Caveats: Claude judging Claude-chosen clips; n = 10; AI's best vs rules' nearest.
- 8 of AI's top 10 overlap a rules clip: on this show AI didn't find hidden moments - it chose better cut points and explained them.
- Cost estimate: ~294k tokens in, ~29k out, 69 calls per 50-episode show -> roughly $0.15-1.20/show on Gemini Flash paid rates (Nov 2026), free tier covers ~1 show/day.

## My own blind check (Nov 8)
- I judged 10 clips from `manual_review.csv` (4 AI, 6 rules, source hidden). Would post: AI 3/4, rules 5/6. Hook in 3 s: AI 3/4, rules 4/6. Unresolved ending: AI 3/4, rules 5/6. Makes sense alone: AI 3.8, rules 3.7.
- No clear difference on my judgment, unlike the model judge (AI 10/10). Too small to conclude either way. I rejected the AI's #8 (Ep 41) and felt its #1 (Ep 7) hook doesn't land in 3 s.

## Failures found and fixed (real, in order found)
1. **Montage problem (prompt).** v1 joined segments in 40/60 clips, skipping up to 142 s of story (median 25 s). The prompt said "only when it clearly helps" - the model ignored it. Fix: v2 prompt limits joins to short gaps inside one scene + code warning for jumps > 20 s. v2: 13/77 joined, max jump 16.5 s, 0 over 20 s. Blind "understood it" unchanged (3.8).
2. **Overlapping dialogue (code).** My "never cut mid-sentence" fix moved the cut once; in Ep 46 two lines overlap by 0.2 s so the moved cut landed inside the other line. Found by the independent evaluator. Fix: keep moving until clear.
3. **Blind test on the wrong clips (design).** Blind-tested the top 15 by score, but the funnel factor then promoted untested clips to #1 and #2. Fix: test in ranked order, loop until all "post first" clips are tested. Effect: Ep 5 (was #1) scored 3/5 blind and dropped out of the top 10.

## Known weaknesses (not fixed)
- Self-scores bunch at 3-4 (20 clips at hook 4 / cliffhanger 4), so ranking inside a tier leans on tie-breakers. Next: pairwise comparison of top candidates.
- Context debt: the blind stranger's most common confusion is "who are these people to each other / why is she chained". Inherent in a 20-60 s cut from a 50-episode story; tool flags it but can't fix it (text overlays are out of scope).
- Hook/cliffhanger scores are self-graded by the proposer; only "standalone" is checked independently.
- Screenplay ≠ video: acting, pacing, and whether a visual hook reads in 3 s are unknown.

## Where AI tools got it wrong (Claude, while building)
1. Wrote a regex for "Picks up from Episode N" assuming one phrasing; matched 33/50. Replaced with simpler linear-series rule.
2. Defaulted the model to `gemini-2.5-flash` from training knowledge; free tier had moved on. Switched to `gemini-flash-latest` alias + record exact version.
3. Dedupe silently dropped near-duplicates; caught by the fake-model test. Now listed with reasons.
4. Rules version assumed every episode ending is a cliffhanger (Ep 4 ends on the couple walking into sunlight).
5. The proposing model ignored "join only when it clearly helps" (failure 1 above).
6. Claude's own code assumed dialogue lines never overlap (failure 2 above).
7. Its retry logic covered HTTP errors but not timeouts; the first real Gemini run crashed on a slow reply after a 503. Fixed: timeouts and dropped connections retry too.

## Web version (Nov 8)
- `docs/index.html`: the same pipeline in the browser, with parallel calls (fixes the ~1 hour sequential run). Port verified against the Python outputs: rules 70/70 same order; AI 77/77 identical rows, same 11 rejections, same top 10. End-to-end browser test with a simulated Gemini API (8 injected 503s, all retried) reproduced the same result.
- Bugs Claude introduced and caught in testing: a listener bound to a form id that didn't exist (stopped the page's setup), and CSS `display:flex` overriding the `hidden` attribute (all providers' fields showed at once).
