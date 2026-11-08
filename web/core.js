/* Find the Promos - core logic for the browser (and Node, for tests).
   A line-for-line port of promos/parse.py, verify.py, baseline.py and pipeline.py.
   Prompts are injected at build time from promos/prompts.py (single source of truth). */
(function (root) {
  "use strict";
  var P = root.FTP_PROMPTS; // {PROPOSE_SYSTEM, STRANGER_SYSTEM, VERSION}

  // ---------------------------------------------------------------- parse
  var TS = "(\\d+):(\\d+(?:\\.\\d+)?)";
  var BLOCK_RE = /^\*\*(.+?):\*\*\s*$/;
  var TIME_RE = new RegExp("^Start:\\s*\\(" + TS + "\\)\\s*\\|\\s*End:\\s*\\(" + TS + "\\)");
  var SCENE_RE = /^SCENE\s+(\d+)\s*$/i;
  var HEADING_RE = /^Scene heading:\s*(.+)$/i;
  var NON_DIALOGUE = { "CAMERA": "camera", "ACTION": "action", "SOUND FX": "sound" };

  function round2(x) { return Math.round(x * 100) / 100; }
  function toSeconds(m, s) { return round2(parseInt(m, 10) * 60 + parseFloat(s)); }
  function pad(n, w) { n = String(n); while (n.length < w) n = "0" + n; return n; }
  function fmt(t) {
    var m = Math.floor(t / 60), s = t - m * 60;
    var ss = s.toFixed(2); if (s < 10) ss = "0" + ss;
    return pad(m, 2) + ":" + ss;
  }
  function stripQuotes(s) { return s.replace(/^"+|"+$/g, "").trim(); }

  function parseLabel(label) {
    if (NON_DIALOGUE[label]) return [null, []];
    var name = label.split("(")[0].trim(), tags = [], m, re = /\(([^)]*)\)/g;
    while ((m = re.exec(label))) m[1].split(",").forEach(function (t) { t = t.trim(); if (t) tags.push(t); });
    return [name, tags];
  }

  function parseEpisode(text, filename) {
    var lines = text.split(/\r?\n/);
    function header(key) {
      var m = new RegExp("^" + key + ":\\s*(.+)$", "mi").exec(text);
      return m ? m[1].trim() : "";
    }
    var epLabel = header("EPISODE NUMBER");
    var m = /(\d+)/.exec(epLabel) || /episode-(\d+)/.exec(filename || "");
    if (!m) throw new Error("No episode number in " + filename);
    var epNum = parseInt(m[1], 10);
    var out = [], warnings = [], scene = 0, heading = "", i = 0;
    while (i < lines.length) {
      var raw = lines[i].trim(), bm;
      if (SCENE_RE.test(raw)) scene = parseInt(SCENE_RE.exec(raw)[1], 10);
      else if (HEADING_RE.test(raw)) heading = HEADING_RE.exec(raw)[1].trim();
      else if ((bm = BLOCK_RE.exec(raw))) {
        var label = bm[1].trim();
        var tm = i + 1 < lines.length ? TIME_RE.exec(lines[i + 1].trim()) : null;
        if (!tm) { warnings.push("no timestamp after block at line " + (i + 1) + ": " + raw); i++; continue; }
        var start = toSeconds(tm[1], tm[2]), end = toSeconds(tm[3], tm[4]);
        var body = [], j = i + 2;
        while (j < lines.length && lines[j].trim() && !BLOCK_RE.test(lines[j].trim())) { body.push(lines[j].trim()); j++; }
        var st = parseLabel(label);
        out.push({
          id: "E" + pad(epNum, 2) + "-L" + pad(out.length + 1, 3),
          type: NON_DIALOGUE[label] || "dialogue", speaker: st[0], tags: st[1],
          text: stripQuotes(body.join(" ")), start: start, end: end, scene: scene, heading: heading
        });
        i = j; continue;
      }
      i++;
    }
    return {
      episode: epNum, file: filename || "", logline: header("EPISODE LOGLINE"), continuity: header("CONTINUITY NOTES"),
      duration: out.reduce(function (a, l) { return Math.max(a, l.end); }, 0), lines: out, warnings: warnings
    };
  }

  function loadShow(files) { // files: [{name, text}]
    var eps = files.filter(function (f) { return /\.txt$/i.test(f.name); })
      .sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; })
      .map(function (f) { return parseEpisode(f.text, f.name); });
    eps.sort(function (a, b) { return a.episode - b.episode; });
    return eps;
  }

  function lineForPrompt(l) {
    if (l.type === "dialogue") {
      var tags = l.tags.length ? " (" + l.tags.join(", ") + ")" : "";
      return l.id + " [" + l.start.toFixed(1) + "s] " + l.speaker + tags + ': "' + l.text + '"';
    }
    return l.id + " [" + l.start.toFixed(1) + "s] <" + l.type.toUpperCase() + "> " + l.text;
  }
  function showBrief(eps) { return eps.map(function (e) { return "Ep " + e.episode + ": " + e.logline; }).join("\n"); }
  function proposeUser(brief, ep) {
    return "SHOW CONTEXT (one-line summary of every episode; character names vary across scripts, e.g. a character may be called by a description before their name is revealed):\n" +
      brief + "\n\nEPISODE " + ep.episode + " - logline: " + ep.logline + "\nEpisode length: " + ep.duration.toFixed(1) +
      "s\n\nLINES:\n" + ep.lines.map(lineForPrompt).join("\n") + "\n\nFind the best promos in Episode " + ep.episode + ".";
  }
  function plain(l) {
    if (l.type === "dialogue") return l.speaker + " (" + l.tags.join(", ") + '): "' + l.text + '"';
    return "[" + l.type + "] " + l.text;
  }
  function strangerUser(lines) { return "CLIP TRANSCRIPT:\n" + lines.map(plain).join("\n"); }

  // ---------------------------------------------------------------- verify
  var MIN_S = 20, MAX_S = 60, HOOK_WINDOW_S = 3, TAIL_WARN_S = 6, JUMP_WARN_S = 20;

  function Show(eps) {
    var self = this;
    this.eps = {}; this.byId = {}; this.list = eps;
    eps.forEach(function (e) {
      self.eps[e.episode] = e;
      e.lines.forEach(function (l, idx) { self.byId[l.id] = [e.episode, idx, l]; });
    });
    this.lastEp = Math.max.apply(null, eps.map(function (e) { return e.episode; }));
  }

  function inside(t, lines) {
    for (var i = 0; i < lines.length; i++) { var l = lines[i]; if (l.type === "dialogue" && l.start < t && t < l.end) return l; }
    return null;
  }
  function snapStart(t, lines) {
    var t0 = t, moved = [], l;
    while ((l = inside(t, lines))) { t = l.start; moved.push(l.id); }
    return [t, moved.length ? "start moved " + fmt(t0) + "->" + fmt(t) + " to avoid cutting into dialogue " + moved.join(", ") : null];
  }
  function snapEnd(t, lines) {
    var t0 = t, moved = [], l;
    while ((l = inside(t, lines))) { t = l.end; moved.push(l.id); }
    return [t, moved.length ? "end moved " + fmt(t0) + "->" + fmt(t) + " so dialogue " + moved.join(", ") + " finishes" : null];
  }
  function say(l) { return l.type === "dialogue" ? l.speaker + ': "' + l.text + '"' : "[" + l.type + "] " + l.text; }
  function asInt(v) { var f = parseFloat(v); if (isNaN(f)) return 0; return Math.max(0, Math.min(5, Math.round(f))); }

  function verify(cand, show) {
    var notes = [], warnings = [];
    function reject(reason) { var r = Object.assign({}, cand); r.reject_reason = reason; return [null, r]; }
    var segsIn = cand.segments || [];
    if (!segsIn.length) return reject("no segments");
    var ids = [];
    segsIn.forEach(function (s) { ids.push(s.start_id, s.end_id); });
    ids.push(cand.hook_id, cand.cliffhanger_id);
    var missing = ids.filter(function (x) { return !show.byId[x]; });
    if (missing.length) return reject("unknown line IDs " + JSON.stringify(missing) + " (model invented or mistyped them)");
    var epSet = {}; ids.forEach(function (x) { epSet[show.byId[x][0]] = 1; });
    var epKeys = Object.keys(epSet);
    if (epKeys.length !== 1) return reject("segments span episodes " + JSON.stringify(epKeys.map(Number).sort(function (a, b) { return a - b; })) + " - cross-episode joins are out of scope for v1");
    var epNum = Number(epKeys[0]), ep = show.eps[epNum], lines = ep.lines;
    var segs = [], prevEnd = -1;
    for (var n = 0; n < segsIn.length; n++) {
      var s = segsIn[n], a = show.byId[s.start_id][2], b = show.byId[s.end_id][2];
      var r1 = snapStart(a.start, lines); if (r1[1]) notes.push("seg " + (n + 1) + ": " + r1[1]);
      var r2 = snapEnd(Math.max(b.end, a.end), lines); if (r2[1]) notes.push("seg " + (n + 1) + ": " + r2[1]);
      var start = r1[0], end = r2[0];
      if (end <= start) return reject("segment " + (n + 1) + " ends before it starts (" + s.start_id + ".." + s.end_id + ")");
      if (start < prevEnd) return reject("segment " + (n + 1) + " overlaps or comes before segment " + n);
      segs.push({ start: start, end: end, start_id: s.start_id, end_id: s.end_id });
      prevEnd = end;
    }
    var hook = show.byId[cand.hook_id][2], s1 = segs[0];
    if (!(s1.start <= hook.start && hook.start < s1.end)) return reject("hook line " + hook.id + " is not inside segment 1");
    var trimmed = false;
    if (hook.start - s1.start > HOOK_WINDOW_S) {
      var ns = snapStart(hook.start, lines)[0];
      notes.push("seg 1: trimmed " + (hook.start - s1.start).toFixed(1) + "s of setup so the clip opens on the hook (" + fmt(s1.start) + "->" + fmt(ns) + ")");
      s1.start = ns; s1.start_id = hook.id; trimmed = true;
    }
    var hookAt = round2(hook.start - s1.start);
    if (hookAt > HOOK_WINDOW_S) return reject("hook starts " + hookAt.toFixed(1) + "s into the clip (must be <= 3s)");
    for (var k = 1; k < segs.length; k++) {
      var skip = segs[k].start - segs[k - 1].end;
      if (skip > JUMP_WARN_S) warnings.push("join skips " + Math.round(skip) + "s of story between segments " + k + " and " + (k + 1) + " - check it still reads as one moment");
    }
    var duration = round2(segs.reduce(function (acc, x) { return acc + (x.end - x.start); }, 0));
    if (duration < MIN_S) return reject("too short (" + duration.toFixed(1) + "s < 20s)" + (trimmed ? " after trimming setup" : ""));
    if (duration > MAX_S) return reject("too long (" + duration.toFixed(1) + "s > 60s)");
    var cliff = show.byId[cand.cliffhanger_id][2], last = segs[segs.length - 1];
    if (!(last.start <= cliff.start && cliff.start <= last.end)) return reject("cliffhanger line " + cliff.id + " is not inside the last segment");
    var tail = round2(last.end - cliff.end);
    if (tail > TAIL_WARN_S) warnings.push(tail.toFixed(1) + "s of footage after the cliffhanger line - may feel like it resolves");
    var afterIdx = show.byId[last.end_id][1] + 1;
    var after = lines.slice(afterIdx).filter(function (l) { return l.type === "dialogue" && l.start >= last.end - 0.01; }).slice(0, 2);
    var atEnd = ep.duration - last.end <= 1.0;
    var payoff = atEnd ? Math.min(epNum + 1, show.lastEp) : epNum;
    if (atEnd && epNum === show.lastEp) warnings.push("cuts at the end of the last available episode - payoff not in this pack");
    var out = Object.assign({}, cand);
    var sc = {}; Object.keys(cand.scores || {}).forEach(function (key) { sc[key] = asInt(cand.scores[key]); });
    out.scores = sc;
    out.hook_type = String(cand.hook_type || "other");
    Object.assign(out, {
      episode: epNum,
      segments: segs.map(function (x) { return Object.assign({}, x, { start_ts: fmt(x.start), end_ts: fmt(x.end) }); }),
      duration: duration, hook_at: hookAt, hook_text: say(hook), cliffhanger_text: say(cliff),
      after_cut: atEnd ? ["(episode ends - continues in Episode " + payoff + ")"] : after.map(say),
      ends_at_episode_end: atEnd, payoff_episode: payoff, repairs: notes, warnings: warnings
    });
    return [out, null];
  }

  function clipLines(c, show) {
    var ep = show.eps[c.episode], out = [];
    c.segments.forEach(function (s) {
      ep.lines.forEach(function (l) { if (l.start >= s.start - 0.01 && l.end <= s.end + 0.01) out.push(l); });
    });
    return out;
  }

  // ---------------------------------------------------------------- rules-only baseline
  var HIGH_TAGS = ["screaming", "shouting", "furious", "outraged", "horrified", "gasping", "weeping", "desperate", "venomous", "threatening", "cruel", "crying out", "enraged", "panicked", "sobbing", "terrified", "shocked", "accusing", "seething", "roaring", "begging"];
  var PHYSICAL = /\b(slap\w*|strike\w*|struck|shove\w*|grab\w*|seiz\w*|explo\w*|blood\w*|knife|blade|sword|chain\w*|collaps\w*|kneel\w*|kiss\w*|throw\w*|threw|smash\w*|burn\w*|fire|flames|poison\w*)\b/i;
  function intensity(l) {
    var s = 0;
    if (l.type === "dialogue") {
      s += 2 * l.tags.filter(function (t) { return HIGH_TAGS.indexOf(t.toLowerCase()) >= 0; }).length;
      s += l.text.indexOf("!") >= 0 ? 1 : 0;
    }
    if ((l.type === "action" || l.type === "camera") && PHYSICAL.test(l.text)) s += 2;
    return s;
  }
  function endingScore(l, ep) {
    if (ep.duration - l.end <= 1.0) return 3;
    if (l.type === "dialogue" && /\?\s*$/.test(l.text)) return 2;
    if (l.type === "dialogue" && l.text.indexOf("!") >= 0) return 1;
    return 0;
  }
  function baseline(eps, show, perEpisode) {
    perEpisode = perEpisode || 2;
    var kept = [], rejected = [], ENDS = ["a plain line", "an exclamation", "a question", "the episode's final beat"];
    eps.forEach(function (ep) {
      var speakable = ep.lines.filter(function (l) { return l.type === "dialogue" || l.type === "action"; });
      var hooks = speakable.filter(function (l) { return intensity(l) >= 2; })
        .sort(function (a, b) { return (intensity(b) - intensity(a)) || (a.start - b.start); });
      var chosen = [];
      for (var i = 0; i < hooks.length && chosen.length < perEpisode; i++) {
        var h = hooks[i];
        if (chosen.some(function (c) { return c.s - 5 <= h.start && h.start <= c.e; })) continue;
        var win = speakable.filter(function (l) { return h.start + MIN_S <= l.end && l.end <= h.start + MAX_S; });
        if (!win.length) continue;
        var end = win[0];
        win.forEach(function (l) {
          var a = endingScore(l, ep), b = endingScore(end, ep);
          if (a > b || (a === b && l.end > end.end)) end = l;
        });
        var cand = { source: "rules", segments: [{ start_id: h.id, end_id: end.id }], hook_id: h.id, cliffhanger_id: end.id,
          why: "Opens on high-intensity line (score " + intensity(h) + "); ends on " + ENDS[endingScore(end, ep)],
          rule_score: intensity(h) + endingScore(end, ep) };
        var r = verify(cand, show);
        if (r[0]) { kept.push(r[0]); chosen.push({ s: r[0].segments[0].start, e: r[0].segments[r[0].segments.length - 1].end }); }
        else rejected.push(r[1]);
      }
    });
    kept.sort(function (a, b) { return b.rule_score - a.rule_score; });
    return [kept, rejected];
  }
  function finishRules(kept, freeEpisodes) {
    var seen = {};
    kept.forEach(function (c, i) {
      c.cand_id = "R" + pad(i + 1, 2); c.tier = "R"; c.rank = i + 1; c.in_free_window = c.payoff_episode <= freeEpisodes;
      c.rank_reason = "Rules score " + c.rule_score + " (intensity of opening line + type of ending)";
      c.post_first = !seen[c.episode] && Object.keys(seen).length < 10;
      if (c.post_first) seen[c.episode] = 1;
    });
    return kept;
  }

  // ---------------------------------------------------------------- pipeline (same order and rules as pipeline.py)
  function standalone(c) { return c.stranger ? c.stranger.standalone_score : (c.scores || {}).standalone || 0; }
  function scoreSum(c) { var s = c.scores || {}; return (s.hook || 0) + (s.cliffhanger || 0) + standalone(c); }
  function overlap(a, b) {
    if (a.episode !== b.episode) return 0;
    var inter = 0;
    a.segments.forEach(function (x) { b.segments.forEach(function (y) { inter += Math.max(0, Math.min(x.end, y.end) - Math.max(x.start, y.start)); }); });
    return inter / Math.min(a.duration, b.duration);
  }
  function dedupe(cands) {
    var out = [], dups = [];
    cands.slice().sort(function (a, b) { return scoreSum(b) - scoreSum(a); }).forEach(function (c) {
      var twin = null;
      for (var i = 0; i < out.length; i++) if (overlap(c, out[i]) > 0.5) { twin = out[i]; break; }
      if (!twin) out.push(c);
      else dups.push(Object.assign({}, c, { reject_reason: "near-duplicate of " + twin.cand_id + " (>50% overlap, lower score)" }));
    });
    return [out, dups];
  }
  function processProposals(ep, res, show, kept, rejected) {
    if (!res || res._unparseable || !Array.isArray(res.promos)) {
      rejected.push({ episode: ep.episode, source: "llm", reject_reason: "model returned unparseable output" }); return;
    }
    res.promos.forEach(function (p, n) {
      var cand = Object.assign({}, p, { source: "llm", proposed_in_episode: ep.episode, cand_id: "E" + pad(ep.episode, 2) + "-P" + (n + 1) });
      var r = verify(cand, show);
      if (r[0]) kept.push(r[0]); else rejected.push(r[1]);
    });
  }
  function tier(c) {
    var s = c.scores || {}, hook = s.hook || 0, cliff = s.cliffhanger || 0, alone = standalone(c);
    var st = c.stranger || {};
    var resolved = String(st.open_question || "").trim().toLowerCase().indexOf("none") === 0;
    if (hook >= 4 && cliff >= 4 && alone >= 4 && !resolved) return "A";
    if (Math.min(hook, cliff, alone) >= 3 && !resolved) return "B";
    return "C";
  }
  function rank(cands, freeEpisodes) {
    cands.forEach(function (c) { c.tier = tier(c); c.in_free_window = c.payoff_episode <= freeEpisodes; });
    cands.sort(function (a, b) {
      if (a.tier !== b.tier) return a.tier < b.tier ? -1 : 1;
      if (a.in_free_window !== b.in_free_window) return a.in_free_window ? -1 : 1;
      var d = scoreSum(b) - scoreSum(a); if (d) return d;
      return a.payoff_episode - b.payoff_episode;
    });
    var seen = {}, n = 0;
    cands.forEach(function (c) {
      c.post_first = false;
      if ((c.tier === "A" || c.tier === "B") && !seen[c.episode] && n < 10) { c.post_first = true; n++; seen[c.episode] = 1; }
    });
    cands.forEach(function (c, i) {
      c.rank = i + 1;
      var s = c.scores || {}, parts = ["Tier " + c.tier + ": hook " + (s.hook || "?") + "/5, cliffhanger " + (s.cliffhanger || "?") + "/5"];
      parts.push(c.stranger ? "blind stranger understood it " + c.stranger.standalone_score + "/5" : "standalone " + (s.standalone || "?") + "/5 (self-rated, not blind-tested)");
      parts.push("payoff in Ep " + c.payoff_episode + " (" + (c.in_free_window ? "inside" : "outside") + " first " + freeEpisodes + " episodes)");
      c.rank_reason = parts.join("; ");
    });
    return cands;
  }
  function applyStranger(c, res) {
    if (!res || res._unparseable) { c.stranger_error = "blind test returned no usable score"; return; }
    var f = parseFloat(res.standalone_score);
    if (isNaN(f)) { c.stranger_error = "blind test returned no usable score"; return; }
    res.standalone_score = Math.round(f); c.stranger = res;
  }
  // Blind-test in RANKED order until every "post first" clip is tested. callStranger(c) -> Promise<res>
  async function rankWithBlindTest(cands, show, callStranger, topN, freeEpisodes, log) {
    var ranked = rank(cands, freeEpisodes), budget = topN;
    for (var round = 0; round < 4; round++) {
      var untestedFirst = ranked.filter(function (c) { return c.post_first && !c.stranger; });
      if (!untestedFirst.length && budget <= 0) break;
      var order = untestedFirst.concat(ranked.filter(function (c) { return !c.post_first; }));
      var n = Math.max(untestedFirst.length, budget);
      var batch = order.filter(function (c) { return !c.stranger; }).slice(0, n);
      var results = await Promise.all(batch.map(function (c) { return callStranger(c, strangerUser(clipLines(c, show))); }));
      batch.forEach(function (c, i) { applyStranger(c, results[i]); });
      budget -= n;
      ranked = rank(cands, freeEpisodes);
      if (!ranked.some(function (c) { return c.post_first && !c.stranger; })) break;
    }
    return ranked;
  }

  // ---------------------------------------------------------------- model client
  function parseJSON(text) {
    try { return JSON.parse(text); } catch (e) {
      var m = /\{[\s\S]*\}/.exec(text || "");
      if (m) { try { return JSON.parse(m[0]); } catch (e2) {} }
      return { _unparseable: true, raw: String(text || "").slice(0, 2000) };
    }
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // cfg: {provider: gemini|openai|replay, key, model, baseUrl, replay: {tag: parsed}, timeoutMs, onEvent}
  function makeClient(cfg) {
    var stats = { calls: 0, retries: 0, in_tokens: 0, out_tokens: 0, model_version: cfg.model };
    async function post(url, body, headers) {
      var ctl = new AbortController(), timer = setTimeout(function () { ctl.abort(); }, cfg.timeoutMs || 240000);
      try {
        var r = await fetch(url, { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, headers), body: JSON.stringify(body), signal: ctl.signal });
        var txt = await r.text();
        if (!r.ok) { var err = new Error("HTTP " + r.status + ": " + txt.slice(0, 300)); err.status = r.status; err.body = txt; throw err; }
        return JSON.parse(txt);
      } finally { clearTimeout(timer); }
    }
    async function once(system, user) {
      if (cfg.provider === "gemini") {
        var url = "https://generativelanguage.googleapis.com/v1beta/models/" + encodeURIComponent(cfg.model) + ":generateContent";
        var d = await post(url, { systemInstruction: { parts: [{ text: system }] }, contents: [{ role: "user", parts: [{ text: user }] }],
          generationConfig: { temperature: 0, responseMimeType: "application/json" } }, { "x-goog-api-key": cfg.key });
        var parts = (((d.candidates || [])[0] || {}).content || {}).parts || [];
        var u = d.usageMetadata || {};
        stats.in_tokens += u.promptTokenCount || 0; stats.out_tokens += (u.candidatesTokenCount || 0) + (u.thoughtsTokenCount || 0);
        if (d.modelVersion) stats.model_version = d.modelVersion;
        return parts.filter(function (p) { return !p.thought; }).map(function (p) { return p.text || ""; }).join("");
      }
      if (cfg.provider === "openai") {
        var base = (cfg.baseUrl || "https://api.openai.com/v1").replace(/\/+$/, "");
        var o = await post(base + "/chat/completions", { model: cfg.model, temperature: 0, messages: [{ role: "system", content: system }, { role: "user", content: user }] },
          { "Authorization": "Bearer " + cfg.key });
        var uu = o.usage || {}; stats.in_tokens += uu.prompt_tokens || 0; stats.out_tokens += uu.completion_tokens || 0;
        return o.choices[0].message.content;
      }
      throw new Error("unknown provider " + cfg.provider);
    }
    async function call(system, user, tag) {
      if (cfg.provider === "replay") {
        var hit = cfg.replay[tag];
        return hit === undefined ? { _missing: true } : hit;
      }
      var delay = 10000;
      for (var attempt = 0; attempt < 5; attempt++) {
        var t0 = Date.now();
        try {
          var text = await once(system, user);
          stats.calls++;
          if (cfg.onEvent) cfg.onEvent({ tag: tag, ok: true, seconds: (Date.now() - t0) / 1000 });
          return parseJSON(text);
        } catch (e) {
          var retryable = e.name === "AbortError" || e.name === "TypeError" || [429, 500, 502, 503, 504].indexOf(e.status) >= 0;
          if (!retryable || attempt === 4) {
            if (cfg.onEvent) cfg.onEvent({ tag: tag, ok: false, error: e.message || String(e) });
            throw e;
          }
          var m = /"retryDelay":\s*"(\d+)/.exec(e.body || ""), wait = m ? (parseInt(m[1], 10) + 1) * 1000 : delay;
          stats.retries++;
          if (cfg.onEvent) cfg.onEvent({ tag: tag, retry: true, reason: e.status ? "HTTP " + e.status : (e.name === "AbortError" ? "no reply in time" : "network"), wait: wait / 1000 });
          await sleep(wait); delay = Math.min(delay * 2, 90000);
        }
      }
    }
    return { call: call, stats: stats };
  }

  // Run tasks with at most `limit` in flight; results keep input order.
  async function pool(items, limit, worker) {
    var results = new Array(items.length), next = 0;
    async function lane() { while (next < items.length) { var i = next++; results[i] = await worker(items[i], i); } }
    var lanes = []; for (var k = 0; k < Math.max(1, limit); k++) lanes.push(lane());
    await Promise.all(lanes);
    return results;
  }

  // ---------------------------------------------------------------- full AI run
  // opts: {client, runEps, show, allEps, topN, freeEpisodes, parallel, onProgress}
  async function runAI(opts) {
    var brief = showBrief(opts.allEps), kept = [], rejected = [], empty = [];
    var tag = function (ep) { return "propose-ep" + pad(ep.episode, 2); };
    var results = await pool(opts.runEps, opts.parallel || 3, async function (ep) {
      if (opts.onProgress) opts.onProgress({ episode: ep.episode, state: "running" });
      try {
        var res = await opts.client.call(P.PROPOSE_SYSTEM, proposeUser(brief, ep), tag(ep));
        if (opts.onProgress) opts.onProgress({ episode: ep.episode, state: res && res._missing ? "missing" : "done", n: res && res.promos ? res.promos.length : 0 });
        return res;
      } catch (e) {
        if (opts.onProgress) opts.onProgress({ episode: ep.episode, state: "failed", error: e.message });
        return { _failed: true, error: e.message };
      }
    });
    opts.runEps.forEach(function (ep, i) {
      var res = results[i];
      if (res._failed) { rejected.push({ episode: ep.episode, source: "llm", reject_reason: "model call failed: " + res.error }); return; }
      if (res._missing) { rejected.push({ episode: ep.episode, source: "llm", reject_reason: "no saved answer for this episode in the replay folder" }); return; }
      if (Array.isArray(res.promos) && !res.promos.length) empty.push(ep.episode);
      processProposals(ep, res, opts.show, kept, rejected);
    });
    var proposed = kept.length + rejected.length;
    var d = dedupe(kept); kept = d[0]; rejected = rejected.concat(d[1]);
    var callStranger = async function (c, user) {
      try { var r = await opts.client.call(P.STRANGER_SYSTEM, user, "stranger-" + c.cand_id); return r && r._missing ? null : r; }
      catch (e) { return null; }
    };
    var ranked = opts.topN ? await rankWithBlindTest(kept, opts.show, callStranger, opts.topN, opts.freeEpisodes)
      : rank(kept, opts.freeEpisodes);
    return { ranked: ranked, rejected: rejected, proposed: proposed, emptyEpisodes: empty };
  }

  var api = { parseEpisode: parseEpisode, loadShow: loadShow, Show: Show, verify: verify, clipLines: clipLines, baseline: baseline,
    finishRules: finishRules, rank: rank, dedupe: dedupe, runAI: runAI, makeClient: makeClient, pool: pool, fmt: fmt,
    proposeUser: proposeUser, showBrief: showBrief, strangerUser: strangerUser, lineForPrompt: lineForPrompt, parseJSON: parseJSON };
  root.FTP = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
