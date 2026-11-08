"""Sanity checks for Stage 1. Run: python tests/check_parse.py <episodes_folder>"""
import sys, os, re, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from promos.parse import load_show

folder = sys.argv[1]
eps = load_show(folder)
problems = 0
for e in eps:
    raw = open(os.path.join(folder, e["file"]), encoding="utf-8").read()
    expected = len(re.findall(r"^Start: \(", raw, re.M))
    got = len(e["lines"])
    bad_order = [l["id"] for l in e["lines"] if l["end"] < l["start"]]
    if got != expected or e["warnings"] or bad_order or not e["logline"]:
        problems += 1
        print(f"EP {e['episode']}: blocks {got}/{expected} warnings={e['warnings'][:2]} bad={bad_order[:3]}")
types = {}
for e in eps:
    for l in e["lines"]:
        types[l["type"]] = types.get(l["type"], 0) + 1
print(f"episodes={len(eps)} lines={sum(len(e['lines']) for e in eps)} types={types}")
print(f"episodes with problems: {problems}")
print("sample:", eps[0]["lines"][6])
