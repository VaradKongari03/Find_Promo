"""Stage 3 - One function to talk to any model: call_llm(system, user) -> dict.

Swapping models = changing two settings (provider, model). No SDKs, only the
Python standard library, so it runs anywhere (Colab, laptop, Kuku's servers).

Providers:
  gemini     Google AI Studio (free tier)            env: GEMINI_API_KEY
  openai     ANY OpenAI-compatible endpoint: OpenAI, Groq, OpenRouter, Together,
             Ollama, or a company gateway             env: OPENAI_API_KEY, OPENAI_BASE_URL
  anthropic  Claude                                  env: ANTHROPIC_API_KEY
  file       No API. Writes each prompt to handoff/requests/<tag>.json and reads the
             answer from handoff/responses/<tag>.txt. Lets ANY model or chat UI act as
             the LLM (used for the submitted run - see notes/log.md). Run the tool again
             after answers are in; unanswered prompts are reported as pending.

Every response is cached on disk, keyed by (provider, model, prompt). Re-runs
are free and identical, and the cache folder IS the raw-output record.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request


class LLM:
    def __init__(self, provider="gemini", model="gemini-flash-latest", cache_dir="llm_cache",
                 min_interval=4.0, temperature=0.0, max_retries=5):
        self.provider, self.model = provider, model
        self.cache_dir = cache_dir
        self.min_interval = min_interval  # seconds between live calls (free-tier rate limits)
        self.temperature = temperature
        self.max_retries = max_retries
        self._last = 0.0
        self.model_version = model  # exact version reported by the API, if any
        self.stats = {"live_calls": 0, "cache_hits": 0, "in_tokens": 0, "out_tokens": 0, "json_repairs": 0}
        os.makedirs(cache_dir, exist_ok=True)

    # ---------- public ----------
    def call(self, system, user, tag="call"):
        key = hashlib.sha256(f"{self.provider}|{self.model}|{self.temperature}|{system}|{user}".encode()).hexdigest()[:16]
        path = os.path.join(self.cache_dir, f"{tag}-{key}.json")
        if os.path.exists(path):
            self.stats["cache_hits"] += 1
            rec = json.load(open(path, encoding="utf-8"))
            self.model_version = rec.get("usage", {}).get("model_version", self.model_version)
            return rec["parsed"]

        if self.provider == "file":
            text = self._file(system, user, tag)
            if text is None:
                self.stats["pending"] = self.stats.get("pending", 0) + 1
                return {"_pending": True}
            usage = {"in": 0, "out": 0, "model_version": self.model}
            return self._store(path, tag, system, user, text, usage)

        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        t0 = time.time()
        text, usage = self._with_retries(system, user)
        self._last = time.time()
        print(f"     model replied in {self._last - t0:.0f}s")
        self.stats["live_calls"] += 1
        self.stats["in_tokens"] += usage.get("in", 0)
        self.stats["out_tokens"] += usage.get("out", 0)

        return self._store(path, tag, system, user, text, usage)

    def _store(self, path, tag, system, user, text, usage):
        parsed = self._parse_json(text)
        record = {"tag": tag, "provider": self.provider, "model": self.model, "temperature": self.temperature,
                  "usage": usage, "system": system, "user": user, "raw_text": text, "parsed": parsed}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
        return parsed

    # ---------- plumbing ----------
    def _with_retries(self, system, user):
        delay = 10
        for attempt in range(self.max_retries):
            try:
                return getattr(self, f"_{self.provider}")(system, user)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")[:400]
                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    m = re.search(r'"retryDelay":\s*"(\d+)', body)
                    sleep = int(m.group(1)) + 1 if m else delay
                    print(f"   [{e.code}] rate-limited/overloaded, retrying in {sleep}s ...")
                    time.sleep(sleep)
                    delay = min(delay * 2, 90)
                    continue
                raise SystemExit(f"LLM call failed ({e.code}): {body}")
            except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
                # No reply in time (model busy/overloaded) or a dropped connection: retry too.
                if attempt < self.max_retries - 1:
                    print(f"   [{type(e).__name__}] no reply, retrying in {delay}s ...")
                    time.sleep(delay)
                    delay = min(delay * 2, 90)
                    continue
                raise SystemExit(f"LLM call failed after {self.max_retries} tries: {e}")
        raise SystemExit("LLM call failed after retries")

    @staticmethod
    def _post(url, payload, headers):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers})
        with urllib.request.urlopen(req, timeout=240) as r:
            return json.loads(r.read().decode())

    def _file(self, system, user, tag):
        root = os.path.join(os.path.dirname(os.path.abspath(self.cache_dir)), "handoff")
        req, res = os.path.join(root, "requests"), os.path.join(root, "responses")
        os.makedirs(req, exist_ok=True)
        os.makedirs(res, exist_ok=True)
        ans = os.path.join(res, f"{tag}.txt")
        if os.path.exists(ans):
            return open(ans, encoding="utf-8").read()
        with open(os.path.join(req, f"{tag}.json"), "w", encoding="utf-8") as f:
            json.dump({"tag": tag, "system": system, "user": user,
                       "answer_to": os.path.abspath(ans)}, f, ensure_ascii=False, indent=1)
        return None

    def _gemini(self, system, user):
        key = os.environ.get("GEMINI_API_KEY") or _missing("GEMINI_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        data = self._post(url, {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": self.temperature, "responseMimeType": "application/json"},
        }, {"x-goog-api-key": key})
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        u = data.get("usageMetadata", {})
        self.model_version = data.get("modelVersion", self.model)
        return text, {"in": u.get("promptTokenCount", 0), "out": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
                      "model_version": self.model_version}

    def _openai(self, system, user):
        key = os.environ.get("OPENAI_API_KEY") or _missing("OPENAI_API_KEY")
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        data = self._post(f"{base}/chat/completions", {
            "model": self.model, "temperature": self.temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, {"Authorization": f"Bearer {key}"})
        u = data.get("usage", {})
        return data["choices"][0]["message"]["content"], {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}

    def _anthropic(self, system, user):
        key = os.environ.get("ANTHROPIC_API_KEY") or _missing("ANTHROPIC_API_KEY")
        data = self._post("https://api.anthropic.com/v1/messages", {
            "model": self.model, "max_tokens": 4000, "temperature": self.temperature, "system": system,
            "messages": [{"role": "user", "content": user}],
        }, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        u = data.get("usage", {})
        return "".join(b.get("text", "") for b in data["content"]), {"in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0)}

    def _parse_json(self, text):
        """Models sometimes wrap JSON in ``` fences or add chatter. Extract the object."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.stats["json_repairs"] += 1
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            return {"_unparseable": True, "raw": text[:2000]}


def _missing(name):
    raise SystemExit(f"Set the {name} environment variable (see README).")
