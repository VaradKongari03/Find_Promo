"""Stage 5 - Write outputs: promos.json, promos.csv, rejected.json and report.html (editor review sheet)."""
import csv
import html
import json
import os
from datetime import datetime

from .verify import clip_lines


def write_all(out_dir, show_name, ranked, rejected, show, meta, filename="report.html"):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "promos.json" if filename == "report.html" else filename.replace(".html", ".json")), "w", encoding="utf-8") as f:
        json.dump({"show": show_name, "meta": meta, "promos": ranked}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "rejected.json" if filename == "report.html" else filename.replace(".html", "-rejected.json")), "w", encoding="utf-8") as f:
        json.dump(rejected, f, ensure_ascii=False, indent=1)
    if filename == "report.html":
        write_csv(os.path.join(out_dir, "promos.csv"), ranked)
    with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as f:
        f.write(render(show_name, ranked, rejected, show, meta))


def seg_str(c):
    return " + ".join(f"{s['start_ts']}-{s['end_ts']}" for s in c["segments"])


def write_csv(path, ranked):
    cols = ["rank", "tier", "post_first", "episode", "segments", "duration_s", "hook", "cliffhanger", "why",
            "hook_score", "cliffhanger_score", "standalone_score", "stranger_standalone", "payoff_episode",
            "reveals_major_twist", "repairs", "warnings"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in ranked:
            s = c.get("scores", {})
            w.writerow([c["rank"], c.get("tier", ""), c.get("post_first", ""), c["episode"], seg_str(c), c["duration"],
                        c["hook_text"], c["cliffhanger_text"], c.get("why", ""), s.get("hook", ""), s.get("cliffhanger", ""),
                        s.get("standalone", ""), (c.get("stranger") or {}).get("standalone_score", ""), c["payoff_episode"],
                        c.get("reveals_major_twist", ""), " | ".join(c["repairs"]), " | ".join(c["warnings"])])


# ---------------------------------------------------------------- HTML
E = html.escape


def _strip(c, show):
    """Episode timeline: where the clip sits, hook window, cut point, withheld beat."""
    dur = show.eps[c["episode"]]["duration"] or 1
    pct = lambda t: f"{max(0, min(100, t / dur * 100)):.3f}%"
    parts = []
    for i, s in enumerate(c["segments"]):
        parts.append(f'<span class="seg" style="left:{pct(s["start"])};width:{pct(s["end"]-s["start"])}" '
                     f'title="Segment {i+1}: {s["start_ts"]} to {s["end_ts"]}"></span>')
    first, last = c["segments"][0], c["segments"][-1]
    parts.append(f'<span class="hookwin" style="left:{pct(first["start"])};width:{pct(3)}" title="First 3 seconds"></span>')
    if not c["ends_at_episode_end"]:
        parts.append(f'<span class="withheld" style="left:{pct(last["end"])};width:{pct(min(6, dur-last["end"]))}" title="What the viewer does not get to see"></span>')
    parts.append(f'<span class="cut" style="left:{pct(last["end"])}" title="Cut at {last["end_ts"]}"></span>')
    return (f'<div class="strip" role="img" aria-label="Episode {c["episode"]} timeline, clip {seg_str(c)}">'
            f'<span class="t0">0:00</span>{"".join(parts)}<span class="t1">{int(dur//60)}:{int(dur%60):02d}</span></div>')


def _card(c, show):
    s, ev = c.get("scores", {}), c.get("evidence", {})
    st = c.get("stranger")
    flags = []
    if c.get("reveals_major_twist"):
        flags.append('<li class="flag spoil">Reveals a major twist. Your call whether that is bait or a spoiler.</li>')
    flags += [f'<li class="flag warn">{E(w)}</li>' for w in c["warnings"]]
    flags += [f'<li class="flag fix">Adjusted: {E(r)}</li>' for r in c["repairs"]]
    stranger = ""
    if st:
        conf = "; ".join(st.get("confusing") or []) or "nothing flagged"
        stranger = (f'<div class="stranger"><h4>Blind test: a model that has never seen the show watched only this clip</h4>'
                    f'<p><b>It understood:</b> {E(str(st.get("what_is_happening","")))}</p>'
                    f'<p><b>It wants to know:</b> {E(str(st.get("open_question","")))}</p>'
                    f'<p><b>Confused by:</b> {E(conf)}</p>'
                    f'<p class="scoreline">Understood {st.get("standalone_score","?")}/5 · would keep watching {st.get("keep_watching_score","?")}/5</p></div>')
    transcript = "".join(
        f'<li><span class="tc">{l["start"]:.1f}s</span> '
        + (f'<span class="who">{E(l["speaker"])}</span> {E(l["text"])}' if l["type"] == "dialogue" else f'<i>{E(l["text"])}</i>')
        + "</li>" for l in clip_lines(c, show) if l["type"] != "camera")
    segtxt = "".join(f'<li><button class="copy" data-copy="Ep {c["episode"]} {sg["start_ts"]}-{sg["end_ts"]}" '
                     f'aria-label="Copy timecode for segment {i+1}">Ep {c["episode"]} &nbsp;{sg["start_ts"]} – {sg["end_ts"]}</button></li>'
                     for i, sg in enumerate(c["segments"]))
    score = lambda k, label: (f'<div class="sc"><span class="n n{s.get(k, 0)}">{s.get(k, "?")}</span>'
                              f'<span><b>{label}</b> {E(str(ev.get(k, "")))}</span></div>')
    funnel = (f'Payoff lands in Ep {c["payoff_episode"]}' + (" (early, likely free)" if c["in_free_window"] else " (deep in the show)"))
    return f'''
<article class="promo tier{c["tier"]}" data-id="{E(c["cand_id"])}" data-tier="{c["tier"]}" id="{E(c["cand_id"])}">
  <header class="slate">
    <div class="rank"><span class="num">{c["rank"]}</span><span class="tierlbl">Tier {c["tier"]}</span></div>
    <div class="where">
      <ol class="segs">{segtxt}</ol>
      <p class="meta">{c["duration"]:.1f}s · {len(c["segments"])} segment{"s" if len(c["segments"])>1 else ""} · hook at +{c["hook_at"]:.1f}s · {E(c.get("hook_type","").replace("_"," "))} · {funnel}</p>
    </div>
    <div class="decide" role="group" aria-label="Your decision">
      <button class="keep" aria-pressed="false">Keep</button>
      <button class="reject" aria-pressed="false">Reject</button>
      <select class="reason" aria-label="Reason" hidden>
        <option value="">Why reject?</option><option>Weak hook</option><option>Ending resolves</option>
        <option>Confusing without context</option><option>Wrong cut points</option><option>Spoils too much</option><option>Other</option>
      </select>
      <input class="note" placeholder="Note (optional)" aria-label="Note">
    </div>
  </header>
  {_strip(c, show)}
  <div class="beats">
    <div><h3>Opens on</h3><p class="line">{E(c["hook_text"])}</p></div>
    <div><h3>Cuts on</h3><p class="line">{E(c["cliffhanger_text"])}</p>
      <p class="withheldtxt"><b>Withheld:</b> {E(" / ".join(c["after_cut"]))}</p></div>
  </div>
  <p class="why">{E(c.get("why",""))}</p>
  <details><summary>Scores, blind test and full clip</summary>
    {f'<div class="scores">{score("hook","Hook")}{score("cliffhanger","Cliffhanger")}{score("standalone","Makes sense alone (self-rated)")}</div>' if s else ""}
    {f'<p class="leaves"><b>Leaves the viewer asking:</b> {E(str(c.get("open_question","")))}<br><b>A stranger lacks:</b> {E(str(c.get("context_a_stranger_lacks","")))}</p>' if s else ""}
    {stranger}
    <p class="rr">{E(c.get("rank_reason",""))}</p>
    <ol class="transcript">{transcript}</ol>
  </details>
  {f'<ul class="flags">{"".join(flags)}</ul>' if flags else ""}
</article>'''


def render(show_name, ranked, rejected, show, meta):
    post = [c for c in ranked if c.get("post_first")]
    rest = [c for c in ranked if not c.get("post_first")]
    rej = "".join(f'<li><b>{"Ep " + str(r.get("episode") or r.get("proposed_in_episode","?"))}</b> '
                  f'{E(str(r.get("why",""))[:120])} <span class="rr">{E(r["reject_reason"])}</span></li>' for r in rejected)
    summary = (f'{meta.get("proposed", len(ranked)+len(rejected))} clips proposed across {meta.get("episodes_run", len(show.eps))} episodes. '
               f'{len(ranked)} passed the timing checks, {len(rejected)} were thrown out (listed at the bottom with reasons). '
               f'{len(post)} are marked to post first.')
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Promo shortlist: {E(show_name)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Courier+Prime:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
:root{{--bg:#E9EDF0;--paper:#FFFFFF;--ink:#16202A;--muted:#5A6672;--rule:#C9D1D8;--seg:#2440C9;--hook:#C0183F;--cut:#16202A;--withheld:#F2B705;--a:#14663D;--b:#3D4A57;--c:#8A939C}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 "Atkinson Hyperlegible",system-ui,sans-serif;font-variant-numeric:tabular-nums}}
.wrap{{max-width:1080px;margin:0 auto;padding:40px 24px 80px}}
h1{{font:700 2.25rem/1.15 "Courier Prime",ui-monospace,monospace;margin:0 0 .4rem;letter-spacing:-.01em}}
.lede{{max-width:70ch;color:var(--muted);margin:0 0 1.5rem}}
.toolbar{{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:0 0 2rem;position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:2;border-bottom:1px solid var(--rule)}}
.toolbar button,.toolbar label{{font:inherit;font-size:.9rem}}
.toolbar .count{{margin-left:auto;color:var(--muted);font-size:.9rem}}
button{{cursor:pointer}}
.btn{{border:1px solid var(--ink);background:var(--paper);color:var(--ink);padding:6px 12px;border-radius:4px}}
.btn.primary{{background:var(--ink);color:#fff}}
h2{{font-size:1.25rem;margin:2.5rem 0 .25rem}}
h2+p{{margin:0 0 1rem;color:var(--muted);max-width:70ch}}
.promo{{background:var(--paper);border-left:6px solid var(--c);padding:18px 22px 16px;margin:0 0 14px;border-radius:2px 8px 8px 2px}}
.promo.tierA{{border-left-color:var(--a)}} .promo.tierB{{border-left-color:var(--b)}}
.promo.is-kept{{outline:2px solid var(--a)}} .promo.is-rejected{{opacity:.55}}
.slate{{display:grid;grid-template-columns:72px 1fr auto;gap:18px;align-items:start}}
.rank .num{{display:block;font:700 2rem/1 "Courier Prime",monospace}}
.rank .tierlbl{{font-size:.8rem;color:var(--muted)}}
.tierA .tierlbl{{color:var(--a);font-weight:700}}
.segs{{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:6px}}
.copy{{font:700 1.05rem "Atkinson Hyperlegible",sans-serif;border:0;background:#EEF1FB;color:var(--seg);padding:3px 8px;border-radius:4px}}
.copy:hover{{background:#DDE3F8}} .copy.done::after{{content:" copied";font-weight:400;font-size:.8rem}}
.meta{{margin:.35rem 0 0;color:var(--muted);font-size:.9rem}}
.decide{{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;max-width:260px}}
.decide button{{font:inherit;font-size:.9rem;border:1px solid var(--rule);background:#fff;padding:5px 12px;border-radius:4px}}
.decide .keep[aria-pressed=true]{{background:var(--a);color:#fff;border-color:var(--a)}}
.decide .reject[aria-pressed=true]{{background:var(--hook);color:#fff;border-color:var(--hook)}}
.decide select,.decide input{{font:inherit;font-size:.85rem;padding:4px 6px;border:1px solid var(--rule);border-radius:4px;width:100%}}
.strip{{position:relative;height:30px;margin:16px 0 14px;background:repeating-linear-gradient(90deg,#F1F3F5 0 6px,#E6E9EC 6px 7px);border-radius:3px}}
.strip .seg{{position:absolute;top:4px;bottom:4px;background:var(--seg);border-radius:2px}}
.strip .hookwin{{position:absolute;top:0;bottom:0;background:var(--hook);opacity:.9;border-radius:2px 0 0 2px;min-width:3px}}
.strip .withheld{{position:absolute;top:8px;bottom:8px;background:repeating-linear-gradient(45deg,var(--withheld) 0 4px,transparent 4px 8px)}}
.strip .cut{{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--cut)}}
.strip .t0,.strip .t1{{position:absolute;top:100%;font-size:.7rem;color:var(--muted)}} .strip .t1{{right:0}}
.beats{{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:8px}}
h3{{font-size:.85rem;margin:0 0 .2rem;color:var(--muted);font-weight:700}}
.beats div:first-child h3{{color:var(--hook)}}
.line{{font:1.02rem/1.45 "Courier Prime",ui-monospace,monospace;margin:0}}
.withheldtxt{{font-size:.88rem;color:var(--muted);margin:.5rem 0 0;padding-left:10px;border-left:3px solid var(--withheld)}}
.why{{margin:14px 0 6px;max-width:75ch}}
details summary{{cursor:pointer;color:var(--seg);font-size:.9rem}}
.scores{{display:grid;gap:8px;margin:12px 0}}
.sc{{display:grid;grid-template-columns:30px 1fr;gap:10px;font-size:.92rem}}
.n{{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:#EEF0F2;font-weight:700}}
.n5,.n4{{background:#D6EBDD;color:var(--a)}} .n1,.n2{{background:#F8DCE2;color:var(--hook)}}
.stranger{{background:#F5F7F9;padding:10px 14px;border-radius:6px;font-size:.92rem;margin:10px 0}}
.stranger h4{{margin:0 0 .3rem;font-size:.88rem}} .stranger p{{margin:.15rem 0}}
.leaves,.rr{{font-size:.88rem;color:var(--muted)}}
.transcript{{list-style:none;padding:0;font:.9rem/1.5 "Courier Prime",monospace;max-height:320px;overflow:auto;border-top:1px solid var(--rule);padding-top:8px}}
.transcript .tc{{color:var(--muted);display:inline-block;width:56px}} .transcript .who{{font-weight:700}}
.flags{{list-style:none;padding:0;margin:10px 0 0;display:flex;flex-direction:column;gap:4px}}
.flag{{font-size:.85rem;padding:3px 10px;border-radius:4px}}
.flag.spoil{{background:#FFF4CC}} .flag.warn{{background:#FBE6EA}} .flag.fix{{background:#EEF1FB;color:#33406B}}
.rejected{{background:var(--paper);padding:14px 22px;border-radius:8px}}
.rejected li{{margin:.4rem 0;font-size:.92rem}}
:focus-visible{{outline:3px solid var(--seg);outline-offset:2px}}
.legend{{display:flex;flex-wrap:wrap;gap:18px;font-size:.85rem;color:var(--muted);margin:0 0 1rem}}
.legend i{{display:inline-block;width:18px;height:10px;vertical-align:middle;margin-right:6px;border-radius:2px}}
@media (max-width:760px){{.slate{{grid-template-columns:52px 1fr}}.decide{{grid-column:1/-1;justify-content:flex-start;max-width:none}}.beats{{grid-template-columns:1fr}}}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style></head><body><div class="wrap">
<h1>{E(show_name)}</h1>
<p class="lede">{E(summary)} Every clip below is a suggestion. Watch it before posting. Timecodes come straight from the screenplay; if the final edit drifted, nudge them.</p>
<div class="legend"><span><i style="background:var(--seg)"></i>Clip</span><span><i style="background:var(--hook)"></i>First 3 seconds</span><span><i style="background:repeating-linear-gradient(45deg,var(--withheld) 0 4px,transparent 4px 8px)"></i>What the viewer doesn't get to see</span><span><i style="background:var(--cut);width:3px"></i>Cut</span></div>
<div class="toolbar">
  <label><input type="checkbox" id="hideRejected"> Hide rejected</label>
  <label><input type="checkbox" id="onlyA"> Tier A only</label>
  <button class="btn primary" id="export">Export my decisions (CSV)</button>
  <span class="count" id="count"></span>
</div>
<h2>Post these first</h2>
<p>The strongest clip from each of up to 10 different episodes, ordered by tier, then by how early in the show the viewer gets the payoff, then by score.</p>
{"".join(_card(c, show) for c in post) or "<p>No clip reached tier A or B.</p>"}
<h2>Other candidates</h2>
<p>Also passed the timing checks. Weaker, later in the show, or a second clip from an episode already above.</p>
{"".join(_card(c, show) for c in rest) or "<p>None.</p>"}
<h2>Thrown out by the tool</h2>
<p>Clips that broke a hard rule (length, hook timing, line IDs). Shown so you can see what the tool skipped.</p>
<details class="rejected"><summary>{len(rejected)} thrown out</summary><ul>{rej or "<li>None.</li>"}</ul></details>
<p class="rr" style="margin-top:2rem">Generated {E(meta.get("generated",""))} · model {E(meta.get("model",""))} · {E(meta.get("note",""))}</p>
</div>
<script>
const KEY="promo-decisions:"+{json.dumps(show_name + "|" + meta.get("model",""))};
let D={{}};try{{D=JSON.parse(localStorage.getItem(KEY)||"{{}}")}}catch(e){{}}
const save=()=>{{try{{localStorage.setItem(KEY,JSON.stringify(D))}}catch(e){{}}}};
function paint(card){{const d=D[card.dataset.id]||{{}};
  card.classList.toggle("is-kept",d.s==="keep");card.classList.toggle("is-rejected",d.s==="reject");
  card.querySelector(".keep").setAttribute("aria-pressed",d.s==="keep");card.querySelector(".reject").setAttribute("aria-pressed",d.s==="reject");
  const r=card.querySelector(".reason");r.hidden=d.s!=="reject";r.value=d.r||"";card.querySelector(".note").value=d.n||"";}}
function count(){{const v=Object.values(D);document.getElementById("count").textContent=v.filter(x=>x.s==="keep").length+" kept · "+v.filter(x=>x.s==="reject").length+" rejected";
  const hr=document.getElementById("hideRejected").checked,oa=document.getElementById("onlyA").checked;
  document.querySelectorAll(".promo").forEach(c=>{{c.hidden=(hr&&(D[c.dataset.id]||{{}}).s==="reject")||(oa&&c.dataset.tier!=="A")}})}}
document.querySelectorAll(".promo").forEach(card=>{{const id=card.dataset.id;paint(card);
  card.querySelector(".keep").onclick=()=>{{D[id]={{...(D[id]||{{}}),s:(D[id]||{{}}).s==="keep"?"":"keep"}};save();paint(card);count()}};
  card.querySelector(".reject").onclick=()=>{{D[id]={{...(D[id]||{{}}),s:(D[id]||{{}}).s==="reject"?"":"reject"}};save();paint(card);count();if(D[id].s==="reject")card.querySelector(".reason").focus()}};
  card.querySelector(".reason").onchange=e=>{{D[id]={{...(D[id]||{{}}),r:e.target.value}};save()}};
  card.querySelector(".note").oninput=e=>{{D[id]={{...(D[id]||{{}}),n:e.target.value}};save()}};}});
document.querySelectorAll(".copy").forEach(b=>b.onclick=()=>{{navigator.clipboard&&navigator.clipboard.writeText(b.dataset.copy).then(()=>{{b.classList.add("done");setTimeout(()=>b.classList.remove("done"),1200)}})}});
["hideRejected","onlyA"].forEach(i=>document.getElementById(i).onchange=count);
document.getElementById("export").onclick=()=>{{const rows=[["promo","rank","episode","timecodes","decision","reason","note"]];
  document.querySelectorAll(".promo").forEach(c=>{{const d=D[c.dataset.id]||{{}};rows.push([c.dataset.id,c.querySelector(".num").textContent,c.querySelector(".copy").dataset.copy.split(" ")[1],
  [...c.querySelectorAll(".copy")].map(b=>b.dataset.copy).join(" + "),d.s||"",d.r||"",d.n||""])}});
  const csv=rows.map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(",")).join("\\n");
  const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([csv],{{type:"text/csv"}}));a.download="promo-decisions.csv";a.click()}};
count();
</script></body></html>'''
