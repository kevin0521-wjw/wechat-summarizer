// 全链路冒烟：网页版各接口是否都正常（不依赖微信、不依赖 AI key）
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn, spawnSync } from 'node:child_process';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = process.env.PROBE_BASE || 'http://127.0.0.1:8090';
const PORT = 9341;

function cleanEnv() {
  const e = { ...process.env };
  for (const k of Object.keys(e)) if (/^(http|https|all|no)_proxy$/i.test(k)) delete e[k];
  return e;
}
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'wms-smoke-'));
const child = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--user-data-dir=' + profile, '--remote-debugging-port=' + PORT, 'about:blank'],
  { detached: true, stdio: 'ignore', env: cleanEnv() });
child.unref();
const sleep = ms => new Promise(r => setTimeout(r, ms));

let id = 0;
function mk(ws) {
  const p = new Map();
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && p.has(m.id)) { p.get(m.id)(m); p.delete(m.id); }
  });
  return (method, params = {}) => new Promise((res, rej) => {
    const i = ++id;
    const t = setTimeout(() => { p.delete(i); rej(new Error(method + ' timeout')); }, 20000);
    p.set(i, m => { clearTimeout(t); res(m.result ?? m.error); });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
}

const results = [];
const check = (n, ok, d = '') => { results.push({ n, ok, d }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  — ' + d : ''}`); };

(async () => {
  let wsUrl;
  for (let i = 0; i < 30 && !wsUrl; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      wsUrl = l.find(t => t.type === 'page')?.webSocketDebuggerUrl;
    } catch {}
    if (!wsUrl) await sleep(500);
  }
  const ws = new WebSocket(wsUrl);
  await new Promise(r => ws.addEventListener('open', r, { once: true }));
  const send = mk(ws);
  await send('Page.enable');
  await send('Runtime.enable');
  send('Page.navigate', { url: BASE + '/' });

  let ready = false;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    try {
      const e = await send('Runtime.evaluate', {
        expression: "document.readyState", returnByValue: true,
      });
      if (e?.result?.value === 'complete') { ready = true; break; }
    } catch {}
  }
  check('首页加载完成', ready);

  // 同源 fetch 各接口（页面内 fetch 带 cookie/同源，最真实）
  const api = async (url, opts) => {
    const expr = `(async()=>{try{
      const r = await fetch(${JSON.stringify(url)}, ${JSON.stringify(opts || {})});
      const t = await r.text();
      return JSON.stringify({status:r.status, body:t.slice(0,300)});
    }catch(e){return JSON.stringify({status:0, err:String(e)})}})()`;
    const e = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    try { return JSON.parse(e?.result?.value || '{}'); } catch { return { status: 0, raw: e?.result?.value }; }
  };

  const h = await api('/api/health');
  check('GET /api/health', h.status === 200 && /"ok":true/.test(h.body || ''), h.body?.slice(0, 60));

  const st = await api('/api/stats');
  check('GET /api/stats', st.status === 200, `status=${st.status}`);

  const cfg = await api('/api/config');
  check('GET /api/config 返回掩码不含明文 key',
    cfg.status === 200 && /api_key_masked/.test(cfg.body || '') && !/sk-[a-z0-9]{20,}/i.test(cfg.body || ''),
    cfg.body?.slice(0, 90));

  const sel = await api('/api/selection_config');
  check('GET /api/selection_config', sel.status === 200 && /hotkey/.test(sel.body || ''), sel.body?.slice(0, 70));

  const sums = await api('/api/summaries');
  check('GET /api/summaries', sums.status === 200);

  const msgs = await api('/api/messages?since=0&limit=5');
  check('GET /api/messages', msgs.status === 200 && /messages/.test(msgs.body || ''), msgs.body?.slice(0, 60));

  const man = await api('/manifest.json');
  check('GET /manifest.json (PWA)', man.status === 200);

  const sw = await api('/sw.js');
  check('GET /sw.js (PWA)', sw.status === 200);

  // 界面关键区块可见
  const ui = await send('Runtime.evaluate', {
    expression: `JSON.stringify(['stat-total','feed','summaries','sel-input','btn-analyze','btn-settings']
      .map(id=>({id, ok:!!document.getElementById(id)})))`,
    returnByValue: true,
  });
  const uiList = JSON.parse(ui?.result?.value || '[]');
  check('界面关键区块齐全', uiList.length === 6 && uiList.every(x => x.ok),
    uiList.filter(x => !x.ok).map(x => x.id).join(',') || 'all 6');

  // 轮询是否在跑（3 秒后再取一次 stats，看有没有报错）
  await sleep(3500);
  const st2 = await api('/api/stats');
  check('轮询 3.5s 后接口仍正常', st2.status === 200);

  console.log('\n' + '='.repeat(50));
  const bad = results.filter(r => !r.ok);
  console.log(`结果: ${results.length - bad.length}/${results.length} 通过`);
  if (bad.length) bad.forEach(b => console.log('  失败: ' + b.n + '  ' + b.d));

  try { await send('Browser.close'); } catch {}
  ws.close();
  spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch {}
  process.exit(bad.length ? 1 : 0);
})().catch(e => {
  console.error('失败:', e.message);
  spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  process.exit(2);
});
