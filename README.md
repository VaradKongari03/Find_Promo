# Find the Promos

Reads a microdrama screenplay (one `.txt` per episode, Kuku's format) and suggests promo clips: episode, start and end timecodes for every segment, the hook, the cliffhanger, and one line on why it works. Results are ranked and written to an HTML review sheet, where an editor can keep or reject each clip and export their decisions.

It finds clips. It does not cut video.

## How it works
```
screenplay .txt files
  -> parse (code)       every camera/action/dialogue line gets an ID and exact timestamps
  -> propose (LLM)      one call per episode; the model cites LINE IDs, never timestamps
  -> verify (code)      20-60 s, hook within first 3 s, no cut mid-sentence, IDs exist
  -> blind test (LLM)   top 15 clips shown to a fresh call with no show context
  -> rank (code)        tiers A/B/C, then how early the payoff lands, then score
  -> report.html, promos.json, promos.csv, rejected.json, llm_raw/
```
A rules-only version (no AI) runs alongside it for comparison (`rules-only.html`).

## Web version (no install)

`docs/index.html` is the same tool as one page that runs in the browser: choose the show's folder, paste a Gemini key (or pick Rules only / Replay a saved run), click Find promos. Episodes run in parallel, and the results open as the review sheet. Scripts are read locally; only prompts go to the chosen model provider.

Host it free with GitHub Pages: repo **Settings → Pages → Deploy from a branch → `main` / `/docs`**. The link is `https://varadkongari03.github.io/Find_Promo/`.

The page is a port of the Python code (`web/core.js`), built by `python web/build.py` with the prompts taken from `promos/prompts.py`. `node tests/web_parity.js <episodes> <outputs>` checks it reproduces a Python run exactly (on the submitted run: 77/77 clips, same ranks, same rejections).

## Run it

Needs Python 3.9+ and nothing to install (standard library only).

```bash
export GEMINI_API_KEY=...            # free key from https://aistudio.google.com/apikey
python run.py --episodes "path/to/show-folder" --only-episodes 1-3   # quick check first
python run.py --episodes "path/to/show-folder" --out outputs         # whole show
```
Open `outputs/report.html` in a browser.

No key? `python run.py --episodes "path/to/show-folder" --rules-only`

### Swap the model
```bash
# Any Gemini model available to your key
python run.py --episodes ... --model gemini-flash-lite-latest

# Any OpenAI-compatible API (OpenAI, Groq, OpenRouter, Ollama, a company gateway)
export OPENAI_API_KEY=...  OPENAI_BASE_URL=https://api.groq.com/openai/v1
python run.py --episodes ... --provider openai --model <model-id>

# Claude
export ANTHROPIC_API_KEY=...
python run.py --episodes ... --provider anthropic --model <claude-model-id>
```
Every response is cached in `outputs/llm_raw/` (keyed by model + prompt), so re-running is free and gives the same result. Delete that folder to force fresh calls. `run_meta.json` records the exact model version the API reported.

### No API access? File handoff
```bash
python run.py --episodes ... --provider file --model "<name of whatever answers>"
```
The tool writes each prompt to `outputs/handoff/requests/<tag>.json`. Any model or chat UI can answer it; save the raw JSON reply to the `answer_to` path in that file, then run the same command again. Unanswered prompts are reported as pending. The submitted outputs were produced this way (see `notes/log.md`).

### Options
| Flag | Default | Meaning |
|---|---|---|
| `--stranger-top` | 15 | how many top clips get the blind test (0 = off) |
| `--free-episodes` | 10 | assumed free episodes before a paywall; used for the "payoff lands early" factor |
| `--min-interval` | 4.0 | seconds between API calls, to stay under free-tier rate limits |
| `--only-episodes` | all | e.g. `1-5` |

## Files
| File | What |
|---|---|
| `promos/parse.py` | screenplay to timestamped lines |
| `promos/prompts.py` | the two prompts |
| `promos/llm.py` | provider adapter + cache |
| `promos/verify.py` | hard rules, cut-point repair, rejection reasons |
| `promos/pipeline.py` | propose, dedupe, blind test, rank |
| `promos/baseline.py` | rules-only version |
| `promos/report.py` | HTML/CSV/JSON output |
| `tests/` | parser check; plumbing test with a fake model |

## Confidentiality
The input pack is Kuku's content. Don't commit episodes, `outputs/`, or `llm_raw/` (which contains prompts with script text) to a public repo. `.gitignore` excludes them.
