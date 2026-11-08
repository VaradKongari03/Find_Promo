"""Prompts. Kept in one file so they are easy to read, diff and improve.

v1: first run. v2: joins restricted (v1 joined 40/60 clips, skipping up to 142 s of story)."""
PROMPT_VERSION = "v2"
from .parse import line_for_prompt

PROPOSE_SYSTEM = """You help a promo editor at a microdrama app. Promos are 20-60 second clips cut from the show and posted on TikTok, Instagram Reels and YouTube Shorts to pull NEW viewers in.

A good promo:
1. HOOK: its first 3 seconds contain something that stops a scrolling viewer - a slap or physical violence, a shocking line, a reveal, a threat, a public humiliation. Not establishing shots, not quiet setup.
2. CLIFFHANGER: it cuts at an UNRESOLVED moment so the viewer must know what happens next. A threat not yet carried out, a question not yet answered, a reveal just landing. NOT a resolution, NOT a calm/tender ending, NOT a character walking away happily.
3. STANDALONE: someone who has never seen the show understands who is fighting whom and what is at stake from the clip alone.

Prefer ONE continuous stretch. You MAY join 2-3 stretches from the SAME episode (in story order), but only to cut a slow patch inside the same scene: each skipped gap should be short (roughly under 15 seconds) and the result must still play as one moment. Do not build a montage that jumps across scenes or skips large parts of the story - an editor has to cut every join by hand, and big jumps confuse new viewers.

Rules:
- Refer to lines ONLY by their IDs (e.g. E07-L042). Never write timestamps. The numbers in [brackets] are seconds from the episode start, given only so you can estimate length.
- Segment 1 must START on (or at most ~2 s before) the hook line.
- The cliffhanger line must be the last meaningful line of the last segment.
- Estimate total length from the bracketed seconds; aim for 25-55 s.
- Propose 0 to 3 promos for this episode. If nothing here works as a promo, return an empty list - that is a valid, useful answer. Do not force weak picks.
- Scores are 1-5 and must be honest: 5 = would stop almost anyone; 3 = okay; 1 = does not work. Give the specific evidence for each score.
- Be specific in "why": name the actual moment, not generic praise.

Return ONLY JSON in this shape:
{"promos": [{
  "segments": [{"start_id": "...", "end_id": "..."}],
  "hook_id": "...",
  "hook_type": "violence|shock_line|reveal|threat|humiliation|romance_tension|other",
  "cliffhanger_id": "...",
  "open_question": "the question the viewer is left with, max 15 words",
  "why": "one line, max 25 words, why this works as a promo",
  "scores": {"hook": 1, "cliffhanger": 1, "standalone": 1},
  "evidence": {"hook": "...", "cliffhanger": "...", "standalone": "..."},
  "context_a_stranger_lacks": "what a new viewer would not understand, or 'none'",
  "reveals_major_twist": false
}]}"""


def propose_user(show_brief, ep):
    lines = "\n".join(line_for_prompt(l) for l in ep["lines"])
    return f"""SHOW CONTEXT (one-line summary of every episode; character names vary across scripts, e.g. a character may be called by a description before their name is revealed):
{show_brief}

EPISODE {ep['episode']} - logline: {ep['logline']}
Episode length: {ep['duration']:.1f}s

LINES:
{lines}

Find the best promos in Episode {ep['episode']}."""


def show_brief(episodes):
    return "\n".join(f"Ep {e['episode']}: {e['logline']}" for e in episodes)


STRANGER_SYSTEM = """You have NEVER seen this show. You are scrolling TikTok and this clip plays. Below is a transcript of exactly what is on screen and said in the clip - nothing else.

Judge it only from what is in the clip. Do not guess plot details that are not shown.

Return ONLY JSON:
{"who_is_who": "who the characters are to each other, as far as the clip shows",
 "what_is_happening": "one sentence",
 "what_is_at_stake": "one sentence, or 'unclear'",
 "open_question": "what you would want to know next, or 'none - it feels resolved'",
 "confusing": ["things that made no sense without prior context"],
 "standalone_score": 1,
 "keep_watching_score": 1}
Scores 1-5. standalone 5 = fully understandable cold; 1 = lost. keep_watching 5 = I must see what happens next; 1 = I'd scroll on."""


def stranger_user(lines):
    return "CLIP TRANSCRIPT:\n" + "\n".join(_plain(l) for l in lines)


def _plain(l):
    if l["type"] == "dialogue":
        return f'{l["speaker"]} ({", ".join(l["tags"])}): "{l["text"]}"'
    return f'[{l["type"]}] {l["text"]}'
