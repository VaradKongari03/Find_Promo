/* Find the Promos - browser UI. Everything runs locally; only prompts go to the chosen model provider. */
(function () {
  "use strict";
  var F = window.FTP;
  var $ = function (sel) { return document.querySelector(sel); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var S = { eps: null, show: null, replay: null, result: null, rules: null, tab: "first", dec: {}, why: {}, running: false };

  // ------------------------------------------------------------ step 1: load scripts
  function readFiles(fileList) {
    var files = Array.prototype.filter.call(fileList, function (f) { return /\.txt$/i.test(f.name); });
    if (!files.length) { setLoadMsg("No .txt screenplay files found. Pick the folder that holds one .txt per episode (unzip the pack first).", true); return; }
    Promise.all(files.map(function (f) { return f.text().then(function (t) { return { name: f.name, text: t }; }); })).then(function (arr) {
      try {
        S.eps = F.loadShow(arr); S.show = new F.Show(S.eps);
      } catch (e) { setLoadMsg("Could not read these files: " + e.message, true); return; }
      var lines = S.eps.reduce(function (a, e) { return a + e.lines.length; }, 0);
      var mins = S.eps.reduce(function (a, e) { return a + e.duration; }, 0) / 60;
      var warn = S.eps.reduce(function (a, e) { return a + e.warnings.length; }, 0);
      var noLines = S.eps.filter(function (e) { return !e.lines.length; }).map(function (e) { return e.episode; });
      var first = S.eps[0].episode, last = S.eps[S.eps.length - 1].episode;
      $("#fromEp").value = first; $("#toEp").value = Math.min(last, first + 2);
      $("#fromEp").min = $("#toEp").min = first; $("#fromEp").max = $("#toEp").max = last;
      setLoadMsg("Loaded " + S.eps.length + " episodes (Ep " + first + "–" + last + "), " + lines.toLocaleString() + " timestamped lines, " + mins.toFixed(0) + " min of script." +
        (warn ? " " + warn + " blocks had no timestamp and were skipped." : "") + (noLines.length ? " No lines found in Ep " + noLines.join(", ") + ": check the format." : ""), !!noLines.length);
      S.rules = F.finishRules(F.baseline(S.eps, S.show)[0], parseInt($("#freeEps").value, 10) || 10);
      $("#step2").hidden = false; updateRunLabel();
    });
  }
  function setLoadMsg(t, bad) { var m = $("#loadMsg"); m.textContent = t; m.className = bad ? "msg bad" : "msg ok"; }

  // ------------------------------------------------------------ step 2: provider
  function provider() { return document.querySelector('input[name="prov"]:checked').value; }
  function syncProvider() {
    var p = provider();
    document.querySelectorAll("[data-prov]").forEach(function (el) { el.hidden = el.getAttribute("data-prov") !== p; });
    $("#aiOpts").hidden = p === "rules";
    updateRunLabel();
  }
  function updateRunLabel() {
    if (!S.eps) return;
    var p = provider(), a = parseInt($("#fromEp").value, 10), b = parseInt($("#toEp").value, 10);
    var n = S.eps.filter(function (e) { return e.episode >= a && e.episode <= b; }).length;
    $("#runBtn").textContent = p === "rules" ? "Find promos (rules only, instant)" : "Find promos in " + n + " episode" + (n === 1 ? "" : "s");
    var par = parseInt($("#parallel").value, 10) || 1;
    $("#estimate").textContent = p === "gemini" || p === "openai" ? "Each call takes about 30–90 s; with " + par + " at a time, " + n + " episodes take roughly " + Math.max(1, Math.round(n * 60 / par / 60)) + "–" + Math.max(2, Math.round(n * 90 / par / 60)) + " min, plus the blind tests." : "";
  }
  function checkGemini(key) {
    return fetch("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", { headers: { "x-goog-api-key": key } })
      .then(function (r) { return r.text().then(function (t) { if (!r.ok) throw new Error("Google rejected the key (HTTP " + r.status + "): " + t.slice(0, 160)); return JSON.parse(t); }); })
      .then(function (d) {
        return (d.models || []).filter(function (m) { return (m.supportedGenerationMethods || []).indexOf("generateContent") >= 0; })
          .map(function (m) { return m.name.replace(/^models\//, ""); });
      }, function (e) {
        if (e instanceof TypeError) throw new Error("This page can't reach Google from here. Inside claude.ai, outside calls are blocked: open the GitHub Pages version of this page, or use Rules only / Replay.");
        throw e;
      });
  }
  function onCheckKey() {
    var key = $("#gemKey").value.trim(), msg = $("#keyMsg");
    if (!key) { msg.textContent = "Paste a key first."; msg.className = "msg bad"; return; }
    msg.textContent = "Checking…"; msg.className = "msg";
    checkGemini(key).then(function (models) {
      var flash = models.filter(function (m) { return /flash/.test(m); });
      $("#gemModels").innerHTML = models.map(function (m) { return '<option value="' + esc(m) + '"></option>'; }).join("");
      msg.textContent = "Key works. " + flash.length + " Flash models available" + (flash.length ? ", e.g. " + flash.slice(0, 3).join(", ") : "") + ".";
      msg.className = "msg ok";
    }, function (e) { msg.textContent = e.message; msg.className = "msg bad"; });
  }
  function readReplay(fileList) {
    var files = Array.prototype.filter.call(fileList, function (f) { return /\.(json|txt)$/i.test(f.name); });
    Promise.all(files.map(function (f) { return f.text().then(function (t) { return { name: f.name, text: t }; }); })).then(function (arr) {
      var map = {}, n = 0;
      arr.forEach(function (f) {
        try {
          if (/\.json$/i.test(f.name)) { var r = JSON.parse(f.text); if (r && r.tag && r.parsed) { map[r.tag] = r.parsed; n++; } }
          else { map[f.name.replace(/\.txt$/i, "")] = F.parseJSON(f.text); n++; }
        } catch (e) { /* skip unreadable file */ }
      });
      S.replay = map;
      $("#replayMsg").textContent = n ? "Loaded " + n + " saved model answers." : "No saved answers found. Pick the llm_raw folder from a run.";
      $("#replayMsg").className = n ? "msg ok" : "msg bad";
    });
  }

  // ------------------------------------------------------------ step 3: run
  function chips(eps) {
    $("#chips").innerHTML = eps.map(function (e) { return '<span class="chip" id="chip' + e.episode + '" title="Episode ' + e.episode + ': waiting">' + e.episode + "</span>"; }).join("");
  }
  function setChip(ep, state, title) { var c = $("#chip" + ep); if (c) { c.className = "chip " + state; c.title = "Episode " + ep + ": " + title; } }
  function log(t, bad) {
    var li = document.createElement("li"); li.textContent = t; if (bad) li.className = "bad";
    var ul = $("#log"); ul.insertBefore(li, ul.firstChild); while (ul.children.length > 12) ul.removeChild(ul.lastChild);
  }
  function onRun() {
    if (S.running || !S.eps) return;
    var p = provider(), free = parseInt($("#freeEps").value, 10) || 10;
    S.rules = F.finishRules(F.baseline(S.eps, S.show)[0], free);
    S.dec = {}; S.why = {};
    if (p === "rules") {
      S.result = { ranked: S.rules, rejected: [], proposed: S.rules.length, emptyEpisodes: [], mode: "rules" };
      S.tab = "first"; $("#step3").hidden = true; render(); return;
    }
    var a = parseInt($("#fromEp").value, 10), b = parseInt($("#toEp").value, 10);
    var runEps = S.eps.filter(function (e) { return e.episode >= a && e.episode <= b; });
    if (!runEps.length) { alertMsg("No episodes in that range."); return; }
    var cfg = { provider: p, timeoutMs: 240000 };
    if (p === "gemini") { cfg.key = $("#gemKey").value.trim(); cfg.model = $("#gemModel").value.trim() || "gemini-flash-latest"; if (!cfg.key) { alertMsg("Paste a Gemini API key, or choose Rules only."); return; } }
    if (p === "openai") { cfg.key = $("#oaKey").value.trim(); cfg.model = $("#oaModel").value.trim(); cfg.baseUrl = $("#oaBase").value.trim(); if (!cfg.key || !cfg.model) { alertMsg("Fill in the API key and the model name."); return; } }
    if (p === "replay") { if (!S.replay) { alertMsg("Pick the folder of saved answers (llm_raw) first."); return; } cfg.replay = S.replay; cfg.model = "replay of a saved run"; }
    var t0 = Date.now(), timer;
    cfg.onEvent = function (e) {
      if (e.retry) log(e.tag + ": " + e.reason + ", retrying in " + Math.round(e.wait) + " s");
      else if (e.ok) log(e.tag + ": model replied in " + e.seconds.toFixed(0) + " s");
      else log(e.tag + ": failed: " + e.error, true);
    };
    var client = F.makeClient(cfg);
    S.running = true; $("#runBtn").disabled = true; $("#step3").hidden = false; $("#results").hidden = true; $("#log").innerHTML = "";
    chips(runEps);
    $("#runStatus").textContent = "Starting…";
    timer = setInterval(function () { $("#elapsed").textContent = Math.round((Date.now() - t0) / 1000) + " s"; }, 1000);
    var pre = p === "gemini" ? checkGemini(cfg.key).then(function () { log("Key checked; calling " + cfg.model); }) : Promise.resolve();
    pre.then(function () {
      $("#runStatus").textContent = "Reading episodes and proposing clips…";
      return F.runAI({ client: client, runEps: runEps, show: S.show, allEps: S.eps, topN: parseInt($("#blindN").value, 10) || 0,
        freeEpisodes: free, parallel: p === "replay" ? 8 : parseInt($("#parallel").value, 10) || 3,
        onProgress: function (ev) {
          if (ev.state === "running") setChip(ev.episode, "run", "model is reading it");
          else if (ev.state === "done") setChip(ev.episode, "done", ev.n + " clip(s) proposed");
          else if (ev.state === "missing") setChip(ev.episode, "fail", "no saved answer");
          else setChip(ev.episode, "fail", ev.error || "failed");
          var done = document.querySelectorAll("#chips .done, #chips .fail").length;
          $("#runStatus").textContent = done < runEps.length ? "Proposed clips for " + done + " of " + runEps.length + " episodes…" : "Running the blind stranger test on the top clips…";
        } });
    }).then(function (res) {
      res.mode = p; res.model = client.stats.model_version || cfg.model; res.stats = client.stats; res.seconds = Math.round((Date.now() - t0) / 1000);
      S.result = res; S.tab = "first";
      $("#runStatus").textContent = "Done in " + res.seconds + " s: " + res.ranked.length + " clips kept, " + res.rejected.length + " thrown out.";
      render();
    }, function (e) {
      $("#runStatus").textContent = "Stopped: " + e.message; log(e.message, true);
    }).then(function () { S.running = false; $("#runBtn").disabled = false; clearInterval(timer); });
  }
  function alertMsg(t) { var m = $("#runMsg"); m.textContent = t; m.className = "msg bad"; setTimeout(function () { m.textContent = ""; }, 6000); }

  // ------------------------------------------------------------ step 4: results
  var REASONS = ["Weak hook", "Ending resolves", "Confusing cold", "Wrong cut points", "Spoils too much"];
  function strip(c) {
    var dur = S.show.eps[c.episode].duration || 1, pct = function (t) { return Math.max(0, Math.min(100, t / dur * 100)).toFixed(3) + "%"; };
    var first = c.segments[0], last = c.segments[c.segments.length - 1], h = "";
    c.segments.forEach(function (s) { h += '<span class="seg" style="left:' + pct(s.start) + ";width:" + pct(s.end - s.start) + '"></span>'; });
    h += '<span class="hookwin" style="left:' + pct(first.start) + ";width:" + pct(3) + '"></span>';
    if (!c.ends_at_episode_end) h += '<span class="withheld" style="left:' + pct(last.end) + ";width:" + pct(Math.min(6, dur - last.end)) + '"></span>';
    h += '<span class="cut" style="left:' + pct(last.end) + '"></span>';
    return '<div class="strip" aria-hidden="true"><span class="t0">0:00</span>' + h + '<span class="t1">' + Math.floor(dur / 60) + ":" + String(Math.floor(dur % 60)).padStart(2, "0") + "</span></div>";
  }
  function card(c) {
    var s = c.scores || {}, ev = c.evidence || {}, st = c.stranger, d = S.dec[c.cand_id] || "";
    var segs = c.segments.map(function (x, i) { return '<button class="copy" data-copy="Ep ' + c.episode + " " + x.start_ts + "-" + x.end_ts + '">Ep ' + c.episode + " &nbsp;" + x.start_ts + " – " + x.end_ts + "</button>"; }).join(" ");
    var flags = [];
    if (c.reveals_major_twist) flags.push('<li class="flag spoil">Reveals a major twist. Your call whether that is bait or a spoiler.</li>');
    (c.warnings || []).forEach(function (w) { flags.push('<li class="flag warn">' + esc(w) + "</li>"); });
    (c.repairs || []).forEach(function (r) { flags.push('<li class="flag fix">Adjusted: ' + esc(r) + "</li>"); });
    var score = function (k, label) { return s[k] ? '<div class="sc"><span class="n n' + s[k] + '">' + s[k] + "</span><span><b>" + label + "</b> " + esc(ev[k] || "") + "</span></div>" : ""; };
    var tr = F.clipLines(c, S.show).filter(function (l) { return l.type !== "camera"; }).map(function (l) {
      return '<li><span class="tc">' + l.start.toFixed(1) + "s</span> " + (l.type === "dialogue" ? '<span class="who">' + esc(l.speaker) + "</span> " + esc(l.text) : "<i>" + esc(l.text) + "</i>") + "</li>";
    }).join("");
    var stranger = st ? '<div class="stranger"><h4>Blind test: a separate call saw only this clip</h4><p><b>It understood:</b> ' + esc(st.what_is_happening) + "</p><p><b>It wants to know:</b> " + esc(st.open_question) +
      "</p><p><b>Confused by:</b> " + esc((st.confusing || []).join("; ") || "nothing flagged") + '</p><p class="muted">Understood ' + esc(st.standalone_score) + "/5 · would keep watching " + esc(st.keep_watching_score) + "/5</p></div>" : "";
    var reasons = d === "reject" ? '<div class="reasons">' + REASONS.map(function (r) { return '<button class="rsn' + (S.why[c.cand_id] === r ? " on" : "") + '" data-why="' + esc(r) + '" data-id="' + esc(c.cand_id) + '" aria-pressed="' + (S.why[c.cand_id] === r) + '">' + r + "</button>"; }).join("") + "</div>" : "";
    return '<article class="promo tier' + c.tier + (d ? " is-" + d : "") + '">' +
      '<header class="slate"><div class="rank"><span class="num">' + c.rank + '</span><span class="tierlbl">' + (c.tier === "R" ? "Rules" : "Tier " + c.tier) + "</span></div>" +
      '<div class="where"><div class="segs">' + segs + '</div><p class="meta">' + c.duration.toFixed(1) + " s · hook at +" + c.hook_at.toFixed(1) + " s · payoff in Ep " + c.payoff_episode + (c.in_free_window ? " (early, likely free)" : "") + "</p></div>" +
      '<div class="decide"><button class="keep" data-id="' + esc(c.cand_id) + '" aria-pressed="' + (d === "keep") + '">Keep</button><button class="reject" data-id="' + esc(c.cand_id) + '" aria-pressed="' + (d === "reject") + '">Reject</button>' + reasons + "</div></header>" +
      strip(c) +
      '<div class="beats"><div><h3 class="hk">Opens on</h3><p class="line">' + esc(c.hook_text) + '</p></div><div><h3>Cuts on</h3><p class="line">' + esc(c.cliffhanger_text) + '</p><p class="withheldtxt"><b>Withheld:</b> ' + esc((c.after_cut || []).join(" / ")) + "</p></div></div>" +
      '<p class="why">' + esc(c.why || "") + "</p>" +
      "<details><summary>Scores, blind test and full clip</summary>" +
      (s.hook ? '<div class="scores">' + score("hook", "Hook") + score("cliffhanger", "Cliffhanger") + score("standalone", "Makes sense alone (self-rated)") + "</div>" : "") +
      stranger + '<p class="muted">' + esc(c.rank_reason || "") + '</p><ol class="transcript">' + tr + "</ol></details>" +
      (flags.length ? '<ul class="flags">' + flags.join("") + "</ul>" : "") + "</article>";
  }
  function rejectedList(rs) {
    if (!rs.length) return '<p class="muted">Nothing was thrown out.</p>';
    return '<ul class="rejected">' + rs.map(function (r) { return "<li><b>Ep " + esc(r.episode || r.proposed_in_episode || "?") + "</b> " + esc(String(r.why || "").slice(0, 120)) + ' <span class="muted">' + esc(r.reject_reason) + "</span></li>"; }).join("") + "</ul>";
  }
  function render() {
    var R = S.result; if (!R) return;
    var post = R.ranked.filter(function (c) { return c.post_first; });
    var tabs = [["first", "Post first · " + post.length], ["all", "All clips · " + R.ranked.length]];
    if (R.mode !== "rules") { tabs.push(["out", "Thrown out · " + R.rejected.length]); tabs.push(["rules", "Rules-only comparison · " + S.rules.length]); }
    $("#tabs").innerHTML = tabs.map(function (t) { return '<button role="tab" data-tab="' + t[0] + '" aria-selected="' + (S.tab === t[0]) + '">' + t[1] + "</button>"; }).join("");
    var list = S.tab === "first" ? post : S.tab === "all" ? R.ranked : S.tab === "rules" ? S.rules : null;
    $("#cards").innerHTML = list ? (list.length ? list.map(card).join("") : '<p class="muted">No clips reached tier A or B.</p>') : rejectedList(R.rejected);
    var kept = Object.keys(S.dec).filter(function (k) { return S.dec[k] === "keep"; }).length, rej = Object.keys(S.dec).filter(function (k) { return S.dec[k] === "reject"; }).length;
    $("#summary").textContent = R.mode === "rules"
      ? "Rules only (no AI): " + R.ranked.length + " clips from emotion tags, action words and episode endings. Good at timing, weak at meaning; compare with an AI run."
      : R.proposed + " clips proposed by " + (R.model || R.mode) + ", " + R.ranked.length + " passed the timing checks, " + R.rejected.length + " thrown out. " + post.length + " to post first." +
        (R.emptyEpisodes.length ? " No promo-worthy moment found in Ep " + R.emptyEpisodes.join(", ") + "." : "") +
        (R.stats && R.stats.calls ? " " + R.stats.calls + " model calls, " + R.stats.retries + " retries, " + R.seconds + " s." : "");
    $("#decCount").textContent = kept + " kept · " + rej + " rejected";
    $("#results").hidden = false;
  }

  // ------------------------------------------------------------ export
  function csvOf(rows) { return rows.map(function (r) { return r.map(function (x) { return '"' + String(x == null ? "" : x).replace(/"/g, '""') + '"'; }).join(","); }).join("\n"); }
  function promosCSV() {
    var head = ["rank", "tier", "post_first", "episode", "segments", "duration_s", "hook", "cliffhanger", "why", "hook_score", "cliffhanger_score", "standalone_score", "stranger_standalone", "payoff_episode", "reveals_major_twist", "decision", "reason"];
    return csvOf([head].concat(S.result.ranked.map(function (c) {
      var s = c.scores || {};
      return [c.rank, c.tier, c.post_first, c.episode, c.segments.map(function (x) { return x.start_ts + "-" + x.end_ts; }).join(" + "), c.duration, c.hook_text, c.cliffhanger_text, c.why,
        s.hook, s.cliffhanger, s.standalone, (c.stranger || {}).standalone_score, c.payoff_episode, c.reveals_major_twist, S.dec[c.cand_id] || "", S.why[c.cand_id] || ""];
    })));
  }
  function download(name, text, type) {
    var ok = false;
    try { var a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type: type })); a.download = name; document.body.appendChild(a); a.click(); a.remove(); ok = true; } catch (e) { ok = false; }
    var m = $("#exportMsg");
    m.textContent = ok ? "Downloaded " + name + ". If nothing appeared (downloads are blocked inside claude.ai), use Copy." : "Download blocked here; use Copy.";
  }
  function copyText(text, label) {
    var m = $("#exportMsg");
    try { navigator.clipboard.writeText(text).then(function () { m.textContent = label + " copied to the clipboard."; }, function () { m.textContent = "Copy was blocked by the browser."; }); }
    catch (e) { m.textContent = "Copy was blocked by the browser."; }
  }

  // ------------------------------------------------------------ wiring
  document.addEventListener("DOMContentLoaded", function () {
    $("#folderIn").addEventListener("change", function (e) { readFiles(e.target.files); });
    $("#filesIn").addEventListener("change", function (e) { readFiles(e.target.files); });
    var dz = $("#drop");
    dz.addEventListener("dragover", function (e) { e.preventDefault(); dz.classList.add("over"); });
    dz.addEventListener("dragleave", function () { dz.classList.remove("over"); });
    dz.addEventListener("drop", function (e) { e.preventDefault(); dz.classList.remove("over"); readFiles(e.dataTransfer.files); });
    document.querySelectorAll('input[name="prov"]').forEach(function (r) { r.addEventListener("change", syncProvider); });
    ["fromEp", "toEp", "parallel"].forEach(function (id) { $("#" + id).addEventListener("input", updateRunLabel); });
    $("#checkKey").addEventListener("click", onCheckKey);
    $("#replayIn").addEventListener("change", function (e) { readReplay(e.target.files); });
    $("#step2").addEventListener("submit", function (e) { e.preventDefault(); onRun(); });
    $("#tabs").addEventListener("click", function (e) { var t = e.target.closest("[data-tab]"); if (t) { S.tab = t.getAttribute("data-tab"); render(); } });
    $("#cards").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      var id = b.getAttribute("data-id");
      if (b.classList.contains("keep") || b.classList.contains("reject")) {
        var v = b.classList.contains("keep") ? "keep" : "reject"; S.dec[id] = S.dec[id] === v ? "" : v; render();
      } else if (b.classList.contains("rsn")) { var w = b.getAttribute("data-why"); S.why[id] = S.why[id] === w ? "" : w; render(); }
      else if (b.classList.contains("copy")) { copyText(b.getAttribute("data-copy"), "Timecode"); }
    });
    $("#dlCsv").addEventListener("click", function () { if (S.result) download("promos.csv", promosCSV(), "text/csv"); });
    $("#cpCsv").addEventListener("click", function () { if (S.result) copyText(promosCSV(), "Promo list (CSV)"); });
    $("#dlJson").addEventListener("click", function () { if (S.result) download("promos.json", JSON.stringify({ model: S.result.model, promos: S.result.ranked, rejected: S.result.rejected }, null, 1), "application/json"); });
    syncProvider();
  });
})();
