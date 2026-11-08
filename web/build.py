"""Build web/index.html: one self-contained page (prompts + core + app inlined).

Run from the repo root:  python web/build.py
The prompts come from promos/prompts.py, so the web app and the Python tool ask the model the same thing.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from promos import prompts  # noqa: E402

prompts_js = "(function(root){root.FTP_PROMPTS=" + json.dumps({
    "PROPOSE_SYSTEM": prompts.PROPOSE_SYSTEM,
    "STRANGER_SYSTEM": prompts.STRANGER_SYSTEM,
    "VERSION": prompts.PROMPT_VERSION,
}) + ";})(typeof window!=='undefined'?window:globalThis);"
open(os.path.join(HERE, "prompts.js"), "w", encoding="utf-8").write(prompts_js + "\n")

read = lambda name: open(os.path.join(HERE, name), encoding="utf-8").read()
page = read("template.html")
for marker, code in (("/*PROMPTS*/", prompts_js), ("/*CORE*/", read("core.js")), ("/*APP*/", read("app.js"))):
    assert marker in page, marker
    page = page.replace(marker, code.replace("</script", "<\\/script"))
open(os.path.join(HERE, "index.html"), "w", encoding="utf-8").write(page)
docs = os.path.join(os.path.dirname(HERE), "docs")  # GitHub Pages serves /docs
os.makedirs(docs, exist_ok=True)
open(os.path.join(docs, "index.html"), "w", encoding="utf-8").write(page)
print(f"wrote web/index.html and docs/index.html ({len(page) // 1024} KB)")
