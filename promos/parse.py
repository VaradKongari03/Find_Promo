"""Stage 1 - Parse screenplay episodes into structured, timestamped lines.

Input : a folder of episode .txt files in Kuku's screenplay format.
Output: a list of Episode dicts. Every block (camera, action, sound, dialogue)
        becomes a "line" with a stable ID like E03-L042 and exact start/end
        seconds taken straight from the screenplay.

No AI here. Timestamps are facts in the file, so code owns them.
"""
import os
import re
import glob

TS = r"(\d+):(\d+(?:\.\d+)?)"
BLOCK_RE = re.compile(r"^\*\*(.+?):\*\*\s*$")
TIME_RE = re.compile(r"^Start:\s*\(" + TS + r"\)\s*\|\s*End:\s*\(" + TS + r"\)")
SCENE_RE = re.compile(r"^SCENE\s+(\d+)\s*$", re.I)
HEADING_RE = re.compile(r"^Scene heading:\s*(.+)$", re.I)
NON_DIALOGUE = {"CAMERA": "camera", "ACTION": "action", "SOUND FX": "sound"}


def to_seconds(minutes, seconds):
    return round(int(minutes) * 60 + float(seconds), 2)


def fmt(t):
    """Seconds -> 'MM:SS.ss' (the screenplay's own format)."""
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def parse_label(label):
    """'MATRIARCH (O.S.) (Firm, Cold)' -> ('MATRIARCH', ['O.S.', 'Firm', 'Cold'])."""
    if label in NON_DIALOGUE:
        return None, []
    name = label.split("(")[0].strip()
    tags = []
    for group in re.findall(r"\(([^)]*)\)", label):
        tags += [t.strip() for t in group.split(",") if t.strip()]
    return name, tags


def parse_episode(path):
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()

    def header(key):
        m = re.search(rf"^{key}:\s*(.+)$", text, re.M | re.I)
        return m.group(1).strip() if m else ""

    ep_label = header("EPISODE NUMBER")
    m = re.search(r"(\d+)", ep_label) or re.search(r"episode-(\d+)", os.path.basename(path))
    ep_num = int(m.group(1))

    out, warnings = [], []
    scene, heading = 0, ""
    i = 0
    while i < len(lines):
        raw = lines[i].strip()
        if SCENE_RE.match(raw):
            scene = int(SCENE_RE.match(raw).group(1))
        elif HEADING_RE.match(raw):
            heading = HEADING_RE.match(raw).group(1).strip()
        elif BLOCK_RE.match(raw):
            label = BLOCK_RE.match(raw).group(1).strip()
            tm = TIME_RE.match(lines[i + 1].strip()) if i + 1 < len(lines) else None
            if not tm:
                warnings.append(f"no timestamp after block at line {i+1}: {raw}")
                i += 1
                continue
            start, end = to_seconds(*tm.group(1, 2)), to_seconds(*tm.group(3, 4))
            body, j = [], i + 2
            while j < len(lines) and lines[j].strip() and not BLOCK_RE.match(lines[j].strip()):
                body.append(lines[j].strip())
                j += 1
            speaker, tags = parse_label(label)
            out.append({
                "id": f"E{ep_num:02d}-L{len(out)+1:03d}",
                "type": NON_DIALOGUE.get(label, "dialogue"),
                "speaker": speaker,
                "tags": tags,
                "text": " ".join(body).strip('"').strip(),
                "start": start,
                "end": end,
                "scene": scene,
                "heading": heading,
            })
            i = j
            continue
        i += 1

    return {
        "episode": ep_num,
        "file": os.path.basename(path),
        "logline": header("EPISODE LOGLINE"),
        "continuity": header("CONTINUITY NOTES"),
        "duration": max((l["end"] for l in out), default=0),
        "lines": out,
        "warnings": warnings,
    }


def load_show(folder):
    paths = sorted(glob.glob(os.path.join(folder, "*.txt")))
    if not paths:
        raise SystemExit(f"No .txt episodes found in {folder}")
    eps = [parse_episode(p) for p in paths]
    eps.sort(key=lambda e: e["episode"])
    return eps


def line_for_prompt(l):
    """Compact one-line rendering the LLM sees. Note: NO timestamps shown as
    something to copy - only the ID and a relative duration hint."""
    if l["type"] == "dialogue":
        tags = f" ({', '.join(l['tags'])})" if l["tags"] else ""
        return f'{l["id"]} [{l["start"]:.1f}s] {l["speaker"]}{tags}: "{l["text"]}"'
    return f'{l["id"]} [{l["start"]:.1f}s] <{l["type"].upper()}> {l["text"]}'
