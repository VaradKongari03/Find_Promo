const fs = require('fs'), path = require('path');
require(require('path').join(__dirname, '..', 'web', 'prompts.js'));
const F = require(require('path').join(__dirname, '..', 'web', 'core.js'));
const dir = process.argv[2], outDir = process.argv[3];
const files = fs.readdirSync(dir).map(n => ({ name: n, text: fs.readFileSync(path.join(dir, n), 'utf8') }));
const eps = F.loadShow(files), show = new F.Show(eps);
console.log('episodes', eps.length, 'lines', eps.reduce((a, e) => a + e.lines.length, 0));
// 1. rules parity
const [rk] = F.baseline(eps, show); F.finishRules(rk, 10);
const py = JSON.parse(fs.readFileSync(path.join(outDir, 'rules-only.json'))).promos;
const key = c => c.episode + '|' + c.segments.map(s => s.start.toFixed(2) + '-' + s.end.toFixed(2)).join('+');
const a = rk.map(key), b = py.map(key);
console.log('rules: js', a.length, 'py', b.length, 'same set', a.filter(x => b.includes(x)).length, 'same order', a.every((x, i) => x === b[i]));
// 2. AI parity via replay of saved model answers
const replay = {};
for (const f of fs.readdirSync(path.join(outDir, 'llm_raw'))) { const r = JSON.parse(fs.readFileSync(path.join(outDir, 'llm_raw', f))); replay[r.tag] = r.parsed; }
const client = F.makeClient({ provider: 'replay', replay });
F.runAI({ client, runEps: eps, show, allEps: eps, topN: 15, freeEpisodes: 10, parallel: 4 }).then(res => {
  const pyAI = JSON.parse(fs.readFileSync(path.join(outDir, 'promos.json'))).promos;
  const pyRej = JSON.parse(fs.readFileSync(path.join(outDir, 'rejected.json')));
  const sig = c => [c.cand_id, c.rank, c.tier, c.post_first, c.segments.map(s => s.start_ts + '-' + s.end_ts).join('+'), c.duration, c.hook_at, (c.stranger || {}).standalone_score, c.repairs.length, c.warnings.length].join(' ');
  const J = res.ranked.map(sig), Pp = pyAI.map(sig);
  const diffs = J.map((x, i) => x === Pp[i] ? null : ['js ' + x, 'py ' + Pp[i]]).filter(Boolean);
  console.log('AI: js kept', J.length, 'py kept', Pp.length, 'rejected js', res.rejected.length, 'py', pyRej.length, 'proposed', res.proposed);
  console.log('identical rows', J.length - diffs.length, 'of', Pp.length); diffs.slice(0, 5).forEach(d => console.log(d));
  const jr = res.rejected.map(r => r.reject_reason.split(' (')[0]).sort().join('|'), pr = pyRej.map(r => r.reject_reason.split(' (')[0]).sort().join('|');
  console.log('rejection reasons match:', jr === pr);
  console.log('post first js:', res.ranked.filter(c => c.post_first).map(c => c.cand_id).join(','));
  console.log('post first py:', pyAI.filter(c => c.post_first).map(c => c.cand_id).join(','));
});
